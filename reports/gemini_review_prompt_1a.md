# Prompt for Gemini: critical review of Part 1a data-quality findings

Copy everything below the line into Gemini.

---

You are a senior data analyst reviewing someone else's data-quality report. Be critical and specific. Do not praise. If you cannot verify a claim without the data, say so explicitly rather than guessing.

## 1. Context

Tune is a language-learning app with a premium subscription (30-day, multi-month and annual plans, several payment providers, free trials, price tests, discounts). Leadership asks four questions:

- **Q1** How healthy is the subscriber base, and how is it trending?
- **Q2** What drives churn?
- **Q3** Did the free trials and price points work?
- **Q4** Should we push annual plans harder?

The task (Part 1a) is: profile the four files; for each issue state what it is and the query that finds it, its size (rows, users, %), why it matters, and the decision; then **rank issues by how much they affect the answers to Q1-Q4**. Part 1b (next step) builds a clean layer: `dim_user` (one row per user) and a subscription-period table. Part 1c re-implements the churn definition and compares it with the labels.

**Data ends on 2017-03-31.** No transactions after that date exist.

### Files

| File | Rows |
|:---:|:---:|
| users.csv | 1,691,575 |
| transactions_export_1.csv | 5,371,076 |
| transactions_export_2.csv | 356,266 |
| churn_labels.csv | 241,665 |

**users.csv** (user registry): `user_id`, `city` (code), `age` (self-reported), `gender` (self-reported), `acquisition_channel` (code), `registered_at` (YYYYMMDD).

**transactions_export_1.csv / transactions_export_2.csv** (one row per billing event, same columns; how they overlap is undocumented): `user_id`, `payment_method` (code), `payment_plan_days`, `list_price`, `amount_paid` (local currency), `is_auto_renew` (1 = auto-renew), `transacted_at` (YYYYMMDD), `expires_at` (membership expiry after this transaction, YYYYMMDD), `is_cancel` (1 = user cancelled in this transaction).

**churn_labels.csv**: `user_id`, `is_churn`. Billing's definition: the labels cover users whose membership was due to expire in March 2017, based on all transactions up to and including 2017-02-28. A user is churned (`is_churn = 1`) if they make no new subscription transaction (`is_cancel = 0`) between 2017-03-01 and 30 days after their membership expiry. Renewing early counts as retained. A cancellation can move a user's expiry date earlier.

### Loaded tables (DuckDB)

Both exports were loaded into one table `raw_transactions` with two added columns: `src_file` (1 or 2, which export the row came from) and `src_row` (stable row ID for tracing and tie-breaking).

| Table | Rows | Users |
|:---:|:---:|:---:|
| users | 1,691,575 | 1,691,575 |
| transactions (export_1 + export_2) | 5,727,342 | 605,802 |
| churn_labels | 241,665 | 241,665 |

Check IDs: the letter is the table (T = transactions, U = users, L = churn_labels); the number is only the check's position in the SQL file.

Severity scale used: **Critical** = ignoring it makes the headline answers wrong; **High** = materially distorts at least one leadership question; **Medium** = distorts a specific cut or the churn definition; **Low** = small or narrow, handled with a simple rule and a flag.

## 2. The 20 ranked issues

