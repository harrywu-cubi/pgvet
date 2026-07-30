# pgvet

**A local terminal companion for keeping your PostgreSQL healthy.**

pgvet reads how Postgres actually runs your queries and turns it into plain-English
advice. It can:

- **diagnose a slow query** — missing indexes, bad row estimates, disk-spilling sorts, runaway nested loops;
- **tell you when a query got slower** — it remembers past plans and diffs them;
- **test an index before you build it** — via hypothetical indexes (HypoPG);
- **find missing constraints** — undeclared foreign keys, effectively-unique columns, de-facto enums, never-null columns — and hand you the `ALTER TABLE` to fix them.

It runs entirely on your machine — no cloud, no account, no telemetry — and it's
**read-only**: it suggests SQL, it never runs changes for you.

```
$ pgvet report --plan-file slow_query.json

WARN: Seq Scan over large table `orders` [orders]
    Sequential scan reads ~25000 rows from `orders`. Consider an index on the filtered columns.
```

```
$ pgvet infer

SUGGEST: `orders.customer_id` looks like an undeclared foreign key to `customers`
    ALTER TABLE "orders" ADD CONSTRAINT orders_customer_id_fkey FOREIGN KEY ("customer_id") REFERENCES "customers" ("id");
```

---

## Requirements

- **Python 3.11+** and [**uv**](https://docs.astral.sh/uv/) (used to install and run).
- A **PostgreSQL** you can reach (local or dev) — needed for `tui` and `infer`.
  The `report` command works on a saved plan file with **no database at all**.
- *(Optional)* the **HypoPG** extension in your dev DB, only if you want to test
  hypothetical indexes: `CREATE EXTENSION hypopg;`

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

**Diagnose queries interactively** — type SQL, press Enter, see the plan and findings.
Re-run the same query later and it shows a *diff* against the previous run:

```bash
uv run pgvet tui
```

**Find missing constraints** in the current database:

```bash
uv run pgvet infer                 # prints candidate ALTER TABLE ... ADD CONSTRAINT
uv run pgvet infer --format json   # machine-readable, for scripting
```

**Analyze a saved plan (no database needed)** — capture a plan, then read it:

```bash
psql "$DATABASE_URL" -XAt -c \
  "EXPLAIN (ANALYZE, FORMAT JSON) SELECT * FROM orders WHERE status = 'open'" \
  > slow_query.json

uv run pgvet report --plan-file slow_query.json
uv run pgvet report --plan-file slow_query.json --format json
```

> New to it? `docs/HANDOFF.md` is a step-by-step walkthrough from an empty machine to
> a working setup (including a Docker Postgres + sample data).

## Commands

| Command | What it does |
|---|---|
| `pgvet tui` | Interactive workbench over your live DB — enter SQL, view the plan tree + findings, a before/after **diff** when you re-run a query, and (if HypoPG is installed) test a candidate index. |
| `pgvet infer` | Inspect the live DB and propose undeclared constraints as reviewable DDL. `--format json` for scripting. |
| `pgvet report --plan-file FILE` | Analyze a saved `EXPLAIN (FORMAT JSON)` file. **No database required.** `--format json` for CI. |
| `pgvet plugins` | List the installed checks (advisors + inferencers). |

## What it checks

Every check is an independent **plugin**. Two families ship built in.

**Advisors** (over a query's execution plan):

| Advisor | Flags |
|---|---|
| `seq_scan` | A sequential scan reading a large table — likely a missing index. |
| `row_estimate` | The planner's row estimate is wildly off from reality — usually stale stats. |
| `sort_spill` | A sort spilled to disk instead of staying in memory — `work_mem` may be too low. |
| `nested_loop` | A nested-loop join iterating a huge number of times — often a cheaper join exists. |
| `unused_index` | A sequential scan on a table that *has* a usable index the planner skipped. |

**Inferencers** (over your data, via `pgvet infer`):

| Inferencer | Proposes |
|---|---|
| `not_null` | `SET NOT NULL` on a nullable column that is never actually null. |
| `unique` | A `UNIQUE` constraint on a column whose values are all distinct. |
| `enum` | A `CHECK (... IN (...))` on a text column with only a handful of distinct values. |
| `fk_overlap` | A `FOREIGN KEY` on a `*_id` column whose values all live in a parent table's primary key. |

Each inferencer skips constraints your schema already declares, and every suggestion
is yours to review — pgvet only prints the DDL.

## A couple of things it does that most tools don't

**"When did this get slow?"** The `tui` records each query's plan to a local
`.pgvet/history.db` (keyed by a normalized query hash + your current git commit). Re-run
a query and pgvet diffs the new plan against the last one and tells you FASTER / SLOWER /
changed.

**"Would this index actually help?"** With HypoPG installed, the `tui` lets you type a
candidate `CREATE INDEX` and see the *estimated* before/after plan — without building the
index or writing anything to disk.

## Extending pgvet

The plugin host *is* the tool — adding a check never touches the core. A check is a
small, pure function that yields `Finding`s:

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

Ship it from your own package via an entry-point group (`pgvet.advisors` for
plan checks, `pgvet.inferencers` for data checks); pgvet discovers it at startup:

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

pgvet runs `EXPLAIN (ANALYZE, FORMAT JSON)`, normalizes the result into a
version-independent plan model, and runs the checks over it. Data checks (`infer`) go
through a `Sampler` that keeps all inference SQL in one place. The TUI and the CLI are
thin views over the same engine, so anything you see interactively you can also get as
JSON for CI. There's a deeper tour in `docs/ARCHITECTURE.md`.

## Status

Shipped and working: query diagnostics (`report`/`tui`), plan diffing + history,
hypothetical-index testing (HypoPG), and constraint inference (`infer`). Next up:
**ORM↔DB drift detection** (compare your SQLAlchemy/Django models to the live schema).

## Safety

pgvet is read-mostly: it runs `EXPLAIN`, catalog lookups, and bounded sample queries,
and uses only *hypothetical* (in-memory) indexes when testing. It **never** issues
DDL/DML on its own — every suggested `ALTER TABLE`/index is yours to review and apply.
Connection credentials are read from the environment and redacted in all output.
