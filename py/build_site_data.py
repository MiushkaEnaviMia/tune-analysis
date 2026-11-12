"""Export every raw and clean table of tune.duckdb to Parquet for the static site (site/data/),
plus site/catalog.json (layer, grain, rows, columns). Not part of run_all.py (it writes ~400MB).

    .venv/bin/python -I py/build_site_data.py
"""
import glob, json, os, pathlib, shutil
import duckdb

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data"

# table -> (layer, sort order, grain, purpose). Grain/purpose follow reports/02_data_model.md.
TABLES = {
    "raw_users": ("raw", "user_id", "one row of users.csv",
                  "User registry as delivered. age 0 = missing, gender often empty, some users missing."),
    "raw_transactions_export_1": ("raw", "rowid", "one row of transactions_export_1.csv",
                                  "First billing export exactly as delivered."),
    "raw_transactions_export_2": ("raw", "rowid", "one row of transactions_export_2.csv",
                                  "Second billing export exactly as delivered."),
    "base_transactions": ("raw", "src_row", "one row of either export",
                          "Both exports combined, values unchanged, plus src_file and src_row (sql/00_union_exports.sql). Not cleaned yet."),
    "raw_churn_labels": ("raw", "user_id", "one labelled user",
                         "Billing team's churn labels for users due to expire in March 2017."),
    "ref_price_plan": ("clean", "amount_paid", "one price",
                       "Price to plan-length lookup, used to fill in missing plan days (T9)."),
    "stg_users": ("clean", "user_id", "one row of users.csv, cleaned",
                  "Cleaned registry: age 4-92 else NULL, gender 'unknown' if missing, typed registration date."),
    "stg_transactions": ("clean", "user_id, event_seq", "one real billing event",
                         "Deduplicated, conflict-resolved events with typed dates and one flag per cleaning rule."),
    "fct_subscription": ("clean", "user_id, period_no", "one subscription period (a purchase and the cancels that follow it)",
                         "Plan, price, discount, auto-renew, cancel, change vs previous, new/renewal/reactivation, episode."),
    "dim_user": ("clean", "user_id", "one user seen anywhere",
                 "Every user from the registry, transactions or labels, with cleaned attributes and derived fields."),
    "fct_user_month": ("clean", "user_id, month", "one user in one month with activity, payment or churn",
                       "Monthly panel (Jan 2015 to Mar 2017): monthly metrics become a GROUP BY month."),
    "fct_cohort": ("clean", "cohort_month, months_since_start", "one start-month cohort in one month since its start",
                   "Cohort curves: users who started, retention %, paying users, revenue, ARPU and cumulative ARPU by months since the first subscription."),
    "churn_mar17": ("clean", "user_id", "one user in our March-2017 churn cohort and/or with a billing label",
                    "Part 1c: our churn outcome (retained / churned / unknown) next to billing's label, with the disagreement bucket."),
    "churn_confusion": ("clean", "our_outcome", "one of our outcomes, split by billing label",
                        "Part 1c: confusion table, our outcome x billing label, including users only one side has."),
    "churn_disagreement": ("clean", "users desc", "one agreement or disagreement group",
                           "Part 1c: users per group, share labelled churned, and the likely reason."),
    "mart_churn_windows": ("clean", "month, window_days", "one month x one churn window (30 / 32 / 45 days)",
                           "Part 2: paid churn per month under three churn windows; 30 days is the main rule, 32 and 45 are checks."),
    "mart_metrics_month": ("clean", "month", "one calendar month (Jan 2015 to Mar 2017)",
                           "Part 2: paying subscribers (new / renewing / reactivated), churn rate, revenue, ARPU, discounts."),
    "mart_renewal_decisions": ("clean", "end_date, user_id, subscription_id", "one paid period that reached its expiry (a renewal decision)",
                               "Part 3: expiries Jan 2016 to Mar 2017 with churned yes/no (30 days) and every factor tested."),
    "mart_churn_drivers": ("clean", "factor, seg_order, segment", "one factor x one segment",
                           "Part 3: churn per segment, raw and adjusted for the auto-renew and plan-length mix."),
    "mart_churn_factor_summary": ("clean", "factor", "one factor",
                                  "Part 3: how far churn spreads between a factor's best and worst segment, raw vs adjusted."),
    "mart_churn_method_quarter": ("clean", "quarter, grp", "one quarter x one payment group",
                                  "Part 3: churn of payment method 39 vs other auto-renew vs manual payers, by quarter."),
    "mart_churn_plan_monthly": ("clean", "plan_length", "one plan length (manual payers)",
                                "Part 3: churn per renewal decision and per month of cover, by plan length."),
}

con = duckdb.connect(str(ROOT / "tune.duckdb"), read_only=True)
con.sql("set preserve_insertion_order=true; set threads=1")
shutil.rmtree(OUT, ignore_errors=True)
catalog = {"tables": []}
for t, (layer, order, grain, purpose) in TABLES.items():
    d = OUT / layer / t
    d.parent.mkdir(parents=True, exist_ok=True)
    con.sql(f"copy (select * from {t} order by {order}) to '{d}' "
            "(format parquet, compression zstd, compression_level 19, row_group_size 122880, file_size_bytes '18MB')")
    files = sorted(glob.glob(f"{d}/*.parquet"), key=lambda p: int(p.rsplit("_", 1)[1].split(".")[0]))
    rows = con.sql(f"select count(*) from {t}").fetchone()[0]
    back = con.sql("select count(*) from read_parquet([" + ",".join(f"'{f}'" for f in files) + "])").fetchone()[0]
    assert back == rows, (t, rows, back)
    cols = [{"name": r[0], "type": r[1]} for r in con.sql(f"describe {t}").fetchall()]
    size = sum(os.path.getsize(f) for f in files)
    catalog["tables"].append({"name": t, "layer": layer, "grain": grain, "purpose": purpose, "rows": rows,
                              "bytes": size, "columns": cols,
                              "files": [os.path.relpath(f, OUT.parent) for f in files]})
    print(f"{t}: {rows:,} rows, {len(files)} files, {size/1e6:.1f} MB")
(OUT.parent / "catalog.json").write_text(json.dumps(catalog, indent=1))
