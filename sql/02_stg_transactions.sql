-- 02_stg_transactions.sql
-- Part 1b, step 1: the cleaned EVENT layer.
-- Input : base_transactions (both exports, with src_file / src_row lineage; see 00_union_exports.sql)
-- Output: ref_price_plan   price -> plan-length lookup learned from rows that DO carry plan metadata
--         stg_transactions one row per real billing event (dedup + conflict-resolved), typed DATEs,
--                          cleaned values, and one flag per rule applied
-- Grain : one billing event. Key = src_row (lineage back to the raw file). NOT (user_id, transacted_at):
--         that pair is not unique (T8) because several real events can share a user and a day.
-- Issue codes (T*, U*, L*) refer to reports/01_data_quality.md and sql/01_data_quality.sql.

-- ---------------------------------------------------------------------------
-- 0. Price -> plan lookup (used for T9 imputation)
-- ---------------------------------------------------------------------------
-- Learned from non-cancel paid rows that carry a plan length. A price is only used as
-- evidence if one plan length accounts for >= 90% of its rows (149 -> 30 days 94%,
-- 1788 -> 410 days 98%, 894 -> 195 days 99%, 129/119/150 -> 30 days 100%).
CREATE OR REPLACE TABLE ref_price_plan AS
WITH k AS (
  SELECT amount_paid, payment_plan_days, count(*) AS n
  FROM base_transactions
  WHERE payment_plan_days > 0 AND amount_paid > 0 AND is_cancel = 0
  GROUP BY 1, 2)
SELECT amount_paid,
       arg_max(payment_plan_days, [n, -payment_plan_days]) AS plan_days,   -- deterministic on ties
       max(n) / sum(n)                                     AS plan_share,
       sum(n)::BIGINT                                      AS n_rows
FROM k GROUP BY 1
HAVING max(n) / sum(n) >= 0.9;

-- ---------------------------------------------------------------------------
-- 1. Staged events
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE stg_transactions AS
WITH
raw AS (
  SELECT r.*,
         -- T7: exact copies of a whole row inside one export. Keep the lowest src_row.
         row_number() OVER (PARTITION BY user_id, payment_method, payment_plan_days, list_price, amount_paid,
                                         is_auto_renew, transacted_at, expires_at, is_cancel, src_file
                            ORDER BY src_row) AS dup_rank,
         -- "Event core" (same definition as 1a): rows sharing it in one file are either the same
         -- event or a stack of prepaid passes (T24). Counted on the raw rows, as in 1a.
         count(*) OVER (PARTITION BY user_id, transacted_at, payment_method, payment_plan_days,
                                     amount_paid, is_cancel, src_file) AS n_core,
         count(DISTINCT expires_at) OVER (PARTITION BY user_id, transacted_at, payment_method, payment_plan_days,
                                                        amount_paid, is_cancel, src_file) AS n_core_exp
  FROM base_transactions r),

-- T4: the same event in both exports (one-to-one match on the event core; stacks excluded,
-- because they match many-to-many). export_2 is the later snapshot, so it wins; the
-- export_1 expiry is kept as expires_at_asof_feb for the Part 1c label logic.
x_pairs AS (
  SELECT a.src_row AS row_e1, b.src_row AS row_e2, a.expires_at AS exp_e1
  FROM raw a JOIN raw b
    ON a.src_file = 1 AND b.src_file = 2
   AND a.user_id = b.user_id AND a.transacted_at = b.transacted_at
   AND a.payment_method = b.payment_method AND a.payment_plan_days = b.payment_plan_days
   AND a.amount_paid = b.amount_paid AND a.is_cancel = b.is_cancel
  WHERE a.n_core = 1 AND b.n_core = 1),

kept AS (
  SELECT r.*, x.exp_e1,
         (x.row_e2 IS NOT NULL)::TINYINT AS is_conflict_resolved
  FROM raw r
  LEFT JOIN x_pairs x ON x.row_e2 = r.src_row
  WHERE r.dup_rank = 1                                              -- T7
    AND r.src_row NOT IN (SELECT row_e1 FROM x_pairs)),             -- T4 (export_1 side dropped)

