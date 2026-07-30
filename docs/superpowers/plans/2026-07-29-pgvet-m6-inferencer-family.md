# pgvet M6 (part 1) — Constraint-Inference Family Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add a `pgvet infer` capability that inspects a live database and proposes constraints the data already obeys but the schema never declared (not-null, unique, enum, foreign key) as reviewable `ALTER TABLE … ADD CONSTRAINT` DDL.

**Architecture:** A new `Inferencer` plugin family (family `INFERENCER`, already in the enum) runs over a `SchemaContext(schema, sampler)`. A `Sampler` wraps the connection and is the single home of all inference SQL (data-stat methods + a hybrid full-scan/sample rule), so inferencers stay pure and testable with a fake Sampler. Introspection is extended to capture existing constraints/FKs so inferencers skip already-declared ones. The whole suite stays DB-free (fake Sampler + fake connection + fixtures).

**Tech Stack:** Python 3.11+, uv, `psycopg` (only via the existing `Connection`), `pytest`. No new dependencies.

**Prerequisite:** MVP + M4 + M5 are on `main` (91 tests). This plan builds on these existing symbols (do not redefine):
- `pgvet.core.schemamodel`: `Column(name, data_type, nullable, default)`, `Index`, `Constraint(name, kind, columns, definition)`, `Table(schema, name, columns, indexes, constraints)` with `column(name)` + `has_unique_on(cols)`, `SchemaModel(tables)` with `table(name)`.
- `pgvet.core.introspect`: `COLUMNS_SQL`, `INDEXES_SQL`, `introspect(conn)` (currently populates columns + indexes only).
- `pgvet.core.connection.Connection`: `fetch_all(sql, params=None)`, `fetch_one(sql, params=None)`.
- `pgvet.core.findings`: `Finding`, `Severity`, `Location`, `Suggestion`.
- `pgvet.core.registry.Registry`: `register`, `advisors` property, `discover`, `load_builtins`, `ADVISOR_GROUP`.
- `pgvet.core.session.Session(conn, registry, ...)`.
- `pgvet.plugins.base`: `Family` (ADVISOR/INFERENCER/DRIFT), `Advisor`, `PlanContext`.
- `pgvet.cli`: `_registry()`, `report_from_plan_file`, `_finding_dict`, `_render_text`, `main`.

**Conventions:** run tests with `uv run pytest`; end every commit body with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`; commit only the files each task lists.

**Design spec:** `docs/superpowers/specs/2026-07-29-pgvet-m6-inferencer-design.md`.

---

## File Structure

```
src/pgvet/
  core/
    introspect.py     # Task 1: + CONSTRAINTS_SQL, populate Table.constraints
    sampler.py        # Task 2: Stat + Sampler (all inference SQL; hybrid + cache)
    registry.py       # Task 4: family-routed register + inferencers property + INFERENCER_GROUP
                      # Task 10: load_builtins also registers inferencer builtins
    session.py        # Task 11: Session.infer()
  plugins/
    base.py           # Task 3: + Inferencer + SchemaContext
    inferencers/
      __init__.py     # Task 9: register_builtins
      not_null.py     # Task 5
      unique.py       # Task 6
      enum.py         # Task 7
      fk_overlap.py   # Task 8
  cli.py              # Task 12: `pgvet infer`
tests/
  unit/inferencer_helpers.py, test_inferencer_base.py, test_infer_not_null.py,
       test_infer_unique.py, test_infer_enum.py, test_infer_fk_overlap.py, test_inferencer_builtins.py
  engine/test_introspect_constraints.py, test_sampler.py, test_session_infer.py, test_cli_infer.py
```

**Task order note (dependency):** the inferencer builtins package (Task 9) is created BEFORE `Registry.load_builtins` is wired to load it (Task 10), so existing CLI tests that call `_registry()` never hit a missing import.

---

## Task 1: Extend introspection to capture constraints/FKs

**Files:** Modify `src/pgvet/core/introspect.py`; Test `tests/engine/test_introspect_constraints.py`.

- [ ] **Step 1: Write the failing test** — `tests/engine/test_introspect_constraints.py`:
```python
from pgvet.core.introspect import introspect, COLUMNS_SQL, INDEXES_SQL, CONSTRAINTS_SQL


class _FakeConn:
    def __init__(self, columns, indexes, constraints):
        self._columns, self._indexes, self._constraints = columns, indexes, constraints
    def fetch_all(self, sql, params=None):
        if sql == COLUMNS_SQL: return self._columns
        if sql == INDEXES_SQL: return self._indexes
        if sql == CONSTRAINTS_SQL: return self._constraints
        raise AssertionError(f"unexpected sql: {sql!r}")


def test_introspect_populates_constraints():
    columns = [{"table_schema": "public", "table_name": "orders", "column_name": "id",
                "data_type": "integer", "is_nullable": "NO", "column_default": None}]
    constraints = [
        {"table_name": "orders", "constraint_name": "orders_pkey", "kind": "p",
         "column_names": ["id"], "definition": "PRIMARY KEY (id)"},
        {"table_name": "orders", "constraint_name": "orders_customer_fkey", "kind": "f",
         "column_names": ["customer_id"], "definition": "FOREIGN KEY (customer_id) REFERENCES customers(id)"},
    ]
    schema = introspect(_FakeConn(columns, [], constraints))
    orders = schema.table("orders")
    kinds = {c.kind for c in orders.constraints}
    assert kinds == {"p", "f"}
    pk = next(c for c in orders.constraints if c.kind == "p")
    assert pk.columns == ["id"]
```

- [ ] **Step 2: Run, expect FAIL** (`ImportError: cannot import name 'CONSTRAINTS_SQL'`): `uv run pytest tests/engine/test_introspect_constraints.py -v`

- [ ] **Step 3: Implement** — in `src/pgvet/core/introspect.py`, add the constant and extend `introspect`.

Add after `INDEXES_SQL`:
```python
CONSTRAINTS_SQL = """
SELECT t.relname AS table_name,
       c.conname AS constraint_name,
       c.contype AS kind,
       array_agg(a.attname ORDER BY k.ord) AS column_names,
       pg_get_constraintdef(c.oid) AS definition
FROM pg_constraint c
JOIN pg_class t ON t.oid = c.conrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord) ON true
JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND c.contype IN ('p', 'f', 'u', 'c')
GROUP BY t.relname, c.conname, c.contype, c.oid
ORDER BY t.relname, c.conname
"""
```

Add the `Constraint` import at the top (extend the existing import line):
```python
from pgvet.core.schemamodel import Column, Constraint, Index, SchemaModel, Table
```

At the end of `introspect`, before `return`, add a constraints pass (mirrors the indexes pass):
```python
    for row in conn.fetch_all(CONSTRAINTS_SQL):
        table = tables.get(row["table_name"])
        if table is None:
            continue
        table.constraints.append(
            Constraint(
                name=row["constraint_name"],
                kind=row["kind"],
                columns=list(row["column_names"]),
                definition=row["definition"],
            )
        )
