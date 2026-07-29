from pgvet.core.introspect import introspect, COLUMNS_SQL, INDEXES_SQL


class _FakeConn:
    """Returns canned rows based on which known SQL is executed."""
    def __init__(self, columns, indexes):
        self._columns = columns
        self._indexes = indexes
    def fetch_all(self, sql, params=None):
        if sql == COLUMNS_SQL:
            return self._columns
        if sql == INDEXES_SQL:
            return self._indexes
        raise AssertionError(f"unexpected sql: {sql!r}")


def test_introspect_builds_tables_and_columns():
    columns = [
        {"table_schema": "public", "table_name": "orders", "column_name": "id",
         "data_type": "integer", "is_nullable": "NO", "column_default": "nextval('x')"},
        {"table_schema": "public", "table_name": "orders", "column_name": "status",
         "data_type": "text", "is_nullable": "YES", "column_default": None},
    ]
    indexes = [
        {"table_name": "orders", "index_name": "orders_pkey",
         "column_names": ["id"], "is_unique": True, "predicate": None},
    ]
    schema = introspect(_FakeConn(columns, indexes))
    orders = schema.table("orders")
    assert orders is not None
    assert [c.name for c in orders.columns] == ["id", "status"]
    assert orders.column("id").nullable is False
    assert orders.column("status").nullable is True
    assert orders.indexes[0].unique is True
    assert orders.indexes[0].columns == ["id"]
