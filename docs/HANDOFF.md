# pgvet — Run It Locally (beginner handoff)

This guide takes you from "I have nothing" to "pgvet is analyzing real queries on my
own PostgreSQL." No prior knowledge of the project is assumed. It should take about
20–30 minutes. Every command is copy-paste.

> **Prerequisite for the maintainer (not the beginner):** the repo must be pushed to
> GitHub first. Until then `git clone` won't work. Maintainer runs once:
> `git push origin main`. The clone URL below assumes that's done.

---

## 0. What pgvet is (30-second version)

pgvet looks at how PostgreSQL plans to run your query (its "execution plan") and gives
you plain-English advice: missing indexes, bad row estimates, sorts spilling to disk,
etc. You give it a query in a terminal UI; it shows the plan and a list of findings.
It's read-only and runs entirely on your machine.

---

## 1. Install the prerequisites

You need three things. Install whichever you're missing.

**a) Python 3.11 or newer**
- Check: `python --version` (or `python3 --version`). Need ≥ 3.11.
- If missing: https://www.python.org/downloads/ (or your OS package manager).

**b) uv** (the Python package manager pgvet uses — do NOT use pip)
- Install (macOS/Linux): `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Install (Windows PowerShell): `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`
- Check: `uv --version`

**c) A PostgreSQL to point at.** The easiest cross-platform option is Docker; native
installs also work. Pick ONE:

- **Docker (recommended — one command, any OS):**
  ```bash
  docker run --name pgvet-pg -e POSTGRES_PASSWORD=pw -p 5432:5432 -d postgres:16
  ```
  You also want the `psql` client to load sample data. It ships inside the container,
  so you can use `docker exec` (shown later), or install `psql` locally.

- **macOS native:** install [Postgres.app](https://postgresapp.com/) or `brew install postgresql@16 && brew services start postgresql@16`.
- **Windows native:** the [EDB installer](https://www.postgresql.org/download/windows/).
- **Linux native:** `sudo apt install postgresql` (Debian/Ubuntu), then `sudo service postgresql start`.

---

## 2. Get the code

```bash
git clone https://github.com/harrywu-cubi/pgvet.git
cd pgvet
```

## 3. Install pgvet's dependencies

```bash
uv sync --extra dev
```
This creates a `.venv/` and installs everything. From now on you run pgvet with
`uv run pgvet ...` (the `uv run` prefix uses that virtual environment automatically).

## 4. Prove it works WITHOUT a database (30 seconds)

pgvet ships with a saved example plan, so you can see it work before touching Postgres:

```bash
uv run pytest -q                                              # 57 tests should pass
uv run pgvet plugins                                          # lists the 5 built-in advisors
uv run pgvet report --plan-file tests/fixtures/plans/seq_scan.json
```
That last command prints a finding like:
```
WARN: Row estimate off by 950× at customers [customers]
    Planner estimated 1 rows but got 950. Bad estimates lead to bad plans.
```
If you see that, the code is healthy. Now let's point it at a real database.

## 5. Create a database and load sample data

You need a database with enough rows that the advisors have something to flag. The repo
includes `docs/examples/seed.sql` for exactly this.

**If you used Docker:**
```bash
# copy the seed file into the container and run it
docker cp docs/examples/seed.sql pgvet-pg:/seed.sql
docker exec -it pgvet-pg psql -U postgres -d postgres -f /seed.sql
```

**If you used a native install** (adjust user/db as needed):
```bash
createdb pgvetdemo
psql "postgresql://localhost:5432/pgvetdemo" -f docs/examples/seed.sql
```

The script creates `customers` (5k rows) and `orders` (100k rows) and updates
statistics. It prints nothing dramatic — that's fine.

## 6. Tell pgvet where the database is

pgvet reads the standard `DATABASE_URL` environment variable. Your password is never
printed or stored.

**Docker setup:**
```bash
# macOS/Linux
export DATABASE_URL="postgresql://postgres:pw@localhost:5432/postgres"
# Windows PowerShell
$env:DATABASE_URL = "postgresql://postgres:pw@localhost:5432/postgres"
```

**Native setup (example):**
```bash
export DATABASE_URL="postgresql://localhost:5432/pgvetdemo"
```

## 7. Run the interactive workbench

```bash
uv run pgvet tui
```
A full-screen terminal UI opens. In the input box at the top, type a query and press
**Enter**:
```
SELECT * FROM orders WHERE status = 'open'
```
You should see:
- **left pane** — the execution plan as a tree (a `Seq Scan on orders …`), with cost/heat;
- **right pane** — findings, e.g. a **WARN** "Seq Scan over large table `orders`" and an
  **INFO** "Seq Scan despite existing index" (because `orders` has an index on
  `customer_id` that this query doesn't use).

Press **Ctrl+C** to quit.

Try a second query to see a join plan:
```
SELECT o.* FROM orders o JOIN customers c ON c.id = o.customer_id WHERE o.status = 'cancelled'
```

## 8. (Optional) Analyze a saved plan, no DB needed

You can also capture a plan to a file and analyze it offline (handy for CI or sharing):
```bash
psql "$DATABASE_URL" -XAt -c \
  "EXPLAIN (ANALYZE, FORMAT JSON) SELECT * FROM orders WHERE status = 'open'" \
  > /tmp/plan.json

uv run pgvet report --plan-file /tmp/plan.json
uv run pgvet report --plan-file /tmp/plan.json --format json   # machine-readable
```

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `error: DATABASE_URL is not set...` | You didn't set `DATABASE_URL` in this shell (step 6). Env vars don't persist across new terminals — re-export it. |
| `error: ... connection refused` / `could not connect` | Postgres isn't running or the URL is wrong. Docker: `docker start pgvet-pg`. Check host/port/user/password. |
| `pgvet: command not found` | You dropped the `uv run` prefix. Use `uv run pgvet ...`, and make sure you're in the `pgvet/` folder. |
| TUI shows a plan but **no findings** | Your table is too small (the seq-scan advisor needs ≥ 10,000 rows). Use the seeded `orders` table, or a bigger real table. |
| `password authentication failed` | The password in `DATABASE_URL` doesn't match. For the Docker command above it's `pw`. |
| Windows: colors/box characters look odd | Use Windows Terminal (not the legacy console) for the TUI. |

## Cleaning up (Docker)

```bash
docker rm -f pgvet-pg     # stops and removes the demo database container
```

---

## What you just exercised

- `pgvet plugins` → lists the discovered advisor plugins.
- `pgvet report --plan-file` → the **database-free** analysis path (parses a saved plan).
- `pgvet tui` → the **live** path: connects to Postgres, runs `EXPLAIN (ANALYZE, …)`,
  introspects the schema, runs every advisor, and renders the plan + findings.

To understand *how* all of that works internally — enough to explain the design and the
code — read `docs/ARCHITECTURE.md`.