```

- [ ] **Step 4: Run, expect PASS**: `uv run pytest tests/engine/test_introspect_constraints.py -v`
Then confirm no regression to the existing introspection test: `uv run pytest tests/engine/test_introspect.py -q`
*(Note: the existing `test_introspect.py` fake connection only handles COLUMNS_SQL/INDEXES_SQL and will now be asked for CONSTRAINTS_SQL — update that fake to return `[]` for CONSTRAINTS_SQL if the test fails. Add this branch to its `_FakeConn.fetch_all`: `if sql == CONSTRAINTS_SQL: return []`, and import CONSTRAINTS_SQL there.)*

- [ ] **Step 5: Commit**
```bash
git add src/pgvet/core/introspect.py tests/engine/test_introspect_constraints.py tests/engine/test_introspect.py
git commit -m "feat(core): introspect PK/FK/unique/check constraints into SchemaModel"
```

---

## Task 2: `Stat` + `Sampler` (the inference-SQL home)

**Files:** Create `src/pgvet/core/sampler.py`; Test `tests/engine/test_sampler.py`.

- [ ] **Step 1: Write the failing test** — `tests/engine/test_sampler.py`:
```python
from pgvet.core.sampler import Sampler, Stat


class _FakeConn:
    """Answers by inspecting SQL keywords. Records the last SQL executed."""
    def __init__(self, n=100, nulls=0, distinct=0, values=None, ratio=0.0):
        self._n, self._nulls, self._distinct = n, nulls, distinct
        self._values = values or []
        self._ratio = ratio
        self.last_sql = None
    def fetch_one(self, sql, params=None):
        self.last_sql = sql
        if "LEFT JOIN" in sql:            return {"ratio": self._ratio}
        if "IS NULL" in sql:              return {"n": self._nulls}
        if "count(DISTINCT" in sql:       return {"n": self._distinct}
        if "count(*)" in sql:             return {"n": self._n}
        raise AssertionError(sql)
    def fetch_all(self, sql, params=None):
        self.last_sql = sql
        return [{"v": v} for v in self._values]


def test_row_count_is_exact_and_cached():
    conn = _FakeConn(n=42)
    s = Sampler(conn)
    assert s.row_count("orders") == Stat(value=42, sampled=False, sample_size=42)
    # cached: a second call doesn't depend on conn returning again
    assert s.row_count("orders").value == 42


def test_null_and_distinct_full_scan_under_threshold():
    conn = _FakeConn(n=100, nulls=0, distinct=100)
    s = Sampler(conn, full_scan_threshold=1000)
    nc = s.null_count("orders", "status")
    dc = s.distinct_count("orders", "status")
    assert nc.value == 0 and nc.sampled is False and nc.sample_size == 100
    assert dc.value == 100 and dc.sampled is False


def test_sampled_above_threshold_uses_tablesample():
    conn = _FakeConn(n=1_000_000, nulls=0)
    s = Sampler(conn, full_scan_threshold=10)
    nc = s.null_count("orders", "status")
    assert nc.sampled is True
    assert "TABLESAMPLE" in conn.last_sql
    assert nc.sample_size <= 1_000_000


def test_distinct_values_and_orphan_ratio():
    conn = _FakeConn(values=["open", "paid"], ratio=0.0)
    s = Sampler(conn, full_scan_threshold=1000)
    assert s.distinct_values("orders", "status", 12) == ["open", "paid"]
    r = s.orphan_ratio("orders", "customer_id", "customers", "id")
    assert r.value == 0.0
```

- [ ] **Step 2: Run, expect FAIL** (`ModuleNotFoundError`): `uv run pytest tests/engine/test_sampler.py -v`

- [ ] **Step 3: Implement** — `src/pgvet/core/sampler.py`:
```python
"""The single home of constraint-inference SQL. `Sampler` wraps a Connection with
data-stat methods and owns the hybrid full-scan-vs-sample rule, so inferencers call
these methods instead of writing SQL and stay pure + testable with a fake Sampler."""

from __future__ import annotations

from dataclasses import dataclass

FULL_SCAN_THRESHOLD = 100_000
SAMPLE_ROWS = 20_000


@dataclass(frozen=True)
class Stat:
    value: float
    sampled: bool
    sample_size: int


def _q(ident: str) -> str:
    """Double-quote a catalog identifier (names come from introspection, not users)."""
    return '"' + ident.replace('"', '""') + '"'


class Sampler:
    def __init__(self, conn, full_scan_threshold: int = FULL_SCAN_THRESHOLD) -> None:
        self._conn = conn
        self._threshold = full_scan_threshold
        self._row_counts: dict[str, int] = {}

    def row_count(self, table: str) -> Stat:
        if table not in self._row_counts:
            row = self._conn.fetch_one(f"SELECT count(*) AS n FROM {_q(table)}")
            self._row_counts[table] = int(row["n"])
        n = self._row_counts[table]
        return Stat(value=n, sampled=False, sample_size=n)

    def _source(self, table: str) -> tuple[str, bool, int]:
        """(SQL table source, sampled, sample_size) applying the hybrid rule."""
        n = int(self.row_count(table).value)
        if n < self._threshold:
            return _q(table), False, n
        frac = min(100.0, max(0.01, SAMPLE_ROWS / n * 100.0))
        return f"{_q(table)} TABLESAMPLE SYSTEM ({frac})", True, min(n, SAMPLE_ROWS)

    def null_count(self, table: str, column: str) -> Stat:
        src, sampled, size = self._source(table)
        row = self._conn.fetch_one(f"SELECT count(*) AS n FROM {src} WHERE {_q(column)} IS NULL")
        return Stat(value=int(row["n"]), sampled=sampled, sample_size=size)

    def distinct_count(self, table: str, column: str) -> Stat:
        src, sampled, size = self._source(table)
        row = self._conn.fetch_one(f"SELECT count(DISTINCT {_q(column)}) AS n FROM {src}")
        return Stat(value=int(row["n"]), sampled=sampled, sample_size=size)

    def distinct_values(self, table: str, column: str, limit: int) -> list[str]:
        src, _, _ = self._source(table)
        rows = self._conn.fetch_all(f"SELECT DISTINCT {_q(column)} AS v FROM {src} LIMIT {int(limit)}")
        return [r["v"] for r in rows]

    def orphan_ratio(self, child_table: str, child_col: str,
                     parent_table: str, parent_col: str) -> Stat:
        src, sampled, size = self._source(child_table)
        sql = (
            f"SELECT count(*) FILTER (WHERE p.{_q(parent_col)} IS NULL)::float "
            f"/ NULLIF(count(*), 0) AS ratio "
            f"FROM {src} c LEFT JOIN {_q(parent_table)} p "
            f"ON c.{_q(child_col)} = p.{_q(parent_col)} "
            f"WHERE c.{_q(child_col)} IS NOT NULL"
        )
        row = self._conn.fetch_one(sql)
        ratio = row["ratio"]
        return Stat(value=float(ratio if ratio is not None else 0.0), sampled=sampled, sample_size=size)
