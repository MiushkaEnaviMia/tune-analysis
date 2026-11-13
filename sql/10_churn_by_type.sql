-- 10_churn_by_type.sql
-- Part 2.3: monthly churn split by subscriber type, the agreed per-type window (3 / 30 days),
-- and the evidence behind that window.
-- Input : fct_subscription
-- Output: mart_churn_by_type      one row per month x subscriber type (30-day rule, same as 08)
--         mart_churn_mixed_window one row per month: churn with 30 days for all vs 3 days for monthly
--                                 auto-renew and 30 days for everyone who pays by hand
--         mart_return_curve       one row per subscriber type: % of returners back by day 1..45
--
-- Subscriber type of a period:
--   Monthly · auto-renew   plan_days <= 31 and is_auto_renew = 1
--   Monthly · manual       plan_days <= 31 and is_auto_renew = 0
--   90+ day plan · manual  plan_days > 31 (quarterly, half-year, annual; none of them auto-renew)
-- The type of a churned episode = the type of the period whose expiry ends the episode.
-- Denominator = paying subscribers on the first day of the month, by the type of the paid plan they hold
-- that day (latest start if several), so the type rates add up to the total in 08.
-- Window choice (Part 1c follow-up, "Churn window by plan"): waiting one more day is worth it only if it
-- brings back about 0.5% of all returners. Auto-renew: 3 days. Paying by hand: 30 days. 45 days = check.

CREATE OR REPLACE TABLE mart_churn_by_type AS
WITH
s AS (
  SELECT *, CASE WHEN plan_days <= 31 AND is_auto_renew = 1 THEN 'Monthly · auto-renew'
                 WHEN plan_days <= 31                       THEN 'Monthly · manual'
                 ELSE '90+ day plan · manual' END AS sub_type
  FROM fct_subscription),
