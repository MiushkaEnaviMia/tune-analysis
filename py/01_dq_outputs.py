"""01_dq_outputs.py - Part 1a outputs, generated from ONE source of truth.

Reads the dq_* tables built by sql/01_data_quality.sql and the ISSUES catalog below, and writes:
  reports/01_data_quality.md    ranked data-quality report (submission)
  reports/01_data_quality.xlsx  workbook: ranked issues, trade-offs, one tab per raw table with real bad rows
  reports/01_data_quality.html  the same report as a filterable page (building block for the dashboard)
Every number comes from DuckDB at run time, so the report, the workbook, the page and the SQL cannot drift apart.
Every detection query in the catalog is re-run at build time and must return exactly its check's row count.
Run via run_all.py (after the SQL scripts), or directly: .venv/bin/python py/01_dq_outputs.py
"""
import html
import json
import pathlib
import re
import duckdb
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = pathlib.Path(__file__).resolve().parents[1]
con = duckdb.connect(str(ROOT / "tune.duckdb"), read_only=True)

Q = {"Q1": "subscriber-base health & trend", "Q2": "churn drivers",
     "Q3": "free trials & price points", "Q4": "annual plans"}

# ---------------------------------------------------------------------------
# FACTS: supporting numbers quoted in the text (evidence for decisions and for the second-opinion review).
# Each is one SQL scalar, available in the catalog text as {F_name}. Money in local currency units.
# ---------------------------------------------------------------------------
DD = "datediff('day', strptime(transacted_at::VARCHAR, '%Y%m%d'), strptime(expires_at::VARCHAR, '%Y%m%d'))"
T9W = "payment_plan_days = 0 AND list_price = 0 AND amount_paid > 0"
MISSING = "user_id NOT IN (SELECT user_id FROM raw_users)"
FACTS_SQL = {
 "rev_total":   "SELECT sum(amount_paid) FROM t",
 "t23_rev":     f"SELECT sum(amount_paid) FROM t WHERE {MISSING}",
 "t23_payers":  f"SELECT count(DISTINCT user_id) FROM t WHERE amount_paid > 0 AND {MISSING}",
 "age_min":     "SELECT min(age) FROM raw_users",
 "age_max":     "SELECT max(age) FROM raw_users",
 "age_med":     "SELECT median(age)::INT FROM raw_users WHERE age BETWEEN 4 AND 92",
 "age_1_3":     "SELECT count(*) FROM raw_users WHERE age BETWEEN 1 AND 3",
 "age_3":       "SELECT count(*) FROM raw_users WHERE age = 3",
 "age_4":       "SELECT count(*) FROM raw_users WHERE age = 4",
 "age_4_12":    "SELECT count(*) FROM raw_users WHERE age BETWEEN 4 AND 12",
 "age_81_92":   "SELECT count(*) FROM raw_users WHERE age BETWEEN 81 AND 92",
 "ep_0":        "SELECT round(100.0 * avg((gender IS NULL AND city = 1)::INT), 1)::VARCHAR FROM raw_users WHERE age = 0",
 "ep_1_3":      "SELECT round(100.0 * avg((gender IS NULL AND city = 1)::INT), 1)::VARCHAR FROM raw_users WHERE age BETWEEN 1 AND 3",
 "ep_13_92":    "SELECT round(100.0 * avg((gender IS NULL AND city = 1)::INT), 1)::VARCHAR FROM raw_users WHERE age BETWEEN 13 AND 92",
 "age_8192_lo": "SELECT min(n) FROM (SELECT age, count(*) n FROM raw_users WHERE age BETWEEN 81 AND 92 GROUP BY 1)",
 "age_8192_hi": "SELECT max(n) FROM (SELECT age, count(*) n FROM raw_users WHERE age BETWEEN 81 AND 92 GROUP BY 1)",
 "age_106":     "SELECT count(*) FROM raw_users WHERE age = 106",
 "age_112":     "SELECT count(*) FROM raw_users WHERE age = 112",
 "l5_churn":    f"SELECT round(100.0 * avg(is_churn), 1)::VARCHAR FROM raw_churn_labels WHERE {MISSING}",
 "reg_churn":   "SELECT round(100.0 * avg(is_churn), 1)::VARCHAR FROM raw_churn_labels WHERE user_id IN (SELECT user_id FROM raw_users)",
 "reg_lab":     "SELECT count(*) FROM raw_churn_labels WHERE user_id IN (SELECT user_id FROM raw_users)",
 "age_gt100":   "SELECT count(*) FROM raw_users WHERE age > 100",
 "age_1_100":   "SELECT count(*) FROM raw_users WHERE age NOT BETWEEN 1 AND 100",
 "age_1_9":     "SELECT count(*) FROM raw_users WHERE age BETWEEN 1 AND 9",
 "age_81_100":  "SELECT count(*) FROM raw_users WHERE age BETWEEN 81 AND 100",
 "pd0_rows":    "SELECT count(*) FROM t WHERE payment_plan_days = 0",
 "pd0_users":   "SELECT count(DISTINCT user_id) FROM t WHERE payment_plan_days = 0",
 "t9_149":      f"SELECT count(*) FROM t WHERE {T9W} AND amount_paid = 149",
 "t9_eq30":     f"SELECT count(*) FROM t WHERE {T9W} AND {DD} = 30",
 "t9_28_31":    f"SELECT count(*) FROM t WHERE {T9W} AND {DD} BETWEEN 28 AND 31",
 "t9_25_35":    f"SELECT count(*) FROM t WHERE {T9W} AND {DD} BETWEEN 25 AND 35",
 "t9_neg":      f"SELECT count(*) FROM t WHERE {T9W} AND {DD} < 0",
 "t9_1788":     f"SELECT count(*) FROM t WHERE {T9W} AND amount_paid = 1788",
 "t9_1788_med": f"SELECT median({DD})::INT FROM t WHERE {T9W} AND amount_paid = 1788",
 "p30_rows":    "SELECT count(*) FROM t WHERE payment_plan_days = 30 AND is_cancel = 0 AND amount_paid > 0",
 "p30_25_35":   f"SELECT count(*) FROM t WHERE payment_plan_days = 30 AND is_cancel = 0 AND amount_paid > 0 AND {DD} BETWEEN 25 AND 35",
 "cx_neg_all":  "SELECT count(*) FROM t WHERE is_cancel = 1 AND expires_at < transacted_at",
 "cx_after":    "SELECT count(*) FROM t WHERE is_cancel = 1 AND expires_at > transacted_at",
 "cx_after_med": f"SELECT median({DD})::INT FROM t WHERE is_cancel = 1 AND expires_at > transacted_at",
 "sd_rows":     "SELECT sum(n) FROM (SELECT count(*) n FROM t GROUP BY user_id, transacted_at HAVING count(*) > 1)",
 "sd_users":    "SELECT count(DISTINCT user_id) FROM (SELECT user_id FROM t GROUP BY user_id, transacted_at HAVING count(*) > 1)",
 "sd_mixed":    "SELECT count(*) FROM (SELECT 1 FROM t GROUP BY user_id, transacted_at HAVING count(DISTINCT is_cancel) = 2)",
 "t24_rev":     "SELECT sum(amount_paid) FROM t_core WHERE n_core > 1 AND (user_id, transacted_at, payment_method, payment_plan_days, "
                "amount_paid, is_cancel, src_file) IN (SELECT (user_id, transacted_at, payment_method, payment_plan_days, amount_paid, "
                "is_cancel, src_file) FROM t GROUP BY ALL HAVING count(DISTINCT expires_at) > 1)",
 "t24_max":     "SELECT max(n) FROM (SELECT count(*) n FROM t GROUP BY user_id, transacted_at)",
 "t7_rev":      "SELECT sum(amount_paid * (n - 1)) FROM (SELECT amount_paid, count(*) n FROM t GROUP BY user_id, payment_method, "
                "payment_plan_days, list_price, amount_paid, is_auto_renew, transacted_at, expires_at, is_cancel, src_file HAVING count(*) > 1)",
 "zp_rows":     "SELECT count(*) FROM t WHERE amount_paid = 0",
 "zp_users":    "SELECT count(DISTINCT user_id) FROM t WHERE amount_paid = 0",
 "zp_cancel":   "SELECT count(*) FROM t WHERE amount_paid = 0 AND is_cancel = 1",
 "t12_m35":     "SELECT round(100.0 * count(*) FILTER (WHERE payment_method = 35 AND payment_plan_days = 7) / count(*), 0)::INT "
                "FROM t WHERE is_cancel = 0 AND amount_paid = 0 AND list_price = 0",
 "t17_m17":     "SELECT round(100.0 * count(*) FILTER (WHERE payment_method = 17 AND list_price = 0) / count(*), 0)::INT FROM t WHERE expires_at = 19700101",
 "t17_paid":    "SELECT count(*) FROM t WHERE expires_at = 19700101 AND amount_paid > 0",
 "t16_m24":     "SELECT round(100.0 * count(*) FILTER (WHERE payment_method = 24) / count(*), 0)::INT FROM t "
                "WHERE is_cancel = 0 AND expires_at < transacted_at AND expires_at <> 19700101",
 "t18_cx":      "SELECT count(*) FROM t WHERE expires_at < 20150101 AND expires_at <> 19700101 AND is_cancel = 1",
 "t18_ncx":     "SELECT count(*) FROM t WHERE expires_at < 20150101 AND expires_at <> 19700101 AND is_cancel = 0",
 "n410":        "SELECT count(*) FROM t WHERE payment_plan_days = 410 AND transacted_at BETWEEN 20160801 AND 20170228",
 "n410_e2":     "SELECT count(*) FROM t WHERE payment_plan_days = 410 AND transacted_at BETWEEN 20160801 AND 20170228 AND src_file = 2",
 "t19_30u":     "SELECT count(DISTINCT user_id) FROM t WHERE expires_at > 20190331 AND payment_plan_days = 30",
 "t19_30r":     "SELECT count(*) FROM t WHERE expires_at > 20190331 AND payment_plan_days = 30",
 "t4_later":    "SELECT count(*) FROM x_pairs WHERE (exp_e1 <> exp_e2 OR ar_e1 <> ar_e2 OR lp_e1 <> lp_e2) AND exp_e2 > exp_e1",
 "t6_e1":       "SELECT count(*) FROM t JOIN x_keys_complementary USING (user_id, transacted_at) WHERE src_file = 1",
 "e2_mar":      "SELECT count(*) FROM t WHERE src_file = 2 AND transacted_at >= 20170301",
 "t20_0228":    "SELECT count(*) FROM t WHERE expires_at = 20170331 AND transacted_at = 20170228",
 "u7_tx":       "SELECT count(*) FROM raw_users WHERE registered_at > 20170331 AND user_id IN (SELECT user_id FROM t)",
 "t9_win_users": "SELECT count(DISTINCT user_id) FROM t WHERE is_cancel = 0 AND transacted_at BETWEEN 20150301 AND 20151031",
 "t9_win_hit":  "SELECT count(DISTINCT user_id) FROM t WHERE is_cancel = 0 AND transacted_at BETWEEN 20150301 AND 20151031 "
                "AND payment_plan_days = 0 AND list_price = 0 AND amount_paid > 0",
 "t9_win_paid": "SELECT count(*) FROM t WHERE is_cancel = 0 AND amount_paid > 0 AND transacted_at BETWEEN 20150301 AND 20151031",
 "t9_win_t9":   "SELECT count(*) FROM t WHERE is_cancel = 0 AND transacted_at BETWEEN 20150301 AND 20151031 "
                "AND payment_plan_days = 0 AND list_price = 0 AND amount_paid > 0",
 "t25_match":   "SELECT count(*) FROM t_prev WHERE is_cancel = 0 AND payment_plan_days > 0 AND prev_exp > transacted_at "
                "AND " + DD + " - payment_plan_days > 3 AND abs(datediff('day', strptime(prev_exp::VARCHAR, '%Y%m%d'), "
                "strptime(expires_at::VARCHAR, '%Y%m%d')) - payment_plan_days) <= 3",
}
F = {k: con.sql(v).fetchone()[0] for k, v in FACTS_SQL.items()}

