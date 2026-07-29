from pgvet.cli import _default_history_path


def test_default_history_path_is_under_pgvet_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = _default_history_path()
    assert p.endswith("history.db")
    assert ".pgvet" in p
