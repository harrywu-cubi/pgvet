from pgvet.core.session import Session, RunResult
from pgvet.core.registry import Registry
from pgvet.plugins.base import Advisor, PlanContext
from pgvet.core.findings import Finding, Severity
from pgvet.core.planmodel import NodeType, PlanNode, PlanTree
from pgvet.core.schemamodel import SchemaModel


class _Fires(Advisor):
    id = "advisor.fires"
    name = "Fires"
    def run(self, ctx):
        yield Finding(self.id, Severity.WARN, "fired", "d")


class _Boom(Advisor):
    id = "advisor.boom"
    name = "Boom"
    def run(self, ctx):
        raise RuntimeError("kaboom")


class _NotApplicable(Advisor):
    id = "advisor.na"
    name = "NA"
    def applies_to(self, ctx):
        return False
    def run(self, ctx):
        yield Finding(self.id, Severity.INFO, "should not fire", "d")


def _ctx():
    root = PlanNode(NodeType.SEQ_SCAN, "orders", 1, 1, 1, 1, 1, [], {})
    tree = PlanTree(root=root, planning_time_ms=0, execution_time_ms=0, query="SELECT 1")
    return PlanContext(plan=tree, query="SELECT 1", schema=SchemaModel())


def test_analyze_runs_applicable_advisors():
    reg = Registry()
    reg.register(_Fires())
    reg.register(_NotApplicable())
    findings = Session(conn=None, registry=reg).analyze(_ctx())
    assert [f.plugin_id for f in findings] == ["advisor.fires"]


def test_analyze_isolates_plugin_errors():
    reg = Registry()
    reg.register(_Fires())
    reg.register(_Boom())
    findings = Session(conn=None, registry=reg).analyze(_ctx())
    ids = {f.plugin_id for f in findings}
    assert "advisor.fires" in ids
    boom = [f for f in findings if f.plugin_id == "advisor.boom"]
    assert len(boom) == 1 and boom[0].severity == Severity.WARN


def test_run_query_uses_explain_and_introspect(monkeypatch):
    reg = Registry()
    reg.register(_Fires())
    sess = Session(conn=object(), registry=reg)

    tree = _ctx().plan
    monkeypatch.setattr("pgvet.core.session.run_explain", lambda conn, sql: tree)
    monkeypatch.setattr("pgvet.core.session.introspect", lambda conn: SchemaModel())

    result = sess.run_query("SELECT 1")
    assert isinstance(result, RunResult)
    assert result.plan is tree
    assert [f.plugin_id for f in result.findings] == ["advisor.fires"]
