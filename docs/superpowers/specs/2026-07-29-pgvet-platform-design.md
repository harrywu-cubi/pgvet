# pgvet — Design Spec

*A pluggable, local-only PostgreSQL doctor. Status: **design / not yet implemented**. Date: 2026-07-29.*

---

## 1. Summary

`pgvet` is a keyboard-driven terminal tool that connects to a **local or dev**
PostgreSQL database and helps developers diagnose and improve it. Its defining
property is that **the plugin host is the product**: the core is a thin platform
(connection + introspection + a normalized plan/schema model + a plugin registry
+ a TUI shell), and every actual capability ships as a plugin against a stable
interface.

Three plugin *families* are planned on one shared core:

1. **Advisors** (the query-&-index *workbench*) — edit a query, see the execution
   plan, diff two plans, test hypothetical indexes, and get rule-based findings.
   *This is the first family we build.*
2. **Inferencers** (a *constraint-inference* doctor) — infer constraints the data
   already obeys but the schema never declared (undeclared FKs, de-facto unique
   columns, effective enums) and emit reviewable DDL.
3. **Drift rules** (an *ORM↔DB drift* doctor) — compare ORM models against the
   live dev DB and report drift, including facets migration autogenerators miss.

Families 2 and 3 are **designed-for now, built later**. Nothing in the core is
specific to any one family.

### Goals

- A genuinely daily-use developer tool that runs entirely on local resources.
- Extensibility as the primary architectural driver: adding a capability means
  writing a plugin, never editing the core.
- A large but incrementally shippable project: a useful MVP exists early; the
  full vision layers on the same core.

### Non-goals

- **No production monitoring / no cloud.** pgvet targets local/dev databases.
- **No dependence on any credentialed external API.** The only network call is a
  connection to a Postgres instance the developer already controls, addressed by
  a `DATABASE_URL` environment variable. This keeps pgvet inside the workstation's
  data-boundary rules (see §11).
- **Not a general SQL IDE or admin tool** (no user management, no backups). pgvet
  diagnoses; it does not administer.

---

## 2. Users & usage modes

Primary user: a backend / data developer working in a codebase with a real
Postgres schema.

Two distinct usage modes, both first-class:

- **Daily / hourly (Advisors):** "this query is slow" → open pgvet, iterate on the
  plan, ship a fix. Reached for constantly during development.
- **Start-of-an-area (Inferencers, Drift):** "I'm entering this schema" or "did my
  branch switch desync my models?" → run a scan, review findings once in a while.

Designing for both is deliberate: it's why the tool is worth keeping installed.

---

## 3. Architecture overview

```
                        ┌────────────────────────────────────────┐
                        │                  TUI shell              │
                        │      (Textual App + panel widgets)      │
                        └───────────────┬────────────────────────┘
                                        │ uses
                        ┌───────────────▼────────────────────────┐
                        │                Session                  │
                        │  orchestrates a run: gathers context,   │
                        │  invokes plugins, collects Findings      │
                        └───┬───────────────┬──────────────┬──────┘
                            │               │              │
                 ┌──────────▼───┐   ┌────────▼──────┐  ┌────▼─────────┐
                 │  Registry    │   │   Context      │  │  Findings    │
                 │ (plugin      │   │  builders      │  │  collector   │
                 │  discovery)  │   │ (Plan/Schema/  │  │              │
                 └──────┬───────┘   │  Drift)        │  └──────────────┘
                        │           └───┬─────────┬──┘
          discovers     │               │ built from
      plugins via       │        ┌──────▼──────┐ ┌▼──────────────┐
      entry points +    │        │ Introspect  │ │   Explain     │
      builtin registry  │        │ → SchemaIR  │ │ → PlanIR/Diff │
                        │        └──────┬──────┘ └───────┬───────┘
              ┌─────────▼─────────┐     │                │
              │  Plugin families  │     └───────┬────────┘
              │ advisors /         │            │ via
              │ inferencers /      │      ┌──────▼───────┐
              │ drift rules        │      │ Connection    │
              │ (base classes)     │      │ manager       │
              └────────────────────┘      │ (psycopg pool)│
                                          └──────┬────────┘
                                                 │
                                          local / dev Postgres
                                          (DATABASE_URL)
```

### Layered dependency rule

Dependencies point **downward only**:

`tui` → `session` → (`registry`, `context builders`, `findings`) →
(`introspect`, `explain`) → (`planmodel`, `schemamodel`, `findings` dataclasses) →
`connection` → psycopg.

- The **core model layer** (`planmodel`, `schemamodel`, `findings`) has *no*
  dependencies on psycopg, Textual, or plugins. It is pure dataclasses. Plugins
  and tests depend only on this layer, which is what makes plugins stable across
  Postgres versions and lets the whole engine be tested without a live DB.
- The **TUI never talks to psycopg directly.** It only calls `Session`. This means
  a `--report` non-interactive CLI mode reuses the exact same engine with no TUI.

---

## 4. The plugin model (the heart of the design)

Extensibility is the top requirement, so the plugin contract is specified first
and everything else serves it.

### 4.1 Discovery

Two discovery sources, unified by the `Registry`:

1. **Built-in registry** — shipped plugins registered in code (fast, no packaging).
2. **Entry points** — third-party packages advertise plugins via
   `importlib.metadata` entry-point groups:
   - `pgvet.advisors`
   - `pgvet.inferencers`
   - `pgvet.drift_rules`

A third party ships a plugin by declaring, in *their* `pyproject.toml`:

```toml
[project.entry-points."pgvet.advisors"]
timescale = "pgvet_timescale.advisors:register"
```

The `Registry` imports each entry point, calls its `register(registry)` hook, and
the plugin's classes become available. Discovery is lazy and failure-isolated: a
broken third-party plugin logs a warning and is skipped; it never crashes pgvet.

### 4.2 The base contract

All plugins share a minimal protocol (`plugins/base.py`):

```python
class Plugin(Protocol):
    id: str                 # stable, unique, e.g. "advisor.seq_scan"
    name: str               # human label
    family: Family          # ADVISOR | INFERENCER | DRIFT
    def applies_to(self, ctx: Context) -> bool: ...
    def run(self, ctx: Context) -> Iterable[Finding]: ...
```

Each family narrows `Context` to a concrete type:

- `PlanContext` — the current `PlanTree`, the previous `PlanTree` (may be `None`),
  the `PlanDiff`, the query text, and the `SchemaModel`.
- `SchemaContext` — the `SchemaModel` plus a `Sampler` handle for pulling bounded
  data samples (used by inferencers).
- `DriftContext` — the introspected `SchemaModel` (live) plus a declared
  `SchemaModel` produced by an ORM adapter.

Plugins are **pure functions over their context**: they receive a context and
yield `Finding`s. They do not open connections, do not mutate the DB, and do not
touch the TUI. This is what makes them independently testable and safe.

### 4.3 Findings

Every plugin communicates through one output type:

```python
@dataclass(frozen=True)
class Finding:
    plugin_id: str
    severity: Severity          # INFO | SUGGEST | WARN | CRITICAL
    title: str                  # one line
    detail: str                 # markdown; rendered in the TUI
    location: Optional[Location]  # table/column/plan-node this points at
    evidence: dict              # structured support (row counts, costs, samples)
    suggestion: Optional[Suggestion]  # e.g. candidate DDL / query rewrite
```

`Suggestion` carries an optional machine-applicable payload (candidate SQL/DDL) so
the TUI can offer "copy" or, where safe, "apply as reviewed migration." The core
**never auto-applies** anything; a suggestion is always human-gated.

### 4.4 Why this satisfies "extend later without touching core"

- A new advisor is a new class in a new module, registered via one line — the
  plan-diff loop, the TUI, and the findings pane all work unchanged.
- A whole new *family* (e.g. a future `SourceAdapter` for `flightrec`-style work)
  is added by defining a new `Context` type + entry-point group; the `Registry`,
  `Session`, and `Findings` collector are generic over `Family`.

---

## 5. Core components (units, each with one purpose)

