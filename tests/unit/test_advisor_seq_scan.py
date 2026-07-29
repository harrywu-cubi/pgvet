from pgvet.plugins.advisors.seq_scan import SeqScanAdvisor
from pgvet.core.planmodel import NodeType
from pgvet.core.findings import Severity
from tests.unit.advisor_helpers import node, ctx


def test_flags_seq_scan_over_row_threshold():
    root = node(NodeType.SEQ_SCAN, relation="orders", est=50000, actual=50000)
    findings = list(SeqScanAdvisor().run(ctx(root)))
    assert len(findings) == 1
    assert findings[0].severity == Severity.WARN
    assert findings[0].location.identifier == "orders"


def test_ignores_small_seq_scan():
    root = node(NodeType.SEQ_SCAN, relation="tiny", est=10, actual=10)
    assert list(SeqScanAdvisor().run(ctx(root))) == []


def test_ignores_index_scan():
    root = node(NodeType.INDEX_SCAN, relation="orders", est=50000, actual=50000)
    assert list(SeqScanAdvisor().run(ctx(root))) == []
