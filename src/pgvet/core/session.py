"""The engine. Wraps a connection + a plugin registry and produces RunResults.
`analyze` is pure (great for tests and the report CLI); `run_query` is the
connect-backed path used by the TUI and `pgvet report --sql`."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pgvet.core.explain import run_explain
from pgvet.core.findings import Finding, Severity
from pgvet.core.introspect import introspect
from pgvet.core.planmodel import PlanTree
from pgvet.core.registry import Registry
from pgvet.plugins.base import PlanContext

log = logging.getLogger("pgvet.session")


@dataclass
class RunResult:
    query: str
    plan: PlanTree
    findings: list[Finding]


class Session:
    def __init__(self, conn, registry: Registry) -> None:
        self._conn = conn
        self._registry = registry

    def analyze(self, ctx: PlanContext) -> list[Finding]:
        findings: list[Finding] = []
        for advisor in self._registry.advisors:
            try:
                if advisor.applies_to(ctx):
                    findings.extend(advisor.run(ctx))
            except Exception as exc:  # noqa: BLE001 — isolate one bad plugin
                log.warning("advisor %s failed: %s", advisor.id, exc)
                findings.append(
                    Finding(
                        plugin_id=advisor.id,
                        severity=Severity.WARN,
                        title=f"Advisor {advisor.id} failed",
                        detail=str(exc),
                    )
                )
        return findings

    def run_query(self, sql: str) -> RunResult:
        plan = run_explain(self._conn, sql)
        schema = introspect(self._conn)
        ctx = PlanContext(plan=plan, query=sql, schema=schema)
        return RunResult(query=sql, plan=plan, findings=self.analyze(ctx))
