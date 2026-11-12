# 5a · Annual-plan promotion test

**Question from Growth:** should we offer 30-day subscribers a discounted annual plan when their subscription comes up for renewal?

**Bottom line:** one month of renewals is enough to run the test (about 117,000 users per group). The annual cash comes in on day 1, so the first months will always look good. The real answer comes at month 12 (revenue) and month 13 (do annual buyers renew?).

## 1. Hypothesis

Offering "12 months for the price of 10" at renewal raises **12-month net revenue per subscriber**, mainly by locking in people who pay by hand, half of whom are gone within a year.

The risk is the opposite: auto-renew users already stay, so the discount could just hand money back to loyal users.

## 2. Baselines from our data

All numbers come from `fct_subscription` (clean layer, Part 1b). "Eligible" = a paid 30-day period (30 or 31 days, not free) reaching its expiry date.

| Baseline | All | Auto-renew | Pays by hand |
|:--|:--:|:--:|:--:|
| Eligible subscribers per month (Oct 2016 – Jan 2017) | 233,800 | 210,200 (89.9%) | 23,600 (10.1%) |
| Renew within 30 days of expiry (same months) | 96.3% | 97.9% | 82.0% |
| Switch to an annual plan today, with no offer (2016) | 0.13% | - | 0.7% |
| 12-month revenue per subscriber (Q1 2016 group, 225,158 users) | 1,318 | 1,361 | 1,097 |
| Standard deviation of that revenue | 607 | 562 | 762 |
| Still paying 12 months later | 74.9% | 79.9% | 49.3% |

Other facts that shape the design:

- **Annual plans renew at 69.0%** at the end of the plan (20,981 annual periods ending Jan 2016 – Jan 2017). That is our only prior for "annual retention".
- **Prices differ:** in January 2017, 46.9% of 30-day subscribers paid 149 and 39.4% paid 99. Today's annual list price (1,788 for 410 days) is a deal for a 149 payer but costs 50% more than 12 months at 99. So the offer must be priced **from each user's own monthly price**, not from the list price.
- Only **0.3%** of annual purchases since 2016 were cancelled (baseline for the refund guardrail).

## 3. Design

| Item | Choice | Why |
|:--|:--|:--|
| Unit | **User** (`user_id`), assigned once and kept for the whole test | A user renews every month; assigning each renewal would mix both offers for one person. |
| Eligible | Paid 30-day subscriber, 7 days before expiry, no future period already bought, not on a free trial | These are the people Growth wants to reach, at the moment they decide. |
| Split | 50 / 50, balanced within auto-renew vs pays by hand and within price (99 / 149 / other) | The two payer types behave very differently; each needs a fair comparison. |
| Control | Normal renewal | |
| Treatment | Annual plan, 12 months for the price of 10 of their current monthly price (about 17% off) | One clear offer. Several prices would multiply the sample size. |

## 4. Metrics

**Primary: 12-month net revenue per assigned user.** Everyone assigned counts, whether they took the offer or not. This is the only fair way to compare: the people who take an annual plan are the most loyal, so comparing takers with non-takers would flatter the offer.

**Secondary:** annual take-up (today 0.13%); paid days in the next 12 months.

**Guardrails (stop or rethink if they move the wrong way):**

| Guardrail | Baseline | What it protects |
|:--|:--:|:--|
| Renewal at the offer moment, any plan | 96.3% (pays by hand: 82.0%) | The offer must not confuse or push people away. |
| 12-month revenue of auto-renew users | 1,361 | Discounts for people who would have paid anyway. |
| Annual plans cancelled or refunded within 30 days | 0.3% | Regret buys. |

## 5. Sample size

Two-sided test, 5% false-alarm rate, 80% power, revenue standard deviations from section 2.

**Users needed per group** to detect a change in 12-month revenue of:

| Group | 1% | 2% | 3% | 5% |
|:--|:--:|:--:|:--:|:--:|
| All eligible | 33,241 | 8,310 | 3,693 | 1,330 |
| Auto-renew | 26,736 | 6,684 | 2,971 | 1,069 |
| Pays by hand | 75,641 | 18,910 | 8,405 | 3,026 |

**What one month gives us (50 / 50):** about 116,900 users per group, of whom 11,800 pay by hand.

- All users: detects a change of **0.5%** (about 7 per user).
- Auto-renew: **0.5%**.
- Pays by hand: **2.5%** (about 28 per user). This is the group that decides the test, and it sets the enrolment length.

Renewal guardrail: to see a drop from 96.3% to 95.8% needs 23,819 users per group; from 82.0% to 80.0% (pays by hand) needs 6,036. Both fit easily.

Formula: users per group = 2 × (1.96 + 0.84)² × SD² / (smallest change)².

## 6. Duration, and the "cash now, retention later" problem

