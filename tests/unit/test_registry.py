import logging

from pgvet.core.registry import Registry
from pgvet.plugins.base import Advisor
from pgvet.core.findings import Finding, Severity


class _A(Advisor):
    id = "advisor.a"
    name = "A"
    def run(self, ctx):
        yield Finding(self.id, Severity.INFO, "a", "d")


class _B(Advisor):
    id = "advisor.b"
    name = "B"
    def run(self, ctx):
        return []


def test_register_and_list_advisors():
    reg = Registry()
    reg.register(_A())
    reg.register(_B())
    assert {a.id for a in reg.advisors} == {"advisor.a", "advisor.b"}


def test_duplicate_id_rejected():
    reg = Registry()
    reg.register(_A())
    try:
        reg.register(_A())
        assert False, "expected ValueError on duplicate id"
    except ValueError:
        pass


def test_broken_entry_point_is_isolated(caplog):
    reg = Registry()

    class _BrokenEP:
        name = "broken"
        def load(self):
            raise RuntimeError("boom")

    with caplog.at_level(logging.WARNING):
        reg.discover(entry_points=[_BrokenEP()])
    assert "broken" in caplog.text
    assert reg.advisors == []  # nothing registered, no crash


def test_good_entry_point_registers(caplog):
    reg = Registry()

    class _GoodEP:
        name = "good"
        def load(self):
            def register(registry):
                registry.register(_A())
            return register

    reg.discover(entry_points=[_GoodEP()])
    assert [a.id for a in reg.advisors] == ["advisor.a"]
