# pgvet M4 — Plan Diff + History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add plan-to-plan diffing and a local plan-history store so pgvet can answer "did this change help?" and "when did this query get slow?".

**Architecture:** A pure `diff_plans(before, after)` over the existing `PlanTree` model produces a `PlanDiff`; a `History` class persists each run to a local SQLite file keyed by a normalized-query hash + git ref; `Session.run_query` optionally loads the previous plan, computes the diff, and records the new run. The TUI gains a diff pane. Everything stays offline-testable (fixtures + a temp SQLite file); no live DB is required to build or test M4.

**Tech Stack:** Python 3.11+, uv, stdlib `sqlite3`, `sqlglot` (query normalization — already a declared dependency), `rich`/`textual` (diff pane), `pytest`.

**Prerequisite:** MVP (M0–M3) is merged to `main`. This plan builds on these existing symbols (do not redefine them):
- `pgvet.core.planmodel`: `NodeType`, `PlanNode` (fields `node_type, relation, estimated_rows, actual_rows, estimated_cost, actual_time_ms, loops, children, raw`; props `total_actual_rows`, `misestimate_factor`), `PlanTree` (fields `root, planning_time_ms, execution_time_ms, query`; method `walk()` = pre-order).
- `pgvet.core.explain`: `parse_explain_json(payload)`, `run_explain(conn, sql, analyze=True)`.
- `pgvet.core.session`: `Session(conn, registry)`, `RunResult(query, plan, findings)`, `run_query(sql)`.
- `pgvet.plugins.base`: `PlanContext(plan, query, schema, previous=None)` — the `previous` slot is reserved for this milestone.
- `pgvet.tui.app`: `PgvetApp(analyze_query)`; `pgvet.tui.panels` has `render_plan_tree`, `render_findings`.

**Conventions:** run tests with `uv run pytest`; end every commit body with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`; commit only the files listed per task.

---

## File Structure

```
src/pgvet/
  core/
    planmodel.py        # Task 1: add to_payload() to PlanTree
    plandiff.py         # Task 2 (NodeDelta, PlanDiff, DiffVerdict) + Task 3 (diff_plans)
    queryhash.py        # Task 4: normalized-query hashing (sqlglot) + git ref
    session.py          # Task 6: wire history + diff into run_query
  storage/
    __init__.py         # Task 5
    history.py          # Task 5: SQLite plan-run store
  tui/
    panels/
      plan_diff.py      # Task 7: render a PlanDiff
    app.py              # Task 8: show diff pane when present
tests/
  unit/test_plandiff.py, test_queryhash.py, test_to_payload.py, test_render_plan_diff.py
  engine/test_history.py, test_session_history.py
  fixtures/plans/index_scan_fast.json   # Task 3: a faster "after" plan
```

---

## Task 1: Persist a PlanTree back to EXPLAIN payload (`planmodel.to_payload`)

Because `PlanNode.raw` holds the original EXPLAIN node dict (including nested `"Plans"`), a `PlanTree` can round-trip to the payload `parse_explain_json` accepts. History uses this to store/reload plans.

**Files:** Modify `src/pgvet/core/planmodel.py`; Test `tests/unit/test_to_payload.py`.

- [ ] **Step 1: Failing test** — `tests/unit/test_to_payload.py`:
```python
import json
from pathlib import Path

from pgvet.core.explain import parse_explain_json

FIXTURE = Path(__file__).parent.parent / "fixtures" / "plans" / "seq_scan.json"


def test_to_payload_roundtrips_through_parser():
    original = json.loads(FIXTURE.read_text())
    tree = parse_explain_json(original)
    payload = tree.to_payload()
    reparsed = parse_explain_json(payload)
    assert reparsed.root.node_type == tree.root.node_type
    assert reparsed.planning_time_ms == tree.planning_time_ms
    assert reparsed.execution_time_ms == tree.execution_time_ms
    assert [c.relation for c in reparsed.root.children] == [c.relation for c in tree.root.children]
```

- [ ] **Step 2: Run, expect FAIL** (`AttributeError: 'PlanTree' object has no attribute 'to_payload'`): `uv run pytest tests/unit/test_to_payload.py -v`

- [ ] **Step 3: Implement** — add this method to the `PlanTree` dataclass in `src/pgvet/core/planmodel.py`:
```python
    def to_payload(self) -> list:
        """Reconstruct the EXPLAIN (FORMAT JSON) payload this tree came from.

        `root.raw` is the original "Plan" dict (with nested "Plans"), so re-wrapping
        it with the timings yields a structure parse_explain_json accepts."""
        return [
            {
                "Plan": self.root.raw,
                "Planning Time": self.planning_time_ms,
                "Execution Time": self.execution_time_ms,
            }
        ]
