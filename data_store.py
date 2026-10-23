"""
Singleton data store. Loads CSVs once, builds fact/dim tables matching Power BI ETL.
Uses @st.cache_resource so data lives for the server lifetime.
"""
import numpy as np
import pandas as pd
import streamlit as st
import config
import database_sync


def _read(name, **kw):
    return database_sync.read_table(name, **kw)


def _to_int(df, cols):
    for c in cols:
        if c in df.columns:
            values = pd.to_numeric(df[c], errors="raise").fillna(0)
            if (values.abs() > 2 ** 31 - 1).any() or (values % 1 != 0).any():
                raise ValueError(f"Invalid Access Long identifier in {c}")
            df[c] = values.astype("int64")


def _to_float(df, cols):
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="raise").fillna(0).astype("float64")


_TABLES = {
    "dh": ("Doc_Header.csv", ["Doc_Id", "Tt_Id", "Act_ID", "Mode", "TNo", "Doc_Cancel"], ["Bill_Amt", "Bill_Qty"], "Doc_Date", {}),
    "sd": ("Stock_Delv.csv", ["IC_ID", "DOC_ID"], ["BILL_QTY", "BILL_FREE", "SRATE", "BL_VALUE", "BL_NETVAL", "Item_Cost", "CGSTAMT", "SGSTAMT", "IGSTAMT", "Vat_Rate", "Discount", "Dis_Value", "cessAmt", "mrp"], None, {}),
    "sr": ("Stock_Recd.csv", ["IC_ID", "DOC_ID"], ["BILL_QTY", "BILL_FREE", "IRATE", "BL_VALUE", "BL_NETVAL", "CGSTAMT", "SGSTAMT", "IGSTAMT", "Vat_Rate", "Srate", "stockconv"], None, {}),
    "acc": ("Accmst.csv", ["Act_Id"], [], None, {}),
    "adr": ("AccAdr.csv", ["Act_Id"], [], None, {"GSTNO": "string"}),
    "nt": ("NAME_TRAN.csv", ["Doc_Id"], [], None, {"GSTNO": "string"}),
    "items": ("Items.csv", ["ITEM_ID"], [], None, {}),
    "ig": ("Item_Grp.csv", ["IC_ID", "ITEM_ID", "GRP_ID"], ["PRATE", "SRATE", "MRP", "GST", "CGST", "SGST", "IssueConv"], None, {"HSNCode": "string"}),
    "grp": ("Groups.csv", ["GRP_ID"], [], None, {}),
    "tt": ("TTYPES.csv", ["TT_ID"], [], None, {}),
    "db": ("DayBook.csv", ["Act_ID", "Doc_ID"], ["AMOUNT"], "TRDATE", {}),
}
_UNIQUE_KEYS = {"dh": "Doc_Id", "acc": "Act_Id", "adr": "Act_Id", "nt": "Doc_Id", "ig": "IC_ID", "items": "ITEM_ID", "grp": "GRP_ID"}


@st.cache_resource(show_spinner=False, max_entries=33)
def _load_table(key, revision=0):
    filename, integers, amounts, date_col, dtypes = _TABLES[key]
    # Annual Access tables contain many unused fields. Read the report contract
    # only, so ten years of data do not inflate first-load I/O and memory.
    df = _read(filename, usecols=database_sync.TABLE_COLUMNS[filename[:-4]].split(),
               dtype=dtypes, parse_dates=[date_col] if date_col else None)
    _to_int(df, integers)
    _to_float(df, amounts)
    # Access Long IDs restart in each annual file. Namespace all join keys, not
    # the printed bill number. Keep the first source's original IDs for compatibility.
    offset = df["source_index"].astype("int64") * (2 ** 40)
    for col in ["Doc_Id", "DOC_ID", "Doc_ID", "Act_Id", "Act_ID", "Contra_ID", "IC_ID", "ITEM_ID", "GRP_ID"]:
        if col in df:
            local = pd.to_numeric(df[col], errors="raise").fillna(0)
            if (local.abs() > 2 ** 31 - 1).any() or (local % 1 != 0).any():
                raise ValueError(f"Invalid Access Long identifier in {filename}.{col}")
            if key == "dh" and col == "Doc_Id":
                df["source_doc_id"] = local.astype("int64")
            df[col] = local.astype("int64") + offset
    if date_col:
        date = df[date_col].dt
        df["dk"] = (date.year * 10000 + date.month * 100 + date.day).astype("int32")
    if key == "dh":
        # Format each distinct day once, not once per invoice/item line.
        dates = pd.DatetimeIndex(df["Doc_Date"].unique())
        df["date_str"] = df["Doc_Date"].map(dict(zip(dates, dates.strftime("%d-%m-%Y"))))
        df["month"] = df["Doc_Date"].map(dict(zip(dates, dates.strftime("%Y-%m"))))
        df["financial_year"] = database_sync.financial_year(df["Doc_Date"])
        df["document_key"] = df["source_database"] + "::" + df["source_doc_id"].astype(str)
    if key == "adr":
        df["GSTNO"] = df["GSTNO"].fillna("").str.strip()
    if key == "ig":
        df["HSNCode"] = df["HSNCode"].fillna("Unspecified").str.strip().replace("", "Unspecified")
    col = _UNIQUE_KEYS.get(key)
    if col and df[col].duplicated().any():
        raise ValueError(f"Duplicate {col} in {filename}; refresh or repair the source export.")
    return df


