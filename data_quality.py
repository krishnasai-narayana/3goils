"""Read-only reconciliation checks exposed by the dashboard and validation scripts."""
import pandas as pd
import config
from data_store import DataStore as DS, _load_raw


def invoice_reconciliation(store=DS):
    result = []
    for label, ids, lines in [("Sales", config.SALE_TT_IDS, store.sales()),
                              ("Purchase", config.PURCHASE_TT_IDS, store.purchases())]:
        headers = store.doc_header().loc[lambda d: d.Tt_Id.isin(ids), ["Doc_Id", "Bill_Amt"]]
        totals = lines.groupby("Doc_Id").BL_NETVAL.sum().rename("Line_Total")
        frame = headers.merge(totals, on="Doc_Id", how="left", validate="one_to_one")
        frame["Difference"] = frame.Bill_Amt - frame.Line_Total
        frame["Type"] = label
        result.append(frame)
    return pd.concat(result, ignore_index=True)


def validation_summary(store=DS):
    r = {key: store.raw_table(key) for key in ["dh", "acc", "nt", "ig", "sd", "sr", "db"]} if hasattr(store, "raw_table") else _load_raw()
    rows = []
    def add(check, count, detail, warning=False):
        rows.append({"Check": check, "Count": int(count), "Status": "Review" if count and warning else "Pass", "Detail": detail})
    for key, col in [("dh", "Doc_Id"), ("acc", "Act_Id"), ("nt", "Doc_Id"), ("ig", "IC_ID")]:
        add(f"Duplicate {key}.{col}", r[key][col].duplicated().sum(), "Must be zero", True)
    for key in ["sd", "sr"]:
        add(f"Orphan {key} document IDs", (~r[key].DOC_ID.isin(r["dh"].Doc_Id)).sum(), "Must be zero", True)
        add(f"Orphan {key} item IDs", (~r[key].IC_ID.isin(r["ig"].IC_ID)).sum(), "Must be zero", True)
    add("Cancelled documents excluded", (r["dh"].Doc_Cancel != 0).sum(), "Excluded from dashboard totals")
    add("Negative closing stock", (store.closing_stock().closing_qty < -0.001).sum(), "Balance in sale units", True)
    add("Negative sales line margins", (store.sales().margin < -0.01).sum(), "Tax-exclusive line value minus recorded Item_Cost", True)
    add("Services outside goods GST reports", r["dh"].Tt_Id.isin([32, 36, 37, 38]).sum(), "Review services separately", True)
    recon = invoice_reconciliation(store)
    add("Invoices without item lines", recon.Line_Total.isna().sum(), "Must be zero", True)
    add("Invoice/line differences over INR 0.01", (recon.Difference.abs() > 0.01).sum(), "Rounding and source adjustments; details below", True)
    add("Ledger entries without document header", (~r["db"].Doc_ID.isin(r["dh"].Doc_Id)).sum(), "Includes source IDs 0 and -1; retained as ledger entries", True)
    return pd.DataFrame(rows)