typed AS (
  SELECT k.*,
         strptime(transacted_at::VARCHAR, '%Y%m%d')::DATE AS transacted_date,
         CASE WHEN expires_at <> 19700101 THEN strptime(expires_at::VARCHAR, '%Y%m%d')::DATE END AS expires_date_raw,  -- T17 -> NULL
         -- T9: plan days and list price both 0 on a paid row (Mar-Oct 2015 logging gap)
         (payment_plan_days = 0 AND list_price = 0 AND amount_paid > 0) AS is_t9
  FROM kept k),

plan AS (
  SELECT t.*,
         date_diff('day', transacted_date, expires_date_raw) AS raw_span_days,
         p.plan_days AS lookup_plan_days
  FROM typed t LEFT JOIN ref_price_plan p USING (amount_paid)),

clean AS (
  SELECT p.*,
         -- T9 plan-days imputation. 1a chose "dates first, price lookup as fallback". Refined in 1b:
         -- expires_at is the MEMBERSHIP expiry, so an early renewal carries the old remaining days and
         -- the date span overstates the plan (149-paid rows spanning ~400 days). Price lookup is therefore
         -- primary; the snapped date span is the fallback for prices without a dominant plan.
         CASE
           WHEN NOT is_t9 THEN payment_plan_days
           WHEN lookup_plan_days IS NOT NULL THEN lookup_plan_days
           WHEN raw_span_days > 0 THEN
             CASE WHEN raw_span_days <= 10 THEN 7   WHEN raw_span_days <= 60  THEN 30
                  WHEN raw_span_days <= 120 THEN 90 WHEN raw_span_days <= 240 THEN 180
                  ELSE 410 END
         END AS plan_days_clean,
         CASE WHEN is_t9 THEN amount_paid ELSE list_price END AS lp_clean,   -- T9: list = paid, discount 0
         CASE WHEN NOT is_t9 THEN NULL
              WHEN lookup_plan_days IS NOT NULL THEN 'price_lookup'
              WHEN raw_span_days > 0 THEN 'date_span_snapped'
              ELSE 'unresolved' END AS plan_imputation_method
  FROM plan p)