```

- [ ] **Step 4: Run, expect PASS**: `uv run pytest tests/unit/test_to_payload.py -v`

- [ ] **Step 5: Commit**
```bash
git add src/pgvet/core/planmodel.py tests/unit/test_to_payload.py
git commit -m "feat(core): add PlanTree.to_payload for history round-trip"
```

---

## Task 2: PlanDiff data model (`core/plandiff.py`)

**Files:** Create `src/pgvet/core/plandiff.py`; Test `tests/unit/test_plandiff.py` (model-only tests here; the `diff_plans` behavior is Task 3).

- [ ] **Step 1: Failing test** — `tests/unit/test_plandiff.py`:
```python
from pgvet.core.plandiff import NodeDelta, PlanDiff, DiffVerdict


def test_verdict_members():
    assert {v.value for v in DiffVerdict} == {"FASTER", "SLOWER", "SAME", "STRUCTURE_CHANGED"}


def test_nodedelta_and_plandiff_fields():
    d = NodeDelta(
        node_type="SEQ_SCAN", relation="orders",
        cost_before=200.0, cost_after=5.0,
        rows_before=950, rows_after=950,
        time_before=8.0, time_after=0.2,
        node_type_changed=False,
    )
    diff = PlanDiff(verdict=DiffVerdict.FASTER, aligned=True,
                    time_before_ms=13.1, time_after_ms=1.0, node_deltas=[d])
    assert diff.verdict == "FASTER"
    assert diff.aligned is True
    assert diff.node_deltas[0].cost_after == 5.0
