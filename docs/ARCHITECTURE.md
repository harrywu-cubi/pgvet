# pgvet — Architecture & Code Walkthrough

**Read this once and you can explain pgvet's design and code — including in an
interview.** It goes top-down: the idea, the shape, then each part with the *actual*
code and the *why* behind it, and ends with a flow trace, the design tradeoffs, and a
Q&A you can rehearse.

Terms you may not know are defined in the **Glossary** at the bottom — jump there first
if "execution plan" or "sequential scan" are new to you.

---

## 1. The problem and the one big idea

**Problem.** When a PostgreSQL query is slow, the database can tell you *how* it intends
to run it — the **execution plan** (`EXPLAIN`). But reading that plan is an expert skill,
and the good tooling is either read-only viewers, fire-and-forget scripts, or paid cloud
products. There's no free, local, *extensible* tool that reads a plan and hands you
plain-English advice.

**The one big idea: the plugin host IS the product.** pgvet's core is deliberately thin —
it connects to Postgres, turns a plan into a clean data structure, and runs a list of
**advisors** over it. Every actual piece of intelligence (each rule) is a plugin. Adding
a new check never means editing the core; you write a new plugin. This is the single
most important thing to be able to say about the project.

Three design pillars follow from that idea:
1. **A thin core + plugins.** Capabilities are plugins discovered at runtime.
2. **A normalized plan model.** Plugins never see raw Postgres JSON; they see a stable
   Python model. All Postgres-version quirks are quarantined in one file.
3. **Everything is a thin view over one engine.** The terminal UI and the CLI both just
   call the same `Session`; there's no logic duplicated between them.

---

## 2. The mental model (say this first in an interview)

> "pgvet runs `EXPLAIN` on your query, normalizes the result into a plain Python plan
> tree, and then runs a list of plugin *advisors* over that tree; each advisor is a pure
> function that looks for one problem and yields *findings*. The TUI and CLI are just two
> front-ends over the same engine."

Everything below is the detail behind that sentence.

---

## 3. Architecture at a glance

```
        pgvet tui                       pgvet report / plugins
            │                                   │
            ▼                                   ▼
      ┌───────────┐                       ┌───────────┐
      │  TUI app  │                       │    CLI    │      ← thin views
      │ (Textual) │                       │ (argparse)│
      └─────┬─────┘                       └─────┬─────┘
            └──────────────┬───────────────────-┘
                           ▼
                     ┌───────────┐
                     │  Session  │   the engine: build context, run advisors
                     └─────┬─────┘
             ┌────────────-┼───────────────┐
             ▼             ▼                ▼
      ┌───────────┐  ┌───────────┐   ┌───────────┐
      │ Registry  │  │  explain  │   │ introspect│
      │ (plugins) │  │(EXPLAIN → │   │(catalog → │
      └─────┬─────┘  │ PlanTree) │   │SchemaModel)│
            │        └─────┬─────┘   └─────┬─────┘
            ▼              └─────────┬─────┘
      ┌───────────┐                 ▼
      │ Advisors  │           ┌───────────┐
      │(plugins)  │──depend──▶│ pure model│  PlanNode/PlanTree, SchemaModel, Finding
      └───────────┘   only on └─────┬─────┘
                                    ▼
                              ┌───────────┐
                              │Connection │  (the only psycopg in the codebase)
                              └─────┬─────┘
                                    ▼
                              local/dev PostgreSQL
```

**The golden rule — dependency direction points down and never up.** The pure model layer
(`planmodel`, `schemamodel`, `findings`) imports nothing from the rest of pgvet. Advisors
import *only* that pure layer. The TUI/CLI import only `Session`. Nothing above the model
depends on psycopg except the one `Connection` file. This is what makes the pieces
independently testable and the plugins stable.

---

## 4. Directory map (file → responsibility)

