# Validation record — 22 October 2026

Current default-date policy (updated after the full audit below):

| Reports | Default period |
| --- | --- |
| Sales / Purchase Bill Wise | Latest valid current-FY transaction date only |
| Other Sales / Purchase reports | 1 April through the latest loaded current-FY date |
| Analytics | All available data across all imported financial years |
| Home / Summary / Data Validation | Latest-day defaults retained |

The supplied data therefore opens Bill Wise on 7 August 2026, other Sales and
Purchase reports on 1 April–7 August 2026, and Analytics on 31 March–7 August 2026.
These defaults supersede the earlier all-standard-pages latest-day policy
described in the historical audit record below. Date filters remain editable.

The revised defaults passed **34 date-policy tests** with no failures or skips
(`report_date_policy_results.xml`), including every page, report navigation,
current-FY isolation, older-year imports and automatic date-range advancement.
All **23 running-server routes** also passed with the revised periods
(`report_date_policy_live.json`). The MDB hash remains unchanged.

User presentation preference: invoice sale rates and amounts retain the original GST-inclusive values. Sales party totals, summary headline/payment totals and analytics revenue include GST. HSN/GST breakdowns retain separate taxable and tax values. Sales analytics uses the original inclusive revenue-minus-recorded-cost margin presentation; the diagnostic margin check below remains tax-exclusive.

## Scope

Reviewed the application, data store, configuration, dependencies, existing tests and Access export script. Profiled all 123 CSV tables and compared all columns and records against the supplied Access database through a read-only connection. All 123 tables match after allowing for CSV NULL/empty text representation and floating-point serialization. The source database and exported business records were not edited.

Snapshot coverage: **31 March–7 August 2026**. This is the available transaction coverage, even though the files were supplied in October.

## Fixes

- Corrected tax-exclusive sales values: inclusive line amounts were previously reported as taxable, and GST was then added a second time in some summaries.
- Corrected opening stock conversion: conversion now follows the transaction flag, including free quantities, rather than multiplying all receipt quantities by the item conversion factor.
- Purchase facts now contain only purchase vouchers, excluding 65 opening-stock lines. The two service receipt lines are also outside goods purchases and inventory movements.
- Stock summary and stock analytics honor date filters and use comparable sale-unit quantities for inward/outward movements.
- Replaced single-precision money storage with double precision; preserved HSN codes as text.
- Added customer GST fallback from the account address when the transaction-specific GST field is blank.
- Applied consistent voucher selection and cancellation exclusion; added dimension uniqueness guards against join multiplication.
- Kept purchase bills with missing supplier references during grouping and corrected the supplier column label.
- Removed the financial page's empty-group aggregation failure, made its account filter apply to metrics, and clarified the limits of ledger movement totals.
- Added invalid-date validation, a Data Validation page, snapshot coverage information and CSV cache reload.
- Updated deprecated Streamlit sizing arguments and the minimum Streamlit version. Export and test scripts now return nonzero status on failures; individual CSV export writes use temporary files before replacement.

## Reconciled snapshot totals

- Sales: **7,425 invoices**, recorded invoice value **INR 70,156,990.00**.
- Purchases: **93 bills**, recorded invoice value **INR 66,706,545.78**.
- Sales taxable line value: **INR 67,034,623.61**; recorded goods GST: **INR 3,122,561.15**.
- Purchase taxable line value: **INR 63,794,994.29**; recorded goods GST: **INR 2,911,547.44**.
- Closing stock has **55 items with positive balances**, across 488 item variants. No negative closing balances. The sum across each item's sale units is 18,615; different unit types should not be treated as one physical unit of measure.
- No duplicate core dimension/document keys, orphan goods-line joins or missing invoice item lines were found.

## Source records requiring interpretation

- **13,689 sales lines** have a negative difference between tax-exclusive sales and recorded `Item_Cost`. The cost field and its accounting basis need confirmation in the billing system before treating this as commercial profitability. Source costs were retained.
- **2,177 invoices** differ from summed inclusive item lines by more than INR 0.01. Individual sales differences range from INR -1.30 to +1.15; purchase differences range from INR -1.12 to +1.90. Aggregate differences are sales **INR -194.76** and purchases **INR +4.05**. The dashboard exposes these differences instead of forcing totals to agree.
- **Two service vouchers** are excluded from goods GST reporting. Service tax, notes, credit eligibility and other adjustments must be considered separately for a tax return.
- **181 ledger entries** use document IDs 0 or -1 without ordinary headers. These are retained; the export also uses implicit cash contra entries, so a complete balance sheet or profit-and-loss statement cannot be established from the existing movement summary alone.