class _RawTables:
    """Load only tables requested by a page; Streamlit caches each table separately."""
    def __init__(self, revision):
        self.revision = revision

    def __getitem__(self, key):
        return _load_table(key, self.revision)


def _load_raw(revision=None):
    return _RawTables(database_sync.revision() if revision is None else revision)


def _resolve_customer(dh, nt, acc, adr):
    nt2 = nt[["Doc_Id", "Act_Name", "Act_Town", "GSTNO"]].copy()
    nt2.columns = ["Doc_Id", "nt_name", "nt_town", "nt_gstno"]
    ac2 = acc[["Act_Id", "Act_Name"]].rename(columns={"Act_Id": "Act_ID", "Act_Name": "ac_name"})
    h = dh[["Doc_Id", "Act_ID"]].merge(nt2, on="Doc_Id", how="left").merge(ac2, on="Act_ID", how="left")
    h = h.merge(adr[["Act_Id", "GSTNO"]], left_on="Act_ID", right_on="Act_Id", how="left", validate="many_to_one")
    h["customer_name"] = h["nt_name"].replace(r"^\s*$", np.nan, regex=True).fillna(h["ac_name"]).fillna("Unknown customer")
    h["customer_town"] = h["nt_town"].fillna("")
    h["customer_gstno"] = h["nt_gstno"].fillna("").str.strip().replace("", pd.NA).fillna(h["GSTNO"]).fillna("")
    return h[["Doc_Id", "customer_name", "customer_town", "customer_gstno"]]


def _line_amounts(df):
    _to_float(df, ["CGSTAMT", "SGSTAMT", "IGSTAMT", "cessAmt", "CCAMT", "BL_NETVAL"])
    df["total_gst"] = df[["CGSTAMT", "SGSTAMT", "IGSTAMT"]].sum(axis=1)
    df["other_tax"] = df.reindex(columns=["cessAmt", "CCAMT"], fill_value=0).fillna(0).sum(axis=1)
    # The source stores inclusive sales and exclusive purchase BL_VALUE differently.
    # BL_NETVAL consistently includes tax, so derive a common taxable basis from it.
    df["taxable_value"] = df["BL_NETVAL"] - df["total_gst"] - df["other_tax"]
    return df


@st.cache_resource(max_entries=3)
def _dim_item(revision=0):
    r = _load_raw(revision)
    df = r["ig"].merge(r["items"].drop(columns=["source_database", "source_index"]), on="ITEM_ID", how="left")
    df = df.merge(r["grp"][["GRP_ID", "GRP_NAME"]], on="GRP_ID", how="left")
    for column, fallback in [("ITEM_NAME", "Unknown item"), ("GRP_NAME", "Unspecified group")]:
        df[column] = df[column].replace(r"^\s*$", np.nan, regex=True).fillna(fallback)
    return df


@st.cache_resource(max_entries=3)
def _fact_sales(revision=0):
    r = _load_raw(revision)
    dh = r["dh"]
    docs = dh[(dh["Tt_Id"].isin(config.SALE_TT_IDS)) & (dh["Doc_Cancel"] == 0)]
    columns = ["DOC_ID", "IC_ID", "BILL_QTY", "BILL_FREE", "SRATE", "BL_VALUE", "BL_NETVAL", "Item_Cost", "CGSTAMT", "SGSTAMT", "IGSTAMT", "Vat_Rate", "cessAmt", "CCAMT"]
    df = r["sd"][columns].merge(docs[["Doc_Id", "Doc_Date", "dk", "Tt_Id", "TSeries", "TNo", "Act_ID", "Mode", "Bill_Amt", "date_str", "month", "source_database", "financial_year", "document_key"]],
                        left_on="DOC_ID", right_on="Doc_Id", how="inner")
    cust = _resolve_customer(docs, r["nt"], r["acc"], r["adr"])
    df = df.merge(cust, on="Doc_Id", how="left")
    dim = _dim_item(revision)[["IC_ID", "ITEM_NAME", "GRP_NAME", "HSNCode", "GST"]]
    df = df.merge(dim, on="IC_ID", how="left")
    df["bill_no"] = df["TSeries"].astype(str) + "-" + df["TNo"].astype(str)
    df["invoice_label"] = df["bill_no"]
    if dh["source_database"].nunique() > 1:
        df["invoice_label"] = df["bill_no"] + " | FY " + df["financial_year"] + " | " + df["source_database"]
    _line_amounts(df)
    df["margin"] = df["taxable_value"] - df["Item_Cost"]
    return df


