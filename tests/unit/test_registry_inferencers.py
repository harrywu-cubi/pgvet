from pgvet.core.registry import Registry, INFERENCER_GROUP
from pgvet.plugins.base import Advisor, Inferencer
from pgvet.core.findings import Finding, Severity


class _A(Advisor):
    id = "advisor.a"; name = "A"
    def run(self, ctx): return []


class _I(Inferencer):
    id = "inferencer.i"; name = "I"
    def run(self, ctx): return []


def test_register_routes_by_family():
    reg = Registry()
    reg.register(_A())
    reg.register(_I())
    assert [a.id for a in reg.advisors] == ["advisor.a"]
    assert [i.id for i in reg.inferencers] == ["inferencer.i"]


def test_inferencer_group_constant():
    assert INFERENCER_GROUP == "pgvet.inferencers"
