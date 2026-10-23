# Dashboard performance investigation — 22 October 2026

## Findings

The largest reproduced delay was the initial application/session load. The original running server took 11.2569 seconds to deliver the first Home page. Its first Sales → Bill Wise navigation took 0.5197 seconds; subsequent loads were 0.1887–0.2073 seconds. Cached access to the sales fact itself was approximately 0.0001 seconds, so a persistent database query was not the cause.

Profiling also found unnecessary work:

- Chart libraries were imported before any page was shown, including Home and Bill Wise.
- The original raw-data loader eagerly read all eleven backing tables, including purchase receipts and the daybook when displaying Home.
- Navigation buttons rendered the previous page, changed the page state and then explicitly reran the whole script.
- Bill Wise filtered/copied a 106-column sales fact to display seven columns and sorted the same transactions on every interaction.
- Date strings were formatted once per sales line instead of once per distinct document date.
- Streamlit source inspection and module/file scanning incurred substantial path-resolution overhead in this Windows/OneDrive environment. Automatic source-file watching was enabled during normal dashboard use.

## Changes

- Import Plotly only in pages that use charts.
- Cache each backing CSV separately and load it only when requested. Home reads only `Doc_Header.csv`. Bill Wise does not load purchase receipts, the daybook or transaction-type settings.
- Use button callbacks so navigation sets the page before the script runs, avoiding the extra render/rerun.
- Keep required fields in the sales fact, and cache a separate compact bill dataset already sorted by date/bill sequence. It initially contained 11 columns; multi-year support adds three source/year/filter fields. All 17,044 sales lines remain available; no pagination or truncation was introduced.
- Reuse document date/month labels and format each distinct date once.
- Disable source-file watching in the local server configuration. Restart the server after Python/config changes. CSV cache reload remains available and is tested.

GST-inclusive invoice rates, invoice amounts and sales presentation are preserved. Raw CSV/database values were not edited.

## Measurements

The same instrumented AppTest sequence, in a fresh Python test process for each version, measured:

- Initial Home execution: **16.1924 → 4.3719 seconds** (about 73% lower).
- First Bill Wise navigation: **1.5253 → 1.3768 seconds**. This still includes first access to the customer/item/sales CSVs after lazy loading.
- Full-range warm display, including all 17,044 rows and 7,425 bill options: **0.4759 → 0.4197 seconds**.
- Single-bill filtering: **0.4102 → 0.3497 seconds**.
- Returning to Bill Wise: **0.4783 → 0.3033 seconds**.

After restarting the optimized local server, a separate session using its actual WebSocket observed Home at **0.3434 seconds**, Bill Wise navigation at **0.2038 seconds**, repeat loads at **0.1875–0.1981 seconds**, and returning to Bill Wise at **0.2020 seconds**.

These are observed backend/test timings, not guaranteed browser-rendering times. OS/filesystem caches, process startup, profiling overhead and machine load affect them. AppTest and live-server measurements are separate methods and should not be compared directly. Browser automation is unavailable in this session, so client rendering latency was not measured.

Reproducible records: `performance_before.json`, `performance_after.json`, `performance_server_before.json` and `performance_server_after.json`. Test-runtime import time is recorded separately from the AppTest page timings.

## Verification

All **70 original checks** and all **43 regression tests** passed (113 total). The expanded regression suite exercises all 23 routes, filters, empty ranges, invoice source values, GST-inclusive sales totals, stock cutoff dates and CSV cache reload. Four additional guards verify lazy table access, single-render navigation, reuse of the compact sorted bill dataset and cache invalidation. The restarted server returned HTTP 200 from its health endpoint and logged no application exceptions during the live navigation benchmark.

Subsequent multi-year support replaces the manual CSV snapshot with a background-built SQLite cache, while retaining lazy page loading and bounded caches. The latest live-server measurement is in `performance_server_multi_year.json`: initial Home 8.51s, first Bill Wise 1.60s, repeat bill loads 0.14–0.17s, repeat navigation 0.19s. This fresh-session observation illustrates that first-load/import overhead remains different from warm navigation. See `MULTI_YEAR.md` for the latest validation count and automatic-import design.

## Current real-data configuration

Synthetic scale fixtures, their cache and demo benchmark reports were removed
at the user's request. Required-column projection and 1,000-row Bill Wise
pagination remain in place. Both ports 8502 and 8503 now use only the real source.
Standard reports default to the latest valid current-FY transaction date;
initial daily timings should not be compared with earlier full-range tests.
Analytics defaults to all imported real FYs. See README.md and ANALYTICS.md.
