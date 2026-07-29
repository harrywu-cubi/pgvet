import json
from pathlib import Path

from pgvet.core.explain import run_explain
from pgvet.core.planmodel import NodeType

FIXTURE = Path(__file__).parent.parent / "fixtures" / "plans" / "seq_scan.json"


class _FakeConn:
    def __init__(self, payload):
        self._payload = payload
        self.last_sql = None
    def fetch_one(self, sql, params=None):
        self.last_sql = sql
        return {"QUERY PLAN": self._payload}


def test_run_explain_wraps_query_and_parses():
    payload = json.loads(FIXTURE.read_text())
    conn = _FakeConn(payload)
    tree = run_explain(conn, "SELECT * FROM orders o JOIN customers c ON c.id=o.customer_id")
    assert tree.root.node_type == NodeType.NESTED_LOOP
    assert tree.query == "SELECT * FROM orders o JOIN customers c ON c.id=o.customer_id"
    assert conn.last_sql.startswith("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)")


def test_run_explain_without_analyze():
    payload = json.loads(FIXTURE.read_text())
    conn = _FakeConn(payload)
    run_explain(conn, "SELECT 1", analyze=False)
    assert conn.last_sql.startswith("EXPLAIN (BUFFERS, FORMAT JSON)")
