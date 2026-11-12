-- 01_data_quality.sql
-- Part 1a: reproducible data-quality profiling of the four raw files.
-- Input : raw_users, raw_transactions (both exports, with src_file / src_row lineage), raw_churn_labels
-- Output: dq_summary          one row per check: rows, users, % of table  (feeds reports/01_data_quality.md)
--         dq_examples_*       real example rows per issue
--         reports/01_dq_examples_*.csv  (paste-ready for Google Sheets)
-- Rules: read-only on raw tables; every number in the report comes from dq_summary.

-- ---------------------------------------------------------------------------
-- 0. Helper views
-- ---------------------------------------------------------------------------
-- Transactions without the load-time `filename` helper column.
CREATE OR REPLACE VIEW t AS
SELECT user_id, payment_method, payment_plan_days, list_price, amount_paid, is_auto_renew,
       transacted_at, expires_at, is_cancel, src_file, src_row
FROM raw_transactions;

-- "Core" event = user, day, method, plan, amount, cancel flag. n_core = how many rows share that core in one file.
-- n_core > 1 with different expiries = "stacked" passes (issue T24), not versions of one event.
CREATE OR REPLACE VIEW t_core AS
SELECT *, count(*) OVER (PARTITION BY user_id, transacted_at, payment_method, payment_plan_days,
                                      amount_paid, is_cancel, src_file) AS n_core
FROM t;

-- All cross-export core matches (can be many-to-many when passes are stacked).
CREATE OR REPLACE VIEW x_core_match AS
SELECT a.user_id, a.transacted_at, a.src_row AS row_e1, b.src_row AS row_e2,
       a.n_core AS n_e1, b.n_core AS n_e2,
       a.expires_at AS exp_e1, b.expires_at AS exp_e2,
       a.is_auto_renew AS ar_e1, b.is_auto_renew AS ar_e2,
       a.list_price AS lp_e1, b.list_price AS lp_e2
FROM t_core a JOIN t_core b
  ON a.src_file = 1 AND b.src_file = 2
 AND a.user_id = b.user_id AND a.transacted_at = b.transacted_at
 AND a.payment_method = b.payment_method AND a.payment_plan_days = b.payment_plan_days
 AND a.amount_paid = b.amount_paid AND a.is_cancel = b.is_cancel;

-- Cross-export pairs = one-to-one core matches only. If any other field differs it is a
-- conflicting version of ONE event (T4).
CREATE OR REPLACE VIEW x_pairs AS
SELECT * FROM x_core_match WHERE n_e1 = 1 AND n_e2 = 1;

-- (user_id, transacted_at) keys present in both files with NO core match = different events
-- (typically a cancel/trial in one file and a new purchase in the other): complementary, not duplicates.
CREATE OR REPLACE VIEW x_keys_complementary AS
SELECT user_id, transacted_at
FROM t GROUP BY ALL HAVING count(DISTINCT src_file) = 2
EXCEPT
SELECT user_id, transacted_at FROM x_core_match;

-- Naive "due in March 2017" population: expiry of each user's last transaction up to 2017-02-28
-- (same-day tie: non-cancel wins, then latest expiry; deterministic). Rough coverage check only; the real rule is built in 1c.
CREATE OR REPLACE VIEW due_mar AS
SELECT user_id
FROM (SELECT user_id, arg_max(expires_at, [transacted_at, 1 - is_cancel, expires_at]) AS exp_last
      FROM t WHERE transacted_at <= 20170228 GROUP BY 1)
WHERE exp_last BETWEEN 20170301 AND 20170331;

