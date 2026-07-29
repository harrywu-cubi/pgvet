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
