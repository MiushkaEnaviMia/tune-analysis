# Tune subscription analysis (take-home)

Raw billing exports (Jan 2015 – Mar 2017) are loaded into DuckDB, checked for data-quality issues, and rebuilt as a clean,
tested data model. Everything is built by numbered SQL scripts that run in order against the raw CSVs.

Live site (report, table map, SQL on every table in the browser): https://miushkaenavimia.github.io/tune-analysis/

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
| `sql/00_load_raw.sql` | `raw_users`, `raw_transactions`, `raw_churn_labels` | a row of the CSV, as delivered (plus `src_file` / `src_row` lineage) |
| `sql/01_data_quality.sql` | `dq_summary`, `dq_examples_*`, `dq_export_profile`, `dq_t9_by_month`, `dq_exp_0331_by_tx` | one data-quality check / example row |
| `sql/02_stg_transactions.sql` | `ref_price_plan`, `stg_transactions` | a price point; a real billing event (deduplicated, conflicts resolved) |
| `sql/03_fct_subscription.sql` | `fct_subscription` | a subscription period (a purchase and the cancels that follow it) |
| `sql/04_dim_user.sql` | `dim_user` | a user seen anywhere (registry, transactions or labels) |
| `sql/05_fct_user_month.sql` | `fct_user_month` | a user in a calendar month with access, a payment or a churn |
| `sql/06_churn_validation.sql` | `churn_mar17`, `churn_confusion`, `churn_disagreement` | a user in the March-2017 churn cohort or labelled; one outcome × label cell; one disagreement group |
| `py/01_dq_outputs.py` | `reports/01_data_quality.{md,xlsx,html}`, `reports/01_dq_*.csv` | Part 1a report, generated from `dq_summary` |

Each SQL file starts with a header that states its input, output, grain and the rules it applies.

## Where each part of the brief lives

| Part | Where |
|---|---|
| 1a · Data-quality report | `reports/01_data_quality.md` (also `.xlsx`, `.html`); checks in `sql/01_data_quality.sql` |
| 1b · Clean layer and data model | `sql/02`–`sql/05`; design and validation in `reports/02_data_model.md` |
| 1c · Churn definition, validated | `sql/06_churn_validation.sql`; write-up in `reports/03_churn_validation.md` |
| Core metrics, deep dive, executive summary, experiment design | _to add_ |
| AI log | _to add_ (`reports/gemini_review_prompt_1a.md` is one prompt used for review) |

## Repository layout

```
README.md, requirements.txt, run_all.py, query.py
sql/        numbered build scripts (run in order)
py/         Python steps (report generator, site export)
reports/    deliverables
index.html, dq.html, catalog.json, tune_logo.png, .nojekyll, data/raw, data/clean
            the static website served by GitHub Pages; data/raw and data/clean hold Parquet exports
            of the built tables for the site, not the raw CSVs
task_status.json
            rows of the site's "Task & status" tab (status: done / partial / todo)
```

## With more time

_To fill in._

## Time spent

_To fill in._
