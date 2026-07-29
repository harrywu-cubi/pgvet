# Real Database Validation Report: pgvet

**Validation Date:** 2026-07-29  
**Environment:** Live PostgreSQL 16 container on macOS  

---

## 1. System & Environment Information

- **Operating System:** macOS 26.3.1 (Darwin 25.3.0 arm64, Apple Silicon)
- **Client `psql` Version:** `psql (PostgreSQL) 16.13 (Homebrew)`
- **PostgreSQL Server Version:** `PostgreSQL 16.14 (Debian 16.14-1.pgdg13+1) on aarch64-unknown-linux-gnu` (running via Docker `postgres:16`)

---

## 2. Offline Sanity Check Outputs (Step 3)

### 2.1 Pytest Suite
**Command:** `uv run pytest -q`  
**Output:**
```text
.........................................................                [100%]
57 passed in 0.53s
```

### 2.2 Plugin Discovery
**Command:** `uv run pgvet plugins`  
**Output:**
```text
Discovered plugins:
  [ADVISOR] advisor.seq_scan — Sequential scan on large relation
  [ADVISOR] advisor.row_estimate — Row-count misestimate
  [ADVISOR] advisor.sort_spill — Sort spilled to disk
  [ADVISOR] advisor.nested_loop — High-iteration nested loop
  [ADVISOR] advisor.unused_index — Seq scan despite existing index
```

### 2.3 Report on Offline Fixture
**Command:** `uv run pgvet report --plan-file tests/fixtures/plans/seq_scan.json`  
**Output:**
```text
WARN: Row estimate off by 950× at customers [customers]
    Planner estimated 1 rows but got 950. Bad estimates lead to bad plans.
```

---

## 3. Real Execution Plan Analysis Outputs (Step 5)

Real PostgreSQL execution plans were captured from the seeded database (`docs/examples/seed.sql`) into:
- `tests/fixtures/plans/real_seq_scan.json`
- `tests/fixtures/plans/real_join.json`

### 3.1 Analysis of Captured `real_seq_scan.json` (JSON Format)
**Command:** `uv run pgvet report --plan-file tests/fixtures/plans/real_seq_scan.json --format json`  
**Output:**
```json
{
  "query": null,
  "findings": [
    {
      "plugin_id": "advisor.seq_scan",
      "severity": "WARN",
      "title": "Seq Scan over large table `orders`",
      "detail": "Sequential scan reads ~25000 rows from `orders`. Consider an index on the filtered columns.",
      "location": {
        "kind": "table",
        "identifier": "orders"
      },
      "evidence": {
        "rows": 25000.0,
        "cost": 2013.0
      },
      "suggestion": {
        "kind": "note",
        "sql": null,
        "note": "Inspect the WHERE/JOIN predicates on `orders` for an index candidate."
      }
    }
  ]
}
```

### 3.2 Analysis of Captured `real_join.json` (Text Format)
**Command:** `uv run pgvet report --plan-file tests/fixtures/plans/real_join.json`  
**Output:**
```text
WARN: Seq Scan over large table `orders` [orders]
    Sequential scan reads ~25000 rows from `orders`. Consider an index on the filtered columns.
```

---

## 4. Live Path & TUI Workbench Test (Step 6)

- **Connected to Database:** Yes
- **Rendered Plan Tree:** Yes
- **Rendered Findings:** Yes
- **Traceback / Errors:** None

**Test Procedure:**
`uv run pgvet tui` was executed with `DATABASE_URL` set to the live seeded database. The query `SELECT * FROM orders WHERE status='open'` was submitted to the input box.

**Rendered Results:**
- **Left Pane (Plan Tree):** Rendered `Seq Scan` on `orders` with startup cost, total cost, estimated rows (24,763), actual rows (25,000), actual time, and filter details.
- **Right Pane (Findings):** Rendered 2 findings:
  1. `WARN: Seq Scan over large table orders`
  2. `INFO: Seq Scan on orders despite existing index`

---

## 5. Review & Feedback on `docs/HANDOFF.md`

`docs/HANDOFF.md` is well-structured, clear, and easy to follow.

**Observations / Suggestions for Improvement:**
1. **Host `psql` dependency note:** Section 1.c recommends Docker and mentions `docker exec` for running `psql`. However, Section 8 (and standard plan capture scripts) executes `psql "$DATABASE_URL" ...` directly on the host machine. On macOS, host `psql` might not be installed by default or might need to be added to `PATH` (e.g. `export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"` after `brew install postgresql@16`). A small note under Step 1.c or Step 8 reminding users to have `psql` available in their host `PATH` when using host-level `psql "$DATABASE_URL"` commands would be helpful.
2. Everything else worked smoothly as documented.
