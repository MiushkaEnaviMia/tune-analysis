-- 05_fct_user_month.sql
-- Part 1b, step 4: the monthly panel that makes Part 2 metrics plain GROUP BYs.
-- Input : fct_subscription
-- Output: fct_user_month
-- Grain : one row per user per calendar month, Jan-2015 .. Mar-2017, for every month in which the
--         user (a) had access on at least one day, or (b) paid, or (c) churned.
--         Months with none of these are omitted: a dense user x 27-month grid would be ~16M rows,
--         mostly zeros, and every metric would still filter them out.
--
-- Definitions
--   is_active        access on >= 1 day of the month (from the non-overlapping covered intervals)
--   is_active_paid   access on >= 1 day from a PAID period (excludes free trials T11/T12)
--   is_active_som / is_active_eom   access on the first / last day of the month
--   status (one value per row, precedence top to bottom):
--     new          the user's first-ever episode starts this month
--     reactivated  a later episode starts this month (returned > 30 days after the previous expiry)
--     churned      an episode ends this month (its expiry date falls in it) and the user did NOT buy
--                  again within 30 days: the brief's churn rule, applied to every month
--     censored     an episode ends this month but its 30-day window runs past 2017-03-31, so the
--                  outcome is unknown (all March-2017 expiries except 03-01)
--     renewing     active and carried over from an existing episode (renewal or still inside a plan)
--   is_churned is a separate flag because a user can start and churn in the same month.

CREATE OR REPLACE TABLE fct_user_month AS
WITH
months AS (
  SELECT range::DATE AS month_start, (range + INTERVAL 1 MONTH)::DATE AS next_month
  FROM range(DATE '2015-01-01', DATE '2017-04-01', INTERVAL 1 MONTH)),

cov AS (  -- covered days per user-month (covered intervals are half-open [covered_start, covered_end))
  SELECT s.user_id, m.month_start,
         sum(date_diff('day', greatest(s.covered_start, m.month_start), least(s.covered_end, m.next_month))) AS active_days,
         sum(date_diff('day', greatest(s.covered_start, m.month_start), least(s.covered_end, m.next_month)))
           FILTER (WHERE s.is_free = 0)                                                                 AS paid_active_days,
         bool_or(s.covered_start <= m.month_start AND s.covered_end > m.month_start)                     AS active_som,
         bool_or(s.covered_start <= m.next_month - 1 AND s.covered_end > m.next_month - 1)               AS active_eom,
         max(s.episode_no)                                                                               AS episode_no
  FROM fct_subscription s
  JOIN months m ON s.covered_start < m.next_month AND s.covered_end > m.month_start
  WHERE s.covered_end > s.covered_start
  GROUP BY 1, 2),

pay AS (  -- purchases by the month they were made (cash view)
  SELECT user_id, date_trunc('month', start_date)::DATE AS month_start,
         count(*)                                             AS n_purchases,
         count(*) FILTER (WHERE is_free = 0)                  AS n_paid_purchases,
         count(*) FILTER (WHERE subscription_type = 'renewal' AND is_free = 0) AS n_paid_renewals,
         sum(amount_paid)                                     AS amount_paid,
         sum(list_price)                                      AS list_price,
         sum(discount_amount)                                 AS discount_amount,
         max((subscription_type = 'new')::INT)                AS starts_first_episode,
         max((subscription_type = 'reactivation')::INT)       AS starts_later_episode,
         max(is_cancelled)                                    AS has_cancel
  FROM fct_subscription GROUP BY 1, 2),

ends AS (  -- episode ends by the month of the expiry date
  SELECT DISTINCT user_id, date_trunc('month', episode_end_date)::DATE AS month_start,
         episode_outcome
  FROM fct_subscription
  WHERE episode_outcome IN ('churned', 'churned_then_reactivated', 'censored')),

