"""Independent page oracles from the CSV snapshot verified against Access.

Expected values never call DataStore/reporting calculation functions. Both the
latest-day and full-current-FY views are checked, including serialized charts.
"""
import base64
import datetime as dt
import json
import sqlite3

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import config
import database_sync
import data_store
import reporting
from data_store import DataStore as DS
from scripts.test_validation import PAGES, ROOT
from scripts.test_multi_database import importer, add, annual_tables


@pytest.fixture(scope="module")
def raw_source():
    tables = {name: pd.read_csv(config.DATA_DIR / f"{name}.csv", low_memory=False,
                               dtype={"HSNCode": "string", "GSTNO": "string"})
              for name in database_sync.TABLE_COLUMNS}
    h = tables["Doc_Header"].copy()
    h["Doc_Date"] = pd.to_datetime(h.Doc_Date)
    h["month"] = h.Doc_Date.dt.strftime("%Y-%m")
    h["date_str"] = h.Doc_Date.dt.strftime("%d-%m-%Y")
    h["bill_no"] = h.TSeries + "-" + h.TNo.astype(str)
    tables["headers"] = h[h.Doc_Cancel.eq(0)]
    a = tables["Accmst"].set_index("Act_Id")
    ad = tables["AccAdr"].set_index("Act_Id").GSTNO.fillna("").str.strip()
    nt = tables["NAME_TRAN"].set_index("Doc_Id")
    dim = tables["Item_Grp"].copy()
    dim["ITEM_NAME"] = dim.ITEM_ID.map(tables["Items"].set_index("ITEM_ID").ITEM_NAME)
    dim["GRP_NAME"] = dim.GRP_ID.map(tables["Groups"].set_index("GRP_ID").GRP_NAME)
    dim["HSNCode"] = dim.HSNCode.fillna("Unspecified").str.strip().replace("", "Unspecified")
    dim = dim.set_index("IC_ID")
    for name, ids, line in [("sales", [30, 31, 39], "Stock_Delv"), ("purchases", [5, 40], "Stock_Recd")]:
        docs = tables["headers"].loc[lambda x: x.Tt_Id.isin(ids)].set_index("Doc_Id")
        f = tables[line].loc[lambda x: x.DOC_ID.isin(docs.index)].copy()
        f["Doc_Id"] = f.DOC_ID
        for col in ["Doc_Date", "month", "date_str", "bill_no", "TNo", "Mode", "Supp_Billno"]:
            f[col] = f.DOC_ID.map(docs[col])
        for col in ["ITEM_NAME", "GRP_NAME", "HSNCode"]:
            f[col] = f.IC_ID.map(dim[col])
        accounts = f.DOC_ID.map(docs.Act_ID)
        if name == "sales":
            f["party"] = f.DOC_ID.map(nt.Act_Name).replace(r"^\s*$", np.nan, regex=True).fillna(accounts.map(a.Act_Name)).fillna("Unknown customer")
            f["gstin"] = f.DOC_ID.map(nt.GSTNO).fillna("").str.strip().replace("", pd.NA).fillna(accounts.map(ad)).fillna("")
        else:
            f["party"] = accounts.map(a.Act_Name).fillna("Unknown supplier")
            f["gstin"] = accounts.map(ad)
        f["tax"] = f.CGSTAMT + f.SGSTAMT + f.IGSTAMT
        f["other"] = f.cessAmt.fillna(0) + f.CCAMT.fillna(0)
        f["taxable"] = f.BL_NETVAL - f.tax - f.other
        tables[name] = f
    moves = []
    for line, ids, direction in [("Stock_Recd", [0, 5, 40, 6], "Inward"), ("Stock_Delv", [30, 31, 39, 7, 41], "Outward")]:
        dates = tables["headers"].loc[lambda x: x.Tt_Id.isin(ids)].set_index("Doc_Id").Doc_Date
        m = tables[line].loc[lambda x: x.DOC_ID.isin(dates.index)].copy()
        m["Doc_Date"] = m.DOC_ID.map(dates)
        conversion = m.IC_ID.map(dim.IssueConv).clip(lower=1)
        m["q"] = (m.BILL_QTY + m.BILL_FREE) * conversion.where(m.stockconv.eq(1), 1)
        m["direction"] = direction
        m["month"] = m.Doc_Date.dt.strftime("%Y-%m")
        m["ITEM_NAME"] = m.IC_ID.map(dim.ITEM_NAME)
        moves.append(m)
    tables["movements"] = pd.concat(moves, ignore_index=True)
    tables["dim"] = dim.reset_index()
    db = tables["DayBook"].copy()
    db["Doc_Date"] = pd.to_datetime(db.TRDATE)
    db = db[~db.Doc_ID.isin(h.loc[h.Doc_Cancel.ne(0), "Doc_Id"])]
    for col in ["Act_Name", "Act_Type", "Act_MG"]:
        db[col] = db.Act_ID.map(a[col])
    db["Debit"] = db.AMOUNT.where(db.TYPE.isin(["D", "P"]), 0)
    db["Credit"] = db.AMOUNT.where(db.TYPE.isin(["C", "R"]), 0)
    tables["ledger"] = db
    return tables


