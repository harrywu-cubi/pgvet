from pgvet.core.plandiff import NodeDelta, PlanDiff, DiffVerdict


def test_verdict_members():
    assert {v.value for v in DiffVerdict} == {"FASTER", "SLOWER", "SAME", "STRUCTURE_CHANGED"}


def test_nodedelta_and_plandiff_fields():
    d = NodeDelta(
        node_type="SEQ_SCAN", relation="orders",
        cost_before=200.0, cost_after=5.0,
        rows_before=950, rows_after=950,
        time_before=8.0, time_after=0.2,
        node_type_changed=False,
    )
    diff = PlanDiff(verdict=DiffVerdict.FASTER, aligned=True,
                    time_before_ms=13.1, time_after_ms=1.0, node_deltas=[d])
    assert diff.verdict == "FASTER"
    assert diff.aligned is True
    assert diff.node_deltas[0].cost_after == 5.0
