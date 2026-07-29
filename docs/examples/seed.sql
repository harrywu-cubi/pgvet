-- pgvet demo data
-- Creates two tables with enough rows that pgvet's advisors actually fire,
-- so you can see real findings against a live PostgreSQL.
--
-- Load it with (see docs/HANDOFF.md for the full walkthrough):
--   psql "$DATABASE_URL" -f docs/examples/seed.sql

DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS customers;

-- 5,000 customers
CREATE TABLE customers (
    id   integer PRIMARY KEY,
    name text NOT NULL
);
INSERT INTO customers (id, name)
SELECT g, 'customer_' || g
FROM generate_series(1, 5000) AS g;

-- 100,000 orders. status is deliberately NOT indexed so that filtering on it
-- forces a sequential scan (which the seq_scan advisor flags).
CREATE TABLE orders (
    id          integer PRIMARY KEY,
    customer_id integer NOT NULL REFERENCES customers (id),
    status      text    NOT NULL,
    amount      numeric NOT NULL,
    created_at  timestamptz NOT NULL
);
INSERT INTO orders (id, customer_id, status, amount, created_at)
SELECT g,
       1 + (g % 5000),
       (ARRAY['open', 'paid', 'shipped', 'cancelled'])[1 + (g % 4)],
       round((random() * 1000)::numeric, 2),
       now() - (g || ' minutes')::interval
FROM generate_series(1, 100000) AS g;

-- A secondary index on customer_id. Because it exists but a status-filter query
-- won't use it, the unused_index advisor will also fire on such queries.
CREATE INDEX ix_orders_customer_id ON orders (customer_id);

-- Update planner statistics so EXPLAIN estimates are meaningful.
ANALYZE customers;
ANALYZE orders;

-- Try these in `pgvet tui` after loading:
--   SELECT * FROM orders WHERE status = 'open';
--       -> Seq Scan on 100k rows  => seq_scan (WARN) + unused_index (INFO)
--   SELECT o.* FROM orders o JOIN customers c ON c.id = o.customer_id
--    WHERE o.status = 'cancelled';
--       -> join plan; inspect the plan tree + findings