def same(actual, expected):
    """Compare all rows and columns, including duplicate multiplicity."""
    assert set(expected.columns) <= set(actual.columns), (actual.columns, expected.columns)
    cols = list(expected.columns)
    a, e = actual[cols].copy(), expected.copy()
    for col in cols:
        if not pd.api.types.is_numeric_dtype(e[col]):
            a[col] = a[col].fillna("").astype(str)
            e[col] = e[col].fillna("").astype(str)
    a = a.sort_values(cols, kind="stable").reset_index(drop=True)
    e = e.sort_values(cols, kind="stable").reset_index(drop=True)
    pd.testing.assert_frame_equal(a, e, check_dtype=False, atol=0.000001, rtol=1e-12)


def metrics(at, expected):
    assert len(at.metric) == len(expected)
    for widget, value in zip(at.metric, expected):
        assert widget.value == value, (widget.label, widget.value, value)


def money(value, decimals=0):
    return f"₹{value:,.{decimals}f}"


def chart(at, index, expected, x="x", y="y", trace=0):
    traces = json.loads(at.get("plotly_chart")[index].proto.spec)["data"]
    if expected.empty and len(traces) <= trace:
        return
    data = traces[trace]
    for axis, col in [(x, expected.columns[0]), (y, expected.columns[1])]:
        value = data[axis]
        if isinstance(value, dict) and "bdata" in value:
            value = np.frombuffer(base64.b64decode(value["bdata"]), dtype=value["dtype"])
        target = expected[col].to_numpy()
        if pd.api.types.is_numeric_dtype(target):
            np.testing.assert_allclose(np.asarray(value, dtype=float), target, atol=1e-6, rtol=1e-12)
        elif len(target) and isinstance(target[0], dt.date):
            assert list(pd.to_datetime(value).date) == list(pd.to_datetime(target).date)
        else:
            assert [str(v) for v in value] == [str(v) for v in target]


def tax_agg(f, key, qty=False, items=False):
    spec = dict(Taxable=("taxable", "sum"), CGST=("CGSTAMT", "sum"), SGST=("SGSTAMT", "sum"), IGST=("IGSTAMT", "sum"))
    if qty:
        spec.update(Qty=("BILL_QTY", "sum"), Other_Tax=("other", "sum"), Total=("BL_NETVAL", "sum"))
    spec["Items" if items else "Bills"] = ("IC_ID" if items else "Doc_Id", "nunique")
    return f.groupby(key).agg(**spec).reset_index()


