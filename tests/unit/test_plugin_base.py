from pgvet.plugins.base import Family, PlanContext, Advisor
from pgvet.core.findings import Finding, Severity
from pgvet.core.planmodel import NodeType, PlanNode, PlanTree
from pgvet.core.schemamodel import SchemaModel


class _AlwaysFires(Advisor):
    id = "advisor.test"
    name = "Test advisor"

    def run(self, ctx):
        yield Finding(self.id, Severity.INFO, "hi", "d")


def _ctx() -> PlanContext:
    root = PlanNode(NodeType.SEQ_SCAN, "orders", 1, 1, 1, 1, 1, [], {})
    tree = PlanTree(root=root, planning_time_ms=0, execution_time_ms=0, query="SELECT 1")
    return PlanContext(plan=tree, query="SELECT 1", schema=SchemaModel())


def test_advisor_defaults_family_and_applies_to():
    a = _AlwaysFires()
    assert a.family == Family.ADVISOR
    assert a.applies_to(_ctx()) is True


def test_advisor_run_yields_findings():
    findings = list(_AlwaysFires().run(_ctx()))
    assert len(findings) == 1
    assert findings[0].plugin_id == "advisor.test"
