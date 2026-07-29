"""Render a PlanTree as a Rich Tree with cost/misestimate heat."""

from __future__ import annotations

from rich.tree import Tree

from pgvet.core.planmodel import PlanNode, PlanTree


def _label(node: PlanNode) -> str:
    rel = f" on {node.relation}" if node.relation else ""
    factor = node.misestimate_factor
    heat = ""
    if factor is not None and factor >= 100:
        heat = f" [bold red](est×{factor:.0f})[/]"
    elif factor is not None and factor >= 10:
        heat = f" [yellow](est×{factor:.0f})[/]"
    node_name = node.node_type.value.replace("_", " ").title()
    return f"{node_name}{rel} cost={node.estimated_cost:g}{heat}"


def _attach(rich_node, plan_node: PlanNode) -> None:
    for child in plan_node.children:
        branch = rich_node.add(_label(child))
        _attach(branch, child)


def render_plan_tree(plan: PlanTree) -> Tree:
    tree = Tree(_label(plan.root))
    _attach(tree, plan.root)
    return tree