@pytest.mark.parametrize("period", ["latest", "full_fy"])
@pytest.mark.parametrize("page", PAGES)
def test_every_page_numbers_against_independent_raw_records(page, period, raw_source, monkeypatch):
    monkeypatch.setattr(reporting, "today", lambda: dt.date(2026, 10, 22))
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.session_state.page = page
    at.run()
    start = dt.date(2026, 8, 7) if period == "latest" else dt.date(2026, 4, 1)
    end = dt.date(2026, 8, 7)
    for widget in at.date_input:
        widget.set_value(start if widget.label == "From" else end)
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    def window(f):
        return f[f.Doc_Date.between(pd.Timestamp(start), pd.Timestamp(end))]
    s, p, h = [window(raw_source[k]) for k in ["sales", "purchases", "headers"]]
    sh, ph = h[h.Tt_Id.isin([30, 31, 39])], h[h.Tt_Id.isin([5, 40])]
    frames = [f.value for f in at.dataframe]
    if page == "home":
        metrics(at, [money(sh.Bill_Amt.sum()), money(ph.Bill_Amt.sum()), f"{len(sh):,}", f"{len(ph):,}"])
    elif page == "sales_billwise":
        metrics(at, [f"{s.Doc_Id.nunique():,}", f"{len(s):,}", f"{s.BILL_QTY.sum():,.0f}", money(s.BL_NETVAL.sum(), 2)])
        v = s.sort_values(["Doc_Date", "TNo"], ascending=False, kind="stable").head(1000)
        same(frames[0], v[["bill_no", "date_str", "party", "ITEM_NAME", "BILL_QTY", "SRATE", "BL_VALUE"]].set_axis(["Bill_Num", "Date", "Customer_Name", "Item_Name", "Quantity", "Sale_Rate", "Amount"], axis=1))
    elif page == "purch_billwise":
        metrics(at, [f"{p.Doc_Id.nunique():,}", f"{len(p):,}", money(p.BL_NETVAL.sum(), 2)])
        expected = p.groupby(["Doc_Id", "bill_no", "date_str", "Supp_Billno", "party"], dropna=False).BL_NETVAL.sum().reset_index().drop(columns="Doc_Id")
        same(frames[0], expected.set_axis(["bill_reference", "date", "supplier_bill_no", "supplier_name", "bill_total"], axis=1))
    elif page.endswith(("_datewise", "_monthly")):
        f = sh.copy() if page.startswith("sales") else ph.copy()
        monthly = page.endswith("_monthly")
        key = "Month" if monthly else "Date"
        f[key] = f.Doc_Date.dt.strftime("%Y-%m") if monthly else f.Doc_Date.dt.date
        agg = dict(Bills=("Doc_Id", "count"), Amount=("Bill_Amt", "sum"))
        if page == "sales_monthly":
            agg["Avg"] = ("Bill_Amt", "mean")
        expected = f.groupby(key).agg(**agg).reset_index().sort_values(key, ascending=monthly)
        same(frames[0], expected)
        chart(at, 0, expected[[key, "Amount"]])
    elif page.endswith("_hsn"):
        f = s if page.startswith("sales") else p
        expected = tax_agg(f, "HSNCode", qty=True, items=True)
        expected["Tax"] = expected.CGST + expected.SGST + expected.IGST
        same(frames[0], expected)
    elif page.endswith("_partywise"):
        sale = page.startswith("sales")
        f = s if sale else p
        amount, source, party, limit = ("Amount", "BL_NETVAL", "Customer", 20) if sale else ("Taxable", "taxable", "Supplier", 15)
        expected = f.groupby("party").agg(Bills=("Doc_Id", "nunique"), Qty=("BILL_QTY", "sum"), **{amount: (source, "sum"), "Tax": ("tax", "sum")}).reset_index().rename(columns={"party": party}).sort_values(amount, ascending=False)
        same(frames[0], expected)
        chart(at, 0, expected[[amount, party]].head(limit))
    elif page.endswith("_gstno"):
        sale = page.startswith("sales")
        f = (s if sale else p).loc[lambda d: d.gstin.fillna("").ne("")]
        if not f.empty:
            expected = tax_agg(f, ["gstin", "party"]).rename(columns={"gstin": "GSTIN", "party": "Party" if sale else "Supplier"})
            expected["Tax"] = expected.CGST + expected.SGST + expected.IGST
            same(frames[0], expected)
        else:
            assert not frames and len(at.info)
    elif page in ["summary_sales", "summary_purchase"]:
        sale = page == "summary_sales"
        f = s if sale else p
        metrics(at, [f"{f.Doc_Id.nunique():,}", f"{f.BILL_QTY.sum():,.0f}", money(f.BL_NETVAL.sum() if sale else f.taxable.sum()), money(f.tax.sum())])
        same(frames[-1], tax_agg(f, "month", qty=True))
        if sale:
            same(frames[0], pd.DataFrame({"Component": ["CGST", "SGST", "IGST"], "Amount": [s.CGSTAMT.sum(), s.SGSTAMT.sum(), s.IGSTAMT.sum()]}))
            pay = s.groupby("Mode").agg(Bills=("Doc_Id", "nunique"), Amount=("BL_NETVAL", "sum")).reset_index()
            pay["Pay"] = pay.Mode.map({0: "Cash", 1: "Credit"}).fillna(pay.Mode.map(lambda m: f"Other (mode {m})"))
            same(frames[1], pay[["Pay", "Bills", "Amount"]])
    elif page in ["summary_gst", "analytics_gst"]:
        sm = s.groupby("month")[["CGSTAMT", "SGSTAMT", "IGSTAMT"]].sum().add_prefix("Out_")
        pm = p.groupby("month")[["CGSTAMT", "SGSTAMT", "IGSTAMT"]].sum().add_prefix("In_")
        expected = sm.join(pm, how="outer").fillna(0)
        expected.columns = ["Out_CGST", "Out_SGST", "Out_IGST", "In_CGST", "In_SGST", "In_IGST"]
        expected["Net"] = expected.iloc[:, :3].sum(axis=1) - expected.iloc[:, 3:6].sum(axis=1)
        if page == "summary_gst":
            values = [[f[c].sum() for c in ["CGSTAMT", "SGSTAMT", "IGSTAMT"]] for f in [s, p]]
            values.append([v - w for v, w in zip(*values)])
            metrics(at, [money(v) for row in values for v in [*row, sum(row)]])
            same(frames[0], expected.reset_index())
        else:
            gt = pd.DataFrame({"Output": expected.iloc[:, :3].sum(axis=1), "Input": expected.iloc[:, 3:6].sum(axis=1), "Net": expected.Net}).reset_index()
            same(frames[0], gt)
            rates = s.groupby("Vat_Rate").taxable.sum().reset_index()
            rates["Rate"] = rates.Vat_Rate.astype(float).astype(str) + "%"
            chart(at, 0, rates[["Rate", "taxable"]])
            for n, col in enumerate(["Output", "Input", "Net"]):
                chart(at, 1, gt[["month", col]], trace=n)
    elif page == "summary_stock":
        m = raw_source["movements"].loc[lambda d: d.Doc_Date.le(pd.Timestamp(end))]
        before = m[m.Doc_Date.lt(pd.Timestamp(start))]
        within = window(m)
        opening = before.q.where(before.direction.eq("Inward"), -before.q).groupby(before.IC_ID).sum()
        expected = raw_source["dim"][["IC_ID", "ITEM_NAME", "GRP_NAME", "Sale_PACK"]].copy()
        expected["Opening"] = expected.IC_ID.map(opening).fillna(0)
        for col, direction in [("In", "Inward"), ("Out", "Outward")]:
            expected[col] = expected.IC_ID.map(within[within.direction.eq(direction)].groupby("IC_ID").q.sum()).fillna(0)
        expected["Balance"] = expected.Opening + expected.In - expected.Out
        expected = expected.drop(columns="IC_ID").rename(columns={"ITEM_NAME": "Item", "GRP_NAME": "Group", "Sale_PACK": "Unit"})
        same(frames[0], expected)
        metrics(at, [str(expected.Balance.gt(0).sum()), str(expected.Balance.le(0).sum()), str(len(expected))])
    elif page == "summary_financial":
        tb = window(raw_source["ledger"]).groupby(["Act_ID", "Act_Name", "Act_Type", "Act_MG"], dropna=False)[["Debit", "Credit"]].sum().reset_index()
        tb["Net"] = tb.Debit - tb.Credit
        tb = tb[tb.Debit.abs().add(tb.Credit.abs()).gt(0)]
        same(frames[0], tb[["Act_Name", "Act_Type", "Debit", "Credit", "Net"]])
        income = -tb.loc[tb.Act_MG.eq("I"), "Net"].sum()
        expense = tb.loc[tb.Act_MG.eq("E"), "Net"].sum()
        customer = tb.loc[tb.Act_Type.eq("Customer"), "Net"].clip(lower=0).sum()
        supplier = (-tb.loc[tb.Act_Type.eq("Supplier"), "Net"]).clip(lower=0).sum()
        metrics(at, [money(income), money(expense), money(income - expense), money(customer), money(supplier)])
    elif page == "analytics_stock":
        m = window(raw_source["movements"])
        item = at.selectbox(key="as_i").value
        for n, direction in enumerate(["Inward", "Outward"]):
            all_months = sorted(m.loc[m.ITEM_NAME.eq(item), "month"].unique())
            qty = m.loc[m.direction.eq(direction) & m.ITEM_NAME.eq(item)].groupby("month").q.sum().reindex(all_months, fill_value=0)
            chart(at, 0, qty.reset_index(), trace=n)
        top = m[m.direction.eq("Outward")].groupby("ITEM_NAME").q.sum().nlargest(20).reset_index()
        chart(at, 1, top[["q", "ITEM_NAME"]])
    elif page == "analytics_sales":
        chart(at, 0, s.groupby(s.Doc_Date.dt.date).BL_NETVAL.sum().reset_index())
        top = s.groupby("ITEM_NAME").BL_NETVAL.sum().nlargest(20).reset_index()
        chart(at, 1, top[["BL_NETVAL", "ITEM_NAME"]])
        groups = s.groupby("GRP_NAME").BL_NETVAL.sum().reset_index()
        chart(at, 2, groups, x="labels", y="values")
        mg = s.groupby("ITEM_NAME").agg(Revenue=("BL_NETVAL", "sum"), Cost=("Item_Cost", "sum")).nlargest(20, "Revenue").reset_index()
        mg["Margin"] = mg.Revenue - mg.Cost
        mg["Margin%"] = (100 * mg.Margin / mg.Revenue.replace(0, np.nan)).round(1)
        same(frames[0], mg)
        assert any("preceding financial year" in w.value.lower() for w in at.info)
    elif page == "analytics_purchase":
        chart(at, 0, p.groupby(p.Doc_Date.dt.date).taxable.sum().reset_index())
        for n, key in enumerate(["ITEM_NAME", "party"], start=1):
            top = p.groupby(key).taxable.sum().nlargest(15).reset_index()
            chart(at, n, top[["taxable", key]])
    elif page == "validation":
        records = []
        for kind, docs, lines in [("Sales", sh, s), ("Purchase", ph, p)]:
            line_total = lines.groupby("Doc_Id").BL_NETVAL.sum()
            for row in docs.itertuples():
                total = line_total.get(row.Doc_Id, np.nan)
                records.append(dict(Type=kind, Doc_Id=row.Doc_Id, Bill_Amt=row.Bill_Amt, Line_Total=total, Difference=row.Bill_Amt - total))
        r = pd.DataFrame(records)
        summary = r.groupby("Type").agg(Invoices=("Doc_Id", "count"), Invoice_Total=("Bill_Amt", "sum"), Line_Total=("Line_Total", "sum"), Difference=("Difference", "sum"))
        same(frames[1].reset_index(), summary.reset_index())
        same(frames[2], r.loc[r.Difference.abs().gt(.01), ["Type", "Doc_Id", "Bill_Amt", "Line_Total", "Difference"]])
    else:
        pytest.fail(f"Missing independent oracle for {page}")


