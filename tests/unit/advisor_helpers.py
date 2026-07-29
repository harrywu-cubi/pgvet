from pgvet.core.planmodel import NodeType, PlanNode, PlanTree
from pgvet.core.schemamodel import SchemaModel
from pgvet.plugins.base import PlanContext


def node(node_type, relation=None, est=1.0, actual=1.0, loops=1.0,
         cost=1.0, time=1.0, children=None, raw=None):
    return PlanNode(
        node_type=node_type, relation=relation, estimated_rows=est,
        actual_rows=actual, estimated_cost=cost, actual_time_ms=time,
        loops=loops, children=children or [], raw=raw or {},
    )


def ctx(root, query="SELECT 1", schema=None):
    tree = PlanTree(root=root, planning_time_ms=0, execution_time_ms=0, query=query)
    return PlanContext(plan=tree, query=query, schema=schema or SchemaModel())
