"""pgvet command-line entry point. Subcommands: report (this task), tui + plugins
(added later)."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from pgvet.core.explain import parse_explain_json
from pgvet.core.registry import Registry
from pgvet.core.session import Session
from pgvet.plugins.base import PlanContext
from pgvet.core.schemamodel import SchemaModel


def _registry() -> Registry:
    reg = Registry()
    reg.load_builtins()
    reg.discover()
    return reg


def report_from_plan_file(path: str, fmt: str = "text") -> str:
    payload = json.loads(Path(path).read_text())
    plan = parse_explain_json(payload)
    ctx = PlanContext(plan=plan, query=plan.query, schema=SchemaModel())
    findings = Session(conn=None, registry=_registry()).analyze(ctx)
    if fmt == "json":
        return json.dumps(
            {"query": plan.query, "findings": [_finding_dict(f) for f in findings]},
            indent=2,
        )
    return _render_text(findings)


def _finding_dict(f) -> dict:
    d = asdict(f)
    d["severity"] = f.severity.value
    return d


def _render_text(findings) -> str:
    if not findings:
        return "No findings."
    lines = []
    for f in findings:
        loc = f" [{f.location.identifier}]" if f.location else ""
        lines.append(f"{f.severity.value}: {f.title}{loc}\n    {f.detail}")
    return "\n".join(lines)


def plugins_listing() -> str:
    reg = _registry()
    lines = ["Discovered plugins:"]
    for a in reg.advisors:
        lines.append(f"  [{a.family.value}] {a.id} — {a.name}")
    return "\n".join(lines)


def launch_tui() -> int:
    from pgvet.config import Settings
    from pgvet.core.connection import Connection
    from pgvet.tui.app import PgvetApp

    conn = Connection.connect(Settings.from_env())
    session = Session(conn=conn, registry=_registry())
    try:
        PgvetApp(analyze_query=session.run_query).run()
    finally:
        conn.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pgvet")
    sub = parser.add_subparsers(dest="command", required=True)

    rep = sub.add_parser("report", help="analyze a plan and print findings")
    rep.add_argument("--plan-file", required=True, help="EXPLAIN (FORMAT JSON) output file")
    rep.add_argument("--format", default="text", choices=["text", "json"])

    sub.add_parser("tui", help="launch the interactive workbench")
    sub.add_parser("plugins", help="list discovered plugins")

    args = parser.parse_args(argv)
    if args.command == "report":
        print(report_from_plan_file(args.plan_file, fmt=args.format))
        return 0
    if args.command == "plugins":
        print(plugins_listing())
        return 0
    if args.command == "tui":
        return launch_tui()
    return 1


if __name__ == "__main__":
    sys.exit(main())