@pytest.mark.parametrize("name", list(database_sync.TABLE_COLUMNS))
def test_active_cache_matches_access_verified_snapshot(name, raw_source):
    columns = database_sync.TABLE_COLUMNS[name].split()
    # Read the actual published cache, not the CSV fallback.
    with sqlite3.connect(config.IMPORT_CACHE) as connection:
        actual = pd.read_sql_query(f'SELECT * FROM "{name}"', connection)
    expected = raw_source[name][columns].copy()
    for col in ["Doc_Date", "TRDATE", "Supp_Billdate"]:
        if col in expected:
            actual[col] = pd.to_datetime(actual[col]).astype(str)
            expected[col] = pd.to_datetime(expected[col]).astype(str)
    same(actual, expected)


@pytest.mark.parametrize("kind,method", [("sales", DS.sales), ("purchases", DS.purchases)])
def test_every_fact_row_customer_supplier_item_and_tax_mapping(kind, method, raw_source):
    expected = raw_source[kind][["Doc_Id", "IC_ID", "party", "gstin", "ITEM_NAME", "GRP_NAME", "HSNCode", "BILL_QTY", "BL_VALUE", "BL_NETVAL", "taxable", "tax", "other"]]
    actual = method().rename(columns={"customer_name": "party", "supplier_name": "party", "customer_gstno": "gstin", "supplier_gstno": "gstin", "taxable_value": "taxable", "total_gst": "tax", "other_tax": "other"})
    same(actual, expected)


