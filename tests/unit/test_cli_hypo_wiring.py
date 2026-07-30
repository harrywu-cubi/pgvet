from pgvet.cli import _hypothetical_callable


class _Sess:
    def try_hypothetical_index(self, sql, create_sql):
        return ("ran", sql, create_sql)


def test_returns_callable_when_available():
    fn = _hypothetical_callable(_Sess(), available=True)
    assert fn is not None
    assert fn("q", "c") == ("ran", "q", "c")


def test_returns_none_when_unavailable():
    assert _hypothetical_callable(_Sess(), available=False) is None
