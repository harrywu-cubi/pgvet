from pgvet.core.schemamodel import Column, Index, Constraint, Table, SchemaModel


def _orders() -> Table:
    return Table(
        schema="public",
        name="orders",
        columns=[
            Column(name="id", data_type="integer", nullable=False, default="nextval(...)"),
            Column(name="status", data_type="text", nullable=True, default=None),
        ],
        indexes=[Index(name="orders_pkey", columns=["id"], unique=True, predicate=None)],
        constraints=[Constraint(name="orders_pkey", kind="p", columns=["id"], definition="PRIMARY KEY (id)")],
    )


def test_schema_lookup_by_name():
    schema = SchemaModel(tables=[_orders()])
    t = schema.table("orders")
    assert t is not None
    assert t.column("status").nullable is True
    assert schema.table("missing") is None


def test_table_has_unique_index_on():
    t = _orders()
    assert t.has_unique_on(["id"]) is True
    assert t.has_unique_on(["status"]) is False
