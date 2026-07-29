"""Render a list of Findings as a Rich table."""

from __future__ import annotations

from rich.table import Table as RichTable

from pgvet.core.findings import Finding, Severity

_COLOR = {
    Severity.INFO: "cyan",
    Severity.SUGGEST: "green",
    Severity.WARN: "yellow",
    Severity.CRITICAL: "bold red",
}


def render_findings(findings: list[Finding]) -> RichTable:
    table = RichTable(expand=True)
    table.add_column("Severity", no_wrap=True)
    table.add_column("Finding")
    table.add_column("Where", no_wrap=True)
    for f in findings:
        color = _COLOR.get(f.severity, "white")
        where = f.location.identifier if f.location else ""
        table.add_row(f"[{color}]{f.severity.value}[/]", f.title, where)
    return table
