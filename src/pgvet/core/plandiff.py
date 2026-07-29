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