An annual plan pays up front. In month 1 the treatment group will show a big revenue jump that tells us nothing yet. Monthly payers pay as they go, and annual buyers can't churn for a year.

| When | What we read | Decision |
|:--|:--|:--|
| Month 1 | Enrol: every 30-day subscriber passes renewal once | - |
| Months 1–2 | Take-up, renewal guardrail, refunds | Stop early if renewal drops |
| Month 3 | **Earned** revenue: each payment spread over the days it covers, so an annual payment counts 1/12 per month. The rest of the year is projected from the control group's own monthly survival. | Go / no-go, per payer type |
| Month 12 | **Final primary read:** actual 12-month cash for both groups | Confirm or reverse |
| Month 13–14 | Do annual buyers renew? Compare with 69.0% today | Is the annual plan good for the long run? |

Keep 10% of eligible users in a holdout with no annual offer until month 14, even if we roll out at month 3.

## 7. Analysis SQL

Runs on our clean layer plus a hypothetical `experiment_assignments(user_id, variant, assigned_at)` table.

```sql
-- One row per assigned user: offer taken, renewal guardrail, earned revenue (90 days) and cash (12 months)
with a as (
  select e.user_id, e.variant, e.assigned_at::date as d0, max(s.is_auto_renew) as is_auto_renew
  from experiment_assignments e
  left join fct_subscription s
    on s.user_id = e.user_id and e.assigned_at::date between s.start_date and s.end_date
  group by all
), u as (
  select a.user_id, a.variant, a.is_auto_renew,
    max((s.plan_days >= 360 and s.start_date between a.d0 and a.d0 + 37)::int)            as took_annual,
    max((s.is_free = 0 and s.start_date between a.d0 and a.d0 + 37)::int)                 as renewed,
    coalesce(sum(s.amount_paid) filter (where s.start_date between a.d0 and a.d0 + 364), 0) as cash_12m,
    coalesce(sum(s.amount_paid * greatest(0, least(s.end_date, a.d0 + 90) - greatest(s.start_date, a.d0))
                 / nullif(s.end_date - s.start_date, 0)), 0)                               as earned_90d
  from a left join fct_subscription s on s.user_id = a.user_id and s.start_date >= a.d0
  group by all
), g as (
  select is_auto_renew, variant, count(*) n, avg(took_annual) take_up, avg(renewed) renewal,
         avg(cash_12m) cash, var_samp(cash_12m) v, avg(earned_90d) earned_90d
  from u group by all
)
select t.is_auto_renew, t.n n_treat, c.n n_ctrl, t.take_up, c.renewal ctrl_renewal, t.renewal treat_renewal,
       t.cash - c.cash as cash_diff,
       (t.cash - c.cash) / sqrt(t.v / t.n + c.v / c.n) as z_score,   -- |z| > 1.96 = significant
       t.earned_90d - c.earned_90d as earned_90d_diff
from g t join g c on c.is_auto_renew = t.is_auto_renew and t.variant = 'treatment' and c.variant = 'control';
```

Baselines above come from these queries (DuckDB, `tune.duckdb`):

```sql
-- Monthly flow, renewal within 30 days, switch to annual (paid 30-day periods by expiry month)
with s as (
  select *, lead(start_date) over w nxt_start, lead(plan_days) over w nxt_days
  from fct_subscription window w as (partition by user_id order by start_date, period_no)
)
select date_trunc('month', end_date) m, count(distinct user_id) users,
  avg(coalesce(nxt_start <= end_date + 30, false)::int) renew,
  avg(coalesce(nxt_start <= end_date + 30 and nxt_days >= 360, false)::int) to_annual
from s where plan_days in (30, 31) and is_free = 0 and amount_paid > 0
  and end_date between date '2016-01-01' and date '2017-01-31'
group by 1 order by 1;

-- 12-month revenue per subscriber (first eligible expiry in Q1 2016)
with e as (
  select user_id, subscription_id, start_date, end_date, is_auto_renew,
    row_number() over (partition by user_id order by end_date, subscription_id) rn
  from fct_subscription where plan_days in (30, 31) and is_free = 0 and amount_paid > 0
    and end_date between date '2016-01-01' and date '2016-03-31'
)
select e.is_auto_renew, count(distinct e.user_id), avg(rev), stddev(rev) from (
  select e.user_id, e.is_auto_renew, coalesce(sum(s.amount_paid), 0) rev
  from e left join fct_subscription s on s.user_id = e.user_id and s.start_date > e.start_date
    and s.start_date <= e.end_date + 365 and s.subscription_id <> e.subscription_id
  where e.rn = 1 group by all) e
group by rollup(1);
```

## 8. Limits

- Revenue baselines come from 2016; prices and the payer mix may have moved since.
- We can't see app usage, so we can't tell whether annual buyers stay because they learn more or just because they prepaid.
- The 69.0% annual renewal comes from people who chose annual on their own. People who take a discount may renew less.
