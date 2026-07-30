from pgvet.core.registry import Registry


def test_load_builtins_registers_advisors_and_inferencers():
    reg = Registry()
    reg.load_builtins()
    assert len(reg.advisors) == 5        # MVP advisor family
    assert len(reg.inferencers) == 4     # M6 inferencer family
