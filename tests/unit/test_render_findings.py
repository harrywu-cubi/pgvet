from rich.table import Table as RichTable

from pgvet.tui.panels.findings import render_findings
from pgvet.core.findings import Finding, Severity, Location


def test_render_findings_returns_table_with_rows():
    findings = [
        Finding("advisor.seq_scan", Severity.WARN, "Seq Scan on orders", "d",
                location=Location("table", "orders")),
        Finding("advisor.sort_spill", Severity.SUGGEST, "Sort spilled", "d"),
    ]
    table = render_findings(findings)
    assert isinstance(table, RichTable)
    assert table.row_count == 2


def test_render_findings_empty():
    table = render_findings([])
    assert table.row_count == 0
