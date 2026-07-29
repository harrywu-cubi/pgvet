"""Local SQLite store of plan runs, keyed by normalized-query hash. Enables the
'when did this get slow?' history and supplies the 'previous' plan for diffing."""

from __future__ import annotations

import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS plan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_hash TEXT NOT NULL,
    git_ref TEXT,
    recorded_at TEXT NOT NULL,
    execution_time_ms REAL,
    plan_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_plan_runs_hash ON plan_runs(query_hash, id);
"""


class History:
    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def record(self, *, query_hash: str, git_ref: str | None, recorded_at: str,
               execution_time_ms: float | None, plan_json: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO plan_runs (query_hash, git_ref, recorded_at, execution_time_ms, plan_json)"
            " VALUES (?, ?, ?, ?, ?)",
            (query_hash, git_ref, recorded_at, execution_time_ms, plan_json),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def latest(self, query_hash: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM plan_runs WHERE query_hash = ? ORDER BY id DESC LIMIT 1",
            (query_hash,),
        ).fetchone()
        return dict(row) if row else None

    def all_for(self, query_hash: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM plan_runs WHERE query_hash = ? ORDER BY id DESC", (query_hash,)
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        self._conn.close()
