"""Infer UNIQUE: a non-unique column whose scanned values are all distinct."""

from __future__ import annotations

from typing import Iterable

from pgvet.core.findings import Finding, Location, Severity, Suggestion
from pgvet.plugins.base import Inferencer, SchemaContext


class UniqueInferencer(Inferencer):
    id = "inferencer.unique"
    name = "Undeclared UNIQUE"

    def run(self, ctx: SchemaContext) -> Iterable[Finding]:
        for table in ctx.schema.tables:
            for col in table.columns:
                if table.has_unique_on([col.name]):
                    continue
                distinct = ctx.sampler.distinct_count(table.name, col.name)
                scanned = distinct.sample_size
                if scanned == 0 or distinct.value != scanned:
                    continue  # empty, or duplicates found in the scanned rows
                where = f"{table.name}.{col.name}"
                yield Finding(
                    plugin_id=self.id,
                    severity=Severity.INFO if distinct.sampled else Severity.SUGGEST,
                    title=f"`{where}` looks unique but has no unique constraint",
                    detail=(f"All {int(scanned)} scanned values are distinct"
                            f"{' (sampled)' if distinct.sampled else ''}. "
                            f"Consider a UNIQUE constraint on `{where}`."),
                    location=Location(kind="column", identifier=where),
                    evidence={"sampled": distinct.sampled, "sample_size": distinct.sample_size},
                    suggestion=Suggestion(
                        kind="ddl",
                        sql=f'ALTER TABLE "{table.name}" ADD CONSTRAINT {table.name}_{col.name}_key UNIQUE ("{col.name}")',
                    ),
                )
