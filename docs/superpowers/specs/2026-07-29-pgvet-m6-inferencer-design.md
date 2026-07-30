# pgvet M6 (part 1) — Constraint-Inference Family Design Spec

*The first of M6's two families. Status: **design / not yet implemented**. Date: 2026-07-29.*

> **Scope note.** "M6" originally bundled two independent subsystems: the **inferencer
> family** (this spec) and the **drift family** (ORM↔DB — its own future spec). They share
> only the schema-introspection layer and the plugin host, so they are separate
> spec → plan → build cycles. This document covers the inferencer family only.

---

## 1. Summary

The inferencer family teaches pgvet to **infer constraints the data already obeys but the
schema never declared** — undeclared foreign keys, columns that are effectively unique,
low-cardinality text columns that are really enums, and "nullable but never null" columns —
and to emit the reviewable DDL that would declare them. It is a *start-of-an-area* tool:
run it when you inherit or enter a schema, review the candidate constraints, apply the ones
that make sense.

It reuses pgvet's existing plugin host: a new `Inferencer` plugin type (family
`INFERENCER`, already reserved in the `Family` enum) operating over a `SchemaContext`.

### Goals
- Infer the **Core 4**: not-null, single-column unique, low-cardinality enum, and
  foreign-key-by-value-overlap.
- Emit **reviewable `ALTER TABLE … ADD CONSTRAINT` DDL** with evidence and a confidence
  signal. Human applies it; pgvet never does.
- Stay **local-only and read-mostly**, and keep the whole test suite **DB-free** (fake
  Sampler + fixtures), consistent with the rest of pgvet.
- Add capability as **plugins on the unchanged core** — proving the extensibility thesis a
  third time (advisors → inferencers).

### Non-goals (deferred)
- Composite-unique, CHECK/range, and functional-dependency inference.
- Emitting migration files (Alembic/Django) — first cut prints DDL only.
- A TUI panel for inferences (CLI-first).
- The **drift family** (separate spec).
- Auto-applying any DDL. Ever. pgvet is read-mostly.

---

## 2. Where it plugs into the existing system

pgvet already has (on `main`, MVP + M4 + M5):
- `Family` enum with `ADVISOR | INFERENCER | DRIFT` (INFERENCER reserved, unused).
- `SchemaModel` (`Table/Column/Index/Constraint`) — but `introspect` currently populates
  only columns + indexes, **not** constraints/FKs.
- `Registry` with builtin registration + entry-point discovery, and a `Finding`/`Severity`/
  `Suggestion` output model.
- `Connection` (thin psycopg wrapper: `fetch_all`/`fetch_one`), `Session`, and a
  report-style CLI renderer.

M6-part-1 adds a parallel path alongside advisors, touching the core only additively.

---

## 3. Architecture

```
      pgvet infer  (CLI)
            │
            ▼
      ┌───────────┐
      │  Session  │   .infer()  → build SchemaContext, run inferencers, collect Findings
      └─────┬─────┘
      ┌─────┴───────────────┬───────────────────┐
      ▼                     ▼                    ▼
┌───────────┐        ┌───────────┐        ┌───────────┐
│ Registry  │        │ introspect│        │  Sampler  │  (core/sampler.py)
│(inferencers)│      │(+FKs/     │        │ data-stat │  the ONLY inference SQL
└─────┬─────┘        │ constraints)│      │ methods   │
      │              └─────┬─────┘        └─────┬─────┘
      ▼                    ▼                    ▼
┌───────────┐        ┌───────────┐        ┌───────────┐
│Inferencer │─reads─▶│SchemaModel│        │Connection │
│ plugins   │  +uses─────────────────────▶│ (psycopg) │
└───────────┘        └───────────┘        └───────────┘
```

**Dependency direction (unchanged golden rule).** Inferencer plugins depend only on the
pure model (`SchemaModel`, `Finding`) + the `Sampler` *interface*. All inference SQL lives
in `Sampler`. The engine/CLI wire it to a live connection. Nothing above `Sampler`/`Connection`
imports psycopg.

**Key difference from advisors.** Advisors are pure functions over in-memory plan data.
Inferencers need to *ask the database questions* (aggregates over data), so their context
carries a `Sampler` (a live-query capability) in addition to the `SchemaModel`. They remain
testable because the `Sampler` is injected — tests pass a **fake Sampler** returning canned
stats.

---

## 4. Components (each a focused unit)

