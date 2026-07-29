"""The stable plugin contract. Every capability in pgvet is a plugin here.

MVP ships only the ADVISOR family (operates on a PlanContext). The Family enum
and context split are already in place so INFERENCER/DRIFT families can be added
later without touching the registry or session.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from pgvet.core.findings import Finding
from pgvet.core.planmodel import PlanTree
from pgvet.core.schemamodel import SchemaModel


class Family(str, Enum):
    ADVISOR = "ADVISOR"
    INFERENCER = "INFERENCER"
    DRIFT = "DRIFT"


@dataclass
class PlanContext:
    plan: PlanTree
    query: str
    schema: SchemaModel
    previous: PlanTree | None = None  # reserved for M4 plan-diff; always None in MVP


class Advisor(ABC):
    """A pure function over a PlanContext that yields Findings."""

    id: str
    name: str
    family: Family = Family.ADVISOR

    def applies_to(self, ctx: PlanContext) -> bool:  # noqa: ARG002
        return True

    @abstractmethod
    def run(self, ctx: PlanContext) -> Iterable[Finding]:
        ...
