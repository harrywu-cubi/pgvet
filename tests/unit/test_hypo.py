from pgvet.core.hypo import hypopg_available, create_hypothetical_index, reset_hypothetical


class _FakeConn:
    """Simulates HypoPG. Records SQL; returns canned rows by SQL content."""
    def __init__(self, has_hypopg=True):
        self.has_hypopg = has_hypopg
        self.calls = []
    def fetch_one(self, sql, params=None):
        self.calls.append((sql, params))
        if "pg_extension" in sql:
            return {"ok": 1} if self.has_hypopg else None
        if "hypopg_create_index" in sql:
            return {"indexrelid": 98765, "indexname": "<hypo>"}
        if "hypopg_reset" in sql:
            return {"hypopg_reset": ""}
        raise AssertionError(f"unexpected fetch_one: {sql!r}")
    def fetch_all(self, sql, params=None):
        self.calls.append((sql, params))
        return []


def test_hypopg_available_true_and_false():
    assert hypopg_available(_FakeConn(has_hypopg=True)) is True
    assert hypopg_available(_FakeConn(has_hypopg=False)) is False


def test_create_hypothetical_index_returns_indexrelid():
    conn = _FakeConn()
    relid = create_hypothetical_index(conn, "CREATE INDEX ON orders (status)")
    assert relid == 98765
    # the CREATE statement is passed as a parameter, not string-formatted
    create_call = [c for c in conn.calls if "hypopg_create_index" in c[0]][0]
    assert create_call[1] == ("CREATE INDEX ON orders (status)",)


def test_reset_hypothetical_calls_hypopg_reset():
    conn = _FakeConn()
    reset_hypothetical(conn)
    assert any("hypopg_reset" in c[0] for c in conn.calls)
