"""Infer a foreign key: a *_id column whose values are fully contained in a
naming-matched parent table's single-column primary key."""

from __future__ import annotations

from typing import Iterable

from pgvet.core.findings import Finding, Location, Severity, Suggestion
from pgvet.core.schemamodel import SchemaModel
from pgvet.plugins.base import Inferencer, SchemaContext

ORPHAN_TOLERANCE = 0.0  # require zero orphaned child values


class FkOverlapInferencer(Inferencer):
    id = "inferencer.fk_overlap"
    name = "Undeclared foreign key"

    def run(self, ctx: SchemaContext) -> Iterable[Finding]:
        for table in ctx.schema.tables:
            declared_fk = {tuple(c.columns) for c in table.constraints if c.kind == "f"}
            for col in table.columns:
                if not col.name.endswith("_id") or (col.name,) in declared_fk:
                    continue
                parent = self._find_parent(ctx.schema, col.name)
                if parent is None:
                    continue
                ptable, pcol = parent
                if ctx.sampler.row_count(table.name).value == 0:
                    continue
                ratio = ctx.sampler.orphan_ratio(table.name, col.name, ptable, pcol)
                if ratio.value > ORPHAN_TOLERANCE:
                    continue
                where = f"{table.name}.{col.name}"
                yield Finding(
                    plugin_id=self.id,
                    severity=Severity.INFO if ratio.sampled else Severity.SUGGEST,
                    title=f"`{where}` looks like an undeclared foreign key to `{ptable}`",
                    detail=(f"Every non-null `{col.name}` value matches a `{ptable}.{pcol}`"
                            f"{' (sampled)' if ratio.sampled else ''}. "
                            f"A FOREIGN KEY would enforce referential integrity."),
                    location=Location(kind="column", identifier=where),
                    evidence={"orphan_ratio": ratio.value, "sampled": ratio.sampled,
                              "parent": f"{ptable}.{pcol}"},
                    suggestion=Suggestion(
                        kind="ddl",
                        sql=(f'ALTER TABLE "{table.name}" ADD CONSTRAINT {table.name}_{col.name}_fkey '
                             f'FOREIGN KEY ("{col.name}") REFERENCES "{ptable}" ("{pcol}")'),
                    ),
                )

    def _find_parent(self, schema: SchemaModel, col_name: str):
        """customer_id -> the 'customer' or 'customers' table with a single-col PK."""
        prefix = col_name[:-3]  # strip trailing "_id"
        for cand in (prefix, prefix + "s"):
            t = schema.table(cand)
            if t is None:
                continue
            pk = next((c for c in t.constraints if c.kind == "p" and len(c.columns) == 1), None)
            if pk is not None:
                return (t.name, pk.columns[0])
        return None