```

- [ ] **Step 4: Run, expect PASS (4 tests)**: `uv run pytest tests/engine/test_sampler.py -v`

- [ ] **Step 5: Commit**
```bash
git add src/pgvet/core/sampler.py tests/engine/test_sampler.py
git commit -m "feat(core): add Sampler (inference-SQL home) with hybrid sampling"
```

---

## Task 3: `Inferencer` base + `SchemaContext`

**Files:** Modify `src/pgvet/plugins/base.py`; Test `tests/unit/test_inferencer_base.py`.

- [ ] **Step 1: Write the failing test** — `tests/unit/test_inferencer_base.py`:
```python
from pgvet.plugins.base import Family, SchemaContext, Inferencer
from pgvet.core.findings import Finding, Severity
from pgvet.core.schemamodel import SchemaModel


class _Fires(Inferencer):
    id = "inferencer.test"
    name = "Test inferencer"
    def run(self, ctx):
        yield Finding(self.id, Severity.SUGGEST, "hi", "d")


def test_inferencer_family_and_applies_to():
    inf = _Fires()
    assert inf.family == Family.INFERENCER
    ctx = SchemaContext(schema=SchemaModel(), sampler=object())
    assert inf.applies_to(ctx) is True
    assert [f.plugin_id for f in inf.run(ctx)] == ["inferencer.test"]
```

- [ ] **Step 2: Run, expect FAIL** (`ImportError: cannot import name 'SchemaContext'`): `uv run pytest tests/unit/test_inferencer_base.py -v`

- [ ] **Step 3: Implement** — append to `src/pgvet/plugins/base.py` (keep the existing `Family`, `PlanContext`, `Advisor`):
```python
from pgvet.core.schemamodel import SchemaModel  # noqa: E402  (already imported above; keep single import at top)
from pgvet.core.sampler import Sampler


@dataclass
class SchemaContext:
    schema: SchemaModel
    sampler: Sampler


class Inferencer(ABC):
    """A function over a SchemaContext (schema + a Sampler for live data stats)
    that yields Findings carrying candidate DDL."""

    id: str
    name: str
    family: Family = Family.INFERENCER

    def applies_to(self, ctx: SchemaContext) -> bool:  # noqa: ARG002
        return True

    @abstractmethod
    def run(self, ctx: SchemaContext) -> Iterable[Finding]:
        ...
```
*Note: `SchemaModel` is already imported at the top of base.py for `PlanContext`; do NOT add a duplicate import — only add `from pgvet.core.sampler import Sampler`. The `abc`/`dataclass`/`Iterable`/`Family` names are already imported at the top.*

- [ ] **Step 4: Run, expect PASS**: `uv run pytest tests/unit/test_inferencer_base.py -v`
Then confirm no import cycle: `uv run python -c "import pgvet.plugins.base, pgvet.core.session; print('ok')"`

- [ ] **Step 5: Commit**
```bash
git add src/pgvet/plugins/base.py tests/unit/test_inferencer_base.py
git commit -m "feat(plugins): add Inferencer base + SchemaContext"
```

---

## Task 4: Registry — family routing + inferencer discovery

Generalize the registry so one `register` routes by `plugin.family`, add an `inferencers` property and an `INFERENCER_GROUP`. Do NOT change `load_builtins` yet (Task 10). Existing advisor behavior/tests must stay green.

**Files:** Modify `src/pgvet/core/registry.py`; Test `tests/unit/test_registry_inferencers.py`.

- [ ] **Step 1: Write the failing test** — `tests/unit/test_registry_inferencers.py`:
```python
from pgvet.core.registry import Registry, INFERENCER_GROUP
from pgvet.plugins.base import Advisor, Inferencer
from pgvet.core.findings import Finding, Severity


class _A(Advisor):
    id = "advisor.a"; name = "A"
    def run(self, ctx): return []


class _I(Inferencer):
    id = "inferencer.i"; name = "I"
    def run(self, ctx): return []


def test_register_routes_by_family():
    reg = Registry()
    reg.register(_A())
    reg.register(_I())
    assert [a.id for a in reg.advisors] == ["advisor.a"]
    assert [i.id for i in reg.inferencers] == ["inferencer.i"]


def test_inferencer_group_constant():
    assert INFERENCER_GROUP == "pgvet.inferencers"
```

- [ ] **Step 2: Run, expect FAIL** (`ImportError: cannot import name 'INFERENCER_GROUP'`): `uv run pytest tests/unit/test_registry_inferencers.py -v`

- [ ] **Step 3: Implement** — rewrite the storage in `src/pgvet/core/registry.py` to a single id-keyed dict with family-filtered properties. Replace the class body (keep the module docstring, logger, and `ADVISOR_GROUP`; add `INFERENCER_GROUP`):
```python
from pgvet.plugins.base import Family

ADVISOR_GROUP = "pgvet.advisors"
INFERENCER_GROUP = "pgvet.inferencers"


class Registry:
    def __init__(self) -> None:
        self._plugins: dict[str, object] = {}

    def register(self, plugin) -> None:
        if plugin.id in self._plugins:
            raise ValueError(f"duplicate plugin id: {plugin.id}")
        self._plugins[plugin.id] = plugin

    @property
    def advisors(self) -> list:
        return [p for p in self._plugins.values() if p.family == Family.ADVISOR]

    @property
    def inferencers(self) -> list:
        return [p for p in self._plugins.values() if p.family == Family.INFERENCER]

    def discover(self, entry_points=None, group: str = ADVISOR_GROUP) -> None:
        if entry_points is None:
            entry_points = _entry_points(group=group)
        for ep in entry_points:
            try:
                register_fn = ep.load()
                register_fn(self)
            except Exception as exc:  # noqa: BLE001 — isolation is the whole point
                log.warning("skipping plugin entry point %r: %s", ep.name, exc)

    def load_builtins(self) -> None:
        """Register the advisors shipped in pgvet.plugins.advisors."""
        from pgvet.plugins.advisors import register_builtins
        register_builtins(self)
