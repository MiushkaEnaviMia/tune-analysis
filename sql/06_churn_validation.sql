-- 06_churn_validation.sql
-- Part 1c: the billing team's churn definition, implemented on the clean layer and checked
-- against churn_labels.
-- Input : stg_transactions (cleaned events), dim_user, raw_churn_labels
-- Output: churn_mar17        one row per user who is in OUR March-2017 cohort and/or has a label
--         churn_confusion    the confusion table (our outcome x billing label), incl. population gaps
--         churn_disagreement one row per disagreement bucket, with users, label churn rate and reason
--
-- The definition (BRIEF.md):
--   Cohort  : users whose membership was due to expire in March 2017, based on all transactions up
--             to and including 2017-02-28.
--   Churned : no new subscription transaction (is_cancel = 0) between 2017-03-01 and 30 days after
--             the membership expiry. Renewing early counts as retained. A cancel can move the
--             expiry earlier.
--
-- How we read it (decided from the brief, NOT tuned to the labels):
--   * Expiry as of Feb 28 = expiry after the user's LAST event (max event_seq) with
--     transacted_date <= 2017-02-28. Last event, not max expiry: a cancel can move it earlier.
--     We use expires_at_asof_feb, i.e. the export_1 value where the two exports disagree (T4).
--   * A cancel in March that comes BEFORE any renewal and moves the expiry earlier shortens the
--     window (eff_expiry). A renewal is ANY is_cancel = 0 event, paid or free, any plan length.
--   * The data ends 2017-03-31. The 30-day window ends inside the data only when
--     eff_expiry + 30 <= 2017-03-31, i.e. expiry on 2017-03-01 (or a cancel that pulled it into
--     February). Everyone else who has not renewed by Mar 31 is 'unknown': we cannot tell
--     whether they renewed in April. We do NOT guess them.
--
-- Labels are only used to explain disagreements (buckets below), never to choose a rule.

CREATE OR REPLACE TABLE churn_mar17 AS
WITH
st AS (  -- state after the last event up to and including 2017-02-28
  SELECT user_id,
         arg_max(expires_at_asof_feb, event_seq) AS exp_asof_feb,
         arg_max(is_cancel, event_seq)           AS last_event_is_cancel,
         max(transacted_date)                    AS last_tx_date
  FROM stg_transactions
  WHERE transacted_date <= DATE '2017-02-28'
  GROUP BY 1),

st_noncancel AS (  -- expiry before any cancel moved it (used only to explain a bucket)
  SELECT user_id, arg_max(expires_at_asof_feb, event_seq) AS exp_before_cancel
  FROM stg_transactions
  WHERE transacted_date <= DATE '2017-02-28' AND is_cancel = 0
  GROUP BY 1),

st_e1 AS (  -- the same state seen through export_1 ONLY (export_1 holds no expiry after Mar 31)
  SELECT user_id, arg_max(expires_at_asof_feb, event_seq) AS exp_asof_feb_e1
  FROM stg_transactions
  WHERE transacted_date <= DATE '2017-02-28' AND src_file = 1
  GROUP BY 1),

cohort AS (
  SELECT * FROM st
  WHERE exp_asof_feb BETWEEN DATE '2017-03-01' AND DATE '2017-03-31'),

march AS (  -- what the cohort did in March 2017
  SELECT c.user_id,
         min(s.transacted_date) FILTER (WHERE s.is_cancel = 0)                    AS first_renewal_date,
         min(s.transacted_date) FILTER (WHERE s.is_cancel = 1)                    AS first_cancel_date,
         arg_min(s.expires_date, s.event_seq) FILTER (WHERE s.is_cancel = 1)      AS first_cancel_expiry,
         max(s.plan_days_clean) FILTER (WHERE s.is_cancel = 0)                    AS max_renewal_plan_days,
         bool_or(s.amount_paid > 0) FILTER (WHERE s.is_cancel = 0)                AS renewal_paid,
         arg_max(s.is_cancel, s.event_seq)                                        AS last_march_event_is_cancel
  FROM cohort c
  JOIN stg_transactions s
    ON s.user_id = c.user_id
   AND s.transacted_date BETWEEN DATE '2017-03-01' AND DATE '2017-03-31'
  GROUP BY 1),

ours AS (
  SELECT c.user_id, c.exp_asof_feb, c.last_event_is_cancel, m.*  EXCLUDE (user_id),
         CASE WHEN m.first_cancel_date < coalesce(m.first_renewal_date, DATE '9999-12-31')
               AND m.first_cancel_expiry < c.exp_asof_feb
              THEN m.first_cancel_expiry ELSE c.exp_asof_feb END                AS eff_expiry
  FROM cohort c LEFT JOIN march m USING (user_id)),

outcome AS (
  SELECT *,
         eff_expiry + 30                                                        AS window_end,
         CASE WHEN first_renewal_date <= eff_expiry + 30               THEN 'retained'
              WHEN eff_expiry + 30 <= DATE '2017-03-31'                THEN 'churned'
              ELSE 'unknown' END                                                AS our_outcome
  FROM ours),