```
src/pgvet/
  cli.py                     entry point; argparse; report/plugins/tui commands
  config.py                  Settings.from_env() reads DATABASE_URL; redact() hides passwords
  core/
    connection.py            the ONLY psycopg code — fetch_one/fetch_all/close
    explain.py               EXPLAIN JSON  ->  PlanTree   (the version quarantine)
    introspect.py            information_schema/pg_catalog  ->  SchemaModel
    planmodel.py             NodeType, PlanNode, PlanTree   (pure)
    schemamodel.py           Table/Column/Index/Constraint/SchemaModel   (pure)
    findings.py              Finding/Severity/Location/Suggestion   (pure)
    registry.py              plugin discovery + registration
    session.py               the engine: analyze() and run_query()
  plugins/
    base.py                  the plugin contract: Family, PlanContext, Advisor
    advisors/
      __init__.py            register_builtins() wires the 5 shipped advisors
      seq_scan.py … unused_index.py    the 5 advisors
  tui/
    app.py                   PgvetApp (Textual) — a thin view over Session
    panels/plan_tree.py      render a PlanTree as a Rich tree
    panels/findings.py       render findings as a Rich table
```

If someone asks "where would you add X?", the answer is almost always "a new file in
`plugins/advisors/` plus one line in `__init__.py`" — that's the whole point.

---

## 5. The vocabulary: the three pure data models

These three modules are the shared language everything else speaks. They're plain
dataclasses with no dependencies, so they're trivial to construct in tests and to reason
about.

### 5a. `Finding` — the single output type (`core/findings.py`)

Every advisor communicates results as `Finding`s and nothing else:

```python
class Severity(str, Enum):
    INFO = "INFO"; SUGGEST = "SUGGEST"; WARN = "WARN"; CRITICAL = "CRITICAL"

@dataclass(frozen=True)
class Finding:
    plugin_id: str
    severity: Severity
    title: str
    detail: str
    location: Location | None = None      # which table / plan node it points at
    evidence: dict = field(default_factory=dict)   # structured support (rows, cost…)
    suggestion: Suggestion | None = None  # optional fix (e.g. candidate SQL)
```

*Why:* one output type means the UI, the JSON CLI, and any future consumer all handle
results uniformly. `Severity` subclasses `str` so it serializes to JSON directly.
`frozen=True` makes findings immutable value objects.

### 5b. `PlanNode` / `PlanTree` — the normalized plan (`core/planmodel.py`)

This is Postgres's execution plan as a clean tree. Note the two computed properties —
they encode domain knowledge so advisors don't have to:

```python
@dataclass
class PlanNode:
    node_type: NodeType          # normalized enum (SEQ_SCAN, INDEX_SCAN, …)
    relation: str | None         # table name, if this node scans one
    estimated_rows: float        # planner's guess
    actual_rows: float | None    # measured, per-loop (None if EXPLAIN had no ANALYZE)
    estimated_cost: float
    actual_time_ms: float | None
    loops: float
    children: list["PlanNode"]
    raw: dict                    # the original JSON node (escape hatch + round-trip)

    @property
    def total_actual_rows(self) -> float | None:
        # Postgres reports actual rows PER LOOP; total = per-loop × loops.
        return None if self.actual_rows is None else self.actual_rows * self.loops

    @property
    def misestimate_factor(self) -> float | None:
        actual = self.total_actual_rows
        if actual is None or actual <= 0 or self.estimated_rows <= 0:
            return None
        return max(self.estimated_rows / actual, actual / self.estimated_rows)
```

Two subtleties worth being able to explain:
- **Per-loop rows.** Postgres reports `Actual Rows` *per iteration* of a node. If a node
  runs 950 times returning 1 row each, the true total is 950. `total_actual_rows`
  captures that; getting it wrong is a classic plan-reading mistake.
- **Misestimate factor** is symmetric: `max(est/actual, actual/est)`, so both "estimated
  10, got 10000" and "estimated 10000, got 10" come out as a large factor. Bad estimates
  are *the* root cause of bad plans, which is why this lives in the model.

`PlanTree` wraps the root plus timings and offers `walk()`:

```python
def walk(self) -> Iterator[PlanNode]:
    stack = [self.root]
    while stack:
        node = stack.pop(0)
        yield node
        stack = node.children + stack   # prepend children -> depth-first pre-order
```

Advisors almost always start with `for node in ctx.plan.walk():` — one line to visit
every node in the plan.

### 5c. `SchemaModel` — the database's shape (`core/schemamodel.py`)

Tables → columns/indexes/constraints, produced by introspection. Advisors that need to
know "does this table have an index?" read it. It has helpers like
`table(name)` and `Table.has_unique_on(cols)`. It's the same type both a live DB
(now) and future ORM adapters (M6) produce, so drift detection can compare them later.

---

## 6. The plugin system — the heart of pgvet

