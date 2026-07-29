"""Live-DB schema introspection → SchemaModel. Kept intentionally small for the
MVP: tables, columns, and indexes (constraints beyond unique-index inference are
added when the drift family lands)."""

from __future__ import annotations

from pgvet.core.schemamodel import Column, Index, SchemaModel, Table

COLUMNS_SQL = """
SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
ORDER BY table_schema, table_name, ordinal_position
"""

INDEXES_SQL = """
SELECT t.relname AS table_name,
       i.relname AS index_name,
       array_agg(a.attname ORDER BY k.ord) AS column_names,
       ix.indisunique AS is_unique,
       pg_get_expr(ix.indpred, ix.indrelid) AS predicate
FROM pg_index ix
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_class t ON t.oid = ix.indrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
JOIN LATERAL unnest(ix.indkey) WITH ORDINALITY AS k(attnum, ord) ON true
JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
GROUP BY t.relname, i.relname, ix.indisunique, ix.indpred, ix.indrelid
ORDER BY t.relname, i.relname
"""


def introspect(conn) -> SchemaModel:
    tables: dict[str, Table] = {}

    for row in conn.fetch_all(COLUMNS_SQL):
        key = row["table_name"]
        table = tables.setdefault(key, Table(schema=row["table_schema"], name=key))
        table.columns.append(
            Column(
                name=row["column_name"],
                data_type=row["data_type"],
                nullable=(row["is_nullable"] == "YES"),
                default=row["column_default"],
            )
        )

    for row in conn.fetch_all(INDEXES_SQL):
        table = tables.get(row["table_name"])
        if table is None:
            continue
        table.indexes.append(
            Index(
                name=row["index_name"],
                columns=list(row["column_names"]),
                unique=bool(row["is_unique"]),
                predicate=row["predicate"],
            )
        )

    return SchemaModel(tables=list(tables.values()))
