from pgvet.plugins.inferencers.unique import UniqueInferencer
from pgvet.core.schemamodel import Column, Index, Table, SchemaModel
from tests.unit.inferencer_helpers import FakeSampler, sctx


def _schema():
    return SchemaModel(tables=[Table(schema="public", name="users", columns=[
        Column("email", "text", nullable=False, default=None),
    ])])


def test_flags_effectively_unique_column():
    sampler = FakeSampler(rows=500, distincts={("users", "email"): 500})
    findings = list(UniqueInferencer().run(sctx(_schema(), sampler)))
    assert len(findings) == 1
    assert findings[0].suggestion.sql == 'ALTER TABLE "users" ADD CONSTRAINT users_email_key UNIQUE ("email")'


def test_ignores_column_with_duplicates():
    sampler = FakeSampler(rows=500, distincts={("users", "email"): 480})
    assert list(UniqueInferencer().run(sctx(_schema(), sampler))) == []


def test_ignores_already_unique_column():
    schema = SchemaModel(tables=[Table(schema="public", name="users",
        columns=[Column("email", "text", False, None)],
        indexes=[Index(name="users_email_idx", columns=["email"], unique=True, predicate=None)])])
    sampler = FakeSampler(rows=500, distincts={("users", "email"): 500})
    assert list(UniqueInferencer().run(sctx(schema, sampler))) == []