```

- [ ] **Step 2: Run, expect FAIL** (`ModuleNotFoundError`): `uv run pytest tests/unit/test_plandiff.py -v`

- [ ] **Step 3: Implement** — `src/pgvet/core/plandiff.py`:
```python
"""Plan-to-plan diff model. Pure dataclasses; the diff algorithm is in diff_plans
(same module, added next task). Node alignment is positional + node-type based;
when the two plans don't align confidently the verdict is STRUCTURE_CHANGED rather
than a misleading node-by-node diff."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DiffVerdict(str, Enum):
    FASTER = "FASTER"
    SLOWER = "SLOWER"
    SAME = "SAME"
    STRUCTURE_CHANGED = "STRUCTURE_CHANGED"


@dataclass
class NodeDelta:
    node_type: str
    relation: str | None
    cost_before: float
    cost_after: float
    rows_before: float
    rows_after: float
    time_before: float | None
    time_after: float | None
    node_type_changed: bool


@dataclass
class PlanDiff:
    verdict: DiffVerdict
    aligned: bool
    time_before_ms: float | None
    time_after_ms: float | None
    node_deltas: list[NodeDelta] = field(default_factory=list)
```

- [ ] **Step 4: Run, expect PASS**: `uv run pytest tests/unit/test_plandiff.py -v`

- [ ] **Step 5: Commit**
```bash
git add src/pgvet/core/plandiff.py tests/unit/test_plandiff.py
git commit -m "feat(core): add plan-diff data model (NodeDelta/PlanDiff/DiffVerdict)"
```

---

## Task 3: The diff algorithm (`diff_plans`)

Aligns two `PlanTree`s by pre-order position. If the node-type sequences have different lengths, verdict is `STRUCTURE_CHANGED` and `aligned=False`. Otherwise it builds one `NodeDelta` per position (marking `node_type_changed` where types differ) and sets the verdict from whole-plan timing (falling back to root cost when `execution_time_ms` is absent) using a relative threshold.

**Files:** Modify `src/pgvet/core/plandiff.py` (append `diff_plans`); Create fixture `tests/fixtures/plans/index_scan_fast.json`; Test `tests/unit/test_diff_plans.py`.

- [ ] **Step 1: Create the "after" fixture** — `tests/fixtures/plans/index_scan_fast.json` (same shape as seq_scan.json but the orders scan is now an Index Scan and much faster; same node count so it aligns):
```json
[
  {
    "Plan": {
      "Node Type": "Nested Loop",
      "Plan Rows": 100, "Actual Rows": 950, "Total Cost": 30.5,
      "Actual Total Time": 1.2, "Actual Loops": 1,
      "Plans": [
        {"Node Type": "Index Scan", "Relation Name": "orders",
         "Plan Rows": 100, "Actual Rows": 950, "Total Cost": 10.0,
         "Actual Total Time": 0.4, "Actual Loops": 1, "Plans": []},
        {"Node Type": "Index Scan", "Relation Name": "customers",
         "Plan Rows": 1, "Actual Rows": 1, "Total Cost": 0.5,
         "Actual Total Time": 0.004, "Actual Loops": 950, "Plans": []}
      ]
    },
    "Planning Time": 0.3, "Execution Time": 1.9
  }
]
```

- [ ] **Step 2: Failing test** — `tests/unit/test_diff_plans.py`:
```python
import json
from pathlib import Path

from pgvet.core.explain import parse_explain_json
from pgvet.core.plandiff import diff_plans, DiffVerdict
from pgvet.core.planmodel import NodeType, PlanNode, PlanTree

PLANS = Path(__file__).parent.parent / "fixtures" / "plans"


def _load(name):
    return parse_explain_json(json.loads((PLANS / name).read_text()))


def test_faster_when_execution_time_drops():
    before = _load("seq_scan.json")       # exec 13.1ms
    after = _load("index_scan_fast.json") # exec 1.9ms
    diff = diff_plans(before, after)
    assert diff.aligned is True
    assert diff.verdict == DiffVerdict.FASTER
    assert diff.time_before_ms == 13.1
    assert diff.time_after_ms == 1.9
    # first child changed Seq Scan -> Index Scan
    changed = [d for d in diff.node_deltas if d.node_type_changed]
    assert any(d.relation == "orders" for d in changed)


def test_same_when_within_threshold():
    before = _load("seq_scan.json")
    diff = diff_plans(before, before)
    assert diff.verdict == DiffVerdict.SAME
    assert diff.aligned is True


def test_structure_changed_when_node_counts_differ():
    before = _load("seq_scan.json")  # 3 nodes
    leaf = PlanNode(NodeType.SEQ_SCAN, "orders", 1, 1, 1, 1, 1, [], {})
    after = PlanTree(root=leaf, planning_time_ms=0, execution_time_ms=1.0, query=None)  # 1 node
    diff = diff_plans(before, after)
    assert diff.verdict == DiffVerdict.STRUCTURE_CHANGED
    assert diff.aligned is False


def test_slower_when_execution_time_rises():
    before = _load("index_scan_fast.json")  # 1.9ms
    after = _load("seq_scan.json")           # 13.1ms
    diff = diff_plans(before, after)
    assert diff.verdict == DiffVerdict.SLOWER
```

- [ ] **Step 3: Run, expect FAIL** (`ImportError: cannot import name 'diff_plans'`): `uv run pytest tests/unit/test_diff_plans.py -v`

- [ ] **Step 4: Implement** — append to `src/pgvet/core/plandiff.py`:
```python
from pgvet.core.planmodel import PlanTree  # noqa: E402  (kept near algorithm for clarity)

SAME_THRESHOLD = 0.10  # ±10% is "no meaningful change"


def _metric(tree: PlanTree) -> float | None:
    if tree.execution_time_ms is not None:
        return tree.execution_time_ms
    return tree.root.estimated_cost


def diff_plans(before: PlanTree, after: PlanTree) -> PlanDiff:
    before_nodes = list(before.walk())
    after_nodes = list(after.walk())

    if len(before_nodes) != len(after_nodes):
        return PlanDiff(
            verdict=DiffVerdict.STRUCTURE_CHANGED, aligned=False,
            time_before_ms=before.execution_time_ms, time_after_ms=after.execution_time_ms,
        )

    deltas = [
        NodeDelta(
            node_type=a.node_type.value,
            relation=a.relation or b.relation,
            cost_before=b.estimated_cost, cost_after=a.estimated_cost,
            rows_before=b.estimated_rows, rows_after=a.estimated_rows,
            time_before=b.actual_time_ms, time_after=a.actual_time_ms,
            node_type_changed=(a.node_type != b.node_type),
        )
        for b, a in zip(before_nodes, after_nodes)
    ]

    mb, ma = _metric(before), _metric(after)
    if mb is None or ma is None or mb == 0:
        verdict = DiffVerdict.SAME
    elif ma < mb * (1 - SAME_THRESHOLD):
        verdict = DiffVerdict.FASTER
    elif ma > mb * (1 + SAME_THRESHOLD):
        verdict = DiffVerdict.SLOWER
    else:
        verdict = DiffVerdict.SAME

    return PlanDiff(
        verdict=verdict, aligned=True,
        time_before_ms=before.execution_time_ms, time_after_ms=after.execution_time_ms,
        node_deltas=deltas,
    )
```

- [ ] **Step 5: Run, expect PASS (4 tests)**: `uv run pytest tests/unit/test_diff_plans.py -v`

- [ ] **Step 6: Commit**
```bash
git add src/pgvet/core/plandiff.py tests/fixtures/plans/index_scan_fast.json tests/unit/test_diff_plans.py
git commit -m "feat(core): add diff_plans with positional node alignment + verdict"
```

---

## Task 4: Query hashing + git ref (`core/queryhash.py`)

History keys runs by a *normalized* query hash (so whitespace/case changes don't fork the history) and tags them with the current git ref.

**Files:** Create `src/pgvet/core/queryhash.py`; Test `tests/unit/test_queryhash.py`.

- [ ] **Step 1: Failing test** — `tests/unit/test_queryhash.py`:
```python
from pgvet.core.queryhash import hash_query, current_git_ref


def test_hash_is_stable_across_whitespace_and_case():
    a = hash_query("select * from orders where id = 1")
    b = hash_query("SELECT   *\nFROM orders\nWHERE id = 1")
    assert a == b
    assert len(a) == 64  # sha256 hex


def test_hash_differs_for_different_queries():
    assert hash_query("select 1") != hash_query("select 2")


def test_hash_falls_back_on_unparseable_sql():
    # not valid SQL; must not raise, must be deterministic
    h1 = hash_query(">>> not sql <<<")
    h2 = hash_query(">>> not sql <<<")
    assert h1 == h2 and len(h1) == 64


def test_current_git_ref_injectable(monkeypatch):
    monkeypatch.setattr("pgvet.core.queryhash._run_git", lambda args, cwd: "abc1234")
    assert current_git_ref() == "abc1234"


def test_current_git_ref_none_on_failure(monkeypatch):
    def _boom(args, cwd):
        raise OSError("no git")
    monkeypatch.setattr("pgvet.core.queryhash._run_git", _boom)
    assert current_git_ref() is None
```

- [ ] **Step 2: Run, expect FAIL** (`ModuleNotFoundError`): `uv run pytest tests/unit/test_queryhash.py -v`

- [ ] **Step 3: Implement** — `src/pgvet/core/queryhash.py`:
```python
"""Normalized-query hashing + current git ref, used to key plan history."""

from __future__ import annotations

import hashlib
import subprocess


def _normalize(sql: str) -> str:
    try:
        import sqlglot

        return sqlglot.transpile(sql, normalize=True)[0]
    except Exception:  # noqa: BLE001 — unparseable SQL falls back to raw text
        return " ".join(sql.lower().split())


def hash_query(sql: str) -> str:
    return hashlib.sha256(_normalize(sql).encode("utf-8")).hexdigest()


def _run_git(args: list[str], cwd: str | None) -> str:
    out = subprocess.check_output(["git", *args], cwd=cwd, text=True, stderr=subprocess.DEVNULL)
    return out.strip()


def current_git_ref(cwd: str | None = None) -> str | None:
    try:
        return _run_git(["rev-parse", "--short", "HEAD"], cwd) or None
    except Exception:  # noqa: BLE001 — not a repo / git missing
        return None
```
*Note: `sqlglot.transpile(..., normalize=True)` lowercases keywords and collapses whitespace; the exact normalized form is an implementation detail — the tests assert only stability, not a specific string.*

- [ ] **Step 4: Run, expect PASS (5 tests)**: `uv run pytest tests/unit/test_queryhash.py -v`

- [ ] **Step 5: Commit**
```bash
git add src/pgvet/core/queryhash.py tests/unit/test_queryhash.py
git commit -m "feat(core): add normalized query hashing and git-ref helper"
```

---

## Task 5: SQLite plan-history store (`storage/history.py`)

**Files:** Create `src/pgvet/storage/__init__.py` (empty); Create `src/pgvet/storage/history.py`; Test `tests/engine/test_history.py`.

- [ ] **Step 1: Failing test** — `tests/engine/test_history.py`:
```python
import json
from pathlib import Path

from pgvet.core.explain import parse_explain_json
from pgvet.storage.history import History

FIXTURE = Path(__file__).parent.parent / "fixtures" / "plans" / "seq_scan.json"


def _payload_json():
    return json.dumps(json.loads(FIXTURE.read_text()))


def test_record_then_latest(tmp_path):
    h = History(str(tmp_path / "hist.db"))
    assert h.latest("qh1") is None
    h.record(query_hash="qh1", git_ref="abc1234", recorded_at="2026-07-29T00:00:00Z",
             execution_time_ms=13.1, plan_json=_payload_json())
    row = h.latest("qh1")
    assert row is not None
    assert row["git_ref"] == "abc1234"
    assert row["execution_time_ms"] == 13.1
    # plan_json reloads into a PlanTree
    tree = parse_explain_json(json.loads(row["plan_json"]))
    assert tree.execution_time_ms == 13.1
    h.close()


def test_latest_returns_most_recent(tmp_path):
    h = History(str(tmp_path / "hist.db"))
    h.record(query_hash="qh", git_ref="v1", recorded_at="2026-07-01T00:00:00Z",
             execution_time_ms=50.0, plan_json=_payload_json())
    h.record(query_hash="qh", git_ref="v2", recorded_at="2026-07-02T00:00:00Z",
             execution_time_ms=5.0, plan_json=_payload_json())
    assert h.latest("qh")["git_ref"] == "v2"
    assert len(h.all_for("qh")) == 2
    h.close()


def test_persists_across_instances(tmp_path):
    db = str(tmp_path / "hist.db")
    h1 = History(db)
    h1.record(query_hash="qh", git_ref="v1", recorded_at="2026-07-01T00:00:00Z",
              execution_time_ms=1.0, plan_json=_payload_json())
    h1.close()
    h2 = History(db)
    assert h2.latest("qh") is not None
    h2.close()
```

- [ ] **Step 2: Run, expect FAIL** (`ModuleNotFoundError`): `uv run pytest tests/engine/test_history.py -v`

- [ ] **Step 3: Implement** — empty `src/pgvet/storage/__init__.py`, then `src/pgvet/storage/history.py`:
```python
"""Local SQLite store of plan runs, keyed by normalized-query hash. Enables the
'when did this get slow?' history and supplies the 'previous' plan for diffing."""

from __future__ import annotations

import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS plan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_hash TEXT NOT NULL,
    git_ref TEXT,
    recorded_at TEXT NOT NULL,
    execution_time_ms REAL,
    plan_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_plan_runs_hash ON plan_runs(query_hash, id);
"""


