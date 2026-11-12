# Tune subscription analysis (take-home)

Raw billing exports (Jan 2015 – Mar 2017) are checked, cleaned and rebuilt as a tested data model in DuckDB,
then used to answer four leadership questions:

- **Q1** How healthy is the subscriber base, and how is it trending?
- **Q2** What drives churn?
- **Q3** Did the free trials and price points work?
- **Q4** Should we push annual plans harder?

**Live site:** https://miushkaenavimia.github.io/tune-analysis/ — one tab per part of the brief, and SQL on every table
(broken and clean) right in the browser.

## Run it end to end

Requirements: Python 3.9+ and two packages.

```bash
pip install duckdb openpyxl        # or: pip install -r requirements.txt
```

1. Put the four delivered CSVs in `data/` at the repository root:
   `data/users.csv`, `data/transactions_export_1.csv`, `data/transactions_export_2.csv`, `data/churn_labels.csv`.
2. From the repository root run:

```bash
python run_all.py
```

`run_all.py` runs every `sql/NN_*.sql` file in order into `tune.duckdb` (created next to it; about 1 GB, ~20 s),
then every `py/NN_*.py` file, which writes the Part 1a reports into `reports/`.
All paths are relative to the repository root. The raw CSVs and the database are not in the repository.

Optional:
- `python query.py` opens the database read-only and lets you type SQL (`tables` lists the tables).
- `python py/build_site_data.py` re-exports the tables to Parquet for the website (writes `site/data/` and
  `site/catalog.json`; on GitHub those site files sit at the repository root).

## What gets built

| Script | Builds | One row is |
|---|---|---|
| `sql/00_load_raw.sql` | `raw_users`, `raw_transactions_export_1`, `raw_transactions_export_2`, `raw_churn_labels` | a row of the CSV, exactly as delivered (one table per file) |
| `sql/00_union_exports.sql` | `base_transactions` | a row of either export, values unchanged, plus `src_file` / `src_row` lineage |
| `sql/01_data_quality.sql` | `dq_summary`, `dq_examples_*`, `dq_export_profile`, `dq_t9_by_month`, `dq_exp_0331_by_tx` | one data-quality check / example row |
| `sql/02_stg_transactions.sql` | `ref_price_plan`, `stg_transactions` | a price point; a real billing event (deduplicated, conflicts resolved) |
| `sql/02_stg_users.sql` | `stg_users` | a row of users.csv, cleaned (age 4-92 else NULL, gender 'unknown', typed dates) |
| `sql/03_fct_subscription.sql` | `fct_subscription` | a subscription period (a purchase and the cancels that follow it) |
| `sql/04_dim_user.sql` | `dim_user` | a user seen anywhere (registry, transactions or labels) |
| `sql/05_fct_user_month.sql` | `fct_user_month` | a user in a calendar month with access, a payment or a churn |
| `sql/06_churn_validation.sql` | `churn_mar17`, `churn_confusion`, `churn_disagreement` | a user in the March-2017 churn cohort or labelled; one outcome × label cell; one disagreement group |
| `sql/07_fct_cohort.sql` | `fct_cohort` | a start-month cohort in one month since its start |
| `sql/08_metrics.sql` | `mart_metrics_month`, `mart_churn_windows` | a calendar month; a month × churn window |
| `sql/09_deep_dive.sql` | `mart_renewal_decisions`, `mart_churn_drivers`, `mart_churn_factor_summary`, `mart_churn_method_quarter`, `mart_churn_plan_monthly` | Part 3 churn-driver tables |
| `py/01_dq_outputs.py` | `reports/01_data_quality.{md,xlsx,html}`, `reports/01_dq_*.csv` | Part 1a report, generated from `dq_summary` |

Each SQL file starts with a header that states its input, output, grain and the rules it applies.

## Where each part of the brief lives

Every part has a tab on the [live site](https://miushkaenavimia.github.io/tune-analysis/) and a write-up in `reports/`.

| Part | Site tab | Report | Code |
|---|---|---|---|
| 1a · Data-quality report | [1a](https://miushkaenavimia.github.io/tune-analysis/#dq) | `reports/01_data_quality.md` (also `.xlsx`, `.html`) | `sql/01_data_quality.sql`, `py/01_dq_outputs.py` |
| 1b · Clean layer and data model | [1b.1 map](https://miushkaenavimia.github.io/tune-analysis/#lineage), [1b.2 SQL explorer](https://miushkaenavimia.github.io/tune-analysis/#explorer) | `reports/02_data_model.md` | `sql/00`–`sql/05`, `sql/07` |
| 1c · Churn definition, validated | [1c](https://miushkaenavimia.github.io/tune-analysis/#churn) | `reports/03_churn_validation.md` | `sql/06_churn_validation.sql` |
| 2 · Core metrics | [Part 2](https://miushkaenavimia.github.io/tune-analysis/#p2-active) | `reports/04_metrics.md` | `sql/08_metrics.sql` |
| 3 · Deep dive: churn drivers | [Part 3](https://miushkaenavimia.github.io/tune-analysis/#p3a) | `reports/05_deep_dive.md` | `sql/09_deep_dive.sql` |
| 4 · Answers and three recommendations | [Part 4](https://miushkaenavimia.github.io/tune-analysis/#p4) | on the site | built on Parts 1-3 |
| 5a · Experiment design | [5a](https://miushkaenavimia.github.io/tune-analysis/#p5a) | `reports/06_ab_test.md` | |
| 5b · AI log | [5b](https://miushkaenavimia.github.io/tune-analysis/#p5b) | `reports/07_ai_log.md` | prompt example: `reports/gemini_review_prompt_1a.md` |

## Repository layout

```
README.md, requirements.txt, run_all.py, query.py
sql/        numbered build scripts (run in order)
py/         Python steps (report generator, site export, nodot.py = site text style helper)
reports/    deliverables
index.html, dq.html, catalog.json, tune_logo.png, .nojekyll, data/raw, data/clean
            the static website served by GitHub Pages; data/raw and data/clean hold Parquet exports
            of the built tables for the site, not the raw CSVs
task_status.json
            rows of the site's "Task & status" tab (status: done / partial / todo)
```

## With more time

- **Free trials and prices (Part 3 option b).** We chose churn drivers; next would be trial waves vs similar months, and how price relates to renewal.
- **April 2017 transactions.** They would close March-2017 churn and give an outcome to the 10,740 users the churn check can't judge yet.
- **A full user export.** 109,330 users in the transactions are missing from `users.csv` (8.3% of revenue), so they have no channel, city or age.
- **Usage data and failed-payment reason codes.** Today we see patterns, not causes: we can't tell lost interest from a failed card.
- **Run the annual-plan test (Part 5a)** with a 12-month follow-up, since annual-plan retention only shows after a year.
- **Automated tests** for the validation queries (today each SQL file ends with a validation query that prints its result, but nothing fails the build automatically).
- **Test the SQL explorer properly** on the website (every table, large results, slow phones and browsers).
- **Go deeper on the engineering base layers** (RAW, BASE, STAGING): review each rule again and add tests at each step.
- **Check that the model structure is the most efficient one** (table sizes, which tables to keep as views, query speed).

## Time spent

~5 hours
