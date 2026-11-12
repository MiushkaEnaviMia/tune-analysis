-- 00_union_exports.sql
-- BASE step (between RAW and STAGING): combine the two transaction exports into one table.
-- Input : raw_transactions_export_1, raw_transactions_export_2 (untouched copies of the files)
-- Output: base_transactions  one row per row of either export, values unchanged, plus 2 lineage columns
--
-- Why a separate step. The raw tables stay identical to the files, so anyone can check them 1:1.
-- Combining files and adding columns is already a modelling choice, so it lives in its own step.
-- Why combine at all. The exports are split on expiry date, not on purchase date (T1-T3): 89,728 older
-- purchases exist only in export_2. Neither file alone is complete, and the overlap / conflict rules
-- (T4, T7) need both files side by side.
-- Lineage columns (nothing else is changed, no row is removed):
--   src_file  1 or 2: which export the row came from
--   src_row   the row's position: 1..N1 for export_1 in file order, then N1+1.. for export_2.
--             A stable ID that traces every row back to its file and line; used as the event key
--             and as the last tie-break in stg_transactions.
-- Cleaning, deduplication and conflict resolution happen in the next layer (02_stg_transactions.sql).

CREATE OR REPLACE TABLE base_transactions AS
SELECT *, 1::TINYINT AS src_file, rowid + 1 AS src_row
FROM raw_transactions_export_1
UNION ALL
SELECT *, 2::TINYINT AS src_file, rowid + 1 + (SELECT count(*) FROM raw_transactions_export_1) AS src_row
FROM raw_transactions_export_2;

-- Validation: every raw row is here exactly once; src_row is unique and gap-free.
SELECT
  (SELECT count(*) FROM raw_transactions_export_1) + (SELECT count(*) FROM raw_transactions_export_2) AS raw_rows,
  count(*)                                   AS base_rows,
  count(*) - count(DISTINCT src_row)         AS dup_src_row,
  max(src_row) - count(*)                    AS src_row_gaps
FROM base_transactions;