@st.cache_resource(show_spinner=False, max_entries=3)
def _sales_bill_lines(revision=0):
    columns = ["Doc_Id", "dk", "TNo", "bill_no", "date_str", "customer_name", "ITEM_NAME", "BILL_QTY", "SRATE", "BL_VALUE", "BL_NETVAL", "source_database", "financial_year", "invoice_label"]
    return _fact_sales(revision)[columns].sort_values(["dk", "TNo"], ascending=False, kind="stable").reset_index(drop=True)


@st.cache_resource(max_entries=3)
def _fact_purchases(revision=0):
    r = _load_raw(revision)
    dh = r["dh"]
    tt = config.PURCHASE_TT_IDS
    docs = dh[(dh["Tt_Id"].isin(tt)) & (dh["Doc_Cancel"] == 0)]
    df = r["sr"].merge(docs[["Doc_Id", "Doc_Date", "dk", "Tt_Id", "TSeries", "TNo",
                              "Act_ID", "Mode", "Bill_Amt", "Supp_Billno", "Supp_Billdate", "source_database", "financial_year", "document_key"]],
                        left_on="DOC_ID", right_on="Doc_Id", how="inner", suffixes=("", "_doc"))
    ac = r["acc"][["Act_Id", "Act_Name"]]; ad = r["adr"][["Act_Id", "GSTNO"]].drop_duplicates(subset="Act_Id")
    df = df.merge(ac, left_on="Act_ID_doc", right_on="Act_Id", how="left")
    df.rename(columns={"Act_Name": "supplier_name"}, inplace=True)
    df["supplier_name"] = df["supplier_name"].fillna("Unknown supplier")
    df = df.merge(ad, left_on="Act_ID_doc", right_on="Act_Id", how="left", suffixes=("", "_a"))
    df.rename(columns={"GSTNO": "supplier_gstno"}, inplace=True)
    dim = _dim_item(revision)[["IC_ID", "ITEM_NAME", "GRP_NAME", "HSNCode", "GST"]]
    df = df.merge(dim, on="IC_ID", how="left")
    df["bill_no"] = df["TSeries"].astype(str) + "-" + df["TNo"].astype(str)
    df["invoice_label"] = df["bill_no"]
    if dh["source_database"].nunique() > 1:
        df["invoice_label"] = df["bill_no"] + " | FY " + df["financial_year"] + " | " + df["source_database"]
    _line_amounts(df)
    df["month"] = df["Doc_Date"].dt.to_period("M").astype(str)
    df["date_str"] = df["Doc_Date"].dt.strftime("%d-%m-%Y")
    return df


@st.cache_resource(max_entries=3)
def _fact_daybook(revision=0):
    r = _load_raw(revision)
    ac = r["acc"][["Act_Id", "Act_Name", "Act_Type", "Act_MG", "Act_Cat"]]
    cancelled = r["dh"].loc[r["dh"]["Doc_Cancel"] != 0, "Doc_Id"]
    return r["db"].loc[~r["db"]["Doc_ID"].isin(cancelled)].merge(ac, left_on="Act_ID", right_on="Act_Id", how="left", validate="many_to_one")


