from pgvet.core.connection import Connection


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
    def fetchall(self):
        return self._rows
    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeRaw:
    def __init__(self, rows):
        self._rows = rows
        self.executed = []
    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        return _FakeCursor(self._rows)
    def close(self):
        self.closed = True


def test_fetch_all_delegates_to_raw():
    raw = _FakeRaw([{"a": 1}, {"a": 2}])
    conn = Connection(raw)
    assert conn.fetch_all("SELECT a") == [{"a": 1}, {"a": 2}]
    assert raw.executed[0][0] == "SELECT a"


def test_fetch_one_returns_first_row_or_none():
    assert Connection(_FakeRaw([{"a": 1}])).fetch_one("q") == {"a": 1}
    assert Connection(_FakeRaw([])).fetch_one("q") is None
