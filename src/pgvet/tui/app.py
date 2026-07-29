"""The Textual workbench app. A thin view over a query-analysis callable
(normally Session.run_query). Panels are the Rich renderers from tui.panels."""

from __future__ import annotations

from typing import Callable

from rich.console import Group
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, Static

from pgvet.core.session import RunResult
from pgvet.tui.panels.findings import render_findings
from pgvet.tui.panels.plan_diff import render_plan_diff
from pgvet.tui.panels.plan_tree import render_plan_tree


class PgvetApp(App):
    CSS = """
    #plan { width: 2fr; border: round $accent; }
    #findings { width: 3fr; border: round $accent; }
    """
    BINDINGS = [("ctrl+c", "quit", "Quit")]

    def __init__(self, analyze_query: Callable[[str], RunResult], hypothetical_query=None) -> None:
        super().__init__()
        self._analyze_query = analyze_query
        self._hypothetical_query = hypothetical_query
        self.last_result: RunResult | None = None
        self.last_hypo_result = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="Enter SQL, press Enter to run…", id="query")
        yield Input(placeholder="Candidate CREATE INDEX … (Enter to test hypothetically)", id="hypo")
        with Horizontal():
            yield Static("Plan will appear here.", id="plan")
            with Vertical():
                yield Static("Findings will appear here.", id="findings")
                yield Static("", id="diff")
        yield Footer()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "hypo":
            self.run_hypothetical(event.value)
        else:
            self.run_analysis(event.value)

    def run_analysis(self, sql: str) -> None:
        result = self._analyze_query(sql)
        self.last_result = result
        self.query_one("#plan", Static).update(render_plan_tree(result.plan))
        self.query_one("#findings", Static).update(
            Group(f"[b]{len(result.findings)} finding(s)[/]", render_findings(result.findings))
        )
        diff_widget = self.query_one("#diff", Static)
        if result.diff is not None:
            diff_widget.update(render_plan_diff(result.diff))
        else:
            diff_widget.update("")

    def run_hypothetical(self, create_index_sql: str) -> None:
        if self._hypothetical_query is None or self.last_result is None:
            return
        result = self._hypothetical_query(self.last_result.query, create_index_sql)
        self.last_hypo_result = result
        self.query_one("#diff", Static).update(render_plan_diff(result.diff))