@pytest.mark.parametrize("kind,rate", [("sales", "SRATE"), ("purchases", "IRATE")])
def test_source_quantity_rate_and_gst_arithmetic(kind, rate, raw_source):
    f = raw_source[kind]
    np.testing.assert_allclose(f.BL_VALUE, (f.BILL_QTY * f[rate]).round(2), atol=.000001, rtol=0)
    # Independently recompute GST at the recorded percentage. Access rounds
    # components separately; allow two paisa per line for that rounding.
    assert ((f.tax - (f.taxable * f.Vat_Rate / 100).round(2)).abs() <= .020001).all()
    np.testing.assert_allclose(f.CGSTAMT, f.SGSTAMT, atol=.000001, rtol=0)
    assert not (f.IGSTAMT.gt(0) & (f.CGSTAMT.gt(0) | f.SGSTAMT.gt(0))).any()


@pytest.mark.parametrize("page", ["sales_hsn", "purch_hsn", "summary_sales", "summary_purchase"])
def test_cess_and_additional_tax_are_not_lost_from_totals(page, importer, monkeypatch):
    monkeypatch.setattr(reporting, "today", lambda: dt.date(2026, 10, 22))
    def reader(_):
        tables = annual_tables(2026)
        for name in ["Stock_Delv", "Stock_Recd"]:
            tables[name]["cessAmt"] = "3.5"
            tables[name]["CCAMT"] = "1.5"
        return tables
    importer.reader = reader
    add(importer, 2026)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.session_state.page = page
    at.run()
    at.date_input[0].set_value(dt.date(2026, 4, 1)).run()
    assert not at.exception
    table = at.dataframe[-1].value
    assert table.Other_Tax.sum() == 5
    assert table.Total.sum() == (210 if page in ["sales_hsn", "summary_sales"] else 525)
    np.testing.assert_allclose(table.Taxable + table.CGST + table.SGST + table.IGST + table.Other_Tax, table.Total)


