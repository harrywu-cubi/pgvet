from rich.tree import Tree

from pgvet.tui.panels.plan_tree import render_plan_tree
from pgvet.core.planmodel import NodeType
from tests.unit.advisor_helpers import node, ctx


def test_render_returns_rich_tree_with_root_label():
    root = node(NodeType.NESTED_LOOP, children=[node(NodeType.SEQ_SCAN, relation="orders")])
    tree = render_plan_tree(ctx(root).plan)
    assert isinstance(tree, Tree)
    assert "Nested Loop" in str(tree.label)
    assert len(tree.children) == 1
    assert "orders" in str(tree.children[0].label)
