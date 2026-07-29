from pgvet.plugins.advisors.sort_spill import SortSpillAdvisor
from pgvet.core.planmodel import NodeType
from pgvet.core.findings import Severity
from tests.unit.advisor_helpers import node, ctx


def test_flags_sort_spilling_to_disk():
    root = node(NodeType.SORT, raw={"Sort Method": "external merge", "Sort Space Used": 20480})
    findings = list(SortSpillAdvisor().run(ctx(root)))
    assert len(findings) == 1
    assert findings[0].severity == Severity.SUGGEST
    assert "work_mem" in findings[0].detail


def test_ignores_in_memory_sort():
    root = node(NodeType.SORT, raw={"Sort Method": "quicksort", "Sort Space Used": 64})
    assert list(SortSpillAdvisor().run(ctx(root))) == []


def test_ignores_non_sort_nodes():
    root = node(NodeType.SEQ_SCAN, relation="orders")
    assert list(SortSpillAdvisor().run(ctx(root))) == []