```
*Keep the existing top imports (`logging`, `entry_points as _entry_points`) and the `log = logging.getLogger("pgvet.registry")` line. Remove the old `from pgvet.plugins.base import Advisor` if it's now unused, or keep it — `Family` is what's needed.*

- [ ] **Step 4: Run, expect PASS + no advisor regressions**:
```bash
uv run pytest tests/unit/test_registry_inferencers.py tests/unit/test_registry.py -v
uv run pytest -q
```
Expected: all green (existing `test_registry.py` advisor tests still pass — `advisors` now filters by family but advisors have `family == ADVISOR`).

- [ ] **Step 5: Commit**
```bash
git add src/pgvet/core/registry.py tests/unit/test_registry_inferencers.py
git commit -m "feat(core): registry routes plugins by family; add inferencer group"
```

---

## Task 5: `not_null` inferencer (+ shared test helper)

**Files:** Create `src/pgvet/plugins/inferencers/not_null.py`, `src/pgvet/plugins/inferencers/__init__.py` (EMPTY for now — populated in Task 9), `tests/unit/inferencer_helpers.py`; Test `tests/unit/test_infer_not_null.py`.

- [ ] **Step 1: Create the shared helper** — `tests/unit/inferencer_helpers.py`:
```python
from pgvet.core.sampler import Stat
from pgvet.core.schemamodel import SchemaModel
from pgvet.plugins.base import SchemaContext


class FakeSampler:
    def __init__(self, rows=0, nulls=None, distincts=None, values=None, orphans=None, sampled=False):
        self._rows = rows
        self._nulls = nulls or {}
        self._distincts = distincts or {}
        self._values = values or {}
        self._orphans = orphans or {}
        self._sampled = sampled

    def row_count(self, table):
        return Stat(self._rows, False, self._rows)

    def null_count(self, table, column):
        return Stat(self._nulls.get((table, column), 0), self._sampled, self._rows)

    def distinct_count(self, table, column):
        return Stat(self._distincts.get((table, column), 0), self._sampled, self._rows)

    def distinct_values(self, table, column, limit):
        return self._values.get((table, column), [])[:limit]

    def orphan_ratio(self, child_table, child_col, parent_table, parent_col):
        return Stat(self._orphans.get((child_table, child_col), 0.0), self._sampled, self._rows)


def sctx(schema, sampler) -> SchemaContext:
    return SchemaContext(schema=schema, sampler=sampler)
```

- [ ] **Step 2: Write the failing test** — `tests/unit/test_infer_not_null.py`:
```python
from pgvet.plugins.inferencers.not_null import NotNullInferencer
from pgvet.core.schemamodel import Column, Table, SchemaModel
from pgvet.core.findings import Severity
from tests.unit.inferencer_helpers import FakeSampler, sctx


def _schema():
    return SchemaModel(tables=[Table(schema="public", name="orders", columns=[
        Column("id", "integer", nullable=False, default=None),      # already NOT NULL
        Column("status", "text", nullable=True, default=None),      # nullable, never null
    ])])


def test_flags_never_null_nullable_column():
    sampler = FakeSampler(rows=1000, nulls={("orders", "status"): 0})
    findings = list(NotNullInferencer().run(sctx(_schema(), sampler)))
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == Severity.SUGGEST
    assert f.location.identifier == "orders.status"
    assert f.suggestion.sql == 'ALTER TABLE "orders" ALTER COLUMN "status" SET NOT NULL'


def test_ignores_column_with_nulls():
    sampler = FakeSampler(rows=1000, nulls={("orders", "status"): 3})
    assert list(NotNullInferencer().run(sctx(_schema(), sampler))) == []


def test_ignores_already_not_null_column():
    # only "status" is nullable; "id" is NOT NULL and must never be flagged
    sampler = FakeSampler(rows=1000, nulls={("orders", "status"): 0, ("orders", "id"): 0})
    ids = [f.location.identifier for f in NotNullInferencer().run(sctx(_schema(), sampler))]
    assert "orders.id" not in ids
```

- [ ] **Step 3: Run, expect FAIL** (`ModuleNotFoundError`): `uv run pytest tests/unit/test_infer_not_null.py -v`

- [ ] **Step 4: Implement** — create empty `src/pgvet/plugins/inferencers/__init__.py`, then `src/pgvet/plugins/inferencers/not_null.py`:
```python
"""Infer NOT NULL: a nullable column that is never actually null."""

from __future__ import annotations

from typing import Iterable

from pgvet.core.findings import Finding, Location, Severity, Suggestion
from pgvet.plugins.base import Inferencer, SchemaContext


class NotNullInferencer(Inferencer):
    id = "inferencer.not_null"
    name = "Undeclared NOT NULL"

    def run(self, ctx: SchemaContext) -> Iterable[Finding]:
        for table in ctx.schema.tables:
            for col in table.columns:
                if not col.nullable:
                    continue
                if ctx.sampler.row_count(table.name).value == 0:
                    continue
                nulls = ctx.sampler.null_count(table.name, col.name)
                if nulls.value != 0:
                    continue
                where = f"{table.name}.{col.name}"
                yield Finding(
                    plugin_id=self.id,
                    severity=Severity.INFO if nulls.sampled else Severity.SUGGEST,
                    title=f"`{where}` is never null but is declared nullable",
                    detail=(f"No NULLs found in {int(nulls.sample_size)} rows"
                            f"{' (sampled)' if nulls.sampled else ''}. "
                            f"Consider declaring `{where}` NOT NULL."),
                    location=Location(kind="column", identifier=where),
                    evidence={"sampled": nulls.sampled, "sample_size": nulls.sample_size},
                    suggestion=Suggestion(
                        kind="ddl",
                        sql=f'ALTER TABLE "{table.name}" ALTER COLUMN "{col.name}" SET NOT NULL',
                    ),
                )
```

- [ ] **Step 5: Run, expect PASS (3 tests)**: `uv run pytest tests/unit/test_infer_not_null.py -v`

- [ ] **Step 6: Commit**
```bash
git add src/pgvet/plugins/inferencers/__init__.py src/pgvet/plugins/inferencers/not_null.py tests/unit/inferencer_helpers.py tests/unit/test_infer_not_null.py
git commit -m "feat(inferencers): add not-null inferencer"
```

---

## Task 6: `unique` inferencer

**Files:** Create `src/pgvet/plugins/inferencers/unique.py`; Test `tests/unit/test_infer_unique.py`.

- [ ] **Step 1: Write the failing test** — `tests/unit/test_infer_unique.py`:
```python
from pgvet.plugins.inferencers.unique import UniqueInferencer
from pgvet.core.schemamodel import Column, Index, Table, SchemaModel
from tests.unit.inferencer_helpers import FakeSampler, sctx


def _schema():
    return SchemaModel(tables=[Table(schema="public", name="users", columns=[
        Column("email", "text", nullable=False, default=None),
    ])])


def test_flags_effectively_unique_column():
    sampler = FakeSampler(rows=500, distincts={("users", "email"): 500})
    findings = list(UniqueInferencer().run(sctx(_schema(), sampler)))
    assert len(findings) == 1
    assert findings[0].suggestion.sql == 'ALTER TABLE "users" ADD CONSTRAINT users_email_key UNIQUE ("email")'


