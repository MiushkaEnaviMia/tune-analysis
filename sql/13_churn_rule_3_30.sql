-- 13_churn_rule_3_30.sql
-- Part 3 (a) again with the site's main churn rule: a renewal counts as churn when there is no new
-- purchase within 3 days of expiry for monthly auto-renew plans (plan_days <= 31, is_auto_renew = 1)
-- and within 30 days for every plan paid by hand. Same rule as mart_churn_by_type rule 0 (sql/10).
-- Why 3 days: 98.5% of auto-renew users who come back are back by day 3, only 0.3% more by day 7.
-- Input : fct_subscription, dim_user
-- Output: the same five tables as 09_deep_dive.sql, with the suffix _3d. 09 (30 days for all) stays as
--         the side check, so the site can switch between the two rules.

CREATE OR REPLACE TABLE mart_renewal_decisions_3d AS
WITH p AS (
  SELECT s.*,
         lead(start_date) OVER (PARTITION BY user_id ORDER BY period_no) AS next_start
  FROM fct_subscription s)
SELECT
  p.user_id, p.subscription_id, p.end_date, p.plan_days, p.payment_method, p.is_auto_renew,
  CASE p.plan_tier WHEN '1: trial/weekly (<=10d)'  THEN '1-10 days'
                   WHEN '2: monthly (11-45d)'      THEN '30 days'
                   WHEN '3: multi-month (46-300d)' THEN '2-10 months'
                   ELSE '12+ months' END                                       AS plan_length,
  (p.next_start IS NULL OR p.next_start > p.end_date
     + CASE WHEN p.plan_days <= 31 AND p.is_auto_renew = 1 THEN 3 ELSE 30 END)::INT AS is_churn,
  date_diff('month', u.first_paid_date, p.end_date)                           AS tenure_months,
  coalesce(u.acquisition_channel, 'Unknown')                                  AS acquisition_channel,
  coalesce(u.age_band, 'Unknown')                                             AS age_band,
  u.city, u.is_in_users,
  -- Known billing incident (Part 2, "What we don't trust"): method 39 lost ~16k auto-renew users in
  -- Mar 2016 and 97% came back by Jul 2016. That is a payment failure, not a customer decision,
  -- so it is kept in the table but left out of the driver ranking (shown separately).
  (p.payment_method = 39 AND p.end_date < DATE '2016-07-01')::INT              AS is_billing_incident
FROM p LEFT JOIN dim_user u USING (user_id)
WHERE p.is_free = 0
  AND p.end_date BETWEEN DATE '2016-01-01' AND DATE '2017-03-01';

CREATE OR REPLACE TABLE mart_churn_drivers_3d AS
WITH
d AS (SELECT * FROM mart_renewal_decisions_3d WHERE is_billing_incident = 0),
top_pm   AS (SELECT payment_method FROM d GROUP BY 1 ORDER BY count(*) DESC LIMIT 10),
top_city AS (SELECT city FROM d WHERE city IS NOT NULL GROUP BY 1 ORDER BY count(*) DESC LIMIT 10),
d2 AS (
  SELECT d.*, (tp.payment_method IS NOT NULL) AS is_top_pm, (tc.city IS NOT NULL) AS is_top_city
  FROM d LEFT JOIN top_pm tp USING (payment_method) LEFT JOIN top_city tc USING (city)),
f AS (  -- one row per decision per factor
  SELECT *, 'Auto-renew' AS factor, CASE WHEN is_auto_renew = 1 THEN 'On' ELSE 'Off' END AS segment,
         is_auto_renew::INT AS seg_order FROM d2
  UNION ALL
  SELECT *, 'Plan length', plan_length,
         CASE plan_length WHEN '1-10 days' THEN 1 WHEN '30 days' THEN 2 WHEN '2-10 months' THEN 3 ELSE 4 END FROM d2
  UNION ALL
  SELECT *, 'Payment method', CASE WHEN is_top_pm THEN 'Method ' || payment_method ELSE 'Other' END, 0 FROM d2
  UNION ALL
  SELECT *, 'Acquisition channel',
         CASE WHEN is_in_users IS DISTINCT FROM 1 THEN 'Not in users.csv'
              WHEN acquisition_channel IN ('3','4','7','9') THEN 'Channel ' || acquisition_channel
              ELSE 'Other' END, 0 FROM d2
  UNION ALL
  SELECT *, 'Age band', age_band,
         CASE age_band WHEN '4-17' THEN 1 WHEN '18-24' THEN 2 WHEN '25-34' THEN 3
                       WHEN '35-44' THEN 4 WHEN '45-92' THEN 5 ELSE 6 END FROM d2
  UNION ALL
  SELECT *, 'City', CASE WHEN is_in_users IS DISTINCT FROM 1 THEN 'Not in users.csv'
                         WHEN is_top_city THEN 'City ' || city ELSE 'Other' END, 0 FROM d2
  UNION ALL
  SELECT *, 'Tenure',
         CASE WHEN tenure_months <= 1  THEN '0-1 months'  WHEN tenure_months <= 3  THEN '2-3 months'
              WHEN tenure_months <= 6  THEN '4-6 months'  WHEN tenure_months <= 12 THEN '7-12 months'
              WHEN tenure_months <= 24 THEN '13-24 months' ELSE '25+ months' END,
         CASE WHEN tenure_months <= 1 THEN 1 WHEN tenure_months <= 3 THEN 2 WHEN tenure_months <= 6 THEN 3
              WHEN tenure_months <= 12 THEN 4 WHEN tenure_months <= 24 THEN 5 ELSE 6 END FROM d2),
