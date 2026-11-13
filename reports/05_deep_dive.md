# Part 3 · Deep dive (a): what drives churn

**Bottom line.** Churn is about *how people pay* and *how new they are*, not who they are.
Auto-renew and the first renewal matter most. Age, city and channel look important, but most of
their gap disappears once we compare people with the same auto-renew setting and plan length.

SQL: `sql/09_deep_dive.sql` → `mart_renewal_decisions`, `mart_churn_drivers`,
`mart_churn_factor_summary`, `mart_churn_plan_monthly`, `mart_churn_method_quarter`.
Site: Part 3 tab (`#p3a`, `#p3a-act`).

**Main churn rule on the site (added 2026-11-13).** The site now counts churn with 3 days for monthly
Auto-renew plans and 30 days for plans paid by hand (98.5% of Auto-renew users who come back are back
by day 3). `sql/13_churn_rule_3_30.sql` rebuilds the same tables with the suffix `_3d`. With that rule:
churn per renewal 5.1% (4.6% below); Pays by hand 20.1% vs Auto-renew 2.8%; first renewal 17.1% vs
4.2% after a year; gaps with the same auto-renew and plan mix: payment method 5.2×, auto-renew 3.9×,
tenure 2.8×, channel 1.8×, city 1.7×, plan length 1.6×, age 1.3×; the three moves keep up to ~16,000 a
year (~3,000 + ~5,000 + ~7,900). The numbers below use 30 days for all; the site has a toggle for both.

## How we measured

| | |
|---|---|
| Unit | One **paid renewal that came due**: a paid subscription period whose expiry falls 2016-01-01 … 2017-03-01 (3,035,012 rows) |
| Churned | No new purchase (`is_cancel = 0`, paid or free) within 30 days of expiry, the brief's rule. Early renewal = stayed |
| Why 2016+ | 2015 has imputed plan lengths and users first seen in Jan-2015 have unknown tenure |
| Why ≤ 2017-03-01 | Later expiries are censored: the 30-day window runs past 2017-03-31 |
| Left out | Free-trial periods (their end is a conversion, not a renewal). `is_cancel` is not a driver: cancelling *is* churning |
| Billing incident | Payment method 39, expiries before 2016-07-01: 39,323 renewals. Lost ~16k users in Mar-2016, 97% back by Jul-2016 (Part 2). Kept in the table, left out of the ranking |
| Base after that | 2,995,689 renewals, **4.6%** churn |

**Fair comparison (confounding check).** Indirect standardisation on the two contract terms that
set churn mechanically: auto-renew (on/off) × plan length. For each group:
`adjusted = observed churn ÷ expected churn × 4.6%`, where expected uses each renewal's stratum
rate. For auto-renew itself we hold plan length fixed, and for plan length we hold auto-renew fixed.
"Gap" = highest ÷ lowest group, groups with ≥ 10,000 renewals.

## Which factors matter

| Factor | Gap as it looks | Gap, fair comparison | Verdict |
|---|---:|---:|---|
| Auto-renew | 8.9× | **4.5×** | Real. Off 20.1%, on 2.3% |
| Payment method | 27.0× | **4.4×** | Mostly auto-renew; a real residual between providers (method 40 4.3% vs 41 1.9%, both 100% auto-renew) |
| Tenure | 7.7× | **3.5×** | Real. First renewal 16.5% (8.7% even with auto-renew) vs ~4% later |
| Acquisition channel | 8.2× | 2.1× | Mostly mix: channel 7 is 99% auto-renew, channel 4 38% |
| City | 3.6× | 1.7× | Mostly mix; city 1 looks like a default value (empty profiles) |
| Plan length | 7.5× | 1.6× | Misleading per renewal (see below) |
| Age band | 3.9× | **1.3×** | Confounded: young users churn more only because fewer use auto-renew (33–54% vs 84–90%) |

**Plan length.** Every long plan is paid manually. Among manual payers a 12-month plan loses
30.7% at renewal but renews once a year: **2.7% per month** of cover vs **18.5%** on manual 30-day
plans (2-10 months: 26.4% per renewal, 5.4% per month). Self-selection (committed users pick annual)
means this is not proof annual plans retain; that is the Part 5a test.

**Payment method 39 by quarter.** 47.0% (Q1-16), 83.7% (Q2-16), then 4.2%, 1.7%, 1.5%; other
auto-renew methods 1.5–3.6%; manual payers 18.7–21.4% every quarter. One incident, not a trend.

## What we would act on

1. **Move manual payers to auto-renew.** They are 13% of renewals but 57% of churn. Each 10% moved keeps
   ~3,000 subscribers a year, assuming they churn half as much as today (not as little as current
   auto-renew users). Confidence: medium (self-selection). Would change our mind: a default-on test
   with no churn drop, or more refunds/complaints.
2. **Win the first renewal.** 16.5% vs ~4% later. Cutting first-renewal churn by a quarter keeps ~400 a
   month (~4,800 a year). Confidence: medium. Would change our mind: first-month leavers are discount or
   trial hunters who never meant to stay.
3. **Monitor failed payments per provider daily.** Method 39 lost 16,468 users in one month; method 40
   still churns 2.3× method 41 among auto-renew users (~460 extra lost a month, ~5,500 a year).
   Confidence: medium-high for the incident, medium for method 40. Would change our mind: billing logs
   showing deliberate cancellations.

Together: up to ~13,000 subscribers a year if each lands as estimated (~4% of the 303,000 paying base).
Monthly volumes = renewals in the 14-month window ÷ 14.

**Not worth acting on:** age targeting (1.3×), city or channel targeting (1.7–2.1×, driven by
empty profiles), discouraging long plans (they lose far less per month).

## Limits

- Observational: patterns, not proven causes. Auto-renew users may be more committed to begin with.
- No usage data, so we cannot tell lost interest from a failed card.
- Age and gender are missing for about two thirds of users; city 1 looks like a default.
- Tenure counts from the first paid date seen in the data; pre-2015 payers look newer than they are.
- March-2017 expiries are excluded (censored).