# ---------------------------------------------------------------------------
# ISSUE CATALOG (single source of truth). Ranked by impact on leadership's 4 questions.
# checks: dq_summary check_ids; the first one supplies the size.  fields: columns highlighted in examples.
# alts: exactly 2 realistic engineering alternatives (A, B); B is the recommended one. why_b = why B beats A.
# Rule for alternatives: each one is something a competent engineer could ship; no strawmen.
# ---------------------------------------------------------------------------
ISSUES = [
 dict(sev="Critical", checks=["T2", "T1", "T3"], table="transactions", fields=["expires_at", "src_file"],
  title="The two exports are split by expiry date, not purchase date: {T2} older purchases exist only in export_2",
  what="export_1 contains only rows with expires_at <= 2017-03-31: T1 finds {T1} rows expiring later. export_2 contains every row expiring "
       "after that: {F_e2_mar} March 2017 purchases plus {T2} purchases made 2015 - Feb 2017. Neither file is complete on its own.",
  why="Reading export_2 as 'the March file' drops every subscription bought earlier that is still alive after March 2017. That undercounts "
      "the active base at period end (Q1) and hides almost all recent annual plans: {F_n410_e2} of the {F_n410} 410-day plans bought "
      "Aug 2016 - Feb 2017 sit in export_2 (Q4).",
  qs=["Q1", "Q4"],
  sql="-- export_2 rows bought before March 2017 (lost if export_2 is read as 'March only')\n"
      "SELECT * FROM base_transactions WHERE src_file = 2 AND transacted_at < 20170301;\n"
      "-- proof of the split: export_1 never expires after 2017-03-31\n"
      "SELECT src_file, max(expires_at), count(*) FILTER (WHERE expires_at > 20170331) FROM base_transactions GROUP BY 1;",
  alts=[dict(name="Incremental append: export_1 + March rows of export_2",
             desc="Standard monthly-load pattern: export_1 is history, export_2 is the new month; append export_2 rows with transacted_at >= 2017-03-01.",
             cost="Lowest (filtered append)", storage="Lowest", speed="Fastest; fits a daily/monthly incremental job",
             loss="High: silently loses the {T2} older export_2 rows, incl. {F_n410_e2} annual plans"),
        dict(name="Full UNION of both exports + lineage + conflict rules",
             desc="One table with src_file and src_row (which file and row each record came from), then the duplicate and conflict rules of T4, T7 and T24.",
             cost="+1 scan of 5.7M rows (about 1 s in DuckDB)", storage="+2 small columns (TINYINT, BIGINT)",
             speed="Seconds; full reload each time", loss="None; {T4} conflicting rows resolved by an explicit rule")],
  why_b="The append pattern is right only if the files are split by transaction date. They are split by expiry date, so the append "
        "loses rows by construction. A full reload costs about one second at this size.",
  decision="UNION both exports; keep src_file/src_row for audit. Ask billing for one export with an event ID and updated_at."),

 dict(sev="High", checks=["T23", "L5"], table="transactions", fields=["user_id"],
  title="Users who pay or transact but are missing from users.csv ({F_t23_rev_p}% of revenue)",
  what="{T23_u} users with transactions ({T23_pu}% of transacting users; {T23} rows) have no row in the user registry. "
       "They carry {F_t23_rev_m} of revenue ({F_t23_rev_p}% of {F_rev_total_m}); {F_t23_payers} of them paid at least once. "
       "{L5} labelled users are also missing, and they are not a random subset: they churn at {F_l5_churn}% vs {F_reg_churn}% "
       "for the {F_reg_lab} labelled users found in the registry.",
  why="An inner join to users silently drops 18% of transacting users and {F_t23_rev_p}% of revenue from every metric (Q1). "
      "Because the missing users churn at about half the rate of the rest, an inner join also biases the churn rate and every "
      "churn-driver cut (Q2). Their attributes (age, channel, city) are unknown, so segment cuts cover only part of the base. "
      "It ranks below the Critical issues because it does not lose rows by itself (revenue and actives come from transactions), "
      "but any join to users silently changes both the totals and the churn answer.",
  qs=["Q1", "Q2"],
  sql="SELECT * FROM base_transactions\nWHERE user_id NOT IN (SELECT user_id FROM raw_users);",
  alts=[dict(name="Decoupled reporting",
             desc="Revenue, actives and ARPU from transactions only (no join); demographic cuts run separately on the {T23_pu_rest}% of users found in the registry.",
             cost="None extra", storage="None", speed="Fast; no join on the revenue path",
             loss="Low data loss, but two populations: segment totals never add up to the headline numbers"),
        dict(name="dim_user from all IDs + is_in_users flag",
             desc="dim_user = every user_id seen in users, transactions or labels; missing attributes become 'Unknown'.",
             cost="One extra DISTINCT union (seconds)", storage="+{T23_u} small rows", speed="Seconds",
             loss="None")],
  why_b="Both keep all revenue. dim_user keeps one population, so every segment table sums to the headline and the 'Unknown' "
        "segment is visible and testable (is it different on churn?).",
  decision="Build dim_user from the union of all user IDs, with is_in_users = 0 for the missing ones and attributes = 'Unknown'."),

 dict(sev="Critical", checks=["T9"], table="transactions", fields=["payment_plan_days", "list_price"],
  title="Paid purchases logged with plan length 0 and list price 0, Mar-Oct 2015: {F_t9_paid_p}% of paid purchases in those months, {F_t9_win_p}% of active users",
  what="payment_plan_days = 0 and list_price = 0, but amount_paid > 0 ({F_t9_149} rows paid 149) and expires_at is about 1 month later. "
       "All rows fall in 2015-03 to 2015-10: a logging gap in the billing system, not free plans. "
       "Date evidence: {F_t9_25_35_p}% end 25-35 days after the purchase (normal paid 30-day rows: {F_p30_25_35_p}%); "
       "the {F_t9_1788} rows paid 1,788 run a median {F_t9_1788_med} days, i.e. annual plans.",
  why="In Mar-Oct 2015 these rows belong to {F_t9_win_p}% of active users ({F_t9_win_hit} of {F_t9_win_users}). Treated as 0-day plans "
      "they create no subscription period, so that share of the base vanishes from the 2015 trend (Q1). Left as is, 2015 also shows 0-day plans, a negative discount (paid > list) and broken ARPU per plan. That corrupts the 2015 "
      "baseline for the trend (Q1), price points (Q3) and plan mix (Q4).",
  qs=["Q1", "Q3", "Q4"],
  sql="SELECT * FROM base_transactions\nWHERE payment_plan_days = 0 AND list_price = 0 AND amount_paid > 0;",
  alts=[dict(name="Price-to-plan lookup",
             desc="Map amount_paid to the plan sold at that price in the same period (149 -> 30 days, 1,788 -> 410 days ...); list_price = amount_paid; flag.",
             cost="One small mapping table + join", storage="+1 lookup table, +1 flag", speed="Seconds",
             loss="Medium: needs a hand-built price list; prices that map to several plans or appear only in 2015 stay unknown"),
        dict(name="Plan days from the row's own dates, snapped + flag",
             desc="plan_days = expires_at - transacted_at, snapped to 7/30/90/180/365/410; list_price = amount_paid; is_imputed_plan = 1. "
                  "Rows with negative date gaps ({F_t9_neg}) fall back to the price lookup.",
             cost="One CASE expression", storage="+1 flag column", speed="Seconds",
             loss="Low: 2015 discount set to 0; flagged, so it can be excluded")],
  why_b="The expiry is what billing actually granted on that row, so it carries the plan length without a hand-maintained price list, "
        "and it also catches the annual rows. The price lookup stays as the fallback for the few rows with unusable dates.",
  decision="Impute plan days from dates (price lookup as fallback), set list_price = amount_paid, flag every imputed row. Ask billing for a backfill."),

 dict(sev="High", checks=["T11"], table="transactions", fields=["amount_paid"],
  title="Free trials and 100% discounts: paid 0 although the plan has a list price",
  what="Non-cancel rows with list_price > 0 and amount_paid = 0. Not an error: these are the free-trial campaigns, but nothing in the data labels them.",
  why="Counted as paying subscribers, they inflate the active base and deflate ARPU (Q1). They are also the treatment group "
      "for the trial analysis (Q3), so they must be identifiable.",
  qs=["Q1", "Q3"],
  sql="SELECT * FROM base_transactions\nWHERE is_cancel = 0 AND amount_paid = 0 AND list_price > 0;",
  alts=[dict(name="Separate fact_trial table",
             desc="Move zero-paid rows out of the subscription fact into their own trial table; subscriptions stay paid-only.",
             cost="One extra table build", storage="+1 table (same rows, moved)", speed="Seconds; paid queries need no filter",
             loss="Medium: trial -> paid becomes a cross-table join; a paid row right after a trial looks like a brand-new subscription"),
        dict(name="Keep in one table + is_free flag",
             desc="Keep every row; report active subscribers as paid vs free; ARPU on paid only.",
             cost="One boolean expression", storage="+1 flag column", speed="Seconds; every paid metric filters on the flag",
             loss="None; risk is forgetting the filter, handled by paid/free views")],
  why_b="Trial conversion and churn are sequences within one user's period chain. One table keeps that chain intact; the flag "
        "and two thin views give the same convenience as a separate table.",
  decision="Keep and flag is_free = 1. Every subscriber metric is split into paid and free."),

 dict(sev="High", checks=["U11", "U1", "U2", "U3", "U4"], table="users", fields=["age"],
  title="Age missing (0) or implausible for {U11_pu}% of users",
  what="age = 0 for {U1_pr}% of users (the missing-value code), plus negative ages (min {F_age_min}), very young and very old ages "
       "(max {F_age_max}). Range kept: 4-92, deliberately wide so real users are not dropped (the app is for all ages). "
       "Lower bound: ages 1-3 ({F_age_1_3} users) look partly like unfilled profiles: {F_ep_1_3}% have an empty profile (gender missing and "
       "city = 1), against {F_ep_0}% at age 0 and {F_ep_13_92}% at 13-92; the count also jumps from {F_age_3} at age 3 to {F_age_4} at 4. "
       "Upper bound: ages 81-92 stay at {F_age_8192_lo}-{F_age_8192_hi} "
       "users per year, like the late 70s; from 93 the counts rise again (106: {F_age_106}, 112: {F_age_112}), which is not "
       "demographic. There is no ground truth, so we cannot tell whether either edge should be earlier or later; the edge "
       "groups (4-12: {F_age_4_12}; 81-92: {F_age_81_92}) are small, and a sensitivity check can drop them.",
  why="Age is one of the churn segments (Q2). Taking 0 or {F_age_max} at face value breaks the age bands. The users with a known age "
      "are a non-random minority, so a naive cut is confounded.",
  qs=["Q2"],
  sql="SELECT * FROM raw_users\nWHERE age NOT BETWEEN 4 AND 92;",
  alts=[dict(name="Median impute + is_age_imputed flag",
             desc="Fill unusable ages with the median of valid ages ({F_age_med}) and flag them; every user gets an age band.",
             cost="One median + CASE", storage="+1 flag", speed="Seconds",
             loss="High bias here: {U11_pr}% would sit in the median band, so age effects on churn are diluted"),
        dict(name="NULL + 'Unknown' age band",
             desc="Age outside 4-92 becomes NULL; bands 4-17 / 18-24 / 25-34 / 35-44 / 45-92 / Unknown; known-age analysis carries a caveat.",
             cost="One CASE expression", storage="+1 column", speed="Seconds", loss="None (raw values kept in raw_users)")],
  why_b="Median imputation is reasonable at 5% missing, not at {U11_pr}%: the imputed band would be mostly fabricated, and "
        "missingness itself may predict churn, which the 'Unknown' band keeps visible.",
  decision="Set age outside 4-92 to NULL (wide margins, no ground truth for the edges); age_band includes 'Unknown'; no imputation."),

 dict(sev="High", checks=["T12", "T13"], table="transactions", fields=["list_price", "amount_paid"],
  title="Free periods with no price at all (list price 0, paid 0)",
  what="Non-cancel rows with no price at all. {F_t12_m35}% are payment_method 35 with a 7-day plan, which looks like a trial product. "
       "Related: T13 = {T13} rows with 0 plan days; the free ones among them are already in T12.",
  why="Same risk as T11, on more users ({T12_u} vs {T11_u}): they inflate the subscriber count and are part of the trial story (Q3).",
  qs=["Q1", "Q3"],
  sql="SELECT * FROM base_transactions\nWHERE is_cancel = 0 AND amount_paid = 0 AND list_price = 0;",
  alts=[dict(name="Back-fill list_price from the plan's standard price",
             desc="Give each row the standard price of its plan length, so it becomes a 100%-discount row like T11 and all trials share one discount metric.",
             cost="One join to a price table", storage="None", speed="Seconds",
             loss="Medium: invents a price for a product that may be free by design (7-day pass), inflating 'discount given'"),
        dict(name="Keep + is_free flag, list_price stays 0",
             desc="Same flag as T11; trial type = 'unpriced pass' vs 'discounted plan'; 0-day rows create no subscription period.",
             cost="One expression", storage="+1 small column (trial type)", speed="Seconds", loss="None")],
  why_b="The two free products behave differently (7-day pass vs 100% discount on a full plan). Keeping list_price = 0 "
        "keeps them separable for Q3; a back-filled price would merge them and overstate discounts.",
  decision="Keep, with is_free = 1 and a trial type. Rows with 0 plan days produce no subscription period."),

 dict(sev="Medium", checks=["T15", "T14"], table="transactions", fields=["expires_at", "is_cancel"],
  title="Cancellations move expiry before the transaction date",
  what="On cancel rows, expires_at is often earlier than transacted_at. This is documented behaviour ('a cancellation can move a "
       "user's expiry earlier'). On {F_cx_after} other cancel rows the expiry stays after the cancel date (median {F_cx_after_med} days): "
       "the user keeps access until then.",
  why="If cancels are ignored, the period runs to the original expiry, so churn timing (Q2) and monthly actives (Q1) are wrong.",
  qs=["Q1", "Q2"],
  sql="SELECT * FROM base_transactions\nWHERE is_cancel = 1 AND expires_at < transacted_at AND expires_at <> 19700101;",
  alts=[dict(name="Effective end = cancel transacted_at",
             desc="A cancel ends the period on the day it happens; expires_at on cancel rows is ignored.",
             cost="Lowest (no date logic)", storage="+1 flag", speed="Seconds",
             loss="Medium: cuts a median {F_cx_after_med} days of paid access on {F_cx_after} cancels, so actives are understated and churn looks earlier"),
        dict(name="Effective end = cancel row's expires_at, floored at period start",
             desc="effective_end = the cancel row's expires_at (never before the period start); is_cancelled = 1.",
             cost="One window function per user", storage="+2 columns", speed="Seconds", loss="None")],
  why_b="The brief defines the cancel row's expires_at as the new expiry ('a cancellation can move a user's expiry date earlier'), "
        "and the churn labels are built on it. Using the cancel date would contradict both.",
  decision="A cancel row sets the period's effective end date (floored at the period start) and is_cancelled = 1."),

 dict(sev="Medium", checks=["T8"], table="transactions", fields=["transacted_at", "is_cancel"],
  title="One user can have several events on the same day: (user_id, transacted_at) is not a unique key",
  what="Several real events can share a user and a day, for example a cancel at 149 plus a new plan at 129 on the same day "
       "(a price change). {F_sd_mixed} user-days contain both a cancel and a new purchase.",
  why="Deduplicating on (user, day) would delete real upgrades and downgrades (Q3, Q4). Ordering same-day events at random "
      "makes results change between runs (this happened once and was fixed).",
  qs=["Q3", "Q4"],
  sql="SELECT * FROM base_transactions\nQUALIFY count(*) OVER (PARTITION BY user_id, transacted_at, src_file) > 1;",
  alts=[dict(name="Aggregate to one row per user-day",
             desc="Grain = (user_id, day): sum amount_paid, max expires_at, cancel wins if any row is a cancel.",
             cost="One GROUP BY", storage="-{F_sd_rows_less} rows", speed="Fast; simple unique key",
             loss="High: {F_sd_mixed} cancel + new-plan days become 'cancelled', so upgrades read as churn; plan per row is lost"),
        dict(name="Event grain + deterministic sequence",
             desc="Remove only rows identical in every column. Order same-day events: cancel first, then purchase, then expiry, then src_row.",
             cost="One window function", storage="+1 sequence column", speed="Seconds", loss="None")],
  why_b="The user-day grain is easier to join, but it erases what Q3/Q4 need (which plan replaced which). The event grain keeps "
        "both events and a fixed order, so results are identical between runs.",
  decision="Deduplicate on the full row only. Same-day events are ordered cancel, purchase, expiry, src_row (deterministic)."),

 dict(sev="Medium", checks=["T24"], table="transactions", fields=["transacted_at", "expires_at"],
  title="Stacked purchases: the same purchase repeated on one day, each extending the expiry",
  what="Several rows share user, day, method, plan, amount and cancel flag but have different expires_at. For paid 30-day plans, "
       "the expiries are 30 days apart (median gap 30 for every stack size), so each row is one more prepaid month. "
       "Extreme case: {F_t24_max} free 7-day passes for one user on one day.",
  why="They look like duplicates but are real revenue (paid rows in stacks total {F_t24_rev_m}). A dedup on (user, day, "
      "plan, amount) would delete them, understating revenue and renewals (Q1) and plan value (Q4). They also explain the far-future expiries (T19).",
  qs=["Q1", "Q4"],
  sql="SELECT * FROM t_core  -- view in 01_data_quality.sql (adds n_core)\nWHERE n_core > 1\nQUALIFY count(DISTINCT expires_at) OVER (PARTITION BY user_id, transacted_at, payment_method,\n  payment_plan_days, amount_paid, is_cancel, src_file) > 1;",
  alts=[dict(name="Collapse each stack into one purchase",
             desc="One row per stack: amount = sum, expires_at = max, plan_days = max expiry - transacted_at.",
             cost="One GROUP BY", storage="-{T24} rows (fewer)", speed="Fast",
             loss="Medium: revenue kept, but 12 prepaid months look like one long plan, so plan mix (Q4) and renewal counts (Q1) shift"),
        dict(name="Keep each row; chain into one period",
             desc="Every row counts as a purchase of its own plan (revenue, renewal); the subscription period runs to the max expiry of the stack.",
             cost="One window function", storage="None", speed="Seconds", loss="None")],
  why_b="Both keep revenue. Only per-row keeps the plan that was actually sold, which Q4 (monthly vs annual) depends on.",
  decision="Keep every row as a purchase; the period end is the latest expiry in the stack. Free stacks keep is_free = 1."),

 dict(sev="Critical", checks=["L6", "L7", "L4"], table="churn_labels", fields=["user_id", "is_churn"],
  title="Billing's churn labels cover different users than those due to expire in March 2017 (the brief's rule)",
  what="Built from each user's last transaction up to 2017-02-28, the 'due in March' set and the labels disagree: some labelled "
       "users fall outside it (L6), some users in it are unlabelled (L7), and {L4} labelled users have no transaction up to 2017-02-28 (L4).",
  why="These are billing's labels for its April 2017 churn review, most likely the churn number leadership has already seen. "
      "Part 1c shows they break their own rule (early renewals and renewals after 90+ days labelled churned; cohort built from export_1 "
      "only), so the labelled churn rate is overstated and biased against long plans (Q2, Q4). They cannot be repaired from the data, "
      "only replaced by our own implementation of the rule. They are also the yardstick for validating that rule (1c).",
  qs=["Q2", "Q4"],
  sql="SELECT * FROM raw_churn_labels\nWHERE user_id NOT IN (SELECT user_id FROM due_mar);  -- due_mar: view in 01_data_quality.sql",
  alts=[dict(name="Use billing's labels as the churn target",
             desc="Take is_churn as ground truth for the driver analysis; skip our own definition.",
             cost="None", storage="None", speed="Immediate",
             loss="Medium: one cohort only (March 2017), no trend for Q1/Q2, and the population gaps (L6/L7) are inherited unexplained"),
        dict(name="Implement the brief's rule, report disagreement",
             desc="Independent implementation over all months; confusion matrix vs the labels on March 2017; explain each disagreement bucket.",
             cost="One query + review", storage="None", speed="Seconds", loss="None")],
  why_b="Our own rule runs on every month (trend) and the labels stay an independent check of it, instead of an unverified input.",
  decision="Implement the definition independently in 1c; report and explain the disagreement buckets."),

 dict(sev="High", checks=["U5"], table="users", fields=["gender"],
  title="Gender missing for {U5_pu}% of users",
  what="Gender is NULL/empty for {U5_pr}% of users.",
  why="A churn segment (Q2) available for only about a third of users. Same size and same question as age (U11), so the same severity.",
  qs=["Q2"],
  sql="SELECT * FROM raw_users\nWHERE gender IS NULL OR trim(gender) = '';",
  alts=[dict(name="Complete-case analysis",
             desc="Gender cuts use only the {U5_pr_rest}% of users with a value; others are out of that analysis.",
             cost="None", storage="None", speed="Fast",
             loss="Medium: selection bias if missingness relates to churn; shares don't sum to the total"),
        dict(name="'unknown' category",
             desc="gender = coalesce(gender, 'unknown'), kept as its own segment.",
             cost="One coalesce", storage="None", speed="Seconds", loss="None")],
  why_b="The 'unknown' segment contains the complete-case view (filter it out) and also shows whether missing gender behaves differently.",
  decision="gender = 'unknown' when missing; it is reported as its own segment."),

 dict(sev="Low", checks=["T4"], table="transactions", fields=["expires_at", "is_auto_renew"],
  title="The same event appears in both exports with conflicting values",
  what="Matched on user, day, method, plan, amount and cancel flag, but expires_at or is_auto_renew differ. Only one-to-one matches count; stacked purchases (T24) are "
       "excluded. export_2 shows the later state ({F_t4_later} of {T4} have a later expiry in export_2), for example 2017-03-29 in export_1 vs 2017-04-28 in export_2.",
  why="Keeping both double-counts the event; picking the wrong one distorts period length. The effect is small.",
  qs=["Q1"],
  sql="SELECT * FROM x_pairs  -- view in 01_data_quality.sql\nWHERE exp_e1 <> exp_e2 OR ar_e1 <> ar_e2 OR lp_e1 <> lp_e2;",
  alts=[dict(name="Value rule: latest expires_at wins",
             desc="For a matched event keep the version with the max expires_at, whatever the file.",
             cost="One arg_max", storage="None", speed="Seconds",
             loss="Low today (same result); wrong if a later export shortens an expiry, e.g. after a cancel"),
        dict(name="Source rule: export_2 wins; keep export_1 expiry as as-of column",
             desc="The later snapshot wins; expires_at_asof_feb keeps the export_1 value for the 1c label logic.",
             cost="One join", storage="+1 column", speed="Seconds", loss="None")],
  why_b="Same result on this data, but 'newest snapshot wins' stays correct when an update shortens an expiry, and the as-of "
        "column preserves what billing knew on 2017-02-28, which the labels depend on.",
  decision="export_2 version wins; the export_1 expiry is kept as expires_at_asof_feb."),

 dict(sev="Low", checks=["T17"], table="transactions", fields=["expires_at"],
  title="Expiry date missing, stored as 1970-01-01",
  what="An epoch zero date stands in for 'unknown'. {F_t17_m17}% are payment_method 17 rows with no price; {F_t17_paid} rows are paid.",
  why="Taken literally, the period would end 47 years before it started.",
  qs=["Q1"],
  sql="SELECT * FROM base_transactions\nWHERE expires_at = 19700101;",
  alts=[dict(name="Exclude from period building",
             desc="Keep the rows for revenue, but they create no subscription period.",
             cost="One filter", storage="None", speed="Fast",
             loss="Low: {T17} rows; up to {F_t17_paid} paid periods missing from actives"),
        dict(name="NULL + derive from plan days",
             desc="expires_at = transacted_at + plan_days; flag is_expiry_derived.",
             cost="One CASE", storage="+1 flag", speed="Seconds", loss="None; derived value flagged")],
  why_b="Plan days are present on these rows, so the expiry can be rebuilt with the same rule as T16 at no extra cost.",
  decision="Set to NULL and derive from plan days; flag."),

 dict(sev="Low", checks=["T16"], table="transactions", fields=["expires_at"],
  title="Purchase rows whose expiry date is before the purchase date",
  what="Not explained by cancellation. {F_t16_m24}% are payment_method 24, mostly 30-day plans in 2015: a provider-specific bug.",
  why="Creates negative-length periods, so actives are understated.",
  qs=["Q1"],
  sql="SELECT * FROM base_transactions\nWHERE is_cancel = 0 AND expires_at < transacted_at AND expires_at <> 19700101;",
  alts=[dict(name="Zero-length period (expires_at = transacted_at) + flag",
             desc="Conservative: grant no access we cannot prove.",
             cost="One CASE", storage="+1 flag", speed="Seconds",
             loss="Low: up to one plan length of activity missing for {T16_u} users"),
        dict(name="Derive from plan days + flag",
             desc="expires_at = transacted_at + plan_days; is_expiry_derived = 1.",
             cost="One CASE", storage="+1 flag", speed="Seconds", loss="Low: assumes the paid plan was delivered")],
  why_b="These are paid non-cancel rows, so the plan was most likely delivered; the zero-length option would create false churn.",
  decision="Derive expiry from plan days; flag."),

 dict(sev="Low", checks=["T18"], table="transactions", fields=["expires_at"],
  title="Expiry dates in 2007-2014, before the data starts",
  what="{F_t18_cx} of these are cancel rows (valid: a cancel moved the expiry back); {F_t18_ncx} are non-cancel rows.",
  why="Only the non-cancel rows are wrong; they would create periods that end before they start.",
  qs=["Q1"],
  sql="SELECT * FROM base_transactions\nWHERE expires_at < 20150101 AND expires_at <> 19700101;",
  alts=[dict(name="Generic validity window on expires_at",
             desc="One rule for every row: expires_at outside 2015-01-01 .. 2019-03-31 becomes NULL and is derived from plan days.",
             cost="One CASE", storage="+1 flag", speed="Seconds",
             loss="Medium: overwrites {F_t18_cx} valid cancel expiries, so those cancels end later and churn is undercounted"),
        dict(name="Cancels kept; non-cancels derived",
             desc="Cancels follow the T15 rule. Non-cancels follow the T16 rule: derive the expiry from plan days.",
             cost="Reuses existing rules", storage="None", speed="Seconds", loss="None")],
  why_b="A date-range rule is simple but blind to the cancel semantics; the row-type rules already exist and treat both cases correctly.",
  decision="Cancels are kept (they set the effective end); the {F_t18_ncx} non-cancel rows get a derived expiry."),

 dict(sev="Low", checks=["T19"], table="transactions", fields=["expires_at"],
  title="Expiry more than 2 years past data end (up to 2026)",
  what="{F_t19_30r} of these are 30-day plans, for {F_t19_30u} users with about 10 rows each, consistent with stacked prepaid months (T24).",
  why="These users look 'active' until 2023-2026. Before 2017-03-31 the impact is nil; it matters only for forward-looking metrics.",
  qs=["Q1"],
  sql="SELECT * FROM base_transactions\nWHERE expires_at > 20190331;",
  alts=[dict(name="Recompute as transacted_at + plan_days",
             desc="Override billing's value with the row's own plan length.",
             cost="One CASE", storage="None", speed="Seconds",
             loss="Medium: cuts genuinely prepaid stacked months, creating false churn"),
        dict(name="Keep raw + flag",
             desc="Billing's expiry is the access right; flag is_far_future_expiry.",
             cost="One flag", storage="+1 flag", speed="Seconds", loss="None ({T19_u} users, outside the analysis window)")],
  why_b="The far expiries are explained by stacking (T24), so they are real; recomputing would contradict the stack logic.",
  decision="Keep the raw value and flag it; revisit only if forward-looking metrics are needed."),

 dict(sev="Low", checks=["T7"], table="transactions", fields=["user_id", "transacted_at"],
  title="Exact duplicate rows within export_1",
  what="Identical in every column, including the expiry (only src_row differs). Extra copies carry {F_t7_rev} in amount_paid.",
  why="Double counts revenue and renewals. Tiny effect.",
  qs=["Q1"],
  sql="-- returns only the extra copies (first copy = lowest src_row is kept)\nSELECT * FROM base_transactions\nQUALIFY row_number() OVER (PARTITION BY user_id, payment_method, payment_plan_days, list_price,\n  amount_paid, is_auto_renew, transacted_at, expires_at, is_cancel, src_file ORDER BY src_row) > 1;",
  alts=[dict(name="Keep as real double charges",
             desc="Treat each copy as a provider retry that really charged the user (refunds are not in the data).",
             cost="None", storage="+{T7} rows", speed="-",
             loss="Low: overstates revenue by {F_t7_rev} if they are export artefacts"),
        dict(name="Drop exact copies, keep lowest src_row",
             desc="row_number() over all business columns; src_row of the kept copy is preserved.",
             cost="One window function", storage="-{T7} rows", speed="Seconds", loss="Low: understates revenue if a few were real double charges")],
  why_b="A real double charge would get a second expiry (it stacks, T24). Identical expiry means the same event exported twice.",
  decision="Drop exact copies; keep the lowest src_row."),

 dict(sev="Low", checks=["T6"], table="transactions", fields=["is_cancel", "payment_plan_days"],
  title="Different events of the same user and day split across the two exports",
  what="For example, a cancel of a 30-day plan in export_1 and a new 270-day plan in export_2 on the same day (an upgrade).",
  why="A (user, day) dedup across the files would delete the upgrade (Q4).",
  qs=["Q4"],
  sql="SELECT * FROM base_transactions JOIN x_keys_complementary USING (user_id, transacted_at);",
  alts=[dict(name="Snapshot replace on (user, day)",
             desc="For any (user_id, day) present in both files, the newer export (export_2) replaces export_1's rows.",
             cost="One anti-join", storage="Smaller", speed="Fast; the usual 'newer snapshot replaces older' merge",
             loss="Medium: deletes {F_t6_e1} export_1 rows that are real events (cancels before upgrades)"),
        dict(name="Keep both; order by the T8 rule",
             desc="They are complementary events; match only on the full event core (T4).",
             cost="None", storage="None", speed="-", loss="None")],
  why_b="Snapshot replace needs a true event key; (user, day) is not one (T8), so it deletes real events.",
  decision="Keep both and sequence them with the same-day rule."),

 dict(sev="Low", checks=["U7", "U8"], table="users", fields=["registered_at"],
  title="Registration date after data end, or after the first transaction",
  what="{U7} users registered after 2017-03-31 ({F_u7_tx} of them transact); {U8} users registered after their first payment.",
  why="April registrants had no chance to convert inside the data, so trial and paid conversion would show 0% for them (Q3). "
      "Tenure (a Q2 driver) would be negative for U8.",
  qs=["Q2", "Q3"],
  sql="SELECT * FROM raw_users WHERE registered_at > 20170331;",
  alts=[dict(name="Drop April registrants from dim_user",
             desc="Out-of-window users are removed at load; tenure = data end - registered_at.",
             cost="One filter", storage="Smaller", speed="Fast",
             loss="Low: registry counts no longer match the source file; U8 tenure still negative"),
        dict(name="Keep + flag; tenure from least(registered_at, first_tx)",
             desc="is_registered_after_data_end excludes them from conversion denominators; tenure starts at the earliest evidence of the user.",
             cost="One LEAST() + flag", storage="+1 flag", speed="Seconds", loss="None")],
  why_b="Both keep conversion clean; only the flag keeps the registry reconcilable with the source and fixes U8 in the same step.",
  decision="Keep with a flag, excluded from conversion; tenure_start = least(registered_at, first_tx)."),

 dict(sev="Low", checks=["T10"], table="transactions", fields=["amount_paid", "list_price"],
  title="Amount paid above list price (list price > 0)",
  what="A handful of rows paid more than list price (for example list 119, paid 149).",
  why="Produces a negative discount. Negligible size.",
  qs=["Q3"],
  sql="SELECT * FROM base_transactions\nWHERE list_price > 0 AND amount_paid > list_price;",
  alts=[dict(name="Treat list_price as stale: list_price = amount_paid",
             desc="Assume the price list lagged a price increase.",
             cost="One CASE", storage="+1 flag", speed="Seconds", loss="Low: rewrites a source field on a guess"),
        dict(name="Keep raw values, floor the discount at 0 + flag",
             desc="discount = greatest(list_price - amount_paid, 0).",
             cost="One GREATEST()", storage="+1 flag", speed="Seconds", loss="None")],
  why_b="Same effect on discount metrics without overwriting a source column.",
  decision="Floor the discount at 0; flag."),

 dict(sev="High", checks=["T25"], table="transactions", fields=["expires_at", "payment_plan_days"],
  title="Early renewals: expiry counts from the previous expiry, not from the purchase date",
  what="{T25} non-cancel rows ({T25_u} users) end more than 3 days after transacted_at + payment_plan_days. All were bought while an "
       "earlier expiry was still running, and {F_t25_match_p}% end exactly payment_plan_days after that earlier expiry. The data is "
       "correct: billing adds the new days on top of the days still left.",
  why="An analyst who computes the end as transacted_at + payment_plan_days cuts every early renewal short. That creates gaps that never "
      "happened, so users look churned (Q2), the active base dips (Q1) and long-plan renewals look shorter (Q4). Billing's own labels "
      "fall into this trap: Part 1c finds early renewals labelled as churned.",
  qs=["Q1", "Q2", "Q4"],
  sql="SELECT * FROM t_prev\nWHERE is_cancel = 0 AND payment_plan_days > 0 AND prev_exp > transacted_at\n"
      "  AND datediff('day', strptime(transacted_at::VARCHAR, '%Y%m%d'), strptime(expires_at::VARCHAR, '%Y%m%d')) - payment_plan_days > 3;"
      "  -- t_prev: view in 01_data_quality.sql (t + prev_exp = latest expiry of the user's earlier rows)",
  alts=[dict(name="End = transacted_at + payment_plan_days",
             desc="Recompute every period end from the purchase date and the plan length, ignoring expires_at (one rule for all rows).",
             cost="One expression", storage="None", speed="Seconds",
             loss="High: cuts {T25} early renewals short, creating gaps and churn that never happened"),
        dict(name="End = expires_at as billed",
             desc="expires_at is the membership end; a purchase before the current expiry continues the same episode.",
             cost="One window function", storage="None", speed="Seconds", loss="None")],
  why_b="expires_at is what billing actually granted. Recomputing it from the plan length throws that away and invents churn.",
  decision="Use expires_at as the period end (as built in 1b); never recompute it from payment_plan_days."),
]

