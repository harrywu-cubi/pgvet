import json
from pathlib import Path

from pgvet.core.hypo import hypopg_available, create_hypothetical_index, reset_hypothetical, try_hypothetical_index, HypoResult
from pgvet.core.plandiff import DiffVerdict

PLANS = Path(__file__).parent.parent / "fixtures" / "plans"


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
