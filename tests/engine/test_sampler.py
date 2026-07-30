from pgvet.core.sampler import Sampler, Stat


class _FakeConn:
    """Answers by inspecting SQL keywords. Records the last SQL executed."""
    def __init__(self, n=100, nulls=0, distinct=0, values=None, ratio=0.0):
        self._n, self._nulls, self._distinct = n, nulls, distinct
        self._values = values or []
        self._ratio = ratio
        self.last_sql = None
    def fetch_one(self, sql, params=None):
        self.last_sql = sql
        if "LEFT JOIN" in sql:            return {"ratio": self._ratio}
        if "IS NULL" in sql:              return {"n": self._nulls}
        if "count(DISTINCT" in sql:       return {"n": self._distinct}
        if "count(*)" in sql:             return {"n": self._n}
        raise AssertionError(sql)
    def fetch_all(self, sql, params=None):
        self.last_sql = sql
        return [{"v": v} for v in self._values]


def test_row_count_is_exact_and_cached():
    conn = _FakeConn(n=42)
    s = Sampler(conn)
    assert s.row_count("orders") == Stat(value=42, sampled=False, sample_size=42)
    # cached: a second call doesn't depend on conn returning again
    assert s.row_count("orders").value == 42


def test_null_and_distinct_full_scan_under_threshold():
    conn = _FakeConn(n=100, nulls=0, distinct=100)
    s = Sampler(conn, full_scan_threshold=1000)
    nc = s.null_count("orders", "status")
    dc = s.distinct_count("orders", "status")
    assert nc.value == 0 and nc.sampled is False and nc.sample_size == 100
    assert dc.value == 100 and dc.sampled is False


def test_sampled_above_threshold_uses_tablesample():
    conn = _FakeConn(n=1_000_000, nulls=0)
    s = Sampler(conn, full_scan_threshold=10)
    nc = s.null_count("orders", "status")
    assert nc.sampled is True
    assert "TABLESAMPLE" in conn.last_sql
    assert nc.sample_size <= 1_000_000


def test_distinct_values_and_orphan_ratio():
    conn = _FakeConn(values=["open", "paid"], ratio=0.0)
    s = Sampler(conn, full_scan_threshold=1000)
    assert s.distinct_values("orders", "status", 12) == ["open", "paid"]
    r = s.orphan_ratio("orders", "customer_id", "customers", "id")
    assert r.value == 0.0
