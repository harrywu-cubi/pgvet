from pgvet.plugins.advisors.unused_index import UnusedIndexAdvisor
from pgvet.core.planmodel import NodeType
from pgvet.core.findings import Severity
from pgvet.core.schemamodel import Column, Index, Table, SchemaModel
from tests.unit.advisor_helpers import node, ctx


def _schema_with_status_index():
    return SchemaModel(tables=[Table(
        schema="public", name="orders",
        columns=[Column("status", "text", True, None)],
        indexes=[Index(name="ix_orders_status", columns=["status"], unique=False, predicate=None)],
    )])


def test_flags_seq_scan_when_secondary_index_exists():
    root = node(NodeType.SEQ_SCAN, relation="orders", est=50000, actual=50000)
    findings = list(UnusedIndexAdvisor().run(ctx(root, schema=_schema_with_status_index())))
    assert len(findings) == 1
    assert findings[0].severity == Severity.INFO
    assert "ix_orders_status" in findings[0].detail


def test_no_finding_when_no_secondary_index():
    root = node(NodeType.SEQ_SCAN, relation="orders", est=50000, actual=50000)
    empty = SchemaModel(tables=[Table(schema="public", name="orders")])
    assert list(UnusedIndexAdvisor().run(ctx(root, schema=empty))) == []
