import json

from pgvet.cli import infer_report


class _FakeConn:
    def close(self):
        pass


class _FakeSession:
    def __init__(self, conn, registry):
        pass
    def infer(self):
        from pgvet.core.findings import Finding, Severity, Location, Suggestion
        return [Finding("inferencer.not_null", Severity.SUGGEST,
                        "`orders.status` is never null but is declared nullable", "d",
                        location=Location("column", "orders.status"),
                        suggestion=Suggestion(kind="ddl",
                            sql='ALTER TABLE "orders" ALTER COLUMN "status" SET NOT NULL'))]


def _patch(monkeypatch):
    monkeypatch.setattr("pgvet.cli.Session", _FakeSession)
    monkeypatch.setattr("pgvet.cli.Connection",
                        type("C", (), {"connect": staticmethod(lambda s: _FakeConn())}))
    monkeypatch.setattr("pgvet.cli.Settings",
                        type("S", (), {"from_env": staticmethod(lambda: object())}))


def test_infer_report_text(monkeypatch):
    _patch(monkeypatch)
    out = infer_report(fmt="text")
    assert "orders.status" in out
    assert "SET NOT NULL" in out


def test_infer_report_json(monkeypatch):
    _patch(monkeypatch)
    data = json.loads(infer_report(fmt="json"))
    assert data["findings"][0]["suggestion"]["sql"].endswith("SET NOT NULL")
