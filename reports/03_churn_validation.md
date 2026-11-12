# Part 1c: Churn definition, validated against `churn_labels`

Built by `sql/06_churn_validation.sql`, which `run_all.py` runs after the clean layer (it takes under a second). It produces three tables:
`churn_mar17` (one row per user in our cohort or in the labels, with outcome and disagreement bucket), `churn_confusion` and `churn_disagreement`.
Every number below comes from those tables.

## Summary

- **On the users both sides cover and whose outcome we can see, we agree on 96.5%** (197,972 of 205,213).
- **The labels do not follow their own written definition in four systematic ways.** About 32,500 users get a different label, or are in a different cohort, because of these rules. Each one is a clear pattern, not noise:
  1. Renewing onto a **90+ day plan** in March is labelled churned (97.7% of such users).
  2. **Renewing early** is often labelled churned, although the definition says it counts as retained.
  3. The cohort looks as if it was **built from export_1 alone**, so users whose February renewal (in export_2) pushed expiry past March are still included.
  4. **Expiries on 1 March are left out** (4.8% labelled, against about 100% for 2–31 March).
- **For 10,740 users (4.8% of our cohort) the data cannot give an answer.** They had not renewed by 31 March, and their 30-day window runs into April, which we don't have.
- **Under the written definition the labels' churn rate is impossible.** On the shared users the labels say 7.4% churned. Even if every unknown user churned, the definition caps it at 5.0%. The extra 2.4 points are users with a visible March renewal that the labels call churned.
- **What this means for later parts.** We use our own implementation, applied to every month, for churn (Part 2, Part 3). We do not train on the labels. Their bias against long plans would make annual plans look worse, which is exactly the question Q4 asks.

## 1. Implementation

The definition (BRIEF.md): the cohort is users whose membership was due to expire in March 2017, based on all transactions up to and including 2017-02-28. A user has churned if there is no `is_cancel = 0` transaction between 2017-03-01 and 30 days after expiry. Renewing early counts as retained. A cancellation can move the expiry earlier.

| Choice | Our rule | Why |
|---|---|---|
| Expiry as of Feb 28 | Expiry after the user's **last** event (by `event_seq`) dated on or before 2017-02-28 | It is a state "based on all transactions up to Feb 28". We take the last event, not the maximum, because a cancel can move expiry earlier |
| Which export version | `expires_at_asof_feb`: the export_1 value where the two exports carry conflicting versions of one event (T4) | That is the version that existed as of February |
| Cohort | That expiry falls between 2017-03-01 and 2017-03-31 | Wording of the definition |
| Cancel in March | If a cancel comes before any renewal and moves the expiry earlier, the window starts from the new expiry (1,534 users) | "A cancellation can move a user's expiry date earlier" |
| What counts as a renewal | Any `is_cancel = 0` event, paid or free, any plan length | The definition's own words. Only 316 renewals are free-only |
| Window | From 2017-03-01 to effective expiry + 30 days. Early renewals in March are therefore inside it | Wording of the definition |
| Outcome | **retained**: a renewal inside the window. **churned**: no renewal, and the window closed by 2017-03-31. **unknown**: no renewal yet, and the window runs past 2017-03-31 | The data ends on 2017-03-31. We do not guess what happened in April |

Only one expiry date has a window that closes inside the data: 1 March (1 March + 30 days = 31 March). So "churned" can only be observed for 1-March expiries and for a few users whose cancel pulled expiry earlier. Everyone else who has not renewed is **unknown**.

Consistency check: our 364 churned users equal the March-2017 churn that the clean layer reports independently (`fct_user_month`, is_churned = 1 in March 2017, using the same 30-day rule).

## 2. Agreement

### Who is in the cohort

| | Users |
|---|---:|
| Labelled by billing | 241,665 |
| In our cohort | 222,018 |
| In both | 215,953 |
| Labelled only | 25,712 |
| Ours only | 6,065 |

87% of the union is in both.

### Confusion matrix (our outcome × billing label)

| Our outcome | Label: retained | Label: churned | No label | Total |
|---|---:|---:|---:|---:|
| retained | **197,877** | 7,239 | 5,798 | 210,914 |
| churned | 2 | **95** | 267 | 364 |
| unknown (window runs into April) | 2,141 | 8,599 | 0 | 10,740 |
| not in our cohort | 19,998 | 5,714 | n/a | 25,712 |

Users in both, with an outcome we can observe (205,213):

| | Label: retained | Label: churned |
|---|---:|---:|
| **Ours: retained** | 197,877 | 7,239 |
| **Ours: churned** | 2 | 95 |

- Agreement: **96.5%**.
- When we say churned, the label agrees in 95 of 97 cases.
- When we say retained, the label agrees 96.5% of the time.
- Cohen's kappa is low (about 0.02). The reason is the data, not our rule: we can observe churn for only 97 users, so almost every possible label "churned" falls into the retained row. The buckets below explain all 7,239.

### Churn rate on the shared users (215,953)

| | Churn rate |
|---|---:|
| Ours, observed churn only (lower bound) | 0.04% |
| Ours, if every "unknown" user churned (upper bound) | 5.0% |
| Billing labels | **7.4%** |

The labels are above the highest value the written definition allows. That alone shows that the labels count some visible renewals as churn.

