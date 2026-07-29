import pytest

from pgvet.config import Settings, redact


def test_from_env_reads_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:secret@localhost:5432/dev")
    s = Settings.from_env()
    assert s.database_url == "postgresql://u:secret@localhost:5432/dev"


def test_from_env_missing_is_none(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = Settings.from_env()
    assert s.database_url is None


def test_require_url_raises_when_missing(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        Settings.from_env().require_url()


def test_redact_hides_password():
    out = redact("postgresql://u:secret@localhost:5432/dev")
    assert "secret" not in out
    assert "u" in out and "localhost" in out