def test_ignores_column_with_duplicates():
    sampler = FakeSampler(rows=500, distincts={("users", "email"): 480})
    assert list(UniqueInferencer().run(sctx(_schema(), sampler))) == []


def test_ignores_already_unique_column():
    schema = SchemaModel(tables=[Table(schema="public", name="users",
        columns=[Column("email", "text", False, None)],
        indexes=[Index(name="users_email_idx", columns=["email"], unique=True, predicate=None)])])
    sampler = FakeSampler(rows=500, distincts={("users", "email"): 500})
    assert list(UniqueInferencer().run(sctx(schema, sampler))) == []
```

- [ ] **Step 2: Run, expect FAIL** (`ModuleNotFoundError`): `uv run pytest tests/unit/test_infer_unique.py -v`

- [ ] **Step 3: Implement** — `src/pgvet/plugins/inferencers/unique.py`:
```python
"""Infer UNIQUE: a non-unique column whose scanned values are all distinct."""

from __future__ import annotations

from typing import Iterable

from pgvet.core.findings import Finding, Location, Severity, Suggestion
from pgvet.plugins.base import Inferencer, SchemaContext


class UniqueInferencer(Inferencer):
    id = "inferencer.unique"
    name = "Undeclared UNIQUE"

    def run(self, ctx: SchemaContext) -> Iterable[Finding]:
        for table in ctx.schema.tables:
            for col in table.columns:
                if table.has_unique_on([col.name]):
                    continue
                distinct = ctx.sampler.distinct_count(table.name, col.name)
                scanned = distinct.sample_size
                if scanned == 0 or distinct.value != scanned:
                    continue  # empty, or duplicates found in the scanned rows
                where = f"{table.name}.{col.name}"
                yield Finding(
                    plugin_id=self.id,
                    severity=Severity.INFO if distinct.sampled else Severity.SUGGEST,
                    title=f"`{where}` looks unique but has no unique constraint",
                    detail=(f"All {int(scanned)} scanned values are distinct"
                            f"{' (sampled)' if distinct.sampled else ''}. "
                            f"Consider a UNIQUE constraint on `{where}`."),
                    location=Location(kind="column", identifier=where),
                    evidence={"sampled": distinct.sampled, "sample_size": distinct.sample_size},
                    suggestion=Suggestion(
                        kind="ddl",
                        sql=f'ALTER TABLE "{table.name}" ADD CONSTRAINT {table.name}_{col.name}_key UNIQUE ("{col.name}")',
                    ),
                )
```

- [ ] **Step 4: Run, expect PASS (3 tests)**: `uv run pytest tests/unit/test_infer_unique.py -v`

- [ ] **Step 5: Commit**
```bash
git add src/pgvet/plugins/inferencers/unique.py tests/unit/test_infer_unique.py
git commit -m "feat(inferencers): add unique inferencer"
```

---

## Task 7: `enum` inferencer

**Files:** Create `src/pgvet/plugins/inferencers/enum.py`; Test `tests/unit/test_infer_enum.py`.

- [ ] **Step 1: Write the failing test** — `tests/unit/test_infer_enum.py`:
```python
from pgvet.plugins.inferencers.enum import EnumInferencer, ENUM_MAX
from pgvet.core.schemamodel import Column, Table, SchemaModel
from tests.unit.inferencer_helpers import FakeSampler, sctx


def _schema():
    return SchemaModel(tables=[Table(schema="public", name="orders", columns=[
        Column("status", "text", nullable=False, default=None),
        Column("note", "text", nullable=True, default=None),
    ])])


def test_flags_low_cardinality_text_column():
    sampler = FakeSampler(
        rows=10000,
        distincts={("orders", "status"): 4, ("orders", "note"): 9000},
        values={("orders", "status"): ["open", "paid", "shipped", "cancelled"]},
    )
    findings = list(EnumInferencer().run(sctx(_schema(), sampler)))
    ids = [f.location.identifier for f in findings]
    assert "orders.status" in ids
    assert "orders.note" not in ids
    status = next(f for f in findings if f.location.identifier == "orders.status")
    assert status.suggestion.sql == (
        'ALTER TABLE "orders" ADD CONSTRAINT orders_status_check '
        "CHECK (\"status\" IN ('open', 'paid', 'shipped', 'cancelled'))"
    )


def test_ignores_high_cardinality():
    sampler = FakeSampler(rows=10000, distincts={("orders", "status"): ENUM_MAX + 1, ("orders", "note"): 9000})
    assert list(EnumInferencer().run(sctx(_schema(), sampler))) == []
```

- [ ] **Step 2: Run, expect FAIL** (`ModuleNotFoundError`): `uv run pytest tests/unit/test_infer_enum.py -v`

- [ ] **Step 3: Implement** — `src/pgvet/plugins/inferencers/enum.py`:
```python
"""Infer an enum-like CHECK: a text column with very few distinct values."""

from __future__ import annotations

from typing import Iterable

from pgvet.core.findings import Finding, Location, Severity, Suggestion
from pgvet.plugins.base import Inferencer, SchemaContext

ENUM_MAX = 12  # at most this many distinct values to be considered an enum


def _is_text(data_type: str) -> bool:
    return data_type == "text" or "character" in data_type


class EnumInferencer(Inferencer):
    id = "inferencer.enum"
    name = "Low-cardinality column (candidate enum)"

    def run(self, ctx: SchemaContext) -> Iterable[Finding]:
        for table in ctx.schema.tables:
            for col in table.columns:
                if not _is_text(col.data_type):
                    continue
                distinct = ctx.sampler.distinct_count(table.name, col.name)
                if distinct.value == 0 or distinct.value > ENUM_MAX:
                    continue
                if distinct.value >= distinct.sample_size:
                    continue  # not "many rows, few values" — no repetition
                values = ctx.sampler.distinct_values(table.name, col.name, ENUM_MAX)
                if not values:
                    continue
                in_list = ", ".join("'" + str(v).replace("'", "''") + "'" for v in values)
                where = f"{table.name}.{col.name}"
                yield Finding(
                    plugin_id=self.id,
                    severity=Severity.INFO if distinct.sampled else Severity.SUGGEST,
                    title=f"`{where}` has only {int(distinct.value)} distinct values (candidate enum)",
                    detail=(f"Values seen: {in_list}"
                            f"{' (sampled)' if distinct.sampled else ''}. "
                            f"A CHECK constraint would enforce the allowed set."),
                    location=Location(kind="column", identifier=where),
                    evidence={"distinct": distinct.value, "sampled": distinct.sampled,
                              "values": values},
                    suggestion=Suggestion(
                        kind="ddl",
                        sql=(f'ALTER TABLE "{table.name}" ADD CONSTRAINT {table.name}_{col.name}_check '
                             f'CHECK ("{col.name}" IN ({in_list}))'),
                    ),
                )
