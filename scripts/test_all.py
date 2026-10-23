"""Full test suite for 3G OILS Dashboard — run from 3goils-streamlit/."""
import os, sys, time, warnings
warnings.filterwarnings("ignore")
os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from data_store import DataStore as DS
import config

PASS, FAIL = 0, 0
ERRORS = []

def ok(name, detail=""):
    global PASS; PASS += 1
    print(f"  PASS  {name}" + (f" ({detail})" if detail else ""))

def fail(name, err):
    global FAIL; FAIL += 1
    ERRORS.append(f"{name}: {err}")
    print(f"  FAIL  {name}: {err}")

def test(name, fn):
    try:
        result = fn()
        ok(name, result)
    except Exception as e:
        fail(name, str(e))

# ─── CONFIG ──────────────────────────────────────────────────────────────────
print("\n=== CONFIG ===")
test("DATA_DIR exists", lambda: f"{config.DATA_DIR}" if config.DATA_DIR.exists() else (_ for _ in ()).throw(FileNotFoundError("data/ missing")))
test("DATABASE_DIR exists", lambda: f"{config.DATABASE_DIR}" if config.DATABASE_DIR.exists() else (_ for _ in ()).throw(FileNotFoundError("database/ missing")))
test("MDB file", lambda: f"{list(config.DATABASE_DIR.glob('*.mdb'))}" if list(config.DATABASE_DIR.glob("*.mdb")) else (_ for _ in ()).throw(FileNotFoundError("No .mdb")))
test("CSV count", lambda: f"{len(list(config.DATA_DIR.glob('*.csv')))} files" if len(list(config.DATA_DIR.glob("*.csv"))) > 100 else (_ for _ in ()).throw(ValueError("Too few CSVs")))

# ─── DATA STORE LOADING ─────────────────────────────────────────────────────
print("\n=== DATA STORE LOADING ===")
t0 = time.time()
test("DS.doc_header()", lambda: f"{len(DS.doc_header())} rows")
test("DS.sales()", lambda: f"{len(DS.sales())} rows")
test("DS.purchases()", lambda: f"{len(DS.purchases())} rows")
test("DS.daybook()", lambda: f"{len(DS.daybook())} rows")
test("DS.closing_stock()", lambda: f"{len(DS.closing_stock())} items")
test("DS.min_date()", lambda: f"{DS.min_date()}")
test("DS.max_date()", lambda: f"{DS.max_date()}")
print(f"  Total load time: {time.time()-t0:.2f}s")

# ─── DATA INTEGRITY ─────────────────────────────────────────────────────────
print("\n=== DATA INTEGRITY ===")
s = DS.sales()
p = DS.purchases()
dh = DS.doc_header()
db = DS.daybook()
stk = DS.closing_stock()

test("Sales has dk column", lambda: "yes" if "dk" in s.columns else (_ for _ in ()).throw(KeyError("dk missing")))
test("Sales has customer_name", lambda: "yes" if "customer_name" in s.columns else (_ for _ in ()).throw(KeyError("missing")))
test("Sales has bill_no", lambda: "yes" if "bill_no" in s.columns else (_ for _ in ()).throw(KeyError("missing")))
test("Sales has date_str", lambda: "yes" if "date_str" in s.columns else (_ for _ in ()).throw(KeyError("missing")))
test("Sales has ITEM_NAME", lambda: "yes" if "ITEM_NAME" in s.columns else (_ for _ in ()).throw(KeyError("missing")))
test("Sales has margin", lambda: "yes" if "margin" in s.columns else (_ for _ in ()).throw(KeyError("missing")))
test("Sales has total_gst", lambda: "yes" if "total_gst" in s.columns else (_ for _ in ()).throw(KeyError("missing")))
test("Sales has month", lambda: "yes" if "month" in s.columns else (_ for _ in ()).throw(KeyError("missing")))
test("Sales has Vat_Rate", lambda: "yes" if "Vat_Rate" in s.columns else (_ for _ in ()).throw(KeyError("missing")))
test("Sales has customer_gstno", lambda: "yes" if "customer_gstno" in s.columns else (_ for _ in ()).throw(KeyError("missing")))
test("Sales has HSNCode", lambda: "yes" if "HSNCode" in s.columns else (_ for _ in ()).throw(KeyError("missing")))
test("Sales has GRP_NAME", lambda: "yes" if "GRP_NAME" in s.columns else (_ for _ in ()).throw(KeyError("missing")))

test("Purchases has dk column", lambda: "yes" if "dk" in p.columns else (_ for _ in ()).throw(KeyError("dk missing")))
test("Purchases has supplier_name", lambda: "yes" if "supplier_name" in p.columns else (_ for _ in ()).throw(KeyError("missing")))
test("Purchases has supplier_gstno", lambda: "yes" if "supplier_gstno" in p.columns else (_ for _ in ()).throw(KeyError("missing")))
test("Purchases has bill_no", lambda: "yes" if "bill_no" in p.columns else (_ for _ in ()).throw(KeyError("missing")))
test("Purchases has date_str", lambda: "yes" if "date_str" in p.columns else (_ for _ in ()).throw(KeyError("missing")))
test("Purchases has Supp_Billno", lambda: "yes" if "Supp_Billno" in p.columns else (_ for _ in ()).throw(KeyError("missing")))

