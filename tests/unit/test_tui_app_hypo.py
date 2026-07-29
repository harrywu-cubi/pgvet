import pytest

from pgvet.tui.app import PgvetApp
from pgvet.core.session import RunResult
from pgvet.core.hypo import HypoResult
from pgvet.core.plandiff import PlanDiff, DiffVerdict
from pgvet.core.planmodel import NodeType
from tests.unit.advisor_helpers import node, ctx


def _run_result():
    plan = ctx(node(NodeType.SEQ_SCAN, relation="orders", est=50000, actual=50000),
               query="SELECT * FROM orders").plan
    return RunResult(query="SELECT * FROM orders", plan=plan, findings=[])


def _hypo_result():
    base = ctx(node(NodeType.SEQ_SCAN, relation="orders")).plan
    cand = ctx(node(NodeType.INDEX_SCAN, relation="orders")).plan
    diff = PlanDiff(verdict=DiffVerdict.FASTER, aligned=True,
                    time_before_ms=None, time_after_ms=None, node_deltas=[])
    return HypoResult(baseline=base, candidate=cand, diff=diff)


@pytest.mark.asyncio
async def test_hypothetical_runs_against_last_query():
    captured = {}

    def hypo(sql, create_sql):
        captured["sql"] = sql
        captured["create_sql"] = create_sql
        return _hypo_result()

    app = PgvetApp(analyze_query=lambda sql: _run_result(), hypothetical_query=hypo)
    async with app.run_test() as pilot:
        app.run_analysis("SELECT * FROM orders")   # sets last query
        await pilot.pause()
        app.run_hypothetical("CREATE INDEX ON orders (status)")
        await pilot.pause()
        assert captured["sql"] == "SELECT * FROM orders"
        assert captured["create_sql"] == "CREATE INDEX ON orders (status)"
        assert app.last_hypo_result is not None
        assert app.last_hypo_result.diff.verdict == DiffVerdict.FASTER


@pytest.mark.asyncio
async def test_hypothetical_noop_without_callable():
    app = PgvetApp(analyze_query=lambda sql: _run_result())  # no hypothetical_query
    async with app.run_test() as pilot:
        app.run_analysis("SELECT * FROM orders")
        await pilot.pause()
        app.run_hypothetical("CREATE INDEX ON orders (status)")  # must not raise
        await pilot.pause()
        assert app.last_hypo_result is None