# Type and fixability of each issue (keyed by the issue's first check).
# Data Bug = the data in the file is missing or wrong; Analytical Gotcha = the data is correct but misleads.
BUG, GOT = "Data Bug", "Analytical Gotcha"
CLASS = {"L6": (BUG, "None"), "T9": (BUG, "Partial"), "T2": (GOT, "Full"),
         "T23": (BUG, "Partial"), "U11": (BUG, "None"), "U5": (BUG, "None"), "T11": (GOT, "Full"), "T12": (GOT, "Full"), "T25": (GOT, "Full"),
         "T15": (GOT, "Full"), "T8": (GOT, "Full"), "T24": (GOT, "Full"),
         "T17": (BUG, "Partial"), "T16": (BUG, "Partial"), "T18": (BUG, "Partial"), "T19": (BUG, "None"), "T7": (BUG, "Full"),
         "U7": (BUG, "Partial"), "T10": (BUG, "Partial"), "T4": (GOT, "Full"), "T6": (GOT, "Full")}
# Order rule: severity first (the brief: impact on leadership's answers); within a severity, Data Bugs before Analytical Gotchas.
ORDER = ["L6", "T9", "T2", "T23", "U11", "U5", "T11", "T12", "T25", "T15", "T8", "T24",
         "T17", "T16", "T18", "T19", "T7", "U7", "T10", "T4", "T6"]
