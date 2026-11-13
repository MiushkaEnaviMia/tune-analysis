# Part 4 · Executive summary

For the CEO and the Head of Growth. The four leadership questions, answered as far as the data allows, three recommendations, and what we can't answer yet. Every number comes from Part 1 (data), Part 2 (metrics, `reports/04_metrics.md`) and Part 3 (churn deep dive, `reports/05_deep_dive.md`). Paying subscriber = at least one paid day in the month; churn = our 30-day rule, not `churn_labels.csv`.

Interactive version with charts: https://miushkaenavimia.github.io/tune-analysis/#p4

## Bottom line

**The subscriber base is healthy, but growth is slowing.** Paying subscribers grew +19% in the last year (from +52% the year before), and monthly churn fell to about 3.6%. The risk is fewer new payers and flat revenue per user. **Churn is about how people pay and how new they are, not who they are:** manual payers churn 20.1% per renewal vs 2.3% on auto-renew, and the first renewal loses 16.5% vs ~4% later.

| Metric | Value |
|:--|:--|
| Paying subscribers, Mar 2017 | 302,950 (+130% since Jan 2015) |
| Growth, Mar 2016 → Mar 2017 | +19% (was +52%) |
| Monthly churn, 2017 average | 3.6% (5.0% in 2016) |
| New payers per month, 2017 | 2.9% of payers (3.9% in 2016) |
| Revenue per paying user | $119 (Q1-16) → $124 (Q1-17), +4%: flat |

## The four questions

| Question | Status | Answer |
|:--|:--:|:--|
| **1 · How healthy is the base?** | Answered | Healthy, growing, but slowing. +19% paying subscribers in the last year, down from +52%. Monthly churn mostly 3–5%; 3.6% in 2017. Renewing users are 94–96% of the base; new payers fell to 2.9% a month. Revenue per paying user flat: +4% (Q1-16 → Q1-17), growth comes from more payers |
| **2 · What drives churn?** | Answered | How people pay, and how new they are. Auto-renew off 20.1% vs on 2.3% per renewal (4.5× after a fair comparison). First renewal 16.5% vs ~4% later (3.5×). Payment provider: one billing incident (Mar 2016, 16,468 users), plus a real gap, method 40 4.3% vs method 41 1.9%. Age, city and channel only look important: their gap shrinks to 1.3–2.1× once auto-renew and plan length are equal |
| **3 · Did free trials and prices work?** | Partly | We see what changed, not whether it paid off. Discounts stopped by Oct 2015 (9.7% of paid purchases → about 0.1%). Promotion moved to free trials: 42,743 free starts in Jun 2015, 58,821 in Oct–Nov 2016. Not measured: our deep dive chose churn drivers (option a), so the trial and price analysis (option b) is not done |
| **4 · Push annual plans harder?** | Partly | Promising, but test before pushing. Per month of cover, manual annual plans lose 2.7% vs 18.5% on manual 30-day plans, but committed users pick annual plans, so this is not proof: that is the Part 5a test. Annual plans are 10.7% of revenue; do not judge them on billing's labels (97.7% of 90+ day renewals wrongly "churned") |

Gap between the highest- and lowest-churn group, as it looks and after comparing people with the same auto-renew setting and plan length:

| Factor | Gap as it looks | Gap after a fair comparison |
|:--|:--:|:--:|
| Auto-renew | 8.9× | 4.5× |
| Payment method | 27.0× | 4.4× |
| Tenure (1st renewal) | 7.7× | 3.5× |
| Channel | 8.2× | 2.1× |
| City | 3.6× | 1.7× |
| Plan length | 7.5× | 1.6× |
| Age band | 3.9× | 1.3× |

## Three recommendations

Together: up to ~13,000 subscribers kept a year (~4% of the 303,000 paying base), if each lands as estimated.

| # | Recommendation | Expected impact | Confidence | What would change our mind |
|:--:|:--|:--|:--|:--|
| 1 | **Move manual payers to auto-renew.** Make auto-renew the default at checkout and offer it at every manual renewal. Manual payers are 13% of renewals but 57% of churn | Each 10% of manual payers moved keeps ~3,000 subscribers a year (assuming they churn half as much as today) | Medium: auto-renew users may be more committed to begin with | A default-on test with no churn drop, or more refunds and complaints |
| 2 | **Win the first renewal.** Focus onboarding and reminders on the first month: 16.5% leave at the first renewal vs ~4% later (8.7% even with auto-renew) | Cutting first-renewal churn by a quarter keeps ~400 a month (~4,800 a year) | Medium: the pattern holds after a fair comparison (3.5×); no usage data to explain why | First-month leavers turn out to be discount or trial hunters who never meant to stay |
| 3 | **Catch payment failures before they become churn.** Monitor failed auto-renew payments by provider every day, retry failed charges, and ask lapsed users to update their payment method | Avoids a repeat of Mar 2016 (16,468 users, 7.0% of paying subscribers); closing the method 40 vs 41 gap keeps ~5,500 a year | Medium-high for the incident (one provider, 97% came back); medium for method 40 | Billing logs showing deliberate cancellations or a planned provider migration |

Not worth acting on: targeting by age (1.3×), city or channel (1.7–2.1×), or discouraging long plans. Before any churn review, use our validated 30-day rule, not `churn_labels.csv` (13.4% of labels wrong).

## What we can't answer yet

| Question | Status | What is missing | What it would take |
|:--|:--:|:--|:--|
| 1 · Health of the base | Answered | March 2017 churn: the 30-day window needs April data | April 2017 transactions |
| 2 · What drives churn | Answered | Patterns, not proven causes; no usage data, so we can't tell lost interest from a failed card | App usage data; billing's reason codes for failed payments; a default auto-renew test |
| 3 · Free trials and prices | Partly | Whether trials created extra paying users, and how price relates to renewal. Our deep dive chose churn drivers (option a) instead | The free-trial and price analysis (option b): trial waves vs similar months; next time, a group that gets no trial |
| 4 · Annual plans | Partly | Annual plans look better per month, but committed users choose them; true retention shows only after 12 months | The annual-plan test (Part 5a) with a 12-month follow-up |
| All questions | Limit | 109,330 users in the transactions are missing from `users.csv` (8.3% of revenue); no channel or city for them | A full user export from the registry |
| All questions | Limit | 10,740 users in the March 2017 churn check have no outcome yet | April 2017 transactions |
