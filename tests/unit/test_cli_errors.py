import json

from pgvet.cli import main


def test_report_missing_file_returns_error_no_traceback(capsys):
    rc = main(["report", "--plan-file", "does_not_exist_12345.json"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "does_not_exist_12345.json" in err or "not found" in err.lower()


def test_report_malformed_json_returns_error(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{ this is not valid json ")
    rc = main(["report", "--plan-file", str(bad)])
    assert rc != 0
    err = capsys.readouterr().err
    assert err.strip() != ""


def test_report_valid_file_still_returns_zero(capsys):
    rc = main(["report", "--plan-file", "tests/fixtures/plans/seq_scan.json"])
    assert rc == 0
