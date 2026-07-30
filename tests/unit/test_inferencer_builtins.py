from pgvet.core.registry import Registry
from pgvet.plugins.inferencers import register_builtins


def test_register_builtins_adds_all_inferencers():
    reg = Registry()
    register_builtins(reg)
    assert {i.id for i in reg.inferencers} == {
        "inferencer.not_null",
        "inferencer.unique",
        "inferencer.enum",
        "inferencer.fk_overlap",
    }
