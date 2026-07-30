from pgvet.plugins.inferencers.enum import EnumInferencer, ENUM_MAX
from pgvet.core.schemamodel import Column, Table, SchemaModel
from tests.unit.inferencer_helpers import FakeSampler, sctx


def _schema():
    return SchemaModel(tables=[Table(schema="public", name="orders", columns=[
        Column("status", "text", nullable=False, default=None),
        Column("note", "text", nullable=True, default=None),
    ])])


def test_flags_low_cardinality_text_column():
    sampler = FakeSampler(
        rows=10000,
        distincts={("orders", "status"): 4, ("orders", "note"): 9000},
        values={("orders", "status"): ["open", "paid", "shipped", "cancelled"]},
    )
    findings = list(EnumInferencer().run(sctx(_schema(), sampler)))
    ids = [f.location.identifier for f in findings]
    assert "orders.status" in ids
    assert "orders.note" not in ids
    status = next(f for f in findings if f.location.identifier == "orders.status")
    assert status.suggestion.sql == (
        'ALTER TABLE "orders" ADD CONSTRAINT orders_status_check '
        "CHECK (\"status\" IN ('open', 'paid', 'shipped', 'cancelled'))"
    )


def test_ignores_high_cardinality():
    sampler = FakeSampler(rows=10000, distincts={("orders", "status"): ENUM_MAX + 1, ("orders", "note"): 9000})
    assert list(EnumInferencer().run(sctx(_schema(), sampler))) == []