assert set(ORDER) == set(CLASS) == {i["checks"][0] for i in ISSUES} and len(ORDER) == len(ISSUES)
ISSUES.sort(key=lambda i: ORDER.index(i["checks"][0]))
_SEV = ["Critical", "High", "Medium", "Low"]
for _a, _b in zip(ISSUES, ISSUES[1:]):
    _ka, _kb = (_SEV.index(_a["sev"]), CLASS[_a["checks"][0]][0] != BUG), (_SEV.index(_b["sev"]), CLASS[_b["checks"][0]][0] != BUG)
    assert _ka <= _kb, f"order breaks the rule at {_a['checks'][0]} -> {_b['checks'][0]}"
for _n, _i in enumerate(ISSUES, 1):
    _i["rank"] = _n
    _i["chosen"] = 1
    _i["kind"], _i["fix"] = CLASS[_i["checks"][0]]

NOT_ISSUES = [
 ("T20", "expires_at = 2017-03-31 spike", "Checked and rejected as a cap: {F_t20_0228} of these rows were bought on 2017-02-28. It is month-end billing (Jan 31 -> Feb 28 -> Mar 31)."),
 ("U10", "Registered users with no transactions", "Free users who never subscribed. Not an error; they are the denominator for conversion."),
 ("L8", "Label base rate", "{L8_pr}% of labelled users churned. Context for 1c."),
]

# Second-opinion review: an independent AI review (Gemini) of the same raw files, checked claim by claim.
REVIEW = [
 ("DQ-01 users missing from users.csv: 109,330 'paying' users, 697,306 rows, about 71.7M revenue",
  "Agree, with a correction", "Rows, users and revenue reproduce ({T23}, {T23_u}, {F_t23_rev}). But only {F_t23_payers} of them ever paid; "
  "the rest have only free or cancel rows, so 'paying users' overstates it. Revenue impact ({F_t23_rev_p}% of total) added to issue T23. "
  "Their option A (decoupled reporting) adopted as alternative A."),
 ("DQ-02 27,606 labelled users missing from users.csv (11.42%)", "Agree", "Same as L5: {L5} users, {L5_pr}%."),
 ("DQ-03 export split: export_2 holds March 2017 plus 89,728 older long plans", "Agree on the numbers, correct the mechanism",
  "{T2} older rows reproduce. The cause is a split on expiry date, not a cut in February: export_1 has {T1} rows expiring after "
  "2017-03-31 (check T1). Their option A (append March only) adopted as alternative A."),
 ("DQ-04 age: 1,136,467 unusable; 1,028 above 100; minimum -51; median 28", "Partly correct",
  "1,136,467 = ages outside 1-100 (reproduces: {F_age_1_100}). We use 4-92 ({U11}); see issue U11 for why each edge sits where it does. Above 100 is {F_age_gt100}, not 1,028; minimum is {F_age_min}, "
  "not -51; median of valid ages is {F_age_med}."),
 ("DQ-05 gender missing 65.43%", "Agree", "Same as U5: {U5} users, {U5_pr}%. Their option A (complete-case) adopted as alternative A."),
 ("DQ-06 217,411 rows with plan_days = 0, about 90% are 30 days by date difference", "Correct the scope and the share",
  "{F_pd0_rows} includes {T13} free 0-day rows (T13); the paid metadata gap is T9 = {T9}. Exactly 30 days: {F_t9_eq30_p}%; "
  "25-35 days: {F_t9_25_35_p}% (normal paid 30-day rows: {F_p30_25_35_p}%). Date imputation still holds; "
  "their 'every 149 payment = 30 days' became the price-lookup alternative."),
 ("DQ-07 merge same-day rows (sum paid, max expiry, cancel wins); 154,306 rows / 56,920 users", "Disagree with the fix",
  "Counts reproduce across files ({F_sd_rows} / {F_sd_users}). Merging turns {F_sd_mixed} cancel + new-plan days into "
  "cancellations and collapses stacked prepaid months worth {F_t24_rev_m} (T24). Kept as alternative A for T8 and T24, not chosen."),
 ("DQ-08 cancels move expiry earlier; effective end = transacted_at", "Disagree with the fix",
  "Count reproduces ({F_cx_neg_all} incl. {F_cx_epoch} epoch rows; T15 counts {T15} and excludes them). The brief defines the cancel "
  "row's expires_at as the new expiry; ending at transacted_at cuts a median {F_cx_after_med} days on {F_cx_after} cancels. "
  "Kept as alternative A."),
 ("DQ-10 zero-paid rows: 304,317 rows / 221,619 users", "Agree, split differently",
  "{F_zp_rows} = {F_zp_cancel} cancel rows + {T11} discounted trials (T11) + {T12} unpriced passes (T12). The split matters "
  "for Q3. Their option A (delete) is not realistic; ours compares one table vs a separate trial table."),
 ("DQ-12 13,756 users registered in April 2017", "Agree, added",
  "Same as U7: {U7} users. Their point that conversion would show 0% for them is added to U7."),
 ("Round 2: move T23 from rank 4 to rank 2", "Agree",
  "Labelled users missing from users.csv churn at {F_l5_churn}% vs {F_reg_churn}%; an inner join biases Q2. Moved up to High."),
 ("Round 2: age cap at 80 drops real older users; ages 106 and 112 are Taiwanese (ROC) calendar years", "Agree on the cap, not the cause",
  "Cap raised to 92: ages 81-92 look like real users ({F_age_8192_lo}-{F_age_8192_hi} per year). The ROC idea does not hold: most "
  "age-106 users registered in 2014-2015, not 2017 (ROC 106), and 112 matches no recent ROC year. Lower bound later set to 4 (ages 1-3 look like unfilled profiles)."),
 ("Not in the second opinion", "Our additions",
  "T4, T6, T24, L4, L6, L7, T16, T17, T18, T19 and T7."),
]

CORRECTIONS = [
 "\"11,560 conflicting versions between exports\" was wrong: that counted (user, day) matches, which is not a key (T8). "
 "Real conflicting versions of one event: {T4} rows / {T4_u} users.",
 "\"export_1 expires_at capped at 2017-03-31\" was wrong. The spike is month-end billing (T20); export_1 is filtered on expiry, not capped (T1-T3).",
 "\"export_2 = March 2017 plus a backfill tail\" undersold it: export_2 is every row expiring after Feb 2017.",
 "Loader bug (fixed): `00_load_raw.sql` dropped the alias instead of the `filename` column, so every one of the 5.7M rows carried the file path.",
 "Non-determinism (fixed): the 'due in March' check used `arg_max` with same-day ties, so L6/L7 changed between runs. "
 "The tie-break is now deterministic; consecutive runs give byte-identical outputs.",
 "The first fix for T4 still over-counted (1,561 rows): stacked purchases (T24) match many-to-many across files. "
 "Restricting to one-to-one matches gives {T4} rows. Found because the T4 detection query returned 10,588 rows while the check "
 "said 1,561; every detection query is now validated against its check at build time.",
 "Hard-coded text drifted from the data: the age minimum was written as -505; the real minimum is {F_age_min}. Supporting numbers "
 "are now computed by SQL at build time (FACTS in the generator), not typed.",
 "Several 'alternative A' options were strawmen (keep all copies, trust the raw value, treat as normal subscriptions, keep the "
 "negative discount). Each is now an option a competent engineer could ship, with a stated reason why B wins.",
 "Second-opinion claims rejected after checking: '109,330 paying users' (only {F_t23_payers} paid); 'about 90% of 0-day rows are "
 "30 days' (exactly 30: {F_t9_eq30_p}%; 25-35: {F_t9_25_35_p}%); 'over-100 ages = 1,028' ({F_age_gt100}); 'minimum age -51' "
 "({F_age_min}); 'export cut in February' (split on expiry); merge same-day rows and end cancels at transacted_at (both lose real events).",
 "Ranking (Claude, caught by the user): Claude first kept billing's churn labels (L6) at Medium and argued the export split must stay #1, "
 "without re-reading the brief's rule ('rank the issues by how much they affect the answers leadership is asking for'). The user pointed "
 "out that the labels are most likely the churn number the CEO already saw. Under the brief's rule they are Critical, and now rank #1.",
 "Ranking review (Claude, prompted by the user): the earlier order under-rated the 2015 missing plan length (T9 touches {F_t9_win_p}% of "
 "users active Mar-Oct 2015; now Critical), rated gender (U5) below age (U11) although both are about 65% missing and hit the same "
 "question, and rated unpriced free periods (T12) below free trials (T11) although T12 is larger. All three fixed.",
 "Missed issue (Claude, found after the user asked about wrongly computed plan durations): early renewals (T25) were handled in the "
 "clean layer (1b) but were missing from this list. Claude first rated it Medium, then corrected it to High: it creates false churn, "
 "and billing's own labels fall into it.",
]

# ---------------------------------------------------------------------------
# LEGEND: a short plain-English name for every check ID, and every view / term used in the text.
# The full definition of each check is dq_summary.check_name (from the SQL). Rendered at the top of md, html and xlsx.
# ---------------------------------------------------------------------------
PREFIX = [("T", "transactions", "both billing exports, combined as base_transactions"),
          ("U", "users", "the user registry, users.csv (raw_users)"),
          ("L", "churn_labels", "billing's churn labels for March 2017, churn_labels.csv (raw_churn_labels)")]
SEV_DEF = [("Critical", "If ignored, a headline answer is wrong (e.g. the active base or annual-plan counts)."),
           ("High", "If ignored, at least one leadership question is clearly distorted."),
           ("Medium", "Distorts one cut or the churn rule; handled in the clean layer."),
           ("Low", "Small or narrow; a simple rule and a flag handle it.")]
KIND_DEF = [("Data Bug", "Values missing or wrong: can be flagged or estimated, not fully restored."),
            ("Analytical Gotcha", "Values correct but misleading; one rule handles it fully.")]
FIX_DEF = [("Full", "Fully handled in the clean layer."),
           ("Partial", "Estimated or flagged; some doubt remains."),
           ("None", "Cannot be repaired; shown as 'Unknown' or replaced by our own rule.")]
ORDER_RULE = ("Order: severity first (how much the answers to Q1-Q4 change if the issue is ignored). "
              "Within the same severity, Data Bugs come first, because they cannot be fully fixed.")
SHORT = {
 "U1": "age = 0, the missing-value code", "U2": "negative age", "U3": "age 1-3", "U4": "age above 92", "U5": "gender missing",
 "U6": "invalid registration date", "U7": "registered after data end", "U8": "registered after first payment",
 "U9": "duplicate user_id in users", "U10": "registered, never transacted", "U11": "age unusable: outside 4-92",
 "T1": "export_1 rows expiring after March 2017", "T2": "old purchases in export_2", "T3": "long plans only in export_2",
 "T4": "same event, conflicting versions across exports", "T5": "same event, identical in both exports",
 "T6": "same user and day, different events across exports", "T7": "exact duplicate rows",
 "T8": "user_id + transacted_at not unique", "T9": "paid rows missing plan length and list price",
 "T10": "paid above list price", "T11": "free trial / 100% discount", "T12": "unpriced free period",
 "T13": "0 plan days, other rows", "T14": "cancellations", "T15": "cancel moves expiry earlier",
 "T16": "expiry before purchase, non-cancel row", "T17": "expiry 1970-01-01 placeholder", "T18": "expiry before 2015",
 "T19": "expiry after 2019-03-31", "T20": "expiry spike on 2017-03-31", "T21": "invalid date", "T22": "transaction after data end",
 "T23": "users missing from users.csv", "T24": "stacked purchases", "T25": "early renewal",
 "L1": "duplicate label", "L2": "invalid is_churn value", "L3": "labelled user with no transactions",
 "L4": "labelled user, no transaction by 2017-02-28", "L5": "labelled user missing from users.csv",
 "L6": "labelled but not 'due in March'", "L7": "'due in March' but unlabelled", "L8": "churn label base rate",
}
TERMS = [
 ("export_1, export_2", "The two billing files, transactions_export_1.csv and transactions_export_2.csv. Same columns; their overlap was undocumented."),
 ("raw_users, raw_transactions_export_1, raw_transactions_export_2, raw_churn_labels", "The four files loaded into DuckDB unchanged: one table per file, same rows and columns."),
 ("base_transactions", "Both exports combined in one table (sql/00_union_exports.sql), values unchanged, plus src_file and src_row. The checks on transactions run on this table."),
 ("src_file", "Which export a transaction row came from: 1 or 2. Added in base_transactions."),
 ("src_row", "The row's position: export_1 rows in file order, then export_2. A stable ID that traces each row back to its file and line, and breaks ties."),
 ("t", "View: base_transactions with the business columns plus src_file and src_row."),
 ("event core", "user_id, transacted_at, payment_method, payment_plan_days, amount_paid, is_cancel. Rows with the same core describe the same purchase."),
 ("t_core", "View: t plus n_core = how many rows in the same file share the event core."),
 ("x_core_match", "View: export_1 rows matched to export_2 rows on the event core."),
 ("x_pairs", "View: the one-to-one matches in x_core_match (stacks excluded). Used by T4."),
 ("x_keys_complementary", "View: (user_id, transacted_at) pairs present in both exports with no core match, i.e. different events. Used by T6."),
 ("due_mar", "View: users whose last transaction up to 2017-02-28 expires in March 2017. A naive version of the label population, used by L6 and L7."),
 ("dq_summary", "Table: one row per check, with rows, users and % of the table. Source of every count in this report."),
 ("t_prev", "View: t plus prev_exp = the latest expiry of the user's earlier rows. Used by T25."),
 ("stack, stacked purchase", "The same purchase repeated on one day, each copy pushing the expiry further out (T24)."),
 ("period", "A continuous stretch of access built from the transactions. Built in Part 1b."),
 ("active base", "Users with access (paid or free) on a given day."),
 ("ARPU", "Average revenue per user."),
 ("grain", "What one row of a table represents (one event, one user-day, one period)."),
 ("as-of column", "A column that keeps a value as it was known at an earlier date, e.g. expires_at_asof_feb."),
 ("epoch placeholder", "1970-01-01, the zero date of computer clocks, used by the source system for 'unknown'."),
 ("complete-case", "Analysing only the rows where a field is filled in."),
 ("A / B", "Two realistic fixes per issue. B is the one chosen; 'Why B over A' gives the reason."),
]
ID_RE = re.compile(r"(?<![\w/\-])([TUL]\d{1,2})(?![\w/\-])")


