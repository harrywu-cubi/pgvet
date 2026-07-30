"""The engine. Wraps a connection + a plugin registry and produces RunResults.
`analyze` is pure (great for tests and the report CLI); `run_query` is the
connect-backed path used by the TUI and `pgvet report --sql`."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from pgvet.core.explain import parse_explain_json, run_explain
from pgvet.core.findings import Finding, Severity
from pgvet.core.hypo import HypoResult, try_hypothetical_index
from pgvet.core.introspect import introspect
from pgvet.core.plandiff import PlanDiff, diff_plans
from pgvet.core.planmodel import PlanTree
from pgvet.core.queryhash import hash_query
from pgvet.core.registry import Registry
from pgvet.core.sampler import Sampler
from pgvet.plugins.base import PlanContext, SchemaContext

log = logging.getLogger("pgvet.session")


@dataclass
class RunResult:
    query: str
    plan: PlanTree
    findings: list[Finding]
    previous: PlanTree | None = None
    diff: PlanDiff | None = None


class Session:
    def __init__(self, conn, registry: Registry, history=None,
                 git_ref: str | None = None, clock=None) -> None:
        self._conn = conn
        self._registry = registry
        self._history = history
        self._git_ref = git_ref
        # clock() returns an ISO timestamp string; injected for deterministic tests.
        self._clock = clock or (lambda: __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat())

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

        previous = None
        diff = None
        if self._history is not None:
            qhash = hash_query(sql)
            prev_row = self._history.latest(qhash)
            if prev_row is not None:
                previous = parse_explain_json(json.loads(prev_row["plan_json"]))
                diff = diff_plans(previous, plan)
            self._history.record(
                query_hash=qhash, git_ref=self._git_ref, recorded_at=self._clock(),
                execution_time_ms=plan.execution_time_ms, plan_json=json.dumps(plan.to_payload()),
            )

        ctx = PlanContext(plan=plan, query=sql, schema=schema, previous=previous)
        return RunResult(query=sql, plan=plan, findings=self.analyze(ctx),
                         previous=previous, diff=diff)

    def infer(self) -> list[Finding]:
        schema = introspect(self._conn)
        ctx = SchemaContext(schema=schema, sampler=Sampler(self._conn))
        findings: list[Finding] = []
        for inferencer in self._registry.inferencers:
            try:
                findings.extend(inferencer.run(ctx))
            except Exception as exc:  # noqa: BLE001 — isolate one bad plugin
                log.warning("inferencer %s failed: %s", inferencer.id, exc)
                findings.append(
                    Finding(
                        plugin_id=inferencer.id,
                        severity=Severity.WARN,
                        title=f"Inferencer {inferencer.id} failed",
                        detail=str(exc),
                    )
                )
        return findings

    def try_hypothetical_index(self, sql: str, create_index_sql: str) -> HypoResult:
        return try_hypothetical_index(self._conn, sql, create_index_sql)
