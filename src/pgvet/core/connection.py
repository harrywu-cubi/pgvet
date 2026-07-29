"""Thin wrapper isolating psycopg. All DB access in pgvet goes through here, so
the rest of the engine can be tested against a fake with the same surface."""

from __future__ import annotations

from typing import Any

from pgvet.config import Settings


class Connection:
    def __init__(self, raw: Any) -> None:
        self._raw = raw

    @classmethod
    def connect(cls, settings: Settings) -> "Connection":
        import psycopg
        from psycopg.rows import dict_row

        conn = psycopg.connect(
            settings.require_url(),
            autocommit=True,
            row_factory=dict_row,
        )
        # pgvet is read-mostly in the MVP; keep the session read-only.
        conn.execute("SET default_transaction_read_only = on")
        return cls(conn)

    def fetch_all(self, sql: str, params: Any = None) -> list[dict]:
        return list(self._raw.execute(sql, params).fetchall())

    def fetch_one(self, sql: str, params: Any = None) -> dict | None:
        return self._raw.execute(sql, params).fetchone()

    def close(self) -> None:
        self._raw.close()
