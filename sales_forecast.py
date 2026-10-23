"""Transparent monthly seasonal baseline using closed prior financial years only."""
import numpy as np
import pandas as pd
import config
from reporting import fiscal_bounds, fiscal_label


def project_sales(headers, as_of):
    start, end = fiscal_bounds(as_of)
    frame = headers.loc[headers.Tt_Id.isin(config.SALE_TT_IDS) & (headers.Doc_Cancel == 0)].copy()
    frame = frame.loc[frame.Doc_Date <= pd.Timestamp(as_of)]
    year = frame.Doc_Date.dt.year - (frame.Doc_Date.dt.month < 4).astype(int)
    frame["FY"] = year.astype(str) + "-" + ((year + 1) % 100).astype(str).str.zfill(2)
    frame["MonthNumber"] = frame.Doc_Date.dt.month
    historical = frame.loc[frame.Doc_Date < pd.Timestamp(start)]
    annual = historical.groupby("FY").agg(Sales=("Bill_Amt", "sum"), Invoices=("Doc_Id", "nunique"), Months=("MonthNumber", "nunique")).reset_index()
    eligible = annual.loc[annual.Months == 12].sort_values("FY")
    result = {"history": annual, "reason": "", "monthly": pd.DataFrame(), "growth": 0.0}
    if eligible.empty or int(eligible.iloc[-1].FY[:4]) != start.year - 1:
        result["reason"] = "Load the immediately preceding financial year with sales recorded in all 12 months to enable the seasonal forecast. Partial years are excluded."
        return result
    recent = eligible.tail(4).copy()
    changes = recent.Sales.pct_change(fill_method=None)
    consecutive = recent.FY.str[:4].astype(int).diff().eq(1)
    changes = changes.loc[consecutive & np.isfinite(changes)]
    growth = float(np.clip(changes.median(), -.30, .30)) if len(changes) else 0.0
    result["growth"] = growth
    baseline_year = eligible.iloc[-1].FY
    baseline = historical.loc[historical.FY == baseline_year].groupby("MonthNumber").Bill_Amt.sum()
    current = frame.loc[frame.FY == fiscal_label(as_of)]
    cutoff = current.Doc_Date.max() if not current.empty else pd.Timestamp(start) - pd.Timedelta(days=1)
    actual = current.groupby(current.Doc_Date.dt.to_period("M")).Bill_Amt.sum()
    rows = []
    for month in pd.period_range(start, periods=24, freq="M"):
        value = float(actual.get(month, 0))
        target_fy = month.year - (month.month < 4)
        estimate = float(baseline.get(month.month, 0)) * (1 + growth) ** (target_fy - int(baseline_year[:4]))
        if month.end_time.normalize() <= cutoff.normalize():
            expected, status = value, "Actual"
        elif month.start_time <= cutoff:
            expected, status = max(value, estimate), "Partial month + estimate"
        else:
            expected, status = estimate, "Forecast"
        rows.append({"FY": fiscal_label(month.start_time.date()), "Month": str(month), "Actual": value if month.start_time <= cutoff else np.nan,
                     "Expected": round(expected, 2), "Remaining": round(max(0, expected - value), 2), "Status": status})
    result.update(monthly=pd.DataFrame(rows), baseline_year=baseline_year, cutoff=cutoff.date())
    return result
