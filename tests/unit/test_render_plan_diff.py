from rich.table import Table as RichTable

from pgvet.tui.panels.plan_diff import render_plan_diff
from pgvet.core.plandiff import PlanDiff, NodeDelta, DiffVerdict


def _diff(verdict, deltas=None):
    return PlanDiff(verdict=verdict, aligned=(verdict != DiffVerdict.STRUCTURE_CHANGED),
                    time_before_ms=13.1, time_after_ms=1.9, node_deltas=deltas or [])


def test_render_faster_diff_has_rows():
    d = NodeDelta("SEQ_SCAN", "orders", 200, 5, 950, 950, 8.0, 0.2, node_type_changed=True)
    table = render_plan_diff(_diff(DiffVerdict.FASTER, [d]))
    assert isinstance(table, RichTable)
    assert table.row_count == 1
    assert table.title is not None and "FASTER" in str(table.title)


def test_render_structure_changed_has_no_rows():
    table = render_plan_diff(_diff(DiffVerdict.STRUCTURE_CHANGED))
    assert "STRUCTURE_CHANGED" in str(table.title)
    assert table.row_count == 0