@st.cache_resource(max_entries=3)
def _stock_movements(revision=0):
    r = _load_raw(revision)
    valid = r["dh"][r["dh"]["Doc_Cancel"] == 0]
    ig = r["ig"][["IC_ID", "IssueConv"]].copy(); ig["IssueConv"] = ig["IssueConv"].clip(lower=1)

    ind = valid[valid["Tt_Id"].isin(config.STOCK_INWARD_TT_IDS)]
    inw = r["sr"].merge(ind[["Doc_Id", "dk", "Doc_Date", "Tt_Id", "source_database"]], left_on="DOC_ID", right_on="Doc_Id", suffixes=("_line", "")).merge(ig, on="IC_ID", how="left", validate="many_to_one")
    inw["q"] = (inw["BILL_QTY"] + inw["BILL_FREE"]) * inw["IssueConv"].where(inw["stockconv"] == 1, 1)
    inw["direction"] = "Inward"

    outd = valid[valid["Tt_Id"].isin(config.STOCK_OUTWARD_TT_IDS)]
    outw = r["sd"].merge(outd[["Doc_Id", "dk", "Doc_Date", "Tt_Id", "source_database"]], left_on="DOC_ID", right_on="Doc_Id", suffixes=("_line", "")).merge(ig, on="IC_ID", how="left", validate="many_to_one")
    outw["q"] = (outw["BILL_QTY"] + outw["BILL_FREE"]) * outw["IssueConv"].where(outw["stockconv"] == 1, 1)
    outw["direction"] = "Outward"
    cols = ["IC_ID", "Doc_Id", "Doc_Date", "dk", "Tt_Id", "q", "direction", "source_database"]
    df = pd.concat([inw[cols], outw[cols]], ignore_index=True)
    df["month"] = df["Doc_Date"].dt.to_period("M").astype(str)
    return df.merge(_dim_item(revision)[["IC_ID", "ITEM_NAME", "GRP_NAME"]], on="IC_ID", how="left", validate="many_to_one")


def _fact_closing_stock(as_of=None, from_date=None):
    revision = database_sync.revision()
    movements = _stock_movements(revision)
    cutoff = pd.Timestamp(as_of or DataStore.max_date())
    movements = movements[movements["Doc_Date"] <= cutoff]
    headers = _load_raw(revision)["dh"]
    starts = headers[headers["Tt_Id"] != 0].groupby("source_database")["Doc_Date"].min()
    starts = starts.map(lambda day: pd.Timestamp(year=day.year - (day.month < 4), month=4, day=1))
    eligible = starts[starts <= cutoff]
    if eligible.empty:
        eligible = headers[headers["Doc_Date"] <= cutoff].groupby("source_database")["Doc_Date"].min()
    source = eligible.idxmax() if not eligible.empty else None
    movements = movements[movements["source_database"] == source]
    opening = movements.iloc[0:0]
    if from_date is not None:
        opening = movements[movements["Doc_Date"] < pd.Timestamp(from_date)]
        movements = movements[movements["Doc_Date"] >= pd.Timestamp(from_date)]
    balance = opening.assign(signed=opening["q"].where(opening["direction"] == "Inward", -opening["q"])).groupby("IC_ID")["signed"].sum()
    qi = movements[movements["direction"] == "Inward"].groupby("IC_ID")["q"].sum().rename("total_inward")
    qo = movements[movements["direction"] == "Outward"].groupby("IC_ID")["q"].sum().rename("total_outward")

    dim = _dim_item(revision).loc[lambda d: d.source_database == source, ["IC_ID", "ITEM_NAME", "GRP_NAME", "Sale_PACK"]]
    stk = dim.merge(qi, on="IC_ID", how="left").merge(qo, on="IC_ID", how="left")
    stk["opening_qty"] = stk["IC_ID"].map(balance)
    qty = ["total_inward", "total_outward", "opening_qty"]
    stk[qty] = stk[qty].fillna(0)
    stk["closing_qty"] = stk["opening_qty"] + stk["total_inward"] - stk["total_outward"]
    return stk


class DataStore:
    @staticmethod
    def financial_years():
        headers = _load_raw()["dh"]
        return sorted(headers.loc[headers.Tt_Id != 0, "financial_year"].unique(), reverse=True)
    @staticmethod
    def date_bounds(financial_year):
        headers = _load_raw()["dh"]
        dates = headers.loc[(headers.Tt_Id != 0) & (headers.financial_year == financial_year), "Doc_Date"]
        return dates.min().date(), dates.max().date()
    @staticmethod
    def doc_header(): return _load_raw()["dh"].query("Doc_Cancel == 0").copy()
    @staticmethod
    def sales(): return _fact_sales(database_sync.revision())
    @staticmethod
    def sales_bill_lines(): return _sales_bill_lines(database_sync.revision())
    @staticmethod
    def purchases(): return _fact_purchases(database_sync.revision())
    @staticmethod
    def daybook(): return _fact_daybook(database_sync.revision())
    @staticmethod
    def closing_stock(as_of=None, from_date=None): return _fact_closing_stock(as_of, from_date)
    @staticmethod
    def stock_movements(): return _stock_movements(database_sync.revision())
    @staticmethod
    def min_date(): return _load_raw()["dh"]["Doc_Date"].min().date()
    @staticmethod
    def max_date(): return _load_raw()["dh"]["Doc_Date"].max().date()