```

- [ ] **Step 4: Run, expect PASS (2 tests)**: `uv run pytest tests/unit/test_infer_enum.py -v`

- [ ] **Step 5: Commit**
```bash
git add src/pgvet/plugins/inferencers/enum.py tests/unit/test_infer_enum.py
git commit -m "feat(inferencers): add enum (low-cardinality CHECK) inferencer"
```

---

## Task 8: `fk_overlap` inferencer

**Files:** Create `src/pgvet/plugins/inferencers/fk_overlap.py`; Test `tests/unit/test_infer_fk_overlap.py`.

- [ ] **Step 1: Write the failing test** — `tests/unit/test_infer_fk_overlap.py`:
```python
from pgvet.plugins.inferencers.fk_overlap import FkOverlapInferencer
from pgvet.core.schemamodel import Column, Constraint, Table, SchemaModel
from tests.unit.inferencer_helpers import FakeSampler, sctx


def _schema(with_fk=False):
    orders_constraints = []
    if with_fk:
        orders_constraints.append(Constraint("orders_customer_id_fkey", "f", ["customer_id"],
                                             "FOREIGN KEY (customer_id) REFERENCES customers(id)"))
    return SchemaModel(tables=[
        Table(schema="public", name="orders",
              columns=[Column("customer_id", "integer", False, None)],
              constraints=orders_constraints),
        Table(schema="public", name="customers",
              columns=[Column("id", "integer", False, None)],
              constraints=[Constraint("customers_pkey", "p", ["id"], "PRIMARY KEY (id)")]),
    ])


def test_flags_undeclared_fk_when_no_orphans():
    sampler = FakeSampler(rows=1000, orphans={("orders", "customer_id"): 0.0})
    findings = list(FkOverlapInferencer().run(sctx(_schema(), sampler)))
    assert len(findings) == 1
    assert findings[0].suggestion.sql == (
        'ALTER TABLE "orders" ADD CONSTRAINT orders_customer_id_fkey '
        'FOREIGN KEY ("customer_id") REFERENCES "customers" ("id")'
    )


def test_ignores_when_orphans_exist():
    sampler = FakeSampler(rows=1000, orphans={("orders", "customer_id"): 0.02})
    assert list(FkOverlapInferencer().run(sctx(_schema(), sampler))) == []


def test_ignores_when_fk_already_declared():
    sampler = FakeSampler(rows=1000, orphans={("orders", "customer_id"): 0.0})
    assert list(FkOverlapInferencer().run(sctx(_schema(with_fk=True), sampler))) == []
```

- [ ] **Step 2: Run, expect FAIL** (`ModuleNotFoundError`): `uv run pytest tests/unit/test_infer_fk_overlap.py -v`

- [ ] **Step 3: Implement** — `src/pgvet/plugins/inferencers/fk_overlap.py`:
```python
"""Infer a foreign key: a *_id column whose values are fully contained in a
naming-matched parent table's single-column primary key."""

from __future__ import annotations

from typing import Iterable

from pgvet.core.findings import Finding, Location, Severity, Suggestion
from pgvet.core.schemamodel import SchemaModel
from pgvet.plugins.base import Inferencer, SchemaContext

ORPHAN_TOLERANCE = 0.0  # require zero orphaned child values


class FkOverlapInferencer(Inferencer):
    id = "inferencer.fk_overlap"
    name = "Undeclared foreign key"

    def run(self, ctx: SchemaContext) -> Iterable[Finding]:
        for table in ctx.schema.tables:
            declared_fk = {tuple(c.columns) for c in table.constraints if c.kind == "f"}
            for col in table.columns:
                if not col.name.endswith("_id") or (col.name,) in declared_fk:
                    continue
                parent = self._find_parent(ctx.schema, col.name)
                if parent is None:
                    continue
                ptable, pcol = parent
                if ctx.sampler.row_count(table.name).value == 0:
                    continue
                ratio = ctx.sampler.orphan_ratio(table.name, col.name, ptable, pcol)
                if ratio.value > ORPHAN_TOLERANCE:
                    continue
                where = f"{table.name}.{col.name}"
                yield Finding(
                    plugin_id=self.id,
                    severity=Severity.INFO if ratio.sampled else Severity.SUGGEST,
                    title=f"`{where}` looks like an undeclared foreign key to `{ptable}`",
                    detail=(f"Every non-null `{col.name}` value matches a `{ptable}.{pcol}`"
                            f"{' (sampled)' if ratio.sampled else ''}. "
                            f"A FOREIGN KEY would enforce referential integrity."),
                    location=Location(kind="column", identifier=where),
                    evidence={"orphan_ratio": ratio.value, "sampled": ratio.sampled,
                              "parent": f"{ptable}.{pcol}"},
                    suggestion=Suggestion(
                        kind="ddl",
                        sql=(f'ALTER TABLE "{table.name}" ADD CONSTRAINT {table.name}_{col.name}_fkey '
                             f'FOREIGN KEY ("{col.name}") REFERENCES "{ptable}" ("{pcol}")'),
                    ),
                )

    def _find_parent(self, schema: SchemaModel, col_name: str):
        """customer_id -> the 'customer' or 'customers' table with a single-col PK."""
        prefix = col_name[:-3]  # strip trailing "_id"
        for cand in (prefix, prefix + "s"):
            t = schema.table(cand)
            if t is None:
                continue
            pk = next((c for c in t.constraints if c.kind == "p" and len(c.columns) == 1), None)
            if pk is not None:
                return (t.name, pk.columns[0])
        return None
```

- [ ] **Step 4: Run, expect PASS (3 tests)**: `uv run pytest tests/unit/test_infer_fk_overlap.py -v`

- [ ] **Step 5: Commit**
```bash
git add src/pgvet/plugins/inferencers/fk_overlap.py tests/unit/test_infer_fk_overlap.py
git commit -m "feat(inferencers): add fk-by-overlap inferencer"
```

---

## Task 9: Register builtin inferencers

**Files:** Modify `src/pgvet/plugins/inferencers/__init__.py`; Test `tests/unit/test_inferencer_builtins.py`.

- [ ] **Step 1: Write the failing test** — `tests/unit/test_inferencer_builtins.py`:
```python
from pgvet.core.registry import Registry
from pgvet.plugins.inferencers import register_builtins


def test_register_builtins_adds_all_inferencers():
    reg = Registry()
    register_builtins(reg)
    assert {i.id for i in reg.inferencers} == {
        "inferencer.not_null",
        "inferencer.unique",
        "inferencer.enum",
        "inferencer.fk_overlap",
    }
