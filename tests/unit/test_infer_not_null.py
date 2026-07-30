from pgvet.plugins.inferencers.not_null import NotNullInferencer
from pgvet.core.schemamodel import Column, Table, SchemaModel
from pgvet.core.findings import Severity
from tests.unit.inferencer_helpers import FakeSampler, sctx


def _schema():
    return SchemaModel(tables=[Table(schema="public", name="orders", columns=[
        Column("id", "integer", nullable=False, default=None),      # already NOT NULL
        Column("status", "text", nullable=True, default=None),      # nullable, never null
    ])])


def test_flags_never_null_nullable_column():
    sampler = FakeSampler(rows=1000, nulls={("orders", "status"): 0})
    findings = list(NotNullInferencer().run(sctx(_schema(), sampler)))
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == Severity.SUGGEST
    assert f.location.identifier == "orders.status"
    assert f.suggestion.sql == 'ALTER TABLE "orders" ALTER COLUMN "status" SET NOT NULL'


def test_ignores_column_with_nulls():
    sampler = FakeSampler(rows=1000, nulls={("orders", "status"): 3})
    assert list(NotNullInferencer().run(sctx(_schema(), sampler))) == []


def test_ignores_already_not_null_column():
    # only "status" is nullable; "id" is NOT NULL and must never be flagged
    sampler = FakeSampler(rows=1000, nulls={("orders", "status"): 0, ("orders", "id"): 0})
    ids = [f.location.identifier for f in NotNullInferencer().run(sctx(_schema(), sampler))]
    assert "orders.id" not in ids
