-- 00_load_raw.sql
-- Loads the four raw CSVs from ./data with explicit, deliberate types.
-- Dates stay as raw INTEGER here (YYYYMMDD) on purpose: invalid/odd values must
-- survive the load so the data-quality step (01) can measure them. Typing to DATE
-- happens in the clean layer.
-- Run from the repo root:  duckdb tune.duckdb < sql/00_load_raw.sql

CREATE OR REPLACE TABLE raw_users AS
SELECT * FROM read_csv('data/users.csv', header = true, columns = {
  'user_id': 'VARCHAR', 'city': 'INTEGER', 'age': 'INTEGER', 'gender': 'VARCHAR',
  'acquisition_channel': 'INTEGER', 'registered_at': 'INTEGER'});

-- Both transaction exports go into ONE table with lineage columns, so overlap and
-- conflict rules are explicit and auditable (src_file, src_row).
CREATE OR REPLACE TABLE raw_transactions AS
SELECT * EXCLUDE (filename),
       regexp_extract(filename, 'export_(\d)', 1)::TINYINT AS src_file,
       row_number() OVER () AS src_row
FROM read_csv('data/transactions_export_*.csv', header = true, filename = true, columns = {
  'user_id': 'VARCHAR', 'payment_method': 'INTEGER', 'payment_plan_days': 'INTEGER',
  'list_price': 'INTEGER', 'amount_paid': 'INTEGER', 'is_auto_renew': 'TINYINT',
  'transacted_at': 'INTEGER', 'expires_at': 'INTEGER', 'is_cancel': 'TINYINT'});

CREATE OR REPLACE TABLE raw_churn_labels AS
SELECT * FROM read_csv('data/churn_labels.csv', header = true, columns = {
  'user_id': 'VARCHAR', 'is_churn': 'TINYINT'});

-- Load audit: row counts must match BRIEF.md
SELECT 'users' tbl, count(*) n FROM raw_users
UNION ALL SELECT 'transactions_export_' || src_file, count(*) FROM raw_transactions GROUP BY src_file
UNION ALL SELECT 'churn_labels', count(*) FROM raw_churn_labels
ORDER BY 1;
