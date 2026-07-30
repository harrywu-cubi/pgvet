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
