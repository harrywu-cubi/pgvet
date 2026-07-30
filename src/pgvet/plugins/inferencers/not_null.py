"""Infer NOT NULL: a nullable column that is never actually null."""

from __future__ import annotations

from typing import Iterable

from pgvet.core.findings import Finding, Location, Severity, Suggestion
from pgvet.plugins.base import Inferencer, SchemaContext


class NotNullInferencer(Inferencer):
    id = "inferencer.not_null"
    name = "Undeclared NOT NULL"

    def run(self, ctx: SchemaContext) -> Iterable[Finding]:
        for table in ctx.schema.tables:
            for col in table.columns:
                if not col.nullable:
                    continue
                if ctx.sampler.row_count(table.name).value == 0:
                    continue
                nulls = ctx.sampler.null_count(table.name, col.name)
                if nulls.value != 0:
                    continue
                where = f"{table.name}.{col.name}"
                yield Finding(
                    plugin_id=self.id,
                    severity=Severity.INFO if nulls.sampled else Severity.SUGGEST,
                    title=f"`{where}` is never null but is declared nullable",
                    detail=(f"No NULLs found in {int(nulls.sample_size)} rows"
                            f"{' (sampled)' if nulls.sampled else ''}. "
                            f"Consider declaring `{where}` NOT NULL."),
                    location=Location(kind="column", identifier=where),
                    evidence={"sampled": nulls.sampled, "sample_size": nulls.sample_size},
                    suggestion=Suggestion(
                        kind="ddl",
                        sql=f'ALTER TABLE "{table.name}" ALTER COLUMN "{col.name}" SET NOT NULL',
                    ),
                )