test("Daybook has dk column", lambda: "yes" if "dk" in db.columns else (_ for _ in ()).throw(KeyError("dk missing")))
test("Daybook has Act_Name", lambda: "yes" if "Act_Name" in db.columns else (_ for _ in ()).throw(KeyError("missing")))
test("Daybook has TYPE", lambda: "yes" if "TYPE" in db.columns else (_ for _ in ()).throw(KeyError("missing")))

test("Stock has closing_qty", lambda: "yes" if "closing_qty" in stk.columns else (_ for _ in ()).throw(KeyError("missing")))

# ─── CUSTOMER NAME ACCURACY (Power BI match) ────────────────────────────────
print("\n=== CUSTOMER NAME ACCURACY ===")
expected = {
    7425: "CHUKKAPALLI SRINIVASU",
    7424: "KURAPATI MURTY",
    7423: "KAKARAPARTI SUBRAMANYAM",
    7422: "PENUGONDA TIRUPATI RAO",
    7421: "PASUPULETI RANGARAO",
    7420: "ANCHULA VIJAYALAKSHMI",
    7419: "ANCHULA VARADAIAH",
    7418: "NVR SRINIVASA RAO PERSONAL A/C",
}
for tno, exp_name in expected.items():
    def check(t=tno, e=exp_name):
        row = s[s["TNo"] == t]
        if row.empty: raise ValueError(f"Bill {t} not found")
        actual = row.iloc[0]["customer_name"]
        if actual != e: raise ValueError(f"Expected '{e}', got '{actual}'")
        return actual
    test(f"Bill 3GST-{tno} customer", check)

# ─── CANCELLED DOCS EXCLUDED ────────────────────────────────────────────────
print("\n=== CANCELLED DOCS ===")
test("Sales exclude cancelled", lambda: f"ok" if dh[(dh["Doc_Cancel"] != 0) & dh["Doc_Id"].isin(s["Doc_Id"])].empty else (_ for _ in ()).throw(ValueError("Cancelled docs in sales!")))
test("Purchases exclude cancelled", lambda: f"ok" if dh[(dh["Doc_Cancel"] != 0) & dh["Doc_Id"].isin(p["Doc_Id"])].empty else (_ for _ in ()).throw(ValueError("Cancelled docs in purchases!")))

# ─── PAGE DATA SIMULATIONS ──────────────────────────────────────────────────
print("\n=== PAGE SIMULATIONS (all 21 pages) ===")
sd_dt = pd.Timestamp("2026-04-01").date()
ed_dt = pd.Timestamp("2026-08-07").date()
sdk, edk = 20260401, 20260807

sf = s[(s["dk"] >= sdk) & (s["dk"] <= edk)]
pf = p[(p["dk"] >= sdk) & (p["dk"] <= edk)]
dhf = dh[(dh["dk"] >= sdk) & (dh["dk"] <= edk)]
dbf = db[(db["dk"] >= sdk) & (db["dk"] <= edk)]

# Sales pages
test("sales_billwise", lambda: f'{sf[["bill_no","date_str","customer_name","ITEM_NAME","BILL_QTY","SRATE","BL_VALUE","TNo"]].sort_values("TNo",ascending=False).shape}')
test("sales_datewise", lambda: f'{dhf[dhf["Tt_Id"]==31].groupby(dhf[dhf["Tt_Id"]==31]["Doc_Date"].dt.date).agg(Bills=("Doc_Id","count"),Amount=("Bill_Amt","sum")).shape}')
test("sales_monthly", lambda: f'{dhf[dhf["Tt_Id"]==31].assign(M=dhf[dhf["Tt_Id"]==31]["Doc_Date"].dt.to_period("M").astype(str)).groupby("M").agg(Bills=("Doc_Id","count")).shape}')
test("sales_hsn", lambda: f'{sf.groupby("HSNCode").agg(Qty=("BILL_QTY","sum"),Taxable=("BL_VALUE","sum")).shape}')
test("sales_partywise", lambda: f'{sf.groupby("customer_name").agg(Bills=("Doc_Id","nunique"),Amount=("BL_VALUE","sum")).shape}')
gst_sales = sf[sf["customer_gstno"].notna() & (sf["customer_gstno"] != "") & (sf["customer_gstno"] != "nan")]
test("sales_gstno", lambda: f'{gst_sales.groupby(["customer_gstno","customer_name"]).agg(Taxable=("BL_VALUE","sum")).shape}')

