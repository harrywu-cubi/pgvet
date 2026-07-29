from pgvet.plugins.advisors.nested_loop import NestedLoopAdvisor
from pgvet.core.planmodel import NodeType
from pgvet.core.findings import Severity
from tests.unit.advisor_helpers import node, ctx


def test_flags_nested_loop_with_high_inner_loops():
    inner = node(NodeType.INDEX_SCAN, relation="customers", est=1, actual=1, loops=50000)
    root = node(NodeType.NESTED_LOOP, children=[inner])
    findings = list(NestedLoopAdvisor().run(ctx(root)))
    assert len(findings) == 1
    assert findings[0].severity == Severity.WARN
    assert findings[0].evidence["loops"] == 50000


def test_ignores_low_loop_nested_loop():
    inner = node(NodeType.INDEX_SCAN, relation="customers", loops=5)
    root = node(NodeType.NESTED_LOOP, children=[inner])
    assert list(NestedLoopAdvisor().run(ctx(root))) == []
