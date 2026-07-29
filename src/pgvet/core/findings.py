"""The single output type every pgvet plugin emits."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    INFO = "INFO"
    SUGGEST = "SUGGEST"
    WARN = "WARN"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class Location:
    kind: str  # "table" | "column" | "plan_node"
    identifier: str


@dataclass(frozen=True)
class Suggestion:
    kind: str  # "ddl" | "rewrite" | "note"
    sql: str | None = None
    note: str = ""


@dataclass(frozen=True)
class Finding:
    plugin_id: str
    severity: Severity
    title: str
    detail: str
    location: Location | None = None
    evidence: dict = field(default_factory=dict)
    suggestion: Suggestion | None = None
