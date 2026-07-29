"""Flag nodes whose row estimate diverges badly from actuals — a common cause of
bad plan choices; often means stale stats (ANALYZE) or a correlated predicate."""

from __future__ import annotations

from typing import Iterable

from pgvet.core.findings import Finding, Location, Severity, Suggestion
from pgvet.plugins.base import Advisor, PlanContext

MISESTIMATE_THRESHOLD = 100.0


class RowEstimateAdvisor(Advisor):
    id = "advisor.row_estimate"
    name = "Row-count misestimate"

    def run(self, ctx: PlanContext) -> Iterable[Finding]:
        for node in ctx.plan.walk():
            factor = node.misestimate_factor
            if factor is None or factor < MISESTIMATE_THRESHOLD:
                continue
            rel = node.relation or node.node_type.value
            yield Finding(
                plugin_id=self.id,
                severity=Severity.WARN,
                title=f"Row estimate off by {factor:.0f}× at {rel}",
                detail=(
                    f"Planner estimated {int(node.estimated_rows)} rows but got "
                    f"{int(node.total_actual_rows)}. Bad estimates lead to bad plans."
                ),
                location=Location(kind="plan_node", identifier=rel),
                evidence={"factor": factor,
                          "estimated": node.estimated_rows,
                          "actual": node.total_actual_rows},
                suggestion=Suggestion(
                    kind="note",
                    note=(f"Run ANALYZE on `{node.relation}`; consider extended "
                          "statistics if columns are correlated." if node.relation
                          else "Run ANALYZE on the involved tables."),
                ),
            )
