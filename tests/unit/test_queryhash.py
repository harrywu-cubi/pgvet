from pgvet.core.queryhash import hash_query, current_git_ref


def test_hash_is_stable_across_whitespace_and_case():
    a = hash_query("select * from orders where id = 1")
    b = hash_query("SELECT   *\nFROM orders\nWHERE id = 1")
    assert a == b
    assert len(a) == 64  # sha256 hex


def test_hash_differs_for_different_queries():
    assert hash_query("select 1") != hash_query("select 2")


def test_hash_falls_back_on_unparseable_sql():
    # not valid SQL; must not raise, must be deterministic
    h1 = hash_query(">>> not sql <<<")
    h2 = hash_query(">>> not sql <<<")
    assert h1 == h2 and len(h1) == 64


def test_current_git_ref_injectable(monkeypatch):
    monkeypatch.setattr("pgvet.core.queryhash._run_git", lambda args, cwd: "abc1234")
    assert current_git_ref() == "abc1234"


def test_current_git_ref_none_on_failure(monkeypatch):
    def _boom(args, cwd):
        raise OSError("no git")
    monkeypatch.setattr("pgvet.core.queryhash._run_git", _boom)
    assert current_git_ref() is None
