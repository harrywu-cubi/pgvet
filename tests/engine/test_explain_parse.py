import json
from pathlib import Path

from pgvet.core.explain import parse_explain_json
from pgvet.core.planmodel import NodeType

FIXTURE = Path(__file__).parent.parent / "fixtures" / "plans" / "seq_scan.json"


def _tree():
    payload = json.loads(FIXTURE.read_text())
    return parse_explain_json(payload)


def test_parses_root_and_timings():
    tree = _tree()
    assert tree.root.node_type == NodeType.NESTED_LOOP
    assert tree.planning_time_ms == 0.35
    assert tree.execution_time_ms == 13.1


def test_parses_children_and_relations():
    tree = _tree()
    children = tree.root.children
    assert [c.node_type for c in children] == [NodeType.SEQ_SCAN, NodeType.INDEX_SCAN]
    assert children[0].relation == "orders"
    assert children[1].loops == 950


def test_seq_scan_misestimate_detected():
    tree = _tree()
    seq = tree.root.children[0]
    assert seq.estimated_rows == 100
    assert seq.total_actual_rows == 950
    assert round(seq.misestimate_factor, 1) == 9.5


def test_unknown_node_type_degrades_gracefully():
    payload = [{"Plan": {"Node Type": "Gather Merge Turbo", "Plan Rows": 1,
                         "Total Cost": 1.0, "Plans": []}}]
    tree = parse_explain_json(payload)
    assert tree.root.node_type == NodeType.UNKNOWN
    assert tree.root.raw["Node Type"] == "Gather Merge Turbo"