@pytest.mark.parametrize("value", [1.5, "broken", np.inf, 2**31])
def test_invalid_integer_keys_cannot_be_silently_truncated(value):
    frame = pd.DataFrame({"DOC_ID": [value]})
    with pytest.raises((ValueError, OverflowError)):
        data_store._to_int(frame, ["DOC_ID"])


def test_stricter_import_contract_accepts_the_verified_real_source(raw_source):
    tables = {name: raw_source[name] for name in database_sync.TABLE_COLUMNS}
    assert database_sync.validate_tables(tables) == ["2026-27"]


def test_voucher_classification_matches_all_source_definitions(raw_source):
    types = pd.read_csv(config.DATA_DIR / "TTYPES.csv").set_index("TT_ID")
    assert set(raw_source["Doc_Header"].Tt_Id) <= set(types.index)
    for label, expected in [("Sales", config.SALE_TT_IDS), ("Purchase", config.PURCHASE_TT_IDS), ("Sales Return", config.SALE_RETURN_TT_IDS), ("Purchase Return", config.PURCHASE_RETURN_TT_IDS), ("OpStock", config.OPENING_STOCK_TT_IDS)]:
        assert set(types.index[types.vouchtype.eq(label)]) == set(expected)


def test_blank_dimension_labels_do_not_drop_analytics_revenue(importer):
    def reader(_):
        tables = annual_tables(2026)
        tables["Groups"]["GRP_NAME"] = " "
        tables["Items"]["ITEM_NAME"] = None
        return tables
    importer.reader = reader
    add(importer, 2026)
    facts = DS.sales()
    assert facts.groupby("GRP_NAME").BL_NETVAL.sum().to_dict() == {"Unspecified group": 210}
    assert facts.groupby("ITEM_NAME").BL_NETVAL.sum().to_dict() == {"Unknown item": 210}