-- Each row with prev_exp = the latest expiry of the user's EARLIER rows (both exports, placeholder 1970-01-01 excluded).
-- Used by T25: a renewal bought while prev_exp is still running gets its plan days added on top of prev_exp.
CREATE OR REPLACE VIEW t_prev AS
SELECT *, max(expires_at) OVER (PARTITION BY user_id ORDER BY transacted_at, expires_at, src_row
                                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prev_exp
FROM t WHERE expires_at <> 19700101;

-- ---------------------------------------------------------------------------
-- 1. Summary table: one row per check
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE dq_summary AS
WITH
n AS (SELECT (SELECT count(*) FROM raw_users)                AS users_rows,
             (SELECT count(*) FROM t)                        AS tx_rows,
             (SELECT count(DISTINCT user_id) FROM t)         AS tx_users,
             (SELECT count(*) FROM raw_churn_labels)         AS lbl_rows),
tx_first AS (SELECT user_id, min(transacted_at) AS first_tx FROM t GROUP BY 1),
checks AS (
  -- ===== USERS =====
  SELECT 'U1' id, 'users' tbl, 'age = 0 (missing, stored as 0)' chk,
         count(*) FILTER (WHERE age = 0) r, count(DISTINCT user_id) FILTER (WHERE age = 0) u FROM raw_users
  UNION ALL SELECT 'U2','users','age < 0',
         count(*) FILTER (WHERE age < 0), count(*) FILTER (WHERE age < 0) FROM raw_users
  UNION ALL SELECT 'U3','users','age 1-3 (below the lower margin)',
         count(*) FILTER (WHERE age BETWEEN 1 AND 3), count(*) FILTER (WHERE age BETWEEN 1 AND 3) FROM raw_users
  UNION ALL SELECT 'U4','users','age > 92 (above the upper margin, max 1820)',
         count(*) FILTER (WHERE age > 92), count(*) FILTER (WHERE age > 92) FROM raw_users
  UNION ALL SELECT 'U5','users','gender missing (NULL/empty)',
         count(*) FILTER (WHERE gender IS NULL OR trim(gender) = ''), count(*) FILTER (WHERE gender IS NULL OR trim(gender) = '') FROM raw_users
  UNION ALL SELECT 'U6','users','registered_at not a valid YYYYMMDD date',
         count(*) FILTER (WHERE try_strptime(registered_at::VARCHAR, '%Y%m%d') IS NULL), count(*) FILTER (WHERE try_strptime(registered_at::VARCHAR, '%Y%m%d') IS NULL) FROM raw_users
  UNION ALL SELECT 'U7','users','registered_at after data end (> 2017-03-31)',
         count(*) FILTER (WHERE registered_at > 20170331), count(*) FILTER (WHERE registered_at > 20170331) FROM raw_users
  UNION ALL SELECT 'U8','users','registered_at after the user''s first transaction',
         count(*), count(*) FROM raw_users JOIN tx_first USING (user_id) WHERE registered_at > first_tx
  UNION ALL SELECT 'U9','users','duplicate user_id (extra rows)',
         count(*) - count(DISTINCT user_id), 0 FROM raw_users
  UNION ALL SELECT 'U10','users','registered users with no transactions (free users; info)',
         count(*), count(*) FROM raw_users WHERE user_id NOT IN (SELECT user_id FROM tx_first)
  UNION ALL SELECT 'U11','users','age unusable: outside 4-92 (U1+U2+U3+U4)',
         count(*) FILTER (WHERE age NOT BETWEEN 4 AND 92), count(*) FILTER (WHERE age NOT BETWEEN 4 AND 92) FROM raw_users

  -- ===== TRANSACTIONS: structure of the two exports =====
  UNION ALL SELECT 'T1','transactions','export_1 rows with expires_at > 2017-03-31 (file is split on expiry)',
         count(*) FILTER (WHERE src_file = 1 AND expires_at > 20170331), 0 FROM t
  UNION ALL SELECT 'T2','transactions','export_2 rows transacted before 2017-03-01 (older purchases expiring after Feb)',
         count(*) FILTER (WHERE src_file = 2 AND transacted_at < 20170301),
         count(DISTINCT user_id) FILTER (WHERE src_file = 2 AND transacted_at < 20170301) FROM t
  UNION ALL SELECT 'T3','transactions','users whose only long-plan (>=180d) rows sit in export_2',
         count(*), count(DISTINCT user_id) FROM t
         WHERE src_file = 2 AND payment_plan_days >= 180
           AND user_id NOT IN (SELECT user_id FROM t WHERE src_file = 1 AND payment_plan_days >= 180)
  UNION ALL SELECT 'T4','transactions','same event in both exports with conflicting fields (rows in export_1 superseded)',
         count(DISTINCT row_e1), count(DISTINCT user_id) FROM x_pairs
         WHERE exp_e1 <> exp_e2 OR ar_e1 <> ar_e2 OR lp_e1 <> lp_e2
  UNION ALL SELECT 'T5','transactions','same event in both exports, all fields identical (true cross-file duplicates)',
         count(DISTINCT row_e1), count(DISTINCT user_id) FROM x_pairs
         WHERE exp_e1 = exp_e2 AND ar_e1 = ar_e2 AND lp_e1 = lp_e2
  UNION ALL SELECT 'T6','transactions','same user+day in both exports but different events (complementary; keep both)',
         count(*), count(DISTINCT user_id) FROM t JOIN x_keys_complementary USING (user_id, transacted_at)
  UNION ALL SELECT 'T7','transactions','exact duplicate rows within one export (extra copies)',
         sum(n - 1), count(DISTINCT user_id) FROM (
           SELECT user_id, src_file, count(*) n FROM t
           GROUP BY user_id, payment_method, payment_plan_days, list_price, amount_paid,
                    is_auto_renew, transacted_at, expires_at, is_cancel, src_file
           HAVING count(*) > 1)
  UNION ALL SELECT 'T8','transactions','(user_id, transacted_at) not unique within a file (grain finding; info)',
         sum(n), count(DISTINCT user_id) FROM (
           SELECT user_id, count(*) n FROM t GROUP BY user_id, transacted_at, src_file HAVING count(*) > 1)

  UNION ALL SELECT 'T24','transactions','stacked passes: same user+day+core event repeated in one file with different expiries',
         count(*), count(DISTINCT user_id) FROM t_core
         WHERE n_core > 1 AND (user_id, transacted_at, payment_method, payment_plan_days, amount_paid, is_cancel, src_file) IN (
           SELECT (user_id, transacted_at, payment_method, payment_plan_days, amount_paid, is_cancel, src_file) FROM t
           GROUP BY user_id, transacted_at, payment_method, payment_plan_days, amount_paid, is_cancel, src_file
           HAVING count(DISTINCT expires_at) > 1)

  -- ===== TRANSACTIONS: values =====
  UNION ALL SELECT 'T9','transactions','plan_days = 0 AND list_price = 0 but amount_paid > 0 (missing plan metadata, Mar-Oct 2015)',
         count(*), count(DISTINCT user_id) FROM t WHERE payment_plan_days = 0 AND list_price = 0 AND amount_paid > 0
  UNION ALL SELECT 'T10','transactions','amount_paid > list_price with list_price > 0',
         count(*), count(DISTINCT user_id) FROM t WHERE list_price > 0 AND amount_paid > list_price
  UNION ALL SELECT 'T11','transactions','amount_paid = 0 on a non-cancel row with list_price > 0 (free trial / 100% discount)',
         count(*), count(DISTINCT user_id) FROM t WHERE is_cancel = 0 AND amount_paid = 0 AND list_price > 0
  UNION ALL SELECT 'T12','transactions','list_price = 0 AND amount_paid = 0 on a non-cancel row (unpriced free period)',
         count(*), count(DISTINCT user_id) FROM t WHERE is_cancel = 0 AND amount_paid = 0 AND list_price = 0
  UNION ALL SELECT 'T13','transactions','plan_days = 0 on any other row',
         count(*), count(DISTINCT user_id) FROM t WHERE payment_plan_days = 0 AND NOT (list_price = 0 AND amount_paid > 0)
  UNION ALL SELECT 'T14','transactions','cancellations (is_cancel = 1; info)',
         count(*) FILTER (WHERE is_cancel = 1), count(DISTINCT user_id) FILTER (WHERE is_cancel = 1) FROM t
  UNION ALL SELECT 'T15','transactions','expires_at < transacted_at on a cancel row (documented: cancel moves expiry earlier)',
         count(*), count(DISTINCT user_id) FROM t WHERE is_cancel = 1 AND expires_at < transacted_at AND expires_at <> 19700101
  UNION ALL SELECT 'T16','transactions','expires_at < transacted_at on a NON-cancel row',
         count(*), count(DISTINCT user_id) FROM t WHERE is_cancel = 0 AND expires_at < transacted_at AND expires_at <> 19700101
  UNION ALL SELECT 'T17','transactions','expires_at = 1970-01-01 (epoch placeholder = missing)',
         count(*), count(DISTINCT user_id) FROM t WHERE expires_at = 19700101
  UNION ALL SELECT 'T18','transactions','expires_at before 2015-01-01 (excluding epoch)',
         count(*), count(DISTINCT user_id) FROM t WHERE expires_at < 20150101 AND expires_at <> 19700101
  UNION ALL SELECT 'T19','transactions','expires_at after 2019-03-31 (> 2 years past data end)',
         count(*), count(DISTINCT user_id) FROM t WHERE expires_at > 20190331
  UNION ALL SELECT 'T20','transactions','expires_at = 2017-03-31 (spike; month-end billing anchor, not a cap)',
         count(*), count(DISTINCT user_id) FROM t WHERE expires_at = 20170331
  UNION ALL SELECT 'T21','transactions','invalid transacted_at / expires_at (not a YYYYMMDD date)',
         count(*), count(DISTINCT user_id) FROM t
         WHERE try_strptime(transacted_at::VARCHAR, '%Y%m%d') IS NULL OR try_strptime(expires_at::VARCHAR, '%Y%m%d') IS NULL
  UNION ALL SELECT 'T22','transactions','transacted_at after data end (> 2017-03-31)',
         count(*), count(DISTINCT user_id) FROM t WHERE transacted_at > 20170331
  UNION ALL SELECT 'T23','transactions','transactions for users missing from users.csv',
         count(*), count(DISTINCT user_id) FROM t WHERE user_id NOT IN (SELECT user_id FROM raw_users)
  UNION ALL SELECT 'T25','transactions','early renewal: non-cancel row expiring > plan_days + 3 days after purchase, bought while an earlier expiry was still running',
         count(*), count(DISTINCT user_id) FROM t_prev
         WHERE is_cancel = 0 AND payment_plan_days > 0 AND prev_exp > transacted_at
           AND datediff('day', strptime(transacted_at::VARCHAR, '%Y%m%d'), strptime(expires_at::VARCHAR, '%Y%m%d')) - payment_plan_days > 3

  -- ===== CHURN LABELS =====
  UNION ALL SELECT 'L1','churn_labels','duplicate user_id (extra rows)',
         count(*) - count(DISTINCT user_id), 0 FROM raw_churn_labels
  UNION ALL SELECT 'L2','churn_labels','is_churn not in (0,1) or NULL',
         count(*) FILTER (WHERE is_churn IS NULL OR is_churn NOT IN (0, 1)), 0 FROM raw_churn_labels
  UNION ALL SELECT 'L3','churn_labels','labelled users with no transactions at all',
         count(*), count(*) FROM raw_churn_labels WHERE user_id NOT IN (SELECT user_id FROM t)
  UNION ALL SELECT 'L4','churn_labels','labelled users with no transaction on or before 2017-02-28',
         count(*), count(*) FROM raw_churn_labels l
         WHERE NOT EXISTS (SELECT 1 FROM t WHERE t.user_id = l.user_id AND t.transacted_at <= 20170228)
  UNION ALL SELECT 'L5','churn_labels','labelled users missing from users.csv',
         count(*), count(*) FROM raw_churn_labels WHERE user_id NOT IN (SELECT user_id FROM raw_users)
  UNION ALL SELECT 'L6','churn_labels','labelled users NOT in naive "due in March" population',
         count(*), count(*) FROM raw_churn_labels WHERE user_id NOT IN (SELECT user_id FROM due_mar)
  UNION ALL SELECT 'L7','churn_labels','naive "due in March" users with NO label',
         count(*), count(*) FROM due_mar WHERE user_id NOT IN (SELECT user_id FROM raw_churn_labels)
  UNION ALL SELECT 'L8','churn_labels','is_churn = 1 (label base rate; info)',
         count(*) FILTER (WHERE is_churn = 1), count(*) FILTER (WHERE is_churn = 1) FROM raw_churn_labels
)
SELECT c.id AS check_id, c.tbl AS table_name, c.chk AS check_name,
       c.r::BIGINT AS rows_affected,
       c.u::BIGINT AS users_affected,
       round(100.0 * c.r / CASE c.tbl WHEN 'users' THEN n.users_rows
                                      WHEN 'transactions' THEN n.tx_rows
                                      ELSE n.lbl_rows END, 2) AS pct_of_table_rows,
       round(100.0 * c.u / CASE c.tbl WHEN 'users' THEN n.users_rows
                                      WHEN 'transactions' THEN n.tx_users
                                      ELSE n.lbl_rows END, 2) AS pct_of_table_users
FROM checks c CROSS JOIN n;

-- ---------------------------------------------------------------------------
-- 2. Context profiles used in the report (not checks)
-- ---------------------------------------------------------------------------
-- Export coverage: export_1 never has expires_at > 2017-03-31; export_2 almost always has expires_at >= 2017-03-01.
CREATE OR REPLACE TABLE dq_export_profile AS
SELECT src_file, count(*) AS n_rows, count(DISTINCT user_id) AS n_users,
       min(transacted_at) AS min_tx, max(transacted_at) AS max_tx,
       min(expires_at) FILTER (WHERE expires_at > 19700101) AS min_exp, max(expires_at) AS max_exp,
       count(*) FILTER (WHERE expires_at BETWEEN 20170301 AND 20170331) AS exp_in_mar17,
       count(*) FILTER (WHERE expires_at >  20170331) AS exp_after_mar17,
       count(*) FILTER (WHERE transacted_at >= 20170301) AS tx_in_mar17
FROM t GROUP BY 1 ORDER BY 1;

-- The 2017-03-31 expiry spike: which transaction dates produce it (month-end anchoring test).
CREATE OR REPLACE TABLE dq_exp_0331_by_tx AS
SELECT src_file, transacted_at, count(*) AS n
FROM t WHERE expires_at = 20170331 GROUP BY ALL ORDER BY n DESC LIMIT 10;

-- Month of the missing-plan-metadata rows (T9).
CREATE OR REPLACE TABLE dq_t9_by_month AS
SELECT transacted_at // 100 AS yyyymm, count(*) AS n, mode(amount_paid) AS typical_paid
FROM t WHERE payment_plan_days = 0 AND list_price = 0 AND amount_paid > 0 GROUP BY 1 ORDER BY 1;

-- ---------------------------------------------------------------------------
-- 3. Example rows (deterministic sample: lowest hash per issue)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE dq_examples_transactions AS
WITH t4_pair AS (  -- one fixed pair (a row in export_1 can match several in export_2)
  SELECT row_e1, row_e2 FROM x_pairs WHERE exp_e1 <> exp_e2 ORDER BY hash(row_e1), row_e1, row_e2 LIMIT 1),
tagged AS (
  SELECT 'T4 conflicting version (export_1 side)' AS issue, t.* FROM t
    WHERE src_row = (SELECT row_e1 FROM t4_pair)
  UNION ALL SELECT 'T4 conflicting version (export_2 side)', t.* FROM t
    WHERE src_row = (SELECT row_e2 FROM t4_pair)
  UNION ALL SELECT 'T6 complementary events split across exports', t.* FROM t
    WHERE (user_id, transacted_at) IN (SELECT (user_id, transacted_at) FROM x_keys_complementary ORDER BY hash(user_id) LIMIT 1)
  UNION ALL SELECT 'T7 exact duplicate within export', t.* FROM t
    WHERE (user_id, transacted_at, expires_at, src_file) IN (
      SELECT (user_id, transacted_at, expires_at, src_file) FROM t
      GROUP BY user_id, payment_method, payment_plan_days, list_price, amount_paid, is_auto_renew,
               transacted_at, expires_at, is_cancel, src_file
      HAVING count(*) > 1 ORDER BY hash(user_id) LIMIT 1)
  UNION ALL SELECT * FROM (SELECT 'T2 export_2 row bought before March (long plan expiring after Feb)', t.* FROM t
    WHERE src_file = 2 AND transacted_at < 20170301 AND payment_plan_days >= 360 AND is_cancel = 0 ORDER BY hash(src_row) LIMIT 1)
  UNION ALL SELECT * FROM (SELECT 'T13 plan_days=0 on other row', t.* FROM t
    WHERE payment_plan_days = 0 AND NOT (list_price = 0 AND amount_paid > 0) ORDER BY hash(src_row) LIMIT 1)
  UNION ALL SELECT 'T8 several real events same user+day in one file', t.* FROM t
    WHERE (user_id, transacted_at, src_file) IN (
      SELECT (user_id, transacted_at, src_file) FROM t GROUP BY user_id, transacted_at, src_file
      HAVING count(*) = 2 AND count(DISTINCT is_cancel) = 2 ORDER BY hash(user_id), user_id LIMIT 1)
  UNION ALL SELECT * FROM (SELECT 'T24 stacked free passes (first 3 of the largest stack)', t.* FROM t
    WHERE (user_id, transacted_at) = (SELECT (user_id, transacted_at) FROM t GROUP BY user_id, transacted_at
                                      ORDER BY count(*) DESC, user_id LIMIT 1)
    ORDER BY expires_at, src_row LIMIT 3)
  UNION ALL SELECT * FROM (SELECT 'T9 plan_days=0 & list_price=0 but paid', t.* FROM t
    WHERE payment_plan_days = 0 AND list_price = 0 AND amount_paid > 0 ORDER BY hash(src_row) LIMIT 1)
  UNION ALL SELECT * FROM (SELECT 'T10 amount_paid > list_price (list>0)', t.* FROM t
    WHERE list_price > 0 AND amount_paid > list_price ORDER BY hash(src_row) LIMIT 1)
  UNION ALL SELECT * FROM (SELECT 'T11 free trial / 100% discount', t.* FROM t
    WHERE is_cancel = 0 AND amount_paid = 0 AND list_price > 0 ORDER BY hash(src_row) LIMIT 1)
  UNION ALL SELECT * FROM (SELECT 'T12 unpriced free period', t.* FROM t
    WHERE is_cancel = 0 AND amount_paid = 0 AND list_price = 0 ORDER BY hash(src_row) LIMIT 1)
  UNION ALL SELECT * FROM (SELECT 'T15 cancel with expiry before transaction', t.* FROM t
    WHERE is_cancel = 1 AND expires_at < transacted_at AND expires_at <> 19700101 ORDER BY hash(src_row) LIMIT 1)
  UNION ALL SELECT * FROM (SELECT 'T16 non-cancel with expiry before transaction', t.* FROM t
    WHERE is_cancel = 0 AND expires_at < transacted_at AND expires_at <> 19700101 ORDER BY hash(src_row) LIMIT 1)
  UNION ALL SELECT * FROM (SELECT 'T17 expires_at = 1970-01-01', t.* FROM t
    WHERE expires_at = 19700101 ORDER BY hash(src_row) LIMIT 1)
  UNION ALL SELECT * FROM (SELECT 'T18 expires_at before 2015', t.* FROM t
    WHERE expires_at < 20150101 AND expires_at <> 19700101 ORDER BY hash(src_row) LIMIT 1)
  UNION ALL SELECT * FROM (SELECT 'T19 expires_at > 2019-03-31', t.* FROM t
    WHERE expires_at > 20190331 ORDER BY hash(src_row) LIMIT 1)
  UNION ALL SELECT * FROM (SELECT 'T20 expires_at = 2017-03-31 spike', t.* FROM t
    WHERE expires_at = 20170331 AND src_file = 1 AND transacted_at = 20170228 ORDER BY hash(src_row) LIMIT 1)
  UNION ALL SELECT * FROM (SELECT 'T25 early renewal: expiry = earlier expiry + plan days', t.* FROM t
    WHERE src_row = (SELECT src_row FROM t_prev
                     WHERE is_cancel = 0 AND payment_plan_days = 30 AND prev_exp > transacted_at AND is_auto_renew = 0
                       AND datediff('day', strptime(prev_exp::VARCHAR, '%Y%m%d'), strptime(expires_at::VARCHAR, '%Y%m%d')) = 30
                       AND datediff('day', strptime(transacted_at::VARCHAR, '%Y%m%d'), strptime(prev_exp::VARCHAR, '%Y%m%d')) >= 10
                     ORDER BY hash(src_row) LIMIT 1))
  UNION ALL SELECT * FROM (SELECT 'T23 user missing from users.csv', t.* FROM t
    WHERE user_id NOT IN (SELECT user_id FROM raw_users) ORDER BY hash(src_row) LIMIT 1)
)
SELECT * FROM tagged ORDER BY issue, user_id, transacted_at, src_file, src_row;

CREATE OR REPLACE TABLE dq_examples_users AS
SELECT * FROM (SELECT 'U1 age = 0' AS issue, * FROM raw_users WHERE age = 0 ORDER BY hash(user_id) LIMIT 1)
UNION ALL SELECT * FROM (SELECT 'U2 age < 0', * FROM raw_users WHERE age < 0 ORDER BY hash(user_id) LIMIT 1)
UNION ALL SELECT * FROM (SELECT 'U3 age 1-3', * FROM raw_users WHERE age BETWEEN 1 AND 3 ORDER BY hash(user_id) LIMIT 1)
UNION ALL SELECT * FROM (SELECT 'U4 age > 92', * FROM raw_users WHERE age > 92 ORDER BY age DESC, hash(user_id) LIMIT 1)
UNION ALL SELECT * FROM (SELECT 'U5 gender missing', * FROM raw_users WHERE gender IS NULL OR trim(gender) = '' ORDER BY hash(user_id) LIMIT 1)
UNION ALL SELECT * FROM (SELECT 'U7 registered after data end', * FROM raw_users WHERE registered_at > 20170331 ORDER BY hash(user_id) LIMIT 1)
UNION ALL SELECT * FROM (SELECT 'U8 registered after first transaction', u.* FROM raw_users u
  JOIN (SELECT user_id, min(transacted_at) f FROM t GROUP BY 1) x USING (user_id)
  WHERE u.registered_at > x.f ORDER BY hash(user_id) LIMIT 1);

CREATE OR REPLACE TABLE dq_examples_churn_labels AS
SELECT * FROM (SELECT 'L4 no transaction on or before 2017-02-28' AS issue, l.* FROM raw_churn_labels l
  WHERE NOT EXISTS (SELECT 1 FROM t WHERE t.user_id = l.user_id AND t.transacted_at <= 20170228)
  ORDER BY hash(user_id) LIMIT 1)
UNION ALL SELECT * FROM (SELECT 'L5 missing from users.csv', * FROM raw_churn_labels
  WHERE user_id NOT IN (SELECT user_id FROM raw_users) ORDER BY hash(user_id) LIMIT 1)
UNION ALL SELECT * FROM (SELECT 'L6 labelled but not in naive due-in-March population', * FROM raw_churn_labels
  WHERE user_id NOT IN (SELECT user_id FROM due_mar) ORDER BY hash(user_id) LIMIT 1);

COPY dq_examples_transactions TO 'reports/01_dq_examples_transactions.csv' (HEADER, DELIMITER ',');
COPY dq_examples_users        TO 'reports/01_dq_examples_users.csv'        (HEADER, DELIMITER ',');
COPY dq_examples_churn_labels TO 'reports/01_dq_examples_churn_labels.csv' (HEADER, DELIMITER ',');
COPY dq_summary               TO 'reports/01_dq_summary.csv'               (HEADER, DELIMITER ',');

SELECT * FROM dq_summary ORDER BY table_name, check_id;
