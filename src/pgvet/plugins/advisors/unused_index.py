"""Flag a seq scan on a table that has a non-unique secondary index — the index
exists but the planner chose not to use it for this query (worth a look)."""

from __future__ import annotations

from typing import Iterable

from pgvet.core.findings import Finding, Location, Severity
from pgvet.core.planmodel import NodeType
from pgvet.plugins.base import Advisor, PlanContext


class UnusedIndexAdvisor(Advisor):
    id = "advisor.unused_index"
    name = "Seq scan despite existing index"

    def run(self, ctx: PlanContext) -> Iterable[Finding]:
        for node in ctx.plan.walk():
            if node.node_type != NodeType.SEQ_SCAN or node.relation is None:
                continue
            table = ctx.schema.table(node.relation)
            if table is None:
                continue
            secondary = [ix for ix in table.indexes if not ix.unique]
            if not secondary:
                continue
            names = ", ".join(ix.name for ix in secondary)
            yield Finding(
                plugin_id=self.id,
                severity=Severity.INFO,
                title=f"Seq Scan on `{node.relation}` despite existing index",
                detail=(
                    f"`{node.relation}` has secondary index(es) [{names}] but this "
                    "query used a Seq Scan. The predicate may not match the index, "
                    "or the planner judged the scan cheaper."
                ),
                location=Location(kind="table", identifier=node.relation),
                evidence={"indexes": [ix.name for ix in secondary]},
            )
