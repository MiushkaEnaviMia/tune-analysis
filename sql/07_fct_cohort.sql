-- 07_fct_cohort.sql
-- Cohort table: revenue and retention over time, by start month.
-- Input : dim_user, fct_user_month
-- Output: fct_cohort  one row per COHORT x MONTHS SINCE START (dense: every month from the cohort's
--         start to 2017-03, zeros included, so a cohort that fades out shows 0, not a missing row)
--
-- Which start date. users.csv has a registration date (registered_at), but it is not used:
--   * it exists only for users in users.csv (109,330 transacting users are missing, T23),
--   * 44% of registrations are before the data window (from 2004; transactions start 2015-01),
--     so months 0..N after registration would be unobserved, not zero,
--   * some registrations are after the first transaction (U8) or after the data end (U7).
-- The cohort is the user's FIRST SUBSCRIPTION month: dim_user.first_period_date (first purchase,
-- free or paid) -- the same event that marks status = 'new' in fct_user_month.
-- Users with no subscription period at all (registry-only users) are not in any cohort.
--
-- Field definitions (m = months_since_start; "the month" = cohort_month + m)
--   cohort_month            month of the user's first subscription period
--   months_since_start      0 = the start month, 1 = next calendar month, ...
--   calendar_month          cohort_month + months_since_start
--   cohort_users            users who started in cohort_month (same on every row of the cohort)
--   active_users            cohort users with access on >= 1 day of the month (fct_user_month.is_active)
--   retained_users          cohort users active in the month OR who bought in it (n_purchases > 0).
--                           Equals active_users except for purchases with 0 access days (retro
--                           cancels / zero-length periods; 3,454 users in their start month), and
--                           makes month 0 = 100% by construction
--   retention_pct           retained_users / cohort_users * 100
--   active_paid_users       cohort users with access from a PAID period (fct_user_month.is_active_paid;
--                           excludes free trials, includes annual payers in months they did not pay)
--   paying_users            cohort users who paid money in the month (amount_paid > 0)
--   revenue                 sum of amount_paid on purchases made in the month (cash view, as in
--                           fct_user_month; an annual plan counts fully in the month it was bought)
--   cum_revenue             revenue summed from month 0 to this month
--   arpu                    revenue / cohort_users  (per user who STARTED, so cohorts compare fairly)
--   cum_arpu                cum_revenue / cohort_users  (revenue per starting user to date; its growth
--                           over months_since_start is the cohort's revenue curve)
--   arpu_active             revenue / active_users (per user active in the month; NULL if none)
--   months_observed         months of data the cohort has: from cohort_month to 2017-03 inclusive
--   is_last_observed_month  1 on the cohort's last row (calendar_month = 2017-03)
--   flag_incomplete_cohort  1 if the cohort has fewer than 6 months of data (cohort_month >= 2016-10):
--                           its curve is too short to compare with older cohorts at m >= 6
--   flag_left_censored      1 for the 2015-01 cohort: the data starts 2015-01-01, so part of it are
--                           older users seen for the first time (dim_user.flag_first_seen_jan2015)
-- Note: 2017-03 is fully observed for activity and revenue (purchases to 2017-03-31). Only churn in
-- 2017-03 is incomplete; this table does not use churn.

CREATE OR REPLACE TABLE fct_cohort AS
WITH
cohort_user AS (
  SELECT user_id, date_trunc('month', first_period_date)::DATE AS cohort_month
  FROM dim_user
  WHERE n_periods > 0),

sizes AS (
  SELECT cohort_month, count(*) AS cohort_users FROM cohort_user GROUP BY 1),

grid AS (   -- every cohort x every month from its start to 2017-03
  SELECT s.cohort_month, s.cohort_users, r.range::DATE AS calendar_month
  FROM sizes s,
       range(DATE '2015-01-01', DATE '2017-04-01', INTERVAL 1 MONTH) r
  WHERE r.range::DATE >= s.cohort_month),

act AS (
  SELECT c.cohort_month, m.month AS calendar_month,
         count(*) FILTER (WHERE m.is_active = 1)                          AS active_users,
         count(*) FILTER (WHERE m.is_active = 1 OR m.n_purchases > 0)     AS retained_users,
         count(*) FILTER (WHERE m.is_active_paid = 1)                     AS active_paid_users,
         count(*) FILTER (WHERE m.amount_paid > 0)                        AS paying_users,
         sum(m.amount_paid)                                               AS revenue
  FROM cohort_user c
  JOIN fct_user_month m USING (user_id)
  GROUP BY 1, 2)

SELECT
  g.cohort_month,
  date_diff('month', g.cohort_month, g.calendar_month)::INT                AS months_since_start,
  g.calendar_month,
  g.cohort_users,
  coalesce(a.active_users, 0)                                              AS active_users,
  coalesce(a.retained_users, 0)                                            AS retained_users,
  round(100.0 * coalesce(a.retained_users, 0) / g.cohort_users, 2)         AS retention_pct,
  coalesce(a.active_paid_users, 0)                                         AS active_paid_users,
  coalesce(a.paying_users, 0)                                              AS paying_users,
  coalesce(a.revenue, 0)::BIGINT                                           AS revenue,
  (sum(coalesce(a.revenue, 0)) OVER w)::BIGINT                            AS cum_revenue,
  round(coalesce(a.revenue, 0) / g.cohort_users, 4)                        AS arpu,
  round(sum(coalesce(a.revenue, 0)) OVER w / g.cohort_users, 4)            AS cum_arpu,
  round(a.revenue / nullif(a.active_users, 0), 4)                          AS arpu_active,
  date_diff('month', g.cohort_month, DATE '2017-03-01')::INT + 1           AS months_observed,
  (g.calendar_month = DATE '2017-03-01')::TINYINT                          AS is_last_observed_month,
  (g.cohort_month >= DATE '2016-10-01')::TINYINT                           AS flag_incomplete_cohort,
  (g.cohort_month = DATE '2015-01-01')::TINYINT                            AS flag_left_censored
FROM grid g
LEFT JOIN act a USING (cohort_month, calendar_month)
WINDOW w AS (PARTITION BY g.cohort_month ORDER BY g.calendar_month
             ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
ORDER BY 1, 2;

-- ---------------------------------------------------------------------------
-- Validation (every *_diff / n_* column below should be 0; month0 values 100)
-- ---------------------------------------------------------------------------
SELECT
  count(*)                                                                        AS rows,
  count(DISTINCT cohort_month)                                                    AS cohorts,
  count(*) - count(DISTINCT (cohort_month, months_since_start))                   AS dup_keys,
  -- 1. users: cohort sizes = subscribed users in dim_user
  (SELECT sum(cohort_users) FROM fct_cohort WHERE months_since_start = 0)
    - (SELECT count(*) FROM dim_user WHERE n_periods > 0)                         AS users_diff,
  -- 2. revenue ties to fct_user_month and fct_subscription
  round(sum(revenue) - (SELECT sum(amount_paid) FROM fct_user_month), 6)          AS revenue_vs_user_month_diff,
  round(sum(revenue) - (SELECT sum(amount_paid) FROM fct_subscription), 6)        AS revenue_vs_subscription_diff,
  round((SELECT sum(cum_revenue) FROM fct_cohort WHERE is_last_observed_month = 1)
        - (SELECT sum(amount_paid) FROM fct_subscription), 6)                    AS cum_revenue_end_diff,
  -- 3. active / paying users tie to fct_user_month
  sum(active_users) - (SELECT count(*) FROM fct_user_month WHERE is_active = 1)  AS active_diff,
  sum(active_paid_users) - (SELECT count(*) FROM fct_user_month WHERE is_active_paid = 1) AS active_paid_diff,
  sum(paying_users) - (SELECT count(*) FROM fct_user_month WHERE amount_paid > 0) AS paying_diff,
  -- 4. month 0 = 100%
  min(retention_pct) FILTER (WHERE months_since_start = 0)                        AS month0_min_retention,
  max(retention_pct) FILTER (WHERE months_since_start = 0)                        AS month0_max_retention,
  -- 5. ranges
  count(*) FILTER (WHERE retention_pct < 0 OR retention_pct > 100
                      OR active_users > cohort_users OR retained_users > cohort_users
                      OR paying_users > cohort_users)                             AS n_out_of_range,
  count(*) FILTER (WHERE revenue < 0 OR cum_revenue < 0 OR arpu < 0)              AS n_negative,
  count(*) FILTER (WHERE cum_arpu < lag_cum_arpu)                                 AS n_cum_arpu_decreasing,
  count(*) FILTER (WHERE active_users > retained_users)                           AS n_active_gt_retained,
  -- 6. data-end flags
  count(DISTINCT cohort_month) FILTER (WHERE flag_incomplete_cohort = 1)          AS n_incomplete_cohorts,
  count(*) FILTER (WHERE calendar_month > DATE '2017-03-01')                      AS n_after_data_end
FROM (SELECT *, lag(cum_arpu) OVER (PARTITION BY cohort_month ORDER BY months_since_start) AS lag_cum_arpu
      FROM fct_cohort);
