"""pgvet command-line entry point. Subcommands: report (this task), tui + plugins
(added later)."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from pgvet.config import Settings
from pgvet.core.connection import Connection
from pgvet.core.explain import parse_explain_json
from pgvet.core.registry import ADVISOR_GROUP, INFERENCER_GROUP, Registry
from pgvet.core.session import Session
from pgvet.plugins.base import PlanContext
from pgvet.core.schemamodel import SchemaModel


def _registry() -> Registry:
    reg = Registry()
    reg.load_builtins()
    reg.discover(group=ADVISOR_GROUP)
    reg.discover(group=INFERENCER_GROUP)
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


def infer_report(fmt: str = "text") -> str:
    conn = Connection.connect(Settings.from_env())
    try:
        findings = Session(conn=conn, registry=_registry()).infer()
    finally:
        conn.close()
    if fmt == "json":
        return json.dumps({"findings": [_finding_dict(f) for f in findings]}, indent=2)
    if not findings:
        return "No candidate constraints found."
    lines = []
    for f in findings:
        lines.append(f"{f.severity.value}: {f.title}")
        if f.suggestion and f.suggestion.sql:
            lines.append(f"    {f.suggestion.sql};")
    return "\n".join(lines)


def plugins_listing() -> str:
    reg = _registry()
    lines = ["Discovered plugins:"]
    for a in reg.advisors + reg.inferencers:
        lines.append(f"  [{a.family.value}] {a.id} - {a.name}")
    return "\n".join(lines)


def _default_history_path() -> str:
    from pathlib import Path

    d = Path.cwd() / ".pgvet"
    d.mkdir(exist_ok=True)
    return str(d / "history.db")


def _hypothetical_callable(session, available: bool):
    if not available:
        return None
    return session.try_hypothetical_index


def launch_tui() -> int:
    from pgvet.core.hypo import hypopg_available
    from pgvet.core.queryhash import current_git_ref
    from pgvet.storage.history import History
    from pgvet.tui.app import PgvetApp

    conn = None
    history = None
    try:
        conn = Connection.connect(Settings.from_env())
        history = History(_default_history_path())
        session = Session(conn=conn, registry=_registry(),
                          history=history, git_ref=current_git_ref())
        hypo_fn = _hypothetical_callable(session, hypopg_available(conn))
        PgvetApp(analyze_query=session.run_query, hypothetical_query=hypo_fn).run()
    finally:
        if history is not None:
            history.close()
        if conn is not None:
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

    inf = sub.add_parser("infer", help="infer undeclared constraints from live data")
    inf.add_argument("--format", default="text", choices=["text", "json"])

    args = parser.parse_args(argv)
    try:
        if args.command == "report":
            print(report_from_plan_file(args.plan_file, fmt=args.format))
            return 0
        if args.command == "plugins":
            print(plugins_listing())
            return 0
        if args.command == "infer":
            print(infer_report(fmt=args.format))
            return 0
        if args.command == "tui":
            return launch_tui()
    except FileNotFoundError as exc:
        print(f"error: file not found: {exc.filename or exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"error: could not parse plan JSON: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
