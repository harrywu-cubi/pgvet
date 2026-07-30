from pgvet.core.sampler import Stat
from pgvet.core.schemamodel import SchemaModel
from pgvet.plugins.base import SchemaContext


class FakeSampler:
    def __init__(self, rows=0, nulls=None, distincts=None, values=None, orphans=None, sampled=False):
        self._rows = rows
        self._nulls = nulls or {}
        self._distincts = distincts or {}
        self._values = values or {}
        self._orphans = orphans or {}
        self._sampled = sampled

    def row_count(self, table):
        return Stat(self._rows, False, self._rows)

    def null_count(self, table, column):
        return Stat(self._nulls.get((table, column), 0), self._sampled, self._rows)

    def distinct_count(self, table, column):
        return Stat(self._distincts.get((table, column), 0), self._sampled, self._rows)

    def distinct_values(self, table, column, limit):
        return self._values.get((table, column), [])[:limit]

    def orphan_ratio(self, child_table, child_col, parent_table, parent_col):
        return Stat(self._orphans.get((child_table, child_col), 0.0), self._sampled, self._rows)


def sctx(schema, sampler) -> SchemaContext:
    return SchemaContext(schema=schema, sampler=sampler)
