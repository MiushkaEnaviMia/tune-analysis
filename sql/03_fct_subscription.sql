-- 03_fct_subscription.sql
-- Part 1b, step 2: subscription periods and episodes.
-- Input : stg_transactions
-- Output: fct_subscription  one row per SUBSCRIPTION PERIOD
--
-- Grain choice. One row per purchase (a non-cancel event with plan days > 0), plus the cancels
-- that follow it before the next purchase. Why this grain:
--   * It keeps the plan that was actually sold (30-day vs annual, price, discount, auto-renew),
--     which Q3/Q4 need and an episode grain would average away.
--   * Revenue sums exactly: every paid event is one period (stacks T24 included).
--   * Episodes (continuous membership) are carried as episode_no / episode_id on every row, so
--     the coarser grain is one GROUP BY away.
--
-- How the dates work. In this billing system expires_at is the MEMBERSHIP expiry after the event,
-- not the plan's own end: an early renewal adds its days on top of the old expiry (1,003,292 of
-- 1,047,912 early 30-day renewals expire ~30 days after the PREVIOUS expiry). So:
--   start_date      = purchase date
--   end_date        = membership expiry after the last event of the period (the purchase, or a
--                     following cancel, which can move it earlier; T15), floored at start_date
--   covered_start / covered_end = the part of the timeline this period "owns": from its purchase
--                     until the next purchase takes over (or end_date). These intervals never
--                     overlap within a user, so active-user counts can be summed safely.
--   gap_days        = start_date - previous period's end_date (negative = renewed early)
-- Episode rule: a new episode starts when gap_days > 30, the brief's churn window (a user who buys
-- again within 30 days of expiry is "retained"), so episodes and the churn labels agree by design.

