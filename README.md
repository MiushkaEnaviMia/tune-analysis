# Tune subscription analysis

Static site for the Tune take-home: data-quality report (Part 1a), data model and table map (Part 1b),
and a table explorer where you can run SQL on every table, broken (as delivered) and clean.

Open `index.html` through any web server (GitHub Pages serves it as is). Queries run in the browser with DuckDB-WASM
and read the Parquet files in `data/`. Rebuild the data with `.venv/bin/python -I py/build_site_data.py` in the project.
