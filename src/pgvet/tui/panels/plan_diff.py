"""Render a PlanDiff as a Rich table: one row per aligned node, with a title that
states the overall verdict and the before/after execution time."""

from __future__ import annotations

from rich.table import Table as RichTable

from pgvet.core.plandiff import DiffVerdict, PlanDiff

_VERDICT_COLOR = {
    DiffVerdict.FASTER: "green",
    DiffVerdict.SLOWER: "red",
    DiffVerdict.SAME: "dim",
    DiffVerdict.STRUCTURE_CHANGED: "yellow",
}


def render_plan_diff(diff: PlanDiff) -> RichTable:
    color = _VERDICT_COLOR.get(diff.verdict, "white")
    timing = ""
    if diff.time_before_ms is not None and diff.time_after_ms is not None:
        timing = f"  ({diff.time_before_ms:g}ms → {diff.time_after_ms:g}ms)"
    table = RichTable(title=f"[{color}]{diff.verdict.value}[/]{timing}", expand=True)
    table.add_column("Node")
    table.add_column("Where", no_wrap=True)
    table.add_column("cost Δ", justify="right")
    table.add_column("rows Δ", justify="right")
    for d in diff.node_deltas:
        node = d.node_type.replace("_", " ").title()
        if d.node_type_changed:
            node = f"[bold]{node}[/] (changed)"
        cost = f"{d.cost_before:g}→{d.cost_after:g}"
        rows = f"{d.rows_before:g}→{d.rows_after:g}"
        table.add_row(node, d.relation or "", cost, rows)
    return table
