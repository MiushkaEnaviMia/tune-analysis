-- 00_load_raw.sql
-- RAW layer: the four CSV files loaded exactly as delivered. One table per file, same columns,
-- same rows, same order. Nothing is added, combined or fixed here, so every raw table can be
-- compared 1:1 with its file.
-- Types are explicit and deliberate. Dates stay as raw INTEGER (YYYYMMDD) on purpose: invalid or
-- odd values (e.g. 19700101) must survive the load so the data-quality step (01) can measure them.
-- Combining the two transaction exports is the next step (00_union_exports.sql -> base_transactions).
-- Run from the repo root:  duckdb tune.duckdb < sql/00_load_raw.sql

CREATE OR REPLACE TABLE raw_users AS
SELECT * FROM read_csv('data/users.csv', header = true, columns = {
  'user_id': 'VARCHAR', 'city': 'INTEGER', 'age': 'INTEGER', 'gender': 'VARCHAR',
  'acquisition_channel': 'INTEGER', 'registered_at': 'INTEGER'});

CREATE OR REPLACE TABLE raw_transactions_export_1 AS
SELECT * FROM read_csv('data/transactions_export_1.csv', header = true, columns = {
  'user_id': 'VARCHAR', 'payment_method': 'INTEGER', 'payment_plan_days': 'INTEGER',
  'list_price': 'INTEGER', 'amount_paid': 'INTEGER', 'is_auto_renew': 'TINYINT',
  'transacted_at': 'INTEGER', 'expires_at': 'INTEGER', 'is_cancel': 'TINYINT'});

CREATE OR REPLACE TABLE raw_transactions_export_2 AS
SELECT * FROM read_csv('data/transactions_export_2.csv', header = true, columns = {
  'user_id': 'VARCHAR', 'payment_method': 'INTEGER', 'payment_plan_days': 'INTEGER',
  'list_price': 'INTEGER', 'amount_paid': 'INTEGER', 'is_auto_renew': 'TINYINT',
  'transacted_at': 'INTEGER', 'expires_at': 'INTEGER', 'is_cancel': 'TINYINT'});

CREATE OR REPLACE TABLE raw_churn_labels AS
SELECT * FROM read_csv('data/churn_labels.csv', header = true, columns = {
  'user_id': 'VARCHAR', 'is_churn': 'TINYINT'});

-- Load audit: row counts must match BRIEF.md
SELECT 'users' tbl, count(*) n FROM raw_users
UNION ALL SELECT 'transactions_export_1', count(*) FROM raw_transactions_export_1
UNION ALL SELECT 'transactions_export_2', count(*) FROM raw_transactions_export_2
UNION ALL SELECT 'churn_labels', count(*) FROM raw_churn_labels
ORDER BY 1;