| Module | Responsibility | Depends on | Tested via |
|---|---|---|---|
| `plugins/base.py` (extend) | Add `Inferencer(ABC)` + `SchemaContext(schema, sampler)` | findings, schemamodel, sampler type | pure unit |
| `core/introspect.py` (extend) | Add FK + constraint capture → populate `Constraint` on tables | connection, schemamodel | fake-conn fixture rows |
| `core/sampler.py` (new) | Data-stat methods + hybrid full-scan/sample logic; owns all inference SQL | connection | fake connection |
| `plugins/inferencers/__init__.py` (new) | `register_builtins` for the inferencer family | the 4 inferencers | registry test |
| `plugins/inferencers/not_null.py` etc. (new) | The Core-4 inferencers | findings, schemamodel, sampler iface | fake Sampler |
| `core/registry.py` (extend) | Add `inferencers` list + `INFERENCER_GROUP` discovery + builtin load | plugins.base | fake entry points |
| `core/session.py` (extend) | `Session.infer() -> list[Finding]` (pure over ctx, isolation like `analyze`) | introspect, sampler, registry | fake sampler/schema |
| `cli.py` (extend) | `pgvet infer` subcommand (text/json), reuses report renderer | session, connection | pure `infer()` path |

---

## 5. The `Sampler` interface (the crux)

`Sampler` wraps a `Connection` and is the single home of inference SQL. Every method returns
a small immutable `Stat`:

```python
@dataclass(frozen=True)
class Stat:
    value: float | int          # the answer (a count, ratio, etc.)
    sampled: bool               # True if computed from a sample, not the full table
    sample_size: int            # rows considered (== row_count when not sampled)
```

Methods (first cut):
- `row_count(table) -> Stat`
- `null_count(table, column) -> Stat` — for not-null inference
- `distinct_count(table, column) -> Stat` — for unique inference
- `distinct_values(table, column, limit) -> list[str]` — for enum inference (values for the
  CHECK list; returns at most `limit`, so an over-cardinality column returns `limit` items
  and is rejected as an enum)
- `orphan_ratio(child_table, child_col, parent_table, parent_col) -> Stat` — fraction of
  child values with no matching parent value (≈ 0 ⇒ candidate FK)

**Hybrid sampling rule.** `Sampler` holds a `full_scan_threshold` (default 100_000). For a
table under it, methods scan the whole table (`sampled=False`). At/above it, methods run
against a bounded sample (`TABLESAMPLE SYSTEM (…)` or an `ORDER BY … LIMIT`-bounded subquery)
and set `sampled=True`, `sample_size` = rows sampled. A per-`(table)` `row_count` cache
avoids recomputing size for every column.

**Confidence model (deliberately simple for the first cut).** If a check passes on a *full*
scan, confidence is "certain" (the data provably obeys it *now* — the finding still says
"the DB doesn't enforce it, so future writes could violate it"). If it passes on a *sample*,
the finding is phrased "candidate — verify" and `evidence` carries `sampled=True` +
`sample_size`. No p-value math in the first cut; sampled findings are advisory.

---

## 6. The Core-4 inferencers

Each is an `Inferencer` that reads `ctx.schema` + calls `ctx.sampler`, **skips constraints
that already exist** (using the now-populated `Constraint`s), and yields a `Finding` whose
`Suggestion.sql` is the candidate DDL. Severity `SUGGEST` (full-scan) or `INFO` (sampled).

| Inferencer | Fires when | Candidate DDL |
|---|---|---|
| `not_null` | column is `nullable` and `null_count == 0` | `ALTER TABLE t ALTER COLUMN c SET NOT NULL` |
| `unique` | no unique index/constraint on `c` and `distinct_count == row_count` (and row_count > 0) | `ALTER TABLE t ADD CONSTRAINT t_c_key UNIQUE (c)` |
| `enum` | text column, `distinct_count ≤ ENUM_MAX` (default 12), row_count ≫ distinct | `ALTER TABLE t ADD CONSTRAINT t_c_check CHECK (c IN ('…', …))` |
| `fk_overlap` | column looks referential (name ends `_id` or matches a PK column name), not already an FK, and `orphan_ratio ≈ 0` (≤ `ORPHAN_TOLERANCE`, default 0.0 for full scan) against a table whose PK it overlaps | `ALTER TABLE child ADD CONSTRAINT child_c_fkey FOREIGN KEY (c) REFERENCES parent(pk)` |

`fk_overlap` candidate-parent selection (first cut, kept cheap): for a referential-looking
column `orders.customer_id`, look for a table whose name (singular/plural of the prefix,
e.g. `customer`/`customers`) has a single-column PK; test overlap against that. If no naming
match, skip (don't brute-force all table pairs in the first cut — that's the expensive path
deferred with composite inference).