### 6a. The contract (`plugins/base.py`)

```python
class Family(str, Enum):
    ADVISOR = "ADVISOR"; INFERENCER = "INFERENCER"; DRIFT = "DRIFT"

@dataclass
class PlanContext:
    plan: PlanTree
    query: str
    schema: SchemaModel
    previous: PlanTree | None = None   # reserved for M4 plan-diff

class Advisor(ABC):
    """A pure function over a PlanContext that yields Findings."""
    id: str
    name: str
    family: Family = Family.ADVISOR

    def applies_to(self, ctx: PlanContext) -> bool:
        return True

    @abstractmethod
    def run(self, ctx: PlanContext) -> Iterable[Finding]:
        ...
```

Three things to point out:
- An advisor is **pure**: it takes a `PlanContext`, yields `Finding`s, and touches nothing
  else — no database, no I/O, no globals. That's why every advisor is testable with a
  hand-built context and no Postgres.
- `applies_to` is an optional cheap pre-filter; `run` is the required work.
- The `Family` enum and the separate context types are the **forward-compatibility seam**.
  The MVP only ships `ADVISOR`, but `INFERENCER` (infer constraints from data) and `DRIFT`
  (compare ORM models to the DB) are already accommodated: a new family is a new context
  type + a new entry-point group, *not* a change to the registry or engine.

### 6b. Discovery + registration (`core/registry.py`)

```python
ADVISOR_GROUP = "pgvet.advisors"

class Registry:
    def __init__(self): self._advisors: dict[str, Advisor] = {}

    def register(self, plugin):
        if plugin.id in self._advisors:
            raise ValueError(f"duplicate plugin id: {plugin.id}")
        self._advisors[plugin.id] = plugin

    @property
    def advisors(self): return list(self._advisors.values())

    def discover(self, entry_points=None):
        if entry_points is None:
            entry_points = _entry_points(group=ADVISOR_GROUP)
        for ep in entry_points:
            try:
                register_fn = ep.load()
                register_fn(self)
            except Exception as exc:        # a broken 3rd-party plugin is skipped…
                log.warning("skipping plugin entry point %r: %s", ep.name, exc)

    def load_builtins(self):
        from pgvet.plugins.advisors import register_builtins   # lazy import
        register_builtins(self)
```

The registry has **two sources**:
- **Built-ins** — `load_builtins()` registers the 5 advisors that ship with pgvet.
- **Third-party** — `discover()` uses Python's `importlib.metadata` **entry points**. Any
  installed package can advertise a `pgvet.advisors` entry point; pgvet finds it at
  startup. This is the mechanism that lets someone extend pgvet *without touching this
  repo at all*.

Two robustness details to call out: `register` **rejects duplicate ids** (fail fast), and
`discover` **isolates failures** — a broken plugin logs a warning and is skipped, so a bad
third-party plugin can never crash pgvet. The `load_builtins` import is *lazy* (inside the
method) to avoid an import cycle, since advisors import from the core that defines the
registry.

### 6c. What "adding a capability" actually looks like — read one advisor

`plugins/advisors/seq_scan.py` — flags a sequential scan over a big table:

```python
ROW_THRESHOLD = 10_000

class SeqScanAdvisor(Advisor):
    id = "advisor.seq_scan"
    name = "Sequential scan on large relation"

    def run(self, ctx: PlanContext) -> Iterable[Finding]:
        for node in ctx.plan.walk():
            if node.node_type != NodeType.SEQ_SCAN or node.relation is None:
                continue
            rows = node.total_actual_rows or node.estimated_rows
            if rows < ROW_THRESHOLD:
                continue
            yield Finding(
                plugin_id=self.id, severity=Severity.WARN,
                title=f"Seq Scan over large table `{node.relation}`",
                detail=f"Sequential scan reads ~{int(rows)} rows from `{node.relation}`. "
                       "Consider an index on the filtered columns.",
                location=Location(kind="table", identifier=node.relation),
                evidence={"rows": rows, "cost": node.estimated_cost},
                suggestion=Suggestion(kind="note", note=f"Inspect the WHERE/JOIN predicates on `{node.relation}`…"),
            )
```

That is the whole shape of a plugin: walk the plan, skip nodes you don't care about,
`yield` a `Finding` when your rule matches. The other four advisors are variations —
`row_estimate` checks `misestimate_factor`, `sort_spill` reads `node.raw["Sort Method"]`,
`nested_loop` checks child `loops`, `unused_index` cross-references `ctx.schema`.

