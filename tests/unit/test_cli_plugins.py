from pgvet.cli import plugins_listing


def test_plugins_listing_names_builtin_advisors():
    out = plugins_listing()
    assert "advisor.seq_scan" in out
    assert "advisor.unused_index" in out
    assert "ADVISOR" in out