| Module | Responsibility | Depends on | Testable via |
|---|---|---|---|
| `core/connection.py` | Own the psycopg connection/pool; resolve `DATABASE_URL`; enforce read-mostly session | psycopg, `config` | mocked psycopg / local dev DB |
| `core/introspect.py` | Query `pg_catalog`/`information_schema` → `SchemaModel` | `connection`, `schemamodel` | recorded catalog snapshots (JSON fixtures) |
| `core/explain.py` | Run `EXPLAIN (ANALYZE, FORMAT JSON)`; parse JSON → `PlanTree`; compute `PlanDiff` | `connection`, `planmodel` | **recorded EXPLAIN JSON fixtures** |
| `core/planmodel.py` | `PlanNode`, `PlanTree`, `PlanDiff` dataclasses + normalization | — (pure) | pure unit tests |
| `core/schemamodel.py` | `Table`, `Column`, `Index`, `Constraint`, `SchemaModel` | — (pure) | pure unit tests |
| `core/findings.py` | `Finding`, `Severity`, `Suggestion`, `Location` | — (pure) | pure unit tests |
| `core/registry.py` | Discover + register plugins (builtin + entry points); failure isolation | `plugins.base` | fake entry points |
| `core/session.py` | Build the right `Context`, run applicable plugins, collect findings | all core | fixture-driven end-to-end |
| `core/hypo.py` | Drive HypoPG: create/drop hypothetical indexes around a re-plan | `connection` | mocked / local dev DB |
| `storage/history.py` | Persist plan runs to local SQLite, keyed by query hash + git/migration state | stdlib sqlite3 | temp DB file |
| `config.py` | Settings: connection resolution, plugin enable/disable, keybindings | stdlib | pure unit tests |
| `cli.py` / `__main__.py` | Entry point; subcommands `tui`, `report`, `plugins` | `session`, `tui` | CLI invocation tests |

### The hardest risk, isolated on purpose

Mapping Postgres's JSON `EXPLAIN` output — which varies by major version and node
type — into a stable `PlanTree` is the project's top technical risk. It is
**quarantined inside `explain.py`'s normalization step**. Plugins depend only on
`planmodel`, never on raw EXPLAIN JSON, so a new Postgres release means updating
one normalization layer, not every plugin. The normalizer is version-aware and
tested against recorded fixtures from multiple PG major versions.

---

## 6. Key data models

### PlanTree / PlanNode (normalized)

Each `PlanNode` carries a small, stable surface the advisors rely on:
`node_type` (normalized enum, e.g. `SEQ_SCAN`, `INDEX_SCAN`, `NESTED_LOOP`,
`SORT`, `HASH_JOIN`), `relation`, `estimated_rows`, `actual_rows`,
`estimated_cost`, `actual_time_ms`, `loops`, `buffers`, and `children`. A
`misestimate_factor` convenience property = `max(est/actual, actual/est)`.

### PlanDiff

Given two `PlanTree`s for the same normalized query, `PlanDiff` aligns nodes by
structural position and reports per-node deltas (cost, rows, time, node-type
changes) and a top-level verdict (`FASTER`/`SLOWER`/`SAME` within a threshold).
Node alignment across structurally different plans is a known hard sub-problem; v1
uses positional + node-type alignment and flags "structure changed" when it can't
align confidently rather than inventing a misleading diff.

### SchemaModel

A normalized snapshot: tables → columns (type, nullable, default), indexes
(columns, unique, partial predicate), constraints (PK/FK/unique/check), enums.
Produced by `introspect.py` from the live DB, and (later) by ORM adapters from
model definitions — the *same* type on both sides is what makes drift detection a
clean comparison.

---

## 7. Data flow (Advisor / workbench happy path)

1. User opens the TUI, picks/enters a query.
2. `Session` asks `explain.py` to run `EXPLAIN (ANALYZE, FORMAT JSON)` → `PlanTree`.
3. `Session` loads the previous `PlanTree` for this query hash from `history` (if
   any), computes `PlanDiff`.
4. `Session` builds a `PlanContext` (plan, prev, diff, query, schema) and runs all
   applicable advisors from the `Registry`, collecting `Finding`s.
5. TUI renders three panes: plan tree (with heat), plan diff, findings.
6. User opts to "test a hypothetical index": `hypo.py` creates a HypoPG
   hypothetical index, `Session` re-plans (no `ANALYZE`, since the index isn't
   real), shows the new estimated plan vs. the baseline, then drops the
   hypothetical index. Nothing is built on disk.
7. On request, the current run is written to `history` keyed by query hash + git
   HEAD / latest migration id, so "when did this get slow?" becomes a query.

---

## 8. TUI structure

- **Framework:** Textual (async, widget-based), Rich for plan-tree rendering.
- **Layout:** left = query editor / query picker; center = plan tree (color-heat by
  cost/time and by misestimate); right/bottom = plan diff and findings list.
  Selecting a finding highlights the plan node or schema object it points at.
