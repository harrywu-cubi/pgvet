"""Normalized relational schema model.

Produced from a live DB by `introspect.introspect`. Later families (drift) will
also produce it from ORM metadata, so both sides compare as the same type.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Column:
    name: str
    data_type: str
    nullable: bool
    default: str | None


@dataclass
class Index:
    name: str
    columns: list[str]
    unique: bool
    predicate: str | None


@dataclass
class Constraint:
    name: str
    kind: str  # p=primary, f=foreign, u=unique, c=check
    columns: list[str]
    definition: str


@dataclass
class Table:
    schema: str
    name: str
    columns: list[Column] = field(default_factory=list)
    indexes: list[Index] = field(default_factory=list)
    constraints: list[Constraint] = field(default_factory=list)

    def column(self, name: str) -> Column | None:
        return next((c for c in self.columns if c.name == name), None)

    def has_unique_on(self, columns: list[str]) -> bool:
        target = set(columns)
        if any(ix.unique and set(ix.columns) == target for ix in self.indexes):
            return True
        return any(c.kind in ("p", "u") and set(c.columns) == target for c in self.constraints)


@dataclass
class SchemaModel:
    tables: list[Table] = field(default_factory=list)

    def table(self, name: str) -> Table | None:
        return next((t for t in self.tables if t.name == name), None)
