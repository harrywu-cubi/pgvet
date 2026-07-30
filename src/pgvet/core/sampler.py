"""The single home of constraint-inference SQL. `Sampler` wraps a Connection with
data-stat methods and owns the hybrid full-scan-vs-sample rule, so inferencers call
these methods instead of writing SQL and stay pure + testable with a fake Sampler."""

from __future__ import annotations

from dataclasses import dataclass

FULL_SCAN_THRESHOLD = 100_000
SAMPLE_ROWS = 20_000


@dataclass(frozen=True)
class Stat:
    value: float
    sampled: bool
    sample_size: int


def _q(ident: str) -> str:
    """Double-quote a catalog identifier (names come from introspection, not users)."""
    return '"' + ident.replace('"', '""') + '"'


class Sampler:
    def __init__(self, conn, full_scan_threshold: int = FULL_SCAN_THRESHOLD) -> None:
        self._conn = conn
        self._threshold = full_scan_threshold
        self._row_counts: dict[str, int] = {}

    def row_count(self, table: str) -> Stat:
        if table not in self._row_counts:
            row = self._conn.fetch_one(f"SELECT count(*) AS n FROM {_q(table)}")
            self._row_counts[table] = int(row["n"])
        n = self._row_counts[table]
        return Stat(value=n, sampled=False, sample_size=n)

    def _source(self, table: str) -> tuple[str, bool, int]:
        """(SQL table source, sampled, sample_size) applying the hybrid rule."""
        n = int(self.row_count(table).value)
        if n < self._threshold:
            return _q(table), False, n
        frac = min(100.0, max(0.01, SAMPLE_ROWS / n * 100.0))
        return f"{_q(table)} TABLESAMPLE SYSTEM ({frac})", True, min(n, SAMPLE_ROWS)

    def null_count(self, table: str, column: str) -> Stat:
        src, sampled, size = self._source(table)
        row = self._conn.fetch_one(f"SELECT count(*) AS n FROM {src} WHERE {_q(column)} IS NULL")
        return Stat(value=int(row["n"]), sampled=sampled, sample_size=size)

    def distinct_count(self, table: str, column: str) -> Stat:
        src, sampled, size = self._source(table)
        row = self._conn.fetch_one(f"SELECT count(DISTINCT {_q(column)}) AS n FROM {src}")
        return Stat(value=int(row["n"]), sampled=sampled, sample_size=size)

    def distinct_values(self, table: str, column: str, limit: int) -> list[str]:
        src, _, _ = self._source(table)
        rows = self._conn.fetch_all(f"SELECT DISTINCT {_q(column)} AS v FROM {src} LIMIT {int(limit)}")
        return [r["v"] for r in rows]

    def orphan_ratio(self, child_table: str, child_col: str,
                     parent_table: str, parent_col: str) -> Stat:
        src, sampled, size = self._source(child_table)
        sql = (
            f"SELECT count(*) FILTER (WHERE p.{_q(parent_col)} IS NULL)::float "
            f"/ NULLIF(count(*), 0) AS ratio "
            f"FROM {src} c LEFT JOIN {_q(parent_table)} p "
            f"ON c.{_q(child_col)} = p.{_q(parent_col)} "
            f"WHERE c.{_q(child_col)} IS NOT NULL"
        )
        row = self._conn.fetch_one(sql)
        ratio = row["ratio"]
        return Stat(value=float(ratio if ratio is not None else 0.0), sampled=sampled, sample_size=size)
