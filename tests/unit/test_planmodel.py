from pgvet.core.planmodel import NodeType, PlanNode, PlanTree


def test_nodetype_from_pg_known_and_unknown():
    assert NodeType.from_pg("Seq Scan") == NodeType.SEQ_SCAN
    assert NodeType.from_pg("Index Scan") == NodeType.INDEX_SCAN
    assert NodeType.from_pg("Nested Loop") == NodeType.NESTED_LOOP
    assert NodeType.from_pg("Some Future Node") == NodeType.UNKNOWN


def test_total_actual_rows_accounts_for_loops():
    node = PlanNode(
        node_type=NodeType.INDEX_SCAN,
        relation="orders",
        estimated_rows=10,
        actual_rows=5,
        estimated_cost=1.0,
        actual_time_ms=0.1,
        loops=4,
        children=[],
        raw={},
    )
    assert node.total_actual_rows == 20


def test_misestimate_factor():
    node = PlanNode(
        node_type=NodeType.SEQ_SCAN,
        relation="orders",
        estimated_rows=10,
        actual_rows=1000,
        estimated_cost=1.0,
        actual_time_ms=1.0,
        loops=1,
        children=[],
        raw={},
    )
    assert node.misestimate_factor == 100.0


def test_misestimate_factor_none_without_actuals():
    node = PlanNode(
        node_type=NodeType.SEQ_SCAN,
        relation="orders",
        estimated_rows=10,
        actual_rows=None,
        estimated_cost=1.0,
        actual_time_ms=None,
        loops=1,
        children=[],
        raw={},
    )
    assert node.misestimate_factor is None


def test_walk_visits_all_nodes_depth_first():
    leaf = PlanNode(NodeType.SEQ_SCAN, "a", 1, 1, 1, 1, 1, [], {})
    root = PlanNode(NodeType.NESTED_LOOP, None, 1, 1, 1, 1, 1, [leaf], {})
    tree = PlanTree(root=root, planning_time_ms=0.5, execution_time_ms=2.0, query="SELECT 1")
    types = [n.node_type for n in tree.walk()]
    assert types == [NodeType.NESTED_LOOP, NodeType.SEQ_SCAN]
