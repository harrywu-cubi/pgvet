"""EXPLAIN handling. `parse_explain_json` is the version-quarantine boundary:
all Postgres-specific JSON shape lives here; everything downstream sees only
PlanTree/PlanNode."""

from __future__ import annotations

from pgvet.core.planmodel import NodeType, PlanNode, PlanTree


def _node(raw: dict) -> PlanNode:
    return PlanNode(
        node_type=NodeType.from_pg(raw.get("Node Type", "")),
        relation=raw.get("Relation Name"),
        estimated_rows=float(raw.get("Plan Rows", 0)),
        actual_rows=(float(raw["Actual Rows"]) if "Actual Rows" in raw else None),
        estimated_cost=float(raw.get("Total Cost", 0)),
        actual_time_ms=(float(raw["Actual Total Time"]) if "Actual Total Time" in raw else None),
        loops=float(raw.get("Actual Loops", 1)),
        children=[_node(child) for child in raw.get("Plans", [])],
        raw=raw,
    )


def parse_explain_json(payload) -> PlanTree:
    """`payload` is the list returned by EXPLAIN (FORMAT JSON)."""
    top = payload[0] if isinstance(payload, list) else payload
    return PlanTree(
        root=_node(top["Plan"]),
        planning_time_ms=top.get("Planning Time"),
        execution_time_ms=top.get("Execution Time"),
    )


def run_explain(conn, sql: str, analyze: bool = True) -> PlanTree:
    """Run EXPLAIN on `sql` via a Connection-like object and parse the result.

    `conn` must expose `fetch_one(sql) -> dict` (see core.connection.Connection).
    """
    options = "ANALYZE, BUFFERS, FORMAT JSON" if analyze else "BUFFERS, FORMAT JSON"
    row = conn.fetch_one(f"EXPLAIN ({options}) {sql}")
    payload = row["QUERY PLAN"]
    tree = parse_explain_json(payload)
    tree.query = sql
    return tree
