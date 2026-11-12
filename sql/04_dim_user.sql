-- 04_dim_user.sql
-- Part 1b, step 3: one row per user.
-- Input : raw_users, raw_churn_labels, stg_transactions, fct_subscription
-- Output: dim_user
-- Grain : one user_id that appears ANYWHERE (users.csv OR transactions OR churn labels).
--   Why not users.csv only: 109,330 transacting users (18% of them) are missing from the registry
--   (T23) and labelled users missing from it churn less (L5: 5.2% vs 9.4%). An inner join would
--   silently drop them and bias churn drivers (Q2). They are kept with is_in_users = 0 and
--   'Unknown' attributes.
-- Built after fct_subscription because the derived fields (first plan, episodes) come from it.

CREATE OR REPLACE TABLE dim_user AS
WITH
ids AS (
  SELECT user_id FROM raw_users
  UNION SELECT user_id FROM stg_transactions
  UNION SELECT user_id FROM raw_churn_labels),

tx AS (   -- event-level facts (all events, incl. cancels and zero-plan rows)
  SELECT user_id,
         min(transacted_date)                                   AS first_tx_date,
         max(transacted_date)                                   AS last_tx_date,
         count(*)                                               AS n_events,
         count(*) FILTER (WHERE is_cancel = 1)                  AS n_cancels,
         -- "last transaction" uses the deterministic event_seq (same-day rule in 02)
         arg_max(is_auto_renew, event_seq)                      AS last_is_auto_renew,
         arg_max(payment_method, event_seq)                     AS last_payment_method
  FROM stg_transactions GROUP BY 1),

sub AS (  -- subscription facts
  SELECT user_id,
         count(*)                                               AS n_periods,
         count(*) FILTER (WHERE is_free = 0)                    AS n_paid_periods,
         count(*) FILTER (WHERE is_free = 1)                    AS n_free_periods,
         max(episode_no)                                        AS n_episodes,
         sum(amount_paid)                                       AS lifetime_paid,
         sum(discount_amount)                                   AS lifetime_discount,
         min(start_date)                                        AS first_period_date,
         min(start_date) FILTER (WHERE is_free = 0)             AS first_paid_date,
         arg_min(plan_days, period_no)                          AS first_plan_days,
         arg_min(plan_tier, period_no)                          AS first_plan_tier,
         arg_min(price_type, period_no)                         AS first_price_type,
         arg_min(payment_method, period_no)                     AS first_payment_method,
         arg_min(is_auto_renew, period_no)                      AS first_is_auto_renew,
         arg_min(plan_days, period_no)  FILTER (WHERE is_free = 0) AS first_paid_plan_days,
         arg_min(list_price, period_no) FILTER (WHERE is_free = 0) AS first_paid_list_price,
         arg_min(amount_paid, period_no) FILTER (WHERE is_free = 0) AS first_paid_amount,
         max(plan_tier)                                         AS max_plan_tier,
         arg_max(end_date, period_no)                           AS current_end_date,
         arg_max(episode_outcome, period_no)                    AS last_episode_outcome
  FROM fct_subscription GROUP BY 1)

