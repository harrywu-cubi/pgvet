"""Settings + secret-safe helpers. Secrets are read from the environment by name
only; passwords are never stored beyond the connection string and are redacted in
all output."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass


def redact(url: str) -> str:
    """Replace the password in a libpq URL with ***."""
    return re.sub(r"(://[^:/@]+:)[^@]*(@)", r"\1***\2", url)


@dataclass
class Settings:
    database_url: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(database_url=os.environ.get("DATABASE_URL"))

    def require_url(self) -> str:
        if not self.database_url:
            raise RuntimeError(
                "DATABASE_URL is not set. Point pgvet at your local/dev Postgres, "
                "e.g. export DATABASE_URL=postgresql://user@localhost:5432/dev"
            )
        return self.database_url