```

- [ ] **Step 2: Run, expect FAIL** (`ImportError: cannot import name 'register_builtins'`): `uv run pytest tests/unit/test_inferencer_builtins.py -v`

- [ ] **Step 3: Implement** — `src/pgvet/plugins/inferencers/__init__.py`:
```python
"""Builtin inferencer registration (used by Registry.load_builtins)."""

from pgvet.plugins.inferencers.enum import EnumInferencer
from pgvet.plugins.inferencers.fk_overlap import FkOverlapInferencer
from pgvet.plugins.inferencers.not_null import NotNullInferencer
from pgvet.plugins.inferencers.unique import UniqueInferencer

_BUILTINS = [NotNullInferencer, UniqueInferencer, EnumInferencer, FkOverlapInferencer]


def register_builtins(registry) -> None:
    for inferencer_cls in _BUILTINS:
        registry.register(inferencer_cls())
```

- [ ] **Step 4: Run, expect PASS**: `uv run pytest tests/unit/test_inferencer_builtins.py -v`

- [ ] **Step 5: Commit**
```bash
git add src/pgvet/plugins/inferencers/__init__.py tests/unit/test_inferencer_builtins.py
git commit -m "feat(inferencers): register builtin inferencer family"
```

---

## Task 10: Wire inferencer builtins into `Registry.load_builtins`

Now that the package exists, `load_builtins` registers both families. This is safe: every existing caller of `load_builtins` (the CLI `_registry()`) will now also get inferencers, and the package is present.

**Files:** Modify `src/pgvet/core/registry.py`; Test `tests/unit/test_registry_load_both.py`.

- [ ] **Step 1: Write the failing test** — `tests/unit/test_registry_load_both.py`:
```python
from pgvet.core.registry import Registry


def test_load_builtins_registers_advisors_and_inferencers():
    reg = Registry()
    reg.load_builtins()
    assert len(reg.advisors) == 5        # MVP advisor family
    assert len(reg.inferencers) == 4     # M6 inferencer family
```

- [ ] **Step 2: Run, expect FAIL** (only 0 inferencers registered): `uv run pytest tests/unit/test_registry_load_both.py -v`

- [ ] **Step 3: Implement** — update `load_builtins` in `src/pgvet/core/registry.py`:
```python
    def load_builtins(self) -> None:
        """Register the advisors and inferencers shipped with pgvet."""
        from pgvet.plugins.advisors import register_builtins as register_advisors
        from pgvet.plugins.inferencers import register_builtins as register_inferencers
        register_advisors(self)
        register_inferencers(self)
```

- [ ] **Step 4: Run, expect PASS + full suite green**:
```bash
uv run pytest tests/unit/test_registry_load_both.py -v
uv run pytest -q
```
Expected: all green — existing CLI tests (`test_cli_report.py`, `test_cli_plugins.py`) still pass; `pgvet plugins` now also lists inferencers (that's fine — `plugins_listing` iterates `reg.advisors`, so its output is unchanged; inferencers show only via `pgvet infer`).

- [ ] **Step 5: Commit**
```bash
git add src/pgvet/core/registry.py tests/unit/test_registry_load_both.py
git commit -m "feat(core): load builtin inferencers in Registry.load_builtins"
```

---

## Task 11: `Session.infer()`

**Files:** Modify `src/pgvet/core/session.py`; Test `tests/engine/test_session_infer.py`.

- [ ] **Step 1: Write the failing test** — `tests/engine/test_session_infer.py`:
```python
from pgvet.core.session import Session
from pgvet.core.registry import Registry
from pgvet.plugins.base import Inferencer, SchemaContext
from pgvet.core.findings import Finding, Severity
from pgvet.core.schemamodel import SchemaModel


class _Fires(Inferencer):
    id = "inferencer.fires"; name = "F"
    def run(self, ctx):
        yield Finding(self.id, Severity.SUGGEST, "found", "d")


class _Boom(Inferencer):
    id = "inferencer.boom"; name = "B"
    def run(self, ctx):
        raise RuntimeError("kaboom")


def test_infer_runs_inferencers_and_isolates_errors(monkeypatch):
    reg = Registry()
    reg.register(_Fires())
    reg.register(_Boom())
    sess = Session(conn=object(), registry=reg)
    monkeypatch.setattr("pgvet.core.session.introspect", lambda conn: SchemaModel())
    monkeypatch.setattr("pgvet.core.session.Sampler", lambda conn: object())

    findings = sess.infer()
    ids = {f.plugin_id for f in findings}
    assert "inferencer.fires" in ids
    boom = [f for f in findings if f.plugin_id == "inferencer.boom"]
    assert len(boom) == 1 and boom[0].severity == Severity.WARN
```

- [ ] **Step 2: Run, expect FAIL** (`AttributeError: 'Session' object has no attribute 'infer'`): `uv run pytest tests/engine/test_session_infer.py -v`

- [ ] **Step 3: Implement** — in `src/pgvet/core/session.py`:

(a) extend imports (add `Sampler` and `SchemaContext`):
```python
from pgvet.core.sampler import Sampler
from pgvet.plugins.base import PlanContext, SchemaContext
```
(b) add the method to `Session` (mirrors `analyze`'s isolation):
```python
    def infer(self) -> list[Finding]:
        schema = introspect(self._conn)
        ctx = SchemaContext(schema=schema, sampler=Sampler(self._conn))
        findings: list[Finding] = []
        for inferencer in self._registry.inferencers:
            try:
                findings.extend(inferencer.run(ctx))
            except Exception as exc:  # noqa: BLE001 — isolate one bad plugin
                log.warning("inferencer %s failed: %s", inferencer.id, exc)
                findings.append(
                    Finding(
                        plugin_id=inferencer.id,
                        severity=Severity.WARN,
                        title=f"Inferencer {inferencer.id} failed",
                        detail=str(exc),
                    )
                )
        return findings
```

- [ ] **Step 4: Run, expect PASS + full suite green**: `uv run pytest tests/engine/test_session_infer.py -v && uv run pytest -q`

- [ ] **Step 5: Commit**
```bash
git add src/pgvet/core/session.py tests/engine/test_session_infer.py
git commit -m "feat(core): add Session.infer() (run inferencers with isolation)"
```

---

## Task 12: `pgvet infer` CLI

**Files:** Modify `src/pgvet/cli.py`; Test `tests/engine/test_cli_infer.py`.

- [ ] **Step 1: Write the failing test** — `tests/engine/test_cli_infer.py`:
```python
import json

from pgvet.cli import infer_report


class _FakeSession:
    def __init__(self, conn, registry):
        pass
    def infer(self):
        from pgvet.core.findings import Finding, Severity, Location, Suggestion
        return [Finding("inferencer.not_null", Severity.SUGGEST,
                        "`orders.status` is never null but is declared nullable", "d",
                        location=Location("column", "orders.status"),
                        suggestion=Suggestion(kind="ddl",
                            sql='ALTER TABLE "orders" ALTER COLUMN "status" SET NOT NULL'))]


