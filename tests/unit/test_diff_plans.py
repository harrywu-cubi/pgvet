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