def expand(text, seen):
    """Put the short name next to each check ID on its first use (per issue); later uses stay bare."""
    def rep(m):
        c = m.group(1)
        if c not in SHORT or c in seen:
            return c
        seen.add(c)
        s, e = m.start(), m.end()
        if text[s - 1:s] == "(" and text[e:e + 1] == ")":
            return f"{c}: {SHORT[c]}"
        return f"{c} ({SHORT[c]})"
    return ID_RE.sub(rep, text)


# ---------------------------------------------------------------------------
summ = {r[0]: dict(zip(["id", "tbl", "name", "rows", "users", "pct_rows", "pct_users"], r))
        for r in con.sql("SELECT * FROM dq_summary").fetchall()}
totals = dict(users=con.sql("SELECT count(*) FROM raw_users").fetchone()[0],
              tx_rows=con.sql("SELECT count(*) FROM base_transactions").fetchone()[0],
              tx_users=con.sql("SELECT count(DISTINCT user_id) FROM base_transactions").fetchone()[0],
              labels=con.sql("SELECT count(*) FROM raw_churn_labels").fetchone()[0])
passed = [s for s in summ.values() if s["rows"] == 0]
f = lambda n: f"{n:,}"
pct = lambda a, b: f"{100 * a / b:.1f}"
mil = lambda x: f"{x / 1e6:.1f}M"

# Placeholders: {CHECK} rows, {CHECK_u} users, {CHECK_pr}/{CHECK_pu} % of table, {F_x} facts (+ derived _p %, _m millions).
N = {}
for k, v in summ.items():
    N[k], N[k + "_u"], N[k + "_pr"], N[k + "_pu"] = f(v["rows"]), f(v["users"]), v["pct_rows"], v["pct_users"]
    N[k + "_pr_rest"], N[k + "_pu_rest"] = f"{100 - v['pct_rows']:.2f}", f"{100 - v['pct_users']:.2f}"
for k, v in F.items():
    N["F_" + k] = f(v) if isinstance(v, int) else v
N.update(F_t9_win_p=pct(F["t9_win_hit"], F["t9_win_users"]), F_t9_paid_p=pct(F["t9_win_t9"], F["t9_win_paid"]), F_t25_match_p=pct(F["t25_match"], summ["T25"]["rows"]),
         F_rev_total_m=mil(F["rev_total"]), F_t23_rev_m=mil(F["t23_rev"]), F_t24_rev_m=mil(F["t24_rev"]),
         F_t23_rev_p=pct(F["t23_rev"], F["rev_total"]),
         F_t9_eq30_p=pct(F["t9_eq30"], summ["T9"]["rows"]), F_t9_25_35_p=pct(F["t9_25_35"], summ["T9"]["rows"]),
         F_p30_25_35_p=pct(F["p30_25_35"], F["p30_rows"]),
         F_sd_rows_less=f(F["sd_rows"] - con.sql("SELECT count(*) FROM (SELECT 1 FROM t GROUP BY user_id, transacted_at HAVING count(*) > 1)").fetchone()[0]),
         F_cx_epoch=f(F["cx_neg_all"] - summ["T15"]["rows"]))
assert set(SHORT) == set(summ), f"SHORT names out of sync with dq_summary: {set(SHORT) ^ set(summ)}"
for i in ISSUES:
    seen = set(i["checks"])  # the issue's own checks are named on its 'Checks' line
    for key in ("title", "what", "why"):
        i[key] = expand(i[key].format(**N), seen)
    for a in i["alts"]:
        for key in ("name", "desc", "cost", "storage", "speed", "loss"):
            a[key] = expand(a[key].format(**N), seen)
    for key in ("why_b", "decision"):
        i[key] = expand(i[key].format(**N), seen)
NOT_ISSUES = [(c, n, expand(t.format(**N), {c})) for c, n, t in NOT_ISSUES]
REVIEW = [(a, b, expand(c.format(**N), set())) for a, b, c in REVIEW]
CORRECTIONS = [expand(c.format(**N), set()) for c in CORRECTIONS]
SEV_ORDER = ["Critical", "High", "Medium", "Low"]
# status of every check for the legend
ISSUE_OF = {}
for i in ISSUES:
    for c in i["checks"]:
        ISSUE_OF.setdefault(c, i["rank"])


ISSUE_ID = {c: i["checks"][0] for i in ISSUES for c in i["checks"]}


def check_status(cid):
    if cid in ISSUE_OF:
        return f"Issue #{ISSUE_OF[cid]}"
    if summ[cid]["rows"] == 0:
        return "Passed (0 rows)"
    return "Not an issue / info"


LEGEND_ORDER = sorted(summ.values(), key=lambda s: ("TUL".index(s["id"][0]), int(s["id"][1:])))
passed_sorted = sorted(passed, key=lambda s: ("TUL".index(s["id"][0]), int(s["id"][1:])))


def checks_line(i):
    return " · ".join(f"**{c}** {SHORT[c]}: {f(summ[c]['rows'])}" for c in i["checks"])


def size(i):
    s = summ[i["checks"][0]]
    return s["rows"], s["users"], s["pct_rows"], s["pct_users"]


# ---------------------------------------------------------------------------
# 0. Validation: every catalog detection query (first statement) must return exactly its check's row count.
# ---------------------------------------------------------------------------
def first_stmt(sql):
    lines = sql.split("\n")
    while lines and lines[0].lstrip().startswith("--"):
        lines.pop(0)
    return "\n".join(lines).split(";")[0]


for i in ISSUES:
    got = con.sql(f"SELECT count(*) FROM (\n{first_stmt(i['sql'])}\n)").fetchone()[0]
    want = summ[i["checks"][0]]["rows"]
    assert got == want, f"detection SQL for {i['checks'][0]} returns {got:,}, check says {want:,}"
    i["validated"] = got
print(f"validated {len(ISSUES)} detection queries against dq_summary")

# ---------------------------------------------------------------------------
# 1. Markdown report
# ---------------------------------------------------------------------------
md = []
md += ["# Part 1a: Data-Quality Report", "",
       "Generated by `py/01_dq_outputs.py` from the `dq_*` tables built in `sql/01_data_quality.sql`. Every number is computed at "
       "run time. Every detection query is re-run and must return exactly its check's row count. So this report, the workbook "
       "(`reports/01_data_quality.xlsx`), the page (`reports/01_data_quality.html`) and the SQL always agree.", "",
       "| Table | Rows | Users |", "|:---:|:---:|:---:|",
       f"| users | {f(totals['users'])} | {f(totals['users'])} |",
       f"| transactions (export_1 + export_2) | {f(totals['tx_rows'])} | {f(totals['tx_users'])} |",
       f"| churn_labels | {f(totals['labels'])} | {f(totals['labels'])} |", "",
       "## How to read this report", "",
       "- **Check IDs.** Every finding comes from one check in `sql/01_data_quality.sql`. The letter names the table: "
       + "; ".join(f"**{p}** = {t} ({d})" for p, t, d in PREFIX) + ". The number is only the check's position. "
       "The full list of checks and the names used in the text are in the legend at the end of this section.",
       "- **Leadership questions:** " + "; ".join(f"**{k}** {v}" for k, v in Q.items()) + ".",
       "- **Severity** (how much the answers change if the issue is ignored):"] + [f"  - **{k}:** {v}" for k, v in SEV_DEF] + [
       "- **Type:**"] + [f"  - **{k}:** {v}" for k, v in KIND_DEF] + [
       "- **Fix** (can it be repaired?):"] + [f"  - **{k}:** {v}" for k, v in FIX_DEF] + [
       f"- **{ORDER_RULE.split(': ', 1)[0]}:** {ORDER_RULE.split(': ', 1)[1]}",
       "- **Options A / B:** two realistic fixes per issue. B is chosen; 'Why B over A' gives the reason.", "",
       "### Legend: check IDs", "",
       "Short name = the name used in the text. Definition = the exact rule the SQL counts (`dq_summary.check_name`).", "",
       "| Check | Table | Short name | Definition (what the SQL counts) | Rows | Status |", "|:---:|:---:|:---:|:---:|:---:|:---:|"]
md += [f"| {s['id']} | {s['tbl']} | {SHORT[s['id']]} | {s['name']} | {f(s['rows'])} | {check_status(s['id'])} |" for s in LEGEND_ORDER]
md += ["", "### Legend: names and terms used in the text", "", "| Name | Meaning |", "|:---:|:---:|"]
md += [f"| {a} | {b} |" for a, b in TERMS]
md += ["", "## Ranked issues", "",
       ORDER_RULE + " Size comes from the first check listed. Percentages are of the table's rows and users.", "",
       "| Rank | Severity | Type | Fix | Checks | Table.field | Issue | Rows | Users | % rows | % users | Questions | Decision |",
       "|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|"]
for i in ISSUES:
    r, u, pr, pu = size(i)
    md.append(f"| {i['rank']} | {i['sev']} | {i['kind']} | {i['fix']} | {', '.join(i['checks'])} | {i['table']}.{', '.join(i['fields'])} | {i['title']} | "
              f"{f(r)} | {f(u)} | {pr}% | {pu}% | {', '.join(i['qs'])} | {i['decision']} |")
md += ["", "## Issue detail", "",
       "Each issue: what is broken, how big, why it matters, the query that finds it, two fixes (A, B), and the decision.", ""]
for i in ISSUES:
    r, u, pr, pu = size(i)
    md += [f"### {i['rank']}. {i['title']}", "",
           f"- **Severity:** {i['sev']}. **Type:** {i['kind']}. **Fix:** {i['fix']}. **Questions hit:** " + "; ".join(f"{q} ({Q[q]})" for q in i["qs"]) + ".",
           f"- **Checks** (rows): {checks_line(i)}",
           f"- **What is broken:** {i['what']}",
           f"- **Size ({i['checks'][0]}):** {f(r)} rows ({pr}% of {i['table']}), {f(u)} users ({pu}%).",
           f"- **Why it matters:** {i['why']}",
           f"- **How found** (returns {f(i['validated'])} rows, validated against {i['checks'][0]}):", "", "```sql", i["sql"], "```", "",
           "| Option | Approach | Run cost | Storage | Speed / latency | Data-loss / bias risk | Verdict |",
           "|:---:|:---:|:---:|:---:|:---:|:---:|:---:|"]
    for k, a in enumerate(i["alts"]):
        md.append(f"| {'AB'[k]}: {a['name']} | {a['desc']} | {a['cost']} | {a['storage']} | {a['speed']} | {a['loss']} | "
                  f"{'**Chosen**' if k == i['chosen'] else 'Rejected'} |")
    md += ["", f"- **Why B over A:** {i['why_b']}", f"- **Decision:** {i['decision']}", ""]
md += ["## Checked and not an issue", "", "| Check | What | Finding |", "|:---:|:---:|:---:|"]
md += [f"| {c} | {n} | {t} |" for c, n, t in NOT_ISSUES]
md += [f"| {', '.join(s['id'] for s in passed_sorted)} | Zero-row checks (passed) | "
       + "; ".join(f"{s['id']} {s['name']}" for s in passed_sorted) + " |", ""]
md += ["## Second-opinion review (Gemini), checked claim by claim", "",
       "An independent AI review of the same files. Every number it gave was re-run in DuckDB before being accepted.", "",
       "| Second-opinion claim | Verdict | Evidence (from SQL) |", "|:---:|:---:|:---:|"]
md += [f"| {a} | {b} | {c} |" for a, b, c in REVIEW]
md += ["", "## Corrections to earlier assumptions (for the AI log, 5b)", ""]
md += [f"{n}. {c}" for n, c in enumerate(CORRECTIONS, 1)] + [""]
(ROOT / "reports/01_data_quality.md").write_text("\n".join(md))

# ---------------------------------------------------------------------------
# 2. Excel workbook (calm blue palette, centered, no italics)
# ---------------------------------------------------------------------------
NAVY, BLUE, LIGHT, PALE = "1F3864", "2E75B6", "DDEBF7", "F3F8FC"
FONT = "Arial"
thin = Side(style="thin", color="BDD7EE")
BORDER = Border(left=thin, right=thin, top=thin, bottom=thin)
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)
RIGHT = Alignment(horizontal="right", vertical="center", wrap_text=True, readingOrder=2)
SEV_FILL = {"Critical": NAVY, "High": BLUE, "Medium": "9DC3E6", "Low": LIGHT}


def title(ws, text, sub):
    ws["A1"] = text
    ws["A1"].font = Font(name=FONT, size=16, bold=True, color=NAVY)
    ws["A2"] = sub
    ws["A2"].font = Font(name=FONT, size=10, color="404040")
    ws.row_dimensions[1].height = 26


def header(ws, row, cols):
    for c, h in enumerate(cols, 1):
        cell = ws.cell(row=row, column=c, value=h)
        cell.font = Font(name=FONT, bold=True, color="FFFFFF", size=10)
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.alignment = CENTER
        cell.border = BORDER
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def body(cell, fill=None, bold=False, color="000000", align=CENTER, fmt=None):
    cell.font = Font(name=FONT, size=10, bold=bold, color=color)
    cell.alignment = align
    cell.border = BORDER
    if fill:
        cell.fill = PatternFill("solid", fgColor=fill)
    if fmt:
        cell.number_format = fmt


def widths(ws, w):
    for k, v in enumerate(w, 1):
        ws.column_dimensions[get_column_letter(k)].width = v


wb = Workbook()