## Test coverage and limits

Following the performance fixes, the original suite passed all 70 checks, and the expanded regression suite passed all 43 tests (113 checks/tests total). The regression suite covers all 23 routes, including the validation page, and exercises actual Streamlit execution, navigation, customer filtering, invalid dates, empty goods ranges, stock cutoff changes, tax reconciliation, precision, join cardinality, lazy table loading and cache invalidation. Python compilation and the local server health endpoint were also checked. See `PERFORMANCE.md` for measured timings and the changes made.

The subsequent multi-year implementation passed 75 tests in the full regression run plus two focused background-import/rollback tests, alongside the original 70 checks (147 total). It imports new/changed `.mdb` files automatically, namespaces repeated document/master IDs and avoids adding successive annual stock openings together. The real 2026 totals above reconciled against the imported cache. Earlier years were tested using isolated synthetic databases with colliding IDs. See `MULTI_YEAR.md`.

Native/browser automation is unavailable in this Codex session. Page execution and widget interactions were validated through Streamlit AppTest; visual appearance, responsive layout and browser downloads still need the user's browser check at http://localhost:8502.

The local server binds to loopback only. Existing servers on port 8501 were left running.

## Real-data-only defaults

All generated synthetic annual files, their cache, generator, launcher and
associated reports have been removed. The reference MDB SHA-256 is unchanged;
the real cache contains only 3g2026.mdb. Both localhost ports now use this real
source. Cleanup evidence is in synthetic_cleanup.json (metadata only).

All standard pages, including invoice reconciliation, default both date inputs
to the latest valid current-FY business transaction date. Newer imports advance
that default; cancelled documents do not set it. Current-FY integrity checks
remain FY-wide. Analytics defaults to All years and its complete available
range, expands default bounds after imports, and restores All years on re-entry.

All 139 automated tests passed: 30 defaults checks and 109 regression/policy
tests, with zero failures or skips. The defaults suite covers all 23 routes, with checks
for reopening reports, adding an older annual file, removing demo configuration,
reference-file integrity, automatic latest-date advancement, cancelled
transaction exclusion, and India midnight/FY rollover. See
`date_defaults_results.xml` and `regression_results.xml` for the current results.
Historical importer and forecast fixtures are isolated unit tests and are not
loaded into either dashboard. Forecasts require sufficient real prior-year data;
the current production dataset does not yet meet that requirement.

## Latest page and calculation audit

Repeated the read-only Access comparison: **123 of 123 tables matched**, with
zero table discrepancies. Verified the 11 active SQLite reporting tables against
that snapshot, and compared every sales/purchase fact row's document, item,
customer/supplier, GSTIN, HSN, quantity, amount and tax fields independently.
The source MDB SHA-256 remains
`5330c736bde104d64281d6eedc635ec95ed6094dbb842a3968f97689f7d99595`.
The production folder/cache contains only `3G2026.mdb`; no demonstration years
were added by these tests.

### Issues fixed

- Financial Summary previously removed accounts with net movement below INR
  0.50, hiding real debit and credit activity. It now retains every account with
  nonzero recorded movements, including balanced accounts. For 1 April–7 August,
  this restores **201 accounts** representing **INR 18,984,163.78 on each side**.
  The previous filter would have omitted 209 accounts over the entire exported
  period, which includes pre-FY records. On the latest day, two balanced accounts
  with INR 4,227 on each side are now visible.
- Both HSN pages and both monthly summary tables now include `Other_Tax` and use
  the actual inclusive line total for `Total`. Nonzero cess/additional tax can no
  longer disappear from those totals. The real snapshot has zero such tax;
  isolated regression cases exercise nonzero values, including numeric text.
- Unknown payment modes retain their source code. The former UPI label for mode
  3 was unsupported by the available metadata; its meaning still needs billing
  system confirmation. The 651 mode-3 sales and their amounts remain included.
- Import validation rejects malformed/fractional/out-of-range identifiers,
  non-finite numeric values and missing item/group parent references before
  publication. Failed updates preserve the last good cache. Integer conversion
  also refuses silent truncation/coercion of bad keys.
- Blank item/group names receive explicit fallback labels, so group-by charts
  do not silently discard their revenue. Existing valid names are unchanged.
- Purchase Analytics states its tax-exclusive basis. Sales Analytics states that
  its existing displayed margin uses GST-inclusive revenue and unverified source
  cost; this arithmetic is not a confirmed accounting profit measure.

### Independent numerical coverage

