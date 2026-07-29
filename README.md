# pgvet

**A terminal companion that tells you what's wrong with your Postgres queries.**

Point pgvet at a local or dev database, give it a slow query, and it shows you the
execution plan with plain-English advice: missing indexes, bad row estimates, sorts
spilling to disk, runaway nested loops, and more. It runs entirely on your machine —
no cloud, no account, no telemetry.

```
$ pgvet report --plan-file slow_query.json

WARN: Row estimate off by 950× at customers [customers]
    Planner estimated 1 rows but got 950. Bad estimates lead to bad plans.
    → Run ANALYZE on `customers`; consider extended statistics if columns are correlated.
```

---

## Requirements

- **Python 3.11+** and [**uv**](https://docs.astral.sh/uv/) (used for install and running).
- A **PostgreSQL** you can reach (local or dev) — needed for the live `tui`.
  The `report` command works on a saved plan file with **no database at all**.

## Install

```bash
git clone https://github.com/harrywu-cubi/pgvet.git
cd pgvet
uv sync --extra dev
```

## Quick start

Tell pgvet where your database is (it reads the standard `DATABASE_URL`; your
password is never stored or printed):

```bash
export DATABASE_URL=postgresql://user@localhost:5432/mydb
```

**Interactive workbench** — type a query, press Enter, see the plan and findings:

```bash
uv run pgvet tui
```

**Analyze a saved plan (no database needed)** — capture a plan, then read it:

```bash
# capture EXPLAIN output to a file...
psql "$DATABASE_URL" -XAt -c \
  "EXPLAIN (ANALYZE, FORMAT JSON) SELECT * FROM orders WHERE status = 'open'" \
  > slow_query.json

# ...then let pgvet diagnose it
uv run pgvet report --plan-file slow_query.json
uv run pgvet report --plan-file slow_query.json --format json   # machine-readable
```

## Commands

| Command | What it does |
|---|---|
| `pgvet tui` | Interactive workbench over your live DB — enter SQL, view the plan tree + findings. |
| `pgvet report --plan-file FILE` | Analyze a saved `EXPLAIN (FORMAT JSON)` file. No database required. Add `--format json` for scripting/CI. |
| `pgvet plugins` | List the advisors currently installed. |

## What it checks

Each check is an independent **advisor**. The built-in set:

| Advisor | Flags |
|---|---|
| `seq_scan` | A sequential scan reading a large table — likely a missing index. |
| `row_estimate` | The planner's row estimate is wildly off from reality — usually stale stats. |
| `sort_spill` | A sort spilled to disk instead of staying in memory — `work_mem` may be too low. |
| `nested_loop` | A nested-loop join iterating a huge number of times — often a cheaper join exists. |
| `unused_index` | A sequential scan on a table that *has* a usable index the planner skipped. |

## Extending pgvet

Advisors are plugins, and the plugin host *is* the tool — adding a check never
touches the core. An advisor is a small, pure function over the query plan:

```python
from pgvet.plugins.base import Advisor
from pgvet.core.findings import Finding, Severity
from pgvet.core.planmodel import NodeType


class GatherHeavyAdvisor(Advisor):
    id = "advisor.gather_heavy"
    name = "Parallel gather doing too much"

    def run(self, ctx):
        for node in ctx.plan.walk():
            if node.node_type == NodeType.UNKNOWN:  # your condition
                yield Finding(
                    plugin_id=self.id,
                    severity=Severity.INFO,
                    title="Interesting node found",
                    detail="Explain what it means and how to fix it.",
                )
```

Ship it from your own package by advertising it under the `pgvet.advisors`
entry-point group; pgvet discovers it automatically at startup:

```toml
# in your package's pyproject.toml
[project.entry-points."pgvet.advisors"]
myplugin = "my_pgvet_plugin:register"
```

```python
# my_pgvet_plugin/__init__.py
from .advisors import GatherHeavyAdvisor

def register(registry):
    registry.register(GatherHeavyAdvisor())
```

A broken third-party plugin is skipped with a warning — it can't crash pgvet.

## How it works

`pgvet` runs `EXPLAIN (ANALYZE, FORMAT JSON)`, normalizes the result into a
version-independent plan model, and runs every advisor over it. The TUI and the
`report` CLI are thin views over the same engine, so anything you see interactively
you can also get as JSON for CI.

## Status & roadmap

This is the **MVP** (the query-and-index workbench). Planned next, each as its own
release: plan **diffing + history** ("when did this get slow?"), **hypothetical
index** testing (via HypoPG), and additional plugin families — **constraint
inference** from your data and **ORM↔DB drift** detection.

## Safety

pgvet is read-mostly: it runs `EXPLAIN`, catalog lookups, and bounded sample
queries. It never issues DDL/DML on its own — any suggested SQL is yours to review
and apply. Connection credentials are read from the environment and redacted in all
output.