ends_m AS (
  SELECT user_id, month_start,
         max((episode_outcome IN ('churned', 'churned_then_reactivated'))::INT) AS is_churned,
         max((episode_outcome = 'censored')::INT)                               AS is_censored
  FROM ends GROUP BY 1, 2),

grid AS (
  SELECT user_id, month_start FROM cov
  UNION SELECT user_id, month_start FROM pay
  UNION SELECT user_id, month_start FROM ends_m)

SELECT
  g.user_id,
  g.month_start                                                 AS month,
  (coalesce(c.active_days, 0) > 0)::TINYINT                     AS is_active,
  (coalesce(c.paid_active_days, 0) > 0)::TINYINT                AS is_active_paid,
  coalesce(c.active_som, FALSE)::TINYINT                        AS is_active_som,
  coalesce(c.active_eom, FALSE)::TINYINT                        AS is_active_eom,
  coalesce(c.active_days, 0)                                    AS active_days,
  coalesce(c.paid_active_days, 0)                               AS paid_active_days,
  coalesce(p.starts_first_episode, 0)::TINYINT                  AS is_new,
  coalesce(p.starts_later_episode, 0)::TINYINT                  AS is_reactivated,
  coalesce(e.is_churned, 0)::TINYINT                            AS is_churned,
  coalesce(e.is_censored, 0)::TINYINT                           AS is_churn_censored,
  CASE WHEN p.starts_first_episode = 1 THEN 'new'
       WHEN p.starts_later_episode = 1 THEN 'reactivated'
       WHEN e.is_churned = 1           THEN 'churned'
       WHEN e.is_censored = 1          THEN 'censored'
       WHEN c.active_days > 0          THEN 'renewing'
       ELSE 'inactive_payment' END                              AS status,    -- paid/cancelled in a month with 0 access days (retro cancel)
  coalesce(p.n_purchases, 0)                                    AS n_purchases,
  coalesce(p.n_paid_purchases, 0)                               AS n_paid_purchases,
  coalesce(p.n_paid_renewals, 0)                                AS n_paid_renewals,
  coalesce(p.amount_paid, 0)                                    AS amount_paid,
  coalesce(p.list_price, 0)                                     AS list_price,
  coalesce(p.discount_amount, 0)                                AS discount_amount,
  coalesce(p.has_cancel, 0)::TINYINT                            AS has_cancel
FROM grid g
LEFT JOIN cov    c USING (user_id, month_start)
LEFT JOIN pay    p USING (user_id, month_start)
LEFT JOIN ends_m e USING (user_id, month_start)
WHERE g.month_start BETWEEN DATE '2015-01-01' AND DATE '2017-03-01';

-- ---------------------------------------------------------------------------
-- Validation
-- ---------------------------------------------------------------------------
-- Expect: (user_id, month) unique; 27 months; no active_days above the month length;
-- revenue reconciles with fct_subscription; status counts sane.
SELECT
  count(*)                                                                AS rows,
  count(*) - count(DISTINCT (user_id, month))                             AS dup_user_month,
  count(DISTINCT month)                                                   AS months,
  min(month) AS first_month, max(month) AS last_month,
  count(*) FILTER (WHERE active_days > 31)                                AS active_days_gt_31,
  sum(amount_paid) - (SELECT sum(amount_paid) FROM fct_subscription)      AS revenue_diff,
  count(*) FILTER (WHERE status = 'new')                                  AS n_new,
  count(*) FILTER (WHERE status = 'reactivated')                          AS n_reactivated,
  count(*) FILTER (WHERE status = 'renewing')                             AS n_renewing,
  count(*) FILTER (WHERE status = 'churned')                              AS n_churned_status,
  sum(is_churned)                                                         AS n_churn_events,
  count(*) FILTER (WHERE status = 'censored')                             AS n_censored,
  count(*) FILTER (WHERE status = 'inactive_payment')                     AS n_inactive_payment
FROM fct_user_month;
