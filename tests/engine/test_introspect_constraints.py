from pgvet.core.introspect import introspect, COLUMNS_SQL, INDEXES_SQL, CONSTRAINTS_SQL


class _FakeConn:
    def __init__(self, columns, indexes, constraints):
        self._columns, self._indexes, self._constraints = columns, indexes, constraints
    def fetch_all(self, sql, params=None):
        if sql == COLUMNS_SQL: return self._columns
        if sql == INDEXES_SQL: return self._indexes
        if sql == CONSTRAINTS_SQL: return self._constraints
        raise AssertionError(f"unexpected sql: {sql!r}")


def test_introspect_populates_constraints():
    columns = [{"table_schema": "public", "table_name": "orders", "column_name": "id",
                "data_type": "integer", "is_nullable": "NO", "column_default": None}]
    constraints = [
        {"table_name": "orders", "constraint_name": "orders_pkey", "kind": "p",
         "column_names": ["id"], "definition": "PRIMARY KEY (id)"},
        {"table_name": "orders", "constraint_name": "orders_customer_fkey", "kind": "f",
         "column_names": ["customer_id"], "definition": "FOREIGN KEY (customer_id) REFERENCES customers(id)"},
    ]
    schema = introspect(_FakeConn(columns, [], constraints))
    orders = schema.table("orders")
    kinds = {c.kind for c in orders.constraints}
    assert kinds == {"p", "f"}
    pk = next(c for c in orders.constraints if c.kind == "p")
    assert pk.columns == ["id"]
