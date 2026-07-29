"""Flag nested loops whose inner side executes a very high number of loops — often
a row-misestimate causing an accidental O(n·m) join."""

from __future__ import annotations

from typing import Iterable

from pgvet.core.findings import Finding, Location, Severity, Suggestion
from pgvet.core.planmodel import NodeType
from pgvet.plugins.base import Advisor, PlanContext

LOOP_THRESHOLD = 10_000


class NestedLoopAdvisor(Advisor):
    id = "advisor.nested_loop"
    name = "High-iteration nested loop"

    def run(self, ctx: PlanContext) -> Iterable[Finding]:
        for node in ctx.plan.walk():
            if node.node_type != NodeType.NESTED_LOOP:
                continue
            max_loops = max((c.loops for c in node.children), default=0)
            if max_loops < LOOP_THRESHOLD:
                continue
            yield Finding(
                plugin_id=self.id,
                severity=Severity.WARN,
                title=f"Nested loop iterating {int(max_loops)}×",
                detail=(
                    "A nested-loop join runs its inner side a very high number of "
                    "times. If the planner misestimated rows, a hash/merge join may "
                    "be far cheaper."
                ),
                location=Location(kind="plan_node", identifier="Nested Loop"),
                evidence={"loops": max_loops},
                suggestion=Suggestion(
                    kind="note",
                    note="Check row estimates on the outer side; ensure the join keys are indexed.",
                ),
            )
