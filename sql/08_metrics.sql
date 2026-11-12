-- 08_metrics.sql
-- Part 2: core monthly metrics, Jan-2015 .. Mar-2017.
-- Input : fct_user_month, fct_subscription
-- Output: mart_metrics_month   one row per calendar month (27 rows)
--         mart_churn_windows   one row per month x churn window (30 / 32 / 45 days)
--
-- Definitions (also in reports/04_metrics.md)
--   paying subscriber (month m)  user with >= 1 day of PAID access in m (fct_user_month.is_active_paid).
--                                Free-trial / unpriced free days do not count.
--   new                          paying subscriber whose first-ever episode starts in m
--   reactivated                  paying subscriber whose later episode starts in m (came back > 30 days
--                                after the previous expiry)
--   renewing                     every other paying subscriber (carried over: renewed, or still inside a plan)
--   paid churn (window W)        a membership episode that contained >= 1 paid period ends in m (its expiry
--                                date falls in m) and the user makes no new purchase within W days.
--                                W = 30 is the brief's rule (main), 32 and 45 are sensitivity checks.
--   censored                     the episode ends in m but expiry + W runs past 2017-03-31: outcome unknown
--   monthly churn rate           paid churn in m / paying subscribers on the first day of m
--   cash revenue                 amount_paid of purchases made in m
--   recognised revenue           amount_paid spread evenly over the plan's days ([start, start + plan_days)),
--                                the part that falls in m (annual plans count 1/12 per month, not all upfront)
--   ARPU                         recognised revenue / paying subscribers (cash ARPU kept as a check)
--   discount depth               discount_amount / list_price over PAID purchases made in m,
--                                free trials (100% off) are counted separately as free starts

