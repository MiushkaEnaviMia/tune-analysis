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
    "raw_transactions": ("raw", "src_row", "one row of transactions_export_1.csv or _2.csv",
                         "Both billing exports as delivered, with src_file and src_row added at load."),
    "raw_churn_labels": ("raw", "user_id", "one labelled user",
                         "Billing team's churn labels for users due to expire in March 2017."),
    "ref_price_plan": ("clean", "amount_paid", "one price",
                       "Price to plan-length lookup, used to fill in missing plan days (T9)."),
    "stg_transactions": ("clean", "user_id, event_seq", "one real billing event",
                         "Deduplicated, conflict-resolved events with typed dates and one flag per cleaning rule."),
    "fct_subscription": ("clean", "user_id, period_no", "one subscription period (a purchase and the cancels that follow it)",
                         "Plan, price, discount, auto-renew, cancel, change vs previous, new/renewal/reactivation, episode."),
    "dim_user": ("clean", "user_id", "one user seen anywhere",
                 "Every user from the registry, transactions or labels, with cleaned attributes and derived fields."),
    "fct_user_month": ("clean", "user_id, month", "one user in one month with activity, payment or churn",
                       "Monthly panel (Jan 2015 to Mar 2017): monthly metrics become a GROUP BY month."),
    "churn_mar17": ("clean", "user_id", "one user in our March-2017 churn cohort and/or with a billing label",
                    "Part 1c: our churn outcome (retained / churned / unknown) next to billing's label, with the disagreement bucket."),
    "churn_confusion": ("clean", "our_outcome", "one of our outcomes, split by billing label",
                        "Part 1c: confusion table, our outcome x billing label, including users only one side has."),
    "churn_disagreement": ("clean", "users desc", "one agreement or disagreement group",
                           "Part 1c: users per group, share labelled churned, and the likely reason."),
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