Finally, `plugins/advisors/__init__.py` lists them:
```python
def register_builtins(registry):
    for cls in [SeqScanAdvisor, RowEstimateAdvisor, SortSpillAdvisor,
                NestedLoopAdvisor, UnusedIndexAdvisor]:
        registry.register(cls())
```

---

## 7. The engine (`core/session.py`)

`Session` is small on purpose. It has two methods:

```python
class Session:
    def __init__(self, conn, registry): self._conn, self._registry = conn, registry

    def analyze(self, ctx: PlanContext) -> list[Finding]:
        findings = []
        for advisor in self._registry.advisors:
            try:
                if advisor.applies_to(ctx):
                    findings.extend(advisor.run(ctx))
            except Exception as exc:                       # one bad plugin can't break a run
                log.warning("advisor %s failed: %s", advisor.id, exc)
                findings.append(Finding(advisor.id, Severity.WARN,
                                        f"Advisor {advisor.id} failed", str(exc)))
        return findings

    def run_query(self, sql: str) -> RunResult:
        plan = run_explain(self._conn, sql)                # EXPLAIN (ANALYZE, …)
        schema = introspect(self._conn)                    # catalog -> SchemaModel
        ctx = PlanContext(plan=plan, query=sql, schema=schema)
        return RunResult(query=sql, plan=plan, findings=self.analyze(ctx))
```

- **`analyze(ctx)` is pure** — no database. Give it a context, get findings. This is what
  the `report` CLI and every test use. Note the per-advisor `try/except`: an exception in
  one advisor becomes a `WARN` finding, and the loop continues. **Isolation is a core
  guarantee.**
- **`run_query(sql)` is the connected path** — it fetches the plan and schema, builds the
  context, then calls `analyze`. It's the only method that needs a live connection, and
  even it takes `conn` by dependency injection so tests pass a fake.

`RunResult` is just `(query, plan, findings)`.

---

## 8. The version quarantine (`core/explain.py`)

This is the riskiest part of any Postgres tool — the plan JSON changes across Postgres
versions and node types — so it's isolated in one place:

```python
def _node(raw: dict) -> PlanNode:
    return PlanNode(
        node_type=NodeType.from_pg(raw.get("Node Type", "")),
        relation=raw.get("Relation Name"),
        estimated_rows=float(raw.get("Plan Rows", 0)),
        actual_rows=float(raw["Actual Rows"]) if "Actual Rows" in raw else None,
        estimated_cost=float(raw.get("Total Cost", 0)),
        actual_time_ms=float(raw["Actual Total Time"]) if "Actual Total Time" in raw else None,
        loops=float(raw.get("Actual Loops", 1)),
        children=[_node(c) for c in raw.get("Plans", [])],   # recurse into subplans
        raw=raw,
    )

def parse_explain_json(payload) -> PlanTree:
    top = payload[0] if isinstance(payload, list) else payload
    return PlanTree(root=_node(top["Plan"]),
                    planning_time_ms=top.get("Planning Time"),
                    execution_time_ms=top.get("Execution Time"))

def run_explain(conn, sql, analyze=True) -> PlanTree:
    options = "ANALYZE, BUFFERS, FORMAT JSON" if analyze else "BUFFERS, FORMAT JSON"
    row = conn.fetch_one(f"EXPLAIN ({options}) {sql}")
    tree = parse_explain_json(row["QUERY PLAN"])
    tree.query = sql
    return tree
```

Why this matters and what to say about it:
- **All Postgres-specific key names (`"Node Type"`, `"Plan Rows"`, `"Actual Rows"`…) exist
  ONLY here.** Grep the rest of the codebase and you won't find them. Every advisor talks
  to `PlanNode`, not JSON. So a new Postgres release means updating *one* file, not every
  plugin. That's the quarantine.
- **Graceful degradation.** Unknown node types map to `NodeType.UNKNOWN` (via `from_pg`'s
  `dict.get` default) and the raw dict is preserved on `PlanNode.raw`, so a plan pgvet
  doesn't fully understand still parses instead of crashing.
- **`.get(..., default)` everywhere** so a plan produced *without* `ANALYZE` (no actual
  rows/times) parses fine — the fields just become `None`.

