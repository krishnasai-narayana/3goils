# Current financial year and historical analytics

Home, Sales, Purchase, Summary and Data Validation show the current Indian
financial year only, using India's current date (UTC+05:30) and April–March boundaries.
On October 22, 2026 that is FY 2026–27. Their date inputs cannot select an earlier
year. The year selector is available only on the four Analytics pages, where
All years or individual financial years can be selected.

Returning from an older Analytics year resets operational dates and filters.
Current-year data is selected before report aggregation, customer/bill selection,
invoice reconciliation and ledger summaries. A missing current-year annual file
produces empty operational reports with an explanatory message, rather than
falling back to the latest historical file. Stock retains the current source's
opening balance as a balance; previous annual snapshots are not added to it.
The automatic page check also refreshes at a date/FY rollover.

## Sales outlook

Open Analytics → Sales. Existing historical charts and item margins remain;
the Sales outlook section adds prior-FY invoice totals and a 24-month table
covering the current and next FY. Historical chart filters do not alter training
data, and the forecast says so explicitly.

The model uses recorded invoice amounts including GST and invoice rounding:

1. Remove cancelled, non-sales and future-dated documents from the input.
2. Consider prior financial years only. A candidate needs sales records in all
   12 calendar months. This is a conservative coverage check, not certification
   that an annual source is complete. The immediately preceding FY must qualify.
3. Use that previous year's monthly pattern as the seasonal baseline.
4. Estimate annual growth from the median of up to three consecutive historical
   year-on-year changes among the last four qualifying years. Ignore nonfinite
   changes and default to zero growth when no usable comparison exists. Limit
   the assumed annual growth to -30% through +30%, as shown on screen.
5. Scale the baseline one year forward for the current FY and two years forward
   for the next FY. Completed months retain their recorded actuals. A partial
   month uses the greater of recorded sales and the baseline estimate; remaining
   months use the historical estimate. Future actual cells remain blank.

Actuals are current through the latest loaded current-FY sales date, which is
displayed. Later missing records are estimated rather than treated as observed
zero sales. Without current-year records, the outlook is explicitly marked as
entirely historical. Without the required prior-year coverage, the app explains
that more data is needed and does not invent a forecast.

These are transparent seasonal planning estimates, not guaranteed predictions,
confidence intervals or a backtested statistical model. Promotions, availability,
price changes and incomplete source records can materially change outcomes.
The real dataset currently has only FY 2026–27; projections become
available after a suitable FY 2025–26 database is added and imported.

## Real data and defaults

All generated synthetic MDB files, their cache, generator, launcher and demo
configuration have been removed. Both localhost ports 8502 and 8503 use the real
database folder. Current data contains only FY 2026–27; other years will appear
after real annual files are imported. Forecasts remain unavailable until the
required real historical coverage exists.

Sales and Purchase Bill Wise default both From and To to the latest valid
transaction date in the current FY (7 August 2026 for the supplied source).
Their Date Wise, Monthly, HSN, Party Wise and GST No Wise reports default From
to 1 April and To to that latest date, covering all available current-FY data.
Home, Summary and Data Validation retain their latest-day defaults. Cancelled
documents do not move the latest day forward. Newer imports update the default
automatically; reopening a report restores the default appropriate to that page.
Analytics defaults to All years and the full available date
range. Entering Analytics from Home resets an earlier FY selection to All years.
When an imported annual file extends the range, an existing All years view using
its default bounds expands with it. Explicit date filters remain user choices.