def test_infer_report_text(monkeypatch):
    monkeypatch.setattr("pgvet.cli.Session", _FakeSession)
    monkeypatch.setattr("pgvet.cli.Connection", type("C", (), {"connect": staticmethod(lambda s: type("Conn", (), {"close": lambda self: None})())}))
    monkeypatch.setattr("pgvet.cli.Settings", type("S", (), {"from_env": staticmethod(lambda: object())}))
    out = infer_report(fmt="text")
    assert "orders.status" in out
    assert "SET NOT NULL" in out


def test_infer_report_json(monkeypatch):
    monkeypatch.setattr("pgvet.cli.Session", _FakeSession)
    monkeypatch.setattr("pgvet.cli.Connection", type("C", (), {"connect": staticmethod(lambda s: type("Conn", (), {"close": lambda self: None})())}))
    monkeypatch.setattr("pgvet.cli.Settings", type("S", (), {"from_env": staticmethod(lambda: object())}))
    data = json.loads(infer_report(fmt="json"))
    assert data["findings"][0]["suggestion"]["sql"].endswith("SET NOT NULL")
```

- [ ] **Step 2: Run, expect FAIL** (`ImportError: cannot import name 'infer_report'`): `uv run pytest tests/engine/test_cli_infer.py -v`

- [ ] **Step 3: Implement** — in `src/pgvet/cli.py`:

(a) add module-level imports so the monkeypatch targets exist (near the top, alongside existing imports):
```python
from pgvet.config import Settings
from pgvet.core.connection import Connection
```
*(These were previously imported lazily inside `launch_tui`. Move them to module scope so `pgvet.cli.Settings`/`pgvet.cli.Connection` are patchable and reusable. Leave the lazy imports inside `launch_tui` removed to avoid shadowing — or keep them; module-scope is what the tests patch.)*

(b) add `infer_report` and `_render_ddl` (reusing `_finding_dict`):
```python
def infer_report(fmt: str = "text") -> str:
    conn = Connection.connect(Settings.from_env())
    try:
        findings = Session(conn=conn, registry=_registry()).infer()
    finally:
        conn.close()
    if fmt == "json":
        return json.dumps({"findings": [_finding_dict(f) for f in findings]}, indent=2)
    if not findings:
        return "No candidate constraints found."
    lines = []
    for f in findings:
        lines.append(f"{f.severity.value}: {f.title}")
        if f.suggestion and f.suggestion.sql:
            lines.append(f"    {f.suggestion.sql};")
    return "\n".join(lines)
```

(c) register the subcommand in `main` (add near the other `sub.add_parser(...)` calls):
```python
    inf = sub.add_parser("infer", help="infer undeclared constraints from live data")
    inf.add_argument("--format", default="text", choices=["text", "json"])
```
(d) add the dispatch branch inside the `try` in `main` (alongside report/plugins/tui):
```python
        if args.command == "infer":
            print(infer_report(fmt=args.format))
            return 0
```

- [ ] **Step 4: Run, expect PASS + full suite + import check**:
```bash
uv run pytest tests/engine/test_cli_infer.py -v
uv run pytest -q
uv run python -c "import pgvet.cli; print('ok')"
uv run pgvet plugins   # still works; unchanged output
```

- [ ] **Step 5: Commit**
```bash
git add src/pgvet/cli.py tests/engine/test_cli_infer.py
git commit -m "feat(cli): add 'pgvet infer' (candidate-constraint DDL from live data)"
```

---

## Live-DB validation (deferred — run on the connected machine)

The suite above is fully offline (fake Sampler + fake connection). On a real dev Postgres
with the seeded demo DB (`docs/examples/seed.sql`):
1. `export DATABASE_URL=...`; `uv run pgvet infer` (and `--format json`).
2. Expect candidates such as: `orders.status` / `note` as enums or NOT NULL where the seed
   data has no nulls; `orders.customer_id` as an undeclared FK to `customers(id)` (the seed
   creates the FK, so drop it first to see the inference, or point at a schema without it).
3. Verify the CONSTRAINTS_SQL introspection returns real rows and inferencers correctly
   SKIP already-declared constraints.
4. Verify `TABLESAMPLE SYSTEM` works and sampled findings are labelled — force sampling by
   running with a low threshold against a >100k-row table (`orders` has 100k).
5. Sanity-check that pgvet issued only SELECTs (no ALTER ran) under the read-only session.

---

## Self-Review

**Spec coverage (design doc §3–§10):**
- §3 architecture (Inferencer family, SchemaContext, Sampler, extended introspection) → Tasks 1–4. ✔
- §4 components table → introspect (1), sampler (2), base (3), registry (4,10), inferencers (5–9), session (11), cli (12). ✔
- §5 Sampler interface (Stat + row_count/null_count/distinct_count/distinct_values/orphan_ratio + hybrid + cache) → Task 2. ✔
- §6 Core-4 inferencers with the exact DDL shapes → Tasks 5–8. ✔
- §7 engine + CLI (`Session.infer`, `pgvet infer` text/json, reuse renderer) → Tasks 11–12. ✔
- §8 safety (read-only, human-gated DDL, no auto-apply) → Sampler only SELECTs; CLI only prints DDL; verified in live-validation step 5. ✔
- §9 testing (fake Sampler, fake conn, DB-free) → every inferencer + sampler + session test is offline. ✔
- §10 scope ladder → Tasks 1–12 = the first cut; composite/CHECK/functional-deps/migrations/TUI/drift explicitly deferred (not tasked). ✔

**Placeholder scan:** No TBD/TODO/"handle edge cases". Every code step is complete. The one conditional (Task 1 Step 4 updating the existing introspect fake) is explicit with the exact branch to add.

**Type consistency:** `Stat(value, sampled, sample_size)`; `Sampler(conn, full_scan_threshold=100_000)` with `row_count/null_count/distinct_count(table[,column])->Stat`, `distinct_values(table,column,limit)->list`, `orphan_ratio(child_table,child_col,parent_table,parent_col)->Stat`; `SchemaContext(schema, sampler)`; `Inferencer.run(ctx)->Iterable[Finding]` with `family=INFERENCER`; `Registry.register` (family-routed), `.advisors`, `.inferencers`, `INFERENCER_GROUP`, `load_builtins` (both); `Session.infer()->list[Finding]`; `register_builtins(registry)`; `infer_report(fmt)`; DDL strings quote identifiers with double-quotes and match the inferencer tests exactly. Consistent across tasks. ✔

**Dependency-order check:** Task 9 (inferencers package) precedes Task 10 (load_builtins wiring), so existing `_registry()`/CLI tests never hit a missing import. Task 4 leaves `load_builtins` untouched. ✔
