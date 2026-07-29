from pgvet.core.findings import Severity, Location, Suggestion, Finding


def test_finding_defaults_and_fields():
    f = Finding(
        plugin_id="advisor.seq_scan",
        severity=Severity.WARN,
        title="Seq scan on large table",
        detail="Sequential scan over `orders`.",
    )
    assert f.location is None
    assert f.suggestion is None
    assert f.evidence == {}
    assert f.severity == "WARN"  # Severity is a str enum


def test_finding_with_location_and_suggestion():
    f = Finding(
        plugin_id="advisor.seq_scan",
        severity=Severity.SUGGEST,
        title="t",
        detail="d",
        location=Location(kind="table", identifier="orders"),
        evidence={"rows": 100000},
        suggestion=Suggestion(kind="ddl", sql="CREATE INDEX ...", note="candidate"),
    )
    assert f.location.kind == "table"
    assert f.suggestion.sql.startswith("CREATE INDEX")
    assert f.evidence["rows"] == 100000
