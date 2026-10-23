"""Profile every CSV and compare its contents with Access, using a read-only connection.

Run: python scripts/audit_data.py
Writes validation_results.json; does not modify database or CSV exports.
"""
import datetime
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pyodbc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from export_mdb import MDB_PATH, PASSWORD
from data_quality import validation_summary, invoice_reconciliation
from data_store import DataStore as DS


def compare_table(source, exported):
    if list(source.columns) != list(exported.columns) or len(source) != len(exported):
        return "FAIL: shape or columns differ"
    # Access SELECT and its CSV export retain record order; compare every cell.
    for col in source:
        a, b = source[col], exported[col]
        if pd.api.types.is_numeric_dtype(a) and not pd.api.types.is_bool_dtype(a):
            if not np.allclose(pd.to_numeric(a).to_numpy(dtype=float, na_value=np.nan), pd.to_numeric(b).to_numpy(dtype=float, na_value=np.nan), rtol=1e-12, atol=1e-7, equal_nan=True):
                return f"FAIL: numbers differ in {col}"
        elif pd.api.types.is_datetime64_any_dtype(a):
            if not np.array_equal(pd.to_datetime(a).fillna(pd.Timestamp.min).to_numpy(), pd.to_datetime(b).fillna(pd.Timestamp.min).to_numpy()):
                return f"FAIL: dates differ in {col}"
        else:
            # CSV cannot distinguish an empty Access text cell from NULL.
            if not np.array_equal(a.fillna("").astype(str).to_numpy(), b.fillna("").astype(str).to_numpy()):
                return f"FAIL: text differs in {col}"
    return "PASS"


def main():
    warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy")
    connection = pyodbc.connect(
        f"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={MDB_PATH};PWD={PASSWORD};",
        readonly=True, timeout=15)
    tables = []
    try:
        names = {row.table_name for row in connection.cursor().tables(tableType="TABLE") if not row.table_name.startswith("MSys")}
        csv_names = {p.stem for p in (ROOT / "data").glob("*.csv")}
        for name in sorted(names | csv_names):
            if name not in names or name not in csv_names:
                tables.append({"table": name, "comparison": "FAIL: missing database table or CSV"})
                continue
            exported = pd.read_csv(ROOT / "data" / f"{name}.csv", low_memory=False)
            exact = pd.read_csv(ROOT / "data" / f"{name}.csv", dtype="string", keep_default_na=False, na_values=[""])
            source = pd.read_sql(f"SELECT * FROM [{name.replace(']', ']]')}]", connection)
            numeric = exported.select_dtypes(include="number")
            tables.append({"table": name, "rows": len(exported), "columns": len(exported.columns),
                           "duplicate_rows": int(exported.duplicated().sum()),
                           "null_counts": {c: int(v) for c, v in exported.isna().sum().items() if v},
                           "numeric_profile": json.loads(numeric.describe().to_json()) if not numeric.empty else {},
                           "comparison": compare_table(source, exact)})
    finally:
        connection.close()
    recon = invoice_reconciliation()
    result = {"checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "date_min": str(DS.min_date()), "date_max": str(DS.max_date()),
              "tables": tables, "checks": validation_summary().to_dict(orient="records"),
              "totals": {"sales_invoices": DS.sales().Doc_Id.nunique(), "purchase_bills": DS.purchases().Doc_Id.nunique(),
                         "sales_invoice_value": float(recon.query("Type == 'Sales'").Bill_Amt.sum()),
                         "purchase_invoice_value": float(recon.query("Type == 'Purchase'").Bill_Amt.sum()),
                         "sales_taxable": float(DS.sales().taxable_value.sum()),
                         "sales_gst": float(DS.sales().total_gst.sum()),
                         "purchase_taxable": float(DS.purchases().taxable_value.sum()),
                         "purchase_gst": float(DS.purchases().total_gst.sum()),
                         "closing_stock_sale_units": float(DS.closing_stock().closing_qty.sum())},
              "invoice_reconciliation": recon.groupby("Type").agg(Invoices=("Doc_Id", "count"),
                    Invoice_Total=("Bill_Amt", "sum"), Line_Total=("Line_Total", "sum"),
                    Difference=("Difference", "sum")).to_dict(orient="index")}
    output = ROOT / "validation_results.json"
    output.write_text(json.dumps(result, indent=2, default=lambda v: v.item() if hasattr(v, "item") else str(v)), encoding="utf-8")
    failures = [t for t in tables if t["comparison"] != "PASS"]
    print(f"Compared {len(tables)} tables: {len(tables) - len(failures)} matched; {len(failures)} discrepancies.")
    for table in failures:
        print(table["table"], table["comparison"])
    print(json.dumps(result["totals"], indent=2, default=int))
    print(validation_summary().to_string(index=False))
    print(f"Detailed results: {output}")
    return bool(failures)


if __name__ == "__main__":
    sys.exit(main())
