"""Run the whole pipeline: every sql/NN_*.sql in order against tune.duckdb (rebuilt from ./data),
then every py/NN_*.py in order (report/workbook generators that read tune.duckdb)."""
import duckdb, pathlib, runpy, time
con = duckdb.connect("tune.duckdb")
for f in sorted(pathlib.Path("sql").glob("[0-9][0-9]_*.sql")):
    t = time.time()
    stmts = [s for s in con.extract_statements(f.read_text())]
    for s in stmts:
        res = con.execute(s)
    print(f"✓ {f.name} ({time.time()-t:.1f}s)")
    try:
        print(con.sql(stmts[-1].query) if stmts[-1].type.name == "SELECT" else "")
    except Exception:
        pass
con.close()  # release the write lock so the Python steps can open the database
for f in sorted(pathlib.Path("py").glob("[0-9][0-9]_*.py")):
    t = time.time()
    runpy.run_path(str(f), run_name="__main__")
    print(f"✓ {f.name} ({time.time()-t:.1f}s)")