| Rank | Severity | Checks (rows) | Issue | Rows | Users | % rows | % users | Questions | Decision |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 1 | Critical | T2 (89,728), T1 (0), T3 (15,731) | The two exports are split on `expires_at`, not on `transacted_at`: export_1 has only rows expiring <= 2017-03-31; export_2 has every row expiring later (266,538 March-2017 purchases + 89,728 purchases from 2015-Feb 2017). 10,228 of the 10,291 410-day plans bought Aug 2016-Feb 2017 sit in export_2. | 89,728 | 65,306 | 1.57% | 10.78% | Q1, Q4 | UNION both exports; keep src_file/src_row; ask billing for one export with an event ID and updated_at. |
| 2 | High | T9 (214,207) | `payment_plan_days` = 0 and `list_price` = 0 on paid rows, Mar-Oct 2015 only (194,047 rows paid 149). 86.4% end 25-35 days after purchase; the 1,031 rows paid 1,788 run a median 413 days. | 214,207 | 122,393 | 3.74% | 20.2% | Q1, Q3, Q4 | Plan days = expires_at - transacted_at snapped to 7/30/90/180/365/410 (price lookup fallback for 1,698 rows with negative gaps); list_price = amount_paid; flag is_imputed_plan. |
| 3 | High | T11 (79,575) | Non-cancel rows with list_price > 0 and amount_paid = 0 (free trials / 100% discounts), unlabelled. | 79,575 | 77,570 | 1.39% | 12.8% | Q1, Q3 | Keep, flag is_free = 1; split every subscriber metric into paid and free. |
| 4 | High | T23 (697,306), L5 (27,606) | Transacting users missing from users.csv. 71.7M revenue (8.3% of 862.6M); only 53,023 of the 109,330 ever paid. 27,606 labelled users also missing. | 697,306 | 109,330 | 12.18% | 18.05% | Q1, Q2 | dim_user from the union of all user_ids; is_in_users = 0; attributes 'Unknown'; never inner join. |
| 5 | High | U11 (1,137,655), U1 (1,135,039), U2 (72), U3 (240), U4 (2,304) | Age missing (0) or implausible (min -6,807, max 1,820). Valid range used: 10-80. | 1,137,655 | 1,137,655 | 67.25% | 67.25% | Q2 | Age outside 10-80 = NULL; age_band with 'Unknown'; no imputation. |
| 6 | Medium | T12 (163,152), T13 (3,204) | Non-cancel rows with list_price = 0 and amount_paid = 0; 84% are payment_method 35 with a 7-day plan (looks like a trial product). | 163,152 | 143,834 | 2.85% | 23.74% | Q1, Q3 | Keep, is_free = 1 plus a trial type; 0-day rows create no subscription period. |
| 7 | Medium | T15 (37,811), T14 (222,448) | Cancel rows with expires_at < transacted_at (documented: a cancel moves expiry earlier). | 37,811 | 33,702 | 0.66% | 5.56% | Q1, Q2 | Cancel row sets the period's effective end (floored at period start); is_cancelled = 1. |
| 8 | Medium | T8 (151,025) | (user_id, transacted_at) is not unique within a file. | 151,025 | 55,809 | 2.64% | 9.21% | Q3, Q4 | Deduplicate on the full row only; same-day order: cancel, purchase, expiry, src_row. |
| 9 | Medium | T24 (36,464) | Stacked purchases: same user + day + event core repeated in one file, each copy pushing expires_at further. | 36,464 | 9,104 | 0.64% | 1.5% | Q1, Q4 | Keep every row as a purchase; period end = latest expiry in the stack. |
| 10 | Medium | L6 (26,126), L7 (6,061), L4 (639) | Labels don't match a naive 'due in March' population (users whose last transaction up to 2017-02-28 expires in March 2017): 26,126 labelled but not in it, 6,061 in it but unlabelled, 639 labelled with no transaction by 2017-02-28. | 26,126 | 26,126 | 10.81% | 10.81% | Q2 | Implement the definition independently in 1c; report and explain disagreement buckets. |
| 11 | Medium | U5 (1,106,850) | Gender missing. | 1,106,850 | 1,106,850 | 65.43% | 65.43% | Q2 | gender = 'unknown', reported as its own segment. |
| 12 | Low | T4 (747) | Same event in both exports with conflicting expires_at / is_auto_renew. | 747 | 741 | 0.01% | 0.12% | Q1 | export_2 version wins; export_1 expiry kept as expires_at_asof_feb. |
| 13 | Low | T17 (457) | expires_at = 1970-01-01 (placeholder for missing). | 457 | 456 | 0.01% | 0.08% | Q1 | NULL, derive from plan days, flag. |
| 14 | Low | T16 (1,287) | expires_at < transacted_at on a non-cancel row. | 1,287 | 448 | 0.02% | 0.07% | Q1 | Derive expiry from plan days, flag. |
| 15 | Low | T18 (2,020) | expires_at before 2015 (2007-2014). | 2,020 | 1,835 | 0.04% | 0.3% | Q1 | Cancels kept (they set the effective end); 207 non-cancel rows get a derived expiry. |
| 16 | Low | T19 (1,738) | expires_at more than 2 years after data end (up to 2026). | 1,738 | 200 | 0.03% | 0.03% | Q1 | Keep raw value, flag. |
| 17 | Low | T7 (832) | Exact duplicate rows within export_1. | 832 | 755 | 0.01% | 0.12% | Q1 | Drop copies; keep lowest src_row. |
| 18 | Low | T6 (1,780) | Different events of the same user and day split across the two exports. | 1,780 | 853 | 0.03% | 0.14% | Q4 | Keep both; sequence with the same-day rule. |
| 19 | Low | U7 (13,756), U8 (26) | registered_at after data end, or after the user's first transaction. | 13,756 | 13,756 | 0.81% | 0.81% | Q2, Q3 | Keep with flag; exclude from conversion; tenure_start = least(registered_at, first transaction). |
| 20 | Low | T10 (13) | amount_paid > list_price (list_price > 0). | 13 | 13 | 0.0% | 0.0% | Q3 | Floor discount at 0; flag. |