j AS (
  SELECT coalesce(o.user_id, l.user_id)        AS user_id,
         (o.user_id IS NOT NULL)::TINYINT      AS in_our_cohort,
         (l.user_id IS NOT NULL)::TINYINT      AS has_label,
         l.is_churn                            AS label_is_churn,
         o.* EXCLUDE (user_id, exp_asof_feb, last_event_is_cancel)
  FROM outcome o FULL JOIN raw_churn_labels l USING (user_id))

SELECT j.*,
       a.exp_asof_feb, a.last_event_is_cancel, a.last_tx_date,
       n.exp_before_cancel, e.exp_asof_feb_e1,
       d.is_in_users,
       CASE
         -- both sides have the user
         WHEN in_our_cohort = 1 AND has_label = 1 THEN
           CASE
             WHEN our_outcome = 'retained' AND label_is_churn = 0 THEN 'A1 match: retained'
             WHEN our_outcome = 'churned'  AND label_is_churn = 1 THEN 'A2 match: churned'
             WHEN our_outcome = 'unknown'                          THEN 'B1 unknown to us: no renewal by Mar 31, window runs into April'
             WHEN our_outcome = 'retained' AND max_renewal_plan_days >= 90
                                                                    THEN 'C1 renewed in March onto a 90+ day plan, label says churned'
             WHEN our_outcome = 'retained' AND last_march_event_is_cancel = 1
                                                                    THEN 'C2 renewed in March then cancelled in March, label says churned'
             WHEN our_outcome = 'retained'                         THEN 'C3 renewed in March (30-day plan), label says churned'
             ELSE                                                       'C4 no renewal and window closed, label says retained'
           END
         -- label only
         WHEN has_label = 1 THEN
           CASE
             WHEN a.user_id IS NULL                                THEN 'D1 labelled, no transaction up to Feb 28'
             WHEN a.exp_asof_feb > DATE '2017-03-31'
              AND e.exp_asof_feb_e1 BETWEEN DATE '2017-03-01' AND DATE '2017-03-31'
                                                                    THEN 'D2 labelled, a February renewal (export_2) already pushed expiry past March'
             WHEN a.exp_asof_feb < DATE '2017-03-01' AND a.last_event_is_cancel = 1
              AND n.exp_before_cancel BETWEEN DATE '2017-03-01' AND DATE '2017-03-31'
                                                                    THEN 'D3 labelled, a cancel by Feb 28 moved expiry from March into February'
             WHEN a.exp_asof_feb < DATE '2017-03-01'               THEN 'D4 labelled, membership already expired before March'
             ELSE                                                       'D5 labelled, expiry after March (other)'
           END
         -- our cohort only
         WHEN a.exp_asof_feb = DATE '2017-03-01'                   THEN 'E1 our cohort, not labelled: expiry on Mar 1'
         ELSE                                                           'E2 our cohort, not labelled: other'
       END AS bucket
FROM j
LEFT JOIN st             a USING (user_id)
LEFT JOIN st_noncancel   n USING (user_id)
LEFT JOIN st_e1         e USING (user_id)
LEFT JOIN dim_user       d USING (user_id);

-- ---------------------------------------------------------------------------
-- Confusion table: our outcome (rows) x billing label (columns), incl. users only one side has
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE churn_confusion AS
SELECT coalesce(our_outcome, 'not in our cohort')                     AS our_outcome,
       count(*) FILTER (WHERE label_is_churn = 0)                      AS label_retained,
       count(*) FILTER (WHERE label_is_churn = 1)                      AS label_churned,
       count(*) FILTER (WHERE has_label = 0)                           AS no_label,
       count(*)                                                        AS total
FROM churn_mar17
GROUP BY 1
ORDER BY CASE coalesce(our_outcome, 'not in our cohort') WHEN 'retained' THEN 1 WHEN 'churned' THEN 2 WHEN 'unknown' THEN 3 ELSE 4 END;

CREATE OR REPLACE TABLE churn_disagreement AS
SELECT bucket,
       count(*)                                        AS users,
       round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct_of_all_rows,
       sum(label_is_churn)                             AS label_churned,
       round(100.0 * avg(label_is_churn), 1)           AS label_churn_pct
FROM churn_mar17
GROUP BY 1
ORDER BY 1;

-- ---------------------------------------------------------------------------
-- Validation
-- ---------------------------------------------------------------------------
-- Expect: one row per user; every label present; buckets add up; the 'churned' outcome equals the
-- March-2017 churn the clean layer itself reports (fct_user_month, same 30-day rule).
SELECT
  count(*)                                                               AS rows,
  count(*) - count(DISTINCT user_id)                                     AS dup_user,
  sum(has_label) - (SELECT count(*) FROM raw_churn_labels)               AS labels_missing,
  sum(in_our_cohort)                                                     AS our_cohort,
  sum(in_our_cohort * has_label)                                         AS in_both,
  count(*) FILTER (WHERE our_outcome = 'retained')                       AS ours_retained,
  count(*) FILTER (WHERE our_outcome = 'churned')                        AS ours_churned,
  count(*) FILTER (WHERE our_outcome = 'unknown')                        AS ours_unknown,
  count(*) FILTER (WHERE bucket LIKE 'A%')                               AS matches,
  count(*) FILTER (WHERE bucket LIKE 'C%')                               AS outcome_disagreements,
  (SELECT count(*) FROM fct_user_month
   WHERE month = DATE '2017-03-01' AND is_churned = 1)                   AS fct_user_month_mar_churned
FROM churn_mar17;
