"""Normalized-query hashing + current git ref, used to key plan history."""

from __future__ import annotations

import hashlib
import subprocess


def _normalize(sql: str) -> str:
    try:
        import sqlglot

        return sqlglot.transpile(sql, normalize=True)[0]
    except Exception:  # noqa: BLE001 — unparseable SQL falls back to raw text
        return " ".join(sql.lower().split())


def hash_query(sql: str) -> str:
    return hashlib.sha256(_normalize(sql).encode("utf-8")).hexdigest()


def _run_git(args: list[str], cwd: str | None) -> str:
    out = subprocess.check_output(["git", *args], cwd=cwd, text=True, stderr=subprocess.DEVNULL)
    return out.strip()


def current_git_ref(cwd: str | None = None) -> str | None:
    try:
        return _run_git(["rev-parse", "--short", "HEAD"], cwd) or None
    except Exception:  # noqa: BLE001 — not a repo / git missing
        return None
