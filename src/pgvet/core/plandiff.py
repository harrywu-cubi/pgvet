"""Plan-to-plan diff model. Pure dataclasses; the diff algorithm is in diff_plans
(same module, added next task). Node alignment is positional + node-type based;
when the two plans don't align confidently the verdict is STRUCTURE_CHANGED rather
than a misleading node-by-node diff."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DiffVerdict(str, Enum):
    FASTER = "FASTER"
    SLOWER = "SLOWER"
    SAME = "SAME"
    STRUCTURE_CHANGED = "STRUCTURE_CHANGED"


@dataclass
class NodeDelta:
    node_type: str
    relation: str | None
    cost_before: float
    cost_after: float
    rows_before: float
    rows_after: float
    time_before: float | None
    time_after: float | None
    node_type_changed: bool


@dataclass
class PlanDiff:
    verdict: DiffVerdict
    aligned: bool
    time_before_ms: float | None
    time_after_ms: float | None
    node_deltas: list[NodeDelta] = field(default_factory=list)


from pgvet.core.planmodel import PlanTree  # noqa: E402  (kept near algorithm for clarity)

SAME_THRESHOLD = 0.10  # ±10% is "no meaningful change"


def _metric(tree: PlanTree) -> float | None:
    if tree.execution_time_ms is not None:
        return tree.execution_time_ms
    return tree.root.estimated_cost


def diff_plans(before: PlanTree, after: PlanTree) -> PlanDiff:
    before_nodes = list(before.walk())
    after_nodes = list(after.walk())

    if len(before_nodes) != len(after_nodes):
        return PlanDiff(
            verdict=DiffVerdict.STRUCTURE_CHANGED, aligned=False,
            time_before_ms=before.execution_time_ms, time_after_ms=after.execution_time_ms,
        )

    deltas = [
        NodeDelta(
            node_type=a.node_type.value,
            relation=a.relation or b.relation,
            cost_before=b.estimated_cost, cost_after=a.estimated_cost,
            rows_before=b.estimated_rows, rows_after=a.estimated_rows,
            time_before=b.actual_time_ms, time_after=a.actual_time_ms,
            node_type_changed=(a.node_type != b.node_type),
        )
        for b, a in zip(before_nodes, after_nodes)
    ]

    mb, ma = _metric(before), _metric(after)
    if mb is None or ma is None or mb == 0:
        verdict = DiffVerdict.SAME
    elif ma < mb * (1 - SAME_THRESHOLD):
        verdict = DiffVerdict.FASTER
    elif ma > mb * (1 + SAME_THRESHOLD):
        verdict = DiffVerdict.SLOWER
    else:
        verdict = DiffVerdict.SAME

    return PlanDiff(
        verdict=verdict, aligned=True,
        time_before_ms=before.execution_time_ms, time_after_ms=after.execution_time_ms,
        node_deltas=deltas,
    )
