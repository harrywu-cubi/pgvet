from pgvet.plugins.inferencers.fk_overlap import FkOverlapInferencer
from pgvet.core.schemamodel import Column, Constraint, Table, SchemaModel
from tests.unit.inferencer_helpers import FakeSampler, sctx


def _schema(with_fk=False):
    orders_constraints = []
    if with_fk:
        orders_constraints.append(Constraint("orders_customer_id_fkey", "f", ["customer_id"],
                                             "FOREIGN KEY (customer_id) REFERENCES customers(id)"))
    return SchemaModel(tables=[
        Table(schema="public", name="orders",
              columns=[Column("customer_id", "integer", False, None)],
              constraints=orders_constraints),
        Table(schema="public", name="customers",
              columns=[Column("id", "integer", False, None)],
              constraints=[Constraint("customers_pkey", "p", ["id"], "PRIMARY KEY (id)")]),
    ])


def test_flags_undeclared_fk_when_no_orphans():
    sampler = FakeSampler(rows=1000, orphans={("orders", "customer_id"): 0.0})
    findings = list(FkOverlapInferencer().run(sctx(_schema(), sampler)))
    assert len(findings) == 1
    assert findings[0].suggestion.sql == (
        'ALTER TABLE "orders" ADD CONSTRAINT orders_customer_id_fkey '
        'FOREIGN KEY ("customer_id") REFERENCES "customers" ("id")'
    )


def test_ignores_when_orphans_exist():
    sampler = FakeSampler(rows=1000, orphans={("orders", "customer_id"): 0.02})
    assert list(FkOverlapInferencer().run(sctx(_schema(), sampler))) == []


def test_ignores_when_fk_already_declared():
    sampler = FakeSampler(rows=1000, orphans={("orders", "customer_id"): 0.0})
    assert list(FkOverlapInferencer().run(sctx(_schema(with_fk=True), sampler))) == []
