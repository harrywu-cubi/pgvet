import json
from pathlib import Path

from pgvet.cli import report_from_plan_file

FIXTURE = Path(__file__).parent.parent / "fixtures" / "plans" / "seq_scan.json"


def test_report_from_plan_file_text_produces_findings():
    out = report_from_plan_file(str(FIXTURE), fmt="text")
    assert out.strip() != ""
    assert out != "No findings."
    # the row-estimate advisor fires on the fixture's 950x misestimate
    assert "WARN" in out


def test_report_from_plan_file_json_is_valid():
    out = report_from_plan_file(str(FIXTURE), fmt="json")
    data = json.loads(out)
    assert isinstance(data["findings"], list)
    assert len(data["findings"]) >= 1
    assert data["query"] is None or isinstance(data["query"], str)
