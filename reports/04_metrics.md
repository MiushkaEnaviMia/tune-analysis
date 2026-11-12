# Part 2 · Core metrics (monthly, Jan 2015 – Mar 2017)

Built by `sql/08_metrics.sql` from `fct_user_month` and `fct_subscription` (Part 1b).
Output tables: `mart_metrics_month` (one row per month) and `mart_churn_windows` (month × churn window 30 / 32 / 45 days).
Churn is our own rule from 1b/1c, not billing's `churn_labels.csv`.

## Definitions

| Metric | Precise definition |
|---|---|
| **Paying subscriber** (month m) | User with ≥ 1 day of **paid** access in m (`fct_user_month.is_active_paid = 1`). Free-trial and unpriced free days don't count. |
| Active user (any) | ≥ 1 day of any access in m, free included (`is_active = 1`). Shown only for contrast. |
| **New** | Paying subscriber whose first-ever episode starts in m (`is_new = 1`). |
| **Reactivated** | Paying subscriber whose later episode starts in m: came back > 30 days after the previous expiry (`is_reactivated = 1`). |
| **Renewing** | Every other paying subscriber: renewed, or still inside a multi-month / annual plan. New + reactivated + renewing = paying subscribers (checked). |
| **Paid churn** (window W) | A membership episode with ≥ 1 paid period ends in m (expiry date in m) and the user makes no new purchase within W days. W = 30 (brief's rule) is the main figure; 32 and 45 are checks. Episodes that were only free trials are counted separately (`free_only_churned`). |
| Censored | Episode ends in m but expiry + W runs past 2017-03-31: outcome unknown, left out of churn. |
| **Monthly churn rate** | Paid churn in m ÷ paying subscribers on the first day of m. |
| Cash revenue | `amount_paid` of purchases made in m. |
| **Recognised revenue** | Each paid purchase spread evenly over its plan days; the part that falls in m. An annual plan counts ~1/12 per month instead of all upfront. |
| **ARPU** | Recognised revenue ÷ paying subscribers. Cash ARPU kept as a check. |
| **Discount depth** | Over **paid** purchases made in m: `sum(discount_amount) ÷ sum(list_price)`, plus the % of paid purchases with any discount. Free trials (100% off) are counted as free starts, not inside depth. |

## Results

| | 2015 (Feb–Dec) | 2016 | 2017 (Jan–Feb) |
|---|---:|---:|---:|
| Paying subscribers (monthly average) | 190,510 | 265,631 | 300,758 |
| New, % of paying subscribers | 6.9% | 3.9% | 2.9% |
| Reactivated, % of paying subscribers | 1.9% | 2.3% | 1.9% |
| Monthly churn rate (30-day, average) | 5.2% | 5.0% | 3.6% |
| ARPU (recognised, average) | 133.4 | 122.6 | 119.6 |

- **Active subscribers:** 131,441 paying in Jan 2015 → 302,950 in Mar 2017 (+130%). Year on year, Mar 2016 → Mar 2017: +19% (254,318 → 302,950), down from +52% the year before. Growth is real but slowing.
- **New vs renewing vs reactivated:** renewing users are 94–96% of the base since 2016. New paying users fell from 3.9% of the base (2016) to 2.9% (2017); 2015's 6.9% is overstated by the warm-up (see below). In absolute terms 122,110 new paying users in 2016, about 8,600 a month in 2017.
- **Monthly churn:** typically 3–5%. Feb 2015 – Feb 2016 averages 4.5% (without Apr 2015); Apr 2016 – Feb 2017 averages 3.9%; the last 6 months 3.1–4.6%. The 32- and 45-day windows move the level by 0.1–0.5 points, except December (see below).
- **ARPU:** 114–141 a month, slowly down from ~133 (2015) to ~120 (2017). Monthly recognised revenue grew from 27.0M (Aug 2015) to 40.4M (Mar 2017). Annual plans are 10.7% of all revenue, so cash and recognised ARPU stay close.
- **Discounts:** in Jan 2015 9.7% of paid purchases had a discount (~20% off, 1.6% of list price overall). Discounts stopped by Oct 2015 and have been ~0.1% of purchases since. Promotion moved to free trials: 42,743 free starts in Jun 2015 and 58,821 in Oct–Nov 2016.

## What we don't trust, and why

| Series / month | Problem | Evidence | What we did |
|---|---|---|---|
| Jan 2015 (all series) | Warm-up month: purchases before 2015 are not in the files, so every Jan-2015 user looks "new" and start-of-month subscribers are only 5,152. | `new_pct` = 100%, churn rate 28.7% | Excluded from trends; series start Feb 2015. |
| "New" Feb–Mar 2015 (7.6%, 16.4%) | Same warm-up: users on plans bought before 2015 look new at their first 2015 purchase, so the 2015 new share is overstated. | Mar 2015: 27,285 "new" paying users, 2.5× any later month | Read the drop in new users from 2016 on, not from 2015. |
| Churn Apr 2015 (13.9%) | A billing gap, not churn: 17,435 auto-renew users all expire on 2015-04-30, plans imputed (98%), and 99.5% buy again in Jun 2015. | Same users = the Jun 2015 reactivation spike (10.2%) | Flagged; read the underlying level as ~4%. |
| Churn Mar 2016 (13.8%) | Provider-specific gap: payment method 39 lost 16,468 auto-renew users (normal month: ~670); 97% came back in Jul 2016. | Same users = the Jul 2016 reactivation spike (9.3%) | Flagged; likely involuntary (payment failure). Ask billing. |
| Churn Dec 2015, Dec 2016 | Window-sensitive: many December expiries renew on day 31–32. 30-day churn 5.2% / 4.6% drops to 3.8% / 3.2% with 32 days. | `mart_churn_windows` | Report 30-day (brief's rule), note the 32-day level. |
| Churn Mar 2017 | Censored: the 30-day window needs April data. | 14,396 censored episodes | Not reported. The 45-day check is also censored for Feb 2017 (1.6%). |
| Mar–Oct 2015 revenue, ARPU, discount | 214,207 paid rows had plan length and list price filled from a price lookup (1a, T9). | 1a issue #2 | Use, with lower confidence. |
| "Active users" incl. free | Free-trial waves (Jun 2015, Oct–Nov 2016) inflate it by up to 46,000. | `active_any` vs `paying_subscribers` | Headline uses paying subscribers. |
| 30-day churn vs `fct_user_month` | Counts differ by < 1% (5% in Dec 2015) because here episodes are rebuilt with a running membership end. | Validation query in `08_metrics.sql` | Accepted; both shown in SQL. |

Note: `run_all.py` does not yet run `sql/08_metrics.sql`; run it after `05`.