## 3. Where and why we disagree

Each user falls into exactly one bucket (`churn_mar17.bucket`). The label churn % is the share of the bucket that billing labelled churned.

| Bucket | Users | Label churn % | What happened | Confidence in the explanation |
|---|---:|---:|---|---|
| A1 match: retained | 197,877 | 0% | | |
| A2 match: churned | 95 | 100% | | |
| **B1 unknown to us** | 10,740 | 80.1% | No renewal by 31 March. Billing had April data, we don't. This is not a disagreement, but we cannot check it | n/a |
| **C1 renewed onto a 90+ day plan** | 3,436 | 100% | Bought a 90, 180, 195, 360 or 410-day plan in March. Of all 3,516 such users, 97.7% are labelled churned. That holds whether the previous plan was long (99.9%) or 30 days (92.0%). The definition counts any non-cancel transaction | High that it is a rule in billing's code. Why, unknown |
| **C2 renewed, then cancelled in March** | 1,352 | 100% | Billing seems to treat a later cancel as undoing the renewal (84.9% of the 1,593 such users are labelled churned). The definition is ambiguous here, and we follow its literal wording | Medium. A defensible alternative reading |
| **C3 renewed on a 30-day plan, labelled churned** | 2,451 | 100% | 2,280 of them (93%) **renewed early**. Among early manual-pay renewers, 49.5% are labelled churned, against 0.3% for on-time or late manual renewers. Auto-renew: 5.0% against 0.1%. This fits billing not counting purchases made before the old expiry, which contradicts "renewing early counts as retained". The other 171 are unexplained (possibly April refunds or cancels we can't see) | Medium-high for the early-renewal pattern |
| C4 no renewal, window closed, labelled retained | 2 | 0% | Unexplained | Negligible |
| **D2 labelled, but a February renewal already pushed expiry past March** | 20,733 | 15.4% | Renewed in February, so as of 28 February they are no longer due in March. Their February renewal sits in export_2, and export_1 holds no expiry after 31 March. Seen through export_1 alone, their expiry is still in March. Every user whose export_1-only expiry falls between 2 and 31 March has a label (0 missing). So billing's cohort looks as if it was built from export_1 alone | High |
| D3 labelled, a cancel by Feb 28 moved expiry into February | 1,017 | 96.1% | Billing used the expiry from before the cancel. The definition says a cancel can move expiry earlier, so they are not due in March | High |
| D4 labelled, expired before March | 3,251 | 34.4% | Not due in March in any version of the data we have | Unexplained |
| D1 labelled, no transaction up to Feb 28 | 639 | 54.3% | Their first transaction is in March | Unexplained |
| D5 labelled, expiry after March (other) | 72 | 100% | | Unexplained |
| **E1 in our cohort, not labelled: expiry on 1 March** | 6,065 | n/a | Only 307 of the 6,372 users expiring on 1 March have a label (4.8%), against about 100% for every day from 2 to 31 March. Billing seems to treat expiry as an exclusive end date (1 March expiry = last access on 28 February), or used a "> 1 March" filter | High that it is a boundary rule. Which one, unknown |

**Explained by a clear pattern:** C1, C2, C3 (early renewals), D2, D3 and E1 cover about 34,900 users. They are differences in rules, not random errors. In nearly every case the labels drift away from the written definition.

**Unexplained:** C3 non-early, C4, D1, D4 and D5 cover about 4,100 users (1.7% of the union).

## 4. What we cannot determine from this data

1. **What happened in April.** 10,740 users (4.8% of our cohort) had not renewed by 31 March, and their window runs to the end of April. The labels say 80% of them churned. We cannot confirm or contradict that.
2. **Whether April events changed March renewals.** A refund or cancel in April could reverse a March renewal. That could explain part of C2 and C3, and we cannot see it.
3. **Billing's actual code and inputs.** Which file it read, which cutoff it used, whether expiry is inclusive, and how it treats long plans and early renewals. Our explanations are patterns in the data that fit these rules. Only billing's query can confirm them.
4. **The intended rule for "renewed, then cancelled".** The definition does not say whether a cancel after a renewal undoes it (C2, 1,352 users).
5. **What `expires_at` means exactly.** It could be the last day of access or the first day without access. This decides whether 1-March expiries belong in a "March" cohort (E1, 6,065 users).
6. **Why D1 and D4 users are labelled at all** (3,890 users). No record we have puts them in the March cohort.

## 5. Decisions for the rest of the analysis

- **Churn in Part 2 and Part 3 uses our implementation**, the same 30-day rule applied to every month (`fct_user_month`). It is independent of the labels, follows the written definition, and gives a trend rather than one cohort.
- **The labels are not used as a training target.** Their errors are not random. C1 marks almost every buyer of a long plan as churned, which would bias "should we push annual plans" (Q4) against annual plans. C3 penalises early renewers, who are among the most engaged users.
- **Questions for billing:** the five open points in section 4, above all the C1 rule and the 1-March boundary.

## Reproduce

```bash
python run_all.py                 # rebuilds everything, including sql/06_churn_validation.sql
python query.py                   # then, for example:
#   SELECT * FROM churn_confusion;
#   SELECT * FROM churn_disagreement;
#   SELECT * FROM churn_mar17 WHERE bucket LIKE 'C1%' LIMIT 20;
```