- **Keyboard-first:** run (`ctrl-r`), diff-against-previous, add-hypothetical-index,
  toggle a plugin, export report.
- **Panels are thin views over `Session` output.** No DB logic in widgets. A panel
  is essentially a renderer for one slice of the run result, which keeps the TUI
  independently replaceable (and means the `report` CLI mode needs no TUI at all).

---

## 9. CLI surface

`pgvet` ships one console script with subcommands:

- `pgvet tui` — launch the interactive workbench (default).
- `pgvet report --query FILE` / `--sql "..."` — non-interactive: run the engine,
  print findings (text or JSON via `--format json`) for CI or scripting.
- `pgvet plugins list` — show discovered plugins, family, source (builtin/entry
  point), enabled state.
- `pgvet scan --inferencers` / `--drift` — (later families) one-shot start-of-area
  scans.

All subcommands share the same `Session` engine.

---

## 10. Error handling

- **Connection errors:** surfaced as a clear, actionable message ("set
  `DATABASE_URL`, or is your dev Postgres running?"), never a stack trace in the
  TUI. `report` mode exits non-zero with a diagnostic.
- **Plugin errors:** a plugin that raises is caught by the `Session`; it produces a
  single `WARN` finding ("plugin X failed") and the run continues. One bad plugin
  never breaks a run.
- **Unparseable EXPLAIN / unknown node type:** the normalizer degrades gracefully —
  unknown nodes become a generic `PlanNode` with `node_type=UNKNOWN` and the raw
  payload preserved in `evidence`, so advisors that don't understand it simply
  don't fire.
- **HypoPG not installed:** hypothetical-index features are detected at startup and
  disabled with an explanatory note; the rest of the tool works.

---

## 11. Security & workstation-boundary notes

This tool is being designed on a **network-restricted workstation** paired with a
separate internet-connected machine. The design respects that boundary:

- The **only** network egress is a connection to a Postgres instance the developer
  controls (localhost or a dev host), addressed by `DATABASE_URL`. This is local
  infrastructure, **not** a credentialed third-party data-source API — pgvet never
  calls any external service whose keys live off-machine.
- **Secrets are read from the environment by name only** (`DATABASE_URL`, or
  discrete `PGHOST`/`PGUSER`/… vars). pgvet never stores, logs, or prints a
  password; connection strings are redacted in all output and history records.
- **pgvet is read-mostly.** It runs `EXPLAIN`, catalog queries, and bounded
  `SELECT` samples. It creates *hypothetical* (HypoPG) indexes only, which are
  session-local and never touch disk. It never issues DDL/DML on its own; any
  suggested DDL is copy/apply-gated by the human. The engine should open its
  working session with a read-only transaction default where feasible.
- **Test data is committed sample data / recorded fixtures**, never fabricated and
  never a live production endpoint. See §12.

---

## 12. Testing strategy

Three tiers, most weight on the fast tier:

1. **Pure unit (no DB):** `planmodel`, `schemamodel`, `findings`, `config`, and
   every plugin. Plugins are pure functions over context, so a plugin test
   constructs a `PlanContext`/`SchemaContext` from a fixture and asserts on the
   `Finding`s. This is the bulk of the suite and needs no Postgres.
2. **Fixture-driven engine tests:** `explain.py` and `introspect.py` are tested
   against **recorded, committed artifacts** — real `EXPLAIN (FORMAT JSON)` outputs
   and real catalog snapshots captured from actual databases (by the paired
   machine / from sample schemas), stored under `tests/fixtures/`. This is how we
   test the normalizer against multiple PG major versions **without** a live
   connection, and it mirrors the standing rule: build against real committed
   sample data, mock the actual call.
3. **Optional integration (local dev Postgres):** a marked, opt-in tier
   (`-m integration`) that runs against a throwaway local Postgres (developer-run,
   e.g. a local container or installed instance). Skipped by default and in any
   restricted environment. **Never** run against a shared/prod endpoint.

Test-driven: each core module and plugin is built test-first per the repo's TDD
workflow.

---

## 13. Tech stack & dependencies

- **Runtime:** Python 3.11+.
- **DB:** `psycopg[binary]` 3.x.
- **SQL parsing / DDL emission:** `sqlglot`.
- **TUI / rendering:** `textual`, `rich`.
- **Fast local stats for inferencers (later):** `duckdb` or `polars` over samples.
- **LSP for drift-in-editor (later, optional extra):** `pygls`.
- **Hypothetical indexes:** the **HypoPG** Postgres extension (a DB-side dependency,
  detected at runtime; not a Python package).
- **Packaging / env:** `uv` for environment and dependency management (per
  workstation convention — never `pip`). `pyproject.toml`, `src/` layout.
- **Testing:** `pytest`, `pytest-cov`.

Dependency risk is low: every core-family library (psycopg, sqlglot, textual) is
mature. The one non-Python dependency (HypoPG) is optional and feature-gated.

---

## 14. Package layout

```
pgvet/
  pyproject.toml
  README.md
  docs/superpowers/specs/2026-07-29-pgvet-platform-design.md   # this file
  src/pgvet/
    __init__.py
    __main__.py            # python -m pgvet
    cli.py                 # subcommands: tui / report / plugins / scan
    config.py
    core/
      connection.py
      introspect.py
      explain.py
      hypo.py
      planmodel.py         # pure
      schemamodel.py       # pure
      findings.py          # pure
      registry.py
      session.py
    plugins/
      base.py              # Plugin protocol, Family, Context types
      advisors/            # FIRST family (workbench)
        seq_scan.py
        row_estimate.py
        sort_spill.py
        nested_loop.py
        unused_index.py
      inferencers/         # designed-for, built later
      drift/               # designed-for, built later
    storage/
      history.py           # SQLite plan history
    tui/
      app.py
      panels/
        query_editor.py
        plan_tree.py
        plan_diff.py
        findings.py
  tests/
    fixtures/
      plans/               # recorded EXPLAIN JSON (multiple PG versions)
      catalog/             # recorded introspection snapshots
    unit/
    engine/
    integration/           # opt-in, marked
```

---

## 15. Scope ladder (milestones)

The full build happens **after** this session; this ladder is what the
implementation plan will sequence.

- **M0 — Skeleton & core model.** `pyproject.toml` (uv), package layout, pure
  dataclasses (`planmodel`, `schemamodel`, `findings`), `config`, the `Plugin`
  base contract, and the `Registry` (builtin + entry-point discovery). Fully
  unit-tested, no DB.
- **M1 — Engine (fixture-driven).** `connection`, `introspect`, `explain` +
  normalizer, `session`. Tested entirely against recorded fixtures. `pgvet report`
  works from a fixture; no TUI yet.
- **M2 — Advisor family v1.** First 3–5 advisors (seq-scan, row-misestimate,
  sort-spill, nested-loop blowup, unused-index) as pure, tested plugins.
- **M3 — TUI workbench.** Textual app: query editor, plan tree with heat, findings
  pane. Wraps the M1/M2 engine.
- **M4 — Plan diff + history.** `PlanDiff`, `storage/history` keyed by query hash +
  git/migration state, diff pane, "when did this get slow" view.
- **M5 — Hypothetical indexes.** `hypo.py` + HypoPG integration; "add hypothetical
  index → re-plan → compare" loop.
- **M6+ — Later families.** Inferencer family (constraint inference + DDL
  suggestions) and Drift family (ORM adapters + drift rules, optional `pygls` LSP)
  — each on the unchanged core, proving the extensibility thesis.

MVP line = **M0–M3** (a useful, extensible workbench). Everything past it layers on
the same core.

---

## 16. Open questions / risks

1. **Plan-node alignment for diffs** across structurally different plans — v1
   degrades to "structure changed" rather than guessing. Revisit if noisy.
2. **EXPLAIN normalization across PG versions** — mitigated by fixtures per major
   version; still the top maintenance cost.
3. **Inferencer cost on large tables** (later) — uniqueness/FK inference is
   super-linear across column pairs; will require sampling with confidence bounds.
   Out of scope until M6, but the `Sampler` handle in `SchemaContext` is reserved
   for it now.
4. **Cross-ORM schema IR** (later) — SQLAlchemy and Django model concepts
   differently; the shared `SchemaModel` must be rich enough to compare both
   without false-positive drift.
5. **Name availability** — confirm `pgvet` is free on PyPI before first publish
   (not probed from this workstation).
