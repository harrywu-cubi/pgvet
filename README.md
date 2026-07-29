# pgvet

A pluggable, local-only PostgreSQL doctor. Point it at your local/dev database
(`DATABASE_URL`) and get plan-based advice on your queries.

## Install (dev)

    uv sync --extra dev

## Use

    export DATABASE_URL=postgresql://user@localhost:5432/dev
    uv run pgvet tui                                  # interactive workbench
    uv run pgvet report --plan-file plan.json         # analyze a saved EXPLAIN JSON (no DB)
    uv run pgvet plugins                              # list installed advisors

## Design

See `docs/superpowers/specs/2026-07-29-pgvet-platform-design.md` and the MVP plan
in `docs/superpowers/plans/`.

## Extending

Advisors are plugins. Ship one from your own package via the `pgvet.advisors`
entry-point group; it's discovered automatically. Each advisor is a pure function
over a `PlanContext` that yields `Finding`s.
