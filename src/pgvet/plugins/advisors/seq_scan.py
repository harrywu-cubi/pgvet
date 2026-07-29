"""Flag sequential scans over large relations — a classic missing-index smell."""

from __future__ import annotations

from typing import Iterable

from pgvet.core.findings import Finding, Location, Severity, Suggestion
from pgvet.core.planmodel import NodeType
from pgvet.plugins.base import Advisor, PlanContext

ROW_THRESHOLD = 10_000


class SeqScanAdvisor(Advisor):
    id = "advisor.seq_scan"
    name = "Sequential scan on large relation"

    def run(self, ctx: PlanContext) -> Iterable[Finding]:
        for node in ctx.plan.walk():
            if node.node_type != NodeType.SEQ_SCAN or node.relation is None:
                continue
            rows = node.total_actual_rows or node.estimated_rows
            if rows < ROW_THRESHOLD:
                continue
            yield Finding(
                plugin_id=self.id,
                severity=Severity.WARN,
                title=f"Seq Scan over large table `{node.relation}`",
                detail=(
                    f"Sequential scan reads ~{int(rows)} rows from "
                    f"`{node.relation}`. Consider an index on the filtered columns."
                ),
                location=Location(kind="table", identifier=node.relation),
                evidence={"rows": rows, "cost": node.estimated_cost},
                suggestion=Suggestion(
                    kind="note",
                    note=f"Inspect the WHERE/JOIN predicates on `{node.relation}` for an index candidate.",
                ),
            )
