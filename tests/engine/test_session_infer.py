from pgvet.core.session import Session
from pgvet.core.registry import Registry
from pgvet.plugins.base import Inferencer, SchemaContext
from pgvet.core.findings import Finding, Severity
from pgvet.core.schemamodel import SchemaModel


class _Fires(Inferencer):
    id = "inferencer.fires"; name = "F"
    def run(self, ctx):
        yield Finding(self.id, Severity.SUGGEST, "found", "d")


class _Boom(Inferencer):
    id = "inferencer.boom"; name = "B"
    def run(self, ctx):
        raise RuntimeError("kaboom")


def test_infer_runs_inferencers_and_isolates_errors(monkeypatch):
    reg = Registry()
    reg.register(_Fires())
    reg.register(_Boom())
    sess = Session(conn=object(), registry=reg)
    monkeypatch.setattr("pgvet.core.session.introspect", lambda conn: SchemaModel())
    monkeypatch.setattr("pgvet.core.session.Sampler", lambda conn: object())

    findings = sess.infer()
    ids = {f.plugin_id for f in findings}
    assert "inferencer.fires" in ids
    boom = [f for f in findings if f.plugin_id == "inferencer.boom"]
    assert len(boom) == 1 and boom[0].severity == Severity.WARN