class History:
    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def record(self, *, query_hash: str, git_ref: str | None, recorded_at: str,
               execution_time_ms: float | None, plan_json: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO plan_runs (query_hash, git_ref, recorded_at, execution_time_ms, plan_json)"
            " VALUES (?, ?, ?, ?, ?)",
            (query_hash, git_ref, recorded_at, execution_time_ms, plan_json),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def latest(self, query_hash: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM plan_runs WHERE query_hash = ? ORDER BY id DESC LIMIT 1",
            (query_hash,),
        ).fetchone()
        return dict(row) if row else None

    def all_for(self, query_hash: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM plan_runs WHERE query_hash = ? ORDER BY id DESC", (query_hash,)
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 4: Run, expect PASS (3 tests)**: `uv run pytest tests/engine/test_history.py -v`

- [ ] **Step 5: Commit**
```bash
git add src/pgvet/storage/__init__.py src/pgvet/storage/history.py tests/engine/test_history.py
git commit -m "feat(storage): add SQLite plan-history store"
```

---

## Task 6: Wire history + diff into the engine (`session.run_query`)

Extend `Session` so that, when a `History` is provided, `run_query` loads the previous plan for the query hash, computes a `PlanDiff`, records the new run, and returns them on `RunResult`. Defaults keep existing behavior (and all existing tests) unchanged.

**Files:** Modify `src/pgvet/core/session.py`; Test `tests/engine/test_session_history.py`.

- [ ] **Step 1: Failing test** — `tests/engine/test_session_history.py`:
```python
import json
from pathlib import Path

from pgvet.core.explain import parse_explain_json
from pgvet.core.registry import Registry
from pgvet.core.session import Session, RunResult
from pgvet.core.plandiff import DiffVerdict
from pgvet.storage.history import History
from pgvet.core.schemamodel import SchemaModel

PLANS = Path(__file__).parent.parent / "fixtures" / "plans"


def _tree(name):
    return parse_explain_json(json.loads((PLANS / name).read_text()))


def test_run_query_records_and_diffs(tmp_path, monkeypatch):
    hist = History(str(tmp_path / "h.db"))
    sess = Session(conn=object(), registry=Registry(),
                   history=hist, git_ref="testref", clock=lambda: "2026-07-29T00:00:00Z")

    # first run: seq_scan (slow). No previous → diff is None.
    monkeypatch.setattr("pgvet.core.session.run_explain", lambda conn, sql: _tree("seq_scan.json"))
    monkeypatch.setattr("pgvet.core.session.introspect", lambda conn: SchemaModel())
    r1 = sess.run_query("SELECT 1")
    assert isinstance(r1, RunResult)
    assert r1.diff is None
    assert r1.previous is None

    # second run of the SAME query: index_scan_fast (fast) → diff FASTER vs previous.
    monkeypatch.setattr("pgvet.core.session.run_explain", lambda conn, sql: _tree("index_scan_fast.json"))
    r2 = sess.run_query("SELECT 1")
    assert r2.previous is not None
    assert r2.diff is not None
    assert r2.diff.verdict == DiffVerdict.FASTER
    hist.close()


def test_run_query_without_history_is_unchanged(monkeypatch):
    sess = Session(conn=object(), registry=Registry())
    monkeypatch.setattr("pgvet.core.session.run_explain", lambda conn, sql: _tree("seq_scan.json"))
    monkeypatch.setattr("pgvet.core.session.introspect", lambda conn: SchemaModel())
    r = sess.run_query("SELECT 1")
    assert r.diff is None and r.previous is None
```

- [ ] **Step 2: Run, expect FAIL**: `uv run pytest tests/engine/test_session_history.py -v`

- [ ] **Step 3: Implement** — modify `src/pgvet/core/session.py`:

(a) Extend imports at the top:
```python
import json

from pgvet.core.explain import parse_explain_json, run_explain
from pgvet.core.plandiff import PlanDiff, diff_plans
from pgvet.core.queryhash import hash_query
```
(b) Extend `RunResult` with two optional fields (defaults preserve existing construction):
```python
@dataclass
class RunResult:
    query: str
    plan: PlanTree
    findings: list[Finding]
    previous: PlanTree | None = None
    diff: PlanDiff | None = None
```
(c) Extend `Session.__init__` to accept optional history/git_ref/clock:
```python
    def __init__(self, conn, registry: Registry, history=None,
                 git_ref: str | None = None, clock=None) -> None:
        self._conn = conn
        self._registry = registry
        self._history = history
        self._git_ref = git_ref
        # clock() returns an ISO timestamp string; injected for deterministic tests.
        self._clock = clock or (lambda: __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat())
```
(d) Replace `run_query` with the history-aware version:
```python
    def run_query(self, sql: str) -> RunResult:
        plan = run_explain(self._conn, sql)
        schema = introspect(self._conn)

        previous = None
        diff = None
        if self._history is not None:
            qhash = hash_query(sql)
            prev_row = self._history.latest(qhash)
            if prev_row is not None:
                previous = parse_explain_json(json.loads(prev_row["plan_json"]))
                diff = diff_plans(previous, plan)
            self._history.record(
                query_hash=qhash, git_ref=self._git_ref, recorded_at=self._clock(),
                execution_time_ms=plan.execution_time_ms, plan_json=json.dumps(plan.to_payload()),
            )

        ctx = PlanContext(plan=plan, query=sql, schema=schema, previous=previous)
        return RunResult(query=sql, plan=plan, findings=self.analyze(ctx),
                         previous=previous, diff=diff)
```

- [ ] **Step 4: Run new + full suite, expect PASS**: `uv run pytest tests/engine/test_session_history.py -v && uv run pytest -q`

- [ ] **Step 5: Commit**
```bash
git add src/pgvet/core/session.py tests/engine/test_session_history.py
git commit -m "feat(core): wire plan history + diff into Session.run_query"
```

---

## Task 7: Plan-diff renderer (`tui/panels/plan_diff.py`)

**Files:** Create `src/pgvet/tui/panels/plan_diff.py`; Test `tests/unit/test_render_plan_diff.py`.

- [ ] **Step 1: Failing test** — `tests/unit/test_render_plan_diff.py`:
```python
from rich.table import Table as RichTable

from pgvet.tui.panels.plan_diff import render_plan_diff
from pgvet.core.plandiff import PlanDiff, NodeDelta, DiffVerdict


def _diff(verdict, deltas=None):
    return PlanDiff(verdict=verdict, aligned=(verdict != DiffVerdict.STRUCTURE_CHANGED),
                    time_before_ms=13.1, time_after_ms=1.9, node_deltas=deltas or [])


def test_render_faster_diff_has_rows():
    d = NodeDelta("SEQ_SCAN", "orders", 200, 5, 950, 950, 8.0, 0.2, node_type_changed=True)
    table = render_plan_diff(_diff(DiffVerdict.FASTER, [d]))
    assert isinstance(table, RichTable)
    assert table.row_count == 1
    assert table.title is not None and "FASTER" in str(table.title)


def test_render_structure_changed_has_no_rows():
    table = render_plan_diff(_diff(DiffVerdict.STRUCTURE_CHANGED))
    assert "STRUCTURE_CHANGED" in str(table.title)
    assert table.row_count == 0
```

- [ ] **Step 2: Run, expect FAIL** (`ModuleNotFoundError`): `uv run pytest tests/unit/test_render_plan_diff.py -v`

- [ ] **Step 3: Implement** — `src/pgvet/tui/panels/plan_diff.py`:
```python
"""Render a PlanDiff as a Rich table: one row per aligned node, with a title that
states the overall verdict and the before/after execution time."""

from __future__ import annotations

from rich.table import Table as RichTable

from pgvet.core.plandiff import DiffVerdict, PlanDiff

_VERDICT_COLOR = {
    DiffVerdict.FASTER: "green",
    DiffVerdict.SLOWER: "red",
    DiffVerdict.SAME: "dim",
    DiffVerdict.STRUCTURE_CHANGED: "yellow",
}


def render_plan_diff(diff: PlanDiff) -> RichTable:
    color = _VERDICT_COLOR.get(diff.verdict, "white")
    timing = ""
    if diff.time_before_ms is not None and diff.time_after_ms is not None:
        timing = f"  ({diff.time_before_ms:g}ms → {diff.time_after_ms:g}ms)"
    table = RichTable(title=f"[{color}]{diff.verdict.value}[/]{timing}", expand=True)
    table.add_column("Node")
    table.add_column("Where", no_wrap=True)
    table.add_column("cost Δ", justify="right")
    table.add_column("rows Δ", justify="right")
    for d in diff.node_deltas:
        node = d.node_type.replace("_", " ").title()
        if d.node_type_changed:
            node = f"[bold]{node}[/] (changed)"
        cost = f"{d.cost_before:g}→{d.cost_after:g}"
        rows = f"{d.rows_before:g}→{d.rows_after:g}"
        table.add_row(node, d.relation or "", cost, rows)
    return table
```

- [ ] **Step 4: Run, expect PASS (2 tests)**: `uv run pytest tests/unit/test_render_plan_diff.py -v`

- [ ] **Step 5: Commit**
```bash
git add src/pgvet/tui/panels/plan_diff.py tests/unit/test_render_plan_diff.py
git commit -m "feat(tui): add plan-diff Rich renderer"
```

---

## Task 8: Show the diff pane in the TUI (`tui/app.py`)

When a run has a diff, render it beneath the findings. Keep the injected-callable design so it stays testable offline.

**Files:** Modify `src/pgvet/tui/app.py`; Test `tests/unit/test_tui_app_diff.py`.

- [ ] **Step 1: Failing test** — `tests/unit/test_tui_app_diff.py`:
```python
import pytest

from pgvet.tui.app import PgvetApp
from pgvet.core.session import RunResult
from pgvet.core.planmodel import NodeType
from pgvet.core.plandiff import PlanDiff, DiffVerdict
from tests.unit.advisor_helpers import node, ctx


def _result_with_diff():
    plan = ctx(node(NodeType.INDEX_SCAN, relation="orders")).plan
    diff = PlanDiff(verdict=DiffVerdict.FASTER, aligned=True,
                    time_before_ms=13.1, time_after_ms=1.9, node_deltas=[])
    return RunResult(query="SELECT 1", plan=plan, findings=[], diff=diff)


@pytest.mark.asyncio
async def test_app_stores_and_reflects_diff():
    app = PgvetApp(analyze_query=lambda sql: _result_with_diff())
    async with app.run_test() as pilot:
        app.run_analysis("SELECT 1")
        await pilot.pause()
        assert app.last_result.diff is not None
        assert app.last_result.diff.verdict == DiffVerdict.FASTER
```

- [ ] **Step 2: Run, expect FAIL** (the test imports fine but asserts diff rendering wiring — it fails only if run_analysis errors on a diff-bearing result; first confirm it fails because the current app ignores `.diff`): `uv run pytest tests/unit/test_tui_app_diff.py -v`
*If it already passes because `.diff` is simply stored on RunResult and the app doesn't touch it, that's acceptable — but implement Step 3 so the diff is actually shown, then re-run.*

- [ ] **Step 3: Implement** — modify `src/pgvet/tui/app.py`:

(a) import the renderer:
```python
from pgvet.tui.panels.plan_diff import render_plan_diff
```
(b) add a diff Static to `compose()` beneath findings — change the findings column to a vertical stack. Replace the `with Horizontal():` block with:
```python
        with Horizontal():
            yield Static("Plan will appear here.", id="plan")
            with Vertical():
                yield Static("Findings will appear here.", id="findings")
                yield Static("", id="diff")
```
and add `from textual.containers import Horizontal, Vertical` (Vertical is new).
(c) at the end of `run_analysis`, render the diff when present:
```python
        diff_widget = self.query_one("#diff", Static)
        if result.diff is not None:
            diff_widget.update(render_plan_diff(result.diff))
        else:
            diff_widget.update("")
```

- [ ] **Step 4: Run new + full suite, expect PASS**: `uv run pytest tests/unit/test_tui_app_diff.py -v && uv run pytest -q`

- [ ] **Step 5: Commit**
```bash
git add src/pgvet/tui/app.py tests/unit/test_tui_app_diff.py
git commit -m "feat(tui): show plan-diff pane when a run has a previous baseline"
```

---

## Task 9: Wire history into the live TUI launch (`cli.launch_tui`)

Give the live `pgvet tui` a real `History` (in a `.pgvet/history.db` under the cwd) and the current git ref, so interactive runs accumulate history for diffing.

**Files:** Modify `src/pgvet/cli.py`; Test `tests/unit/test_cli_history_wiring.py`.

- [ ] **Step 1: Failing test** — `tests/unit/test_cli_history_wiring.py` (tests the wiring helper, not a live DB):
```python
from pgvet.cli import _default_history_path


def test_default_history_path_is_under_pgvet_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = _default_history_path()
    assert p.endswith("history.db")
    assert ".pgvet" in p
```

- [ ] **Step 2: Run, expect FAIL** (`ImportError`): `uv run pytest tests/unit/test_cli_history_wiring.py -v`

- [ ] **Step 3: Implement** — in `src/pgvet/cli.py`:

(a) add helper near the top-level functions:
```python
def _default_history_path() -> str:
    from pathlib import Path

    d = Path.cwd() / ".pgvet"
    d.mkdir(exist_ok=True)
    return str(d / "history.db")
```
(b) update `launch_tui` to build a History and git ref and pass them to Session, closing the history in the finally:
```python
def launch_tui() -> int:
    from pgvet.config import Settings
    from pgvet.core.connection import Connection
    from pgvet.core.queryhash import current_git_ref
    from pgvet.storage.history import History
    from pgvet.tui.app import PgvetApp

    conn = Connection.connect(Settings.from_env())
    history = History(_default_history_path())
    session = Session(conn=conn, registry=_registry(),
                      history=history, git_ref=current_git_ref())
    try:
        PgvetApp(analyze_query=session.run_query).run()
    finally:
        history.close()
        conn.close()
    return 0
```

- [ ] **Step 4: Run new + full suite, expect PASS**: `uv run pytest tests/unit/test_cli_history_wiring.py -v && uv run pytest -q`

- [ ] **Step 5: Commit**
```bash
git add src/pgvet/cli.py tests/unit/test_cli_history_wiring.py
git commit -m "feat(cli): give the live TUI a plan-history store + git ref"
```

---

## Live-DB validation (deferred — run on the connected machine)

The automated suite above is fully offline. When a live dev Postgres is available,
smoke-test the real loop (NOT part of CI, per the workstation boundary):
1. `export DATABASE_URL=...`; `uv run pgvet tui`.
2. Run a query, then re-run it after `CREATE INDEX` — confirm the diff pane reports
   FASTER/SLOWER correctly and the timing before/after is populated.
3. Switch git branches between runs and confirm `git_ref` is recorded per run
   (inspect `.pgvet/history.db`).
4. Confirm `sqlglot` normalization keeps the same query stable across whitespace edits
   (same history key).

---

## Self-Review

**Spec coverage (design §6 PlanDiff, §15 M4):**
- §6 "align nodes by structural position, per-node deltas, verdict, flag structure changed" → Task 3 `diff_plans`. ✔
- §15 M4 "PlanDiff + storage/history keyed by query hash + git/migration state + diff pane + 'when did this get slow'" → Tasks 2–3 (diff), 4 (hash+git), 5 (history), 6 (wiring), 7–8 (pane), 9 (live wiring). ✔ (Migration-id keying is simplified to git-ref keying for M4; migration-aware keying is deferred to M6 where migration tooling is in scope — noted, not silently dropped.)

**Placeholder scan:** No TBD/TODO; every code step is complete. The one conditional ("if the diff test already passes") is explicit with a defined resolution.

**Type consistency:** `diff_plans(before, after) -> PlanDiff`; `PlanDiff(verdict, aligned, time_before_ms, time_after_ms, node_deltas)`; `NodeDelta(node_type, relation, cost_before, cost_after, rows_before, rows_after, time_before, time_after, node_type_changed)`; `hash_query(sql)->str`; `current_git_ref(cwd=None)->str|None`; `History(db_path)` with `record(*, query_hash, git_ref, recorded_at, execution_time_ms, plan_json)`, `latest`, `all_for`, `close`; `PlanTree.to_payload()->list`; `Session(conn, registry, history=None, git_ref=None, clock=None)`; `RunResult(query, plan, findings, previous=None, diff=None)`; `render_plan_diff(diff)->Table`. Consistent across tasks. ✔

**Dependency note:** Task 6 changes `RunResult` and `Session.__init__` with defaults only, so all M0–M3 tests remain green (verified by the full-suite run in Task 6 Step 4).
