"""Infer an enum-like CHECK: a text column with very few distinct values."""

from __future__ import annotations

from typing import Iterable

from pgvet.core.findings import Finding, Location, Severity, Suggestion
from pgvet.plugins.base import Inferencer, SchemaContext

ENUM_MAX = 12  # at most this many distinct values to be considered an enum


def _is_text(data_type: str) -> bool:
    return data_type == "text" or "character" in data_type


class EnumInferencer(Inferencer):
    id = "inferencer.enum"
    name = "Low-cardinality column (candidate enum)"

    def run(self, ctx: SchemaContext) -> Iterable[Finding]:
        for table in ctx.schema.tables:
            for col in table.columns:
                if not _is_text(col.data_type):
                    continue
                distinct = ctx.sampler.distinct_count(table.name, col.name)
                if distinct.value == 0 or distinct.value > ENUM_MAX:
                    continue
                if distinct.value >= distinct.sample_size:
                    continue  # not "many rows, few values" — no repetition
                values = ctx.sampler.distinct_values(table.name, col.name, ENUM_MAX)
                if not values:
                    continue
                in_list = ", ".join("'" + str(v).replace("'", "''") + "'" for v in values)
                where = f"{table.name}.{col.name}"
                yield Finding(
                    plugin_id=self.id,
                    severity=Severity.INFO if distinct.sampled else Severity.SUGGEST,
                    title=f"`{where}` has only {int(distinct.value)} distinct values (candidate enum)",
                    detail=(f"Values seen: {in_list}"
                            f"{' (sampled)' if distinct.sampled else ''}. "
                            f"A CHECK constraint would enforce the allowed set."),
                    location=Location(kind="column", identifier=where),
                    evidence={"distinct": distinct.value, "sampled": distinct.sampled,
                              "values": values},
                    suggestion=Suggestion(
                        kind="ddl",
                        sql=(f'ALTER TABLE "{table.name}" ADD CONSTRAINT {table.name}_{col.name}_check '
                             f'CHECK ("{col.name}" IN ({in_list}))'),
                    ),
                )
