"""Normalizer robustness against REAL PostgreSQL 16 EXPLAIN output.

These fixtures were captured from a live PG16 database (see docs/VALIDATION.md) and
contain many fields pgvet does not model (Parallel Aware, Shared Hit Blocks, Filter,
a Planning object, Triggers, …). Parsing them proves the version-quarantine holds on
real output, not just the hand-written representative fixture."""

import json
from pathlib import Path

from pgvet.core.explain import parse_explain_json
from pgvet.core.planmodel import NodeType
from pgvet.core.schemamodel import SchemaModel
from pgvet.plugins.base import PlanContext
from pgvet.plugins.advisors.seq_scan import SeqScanAdvisor

PLANS = Path(__file__).parent.parent / "fixtures" / "plans"


def _load(name):
    return parse_explain_json(json.loads((PLANS / name).read_text()))


def test_real_seq_scan_plan_parses_cleanly():
    tree = _load("real_seq_scan.json")
    assert tree.root.node_type == NodeType.SEQ_SCAN
    assert tree.root.relation == "orders"
    assert tree.root.estimated_rows == 24763
    assert tree.root.total_actual_rows == 25000  # loops == 1
    assert tree.planning_time_ms == 1.413
    assert tree.execution_time_ms == 15.602
    # no known real node should fall through to UNKNOWN
    assert all(n.node_type != NodeType.UNKNOWN for n in tree.walk())


def test_real_join_plan_parses_all_known_nodes():
    tree = _load("real_join.json")
    assert tree.root.node_type == NodeType.HASH_JOIN
    types = [n.node_type for n in tree.walk()]
    assert NodeType.SEQ_SCAN in types
    assert NodeType.HASH in types
    assert all(t != NodeType.UNKNOWN for t in types)
    relations = {n.relation for n in tree.walk() if n.relation}
    assert {"orders", "customers"} <= relations


def test_seq_scan_advisor_fires_on_real_plan():
    tree = _load("real_seq_scan.json")
    ctx = PlanContext(plan=tree, query="", schema=SchemaModel())
    findings = list(SeqScanAdvisor().run(ctx))
    assert len(findings) == 1
    assert findings[0].location.identifier == "orders"
    assert findings[0].evidence["rows"] == 25000
