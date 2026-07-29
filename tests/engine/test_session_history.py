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
