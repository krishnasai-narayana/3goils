import streamlit as st
import pandas as pd
from data_store import DataStore as AllData
from reporting import CurrentFY, today
import config
import database_sync
import datetime as dt

IMPORTER = database_sync.start()

# Pin one committed database snapshot for the whole page render.
with database_sync.read_snapshot():
    try:
        available_years = AllData.financial_years()
    except FileNotFoundError:
        available_years = []
    st.set_page_config(page_title="3G OILS Dashboard", page_icon="\U0001F4CA", layout="wide",
                       initial_sidebar_state="expanded" if len(available_years) > 1 else "collapsed")
    st.markdown("""<style>
    [data-testid="stHorizontalBlock"]{gap:0.3rem}
    [data-testid="stMetric"]{padding:0.2rem 0!important}
    hr{margin:0.3rem 0!important}
    .stAppDeployButton, [data-testid="stToolbar"],
    footer, #MainMenu, .viewerBadge_container__r5tak,
    [data-testid="manage-app-button"],
    a[href*="streamlit.io"]{display:none!important}
    footer:after{content:'© Govardhana Giri General Traders';display:block!important;
    text-align:center;padding:0.5rem 0;color:#888;font-size:0.85rem}
    </style>""", unsafe_allow_html=True)

    if "page" not in st.session_state:
        st.session_state.page = "home"

    def reset_report_filters():
        for key in list(st.session_state):
            if key.endswith(("_f", "_t")) and isinstance(st.session_state[key], dt.date):
                del st.session_state[key]
            elif key in ["sbw_c", "sbw_b", "sbw_i", "pbw_s", "pbw_r", "sp_c", "pp_s", "ss_g", "sf_a", "as_i"]:
                del st.session_state[key]

    def nav(p):
        reset_report_filters()
        if p.startswith("analytics_"):
            st.session_state.financial_year = "All years"
        st.session_state.page = p

    INR = "₹"


    @st.fragment(run_every="10s")
    def check_database_updates():
        current = database_sync.revision()
        previous = st.session_state.get("_data_revision", current)
        st.session_state["_data_revision"] = current
        business_day = today()
        previous_day = st.session_state.get("_business_day", business_day)
        st.session_state["_business_day"] = business_day
        if previous != current or previous_day != business_day:
            st.rerun(scope="app")
        if IMPORTER:
            for source, status in list(IMPORTER.status.items()):
                if status.startswith("Import failed"):
                    st.warning(f"{source}: {status}. The last successful data is retained.")
                elif status == "Importing":
                    st.info(f"Loading {source} in the background…")
                elif status.startswith("Ignored"):
                    st.caption(f"{source}: {status}")


    analytics = st.session_state.page.startswith("analytics_")
    full_fy_report = st.session_state.page.startswith(("sales_", "purch_")) and not st.session_state.page.endswith("_billwise")
    business_day = today()
    current = CurrentFY(business_day) if available_years else None
    DS = AllData if analytics else current
    with st.sidebar:
        check_database_updates()
        years = available_years
        if not years:
            st.info("Add a valid .mdb database to the database folder. The dashboard will refresh when its first import completes.")
            st.stop()
        if analytics:
            choices = ["All years"] + years
            if st.session_state.get("financial_year", "All years") not in choices:
                del st.session_state["financial_year"]
            selected_year = st.selectbox("Financial year", choices, key="financial_year")
            st.caption("Previous financial years are available only in Analytics.")
        else:
            selected_year = current.label
            st.caption(f"Current financial year: {current.label}. Earlier years are available in Analytics.")
            if not current.sources:
                st.info(f"No business data loaded for FY {current.label}. Current-year reports are empty; use Analytics for earlier years.")
            else:
                st.caption(f"Latest loaded current-FY transaction: {current.latest:%d %b %Y}.")
    MIN_D, MAX_D = (AllData.min_date(), AllData.max_date()) if analytics else (current.start, current.latest)
    selected_scope = (analytics, selected_year)
    if st.session_state.get("_selected_year", selected_scope) != selected_scope:
        reset_report_filters()
    st.session_state["_selected_year"] = selected_scope
    if analytics and selected_year != "All years":
        MIN_D, MAX_D = AllData.date_bounds(selected_year)
    old_bounds = st.session_state.get("_date_bounds", (MIN_D, MAX_D))
    for key in list(st.session_state):
        value = st.session_state[key]
        if key.endswith(("_f", "_t")) and isinstance(value, dt.date):
            if not MIN_D <= value <= MAX_D:
                del st.session_state[key]
            elif old_bounds != (MIN_D, MAX_D):
                if key.endswith("_f") and value == old_bounds[0]:
                    st.session_state[key] = MIN_D
                elif value == old_bounds[1]:
                    st.session_state[key] = MAX_D
    st.session_state["_date_bounds"] = (MIN_D, MAX_D)

    CC_INT = st.column_config.NumberColumn(format="%d")
    CC_AMT = st.column_config.NumberColumn(format="₹%.2f")
    CC_AMT0 = st.column_config.NumberColumn(format="₹%d")
    CC_QTY = st.column_config.NumberColumn(format="%.2f")
    CC_RATE = st.column_config.NumberColumn(format="%.2f")


    def _dk(d):
        return d.year * 10000 + d.month * 100 + d.day


    def fbd(df, sd, ed):
        return df[(df["dk"] >= _dk(sd)) & (df["dk"] <= _dk(ed))]


    def validate_dates(sd, ed):
        if sd > ed:
            st.error("From date must be on or before To date.")
            st.stop()


    def hdr(title):
        st.markdown(f"**{title}**")


    def dfr(prefix, extra=0):
        cols = st.columns([0.3, 1, 1] + [1.5] * max(extra, 1))
        cols[0].button("\U0001F3E0", key=f"h_{prefix}", on_click=nav, args=("home",))
        sd = cols[1].date_input("From", value=MIN_D if analytics or full_fy_report else MAX_D, min_value=MIN_D, max_value=MAX_D, key=f"{prefix}_f")
        ed = cols[2].date_input("To", value=MAX_D, min_value=MIN_D, max_value=MAX_D, key=f"{prefix}_t")
        validate_dates(sd, ed)
        return sd, ed, cols[3:]


    # ═══════════════════════ HOME ═══════════════════════════════════════════════
    def page_home():
        st.markdown("<h1 style='text-align:center;padding-top:4.5rem;margin-top:0;margin-bottom:0.5rem;'>3G OILS Dashboard</h1>", unsafe_allow_html=True)
        c1, c2, c3, c4, c5, c6 = st.columns([1.2, 1.2, 1, 1, 0.8, 0.8])
        sd = c5.date_input("From", value=MAX_D, min_value=MIN_D, max_value=MAX_D, key="h_f")
        ed = c6.date_input("To", value=MAX_D, min_value=MIN_D, max_value=MAX_D, key="h_t")
        validate_dates(sd, ed)
        dh = fbd(DS.doc_header(), sd, ed)
        sl = dh[dh["Tt_Id"].isin(config.SALE_TT_IDS)]; pu = dh[dh["Tt_Id"].isin(config.PURCHASE_TT_IDS)]
        c1.metric("Total Sales", f"{INR}{sl['Bill_Amt'].sum():,.0f}")
        c2.metric("Total Purchases", f"{INR}{pu['Bill_Amt'].sum():,.0f}")
        c3.metric("Sales Invoices", f"{len(sl):,}"); c4.metric("Purchase Bills", f"{len(pu):,}")
        for sec, icon, items in [
            ("Sales", "\U0001F6D2", [("Bill Wise","sales_billwise"),("Date Wise","sales_datewise"),("Monthly","sales_monthly"),("HSN","sales_hsn"),("Party Wise","sales_partywise"),("GST No Wise","sales_gstno")]),
            ("Purchase", "\U0001F4E6", [("Bill Wise","purch_billwise"),("Date Wise","purch_datewise"),("Monthly","purch_monthly"),("HSN","purch_hsn"),("Party Wise","purch_partywise"),("GST No Wise","purch_gstno")]),
            ("Summary", "\U0001F4CB", [("Closing Stock","summary_stock"),("Sales","summary_sales"),("Purchase","summary_purchase"),("GST","summary_gst"),("Financial","summary_financial")]),
            ("Analytics", "\U0001F4C8", [("Stock","analytics_stock"),("Sales","analytics_sales"),("Purchase","analytics_purchase"),("GST","analytics_gst")]),
        ]:
            st.markdown(f"##### {icon} {sec}"); cols = st.columns(len(items))
            for i, (l, k) in enumerate(items):
                cols[i].button(l, key=f"b_{k}", width="stretch", on_click=nav, args=(k,))
        st.button("Data Validation", key="b_validation", on_click=nav, args=("validation",))
        if st.button("Refresh databases", key="reload_data"):
            if IMPORTER:
                IMPORTER.request_scan()
            st.cache_resource.clear(); st.rerun()


    # ═══════════════════════ SALES ══════════════════════════════════════════════
    def page_sales_billwise():
        hdr("\U0001F6D2 Sales — Bill Wise"); sd, ed, fx = dfr("sbw", extra=3)
        df = fbd(DS.sales_bill_lines(), sd, ed)
        sel = fx[0].multiselect("Customer", sorted(df["customer_name"].dropna().unique()), key="sbw_c")
        if sel: df = df[df["customer_name"].isin(sel)]
        sel = fx[1].multiselect("Bill No", sorted(df["invoice_label"].dropna().unique(), reverse=True), key="sbw_b")
        if sel: df = df[df["invoice_label"].isin(sel)]
        sel = fx[2].multiselect("Item", sorted(df["ITEM_NAME"].dropna().unique()), key="sbw_i")
        if sel: df = df[df["ITEM_NAME"].isin(sel)]
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Bills", f"{df['Doc_Id'].nunique():,}"); k2.metric("Lines", f"{len(df):,}")
        k3.metric("Qty", f"{df['BILL_QTY'].sum():,.0f}"); k4.metric("Amount", f"{INR}{df['BL_NETVAL'].sum():,.2f}")
        page_size = 1000
        scope = (sd, ed, database_sync.revision(), tuple(st.session_state.sbw_c), tuple(st.session_state.sbw_b), tuple(st.session_state.sbw_i))
        if st.session_state.get("_sbw_page_scope") != scope:
            st.session_state.sbw_page = 1
            st.session_state._sbw_page_scope = scope
        pages = max(1, (len(df) + page_size - 1) // page_size)
        st.session_state.sbw_page = min(st.session_state.get("sbw_page", 1), pages)
        page = 1
        if pages > 1:
            pager, description = st.columns([1, 6])
            page = pager.number_input("Page", min_value=1, max_value=pages, step=1, key="sbw_page")
            description.caption(f"{len(df):,} filtered lines · {pages:,} pages · Totals cover all filtered lines.")
        visible = df.iloc[(page - 1) * page_size:page * page_size]
        v = visible[["bill_no", "date_str", "customer_name", "ITEM_NAME", "BILL_QTY", "SRATE", "BL_VALUE", "TNo"]].copy()
        v = v.drop(columns="TNo")
        v.columns = ["Bill_Num", "Date", "Customer_Name", "Item_Name", "Quantity", "Sale_Rate", "Amount"]
        if len(years) > 1:
            v.insert(1, "Financial_Year", visible["financial_year"])
            v["Database"] = visible["source_database"]
        st.dataframe(v, width="stretch", hide_index=True, height=600,
                     column_config={"Quantity": CC_QTY,
                                    "Sale_Rate": st.column_config.NumberColumn("Sale Rate (incl. GST)", format="%.2f"),
                                    "Amount": st.column_config.NumberColumn("Amount (incl. GST)", format="₹%.2f")})


    def page_sales_datewise():
        import plotly.express as px
        hdr("\U0001F6D2 Sales — Date Wise"); sd, ed, _ = dfr("sdw")
        dh = fbd(DS.doc_header(), sd, ed); s = dh[dh["Tt_Id"].isin(config.SALE_TT_IDS)]
        d = s.groupby(s["Doc_Date"].dt.date).agg(Bills=("Doc_Id", "count"), Amount=("Bill_Amt", "sum")).reset_index()
        d.columns = ["Date", "Bills", "Amount"]; d = d.sort_values("Date", ascending=False)
        fig = px.bar(d, x="Date", y="Amount", text_auto=".2s"); fig.update_layout(height=280, margin=dict(t=10, b=10))
        st.plotly_chart(fig, width="stretch")
        st.dataframe(d, width="stretch", hide_index=True, height=500, column_config={"Amount": CC_AMT0})


    def page_sales_monthly():
        import plotly.express as px
        hdr("\U0001F6D2 Sales — Monthly"); sd, ed, _ = dfr("sm")
        dh = fbd(DS.doc_header(), sd, ed); s = dh[dh["Tt_Id"].isin(config.SALE_TT_IDS)].copy()
        s["Month"] = s["Doc_Date"].dt.to_period("M").astype(str)
        m = s.groupby("Month").agg(Bills=("Doc_Id", "count"), Amount=("Bill_Amt", "sum"), Avg=("Bill_Amt", "mean")).reset_index()
        fig = px.bar(m, x="Month", y="Amount", text_auto=".2s"); fig.update_layout(height=280, margin=dict(t=10, b=10))
        st.plotly_chart(fig, width="stretch")
        st.dataframe(m, width="stretch", hide_index=True, column_config={"Amount": CC_AMT0, "Avg": CC_AMT0})


    def page_sales_hsn():
        hdr("\U0001F6D2 Sales — HSN Code Wise"); sd, ed, _ = dfr("sh")
        df = fbd(DS.sales(), sd, ed)
        h = df.groupby("HSNCode").agg(Items=("IC_ID", "nunique"), Qty=("BILL_QTY", "sum"), Taxable=("taxable_value", "sum"), CGST=("CGSTAMT", "sum"), SGST=("SGSTAMT", "sum"), IGST=("IGSTAMT", "sum"), Other_Tax=("other_tax", "sum"), Total=("BL_NETVAL", "sum")).reset_index()
        h["Tax"] = h["CGST"] + h["SGST"] + h["IGST"]; h = h.sort_values("Taxable", ascending=False)
        cc = {c: CC_AMT0 for c in ["Taxable", "CGST", "SGST", "IGST", "Other_Tax", "Tax", "Total"]}
        st.dataframe(h, width="stretch", hide_index=True, height=500, column_config=cc | {"Qty": CC_QTY})


    def page_sales_partywise():
        import plotly.express as px
        hdr("\U0001F6D2 Sales — Party Wise"); sd, ed, fx = dfr("sp", extra=1)
        df = fbd(DS.sales(), sd, ed)
        sel = fx[0].multiselect("Customer", sorted(df["customer_name"].dropna().unique()), key="sp_c")
        if sel: df = df[df["customer_name"].isin(sel)]
        p = df.groupby("customer_name").agg(Bills=("Doc_Id", "nunique"), Qty=("BILL_QTY", "sum"), Amount=("BL_NETVAL", "sum"), Tax=("total_gst", "sum")).reset_index().sort_values("Amount", ascending=False)
        fig = px.bar(p.head(20), y="customer_name", x="Amount", orientation="h", text_auto=".2s")
        fig.update_layout(height=400, margin=dict(t=10, b=10), yaxis=dict(autorange="reversed")); st.plotly_chart(fig, width="stretch")
        st.dataframe(p.rename(columns={"customer_name": "Customer"}), width="stretch", hide_index=True, height=400, column_config={"Amount": CC_AMT0, "Tax": CC_AMT0, "Qty": CC_QTY})


    def page_sales_gstno():
        hdr("\U0001F6D2 Sales — GST No Wise"); sd, ed, _ = dfr("sg")
        df = fbd(DS.sales(), sd, ed)
        g = df[df["customer_gstno"].notna() & (df["customer_gstno"] != "") & (df["customer_gstno"] != "nan")]
        if g.empty: st.info("No GST-registered sales found."); return
        r = g.groupby(["customer_gstno", "customer_name"]).agg(Bills=("Doc_Id", "nunique"), Taxable=("taxable_value", "sum"), CGST=("CGSTAMT", "sum"), SGST=("SGSTAMT", "sum"), IGST=("IGSTAMT", "sum")).reset_index().sort_values("Taxable", ascending=False)
        r["Tax"] = r["CGST"] + r["SGST"] + r["IGST"]
        st.dataframe(r.rename(columns={"customer_gstno": "GSTIN", "customer_name": "Party"}), width="stretch", hide_index=True, height=500,
                     column_config={c: CC_AMT0 for c in ["Taxable", "CGST", "SGST", "IGST", "Tax"]})


    # ═══════════════════════ PURCHASE ═══════════════════════════════════════════
    def page_purch_billwise():
        hdr("\U0001F4E6 Purchase — Bill Wise"); sd, ed, fx = dfr("pbw", extra=2)
        df = fbd(DS.purchases(), sd, ed)
        sel = fx[0].multiselect("Supplier", sorted(df["supplier_name"].dropna().unique()), key="pbw_s")
        if sel: df = df[df["supplier_name"].isin(sel)]
        sel = fx[1].multiselect("Bill Ref", sorted(df["invoice_label"].dropna().unique()), key="pbw_r")
        if sel: df = df[df["invoice_label"].isin(sel)]
        k1, k2, k3 = st.columns(3)
        k1.metric("Bills", f"{df['Doc_Id'].nunique():,}"); k2.metric("Lines", f"{len(df):,}"); k3.metric("Amount", f"{INR}{df['BL_NETVAL'].sum():,.2f}")
        b = df.groupby(["Doc_Id", "TNo", "bill_no", "date_str", "Supp_Billno", "supplier_name", "financial_year", "source_database"], dropna=False).agg(bill_total=("BL_NETVAL", "sum")).reset_index().sort_values(["financial_year", "TNo"])
        v = b[["bill_no", "date_str", "Supp_Billno", "supplier_name", "bill_total"]]
        v.columns = ["bill_reference", "date", "supplier_bill_no", "supplier_name", "bill_total"]
        if len(years) > 1:
            v = v.assign(Financial_Year=b["financial_year"], Database=b["source_database"])
        st.dataframe(v, width="stretch", hide_index=True, height=600, column_config={"bill_total": CC_AMT})


    def page_purch_datewise():
        import plotly.express as px
        hdr("\U0001F4E6 Purchase — Date Wise"); sd, ed, _ = dfr("pdw")
        dh = fbd(DS.doc_header(), sd, ed); p = dh[dh["Tt_Id"].isin(config.PURCHASE_TT_IDS)]
        d = p.groupby(p["Doc_Date"].dt.date).agg(Bills=("Doc_Id", "count"), Amount=("Bill_Amt", "sum")).reset_index(); d.columns = ["Date", "Bills", "Amount"]; d = d.sort_values("Date", ascending=False)
        fig = px.bar(d, x="Date", y="Amount", text_auto=".2s"); fig.update_layout(height=280, margin=dict(t=10, b=10)); st.plotly_chart(fig, width="stretch")
        st.dataframe(d, width="stretch", hide_index=True, height=500, column_config={"Amount": CC_AMT0})


    def page_purch_monthly():
        import plotly.express as px
        hdr("\U0001F4E6 Purchase — Monthly"); sd, ed, _ = dfr("pm")
        dh = fbd(DS.doc_header(), sd, ed); p = dh[dh["Tt_Id"].isin(config.PURCHASE_TT_IDS)].copy(); p["Month"] = p["Doc_Date"].dt.to_period("M").astype(str)
        m = p.groupby("Month").agg(Bills=("Doc_Id", "count"), Amount=("Bill_Amt", "sum")).reset_index()
        fig = px.bar(m, x="Month", y="Amount", text_auto=".2s"); fig.update_layout(height=280, margin=dict(t=10, b=10)); st.plotly_chart(fig, width="stretch")
        st.dataframe(m, width="stretch", hide_index=True, column_config={"Amount": CC_AMT0})


    def page_purch_hsn():
        hdr("\U0001F4E6 Purchase — HSN Code Wise"); sd, ed, _ = dfr("ph")
        df = fbd(DS.purchases(), sd, ed)
        h = df.groupby("HSNCode").agg(Items=("IC_ID", "nunique"), Qty=("BILL_QTY", "sum"), Taxable=("taxable_value", "sum"), CGST=("CGSTAMT", "sum"), SGST=("SGSTAMT", "sum"), IGST=("IGSTAMT", "sum"), Other_Tax=("other_tax", "sum"), Total=("BL_NETVAL", "sum")).reset_index()
        h["Tax"] = h["CGST"] + h["SGST"] + h["IGST"]; h = h.sort_values("Taxable", ascending=False)
        st.dataframe(h, width="stretch", hide_index=True, height=500, column_config={c: CC_AMT0 for c in ["Taxable", "CGST", "SGST", "IGST", "Other_Tax", "Tax", "Total"]} | {"Qty": CC_QTY})


    def page_purch_partywise():
        import plotly.express as px
        hdr("\U0001F4E6 Purchase — Party Wise"); sd, ed, fx = dfr("pp", extra=1)
        df = fbd(DS.purchases(), sd, ed)
        sel = fx[0].multiselect("Supplier", sorted(df["supplier_name"].dropna().unique()), key="pp_s")
        if sel: df = df[df["supplier_name"].isin(sel)]
        p = df.groupby("supplier_name").agg(Bills=("Doc_Id", "nunique"), Qty=("BILL_QTY", "sum"), Taxable=("taxable_value", "sum"), Tax=("total_gst", "sum")).reset_index().sort_values("Taxable", ascending=False)
        fig = px.bar(p.head(15), y="supplier_name", x="Taxable", orientation="h", text_auto=".2s")
        fig.update_layout(height=350, margin=dict(t=10, b=10), yaxis=dict(autorange="reversed")); st.plotly_chart(fig, width="stretch")
        st.dataframe(p.rename(columns={"supplier_name": "Supplier"}), width="stretch", hide_index=True, height=400, column_config={"Taxable": CC_AMT0, "Tax": CC_AMT0, "Qty": CC_QTY})


    def page_purch_gstno():
        hdr("\U0001F4E6 Purchase — GST No Wise"); sd, ed, _ = dfr("pg")
        df = fbd(DS.purchases(), sd, ed)
        g = df[df["supplier_gstno"].notna() & (df["supplier_gstno"] != "") & (df["supplier_gstno"] != "nan")]
        if g.empty: st.info("No GST-registered purchases found."); return
        r = g.groupby(["supplier_gstno", "supplier_name"]).agg(Bi
