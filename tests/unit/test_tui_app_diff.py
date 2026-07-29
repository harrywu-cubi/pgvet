import pytest

from pgvet.tui.app import PgvetApp
from pgvet.core.session import RunResult
from pgvet.core.planmodel import NodeType
from pgvet.core.plandiff import PlanDiff, DiffVerdict
from tests.unit.advisor_helpers import node, ctx


def _result_with_diff():
    plan = ctx(node(NodeType.INDEX_SCAN, relation="orders")).plan
    diff = PlanDiff(verdict=DiffVerdict.FASTER, aligned=True,
                    time_before_ms=13.1, time_after_ms=1.9, node_deltas=[])
    return RunResult(query="SELECT 1", plan=plan, findings=[], diff=diff)


@pytest.mark.asyncio
async def test_app_stores_and_reflects_diff():
    app = PgvetApp(analyze_query=lambda sql: _result_with_diff())
    async with app.run_test() as pilot:
        app.run_analysis("SELECT 1")
        await pilot.pause()
        assert app.last_result.diff is not None
        assert app.last_result.diff.verdict == DiffVerdict.FASTER
