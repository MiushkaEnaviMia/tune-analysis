"""Run SQL queries on tune.duckdb (read-only, so the data cannot be changed by mistake).

  .venv/bin/python -I query.py                          -> interactive: type a query, press Enter
  .venv/bin/python -I query.py "select * from dim_user limit 5"
  .venv/bin/python -I query.py my_query.sql             -> run the query in a .sql file
  .venv/bin/python -I query.py "select ..." --csv out.csv  -> also save the result to a CSV

Interactive commands: tables (list tables + row counts), cols <table> (list columns), exit.
"""
import pathlib, sys, time
import duckdb

DB = pathlib.Path(__file__).resolve().parent / "tune.duckdb"
con = duckdb.connect(str(DB), read_only=True)

TABLES = """select table_name, estimated_size as approx_rows
            from duckdb_tables() order by table_name"""


def run(sql, csv=None):
    sql = sql.strip().rstrip(";")
    if sql == "tables":
        sql = TABLES
    elif sql.startswith("cols "):
        sql = f"describe {sql[5:].strip()}"
    t = time.time()
    try:
        rel = con.sql(sql)
        if rel is None:
            return
        rel.show(max_rows=50, max_width=200)
        if csv:
            rel.write_csv(csv)
            print(f"saved to {csv}")
        print(f"({time.time() - t:.1f}s)")
    except duckdb.Error as e:
        print(f"error: {e}")


args = sys.argv[1:]
csv = None
if "--csv" in args:
    i = args.index("--csv")
    csv = args[i + 1]
    del args[i:i + 2]

if args:
    q = args[0]
    run(pathlib.Path(q).read_text() if q.endswith(".sql") else q, csv)
else:
    try:
        import readline  # noqa: F401  (arrow keys + history in the prompt)
    except ImportError:
        pass
    print("tune.duckdb (read-only). Type a query and press Enter. 'tables', 'cols <table>', 'exit'.")
    while True:
        try:
            q = input("sql> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if q in ("exit", "quit"):
            break
        if q:
            run(q)
