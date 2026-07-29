import pytest

from pgvet.tui.app import PgvetApp
from pgvet.core.session import RunResult
from pgvet.core.findings import Finding, Severity
from pgvet.core.planmodel import NodeType
from tests.unit.advisor_helpers import node, ctx


def _fake_result():
    plan = ctx(node(NodeType.SEQ_SCAN, relation="orders", est=50000, actual=50000)).plan
    findings = [Finding("advisor.seq_scan", Severity.WARN, "Seq Scan on orders", "d")]
    return RunResult(query="SELECT * FROM orders", plan=plan, findings=findings)


@pytest.mark.asyncio
async def test_app_renders_result_on_run():
    app = PgvetApp(analyze_query=lambda sql: _fake_result())
    async with app.run_test() as pilot:
        app.run_analysis("SELECT * FROM orders")
        await pilot.pause()
        assert app.last_result is not None
        assert len(app.last_result.findings) == 1
        assert app.last_result.plan.root.relation == "orders"