# --- Read me -----------------------------------------------------------------
ws = wb.active
ws.title = "Read me"
title(ws, "Tune: Data-Quality Workbook (Part 1a)", "Generated by py/01_dq_outputs.py from tune.duckdb. Do not edit by hand; rerun run_all.py.")
rows = [("Tab", "What it shows"),
        ("Legend", "Start here: what each check ID (T = transactions, U = users, L = churn_labels), short name, view and term means."),
        ("Issues ranked", "Every issue ranked by impact on Q1-Q4: size, why it matters, detection SQL, decision. % cells are formulas over the totals below."),
        ("Trade-offs", "Two realistic engineering alternatives per issue: run cost, storage, speed, data-loss risk, which one is chosen and why."),
        ("Second opinion", "An independent AI review (Gemini) checked claim by claim, plus corrections to earlier assumptions."),
        ("users / transactions / churn_labels", "All original columns plus real bad rows: one example per issue. Columns A-D explain the row; the faulty cells are highlighted."),
        ("All checks", "Every profiling check in dq_summary, including the ones that passed with 0 rows."),
        ("", ""), ("Table totals (inputs for % formulas)", "Value"),
        ("users rows", totals["users"]), ("transactions rows", totals["tx_rows"]),
        ("transactions distinct users", totals["tx_users"]), ("churn_labels rows", totals["labels"]),
        ("", ""), ("Leadership question", "Meaning")] + list(Q.items())
for r, (a, b) in enumerate(rows, 4):
    ws.cell(row=r, column=1, value=a)
    ws.cell(row=r, column=2, value=b)
    hdr = a in ("Tab", "Table totals (inputs for % formulas)", "Leadership question")
    for c in (1, 2):
        cell = ws.cell(row=r, column=c)
        if a == "" and b == "":
            continue
        if hdr:
            body(cell, fill=NAVY, bold=True, color="FFFFFF")
        else:
            body(cell, fill=PALE if c == 1 else None, bold=(c == 1), align=CENTER if c == 1 else LEFT,
                 fmt="#,##0" if isinstance(b, int) and c == 2 else None)
widths(ws, [38, 110])
_r0 = 4 + [a for a, _ in rows].index("users rows")
TOT = {k: f"'Read me'!$B${_r0 + n}" for n, k in enumerate(("users", "transactions", "tx_users", "churn_labels"))}
for k in ("users", "transactions", "tx_users", "churn_labels"):
    c = ws[TOT[k].split("!")[1].replace("$", "")]
    c.font = Font(name=FONT, size=10, color="0000FF")
ws.cell(row=_r0, column=3, value="Source: SELECT count(*) / count(DISTINCT user_id) on raw_* tables in tune.duckdb")
ws.cell(row=_r0, column=3).font = Font(name=FONT, size=9, color="595959")


def pct_formulas(tbl, rcell, ucell):
    den_r = TOT[tbl] if tbl != "transactions" else TOT["transactions"]
    den_u = TOT[tbl] if tbl != "transactions" else TOT["tx_users"]
    return f"=IFERROR({rcell}/{den_r},0)", f"=IFERROR({ucell}/{den_u},0)"


# --- Legend ---------------------------------------------------------------------
ws = wb.create_sheet("Legend")
title(ws, "Legend: check IDs, short names, views and terms", "The letter of a check ID names the table. Definition = the exact rule the SQL counts (dq_summary.check_name).")


def block_header(ws, row, cols):
    for c, h in enumerate(cols, 1):
        body(ws.cell(row=row, column=c, value=h), fill=NAVY, bold=True, color="FFFFFF")


r = 4
block_header(ws, r, ["Prefix", "Table", "Source"])
for p_, t_, d_ in PREFIX:
    r += 1
    for c, v in enumerate([p_, t_, d_], 1):
        body(ws.cell(row=r, column=c, value=v), fill=PALE if c == 1 else None, bold=(c == 1), align=LEFT if c == 3 else CENTER)
r += 2
block_header(ws, r, ["Severity", "Meaning"])
for k_, v_ in SEV_DEF:
    r += 1
    body(ws.cell(row=r, column=1, value=k_), fill=SEV_FILL[k_], bold=True, color="FFFFFF" if k_ in ("Critical", "High") else NAVY)
    body(ws.cell(row=r, column=2, value=v_), align=LEFT)
    ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=4)
for _ttl, _defs in (("Type", KIND_DEF), ("Fix", FIX_DEF)):
    r += 2
    block_header(ws, r, [_ttl, "Meaning"])
    for k_, v_ in _defs:
        r += 1
        body(ws.cell(row=r, column=1, value=k_), fill=PALE, bold=True)
        body(ws.cell(row=r, column=2, value=v_), align=LEFT)
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=4)
r += 1
body(ws.cell(row=r, column=1, value="Order"), fill=PALE, bold=True)
body(ws.cell(row=r, column=2, value=ORDER_RULE.split(": ", 1)[1]), align=LEFT)
ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=4)
r += 2
block_header(ws, r, ["Check ID", "Table", "Short name (used in the text)", "Definition (what the SQL counts)", "Rows", "Status"])
for s_ in LEGEND_ORDER:
    r += 1
    for c, v in enumerate([s_["id"], s_["tbl"], SHORT[s_["id"]], s_["name"], s_["rows"], check_status(s_["id"])], 1):
        body(ws.cell(row=r, column=c, value=v), fill=PALE if r % 2 else None, bold=(c == 1),
             align=LEFT if c in (3, 4) else CENTER, fmt="#,##0" if c == 5 else None)
r += 2
block_header(ws, r, ["Name", "Meaning"])
for a_, b_ in TERMS:
    r += 1
    body(ws.cell(row=r, column=1, value=a_), fill=PALE, bold=True)
    body(ws.cell(row=r, column=2, value=b_), align=LEFT)
    ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=4)
widths(ws, [24, 16, 40, 90, 12, 16])

# --- Issues ranked -------------------------------------------------------------
ws = wb.create_sheet("Issues ranked")
title(ws, "Data-quality issues, ranked by impact", "Severity: Critical > High > Medium > Low. Questions: Q1 base health, Q2 churn drivers, Q3 trials & prices, Q4 annual plans.")
cols = ["Rank", "Severity", "Type", "Fix", "Checks (see Legend)", "Table", "Field(s)", "Issue", "What is broken", "Rows", "Users", "% rows", "% users",
        "Questions hit", "Why it matters", "Detection SQL", "Decision"]
header(ws, 4, cols)
for k, i in enumerate(ISSUES, 5):
    r, u, _, _ = size(i)
    pr, pu = pct_formulas(i["table"], f"J{k}", f"K{k}")
    vals = [i["rank"], i["sev"], i["kind"], i["fix"], "\n".join(f"{c}: {SHORT[c]}" for c in i["checks"]), i["table"], ", ".join(i["fields"]), i["title"], i["what"], r, u, pr, pu,
            ", ".join(i["qs"]), i["why"], i["sql"], i["decision"]]
    for c, v in enumerate(vals, 1):
        cell = ws.cell(row=k, column=c, value=v)
        body(cell, fill=PALE if k % 2 else None, align=LEFT if c in (5, 9, 15, 16, 17) else CENTER,
             fmt="#,##0" if c in (10, 11) else ("0.00%" if c in (12, 13) else None))
    sev = ws.cell(row=k, column=2)
    body(sev, fill=SEV_FILL[i["sev"]], bold=True, color="FFFFFF" if i["sev"] in ("Critical", "High") else NAVY)
    ws.cell(row=k, column=16).font = Font(name="Courier New", size=9)
widths(ws, [6, 10, 16, 9, 30, 13, 18, 34, 55, 11, 11, 9, 9, 11, 55, 55, 45])

# --- Trade-offs ----------------------------------------------------------------
ws = wb.create_sheet("Trade-offs")
title(ws, "Remediation trade-offs: two alternatives per issue", "The chosen option is highlighted. Run cost = compute per full rebuild (DuckDB, 5.7M transaction rows).")
cols = ["Rank", "Issue", "Option", "Approach", "Run cost", "Storage", "Speed / latency", "Data-loss / bias risk", "Verdict", "Why B over A"]
header(ws, 4, cols)
row = 5
for i in ISSUES:
    for k, a in enumerate(i["alts"]):
        chosen = k == i["chosen"]
        vals = [i["rank"], i["title"], f"{'AB'[k]}: {a['name']}", a["desc"], a["cost"], a["storage"], a["speed"], a["loss"],
                "Chosen" if chosen else "Rejected", i["why_b"] if chosen else ""]
        for c, v in enumerate(vals, 1):
            cell = ws.cell(row=row, column=c, value=v)
            body(cell, fill=LIGHT if chosen else None, bold=(chosen and c in (3, 9)),
                 align=LEFT if c in (2, 4, 8, 10) else CENTER)
        row += 1
widths(ws, [6, 38, 30, 50, 24, 20, 14, 40, 10, 45])

# --- One tab per raw table: all original columns + real bad rows ---------------
by_check = {}
for i in ISSUES:
    for c in i["checks"]:
        by_check.setdefault(c, i)
EXTRA = {"T20": ("T20 is NOT an issue: month-end billing (bought 2017-02-28, expires 2017-03-31). Shown because it was a suspected cap.", ["expires_at"]),
         "T13": ("Zero-length free row (plan_days = 0, no price): it creates no subscription period. Part of T12.", ["payment_plan_days"]),
         "T2": None}


def example_tab(name, table, orig_cols):
    ws = wb.create_sheet(name)
    title(ws, f"{name}: real problem rows (one example per issue)",
          "Columns A-D explain the row; then every original column, unchanged. Highlighted cells = the faulty field(s).")
    rows = con.sql(f"SELECT * FROM {table}").fetchall()
    cols = [d[0] for d in con.sql(f"SELECT * FROM {table} LIMIT 0").description]
    header(ws, 4, ["Check ID", "Issue", "Faulty field(s)", "What is wrong in this row"] + orig_cols)
    for k, rec in enumerate(rows, 5):
        d = dict(zip(cols, rec))
        cid = d["issue"].split()[0]
        i = by_check.get(cid)
        if cid in EXTRA and EXTRA[cid]:
            note, flds = EXTRA[cid]
        else:
            note, flds = (i["what"] if i else d["issue"]), (i["fields"] if i else [])
        vals = [cid, d["issue"].split(" ", 1)[1], ", ".join(flds), note] + [d[c] for c in orig_cols]
        for c, v in enumerate(vals, 1):
            cell = ws.cell(row=k, column=c, value=v)
            is_bad = c > 4 and orig_cols[c - 5] in flds
            body(cell, fill=LIGHT if is_bad else (PALE if c <= 4 else None), bold=is_bad or c == 1,
                 color=NAVY if is_bad else "000000", align=LEFT if c == 4 else CENTER)
    widths(ws, [9, 34, 22, 70] + [max(12, len(c) + 4) for c in orig_cols])


example_tab("users", "dq_examples_users", ["user_id", "city", "age", "gender", "acquisition_channel", "registered_at"])
example_tab("transactions", "dq_examples_transactions",
            ["user_id", "payment_method", "payment_plan_days", "list_price", "amount_paid", "is_auto_renew",
             "transacted_at", "expires_at", "is_cancel", "src_file", "src_row"])
example_tab("churn_labels", "dq_examples_churn_labels", ["user_id", "is_churn"])

# --- All checks ----------------------------------------------------------------
ws = wb.create_sheet("All checks")
title(ws, "All profiling checks (dq_summary)", "Rows/users from SQL; % columns are formulas over the totals on 'Read me'. 0-row checks passed.")
header(ws, 4, ["Check ID", "Table", "Check", "Rows", "Users", "% rows", "% users", "Status"])
order = sorted(summ.values(), key=lambda s: (s["tbl"], s["id"][0], int(s["id"][1:])))
for k, s in enumerate(order, 5):
    pr, pu = pct_formulas(s["tbl"], f"D{k}", f"E{k}")
    status = "Passed" if s["rows"] == 0 else ("Info" if s["id"] in ("T14", "U10", "L8", "T20") else "Issue")
    for c, v in enumerate([s["id"], s["tbl"], s["name"], s["rows"], s["users"], pr, pu, status], 1):
        cell = ws.cell(row=k, column=c, value=v)
        body(cell, fill=PALE if k % 2 else None, align=LEFT if c == 3 else CENTER,
             fmt="#,##0" if c in (4, 5) else ("0.00%" if c in (6, 7) else None))
widths(ws, [9, 14, 80, 12, 12, 9, 9, 9])


# --- Second opinion + corrections -----------------------------------------------
ws = wb.create_sheet("Second opinion")
title(ws, "Second-opinion review (Gemini), checked claim by claim", "Every number was re-run in DuckDB before being accepted.")
header(ws, 4, ["Second-opinion claim", "Verdict", "Evidence (from SQL)"])
for k, (a, b, c) in enumerate(REVIEW, 5):
    for col, v in enumerate([a, b, c], 1):
        body(ws.cell(row=k, column=col, value=v), fill=PALE if k % 2 else None, bold=(col == 2), align=CENTER if col == 2 else LEFT)
r0 = 5 + len(REVIEW) + 1
header_row = r0
for col, h in enumerate(["#", "Correction to an earlier assumption (AI log, 5b)"], 1):
    cell = ws.cell(row=header_row, column=col, value=h)
    body(cell, fill=NAVY, bold=True, color="FFFFFF")
for k, c in enumerate(CORRECTIONS, 1):
    body(ws.cell(row=header_row + k, column=1, value=k), fill=PALE, bold=True)
    body(ws.cell(row=header_row + k, column=2, value=c), align=LEFT)
    ws.merge_cells(start_row=header_row + k, start_column=2, end_row=header_row + k, end_column=3)
widths(ws, [48, 26, 110])

wb.save(ROOT / "reports/01_data_quality.xlsx")


# ---------------------------------------------------------------------------
# 3. HTML page (same catalog and numbers; static render + small filter script; data embedded as JSON for the dashboard)
# ---------------------------------------------------------------------------
E = lambda s: html.escape(str(s), quote=True)
TERM_ANCHOR = {}
for _n, (_a, _b) in enumerate(TERMS):
    for _t in _a.split(", "):
        TERM_ANCHOR[_t] = f"term-{_n}"
_LINKABLE = ["export_1", "export_2", "src_file", "src_row", "t_core", "x_core_match", "x_pairs", "x_keys_complementary", "due_mar", "dq_summary"]
LINK_RE = re.compile(r"(?<![\w])([TUL]\d{1,2})(?!\w)|\b(" + "|".join(_LINKABLE) + r")\b")


def cid(c):
    return (f'<a class="cid" href="#legend-{c}" title="{E(c + ": " + SHORT[c] + " · " + summ[c]["name"])}">{c}</a>'
            if c in SHORT else c)


def L(text):
    """Escape, then turn every check ID into a hover + link to the legend, and every view/term into a link to its definition."""
    def rep(m):
        if m.group(1):
            return cid(m.group(1))
        t = m.group(2)
        meaning = dict(TERMS)[next(a for a in dict(TERMS) if t in a.split(", "))]
        return f'<a class="term" href="#{TERM_ANCHOR[t]}" title="{E(t + ": " + meaning)}">{t}</a>'
    return LINK_RE.sub(rep, E(text))


_C, _CS = r"[\x21-\x27\x2a-\x7e]", r"[\x20-\x27\x2a-\x7e]"   # printable ASCII without parentheses (with / without space)
_UNIT = rf"(?:{_C}|\({_CS}*\))"                                    # one char, or a balanced (...) group
BIDI_RE = re.compile(rf"{_UNIT}(?:(?:{_CS}|\({_CS}*\))*{_UNIT})?")  # an English run; unbalanced parens stay outside


