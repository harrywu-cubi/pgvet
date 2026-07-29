"""Flag sorts that spilled to disk (external merge) — usually means work_mem is
too low for this query."""

from __future__ import annotations

from typing import Iterable

from pgvet.core.findings import Finding, Location, Severity, Suggestion
from pgvet.core.planmodel import NodeType
from pgvet.plugins.base import Advisor, PlanContext


class SortSpillAdvisor(Advisor):
    id = "advisor.sort_spill"
    name = "Sort spilled to disk"

    def run(self, ctx: PlanContext) -> Iterable[Finding]:
        for node in ctx.plan.walk():
            if node.node_type != NodeType.SORT:
                continue
            method = str(node.raw.get("Sort Method", "")).lower()
            if "external" not in method:
                continue
            kb = node.raw.get("Sort Space Used")
            yield Finding(
                plugin_id=self.id,
                severity=Severity.SUGGEST,
                title="Sort spilled to disk (external merge)",
                detail=(
                    f"A Sort node used an external merge (~{kb} kB on disk). "
                    "Raising work_mem may keep this sort in memory."
                ),
                location=Location(kind="plan_node", identifier="Sort"),
                evidence={"sort_method": node.raw.get("Sort Method"), "space_kb": kb},
                suggestion=Suggestion(
                    kind="note",
                    note="Increase work_mem for this session/query, or reduce the sorted set.",
                ),
            )
