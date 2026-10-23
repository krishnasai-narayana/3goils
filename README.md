# 3G OILS Dashboard

Sales, purchase, stock, goods GST and recorded ledger reports across annual billing databases.

## Start locally

From this folder:

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py --server.address=127.0.0.1 --server.port=8502 --browser.gatherUsageStats=false
```

Open http://localhost:8502. The dashboard automatically discovers `.mdb` files in `database/`. A background importer reads new or changed files into a local SQLite cache; page clicks use this cache rather than querying Access.

Python source-file watching is disabled to avoid filesystem scans during use. Restart Streamlit after editing Python code or server configuration. Adding/replacing database files, date/customer/bill filters and **Refresh databases** work without restarting.

## Add another financial year

Copy the prior year's `.mdb` file into `database/` using a different filename, for example `3G2025.mdb`. The folder is checked every 10 seconds while the app runs. After import, open pages refresh automatically. Earlier years and the **Financial year** selector are available only in **Analytics**. Home, Sales, Purchase, Summary and Data Validation always use the current April–March FY. Import time depends on file size. **Refresh databases** requests an immediate scan.

Analytics → Sales includes a seasonal outlook for the current and next FY, trained
on covered prior years. It labels missing history, partial months and assumptions.
See [ANALYTICS.md](ANALYTICS.md) for the reporting policy and forecast method.

Keep one primary database per financial year. Invoice numbers may repeat: source-qualified internal document/customer/item IDs keep their joins and counts separate, while printed bill numbers and GST-inclusive sale rates remain unchanged. Bill filters show the financial year and source file when multiple files are loaded. Financial years are derived from transaction dates using April–March boundaries, not guessed from filenames.

Unchanged files are not imported again. Changed files replace their prior cached records atomically. Failed imports retain the previous successful records and display an error. Byte-identical backup copies are ignored; other overlapping financial-year files are rejected to prevent double counting. See `MULTI_YEAR.md` for details.

The importer needs the Microsoft Access ODBC driver on Windows and the same billing schema/password as the current database. A shared password override is supported through `THREEG_MDB_PASSWORD`. Original Access files are opened read-only. `data/mdb_cache.sqlite3` is generated cache data; the original CSVs are only the initial fallback until the first successful import.

For a one-off command-line scan: `python scripts/sync_databases.py`. `scripts/export_mdb.py` remains a legacy export utility for the supplied 2026 file; it is not required for automatic imports.

## Validation

```powershell
python -m pip install -r requirements-dev.txt
python scripts/test_all.py
python -m pytest scripts/test_validation.py scripts/test_performance.py scripts/test_multi_database.py scripts/test_reporting_policy.py scripts/test_date_defaults.py scripts/test_page_calculations.py -q
python scripts/audit_data.py
python scripts/check_live_pages.py --port 8503
```

The first script runs the original 70 checks against the supplied snapshot. The pytest suite includes source-value regressions and isolated multi-year fixtures with intentionally colliding IDs and invoice numbers. It exercises pages, filters, stock cutoff selection, automatic discovery, cache invalidation and failed-import rollback. Background production imports are disabled during tests. The audit compares the original 123 CSVs with the supplied 2026 database; it is a legacy snapshot audit rather than a multi-year database scan.

The independent page-calculation suite checks all 23 routes in both latest-day
and full-current-FY views. It compares displayed metrics, complete grouped tables
and chart values with raw CSV records verified against Access, checks every sales
and purchase fact's customer/supplier/item/HSN/GST mapping, and verifies the active
11-table cache. Additional cases cover pagination, combined filters, nonzero
cess/additional tax, malformed imports and blank dimension labels. The live-page
script checks server execution and date defaults through Streamlit's WebSocket;
it does not inspect browser layout. These snapshot tests deliberately use the
supplied 2026 data and dates; adapt their reference snapshot when replacing it.

Open **Data Validation** on Home for invoice reconciliation and source-quality findings. See `VALIDATION.md` for the latest validation scope and remaining source-data considerations.

Performance measurements and the reasons for the optimization are recorded in `PERFORMANCE.md`. To repeat them, run `python scripts/benchmark_app.py` for instrumented page execution and `python scripts/benchmark_server.py --output performance_server_after.json` against the running local server. The latter opens a separate test session and measures responses over Streamlit's actual WebSocket.

## Default dates and data

Only real database files are used. Generated synthetic files, the separate demo
cache and demo mode have been removed. Ports 8502 and 8503 now serve the same
real-data application.

Sales and Purchase **Bill Wise** default both From and To to the maximum valid
business transaction date in the current FY (7 August 2026 in the supplied data).
Their other reports—Date Wise, Monthly, HSN, Party Wise and GST No Wise—default
From to 1 April of the current FY and To to that latest loaded date, showing all
available current-FY transactions. Home, Summary and invoice reconciliation
retain their latest-day defaults. Cancelled and opening documents do not set the
latest day. A newer import extends the default automatically; custom date filters
remain available within the current FY. Reopening a report restores its own
default period. India time determines which FY is current.
If no valid current-FY transactions exist, reports remain empty rather than
falling back to an older FY.
Current-year source integrity checks remain FY-wide.

Analytics opens on **All years**, with the complete available database date range.
Additional annual files appear automatically after import and extend the default
All years range. A user-selected FY/date range is respected while working on that
page; entering Analytics again restores All years. See `ANALYTICS.md`.

Bill Wise pages large results in groups of 1,000 lines while keeping totals for
all filtered rows. The recorded sale rates and amounts remain GST-inclusive.

## Amount and stock definitions

- Home, date and monthly totals use recorded invoice amounts, including GST and invoice rounding.
- Sales invoice sale rates and amounts retain the original GST-inclusive source values. Sales party totals, the sales summary headline/payment totals and sales analytics revenue also include GST. Invoice rounding differences are shown on Data Validation.
- HSN and GST breakdowns use taxable amounts derived from inclusive line totals less recorded GST and other taxes. Opening stock and sales returns are excluded from purchase reports. Sales analytics preserves the original inclusive revenue-minus-recorded-cost margin presentation; the validation checks separately assess the tax-exclusive difference.
- Stock conversion follows the transaction's conversion flag. Closing stock uses the most recent annual database available as of **To**, including its opening stock and movements through that date. It does not add together opening balances from successive years. The stock report separates the balance before **From** from movements during the selected period.
- Goods GST reports exclude service vouchers and other tax adjustments. The displayed difference is not a complete GST-return calculation.
- Financial reports show recorded ledger movements. They do not reconstruct implicit cash contra entries or account opening balances and must not be interpreted as a complete trial balance or profit-and-loss statement.
- Financial Summary retains accounts with activity even when their net movement is zero. HSN and monthly summary totals include cess/additional tax in `Other_Tax`. Payment modes without a confirmed meaning retain their source code rather than an assumed payment label.