CREATE OR REPLACE TABLE fct_subscription AS
WITH
ev0 AS (  -- every event, tagged with the purchase it belongs to (cancels attach to the previous purchase)
  SELECT *,
         sum(is_purchase) OVER (PARTITION BY user_id ORDER BY event_seq
                                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS period_no_raw,
         min(transacted_date) FILTER (WHERE is_purchase = 1) OVER (PARTITION BY user_id) AS first_purchase_date
  FROM stg_transactions
  WHERE is_purchase = 1 OR is_cancel = 1),          -- T13 zero-plan non-cancel rows create no period

ev AS (
  -- Same-day rule exception: the same-day order puts a cancel BEFORE a purchase (a cancel + new plan
  -- on one day is a plan switch, 1a T8). On the user's FIRST purchase day there is no earlier plan to
  -- switch from, so that cancel can only refer to the purchase itself (5,866 rows; 4,761 move the
  -- expiry back to the purchase day = bought and cancelled the same day). Attach it to period 1.
  -- Cancels on earlier days with no purchase before them (pre-2015 plans we never see) stay orphans.
  SELECT *,
         CASE WHEN period_no_raw = 0 AND is_cancel = 1 AND transacted_date = first_purchase_date THEN 1
              ELSE period_no_raw END AS period_no
  FROM ev0),

grp AS (  -- cancels attached to each period
  SELECT user_id, period_no,
         arg_max(expires_date, [is_cancel, event_seq])          AS last_state_expiry,   -- cancels act after the purchase they attach to   -- membership expiry after the period's last event
         count(*) FILTER (WHERE is_cancel = 1)                  AS n_cancels,
         min(transacted_date) FILTER (WHERE is_cancel = 1)      AS cancel_date
  FROM ev WHERE period_no > 0                         -- cancels before any purchase are orphans (counted in validation)
  GROUP BY 1, 2),

p AS (
  SELECT e.user_id, e.period_no, e.event_id, e.event_seq,
         e.transacted_date                                       AS start_date,
         e.expires_date                                          AS purchase_expiry_date,
         greatest(g.last_state_expiry, e.transacted_date)        AS end_date,          -- T15: cancel moves the end, floored at start
         e.plan_days_clean                                       AS plan_days,
         -- Plan tier for upgrade/downgrade: 30 vs 31 days is the same monthly product (51,028
         -- "31 -> 30" changes would otherwise read as downgrades).
         CASE WHEN e.plan_days_clean <= 10 THEN 1 WHEN e.plan_days_clean <= 45 THEN 2
              WHEN e.plan_days_clean <= 300 THEN 3 ELSE 4 END          AS plan_tier,
         e.list_price_clean                                      AS list_price,
         e.amount_paid, e.discount_amount, e.discount_pct,
         e.payment_method, e.is_auto_renew, e.is_free, e.price_type,
         (g.n_cancels > 0)::TINYINT                              AS is_cancelled,
         g.cancel_date, g.n_cancels,
         e.flag_imputed_plan, e.flag_stacked, e.flag_conflict_resolved, e.flag_expiry_far_future,
         e.src_file
  FROM ev e JOIN grp g USING (user_id, period_no)
  WHERE e.is_purchase = 1),

seq AS (
  SELECT *,
         lag(end_date)   OVER w AS prev_end_date,
         lead(start_date) OVER w AS next_start_date,
         lag(plan_days)  OVER w AS prev_plan_days,
         lag(plan_tier)  OVER w AS prev_plan_tier,
         lag(list_price) OVER w AS prev_list_price,
         lag(is_free)    OVER w AS prev_is_free
  FROM p WINDOW w AS (PARTITION BY user_id ORDER BY period_no)),

ep AS (
  SELECT *,
         date_diff('day', prev_end_date, start_date)                     AS gap_days,
         CASE WHEN prev_end_date IS NULL THEN 1
              WHEN date_diff('day', prev_end_date, start_date) > 30 THEN 1 ELSE 0 END AS is_episode_start
  FROM seq),

ep2 AS (
  SELECT *,
         sum(is_episode_start) OVER (PARTITION BY user_id ORDER BY period_no
                                     ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS episode_no
  FROM ep),

epi AS (  -- episode-level facts, repeated on each row
  SELECT user_id, episode_no,
         min(start_date)                         AS episode_start_date,
         arg_max(end_date, period_no)            AS episode_end_date,     -- state after the episode's last period
         count(*)                                AS episode_n_periods,
         max(episode_no) OVER (PARTITION BY user_id) AS user_n_episodes
  FROM ep2 GROUP BY 1, 2)

SELECT
  e.event_id                                               AS subscription_id,   -- = src_row of the purchase (lineage)
  e.user_id,
  e.period_no,
  e.user_id || ':' || e.episode_no                         AS episode_id,
  e.episode_no,
  -- dates
  e.start_date,
  e.end_date,
  e.purchase_expiry_date,
  e.start_date                                             AS covered_start,
  greatest(least(e.end_date, coalesce(e.next_start_date, e.end_date)), e.start_date) AS covered_end,
  date_diff('day', e.start_date, e.end_date)               AS membership_days,
  e.gap_days,
  -- plan and money
  e.plan_days,
  CASE e.plan_tier WHEN 1 THEN '1: trial/weekly (<=10d)' WHEN 2 THEN '2: monthly (11-45d)'
                   WHEN 3 THEN '3: multi-month (46-300d)' ELSE '4: annual (>300d)' END AS plan_tier,
  e.list_price,
  e.amount_paid,
  e.discount_amount,
  e.discount_pct,
  e.payment_method,
  e.is_auto_renew,
  e.is_free,
  e.price_type,
  -- cancellation
  e.is_cancelled,
  e.cancel_date,
  e.n_cancels,
  -- type of period
  CASE WHEN e.period_no = 1 THEN 'new'
       WHEN e.is_episode_start = 1 THEN 'reactivation'
       ELSE 'renewal' END                                  AS subscription_type,
  (e.gap_days < 0)::TINYINT                                AS is_early_renewal,
  -- change vs the previous period of the same user (any episode)
  CASE WHEN e.prev_plan_days IS NULL                       THEN 'first'
       WHEN e.prev_is_free = 1 AND e.is_free = 0           THEN 'free_to_paid'
       WHEN e.prev_is_free = 0 AND e.is_free = 1           THEN 'paid_to_free'
       WHEN e.plan_tier > e.prev_plan_tier                 THEN 'upgrade'          -- longer plan tier
       WHEN e.plan_tier < e.prev_plan_tier                 THEN 'downgrade'        -- shorter plan tier
       WHEN e.list_price > e.prev_list_price               THEN 'price_up'
       WHEN e.list_price < e.prev_list_price               THEN 'price_down'
       ELSE 'same' END                                     AS change_vs_prev,
  e.prev_plan_days,
  e.prev_list_price,
  -- episode facts
  x.episode_start_date,
  x.episode_end_date,
  x.episode_n_periods,
  (e.episode_no = x.user_n_episodes)::TINYINT              AS is_last_episode,
  -- Episode outcome. Churn = no new purchase within 30 days of the episode's end (brief's rule).
  -- The data ends 2017-03-31, so an episode ending after 2017-03-01 with no successor is unknown.
  CASE WHEN x.episode_end_date > DATE '2017-03-31'                              THEN 'active_at_data_end'
       WHEN e.episode_no < x.user_n_episodes                                     THEN 'churned_then_reactivated'
       WHEN x.episode_end_date + INTERVAL 30 DAY <= DATE '2017-03-31'             THEN 'churned'
       ELSE 'censored' END                                 AS episode_outcome,
  -- lineage / rule flags carried from stg
  e.flag_imputed_plan,
  e.flag_stacked,
  e.flag_conflict_resolved,
  e.flag_expiry_far_future,
  e.src_file
FROM ep2 e JOIN epi x USING (user_id, episode_no);

-- ---------------------------------------------------------------------------
-- Validation
-- ---------------------------------------------------------------------------
-- Expect: one row per purchase; subscription_id unique; (user_id, period_no) unique;
-- covered intervals never overlap within a user; end >= start; revenue reconciles with stg.
WITH ov AS (
  SELECT count(*) FILTER (WHERE covered_start < lag_end) AS n_overlap
  FROM (SELECT covered_start, lag(covered_end) OVER (PARTITION BY user_id ORDER BY period_no) AS lag_end
        FROM fct_subscription))
SELECT
  count(*)                                                              AS periods,
  (SELECT sum(is_purchase) FROM stg_transactions)                       AS stg_purchases,
  count(*) - count(DISTINCT subscription_id)                            AS dup_subscription_id,
  count(*) - count(DISTINCT (user_id, period_no))                       AS dup_user_period,
  (SELECT n_overlap FROM ov)                                            AS covered_overlaps,
  count(*) FILTER (WHERE end_date < start_date OR covered_end < covered_start) AS bad_intervals,
  sum(amount_paid) - (SELECT sum(amount_paid) FROM stg_transactions WHERE is_purchase = 1) AS revenue_diff,
  (SELECT count(*) FROM stg_transactions s WHERE is_cancel = 1 AND NOT EXISTS (
     SELECT 1 FROM stg_transactions q WHERE q.user_id = s.user_id AND q.is_purchase = 1
       AND (q.event_seq < s.event_seq OR q.transacted_date = s.transacted_date))) AS orphan_cancels,
  count(DISTINCT user_id)                                               AS users,
  count(DISTINCT episode_id)                                            AS episodes
FROM fct_subscription;
