"""Normalized, Postgres-version-independent execution-plan model.

Plugins depend ONLY on this module, never on raw EXPLAIN JSON. All version-
specific mapping lives in `explain.parse_explain_json`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterator


class NodeType(str, Enum):
    SEQ_SCAN = "SEQ_SCAN"
    INDEX_SCAN = "INDEX_SCAN"
    INDEX_ONLY_SCAN = "INDEX_ONLY_SCAN"
    BITMAP_HEAP_SCAN = "BITMAP_HEAP_SCAN"
    BITMAP_INDEX_SCAN = "BITMAP_INDEX_SCAN"
    NESTED_LOOP = "NESTED_LOOP"
    HASH_JOIN = "HASH_JOIN"
    MERGE_JOIN = "MERGE_JOIN"
    HASH = "HASH"
    SORT = "SORT"
    AGGREGATE = "AGGREGATE"
    LIMIT = "LIMIT"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_pg(cls, raw: str) -> "NodeType":
        mapping = {
            "Seq Scan": cls.SEQ_SCAN,
            "Index Scan": cls.INDEX_SCAN,
            "Index Only Scan": cls.INDEX_ONLY_SCAN,
            "Bitmap Heap Scan": cls.BITMAP_HEAP_SCAN,
            "Bitmap Index Scan": cls.BITMAP_INDEX_SCAN,
            "Nested Loop": cls.NESTED_LOOP,
            "Hash Join": cls.HASH_JOIN,
            "Merge Join": cls.MERGE_JOIN,
            "Hash": cls.HASH,
            "Sort": cls.SORT,
            "Aggregate": cls.AGGREGATE,
            "Limit": cls.LIMIT,
        }
        return mapping.get(raw, cls.UNKNOWN)


@dataclass
class PlanNode:
    node_type: NodeType
    relation: str | None
    estimated_rows: float
    actual_rows: float | None  # per-loop, as Postgres reports
    estimated_cost: float
    actual_time_ms: float | None
    loops: float
    children: list["PlanNode"]
    raw: dict

    @property
    def total_actual_rows(self) -> float | None:
        if self.actual_rows is None:
            return None
        return self.actual_rows * self.loops

    @property
    def misestimate_factor(self) -> float | None:
        actual = self.total_actual_rows
        if actual is None or actual <= 0 or self.estimated_rows <= 0:
            return None
        return max(self.estimated_rows / actual, actual / self.estimated_rows)


@dataclass
class PlanTree:
    root: PlanNode
    planning_time_ms: float | None
    execution_time_ms: float | None
    query: str | None = None

    def walk(self) -> Iterator[PlanNode]:
        stack = [self.root]
        while stack:
            node = stack.pop(0)
            yield node
            stack = node.children + stack

    def to_payload(self) -> list:
        """Reconstruct the EXPLAIN (FORMAT JSON) payload this tree came from.

        `root.raw` is the original "Plan" dict (with nested "Plans"), so re-wrapping
        it with the timings yields a structure parse_explain_json accepts."""
        return [
            {
                "Plan": self.root.raw,
                "Planning Time": self.planning_time_ms,
                "Execution Time": self.execution_time_ms,
            }
        ]
