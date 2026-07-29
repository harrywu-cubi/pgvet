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