fs AS (  -- adjustment stratum: auto-renew x plan length, minus the factor itself
  SELECT *, CASE factor WHEN 'Auto-renew'  THEN plan_length
                        WHEN 'Plan length' THEN is_auto_renew::VARCHAR
                        ELSE is_auto_renew || '|' || plan_length END AS stratum
  FROM f),
st AS (SELECT factor, stratum, avg(is_churn) AS stratum_rate FROM fs GROUP BY 1, 2),
overall AS (SELECT avg(is_churn) AS rate FROM d)
SELECT
  f.factor, f.segment, min(f.seg_order)                                 AS seg_order,
  count(*)                                                              AS decisions,
  sum(f.is_churn)                                                       AS churned,
  round(100 * avg(f.is_churn), 2)                                       AS churn_pct,
  round(100 * avg(f.is_auto_renew), 1)                                  AS auto_renew_pct,
  round(100 * avg(st.stratum_rate), 2)                                  AS expected_pct,
  round(100 * avg(f.is_churn) / avg(st.stratum_rate) * (SELECT rate FROM overall), 2) AS adjusted_pct,
  round(100 * avg(f.is_churn) FILTER (WHERE f.is_auto_renew = 1), 2)    AS churn_pct_auto_on,
  round(100 * avg(f.is_churn) FILTER (WHERE f.is_auto_renew = 0), 2)    AS churn_pct_auto_off
FROM fs f JOIN st USING (factor, stratum)
GROUP BY 1, 2;

CREATE OR REPLACE TABLE mart_churn_factor_summary_3d AS
SELECT factor,
       count(*)                                                    AS segments,
       round(max(churn_pct)    / min(churn_pct), 1)                AS raw_spread_x,
       round(max(adjusted_pct) / min(adjusted_pct), 1)             AS adjusted_spread_x,
       arg_max(segment, churn_pct)                                 AS worst_segment_raw,
       arg_min(segment, churn_pct)                                 AS best_segment_raw,
       arg_max(segment, adjusted_pct)                              AS worst_segment_adj,
       arg_min(segment, adjusted_pct)                              AS best_segment_adj
FROM mart_churn_drivers_3d
WHERE decisions >= 10000
GROUP BY 1;

-- Payment method by quarter: is a method's churn steady, or one incident?
CREATE OR REPLACE TABLE mart_churn_method_quarter_3d AS
SELECT date_trunc('quarter', end_date)::DATE                                  AS quarter,
       CASE WHEN payment_method = 39 THEN 'Method 39'
            WHEN is_auto_renew = 1   THEN 'Other auto-renew'
            ELSE 'Manual (auto-renew off)' END                                AS grp,
       count(*)                                                               AS decisions,
       round(100 * avg(is_churn), 1)                                          AS churn_pct
FROM mart_renewal_decisions_3d
GROUP BY 1, 2;

-- Plan length is a special case: every long plan is manual (auto-renew off), and one decision on a
-- 12-month plan covers 12 months. So compare manual payers only, and also per month of cover:
-- monthly-equivalent churn = 1 - (1 - churn per decision) ^ (30 / plan days).
CREATE OR REPLACE TABLE mart_churn_plan_monthly_3d AS
SELECT plan_length,
       count(*)                                                                     AS decisions,
       round(avg(plan_days))                                                        AS avg_plan_days,
       round(100 * avg(is_churn), 1)                                                AS churn_per_decision_pct,
       round(100 * (1 - pow(1 - avg(is_churn), 30.0 / avg(plan_days))), 1)          AS churn_per_month_pct
FROM mart_renewal_decisions_3d
WHERE is_auto_renew = 0 AND plan_length <> '1-10 days' AND is_billing_incident = 0
GROUP BY 1;

-- ---------------------------------------------------------------------------
-- Validation / headline
-- ---------------------------------------------------------------------------
-- Expect ~3.0M decisions, ~5% churn; every factor's decisions add up to the same total.
SELECT (SELECT count(*) FROM mart_renewal_decisions_3d)                         AS decisions,
       (SELECT sum(is_billing_incident) FROM mart_renewal_decisions_3d)         AS incident_decisions,
       (SELECT round(100 * avg(is_churn), 2) FROM mart_renewal_decisions_3d
         WHERE is_billing_incident = 0)                                      AS churn_pct_ex_incident,
       (SELECT count(DISTINCT sum_dec) FROM (SELECT sum(decisions) AS sum_dec
          FROM mart_churn_drivers_3d GROUP BY factor))                          AS distinct_factor_totals;
