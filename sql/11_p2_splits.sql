-- 11_p2_splits.sql
-- Part 2: one breakdown per tab, for the "Split by" selector on the site (default view stays the total).
-- Input : fct_user_month, fct_subscription, dim_user, mart_metrics_month (08)
-- Output: mart_p2_splits  one row per split x month x segment, value = count of users or US dollars
--   paying_by_renew   2.1  paying subscribers (fct_user_month.is_active_paid = 1) by is_auto_renew of the
--                          paid plan they hold in the month (latest start if several). Adds up to 08 paying_subscribers
--   new_by_channel    2.2  New paying subscribers (is_active_paid = 1 AND is_new = 1) by dim_user.acquisition_channel
--                          (3, 4, 7, 9; everything else incl. Unknown = Other). Adds up to 08 new_paid
--   revenue_by_plan   2.4  recognised revenue (same formula as 08: each paid purchase spread over its plan days)
--                          by plan length: Monthly (<= 45 days), Multi-month (46-300), Annual (> 300). Adds up to 08

CREATE OR REPLACE TABLE mart_p2_splits AS
WITH
months AS (
  SELECT range::DATE AS month, (range + INTERVAL 1 MONTH)::DATE AS next_month
  FROM range(DATE '2015-01-01', DATE '2017-04-01', INTERVAL 1 MONTH)),

paid_plan AS (  -- the paid plan each user holds in a month (latest start)
  SELECT s.user_id, m.month, arg_max(s.is_auto_renew, s.covered_start) AS is_auto_renew
  FROM fct_subscription s
  JOIN months m ON s.covered_start < m.next_month AND s.covered_end > m.month
  WHERE s.is_free = 0 AND s.covered_end > s.covered_start
  GROUP BY 1, 2),

renew AS (
  SELECT 'paying_by_renew' AS split, um.month,
         CASE WHEN p.is_auto_renew = 1 THEN 'Auto-renew' ELSE 'Manual' END AS segment,
         count(*)::DOUBLE AS value
  FROM fct_user_month um LEFT JOIN paid_plan p USING (user_id, month)
  WHERE um.is_active_paid = 1
  GROUP BY 1, 2, 3),

channel AS (
  SELECT 'new_by_channel' AS split, um.month,
         CASE WHEN d.acquisition_channel IN ('3', '4', '7', '9') THEN 'Channel ' || d.acquisition_channel
              ELSE 'Other' END AS segment,
         count(*)::DOUBLE AS value
  FROM fct_user_month um LEFT JOIN dim_user d USING (user_id)
  WHERE um.is_active_paid = 1 AND um.is_new = 1
  GROUP BY 1, 2, 3),

plan AS (
  SELECT 'revenue_by_plan' AS split, m.month,
         CASE WHEN s.plan_days <= 45 THEN 'Monthly' WHEN s.plan_days <= 300 THEN 'Multi-month' ELSE 'Annual' END AS segment,
         sum(s.amount_paid * date_diff('day', greatest(s.start_date, m.month),
                                              least(s.start_date + s.plan_days, m.next_month)) / s.plan_days) AS value
  FROM fct_subscription s JOIN months m
    ON s.amount_paid > 0 AND s.plan_days > 0
   AND s.start_date < m.next_month AND s.start_date + s.plan_days > m.month
  GROUP BY 1, 2, 3)

SELECT * FROM renew UNION ALL SELECT * FROM channel UNION ALL SELECT * FROM plan
ORDER BY split, month, segment;

-- check: every split adds up to the 08 totals (expect 0 bad months each)
SELECT s.split,
       count(*) FILTER (WHERE abs(s.total - CASE s.split WHEN 'paying_by_renew' THEN m.paying_subscribers
                                                      WHEN 'new_by_channel'  THEN m.new_paid
                                                      ELSE m.recognised_revenue END) > 1) AS bad_months
FROM (SELECT split, month, sum(value) AS total FROM mart_p2_splits GROUP BY 1, 2) s
JOIN mart_metrics_month m USING (month)
GROUP BY 1 ORDER BY 1;