`run_explain` builds the `EXPLAIN` statement, and — key detail — takes any object with a
`fetch_one` method, so tests pass a fake that returns a canned JSON payload.

---

## 9. The two front-ends are thin views

### CLI (`cli.py`)

`main()` is argparse with three subcommands. The important structural point: the CLI holds
**no analysis logic** — it just wires the engine and formats output.

- `report --plan-file f` → `report_from_plan_file`: parse the file → `PlanContext` with an
  empty schema → `Session(conn=None).analyze(ctx)`. **`conn=None` works because `analyze`
  never touches the connection** — that's the payoff of keeping `analyze` pure. Output is
  text or `--format json`.
- `plugins` → `plugins_listing()` lists the registry.
- `tui` → `launch_tui()`: `Connection.connect(Settings.from_env())` → `Session` →
  `PgvetApp(analyze_query=session.run_query).run()`, closing the connection in `finally`.

There's a top-level `try/except` translating `FileNotFoundError`, `json.JSONDecodeError`,
and `RuntimeError` (e.g. missing `DATABASE_URL`) into a one-line stderr message + exit
code 2 — no tracebacks for user errors.

### TUI (`tui/app.py`)

```python
class PgvetApp(App):
    def __init__(self, analyze_query):          # a callable str -> RunResult
        self._analyze_query = analyze_query
        self.last_result = None
    def compose(self):                           # Header, an Input, plan+findings panes, Footer
        ...
    def on_input_submitted(self, event):
        self.run_analysis(event.value)
    def run_analysis(self, sql):
        result = self._analyze_query(sql)        # normally Session.run_query
        self.last_result = result
        self.query_one("#plan").update(render_plan_tree(result.plan))
        self.query_one("#findings").update(Group(..., render_findings(result.findings)))
```

The app doesn't import psycopg or `Session` types beyond `RunResult`; it takes an injected
`analyze_query` callable. That's why the TUI is testable **without a database** — the test
injects a lambda returning a canned `RunResult` and drives the app with Textual's `Pilot`
harness. The `panels/` renderers are pure functions (`PlanTree`/`Finding` → Rich
objects), tested on their own.

---

## 10. Testing strategy (and why it's DB-free)

- **57 tests, 92% coverage**, and **the whole suite runs with no database.** How:
  - Pure model + advisor tests build a `PlanContext` by hand.
  - Engine tests (`explain`, `introspect`, `session`) use a **fake connection** with the
    same tiny surface (`fetch_one`/`fetch_all`) or **recorded fixtures** (a saved
    `EXPLAIN` JSON in `tests/fixtures/plans/`).
  - The TUI test injects a fake analyzer and uses Textual's async test harness.
- The only things not covered are the live-DB code paths (`connection.connect`, the TUI
  launch) — by design; those get validated against a real Postgres, not in CI.
- Built **test-first (TDD)**: every task wrote a failing test, then the code to pass it.

The reason this is possible is the golden rule from §3: because the connection is behind a
2-method wrapper and injected everywhere, "needs a database" is confined to one file.

---

## 11. Design decisions & tradeoffs (rehearse these)

| Decision | Why | Tradeoff / what you'd change at scale |
|---|---|---|
| **Plugin host is the product** | Extensibility was the top goal; new checks shouldn't touch core | More indirection than a monolith; only pays off once there are many plugins |
| **Normalize EXPLAIN into a model** | Quarantine Postgres-version churn; make advisors simple + testable | A normalization layer to maintain; must add fields as advisors need them |
| **`analyze` pure, `run_query` connected** | Lets the CLI + all tests run with no DB | Two entry points to understand |
| **Entry-point plugin discovery** | Third parties extend pgvet without forking | Slightly "magic"; discovery failures must be isolated (they are) |
| **`walk()` uses `list.pop(0)`** | Simple, readable pre-order traversal | O(n) per pop; fine for <1000-node plans, would use `deque` if huge |
| **Table keyed by name, not schema.table** | Postgres `EXPLAIN` only reports the bare relation name | Multi-schema DBs with same-named tables can collide; noted as a follow-up |
| **DB-free test suite** | Fast, deterministic, runs anywhere incl. locked-down machines | Live paths need separate manual validation |

Being able to name a *tradeoff* for each decision is what makes you sound like the author,
not a narrator.

---

## 12. Limitations & roadmap (know what it does NOT do)