SELECT
  i.user_id,
  -- presence flags
  (u.user_id IS NOT NULL)::TINYINT                              AS is_in_users,       -- T23 / L5
  (tx.user_id IS NOT NULL)::TINYINT                             AS has_transactions,
  (l.user_id IS NOT NULL)::TINYINT                              AS has_churn_label,
  -- registry attributes, cleaned
  u.city,
  coalesce(u.acquisition_channel::VARCHAR, 'Unknown')           AS acquisition_channel,
  u.age                                                         AS age_raw,
  CASE WHEN u.age BETWEEN 4 AND 92 THEN u.age END               AS age,                    -- U11: outside 4-92 -> NULL (U1-U4)
  CASE WHEN u.age BETWEEN 4 AND 17  THEN '4-17'
       WHEN u.age BETWEEN 18 AND 24 THEN '18-24'
       WHEN u.age BETWEEN 25 AND 34 THEN '25-34'
       WHEN u.age BETWEEN 35 AND 44 THEN '35-44'
       WHEN u.age BETWEEN 45 AND 92 THEN '45-92'
       ELSE 'Unknown' END                                       AS age_band,
  coalesce(u.gender, 'unknown')                                 AS gender,                 -- U5: own segment, no imputation
  strptime(u.registered_at::VARCHAR, '%Y%m%d')::DATE            AS registered_date,
  (u.registered_at > 20170331)::TINYINT                         AS flag_registered_after_data_end,   -- U7
  (strptime(u.registered_at::VARCHAR, '%Y%m%d')::DATE > tx.first_tx_date)::TINYINT
                                                                AS flag_registered_after_first_tx,   -- U8
  -- tenure: starts at the earlier of registration and first transaction (U8 safe)
  least(strptime(u.registered_at::VARCHAR, '%Y%m%d')::DATE, tx.first_tx_date) AS tenure_start_date,
  -- transaction-derived fields
  tx.first_tx_date,
  tx.last_tx_date,
  tx.n_events,
  tx.n_cancels,
  tx.last_is_auto_renew,
  tx.last_payment_method,
  sub.first_period_date,
  sub.first_paid_date,
  date_diff('day', strptime(u.registered_at::VARCHAR, '%Y%m%d')::DATE, sub.first_paid_date) AS days_registration_to_first_paid,
  sub.first_plan_days,
  sub.first_plan_tier,
  sub.first_price_type,
  sub.first_payment_method,
  sub.first_is_auto_renew,
  sub.first_paid_plan_days,
  sub.first_paid_list_price,
  sub.first_paid_amount,
  coalesce(sub.n_periods, 0)                                    AS n_periods,
  coalesce(sub.n_paid_periods, 0)                               AS n_paid_periods,
  coalesce(sub.n_free_periods, 0)                               AS n_free_periods,
  coalesce(sub.n_episodes, 0)                                   AS n_episodes,
  coalesce(sub.lifetime_paid, 0)                                AS lifetime_paid,
  coalesce(sub.lifetime_discount, 0)                            AS lifetime_discount,
  (coalesce(sub.n_paid_periods, 0) > 0)::TINYINT                AS is_payer,
  (coalesce(sub.n_free_periods, 0) > 0)::TINYINT                AS is_trial_user,          -- had any free period (T11/T12)
  (sub.first_price_type <> 'paid')::TINYINT                     AS started_free,
  (sub.max_plan_tier = '4: annual (>300d)')::TINYINT            AS ever_annual,
  -- Left-censoring: the data starts 2015-01-01, so a user whose first period is in Jan 2015 may
  -- have subscribed earlier. Their "new" status and tenure are lower bounds.
  (sub.first_period_date < DATE '2015-02-01')::TINYINT          AS flag_first_seen_jan2015,
  sub.current_end_date,
  CASE WHEN sub.user_id IS NULL                                   THEN 'never_subscribed'
       WHEN sub.last_episode_outcome = 'active_at_data_end'       THEN 'active'
       WHEN sub.last_episode_outcome = 'censored'                 THEN 'lapsing_unknown'
       ELSE 'churned' END                                       AS status_at_data_end,
  -- tenure in days, from first period to the end of the last one (capped at data end)
  date_diff('day', sub.first_period_date, least(sub.current_end_date, DATE '2017-03-31')) AS subscribed_span_days
FROM ids i
LEFT JOIN raw_users u        USING (user_id)
LEFT JOIN raw_churn_labels l USING (user_id)
LEFT JOIN tx                 USING (user_id)
LEFT JOIN sub                USING (user_id);

-- ---------------------------------------------------------------------------
-- Validation
-- ---------------------------------------------------------------------------
-- Expect: user_id unique; every registry, transaction and label user present.
SELECT
  count(*)                                                                    AS users,
  count(*) - count(DISTINCT user_id)                                          AS dup_user_id,
  count(*) FILTER (WHERE is_in_users = 1)                                AS n_in_users,
  count(*) FILTER (WHERE is_in_users = 0)                                AS n_not_in_users,
  count(*) FILTER (WHERE has_transactions = 1)                                AS with_transactions,
  count(*) FILTER (WHERE has_churn_label = 1)                                 AS with_label,
  (SELECT count(*) FROM raw_users)        - count(*) FILTER (WHERE is_in_users = 1) AS registry_missing,
  (SELECT count(*) FROM raw_churn_labels) - count(*) FILTER (WHERE has_churn_label = 1)  AS labels_missing,
  count(*) FILTER (WHERE age IS NULL AND is_in_users = 1)                AS registry_age_null,
  count(*) FILTER (WHERE is_payer = 1)                                        AS payers
FROM dim_user;