def bidi(text):
    """Hebrew text: isolate each run of English (field names, SQL, numbers) so it reads left-to-right inside RTL."""
    out, pos = [], 0
    for m in BIDI_RE.finditer(text):
        run, lead, trail = m.group(), "", ""
        while run and (run[0] in "-:;,.!?" or (run[0] == "(" and run.count("(") > run.count(")"))):
            lead, run = lead + run[0], run[1:]
        while run and (run[-1] in ".,:;" or (run[-1] == ")" and run.count(")") > run.count("("))):
            trail, run = run[-1] + trail, run[:-1]
        out.append(E(text[pos:m.start()]) + E(lead))
        out.append(f"<bdi>{L(run)}</bdi>" if re.search(r"[A-Za-z0-9]", run) else E(run))
        out.append(E(trail))
        pos = m.end()
    out.append(E(text[pos:]))
    return "".join(out)


sev_count = {s: sum(1 for i in ISSUES if i["sev"] == s) for s in SEV_ORDER}


def chip_row():
    out = ['<div class="filters" role="group" aria-label="Filter issues">',
           '<span class="flabel">Severity</span>',
           f'<button type="button" class="chip on" data-sev="all" id="f-sev-all">All <b>{len(ISSUES)}</b></button>']
    out += [f'<button type="button" class="chip" data-sev="{s}" id="f-sev-{s.lower()}"><i class="dot sev-{s.lower()}"></i>{s} <b>{sev_count[s]}</b></button>'
            for s in SEV_ORDER]
    out += ['<span class="flabel">Question</span>',
            '<button type="button" class="chip on" data-q="all" id="f-q-all">All</button>']
    out += [f'<button type="button" class="chip" data-q="{k}" id="f-q-{k.lower()}" title="{E(v)}">{k}</button>' for k, v in Q.items()]
    out += ['<span class="shown" id="shown" aria-live="polite"></span></div>']
    return "\n".join(out)