SELECT
  -- identity and lineage
  src_row                                    AS event_id,
  user_id,
  src_file,
  src_row,
  -- deterministic per-user order. Same-day rule (T8): cancel first, then purchases, then by
  -- expiry ascending, then src_row. So the "last event of the day" is the purchase with the
  -- latest expiry, i.e. the state billing ends the day in. Without the full key, same-day ties
  -- were broken arbitrarily and a churn count moved between runs (28,506 vs 28,322).
  row_number() OVER (PARTITION BY user_id
                     ORDER BY transacted_date, is_cancel DESC, expires_at, src_row) AS event_seq,
  -- dates
  transacted_date,
  -- Cleaned expiry: cancels keep their own expiry (T15: documented, a cancel can move expiry
  -- earlier); a cancel with the 1970 placeholder ends on its own date. Non-cancel rows with
  -- a missing (T17) or before-the-purchase (T16, incl. the T18 non-cancel rows) expiry get
  -- transacted_date + plan days. Far-future expiries (T19) are kept and flagged.
  CASE
    WHEN is_cancel = 1 THEN coalesce(expires_date_raw, transacted_date)
    WHEN expires_date_raw IS NULL OR expires_date_raw < transacted_date
      THEN transacted_date + coalesce(plan_days_clean, 0)::INTEGER
    ELSE expires_date_raw
  END                                        AS expires_date,
  expires_date_raw,
  CASE WHEN is_conflict_resolved = 1 AND exp_e1 <> 19700101
       THEN strptime(exp_e1::VARCHAR, '%Y%m%d')::DATE
       ELSE expires_date_raw END             AS expires_at_asof_feb,   -- T4: export_1 version where superseded
  -- plan and money
  payment_method,
  payment_plan_days                          AS plan_days_raw,
  plan_days_clean,
  lp_clean                                   AS list_price_clean,
  list_price                                 AS list_price_raw,
  amount_paid,
  greatest(lp_clean - amount_paid, 0)        AS discount_amount,          -- T10: floored at 0
  CASE WHEN lp_clean > 0 THEN round(greatest(lp_clean - amount_paid, 0) / lp_clean, 4) END AS discount_pct,
  is_auto_renew,
  is_cancel,
  -- classification
  (is_cancel = 0 AND amount_paid = 0)::TINYINT                           AS is_free,
  CASE WHEN is_cancel = 1 THEN NULL
       WHEN amount_paid = 0 AND list_price > 0 THEN 'free_trial_discount'  -- T11
       WHEN amount_paid = 0 THEN 'free_unpriced'                           -- T12
       ELSE 'paid' END                                                     AS price_type,
  (is_cancel = 0 AND coalesce(plan_days_clean, 0) > 0)::TINYINT          AS is_purchase,  -- creates a subscription period
  -- rule flags (1 = rule applied / condition present)
  is_t9::TINYINT                                                         AS flag_imputed_plan,          -- T9
  plan_imputation_method,
  is_conflict_resolved                                                   AS flag_conflict_resolved,     -- T4
  (n_core > 1 AND n_core_exp > 1)::TINYINT                               AS flag_stacked,               -- T24
  (count(*) OVER (PARTITION BY user_id, transacted_date) > 1)::TINYINT   AS flag_same_day_multi,        -- T8 (after dedup)
  (count(DISTINCT src_file) OVER (PARTITION BY user_id, transacted_date) = 2)::TINYINT AS flag_same_day_both_exports, -- T6
  (payment_plan_days = 0 AND NOT is_t9)::TINYINT                         AS flag_zero_plan_days,        -- T13
  (list_price > 0 AND amount_paid > list_price)::TINYINT                 AS flag_paid_above_list,       -- T10
  (expires_at = 19700101)::TINYINT                                       AS flag_expiry_epoch,          -- T17
  coalesce(is_cancel = 0 AND expires_date_raw < transacted_date, FALSE)::TINYINT AS flag_expiry_before_tx,      -- T16 (+T18 non-cancel)
  coalesce(is_cancel = 1 AND expires_date_raw < transacted_date, FALSE)::TINYINT AS flag_cancel_moves_expiry,   -- T15 (valid)
  (expires_at > 20190331)::TINYINT                                       AS flag_expiry_far_future,     -- T19 (kept)
  (expires_at = 20170331)::TINYINT                                       AS flag_expiry_month_end_0331  -- T20 (info, not a cap)
FROM clean;

-- ---------------------------------------------------------------------------
-- 2. Validation
-- ---------------------------------------------------------------------------
-- Expect: rows = raw - 832 (T7) - 747 (T4); event_id and (user_id, event_seq) unique;
-- no NULL dates; no non-cancel expiry before its transaction; every T9 row has a plan.
SELECT
  (SELECT count(*) FROM base_transactions)                                       AS raw_rows,
  count(*)                                                                      AS stg_rows,
  (SELECT count(*) FROM base_transactions) - count(*)                            AS rows_removed,
  count(*) - count(DISTINCT event_id)                                           AS dup_event_id,
  count(*) - count(DISTINCT (user_id, event_seq))                               AS dup_user_seq,
  count(*) FILTER (WHERE transacted_date IS NULL OR expires_date IS NULL)       AS null_dates,
  count(*) FILTER (WHERE is_cancel = 0 AND expires_date < transacted_date)      AS noncancel_exp_before_tx,
  count(*) FILTER (WHERE flag_imputed_plan = 1 AND plan_days_clean IS NULL)     AS t9_unresolved,
  sum(flag_imputed_plan)                                                        AS t9_imputed,
  sum(flag_conflict_resolved)                                                   AS t4_resolved,
  sum(flag_stacked)                                                             AS t24_stacked,
  sum(is_purchase)                                                              AS purchases
FROM stg_transactions;
