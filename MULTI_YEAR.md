# Automatic annual database imports

## Everyday use

1. Keep each primary annual `.mdb` file in `database/`, with a distinct filename. The existing `3G2026.mdb` can remain there when adding earlier files.
2. While Streamlit is running, a background worker scans the folder every 10 seconds. It waits for recent file writes to settle, checks size/modification time and imports only new or changed files. It verifies the file did not change during the import.
3. Open dashboard sessions check the committed cache revision every 10 seconds and refresh after a successful import. Importing itself can take longer than these polling intervals. A server restart or manual CSV export is not needed.
4. Earlier financial years and the sidebar **Financial year** selector are available only on Analytics pages. **All years** allows historical analysis across files. Other pages use the actual current April–March FY; they stay empty if no current-year file exists. See `ANALYTICS.md` for sales projections and coverage requirements.

## Repeated invoice and master IDs

Printed invoice numbers stay unchanged. For example, `3GST-1` may appear in both 2025–26 and 2026–27.

The internal document identity is the source database plus its local `Doc_Id`. A persistent source registry allocates an independent numeric namespace to each file. Local document, account, item and item-group IDs are mapped into that namespace before any joins or invoice counts. Transaction-type IDs and printed invoice sequence numbers retain their original meanings.

Bill filters include the bill number, financial year and filename when multiple databases are present. Bill tables show the financial year and database alongside the unchanged printed bill number. The same approach applies to purchase references.

Filenames identify sources and should be kept stable when updating a year's file. Removing a file removes its cached records on the next scan; re-adding that filename reuses its registered namespace. A file containing business dates that overlap another loaded file's financial year is rejected, even if its filename differs. Exact byte-for-byte copies are ignored.

## Stock snapshots

Annual opening stock commonly carries forward the previous year's closing balance. Adding both annual openings would overstate stock.

Closing stock therefore selects the latest annual source available at the requested cutoff, includes that source's opening quantities and applies its own stock movements through the cutoff. An earlier cutoff selects the corresponding older source. Stock item/master joins use the selected source's own IDs and names. This assumes the supplied annual opening balances are the authoritative carried-forward stock.

## Cache consistency and failure handling

Access files are opened read-only. Only the eleven tables required by the dashboard are imported into `data/mdb_cache.sqlite3`. All tables for a source and its import metadata are published in one SQLite transaction. A failed write rolls back the entire source replacement.

Each page render pins one committed read snapshot; an import cannot change its header data halfway through loading the item lines. Streamlit's table/fact/bill caches are keyed by the committed import revision, so a completed import becomes visible without reusing stale facts. Cache entry counts are bounded. Old per-year source rows are replaced, rather than appended repeatedly.

Required tables, required columns, core key uniqueness, document dates and stock-line references are validated before publication. Unsupported/corrupt files show an import error and leave prior successful data available. The driver, schema and database password must be compatible with the supplied billing database. Set `THREEG_MDB_PASSWORD` to override the existing shared password; errors are shown rather than guessed around.

The original CSV files provide an initial fallback before the first successful import. After import, the SQLite cache is authoritative; manual edits to those CSVs do not override imported Access records. Python source changes still require a Streamlit restart because code watching is disabled for performance. Database-folder scanning is independent of Python source watching.

## Validation

The multi-year fixture intentionally reuses document IDs 1/2/3, account IDs 10/20, item ID 100, group ID 2 and bill number `3GST-1` in two annual files, with different names. Checks verify independent invoices and names, unchanged GST-inclusive rates, source-specific stock, year filters and rendering of all report families. Tests also cover unchanged-file skipping, replacement, removal/re-addition, duplicate copies, overlap rejection, partial-copy waiting, background discovery, coherent read snapshots and rollback after a simulated storage failure.

The real 2026 database was imported read-only and reconciled: 7,425 sales invoices, 93 purchase bills, sales invoice value INR 70,156,990.00 and purchase invoice value INR 66,706,545.78. Earlier real databases were not supplied; cross-year behavior is tested with isolated synthetic databases using the same required schema.

The current application uses only real source files. Previously generated
synthetic MDBs and their separate cache have been removed. Sales/Purchase Bill
Wise defaults to the latest valid transaction date in the current FY; their other
reports default to the current FY from 1 April through that latest date. Home,
Summary and Data Validation retain latest-day defaults. Analytics defaults to all available financial
years and automatically picks up additional imported annual files. See
`VALIDATION.md` for current test results and `ANALYTICS.md` for reporting scope.
