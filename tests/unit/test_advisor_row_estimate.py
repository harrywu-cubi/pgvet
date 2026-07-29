from pgvet.plugins.advisors.row_estimate import RowEstimateAdvisor
from pgvet.core.planmodel import NodeType
from pgvet.core.findings import Severity
from tests.unit.advisor_helpers import node, ctx


def test_flags_large_misestimate():
    root = node(NodeType.SEQ_SCAN, relation="orders", est=10, actual=10000, loops=1)
    findings = list(RowEstimateAdvisor().run(ctx(root)))
    assert len(findings) == 1
    assert findings[0].severity == Severity.WARN
    assert findings[0].evidence["factor"] >= 100


def test_ignores_accurate_estimate():
    root = node(NodeType.SEQ_SCAN, relation="orders", est=1000, actual=1100)
    assert list(RowEstimateAdvisor().run(ctx(root))) == []


def test_ignores_node_without_actuals():
    root = node(NodeType.SEQ_SCAN, relation="orders", est=10, actual=None)
    assert list(RowEstimateAdvisor().run(ctx(root))) == []
