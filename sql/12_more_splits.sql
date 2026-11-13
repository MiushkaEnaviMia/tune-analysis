-- 12_more_splits.sql
-- More breakdowns for the "Split by" selector on the site (default view stays the total).
-- Input : fct_subscription, dim_user, mart_metrics_month (08), mart_p2_splits (11)
-- Output: mart_more_splits  one row per split x month x segment, value = US dollars or count
--   revenue_by_renew    2.4 ARPU  recognised revenue (same formula as 08) by the purchase's is_auto_renew.
--                                 Adds up to 08 recognised_revenue. ARPU per group on the site =
--                                 this revenue / mart_p2_splits paying_by_renew of the same group
--   free_by_channel     2.4 trials  free-trial starts (fct_subscription.is_free = 1, month of start_date)
--                                 by dim_user.acquisition_channel (3, 4, 7, 9; rest incl. Unknown = Other).
--                                 Adds up to 08 free_starts
-- Part 3 splits (age, channel, tenure by auto-renew) come from mart_churn_factor_summary (09);
-- Part 4 paying subscribers by auto-renew reuses mart_p2_splits paying_by_renew (11)

CREATE OR REPLACE TABLE mart_more_splits AS
WITH
months AS (
  SELECT range::DATE AS month, (range + INTERVAL 1 MONTH)::DATE AS next_month
  FROM range(DATE '2015-01-01', DATE '2017-04-01', INTERVAL 1 MONTH)),

rev AS (
  SELECT 'revenue_by_renew' AS split, m.month,
         CASE WHEN s.is_auto_renew = 1 THEN 'Auto-renew' ELSE 'Manual' END AS segment,
         sum(s.amount_paid * date_diff('day', greatest(s.start_date, m.month),
                                              least(s.start_date + s.plan_days, m.next_month)) / s.plan_days) AS value
  FROM fct_subscription s JOIN months m
    ON s.amount_paid > 0 AND s.plan_days > 0
   AND s.start_date < m.next_month AND s.start_date + s.plan_days > m.month
  GROUP BY 1, 2, 3),

free AS (
  SELECT 'free_by_channel' AS split, date_trunc('month', s.start_date)::DATE AS month,
         CASE WHEN d.acquisition_channel IN ('3', '4', '7', '9') THEN 'Channel ' || d.acquisition_channel
              ELSE 'Other' END AS segment,
         count(*)::DOUBLE AS value
  FROM fct_subscription s LEFT JOIN dim_user d USING (user_id)
  WHERE s.is_free = 1
  GROUP BY 1, 2, 3)

SELECT * FROM rev UNION ALL SELECT * FROM free
ORDER BY split, month, segment;

-- check: every split adds up to the 08 totals (expect 0 bad months each)
SELECT s.split,
       count(*) FILTER (WHERE abs(s.total - CASE s.split WHEN 'revenue_by_renew' THEN m.recognised_revenue
                                                      ELSE m.free_starts END) > 1) AS bad_months
FROM (SELECT split, month, sum(value) AS total FROM mart_more_splits GROUP BY 1, 2) s
JOIN mart_metrics_month m USING (month)
GROUP BY 1 ORDER BY 1;
