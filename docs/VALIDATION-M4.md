# M4 Live Validation Report (Plan Diff + History)

**Validation Date:** 2026-07-29  
**Feature:** Milestone M4 — Plan Diff + History Store  
**Environment:** Live PostgreSQL 16 container on macOS  

---

## 1. System & Environment Information

- **Operating System:** macOS 26.3.1 (Darwin 25.3.0 arm64, Apple Silicon)
- **Client `psql` Version:** `psql (PostgreSQL) 16.13 (Homebrew)`
- **PostgreSQL Server Version:** `PostgreSQL 16.14 (Debian 16.14-1.pgdg13+1)` (running via Docker `postgres:16`)

---

## 2. Test Suite Sanity Check (Step 4)

**Command:** `uv run pytest -q`  
**Output:**
```text
........................................................................ [ 88%]
.........                                                                [100%]
81 passed in 0.62s
```
- **Total Tests Passed:** 81 passed

---

## 3. M4 Live Loop Validation (Steps 5–7)

### 3.1 Run #1 (Initial Query before Index Creation)
- **Database State:** Table `orders` seeded (100,000 rows), index `ix_orders_amount` NOT present.
- **Query Executed:** `SELECT * FROM orders WHERE amount < 5`
- **Plan Tree:** `SEQ_SCAN` on `orders` (1 node)
- **Execution Time:** `15.443 ms`
- **Findings:** 1 finding (`WARN: Seq Scan over large table orders`)
- **Diff Pane Rendered:** No diff / empty (`previous` = `None`, `diff` = `None`) as expected for the initial run.

### 3.2 Index Creation (Step 6)
**Command:** `psql "$DATABASE_URL" -c "CREATE INDEX ix_orders_amount ON orders(amount); ANALYZE orders;"`  
- Index `ix_orders_amount` created successfully and statistics updated via `ANALYZE orders`.

### 3.3 Run #2 (Re-run of EXACT SAME Query after Index Creation)
- **Query Executed:** `SELECT * FROM orders WHERE amount < 5`
- **Plan Tree:** `BITMAP_HEAP_SCAN` on `orders` (with child `BITMAP_INDEX_SCAN` on `ix_orders_amount`)
- **Execution Time:** `1.478 ms` (~10.4x faster)
- **Previous Plan Tree:** `SEQ_SCAN` on `orders`
- **Diff Pane Rendered:** **YES**
- **Verdict:** `STRUCTURE_CHANGED`
- **Before → After Timing:** `15.443 ms` → `1.478 ms`
- **Node Type Transition:** `SEQ_SCAN` → `BITMAP_HEAP_SCAN` (`Seq Scan` → `Bitmap Heap Scan` + `Bitmap Index Scan`)

---

## 4. History Store Persistence Verification (Step 8)

**Command:**
```bash
uv run python -c "import sqlite3; c=sqlite3.connect('.pgvet/history.db'); c.row_factory=sqlite3.Row; rows=c.execute('SELECT query_hash, git_ref, recorded_at, execution_time_ms FROM plan_runs ORDER BY id').fetchall(); [print(dict(r)) for r in rows]"
```

**Output:**
```python
{'query_hash': 'd380ea89e3aa3f7f9ad05678e2cdbe94abd5dd2a6213ccdee295e74d662bbbe9', 'git_ref': '8307e41', 'recorded_at': '2026-07-29T23:43:49.501949+00:00', 'execution_time_ms': 15.443}
{'query_hash': 'd380ea89e3aa3f7f9ad05678e2cdbe94abd5dd2a6213ccdee295e74d662bbbe9', 'git_ref': '8307e41', 'recorded_at': '2026-07-29T23:44:01.637514+00:00', 'execution_time_ms': 1.478}
```

- Both runs were correctly persisted to `.pgvet/history.db`.
- Both rows share the **exact same `query_hash`** (`d380ea89e3aa...`), confirming `sqlglot` query normalization and sha256 hashing.
- Both rows record the `git_ref` (`8307e41`) and execution timings (`15.443 ms` vs `1.478 ms`).

---

## 5. Tracebacks & Risk Assessment (Step 9)

- **Exceptions / Tracebacks:** None (0 errors/tracebacks).
- **Unicode Rendering:** Unicode characters (`→` and `Δ`) in `render_plan_diff` rendered without any `UnicodeEncodeError`.

---

## 6. Summary Checklist

| Requirement | Result |
|---|---|
| M4 Files Present (`plandiff.py`, `history.py`) | YES |
| Test Suite Count | 81 passed |
| Run #1 Diff Empty | YES |
| Run #2 Diff Pane Rendered | YES |
| History Store Persisted 2 Runs with Matching Hash | YES |
| Errors / Tracebacks | None |