CREATE OR REPLACE TABLE mart_churn_windows AS
WITH
w AS (SELECT unnest([30, 32, 45]) AS win),
p AS (  -- every period in time order, with the running membership end and the next purchase
  SELECT user_id, start_date, end_date, is_free,
         max(end_date) OVER (PARTITION BY user_id ORDER BY start_date, period_no
                             ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS run_end,
         lead(start_date) OVER (PARTITION BY user_id ORDER BY start_date, period_no) AS next_start,
         row_number()     OVER (PARTITION BY user_id ORDER BY start_date, period_no) AS rn
  FROM fct_subscription),
pw AS (  -- an episode ends after a period when the next purchase is more than W days after the membership end
  SELECT p.*, w.win,
         (next_start IS NULL OR date_diff('day', run_end, next_start) > w.win) AS ends_here
  FROM p CROSS JOIN w),
ep AS (  -- episode number per user and window
  SELECT *,
         coalesce(sum(ends_here::INT) OVER (PARTITION BY user_id, win ORDER BY rn
                                            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS ep_no
  FROM pw),
ep_end AS (
  SELECT user_id, win, ep_no,
         max(run_end)                             AS ep_end_date,
         max((is_free = 0)::INT)                  AS has_paid,
         bool_or(ends_here AND next_start IS NULL) AS is_last
  FROM ep GROUP BY 1, 2, 3),
months AS (
  SELECT range::DATE AS month FROM range(DATE '2015-01-01', DATE '2017-04-01', INTERVAL 1 MONTH)),
som AS (  -- paying subscribers on the first day of the month
  SELECT m.month, count(DISTINCT s.user_id) AS paid_som
  FROM months m JOIN fct_subscription s
    ON s.is_free = 0 AND s.covered_start <= m.month AND s.covered_end > m.month
  GROUP BY 1)
SELECT m.month, w.win AS window_days,
       coalesce(s.paid_som, 0)                                                         AS paid_subscribers_som,
       count(e.user_id) FILTER (WHERE e.has_paid = 1 AND NOT (e.is_last AND e.ep_end_date + w.win > DATE '2017-03-31')) AS paid_churned,
       count(e.user_id) FILTER (WHERE e.has_paid = 1 AND e.is_last AND e.ep_end_date + w.win > DATE '2017-03-31')       AS paid_censored,
       count(e.user_id) FILTER (WHERE e.has_paid = 0 AND NOT (e.is_last AND e.ep_end_date + w.win > DATE '2017-03-31')) AS free_only_churned,
       round(100.0 * paid_churned / nullif(coalesce(s.paid_som, 0), 0), 2)            AS churn_rate_pct
FROM months m CROSS JOIN w
LEFT JOIN som s USING (month)
LEFT JOIN ep_end e ON e.win = w.win AND date_trunc('month', e.ep_end_date) = m.month
GROUP BY m.month, w.win, s.paid_som
ORDER BY 1, 2;


CREATE OR REPLACE TABLE mart_metrics_month AS
WITH
um AS (
  SELECT month,
         sum(is_active)                                                               AS active_any,
         sum(is_active_paid)                                                          AS paying_subscribers,
         count(*) FILTER (WHERE is_active_paid = 1 AND is_new = 1)                    AS new_paid,
         count(*) FILTER (WHERE is_active_paid = 1 AND is_new = 0 AND is_reactivated = 1) AS reactivated_paid,
         count(*) FILTER (WHERE is_active_paid = 1 AND is_new = 0 AND is_reactivated = 0) AS renewing_paid,
         sum(amount_paid)                                                             AS cash_revenue
  FROM fct_user_month GROUP BY 1),
buy AS (  -- purchases made in the month
  SELECT date_trunc('month', start_date)::DATE AS month,
         count(*) FILTER (WHERE is_free = 0)                                AS paid_purchases,
         count(*) FILTER (WHERE is_free = 0 AND discount_amount > 0)        AS discounted_purchases,
         sum(list_price) FILTER (WHERE is_free = 0)                         AS paid_list_price,
         sum(discount_amount) FILTER (WHERE is_free = 0)                    AS paid_discount,
         count(*) FILTER (WHERE is_free = 1)                                AS free_starts,
         count(*) FILTER (WHERE is_free = 0 AND plan_days > 300)            AS annual_purchases
  FROM fct_subscription GROUP BY 1),
months AS (
  SELECT range::DATE AS month, (range + INTERVAL 1 MONTH)::DATE AS next_month
  FROM range(DATE '2015-01-01', DATE '2017-04-01', INTERVAL 1 MONTH)),
rec AS (  -- recognised revenue: each paid purchase spread evenly over its plan days
  SELECT m.month,
         sum(s.amount_paid * date_diff('day', greatest(s.start_date, m.month),
                                              least(s.start_date + s.plan_days, m.next_month)) / s.plan_days) AS recognised_revenue
  FROM fct_subscription s JOIN months m
    ON s.amount_paid > 0 AND s.plan_days > 0
   AND s.start_date < m.next_month AND s.start_date + s.plan_days > m.month
  GROUP BY 1),
ch AS (SELECT * FROM mart_churn_windows WHERE window_days = 30)
SELECT um.month,
       um.active_any, um.paying_subscribers, ch.paid_subscribers_som,
       um.new_paid, um.reactivated_paid, um.renewing_paid,
       round(100.0 * um.new_paid         / um.paying_subscribers, 2) AS new_pct,
       round(100.0 * um.reactivated_paid / um.paying_subscribers, 2) AS reactivated_pct,
       round(100.0 * um.renewing_paid    / um.paying_subscribers, 2) AS renewing_pct,
       ch.paid_churned, ch.paid_censored, ch.free_only_churned, ch.churn_rate_pct,
       um.cash_revenue, round(r.recognised_revenue)                  AS recognised_revenue,
       round(r.recognised_revenue / um.paying_subscribers, 2)        AS arpu,
       round(um.cash_revenue / um.paying_subscribers, 2)             AS arpu_cash,
       b.paid_purchases, b.discounted_purchases, b.annual_purchases, b.free_starts,
       round(100.0 * b.discounted_purchases / b.paid_purchases, 2)   AS discounted_pct,
       round(100.0 * b.paid_discount / b.paid_list_price, 2)         AS discount_depth_pct
FROM um
JOIN ch  USING (month)
JOIN buy b USING (month)
JOIN rec r USING (month)
ORDER BY month;

-- ---------------------------------------------------------------------------
-- Validation
-- ---------------------------------------------------------------------------
-- Expect: 27 months, new + reactivated + renewing = paying subscribers, cash revenue reconciles with
-- fct_subscription, recognised revenue <= cash revenue overall (the tail of 2017 plans falls after March).
SELECT count(*)                                                                  AS months,
       count(*) FILTER (WHERE new_paid + reactivated_paid + renewing_paid <> paying_subscribers) AS bad_split,
       sum(cash_revenue) - (SELECT sum(amount_paid) FROM fct_subscription
                            WHERE start_date >= DATE '2015-01-01')               AS cash_diff,
       sum(recognised_revenue)                                                   AS recognised_total,
       sum(cash_revenue)                                                         AS cash_total
FROM mart_metrics_month;

-- 30-day churn here vs fct_user_month.is_churned (built from the episodes in 03) should be close,
-- fct_user_month also counts free-only episodes.
SELECT c.month, c.paid_churned + c.free_only_churned AS churned_here, u.churned_fum
FROM mart_churn_windows c
JOIN (SELECT month, sum(is_churned) AS churned_fum FROM fct_user_month GROUP BY 1) u USING (month)
WHERE c.window_days = 30 ORDER BY 1;