w AS (SELECT unnest([30, 0]) AS win),     -- 0 = mixed rule: 3 days auto-renew, 30 days by hand
p AS (
  SELECT user_id, start_date, end_date, is_free, sub_type,
         max(end_date) OVER (PARTITION BY user_id ORDER BY start_date, period_no
                             ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS run_end,
         lead(start_date) OVER (PARTITION BY user_id ORDER BY start_date, period_no) AS next_start,
         row_number()     OVER (PARTITION BY user_id ORDER BY start_date, period_no) AS rn
  FROM s),
pw AS (
  SELECT p.*, w.win AS rule,
         CASE WHEN w.win = 30 THEN 30 WHEN sub_type = 'Monthly · auto-renew' THEN 3 ELSE 30 END AS win_days
  FROM p CROSS JOIN w),
pe AS (
  SELECT *, (next_start IS NULL OR date_diff('day', run_end, next_start) > win_days) AS ends_here FROM pw),
ep AS (
  SELECT *, coalesce(sum(ends_here::INT) OVER (PARTITION BY user_id, rule ORDER BY rn
                     ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS ep_no
  FROM pe),
ep_end AS (
  SELECT user_id, rule, ep_no,
         max(run_end)                              AS ep_end_date,
         max((is_free = 0)::INT)                   AS has_paid,
         bool_or(ends_here AND next_start IS NULL) AS is_last,
         arg_max(sub_type, rn)                     AS sub_type,
         arg_max(win_days, rn)                     AS win_days
  FROM ep GROUP BY 1, 2, 3),
months AS (SELECT range::DATE AS month FROM range(DATE '2015-01-01', DATE '2017-04-01', INTERVAL 1 MONTH)),
som AS (
  SELECT month, sub_type, count(*) AS paid_som FROM (
    SELECT m.month, s.user_id, arg_max(s.sub_type, s.start_date) AS sub_type
    FROM months m JOIN s ON s.is_free = 0 AND s.covered_start <= m.month AND s.covered_end > m.month
    GROUP BY 1, 2) GROUP BY 1, 2),
ch AS (
  SELECT rule, date_trunc('month', ep_end_date)::DATE AS month, sub_type,
         count(*) FILTER (WHERE NOT (is_last AND ep_end_date + win_days > DATE '2017-03-31')) AS paid_churned,
         count(*) FILTER (WHERE is_last AND ep_end_date + win_days > DATE '2017-03-31')       AS paid_censored
  FROM ep_end WHERE has_paid = 1 GROUP BY 1, 2, 3)
SELECT c.rule, s.month, s.sub_type, s.paid_som,
       coalesce(c.paid_churned, 0) AS paid_churned, coalesce(c.paid_censored, 0) AS paid_censored,
       round(100.0 * coalesce(c.paid_churned, 0) / s.paid_som, 2) AS churn_rate_pct
FROM som s JOIN (SELECT DISTINCT rule FROM ch) r ON TRUE
LEFT JOIN ch c ON c.rule = r.rule AND c.month = s.month AND c.sub_type = s.sub_type
ORDER BY 1, 2, 3;

-- total per month: 30 days for all (rule 30) vs 3 / 30 by type (rule 0)
CREATE OR REPLACE TABLE mart_churn_mixed_window AS
SELECT month,
       sum(paid_som) FILTER (WHERE rule = 30)                                              AS paid_subscribers_som,
       sum(paid_churned) FILTER (WHERE rule = 30)                                          AS churned_30,
       sum(paid_churned) FILTER (WHERE rule = 0)                                           AS churned_3_30,
       round(100.0 * sum(paid_churned) FILTER (WHERE rule = 30) / sum(paid_som) FILTER (WHERE rule = 30), 2) AS churn_30_pct,
       round(100.0 * sum(paid_churned) FILTER (WHERE rule = 0)  / sum(paid_som) FILTER (WHERE rule = 0), 2)  AS churn_3_30_pct
FROM mart_churn_by_type GROUP BY 1 ORDER BY 1;

-- evidence: of everyone who bought again within 60 days of the plan's expiry, % back by day d
-- (renewing before expiry counts as day 0). Expiries up to 2017-01-30 so 60 days are visible.
CREATE OR REPLACE TABLE mart_return_curve AS
WITH s AS (
  SELECT user_id, start_date, end_date, period_no, is_free,
         CASE WHEN plan_days <= 31 AND is_auto_renew = 1 THEN 'Monthly · auto-renew'
              WHEN plan_days <= 31 THEN 'Monthly · manual'
              WHEN plan_days <= 100 THEN 'Quarterly · manual'
              WHEN plan_days <= 200 THEN 'Half-year · manual'
              ELSE 'Annual · manual' END AS sub_type
  FROM fct_subscription),
p AS (
  SELECT *, lead(start_date) OVER (PARTITION BY user_id ORDER BY start_date, period_no) AS next_start
  FROM s),
g AS (
  SELECT sub_type, greatest(date_diff('day', end_date, next_start), 0) AS gap
  FROM p
  WHERE is_free = 0 AND next_start IS NOT NULL AND end_date <= DATE '2017-01-30'
    AND date_diff('day', end_date, next_start) <= 60)
SELECT sub_type, count(*) AS returners_60d,
       round(100.0 * count(*) FILTER (WHERE gap <= 1)  / count(*), 1) AS back_by_day_1,
       round(100.0 * count(*) FILTER (WHERE gap <= 3)  / count(*), 1) AS back_by_day_3,
       round(100.0 * count(*) FILTER (WHERE gap <= 7)  / count(*), 1) AS back_by_day_7,
       round(100.0 * count(*) FILTER (WHERE gap <= 14) / count(*), 1) AS back_by_day_14,
       round(100.0 * count(*) FILTER (WHERE gap <= 30) / count(*), 1) AS back_by_day_30,
       round(100.0 * count(*) FILTER (WHERE gap <= 45) / count(*), 1) AS back_by_day_45
FROM g GROUP BY 1 ORDER BY 1;

-- Validation: rule 30 totals must equal mart_churn_windows (08) at 30 days
SELECT m.month, m.churned_30, w.paid_churned AS churned_08, m.paid_subscribers_som, w.paid_subscribers_som AS som_08,
       m.churn_30_pct, m.churn_3_30_pct
FROM mart_churn_mixed_window m JOIN mart_churn_windows w ON w.month = m.month AND w.window_days = 30
ORDER BY 1;