Each finding's `evidence` includes the raw stat(s), `sampled`, and `sample_size` so the user
can judge it.

---

## 7. Engine + CLI

```python
# Session (additive)
def infer(self) -> list[Finding]:
    schema = introspect(self._conn)              # now includes constraints/FKs
    ctx = SchemaContext(schema=schema, sampler=Sampler(self._conn))
    findings = []
    for inf in self._registry.inferencers:       # same try/except isolation as analyze()
        try:
            findings.extend(inf.run(ctx))
        except Exception as exc:
            findings.append(Finding(inf.id, Severity.WARN, f"Inferencer {inf.id} failed", str(exc)))
    return findings
```

`pgvet infer` connects (`DATABASE_URL`), calls `Session.infer()`, and prints the findings —
reusing the existing `_render_text`/`_finding_dict` renderers (`--format text|json`). Because
each `Suggestion.sql` carries the DDL, `--format json` gives a machine-readable list of
candidate constraints for scripting.

Unlike `pgvet report` (which can run DB-free on a plan file), `pgvet infer` inherently needs
a live DB — but its *engine* (`Session.infer` running inferencers over an injected
`SchemaContext`) is fully testable offline with a fake Sampler.

---

## 8. Safety & workstation boundary

- **Read-mostly.** `Sampler` issues only `SELECT`/aggregate queries (and `TABLESAMPLE`). The
  session stays `default_transaction_read_only = on`. pgvet **never** runs the suggested
  `ALTER TABLE` — it prints it; applying it is the developer's reviewed action.
- **Local/dev only**, `DATABASE_URL` from env, password redacted — unchanged from the rest
  of pgvet. No external service, no credential boundary crossed.
- **Bounded work.** The hybrid threshold caps scan cost; sampled results are labelled so a
  user never mistakes a sampled "candidate" for a proven invariant.

---

## 9. Testing strategy

Three tiers, weighted to the fast one — identical philosophy to the MVP:
1. **Pure inferencer unit tests (no DB):** construct a `SchemaModel` + a **fake Sampler**
   returning canned `Stat`s, assert the `Finding` + candidate DDL. Bulk of the suite.
2. **Sampler tests against a fake connection:** assert each method builds the right SQL and
   maps rows → `Stat`, including the full-scan vs sampled branch at the threshold. Recorded
   catalog/aggregate rows, no live DB.
3. **Introspection-extension tests:** fake-connection rows for the FK/constraint catalog
   query → assert `Constraint`s populate `SchemaModel`.
4. **Opt-in live integration (deferred, not in CI):** real `TABLESAMPLE`, real orphan-ratio
   on the seeded demo DB — validated on the DB machine, mirroring how MVP/M4 were validated.

TDD throughout.

---

## 10. Scope ladder (what the plan will sequence)

- **Prereq:** extend `introspect` to capture PK/FK/unique/check constraints into
  `SchemaModel`.
- **S1:** `Stat` + `Sampler` (row_count/null_count/distinct_count/distinct_values, hybrid +
  cache) against a fake connection.
- **S2:** `Inferencer` base + `SchemaContext`; registry `inferencers` group + builtin load.
- **S3:** the Core-4 inferencers (not_null, unique, enum, fk_overlap) as fake-Sampler-tested
  plugins; `orphan_ratio` added to the Sampler for fk_overlap.
- **S4:** `Session.infer()` + `pgvet infer` CLI (text/json), reusing the report renderer.

MVP line = the above. Deferred (future cuts / drift spec): composite-unique, CHECK/range,
functional deps, migration-file emission, TUI panel, and the entire drift family.

---

## 11. Open questions / risks

1. **`orphan_ratio` cost.** Even with naming-based parent selection it's a join/anti-join
   per candidate column; the hybrid threshold + sampling bound it, but very wide schemas may
   still be slow. First cut only tests naming-matched candidates (no all-pairs brute force).
2. **Sampling faithfulness.** `TABLESAMPLE SYSTEM` samples pages, not rows — fine for
   ballpark stats but can miss rare violations (e.g. a single null in a huge table). Hence
   sampled findings are explicitly "candidate — verify", never asserted as certain.
3. **Enum false positives.** A low-cardinality column today may accept new values tomorrow;
   the CHECK suggestion is advisory and the finding says so.
4. **`TABLESAMPLE` availability / row-vs-page semantics** need confirming on a live PG during
   the deferred integration pass (like the read-only/HypoPG check in M5).
5. **Cross-ORM schema IR** and ORM adapters are **not** in scope here — they belong to the
   drift family spec.
