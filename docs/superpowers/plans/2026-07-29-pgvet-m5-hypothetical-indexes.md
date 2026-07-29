# pgvet M5 — Hypothetical Indexes (HypoPG) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Let a developer test "what if I added this index?" without building one: create a HypoPG *hypothetical* index, re-plan the query, and show the estimated before/after plans side-by-side with a verdict.

**Architecture:** A small `core/hypo.py` drives the HypoPG extension through the existing `Connection` — detect availability, create a hypothetical index, re-run a plain `EXPLAIN` (no `ANALYZE`, because hypothetical indexes only influence the planner's *estimates*), and always reset. It reuses M4's `diff_plans` to compare baseline vs candidate. `Session` exposes a thin entry point; the TUI gains an optional "candidate index" input that's shown only when HypoPG is present. Fully offline-testable via a fake connection that simulates HypoPG; the live behavior is validated on the connected machine.

**Tech Stack:** Python 3.11+, uv, `psycopg` (via the existing `Connection` wrapper), `rich`/`textual`, `pytest`. Runtime DB dependency: the **HypoPG** Postgres extension (feature-gated; absence disables the feature cleanly).

**Prerequisites:**
- MVP (M0–M3) merged to `main`.
- **M4 must be implemented first** — this plan imports `diff_plans` and `PlanDiff` from `pgvet.core.plandiff`.
- Existing symbols reused: `pgvet.core.connection.Connection` (`fetch_one(sql, params=None)`, `fetch_all(sql, params=None)`), `pgvet.core.explain.run_explain(conn, sql, analyze=True)`, `pgvet.core.plandiff.diff_plans`/`PlanDiff`/`DiffVerdict`, `pgvet.core.session.Session`, `pgvet.tui.app.PgvetApp`, `pgvet.tui.panels.plan_diff.render_plan_diff`, `pgvet.tui.panels.plan_tree.render_plan_tree`.

**Conventions:** run tests with `uv run pytest`; end every commit body with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`; commit only the listed files.

**Key correctness note (read before implementing):** hypothetical indexes exist only in the planner's memory for the session; they cannot be used by `EXPLAIN ANALYZE` (which actually executes). So every re-plan in this milestone uses `run_explain(conn, sql, analyze=False)`. The resulting plans have estimated costs but **no** actual times — `diff_plans` already falls back to root `estimated_cost` when `execution_time_ms` is `None`, so the verdict still works on estimates.

---

## File Structure

```
src/pgvet/
  core/
    hypo.py         # Tasks 1-3: availability, create/reset, try_hypothetical_index + HypoResult
    session.py      # Task 4: Session.try_hypothetical_index delegate
  tui/
    app.py          # Task 5: optional candidate-index input + render
    cli.py          # Task 6: feature-gate wiring at launch
tests/
  unit/test_hypo.py, test_tui_app_hypo.py, test_cli_hypo_wiring.py
  fixtures/plans/  (reuses seq_scan.json + index_scan_fast.json from M4)
```

---

## Task 1: HypoPG availability + create/reset primitives (`core/hypo.py`)

**Files:** Create `src/pgvet/core/hypo.py`; Test `tests/unit/test_hypo.py`.

- [ ] **Step 1: Failing test** — `tests/unit/test_hypo.py` (first three tests; more added in later tasks):
```python
from pgvet.core.hypo import hypopg_available, create_hypothetical_index, reset_hypothetical


class _FakeConn:
    """Simulates HypoPG. Records SQL; returns canned rows by SQL content."""
    def __init__(self, has_hypopg=True):
        self.has_hypopg = has_hypopg
        self.calls = []
    def fetch_one(self, sql, params=None):
        self.calls.append((sql, params))
        if "pg_extension" in sql:
            return {"ok": 1} if self.has_hypopg else None
        if "hypopg_create_index" in sql:
            return {"indexrelid": 98765, "indexname": "<hypo>"}
        if "hypopg_reset" in sql:
            return {"hypopg_reset": ""}
        raise AssertionError(f"unexpected fetch_one: {sql!r}")
    def fetch_all(self, sql, params=None):
        self.calls.append((sql, params))
        return []


def test_hypopg_available_true_and_false():
    assert hypopg_available(_FakeConn(has_hypopg=True)) is True
    assert hypopg_available(_FakeConn(has_hypopg=False)) is False


def test_create_hypothetical_index_returns_indexrelid():
    conn = _FakeConn()
    relid = create_hypothetical_index(conn, "CREATE INDEX ON orders (status)")
    assert relid == 98765
    # the CREATE statement is passed as a parameter, not string-formatted
    create_call = [c for c in conn.calls if "hypopg_create_index" in c[0]][0]
    assert create_call[1] == ("CREATE INDEX ON orders (status)",)


def test_reset_hypothetical_calls_hypopg_reset():
    conn = _FakeConn()
    reset_hypothetical(conn)
    assert any("hypopg_reset" in c[0] for c in conn.calls)
```

- [ ] **Step 2: Run, expect FAIL** (`ModuleNotFoundError`): `uv run pytest tests/unit/test_hypo.py -v`

- [ ] **Step 3: Implement** — `src/pgvet/core/hypo.py`:
```python
"""HypoPG hypothetical-index support. Drives the HypoPG extension through the
Connection wrapper. Hypothetical indexes are session-local and never touch disk,
so this is safe and read-mostly. All re-plans use EXPLAIN WITHOUT ANALYZE, because
a hypothetical index only affects the planner's estimates."""

from __future__ import annotations


def hypopg_available(conn) -> bool:
    """True if the HypoPG extension is installed in the connected database."""
    row = conn.fetch_one("SELECT 1 AS ok FROM pg_extension WHERE extname = 'hypopg'")
    return row is not None


def create_hypothetical_index(conn, create_index_sql: str) -> int:
    """Register a hypothetical index from a CREATE INDEX statement; return its
    hypothetical indexrelid. The statement is passed as a bound parameter."""
    row = conn.fetch_one(
        "SELECT indexrelid, indexname FROM hypopg_create_index(%s)", (create_index_sql,)
    )
    return int(row["indexrelid"])


def reset_hypothetical(conn) -> None:
    """Drop all hypothetical indexes for this session."""
    conn.fetch_one("SELECT hypopg_reset()")
```

- [ ] **Step 4: Run, expect PASS (3 tests)**: `uv run pytest tests/unit/test_hypo.py -v`

- [ ] **Step 5: Commit**
```bash
git add src/pgvet/core/hypo.py tests/unit/test_hypo.py
git commit -m "feat(core): add HypoPG availability + create/reset primitives"
```

---

## Task 2: `try_hypothetical_index` + `HypoResult`

Runs the full loop: baseline plan → create hypothetical index → candidate plan → **always reset** (try/finally) → diff. Returns a `HypoResult`.

**Files:** Modify `src/pgvet/core/hypo.py`; Modify `tests/unit/test_hypo.py` (add tests).

- [ ] **Step 1: Add failing tests** to `tests/unit/test_hypo.py`:
```python
import json
from pathlib import Path

from pgvet.core.hypo import try_hypothetical_index, HypoResult
from pgvet.core.plandiff import DiffVerdict

PLANS = Path(__file__).parent.parent / "fixtures" / "plans"


class _PlanningFakeConn:
    """Returns the slow plan before a hypothetical index is created, the fast plan
    after — simulating what HypoPG does to the planner."""
    def __init__(self):
        self.created = False
        self.reset_called = False
    def _payload(self, name):
        return json.loads((PLANS / name).read_text())
    def fetch_one(self, sql, params=None):
        if "pg_extension" in sql:
            return {"ok": 1}
        if "hypopg_create_index" in sql:
            self.created = True
            return {"indexrelid": 1, "indexname": "<hypo>"}
        if "hypopg_reset" in sql:
            self.reset_called = True
            return {"hypopg_reset": ""}
        if sql.startswith("EXPLAIN"):
            name = "index_scan_fast.json" if self.created else "seq_scan.json"
            return {"QUERY PLAN": self._payload(name)}
        raise AssertionError(f"unexpected fetch_one: {sql!r}")


def test_try_hypothetical_index_reports_faster_and_resets():
    conn = _PlanningFakeConn()
    result = try_hypothetical_index(conn, "SELECT * FROM orders", "CREATE INDEX ON orders (status)")
    assert isinstance(result, HypoResult)
    assert result.diff.verdict == DiffVerdict.FASTER
    assert result.baseline.root.node_type.value == "NESTED_LOOP"
    assert conn.reset_called is True  # cleanup always runs


def test_try_hypothetical_index_resets_even_on_explain_error():
    class _BoomConn(_PlanningFakeConn):
        def fetch_one(self, sql, params=None):
            if sql.startswith("EXPLAIN") and self.created:
                raise RuntimeError("explain blew up")
            return super().fetch_one(sql, params)

    conn = _BoomConn()
    try:
        try_hypothetical_index(conn, "SELECT 1", "CREATE INDEX ON orders (status)")
    except RuntimeError:
        pass
    assert conn.reset_called is True  # finally still reset
```

- [ ] **Step 2: Run, expect FAIL** (`ImportError: cannot import name 'try_hypothetical_index'`): `uv run pytest tests/unit/test_hypo.py -v`

- [ ] **Step 3: Implement** — append to `src/pgvet/core/hypo.py`:
```python
from dataclasses import dataclass

from pgvet.core.explain import run_explain
from pgvet.core.plandiff import PlanDiff, diff_plans
from pgvet.core.planmodel import PlanTree


@dataclass
class HypoResult:
    baseline: PlanTree
    candidate: PlanTree
    diff: PlanDiff


def try_hypothetical_index(conn, sql: str, create_index_sql: str) -> HypoResult:
    """Estimate the effect of `create_index_sql` on `sql` without building the index.

    Uses EXPLAIN WITHOUT ANALYZE on both sides (hypothetical indexes affect only
    the planner's estimates). Always resets hypothetical indexes afterwards."""
    baseline = run_explain(conn, sql, analyze=False)
    try:
        create_hypothetical_index(conn, create_index_sql)
        candidate = run_explain(conn, sql, analyze=False)
    finally:
        reset_hypothetical(conn)
    return HypoResult(baseline=baseline, candidate=candidate, diff=diff_plans(baseline, candidate))
```
*Place these imports at the top of the file with the others if your linter prefers; keeping them adjacent to the function is also fine since there is no circular import (`explain`/`plandiff`/`planmodel` do not import `hypo`).*

- [ ] **Step 4: Run, expect PASS**: `uv run pytest tests/unit/test_hypo.py -v` (5 tests total in this file now)

- [ ] **Step 5: Commit**
```bash
git add src/pgvet/core/hypo.py tests/unit/test_hypo.py
git commit -m "feat(core): add try_hypothetical_index (baseline→hypo→diff, always reset)"
```

---

## Task 3: Session entry point (`Session.try_hypothetical_index`)

A thin delegate so callers (TUI, future CLI) go through `Session` rather than touching `hypo` + the raw connection directly.

**Files:** Modify `src/pgvet/core/session.py`; Test `tests/engine/test_session_hypo.py`.

- [ ] **Step 1: Failing test** — `tests/engine/test_session_hypo.py`:
```python
import json
from pathlib import Path

from pgvet.core.session import Session
from pgvet.core.registry import Registry
from pgvet.core.hypo import HypoResult
from pgvet.core.plandiff import DiffVerdict

PLANS = Path(__file__).parent.parent / "fixtures" / "plans"


class _PlanningFakeConn:
    def __init__(self):
        self.created = False
        self.reset_called = False
    def fetch_one(self, sql, params=None):
        if "hypopg_create_index" in sql:
            self.created = True
            return {"indexrelid": 1, "indexname": "<hypo>"}
        if "hypopg_reset" in sql:
            self.reset_called = True
            return {"hypopg_reset": ""}
        if sql.startswith("EXPLAIN"):
            name = "index_scan_fast.json" if self.created else "seq_scan.json"
            return {"QUERY PLAN": json.loads((PLANS / name).read_text())}
        raise AssertionError(sql)


def test_session_delegates_to_hypo():
    sess = Session(conn=_PlanningFakeConn(), registry=Registry())
    result = sess.try_hypothetical_index("SELECT * FROM orders", "CREATE INDEX ON orders (status)")
    assert isinstance(result, HypoResult)
    assert result.diff.verdict == DiffVerdict.FASTER
```

- [ ] **Step 2: Run, expect FAIL** (`AttributeError: 'Session' object has no attribute 'try_hypothetical_index'`): `uv run pytest tests/engine/test_session_hypo.py -v`

- [ ] **Step 3: Implement** — in `src/pgvet/core/session.py`:

(a) add import near the top:
```python
from pgvet.core.hypo import HypoResult, try_hypothetical_index
```
(b) add the method to `Session`:
```python
    def try_hypothetical_index(self, sql: str, create_index_sql: str) -> HypoResult:
        return try_hypothetical_index(self._conn, sql, create_index_sql)
```

- [ ] **Step 4: Run new + full suite, expect PASS**: `uv run pytest tests/engine/test_session_hypo.py -v && uv run pytest -q`

- [ ] **Step 5: Commit**
```bash
git add src/pgvet/core/session.py tests/engine/test_session_hypo.py
git commit -m "feat(core): add Session.try_hypothetical_index delegate"
```

---

## Task 4: TUI candidate-index input (`tui/app.py`)

Add an optional second input for a candidate `CREATE INDEX`. It's wired only when a `hypothetical_query` callable is injected (i.e., HypoPG is available). On submit it runs the candidate against the last query and renders the estimated before/after diff in the diff pane.

**Files:** Modify `src/pgvet/tui/app.py`; Test `tests/unit/test_tui_app_hypo.py`.

*Depends on M4 Task 8 (the `#diff` Static already exists in `compose`). If M4 Task 8 is not present, add the `#diff` Static first.*

- [ ] **Step 1: Failing test** — `tests/unit/test_tui_app_hypo.py`:
```python
import pytest

from pgvet.tui.app import PgvetApp
from pgvet.core.session import RunResult
from pgvet.core.hypo import HypoResult
from pgvet.core.plandiff import PlanDiff, DiffVerdict
from pgvet.core.planmodel import NodeType
from tests.unit.advisor_helpers import node, ctx


def _run_result():
    plan = ctx(node(NodeType.SEQ_SCAN, relation="orders", est=50000, actual=50000),
               query="SELECT * FROM orders").plan
    return RunResult(query="SELECT * FROM orders", plan=plan, findings=[])


def _hypo_result():
    base = ctx(node(NodeType.SEQ_SCAN, relation="orders")).plan
    cand = ctx(node(NodeType.INDEX_SCAN, relation="orders")).plan
    diff = PlanDiff(verdict=DiffVerdict.FASTER, aligned=True,
                    time_before_ms=None, time_after_ms=None, node_deltas=[])
    return HypoResult(baseline=base, candidate=cand, diff=diff)


@pytest.mark.asyncio
async def test_hypothetical_runs_against_last_query():
    captured = {}

    def hypo(sql, create_sql):
        captured["sql"] = sql
        captured["create_sql"] = create_sql
        return _hypo_result()

    app = PgvetApp(analyze_query=lambda sql: _run_result(), hypothetical_query=hypo)
    async with app.run_test() as pilot:
        app.run_analysis("SELECT * FROM orders")   # sets last query
        await pilot.pause()
        app.run_hypothetical("CREATE INDEX ON orders (status)")
        await pilot.pause()
        assert captured["sql"] == "SELECT * FROM orders"
        assert captured["create_sql"] == "CREATE INDEX ON orders (status)"
        assert app.last_hypo_result is not None
        assert app.last_hypo_result.diff.verdict == DiffVerdict.FASTER


@pytest.mark.asyncio
async def test_hypothetical_noop_without_callable():
    app = PgvetApp(analyze_query=lambda sql: _run_result())  # no hypothetical_query
    async with app.run_test() as pilot:
        app.run_analysis("SELECT * FROM orders")
        await pilot.pause()
        app.run_hypothetical("CREATE INDEX ON orders (status)")  # must not raise
        await pilot.pause()
        assert app.last_hypo_result is None
```

- [ ] **Step 2: Run, expect FAIL**: `uv run pytest tests/unit/test_tui_app_hypo.py -v`

- [ ] **Step 3: Implement** — modify `src/pgvet/tui/app.py`:

(a) extend `__init__` to accept the optional callable and track state:
```python
    def __init__(self, analyze_query, hypothetical_query=None) -> None:
        super().__init__()
        self._analyze_query = analyze_query
        self._hypothetical_query = hypothetical_query
        self.last_result = None
        self.last_hypo_result = None
```
(b) in `compose`, add a second input beneath the query input (only meaningful when hypo is wired, but always present is fine):
```python
        yield Input(placeholder="Candidate CREATE INDEX … (Enter to test hypothetically)", id="hypo")
```
(c) route the second input in `on_input_submitted` by widget id:
```python
    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "hypo":
            self.run_hypothetical(event.value)
        else:
            self.run_analysis(event.value)
```
(d) add `run_hypothetical`:
```python
    def run_hypothetical(self, create_index_sql: str) -> None:
        if self._hypothetical_query is None or self.last_result is None:
            return
        result = self._hypothetical_query(self.last_result.query, create_index_sql)
        self.last_hypo_result = result
        self.query_one("#diff", Static).update(render_plan_diff(result.diff))
```
Ensure `render_plan_diff` is imported (added in M4 Task 8; if absent, add `from pgvet.tui.panels.plan_diff import render_plan_diff`).

- [ ] **Step 4: Run new + full suite, expect PASS**: `uv run pytest tests/unit/test_tui_app_hypo.py -v && uv run pytest -q`

- [ ] **Step 5: Commit**
```bash
git add src/pgvet/tui/app.py tests/unit/test_tui_app_hypo.py
git commit -m "feat(tui): add hypothetical-index input and estimated before/after diff"
```

---

## Task 5: Feature-gate wiring at launch (`cli.launch_tui`)

Only wire the hypothetical callable when HypoPG is actually present in the connected DB; otherwise the TUI runs without it (no crash, feature simply inert).

**Files:** Modify `src/pgvet/cli.py`; Test `tests/unit/test_cli_hypo_wiring.py`.

- [ ] **Step 1: Failing test** — `tests/unit/test_cli_hypo_wiring.py` (tests the pure selector helper, not a live DB):
```python
from pgvet.cli import _hypothetical_callable


class _Sess:
    def try_hypothetical_index(self, sql, create_sql):
        return ("ran", sql, create_sql)


def test_returns_callable_when_available():
    fn = _hypothetical_callable(_Sess(), available=True)
    assert fn is not None
    assert fn("q", "c") == ("ran", "q", "c")


def test_returns_none_when_unavailable():
    assert _hypothetical_callable(_Sess(), available=False) is None
```

- [ ] **Step 2: Run, expect FAIL** (`ImportError`): `uv run pytest tests/unit/test_cli_hypo_wiring.py -v`

- [ ] **Step 3: Implement** — in `src/pgvet/cli.py`:

(a) add the selector helper:
```python
def _hypothetical_callable(session, available: bool):
    if not available:
        return None
    return session.try_hypothetical_index
```
(b) update `launch_tui` to detect HypoPG and pass the callable (this builds on M4's `launch_tui`; add the hypo import + availability check):
```python
def launch_tui() -> int:
    from pgvet.config import Settings
    from pgvet.core.connection import Connection
    from pgvet.core.hypo import hypopg_available
    from pgvet.core.queryhash import current_git_ref
    from pgvet.storage.history import History
    from pgvet.tui.app import PgvetApp

    conn = Connection.connect(Settings.from_env())
    history = History(_default_history_path())
    session = Session(conn=conn, registry=_registry(),
                      history=history, git_ref=current_git_ref())
    hypo_fn = _hypothetical_callable(session, hypopg_available(conn))
    try:
        PgvetApp(analyze_query=session.run_query, hypothetical_query=hypo_fn).run()
    finally:
        history.close()
        conn.close()
    return 0
```
*If M4 Task 9 was not implemented, drop the `history`/`git_ref` bits and keep just the connection + hypo wiring.*

- [ ] **Step 4: Run new + full suite, expect PASS**: `uv run pytest tests/unit/test_cli_hypo_wiring.py -v && uv run pytest -q`

- [ ] **Step 5: Commit**
```bash
git add src/pgvet/cli.py tests/unit/test_cli_hypo_wiring.py
git commit -m "feat(cli): feature-gate hypothetical-index support on HypoPG availability"
```

---

## Live-DB validation (deferred — run on the connected machine, needs HypoPG)

The suite above is fully offline (fake HypoPG). On a real dev Postgres:
1. Install the extension in the dev DB: `CREATE EXTENSION IF NOT EXISTS hypopg;` (this is a one-time DBA/dev action, not something pgvet does).
2. `export DATABASE_URL=...`; `uv run pgvet tui`.
3. Run a query that seq-scans; in the candidate box, enter `CREATE INDEX ON <table> (<col>)`; confirm the estimated plan switches to an index scan and the diff reports FASTER, and that **no real index was created** (`\di` shows nothing new; `hypopg_list_indexes()` is empty after the app exits).
4. Confirm that on a DB WITHOUT HypoPG, `pgvet tui` still launches and the candidate box simply does nothing (feature inert, no crash).
5. Sanity-check the analyze/no-analyze choice: verify the candidate plan has estimated costs (it will not have actual times, by design).

---

## Self-Review

**Spec coverage (design §7 step 6, §15 M5):**
- §15 M5 "hypo.py + HypoPG integration; add hypothetical index → re-plan → compare loop" → Tasks 1–3 (primitives + loop + Session entry), 4 (TUI compare loop), 5 (feature gate). ✔
- §7 "HypoPG-powered add hypothetical index with instant re-plan; drop after" → `try_hypothetical_index` with try/finally reset (Task 2), verified by `test_try_hypothetical_index_resets_even_on_explain_error`. ✔
- §10 "HypoPG not installed → detected at startup and disabled with a note; rest works" → Task 5 feature gate (`hypopg_available` → `_hypothetical_callable` → None). ✔

**Placeholder scan:** No TBD/TODO; all code steps complete. Conditional notes ("if M4 Task 8/9 not present") are explicit and actionable, not placeholders.

**Correctness guardrails encoded:** EXPLAIN WITHOUT ANALYZE on both sides (documented + used in Task 2); always-reset via try/finally (tested); create statement bound as a parameter, not string-formatted (tested in Task 1); feature gate returns None cleanly (tested).

**Type consistency:** `hypopg_available(conn)->bool`; `create_hypothetical_index(conn, create_index_sql)->int`; `reset_hypothetical(conn)->None`; `HypoResult(baseline: PlanTree, candidate: PlanTree, diff: PlanDiff)`; `try_hypothetical_index(conn, sql, create_index_sql)->HypoResult`; `Session.try_hypothetical_index(sql, create_index_sql)->HypoResult`; `PgvetApp(analyze_query, hypothetical_query=None)` with `run_hypothetical(create_index_sql)` and `last_hypo_result`; `_hypothetical_callable(session, available)->callable|None`. Consistent across tasks and with M4's `diff_plans`/`PlanDiff`. ✔

**Dependency note:** M5 requires M4 (`pgvet.core.plandiff`). Tasks 4–5 build on M4's `#diff` pane and `launch_tui`; each such dependency is called out inline with a fallback if M4 pieces are absent.