`scripts/test_page_calculations.py` constructs its expected figures directly
from the Access-verified CSVs, without using DataStore/reporting calculations.
It tests each of the 23 pages twice: 7 August alone, and 1 April–7 August 2026.

| Pages | Comparisons |
| --- | --- |
| Home | Invoice-header totals and counts |
| Sales Bill Wise | Every displayed quantity, inclusive rate/amount and party; full filtered totals; pages 2 and 18; combined filters |
| Sales Date Wise / Monthly | Every grouped invoice count, amount and average; chart values |
| Sales HSN / Party Wise / GST No Wise | Every grouped quantity, invoice count, taxable amount and GST component; party chart |
| Purchase Bill Wise | Every supplier bill/reference, grouped inclusive amount and line count; supplier/bill filtering |
| Purchase Date Wise / Monthly | Every invoice count and header amount; chart values |
| Purchase HSN / Party Wise / GST No Wise | Every supplier/GST/HSN group and its amounts, quantities and taxes; party chart |
| Closing Stock | Every item's opening, inward, outward, closing quantity and unit; all three counts |
| Sales / Purchase Summary | Headline metrics, payment groups, tax components and monthly breakdowns |
| GST Summary | Every output/input component, difference metric and monthly amount |
| Financial Summary | Every active account's debit, credit and net movements; all five metrics |
| Stock Analytics | Both movement series for the selected item and the top-items chart |
| Sales Analytics | Daily, item and group chart values; every displayed cost/margin row; insufficient-history state |
| Purchase Analytics | Daily, item and supplier chart values, including empty purchase days |
| GST Analytics | Rate breakdown, output/input/net chart series and table |
| Data Validation | Invoice reconciliation summary and every discrepancy row in the selected range |

All **17,044 sales lines** and **302 purchase lines** match quantity times rate.
Recorded GST differs from recomputed taxable value times rate by at most INR
0.01 on sales lines and INR 0.02 on purchase lines, within component-rounding
tolerance. CGST equals SGST, and no tested line mixes IGST with CGST/SGST.
Configured sales, purchase, return and opening-stock voucher IDs match all
corresponding voucher definitions in the actual source.

Header totals and item-line totals have different source rounding. Home/date/
monthly pages use invoice headers; bill-line/party/summary/analytics pages use
the documented line basis. For example, 7 August sales are INR 622,937 by invoice
headers and INR 622,940.60 by inclusive lines; both refer to the same 54 invoices.
The 2,177 source discrepancies remain visible, comprising 2,100 sales invoices
and 77 purchase bills. No source adjustments were invented to make them equal.

### Running-server checks and remaining limits

All 23 routes were executed through the restarted Streamlit server's actual
WebSocket connection. Every operational page delivered 7 August–7 August;
Analytics delivered the complete 31 March–7 August range. Both health endpoints
on ports 8502/8503 returned `ok`. See `all_pages_live_results.json`.

The separate bill-page benchmark measured first navigation at 1.25 seconds,
warm reruns at 0.27–0.28 seconds, and repeat navigation at 0.28 seconds. A fresh
server's initial Home load took 13.49 seconds during startup; subsequent page
navigation benefits from cached imports. These are local measurements, not a
response-time guarantee. See `audit_performance_server.json`.

The code tests, cache comparison and live transport checks do not inspect browser
pixels or responsive layout. Browser automation surfaces were unavailable in
this session. Source-cost interpretation, mode-3 payment meaning, service tax,
implicit cash contra/opening entries and the existing invoice-rounding
differences remain the limitations described above. Forecast boundary/partial
year/growth/cancellation cases are covered by the policy suite; the production
snapshot still lacks a complete prior FY, so it correctly withholds a forecast.

Final results for this audit:

- **139/139** existing regression, performance, annual-import, reporting-policy
  and date-default tests passed (`full_regression_results.xml`).
- **76/76** independent page-calculation, mapping, cache, filtering, pagination
  and new edge-case tests passed (`page_calculation_results.xml`).
- **2/2** additional quantity/rate/GST arithmetic tests passed
  (`source_arithmetic_results.xml`). Together these are **217 pytest tests**.
- The original **70/70** command-line checks passed. All **123/123** Access/CSV
  table comparisons and **23/23** running-server routes passed separately.
- Compilation succeeded. No source records or source database contents were
  changed. Both real-data servers remain available at 127.0.0.1:8502 and :8503.

There were no failures, errors or skipped tests. One pandas deprecation warning
was emitted by the deliberately all-blank dimension-label fixture; its fallback
labels and retained revenue passed. The supplied production dimensions do not
produce that warning on the installed pandas version.