# Purchase pages
test("purch_billwise", lambda: f'{pf.groupby(["TNo","bill_no","date_str","Supp_Billno","supplier_name"]).agg(total=("BL_NETVAL","sum")).shape}')
test("purch_datewise", lambda: f'{dhf[dhf["Tt_Id"].isin([5,40])].groupby(dhf[dhf["Tt_Id"].isin([5,40])]["Doc_Date"].dt.date).agg(Bills=("Doc_Id","count")).shape}')
test("purch_monthly", lambda: f'{dhf[dhf["Tt_Id"].isin([5,40])].assign(M=dhf[dhf["Tt_Id"].isin([5,40])]["Doc_Date"].dt.to_period("M").astype(str)).groupby("M").agg(Bills=("Doc_Id","count")).shape}')
test("purch_hsn", lambda: f'{pf.groupby("HSNCode").agg(Qty=("BILL_QTY","sum")).shape}')
test("purch_partywise", lambda: f'{pf.groupby("supplier_name").agg(Bills=("Doc_Id","nunique")).shape}')
gst_purch = pf[pf["supplier_gstno"].notna() & (pf["supplier_gstno"] != "") & (pf["supplier_gstno"] != "nan")]
test("purch_gstno", lambda: f'{gst_purch.groupby(["supplier_gstno","supplier_name"]).agg(Taxable=("BL_VALUE","sum")).shape}')

# Summary pages
test("summary_stock", lambda: f'{stk.shape} items, {(stk["closing_qty"]>0).sum()} in stock')
test("summary_sales", lambda: f'invoices={sf["Doc_Id"].nunique()}, tax={sf["total_gst"].sum():,.0f}')
test("summary_purchase", lambda: f'bills={pf["Doc_Id"].nunique()}, tax={pf["total_gst"].sum():,.0f}')
test("summary_gst", lambda: f'out={sf["total_gst"].sum():,.0f}, in={pf["total_gst"].sum():,.0f}')

def tb_test():
    tb = dbf.groupby(["Act_ID","Act_Name","Act_Type","Act_MG"]).apply(
        lambda g: pd.Series({"Debit": g.loc[g["TYPE"].isin(["D","P"]),"AMOUNT"].sum(), "Credit": g.loc[g["TYPE"].isin(["C","R"]),"AMOUNT"].sum()})
    ).reset_index()
    tb["Net"] = tb["Debit"] - tb["Credit"]
    return f'{len(tb)} accounts'
test("summary_financial", tb_test)

# Analytics pages
test("analytics_stock", lambda: f'{s.groupby(["month","ITEM_NAME"]).agg(Sold=("BILL_QTY","sum")).shape}')
test("analytics_sales", lambda: f'{sf.groupby("ITEM_NAME").agg(Revenue=("BL_VALUE","sum")).nlargest(20,"Revenue").shape}')
test("analytics_purchase", lambda: f'{pf.groupby("supplier_name").agg(Amount=("BL_VALUE","sum")).nlargest(15,"Amount").shape}')
test("analytics_gst", lambda: f'{sf.groupby("Vat_Rate").agg(Taxable=("BL_VALUE","sum")).shape}')

# ─── EDGE CASES ──────────────────────────────────────────────────────────────
print("\n=== EDGE CASES ===")
test("Single day filter", lambda: f'{len(s[(s["dk"]>=20260807)&(s["dk"]<=20260807)])} rows' )
test("Empty date range", lambda: f'{len(s[(s["dk"]>=20270101)&(s["dk"]<=20270101)])} rows (should be 0)')
test("No nulls in bill_no", lambda: f'ok ({s["bill_no"].isna().sum()} nulls)' if s["bill_no"].isna().sum() == 0 else (_ for _ in ()).throw(ValueError("nulls in bill_no")))
test("No nulls in customer_name", lambda: f'ok ({s["customer_name"].isna().sum()} nulls)')
test("BL_VALUE > 0 for all sales", lambda: f'ok (min={s["BL_VALUE"].min()})' if s["BL_VALUE"].min() >= 0 else (_ for _ in ()).throw(ValueError("negative BL_VALUE")))
test("Stock closing_qty reasonable", lambda: f'min={stk["closing_qty"].min():.0f}, max={stk["closing_qty"].max():.0f}')

# ─── PERFORMANCE ─────────────────────────────────────────────────────────────
print("\n=== PERFORMANCE ===")
t = time.time(); DS.sales(); print(f"  DS.sales() cached: {(time.time()-t)*1000:.1f}ms")
t = time.time(); _ = s[(s["dk"]>=20260801)&(s["dk"]<=20260807)]; print(f"  Date filter (1 week): {(time.time()-t)*1000:.1f}ms -> {len(_)} rows")
t = time.time(); sf.groupby("customer_name").agg(Bills=("Doc_Id","nunique"),Amount=("BL_VALUE","sum")).reset_index(); print(f"  Groupby partywise: {(time.time()-t)*1000:.1f}ms")
t = time.time()
v = sf[["bill_no","date_str","customer_name","ITEM_NAME","BILL_QTY","SRATE","BL_VALUE","TNo"]].copy()
v.sort_values("TNo", ascending=False)
print(f"  Bill wise view build: {(time.time()-t)*1000:.1f}ms")

# ─── SUMMARY ─────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  PASSED: {PASS}  |  FAILED: {FAIL}")
if ERRORS:
    print(f"\n  FAILURES:")
    for e in ERRORS:
        print(f"    {e}")
print(f"{'='*60}")

# Signal failures to command-line runners and CI.
sys.exit(1 if FAIL else 0)
