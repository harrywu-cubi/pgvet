from pgvet.core.registry import Registry
from pgvet.plugins.advisors import register_builtins


def test_register_builtins_adds_all_advisors():
    reg = Registry()
    register_builtins(reg)
    ids = {a.id for a in reg.advisors}
    assert ids == {
        "advisor.seq_scan",
        "advisor.row_estimate",
        "advisor.sort_spill",
        "advisor.nested_loop",
        "advisor.unused_index",
    }
