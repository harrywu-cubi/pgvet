"""HypoPG hypothetical-index support. Drives the HypoPG extension through the
Connection wrapper. Hypothetical indexes are session-local and never touch disk,
so this is safe and read-mostly. All re-plans use EXPLAIN WITHOUT ANALYZE, because
a hypothetical index only affects the planner's estimates."""

from __future__ import annotations


def hypopg_available(conn) -> bool:
    """True if the HypoPG extension is installed in the connected database."""
    row = conn.fetch_one("SELECT 1 AS ok FROM pg_extension WHERE extname = 'hypopg'")
    return row is not None


def create_hypothetical_index(conn, create_index_sql: str) -> int:
    """Register a hypothetical index from a CREATE INDEX statement; return its
    hypothetical indexrelid. The statement is passed as a bound parameter."""
    row = conn.fetch_one(
        "SELECT indexrelid, indexname FROM hypopg_create_index(%s)", (create_index_sql,)
    )
    return int(row["indexrelid"])


def reset_hypothetical(conn) -> None:
    """Drop all hypothetical indexes for this session."""
    conn.fetch_one("SELECT hypopg_reset()")