def ranked_table():
    rows = []
    for i in ISSUES:
        r, u, pr, pu = size(i)
        rows.append(
            f'<tr data-sev="{i["sev"]}" data-qs="{" ".join(i["qs"])}">'
            f'<td class="issue"><span class="rk">{i["rank"]}</span><a href="#{i["checks"][0]}">{E(i["title"])}</a></td>'
            f'<td><span class="pill sev-{i["sev"].lower()}">{i["sev"]}</span></td>'
            f'<td class="num">{f(r)}</td><td class="num">{f(u)}</td><td class="num">{pr}%</td><td class="num">{pu}%</td>'
            f'<td>{" ".join(f"<span class=q>{q}</span>" for q in i["qs"])}</td>'
            f'<td><span class="kind {"kind-b" if i["kind"] == BUG else "kind-g"}">{i["kind"]}</span></td><td>{i["fix"]}</td>'
            f'<td>{", ".join(cid(c) for c in i["checks"])}</td>'
            f'<td>{E(i["table"])}.{E(", ".join(i["fields"]))}</td></tr>')
    return ('<div class="scroll"><table class="ranked"><thead><tr><th>Rank · Issue</th><th>Severity</th>'
            '<th>Rows</th><th>Users</th><th>% rows</th><th>% users</th>'
            '<th class="add">Questions hit</th><th class="add">Type</th><th class="add">Fix</th><th class="add">Check</th><th class="add">Table.field</th>'
            '</tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>")


def card(i):
    r, u, pr, pu = size(i)
    related = ('<ul class="checks">' + "".join(
        f'<li>{cid(c)} <span>{L(SHORT[c])}</span> <b class="num">{f(summ[c]["rows"])}</b></li>' for c in i["checks"]) + "</ul>")
    alts = []
    for k, a in enumerate(i["alts"]):
        ch = k == i["chosen"]
        alts.append(
            f'<div class="alt{" chosen" if ch else ""}"><div class="alt-h"><span class="letter">{"AB"[k]}</span>'
            f'<h4>{L(a["name"])}</h4><span class="verdict">{"Chosen" if ch else "Rejected"}</span></div>'
            f'<p>{L(a["desc"])}</p><dl>'
            f'<dt>Run cost</dt><dd>{L(a["cost"])}</dd><dt>Storage</dt><dd>{L(a["storage"])}</dd>'
            f'<dt>Speed / latency</dt><dd>{L(a["speed"])}</dd><dt>Data-loss / bias risk</dt><dd>{L(a["loss"])}</dd></dl></div>')
    return f'''<article class="card" id="{i["checks"][0]}" data-sev="{i["sev"]}" data-qs="{" ".join(i["qs"])}">
<header class="card-h"><span class="rank">#{i["rank"]}</span><span class="pill sev-{i["sev"].lower()}">{i["sev"]}</span>
<span class="kind {"kind-b" if i["kind"] == BUG else "kind-g"}">{i["kind"]}</span><span class="small">Fix: {i["fix"]}</span>
<span class="mono">{", ".join(cid(c) for c in i["checks"])}</span><span class="mono small field">{E(i["table"])}.{E(", ".join(i["fields"]))}</span>
<span class="qs">{" ".join(f"<span class=q>{q}</span>" for q in i["qs"])}</span></header>
<h3>{E(i["title"])}</h3>
<div class="stats"><div><b>{f(r)}</b><span>rows · {pr}%</span></div><div><b>{f(u)}</b><span>users · {pu}%</span></div></div>
{related}
<div class="prose"><p><strong>What is broken.</strong> {L(i["what"])}</p>
<p><strong>Why it matters ({", ".join(i["qs"])}).</strong> {L(i["why"])}</p></div>
<details class="more"><summary>Detection query and the two options (A, B)</summary><div class="more-in">
<div class="sql"><div class="sql-h"><span>Detection SQL · returns {f(i["validated"])} rows (validated against {i["checks"][0]})</span>
<button type="button" class="copy" id="copy-{i["checks"][0]}">Copy</button></div><pre><code>{E(i["sql"])}</code></pre></div>
<div class="alts">{"".join(alts)}</div>
<p class="whyb"><strong>Why B over A.</strong> {L(i["why_b"])}</p></div></details>
<p class="decision"><strong>Decision.</strong> {L(i["decision"])}</p>
</article>'''


payload = dict(
    totals=totals, questions=Q,
    issues=[dict(rank=i["rank"], severity=i["sev"], type=i["kind"], fix=i["fix"], checks=i["checks"], table=i["table"], fields=i["fields"], title=i["title"],
                 what=i["what"], why=i["why"], questions=i["qs"], sql=i["sql"], validated_rows=i["validated"],
                 rows=size(i)[0], users=size(i)[1], pct_rows=size(i)[2], pct_users=size(i)[3],
                 alternatives=i["alts"], chosen=i["chosen"], why_b=i["why_b"], decision=i["decision"]) for i in ISSUES],
    checks=[dict(summ[k], short=SHORT[k]) for k in sorted(summ)], facts={k: F[k] for k in sorted(F)})

not_rows = "".join(f"<tr><td class=mono>{cid(c)}</td><td>{E(n)}</td><td>{L(t)}</td></tr>" for c, n, t in NOT_ISSUES)
not_rows += (f"<tr><td class=mono>{', '.join(cid(s['id']) for s in passed_sorted)}</td><td>Zero-row checks (passed)</td><td>"
             + "; ".join(f"{cid(s['id'])} {E(s['name'])}" for s in passed_sorted) + "</td></tr>")
def status_html(c):
    st = E(check_status(c))
    return f'<a href="#{ISSUE_ID[c]}">{st}</a>' if c in ISSUE_ID else st


legend_checks = "".join(
    f'<tr id="legend-{s["id"]}"><td class="mono"><b>{s["id"]}</b></td><td>{E(s["tbl"])}</td><td class="lft">{L(SHORT[s["id"]])}</td>'
    f'<td class="lft">{E(s["name"])}</td><td class="num">{f(s["rows"])}</td>'
    f'<td>{status_html(s["id"])}</td></tr>'
    for s in LEGEND_ORDER)
legend_terms = "".join(f'<tr id="term-{n}"><td class="mono"><b>{E(a)}</b></td><td class="lft">{L(b)}</td></tr>' for n, (a, b) in enumerate(TERMS))
legend_cards = (
    '<div class="howto">'
    '<div class="howto-c"><h3>Severity</h3><p>How much an issue changes the answers leadership asked for.</p><dl>'
    + "".join(f'<dt><span class="pill sev-{k_.lower()}">{k_}</span></dt><dd>{E(v_)}</dd>' for k_, v_ in SEV_DEF) + "</dl></div>"
    '<div class="howto-c"><h3>Type and Fix</h3><p>What kind of problem it is, and how much of it the clean layer repairs.</p><dl>'
    + "".join(f'<dt><span class="kind {"kind-b" if k_ == BUG else "kind-g"}">{k_}</span></dt><dd>{E(v_)}</dd>' for k_, v_ in KIND_DEF)
    + "".join(f"<dt>Fix: {k_}</dt><dd>{E(v_)}</dd>" for k_, v_ in FIX_DEF) + "</dl></div>"
    '<div class="howto-c"><h3>Short codes</h3><p>The codes used in the ranked table and the issue cards.</p><dl>'
    + "<dt>Q1-Q4</dt><dd>The brief's four leadership questions: " + ", ".join(f"{k_} {E(v_)}" for k_, v_ in Q.items()) + ".</dd>"
    + "<dt>T, U, L</dt><dd>A check ID. The letter is the file it checks: T = transactions, U = users, L = churn_labels. Hover an ID to see what it checks.</dd>"
    + "<dt>A / B</dt><dd>The two fixes we considered for each issue. B is the one we chose.</dd></dl></div></div>"
    + '<p class="tnote">Every check ID and every term used in the text is listed in the <a href="#glossary">Glossary</a> at the end of the page.</p>')
rev_rows = "".join(f"<tr><td>{E(a)}</td><td><span class=verdict-tag>{E(b)}</span></td><td>{L(c)}</td></tr>" for a, b, c in REVIEW)
corr = "".join(f"<li>{L(c)}</li>" for c in CORRECTIONS)
tot_rows = (f"<tr><td>users</td><td class=num>{f(totals['users'])}</td><td class=num>{f(totals['users'])}</td></tr>"
            f"<tr><td>transactions (export_1 + export_2)</td><td class=num>{f(totals['tx_rows'])}</td><td class=num>{f(totals['tx_users'])}</td></tr>"
            f"<tr><td>churn_labels</td><td class=num>{f(totals['labels'])}</td><td class=num>{f(totals['labels'])}</td></tr>")

CSS = """
/* Layout: one reading column; summary (totals, filters, ranked table) before per-issue detail cards. */
:root{--bg:#f5f8fc;--surface:#ffffff;--fg:#14233a;--muted:#55657d;--line:#d3e0ee;--accent:#2e75b6;--accent-soft:#ddebf7;
--navy:#1f3864;--code-bg:#eef4fa;--crit:#1f3864;--high:#2e75b6;--med:#7fb0dd;--low:#cfe1f3;--on-dark:#ffffff;--on-light:#14233a;
--font-head:"IBM Plex Sans",system-ui,sans-serif;--font-body:"IBM Plex Sans",system-ui,sans-serif;--font-mono:var(--font-body);--font-code:"IBM Plex Mono",ui-monospace,Menlo,monospace;--th-add:#e6eaf0;--th-add-fg:#2b3a50;
--fs-title:28px;--fs-h2:20px;--fs-h3:17px;--fs-tab:16px;--fs-body:15px;--fs-table:14px;--fs-small:13px;--fs-label:12px;--fs-num:22px}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#0e1624;--surface:#152238;--fg:#e2ebf6;--muted:#9fb0c6;--line:#28395a;
--accent:#7ab3e6;--accent-soft:#1d3352;--navy:#a9cbef;--code-bg:#101c2e;--crit:#a9cbef;--high:#6fa6dc;--med:#3d6ea3;--low:#2a4468;--on-dark:#0e1624;--on-light:#e2ebf6;--th-add:#2c3a4f;--th-add-fg:#dbe4ef;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#0e1624;--surface:#152238;--fg:#e2ebf6;--muted:#9fb0c6;--line:#28395a;
--accent:#7ab3e6;--accent-soft:#1d3352;--navy:#a9cbef;--code-bg:#101c2e;--crit:#a9cbef;--high:#6fa6dc;--med:#3d6ea3;--low:#2a4468;--on-dark:#0e1624;--on-light:#e2ebf6;--th-add:#2c3a4f;--th-add-fg:#dbe4ef;color-scheme:dark}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--fg);font-family:var(--font-body);font-size:var(--fs-body);line-height:1.55;font-style:normal}
em,i{font-style:normal}
.wrap{max-width:1440px;margin:0 auto;padding-block:32px 64px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));display:grid;gap:28px}
h1,h2,h3,h4{font-family:var(--font-head);font-weight:700;text-wrap:balance;margin:0;color:var(--navy)}
h1{font-size:var(--fs-title);line-height:1.2}h2{font-size:var(--fs-h2)}h3{font-size:var(--fs-h3);line-height:1.3}h4{font-size:var(--fs-body)}
.lede{color:var(--muted);max-width:75ch;margin:6px 0 0}
.mono{font-family:var(--font-mono);font-weight:500}.small{font-size:var(--fs-small)}
.num{font-variant-numeric:tabular-nums;white-space:nowrap}
section{display:grid;gap:14px;min-width:0}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:8px;background:var(--surface);scrollbar-width:thin;scrollbar-color:var(--accent) var(--code-bg)}
.scroll::-webkit-scrollbar{height:10px}.scroll::-webkit-scrollbar-track{background:var(--code-bg)}.scroll::-webkit-scrollbar-thumb{background:var(--accent);border-radius:6px}
.scroll-hint{font-size:var(--fs-small);color:var(--accent);font-weight:600;text-align:right;margin:0 0 -8px}.scroll-hint[hidden]{display:none}
table{border-collapse:collapse;width:100%;font-size:var(--fs-table)}
/* Tables only as wide as their content needs (max 1100px); the ranked table keeps the full width */
table:not(.ranked){width:auto;max-width:min(100%,1100px)}
th,td{padding:8px 10px;border:1px solid var(--line);text-align:center;vertical-align:middle}
th{background:var(--navy);color:var(--on-dark);font-weight:700;font-size:var(--fs-label);letter-spacing:.04em;text-transform:uppercase;white-space:nowrap;border-color:color-mix(in srgb,var(--on-dark) 25%,var(--navy))}
th.add{background:var(--th-add);color:var(--th-add-fg);border-color:var(--line)}
table.ranked td,table.ranked td *{font-size:var(--fs-table)}
table.ranked td{text-align:center}table.ranked th:first-child,table.ranked td:first-child{text-align:left}
.rk{display:inline-grid;place-items:center;min-width:26px;height:26px;margin-right:10px;border-radius:50%;background:var(--accent-soft);color:var(--navy);font-weight:700;font-variant-numeric:tabular-nums;vertical-align:middle}
table.ranked td.issue{position:relative;padding-left:48px}table.ranked .rk{position:absolute;left:10px;top:50%;transform:translateY(-50%);margin:0}
.tnote{margin:0;max-width:110ch;font-size:var(--fs-table);line-height:1.6}
.tnote b{color:var(--navy)}
.hk{display:inline-flex;align-items:center;gap:6px;margin-left:16px;font-size:var(--fs-small);color:var(--muted);white-space:nowrap}
.hk i{width:14px;height:14px;border-radius:3px;display:inline-block}.hk-b{background:var(--navy)}.hk-a{background:var(--th-add);border:1px solid var(--line)}
details.more{border:1px solid var(--line);border-radius:8px;padding:8px 12px}
details.more summary{cursor:pointer;font-weight:600;color:var(--accent)}
.more-in{display:grid;gap:12px;margin-top:10px}
table.ranked th{white-space:normal}table.ranked th,table.ranked td{padding:8px 7px}table.ranked .kind{white-space:normal}
tbody tr:nth-child(even){background:color-mix(in srgb,var(--accent-soft) 35%,transparent)}
td.issue{text-align:left;min-width:260px}td.issue a{color:var(--fg);font-weight:600;text-decoration:none}td.issue a:hover{color:var(--accent);text-decoration:underline}
.totals{width:fit-content;max-width:100%}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:var(--fs-label);font-weight:700;letter-spacing:.03em;white-space:nowrap}
.sev-critical{background:var(--crit);color:var(--on-dark)}.sev-high{background:var(--high);color:var(--on-dark)}
.sev-medium{background:var(--med);color:var(--on-light)}.sev-low{background:var(--low);color:var(--on-light)}
.q{display:inline-block;font-family:var(--font-mono);font-size:var(--fs-label);border:1px solid var(--line);border-radius:4px;padding:0 5px;margin:1px;color:var(--muted)}
.filters{display:flex;flex-wrap:wrap;gap:8px;align-items:center;position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--bg);padding-block:10px;border-bottom:1px solid var(--line)}
.flabel{font-size:var(--fs-label);letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:700;margin-left:6px}
.chip{font:inherit;font-size:var(--fs-table);display:inline-flex;gap:6px;align-items:center;padding:5px 12px;border-radius:999px;border:1px solid var(--line);background:var(--surface);color:var(--fg);cursor:pointer}
.chip b{font-variant-numeric:tabular-nums;color:var(--muted)}
.chip.on{border-color:var(--accent);background:var(--accent-soft);font-weight:600}
.chip:focus-visible,.copy:focus-visible,a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.dot{width:9px;height:9px;border-radius:50%;display:inline-block}
.shown{margin-left:auto;color:var(--muted);font-size:var(--fs-small)}
.cards{display:grid;gap:18px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:20px;display:grid;gap:12px;min-width:0;scroll-margin-top:70px}
.card-h{display:flex;flex-wrap:wrap;gap:10px;align-items:center;color:var(--muted)}
.rank{font-family:var(--font-mono);font-weight:700;color:var(--navy)}
.field{color:var(--muted)}.qs{margin-left:auto}
.stats{display:flex;gap:28px;flex-wrap:wrap}
.stats div{display:grid}.stats b{font-size:var(--fs-num);font-variant-numeric:tabular-nums;color:var(--navy)}.stats span{font-size:var(--fs-small);color:var(--muted)}
.related{margin:0;color:var(--muted);font-size:var(--fs-small)}
.prose p,.whyb,.decision{margin:0;max-width:95ch}
.prose{display:grid;gap:8px}
.sql{border:1px solid var(--line);border-radius:8px;overflow:hidden;min-width:0}
.sql-h{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:6px 10px;background:var(--accent-soft);font-size:var(--fs-small);color:var(--fg)}
.copy{font:inherit;font-size:var(--fs-small);padding:3px 10px;border-radius:6px;border:1px solid var(--accent);background:var(--surface);color:var(--accent);cursor:pointer}
pre{margin:0;padding:12px;background:var(--code-bg);overflow-x:auto;font-family:var(--font-code);font-size:var(--fs-small);line-height:1.5}
.alts{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}
.alt{border:1px solid var(--line);border-radius:8px;padding:14px;display:grid;gap:8px;align-content:start;min-width:0}
.alt.chosen{border:2px solid var(--accent);background:color-mix(in srgb,var(--accent-soft) 45%,var(--surface))}
.alt-h{display:flex;gap:10px;align-items:center}
.letter{width:26px;height:26px;border-radius:50%;display:grid;place-items:center;font-weight:700;background:var(--accent-soft);color:var(--navy);flex:none}
.chosen .letter{background:var(--accent);color:var(--on-dark)}
.verdict{margin-left:auto;font-size:var(--fs-label);font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.chosen .verdict{color:var(--accent)}
.alt p{margin:0}
dl{margin:0;display:grid;grid-template-columns:minmax(110px,auto) 1fr;gap:4px 12px;font-size:var(--fs-table)}
dt{color:var(--muted);font-weight:600}dd{margin:0}
.decision{padding:10px 12px;border-radius:8px;background:var(--accent-soft)}
.verdict-tag{font-weight:700;color:var(--navy);white-space:nowrap}
.review td,.notissues td{text-align:center}
ol.corr{margin:0;padding-left:1.4em;display:grid;gap:8px;max-width:100ch}
footer{color:var(--muted);font-size:var(--fs-small)}
.cid,.term{color:inherit;text-decoration:underline dotted var(--accent);text-underline-offset:3px;cursor:help}
.cid:hover,.term:hover{color:var(--accent)}
.tabs{display:flex;gap:6px;border-bottom:2px solid var(--line);flex-wrap:wrap}
.tab{font:inherit;font-weight:600;font-size:var(--fs-tab);padding:8px 16px;border:1px solid var(--line);border-bottom:none;border-radius:8px 8px 0 0;background:var(--surface);color:var(--muted);cursor:pointer}
.tab.on{background:var(--navy);color:var(--on-dark);border-color:var(--navy)}
.tab:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.panel{display:grid;gap:28px;min-width:0}.panel[hidden]{display:none}
.kind{display:inline-block;padding:2px 8px;border-radius:6px;font-size:var(--fs-label);font-weight:600;white-space:nowrap}
.kind-b{background:#fdf0d5;color:#8a5200}.kind-g{background:#ddebf7;color:#1f4e79}
.howto{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}
.howto-c{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:16px;display:grid;gap:8px;align-content:start}
.howto-c p{margin:0;color:var(--muted);font-size:var(--fs-table)}
.howto-c dl{grid-template-columns:auto 1fr}
details.legend{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:10px 14px}
details.legend summary{cursor:pointer;font-weight:700;color:var(--navy)}
details.legend .scroll{margin-top:10px}
.legend-t td.lft{text-align:left}.legend-t td:last-child{white-space:nowrap}
tr:target td{background:var(--accent-soft);outline:none}
ul.checks{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:8px}
ul.checks li{border:1px solid var(--line);border-radius:6px;padding:3px 9px;font-size:var(--fs-table);background:var(--code-bg)}
ul.checks .cid{font-family:var(--font-mono);font-weight:700}
.he{font-family:"IBM Plex Sans Hebrew",var(--font-body);text-align:right;display:grid;gap:28px}
.he bdi{unicode-bidi:isolate}
.he .card p{margin:0;max-width:95ch}
.he .qs{margin-left:0;margin-right:auto}
.he-box{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:16px 20px}
.he-box ul{margin:0;padding-right:1.2em;padding-left:0;display:grid;gap:6px}
.he-terms{grid-template-columns:minmax(140px,auto) 1fr}
@media (max-width:640px){:root{--fs-title:24px;--fs-h2:18px;--fs-h3:16px;--fs-tab:15px;--fs-body:14px;--fs-table:13px;--fs-small:12px;--fs-label:11px;--fs-num:20px}.qs{margin-left:0}.shown{margin-left:0;width:100%}}
@media (prefers-reduced-motion:no-preference){html{scroll-behavior:smooth}}
"""

JS = """
(function(){
  var sev='all', q='all';
  var cards=[].slice.call(document.querySelectorAll('.card'));
  var rows=[].slice.call(document.querySelectorAll('table.ranked tbody tr'));
  function match(el){return (sev==='all'||el.dataset.sev===sev)&&(q==='all'||el.dataset.qs.split(' ').indexOf(q)>=0);}
  function apply(){
    var n=0; cards.forEach(function(c){var m=match(c); c.hidden=!m; if(m) n++;});
    rows.forEach(function(r){r.hidden=!match(r);});
    document.querySelectorAll('[data-sev].chip').forEach(function(b){b.classList.toggle('on',b.dataset.sev===sev);b.setAttribute('aria-pressed',b.dataset.sev===sev);});
    document.querySelectorAll('[data-q].chip').forEach(function(b){b.classList.toggle('on',b.dataset.q===q);b.setAttribute('aria-pressed',b.dataset.q===q);});
    document.getElementById('shown').textContent='Showing '+n+' of '+cards.length+' issues';
  }
  document.querySelectorAll('.chip').forEach(function(b){b.addEventListener('click',function(){
    if(b.dataset.sev) sev=b.dataset.sev; if(b.dataset.q) q=b.dataset.q; apply();});});
  document.querySelectorAll('.copy').forEach(function(b){b.addEventListener('click',function(){
    var code=b.closest('.sql').querySelector('code');
    var done=function(){b.textContent='Copied';setTimeout(function(){b.textContent='Copy';},1400);};
    var fallback=function(){var r=document.createRange();r.selectNodeContents(code);var s=getSelection();s.removeAllRanges();s.addRange(r);b.textContent='Selected';};
    try{navigator.clipboard.writeText(code.textContent).then(done,fallback);}catch(e){fallback();}
  });});
  apply();
  // Language tabs (only present when the Hebrew explainer is built) and legend links that open the right panel / details.
  var tabs=[].slice.call(document.querySelectorAll('.tab'));
  function show(id){tabs.forEach(function(t){var on=t.getAttribute('aria-controls')===id;t.classList.toggle('on',on);
    t.setAttribute('aria-selected',on);document.getElementById(t.getAttribute('aria-controls')).hidden=!on;});}
  tabs.forEach(function(t){t.addEventListener('click',function(){show(t.getAttribute('aria-controls'));window.scrollTo(0,0);});});
  function reveal(hash){
    var el=hash&&document.getElementById(hash.slice(1)); if(!el) return;
    var p=el.closest('.panel'); if(p&&p.hidden) show(p.id);
    var d=el.closest('details'); if(d) d.open=true;
    if(el.hidden){sev='all';q='all';apply();}
    el.scrollIntoView({block:'center'});
  }
  document.addEventListener('click',function(e){var a=e.target.closest('a[href^="#"]'); if(!a) return;
    e.preventDefault(); history.replaceState(null,'',a.getAttribute('href')); reveal(a.getAttribute('href'));});
  if(location.hash) reveal(location.hash);
})();
"""

DATA_JSON = json.dumps(payload, sort_keys=True, default=str).replace("</", "<\\/")


def qspan(q, meaning):
    return f'<span class="q" title="{E(meaning)}">{q}</span>'


english = f"""<header><h1>Tune Data-Quality Report</h1>
<p class="lede">Part 1a. {len(ISSUES)} issues in the raw billing exports, ranked by how much each would change the answers to leadership's questions.
Every number is computed from DuckDB at build time, and every detection query is re-run and matches its check.</p></header>
<section><h2>Raw tables</h2><div class="scroll totals"><table><thead><tr><th>Table</th><th>Rows</th><th>Users</th></tr></thead><tbody>{tot_rows}</tbody></table></div></section>
<section id="legend"><h2>How to read this report</h2>
{legend_cards}
</section>
<section><h2>Ranked issues</h2>
<p class="tnote"><b>What the rank is based on:</b> severity, i.e. how much the answers to the four leadership questions (Q1-Q4) would change if the issue were ignored, as the brief asks. Within the same severity, Data Bugs come first, because they cannot be fully fixed.
<span class="hk"><i class="hk-b"></i>Asked in the brief</span><span class="hk"><i class="hk-a"></i>Added by us</span></p>
{chip_row()}
{ranked_table()}</section>
<section><h2>Issue detail</h2><p class="lede">Each issue: what is broken, why it matters, and the decision. The query and the two options are folded under each one.</p>
<div class="cards">{"".join(card(i) for i in ISSUES)}</div></section>
<section><h2>Checked and not an issue</h2><div class="scroll"><table class="notissues"><thead><tr><th>Check</th><th>What</th><th>Finding</th></tr></thead><tbody>{not_rows}</tbody></table></div></section>
<section><h2>Second-opinion review (Gemini)</h2><p class="lede">An independent AI review of the same files; every number it gave was re-run in DuckDB before being accepted.</p>
<details class="legend"><summary>Show the {len(REVIEW)} claims and our verdicts</summary>
<div class="scroll"><table class="review"><thead><tr><th>Claim</th><th>Verdict</th><th>Evidence (from SQL)</th></tr></thead><tbody>{rev_rows}</tbody></table></div></details></section>
<section><h2>Corrections to earlier assumptions</h2><p class="lede">Mistakes we made and fixed along the way, including AI mistakes (also in the 5b AI log).</p>
<details class="legend"><summary>Show the {len(CORRECTIONS)} corrections</summary><ol class="corr">{corr}</ol></details></section>
<section id="glossary"><h2>Glossary</h2><p class="lede">Look up any check ID or term used above. Clicking an ID anywhere on the page opens this list at that row.</p>
<details class="legend" id="legend-checks"><summary>Check IDs ({len(LEGEND_ORDER)}): short name and what the SQL counts</summary>
<div class="scroll"><table class="legend-t"><thead><tr><th>Check</th><th>Table</th><th>Short name (used in the text)</th><th>Definition (what the SQL counts)</th><th>Rows</th><th>Status</th></tr></thead>
<tbody>{legend_checks}</tbody></table></div></details>
<details class="legend" id="legend-terms"><summary>Terms ({len(TERMS)}): file, table and view names used in the text</summary>
<div class="scroll"><table class="legend-t"><thead><tr><th>Name</th><th>Meaning</th></tr></thead><tbody>{legend_terms}</tbody></table></div></details></section>
<footer>Generated by py/01_dq_outputs.py from tune.duckdb (sql/01_data_quality.sql). Machine-readable copy of every number on this page: the JSON block with id "dq-data".</footer>"""

body_html = english

JS += r"""
(function(){
  /* Wide tables: show a "scroll sideways" note above any table box that does not fit */
  function markWide(){
    [].forEach.call(document.querySelectorAll('.scroll'),function(el){
      if(!el.offsetParent) return;
      var wide=el.scrollWidth>el.clientWidth+2, h=el.previousElementSibling;
      if(!h||!h.classList.contains('scroll-hint')){ if(!wide) return;
        h=document.createElement('p'); h.className='scroll-hint'; h.textContent='More columns: scroll sideways →'; el.parentNode.insertBefore(h,el); }
      if(h.hidden===wide) h.hidden=!wide;
    });
  }
  var t; function q(){clearTimeout(t); t=setTimeout(markWide,120);}
  window.addEventListener('resize',q); document.addEventListener('click',q); document.addEventListener('toggle',q,true); q();
})();
"""

page = f"""<title>Tune Data-Quality Report</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;600;700&family=IBM+Plex+Sans+Hebrew:wght@400;600;700&display=swap">
<style>{CSS}</style>
<div class="wrap">
{body_html}
</div>
<script type="application/json" id="dq-data">{DATA_JSON}</script>
<script>{JS}</script>
"""
import runpy
page = runpy.run_path(str(ROOT / "py/nodot.py"))["nodot"](page)  # style: no period at the end of a box line, cell or bullet
(ROOT / "reports/01_data_quality.html").write_text(page)
# The site tab (site/dq.html) is the same page with a full document head.
(ROOT / "site/dq.html").write_text('<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">\n' + page.rstrip("\n"))

print(f"wrote reports/01_data_quality.md, .xlsx and .html ({len(ISSUES)} issues)")