- **MVP scope.** Today it's the query-and-index *workbench*: run a query, read the plan,
  get advice. No history, no hypothetical indexes yet.
- **Planned, each with a written plan already in `docs/superpowers/plans/`:**
  - **M4** — plan *diffing* + a local history store ("when did this get slow?").
  - **M5** — *hypothetical* index testing via the HypoPG extension (try an index without
    building it).
  - **M6** — two more plugin families: *constraint inference* (infer undeclared
    constraints from data) and *ORM↔DB drift* detection. These have open design questions
    and need a design pass first.
- **Known rough edges:** multi-schema table-name collisions; the TUI runs the query
  synchronously (a very slow `EXPLAIN ANALYZE` would briefly block the UI); one advisor
  reads `node.raw` directly.

---

## 13. Explain-it scripts + interview Q&A

**60-second pitch:** "pgvet is a local PostgreSQL query doctor. You give it a query in a
terminal UI; it runs `EXPLAIN`, turns the plan into a clean Python tree, and runs a set of
plugin *advisors* that each flag one problem — a missing index, a bad row estimate, a sort
spilling to disk — with plain-English advice. The design point is that the core is tiny
and every check is a plugin, so you extend it by writing a new plugin, not editing the
core. The UI and CLI are both thin views over one engine, and the whole test suite runs
without a database because the connection is injected."

**Likely questions and honest answers:**

- *"Why plugins instead of just functions?"* — Discovery + isolation. Plugins register
  via entry points so a separate package can add checks without forking, and a broken
  plugin is skipped rather than crashing the tool. Functions would couple every check into
  the core.
- *"How do you handle different Postgres versions?"* — All version-specific JSON parsing
  is in `explain.py::parse_explain_json`. Everything downstream uses the normalized
  `PlanNode`. Unknown node types degrade to `UNKNOWN` with the raw JSON preserved, so it
  won't crash on a plan shape it hasn't seen.
- *"How is it tested without a database?"* — The connection is a 2-method wrapper injected
  everywhere; advisors are pure functions over a context; engine tests use fakes and
  recorded `EXPLAIN` fixtures. 57 tests, 92% coverage, zero DB.
- *"What was the hardest part?"* — Deciding the boundary of the normalized plan model:
  rich enough for advisors, but not leaking Postgres specifics. And getting the per-loop
  vs total row-count semantics right (`total_actual_rows`), which is a common plan-reading
  bug.
- *"What would you do next / at scale?"* — Plan diffing + history (M4), hypothetical
  indexes (M5), and two more plugin families (M6). At scale I'd revisit the `walk()`
  traversal, key schema by `schema.table`, and move the slow live query off the UI thread.

---

## Glossary (for beginners)

- **Execution plan** — the step-by-step strategy PostgreSQL chooses to run a query (which
  tables to read, in what order, using which method). You see it with `EXPLAIN`.
- **`EXPLAIN` / `EXPLAIN ANALYZE`** — `EXPLAIN` shows the planned strategy with *estimates*;
  `EXPLAIN ANALYZE` actually runs the query and adds *measured* rows/times. pgvet asks for
  it in JSON (`FORMAT JSON`) so it can parse it.
- **Sequential scan (Seq Scan)** — reading a table row by row, top to bottom. Fine for
  small tables, slow for big ones — usually a sign a useful index is missing.
- **Index scan** — using an index to jump to the rows you want instead of reading the
  whole table.
- **Nested loop / hash join / merge join** — three strategies Postgres uses to combine
  (join) two tables. A nested loop that runs an inner side a huge number of times is often
  a symptom of a bad estimate.
- **Row estimate vs actual** — the planner *guesses* how many rows each step yields; if the
  guess is far from reality, it can pick a bad plan. pgvet's `misestimate_factor` measures
  the gap.
- **`work_mem`** — the memory Postgres allows per sort/hash operation. If a sort needs more,
  it "spills to disk," which is slower — pgvet's `sort_spill` advisor flags that.
- **Introspection** — asking the database about its own structure (tables, columns,
  indexes) via the system catalogs (`information_schema` / `pg_catalog`).
- **Entry point (Python)** — a way a package advertises code (here, a plugin) so another
  program can discover and load it at runtime. pgvet finds advisors this way.
- **TUI** — Text User Interface: a full-screen app that runs inside your terminal (pgvet
  uses the Textual framework).