@pytest.mark.parametrize("table,column,value", [
    ("Stock_Delv", "DOC_ID", 2.5),
    ("Stock_Recd", "BL_NETVAL", np.inf),
    ("Item_Grp", "ITEM_ID", 999),
    ("Item_Grp", "GRP_ID", 999),
])
def test_bad_numeric_or_parent_mapping_retains_last_good_import(table, column, value, importer):
    path = add(importer, 2026)
    before = database_sync.revision()
    def broken(_):
        tables = annual_tables(2026)
        tables[table][column] = value
        return tables
    importer.reader = broken
    path.write_bytes(b"invalid updated source")
    importer.sync_once()
    assert database_sync.revision() == before
    assert importer.status[path.name.casefold()].startswith("Import failed")
    assert DS.sales().BL_NETVAL.sum() == 210


def test_bill_pagination_and_combined_filters_keep_complete_totals(raw_source, monkeypatch):
    monkeypatch.setattr(reporting, "today", lambda: dt.date(2026, 10, 22))
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.session_state.page = "sales_billwise"
    at.run()
    at.date_input[0].set_value(dt.date(2026, 4, 1)).run()
    ordered = raw_source["sales"].sort_values(["Doc_Date", "TNo"], ascending=False, kind="stable")
    for page in [2, 18]:
        at.number_input(key="sbw_page").set_value(page).run()
        shown = at.dataframe[0].value
        expected = ordered.iloc[(page - 1) * 1000:page * 1000]
        same(shown, expected[["bill_no", "ITEM_NAME", "BILL_QTY", "BL_VALUE"]].set_axis(["Bill_Num", "Item_Name", "Quantity", "Amount"], axis=1))
        assert at.metric[1].value == "17,044"
        assert at.metric[3].value == money(ordered.BL_NETVAL.sum(), 2)
    customer = ordered.iloc[0].party
    at.multiselect(key="sbw_c").select(customer).run()
    assert at.session_state.sbw_page == 1
    item = at.multiselect(key="sbw_i").options[0]
    at.multiselect(key="sbw_i").select(item).run()
    selected = ordered[ordered.party.eq(customer) & ordered.ITEM_NAME.eq(item)]
    assert at.metric[3].value == money(selected.BL_NETVAL.sum(), 2)
    assert set(at.dataframe[0].value.Customer_Name) == {customer}
    assert set(at.dataframe[0].value.Item_Name) == {item}


def test_purchase_supplier_and_bill_filters_match_raw_invoices(raw_source, monkeypatch):
    monkeypatch.setattr(reporting, "today", lambda: dt.date(2026, 10, 22))
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.session_state.page = "purch_billwise"
    at.run()
    at.date_input[0].set_value(dt.date(2026, 4, 1)).run()
    party = at.multiselect(key="pbw_s").options[0]
    at.multiselect(key="pbw_s").select(party).run()
    bill = at.multiselect(key="pbw_r").options[0]
    at.multiselect(key="pbw_r").select(bill).run()
    expected = raw_source["purchases"].loc[lambda d: d.party.eq(party) & d.bill_no.eq(bill)]
    metrics(at, [f"{expected.Doc_Id.nunique():,}", f"{len(expected):,}", money(expected.BL_NETVAL.sum(), 2)])
    assert set(at.dataframe[0].value.supplier_name) == {party}
    assert set(at.dataframe[0].value.bill_reference) == {bill}