Checks that passed (0 rows): T5 identical cross-file duplicates, T21 invalid dates, T22 transactions after data end, U6 invalid registration date, U9 duplicate user_id, L1 duplicate label, L2 invalid is_churn, L3 labelled user with no transactions. Info only: T20 31,082 rows with expires_at = 2017-03-31 (read as a month-end billing anchor, not a cap); U10 1,195,103 registered users with no transactions; L8 21,647 labels with is_churn = 1.

## 3. Corrections and new findings since your last review

1. **Correction to your earlier claim.** You described the users missing from users.csv as paying users. Only **53,023 of the 109,330** ever paid; the rest have only free or zero-paid rows.
2. **New finding on issue #4.** In churn_labels, the 27,606 users missing from users.csv churn at **5.2%**, against **9.4%** for the 214,059 who are in users.csv. So the missing users are not a random subset, and an inner join to users would bias the churn rate and the Q2 driver analysis. We now think issue #4 should arguably move from rank #4 to **rank #2** (still below #1, because #1 loses rows even without any join, while #4 hurts only when someone joins to users). A rough count also puts them at about 10% of users whose latest non-cancel expiry is on or after 2017-03-31 (29,688 of 296,330; this ignores cancellations, so treat it as approximate).

## 4. What we want from you

1. **Challenge each severity rank.** For every issue, say whether the rank and severity are right, too high or too low, and why, using the definition "how much the answer to Q1-Q4 changes if the issue is ignored or handled naively". Say whether you agree with moving #4 to #2.
2. **Missed issues.** What would you check that is not in the list? (For example: plan changes and overlapping periods, payment_method or price anomalies, label leakage, time-zone or date-boundary effects, users whose label contradicts their transactions.) For each, give the SQL you would run.
3. **Decisions: data loss or bias.** For each decision, does it lose rows, invent values, or bias any of Q1-Q4? Propose a better alternative only if it is realistic for a 4-5 hour take-home.
4. **Flag what you cannot verify.** You do not have the data. Anything you cannot confirm from the numbers above must be marked "cannot verify without data", not stated as fact.

### Output format

Answer in English, as one table per section, with these columns:

| # | Issue / claim | Your assessment | Evidence (from the numbers above, or "cannot verify without data") | Suggested SQL check (DuckDB, on `raw_transactions`, `raw_users`, `raw_churn_labels`) |
|:---:|:---:|:---:|:---:|:---:|

Then finish with: (a) your proposed final top-5 ranking with one line of reasoning each, and (b) at most 5 missed issues, most important first. Keep it concise; no general advice about data quality.
