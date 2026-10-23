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
    footer, #MainMenu{display:none!important}
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
        r = g.groupby(["supplier_gstno", "supplier_name"]).agg(Bills=("Doc_Id", "nunique"), Taxable=("taxable_value", "sum"), CGST=("CGSTAMT", "sum"), SGST=("SGSTAMT", "sum"), IGST=("IGSTAMT", "sum")).reset_index().sort_values("Taxable", ascending=False)
        r["Tax"] = r["CGST"] + r["SGST"] + r["IGST"]
        st.dataframe(r.rename(columns={"supplier_gstno": "GSTIN", "supplier_name": "Supplier"}), width="stretch", hide_index=True, height=500,
                     column_config={c: CC_AMT0 for c in ["Taxable", "CGST", "SGST", "IGST", "Tax"]})


    # ═══════════════════════ SUMMARY ════════════════════════════════════════════
    def page_summary_stock():
        hdr("\U0001F4CB Closing Stock"); sd, ed, fx = dfr("ss", extra=1)
        st.caption("Opening balance is before From; movements cover the selected dates. Balance uses the latest annual stock snapshot available as of To, in each item’s sale unit.")
        stk = DS.closing_stock(ed, sd)
        grp = fx[0].multiselect("Group", sorted(stk["GRP_NAME"].dropna().unique()), key="ss_g")
        d = stk if not grp else stk[stk["GRP_NAME"].isin(grp)]
        c1, c2, c3 = st.columns(3)
        c1.metric("In Stock", f"{(d['closing_qty'] > 0).sum()}"); c2.metric("Out/Zero", f"{(d['closing_qty'] <= 0).sum()}"); c3.metric("Total", f"{len(d)}")
        st.dataframe(d[["ITEM_NAME", "GRP_NAME", "Sale_PACK", "opening_qty", "total_inward", "total_outward", "closing_qty"]].rename(
            columns={"ITEM_NAME": "Item", "GRP_NAME": "Group", "Sale_PACK": "Unit", "opening_qty": "Opening", "total_inward": "In", "total_outward": "Out", "closing_qty": "Balance"}),
            width="stretch", hide_index=True, height=600, column_config={"Opening": CC_QTY, "In": CC_QTY, "Out": CC_QTY, "Balance": CC_QTY})


    def page_summary_sales():
        hdr("\U0001F4CB Sales Summary"); sd, ed, _ = dfr("ssu")
        df = fbd(DS.sales(), sd, ed)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Invoices", f"{df['Doc_Id'].nunique():,}"); c2.metric("Qty", f"{df['BILL_QTY'].sum():,.0f}")
        c3.metric("Sales (incl. GST)", f"{INR}{df['BL_NETVAL'].sum():,.0f}"); c4.metric("Tax", f"{INR}{df['total_gst'].sum():,.0f}")
        col1, col2 = st.columns(2)
        with col1:
            st.dataframe(pd.DataFrame({"Component": ["CGST", "SGST", "IGST"], "Amount": [df["CGSTAMT"].sum(), df["SGSTAMT"].sum(), df["IGSTAMT"].sum()]}), hide_index=True, column_config={"Amount": CC_AMT0})
        with col2:
            mm = {0: "Cash", 1: "Credit"}; ms = df.groupby("Mode").agg(Bills=("Doc_Id", "nunique"), Amount=("BL_NETVAL", "sum")).reset_index(); ms["Pay"] = ms["Mode"].map(mm).fillna(ms["Mode"].map(lambda mode: f"Other (mode {mode})"))
            st.dataframe(ms[["Pay", "Bills", "Amount"]], hide_index=True, width="stretch", column_config={"Amount": CC_AMT0})
            st.caption("Additional payment modes retain their source code until their meaning is confirmed in the billing system.")
        m = df.groupby("month").agg(Bills=("Doc_Id", "nunique"), Qty=("BILL_QTY", "sum"), Taxable=("taxable_value", "sum"), CGST=("CGSTAMT", "sum"), SGST=("SGSTAMT", "sum"), IGST=("IGSTAMT", "sum"), Other_Tax=("other_tax", "sum"), Total=("BL_NETVAL", "sum")).reset_index()
        st.dataframe(m, width="stretch", hide_index=True, column_config={c: CC_AMT0 for c in ["Taxable", "CGST", "SGST", "IGST", "Other_Tax", "Total"]} | {"Qty": CC_QTY})


    def page_summary_purchase():
        hdr("\U0001F4CB Purchase Summary"); sd, ed, _ = dfr("spu")
        df = fbd(DS.purchases(), sd, ed)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Bills", f"{df['Doc_Id'].nunique():,}"); c2.metric("Qty", f"{df['BILL_QTY'].sum():,.0f}")
        c3.metric("Taxable", f"{INR}{df['taxable_value'].sum():,.0f}"); c4.metric("Tax", f"{INR}{df['total_gst'].sum():,.0f}")
        m = df.groupby("month").agg(Bills=("Doc_Id", "nunique"), Qty=("BILL_QTY", "sum"), Taxable=("taxable_value", "sum"), CGST=("CGSTAMT", "sum"), SGST=("SGSTAMT", "sum"), IGST=("IGSTAMT", "sum"), Other_Tax=("other_tax", "sum"), Total=("BL_NETVAL", "sum")).reset_index()
        st.dataframe(m, width="stretch", hide_index=True, column_config={c: CC_AMT0 for c in ["Taxable", "CGST", "SGST", "IGST", "Other_Tax", "Total"]} | {"Qty": CC_QTY})


    def page_summary_gst():
        hdr("\U0001F4CB GST Summary"); sd, ed, _ = dfr("sgst")
        s = fbd(DS.sales(), sd, ed); p = fbd(DS.purchases(), sd, ed)
        oc, os_, oi = s["CGSTAMT"].sum(), s["SGSTAMT"].sum(), s["IGSTAMT"].sum()
        ic, is_, ii = p["CGSTAMT"].sum(), p["SGSTAMT"].sum(), p["IGSTAMT"].sum()
        for lbl, cg, sg, ig in [("Output Tax (Sales)", oc, os_, oi), ("Input Tax (Purchases)", ic, is_, ii)]:
            st.markdown(f"**{lbl}**"); c1, c2, c3, c4 = st.columns(4)
            c1.metric("CGST", f"{INR}{cg:,.0f}"); c2.metric("SGST", f"{INR}{sg:,.0f}"); c3.metric("IGST", f"{INR}{ig:,.0f}"); c4.metric("Total", f"{INR}{cg+sg+ig:,.0f}")
        st.caption("Goods invoices only. Services, credit/debit notes and tax-credit adjustments are excluded. This difference is not a GST return calculation.")
        nc, ns, ni = oc - ic, os_ - is_, oi - ii
        st.markdown("**Recorded GST Difference**"); c1, c2, c3, c4 = st.columns(4)
        c1.metric("CGST", f"{INR}{nc:,.0f}"); c2.metric("SGST", f"{INR}{ns:,.0f}"); c3.metric("IGST", f"{INR}{ni:,.0f}"); c4.metric("Difference", f"{INR}{nc+ns+ni:,.0f}")
        sm = s.groupby("month").agg(Out_CGST=("CGSTAMT", "sum"), Out_SGST=("SGSTAMT", "sum"), Out_IGST=("IGSTAMT", "sum")).reset_index()
        pm = p.groupby("month").agg(In_CGST=("CGSTAMT", "sum"), In_SGST=("SGSTAMT", "sum"), In_IGST=("IGSTAMT", "sum")).reset_index()
        gm = sm.merge(pm, on="month", how="outer").fillna(0); gm["Net"] = gm["Out_CGST"] - gm["In_CGST"] + gm["Out_SGST"] - gm["In_SGST"] + gm["Out_IGST"] - gm["In_IGST"]
        st.dataframe(gm, width="stretch", hide_index=True, column_config={c: CC_AMT0 for c in gm.columns if c != "month"})


    def page_summary_financial():
        hdr("\U0001F4CB Financial Summary"); sd, ed, fx = dfr("sf", extra=1)
        db = DS.daybook(); db_f = db[(db["dk"] >= _dk(sd)) & (db["dk"] <= _dk(ed))]
        db_f = db_f.assign(Debit=db_f["AMOUNT"].where(db_f["TYPE"].isin(["D", "P"]), 0),
                           Credit=db_f["AMOUNT"].where(db_f["TYPE"].isin(["C", "R"]), 0))
        tb = db_f.groupby(["Act_ID", "Act_Name", "Act_Type", "Act_MG"], dropna=False)[["Debit", "Credit"]].sum().reset_index()
        st.caption("Recorded ledger movements for the selected dates. Cash contra entries and account opening balances are not reconstructed; these figures are not a complete trial balance or profit-and-loss statement.")
        tb["Net"] = tb["Debit"] - tb["Credit"]; tb = tb[(tb["Debit"].abs() + tb["Credit"].abs()) > 0].sort_values("Net", ascending=False)
        af = fx[0].multiselect("Acct Type", sorted(tb["Act_Type"].dropna().unique()), key="sf_a")
        td = tb if not af else tb[tb["Act_Type"].isin(af)]
        st.dataframe(td[["Act_Name", "Act_Type", "Debit", "Credit", "Net"]], width="stretch", hide_index=True, height=350,
                     column_config={"Debit": CC_AMT0, "Credit": CC_AMT0, "Net": CC_AMT0})
        c1, c2 = st.columns(2)
        with c1:
            tb = td
            ti = tb[tb["Act_MG"] == "I"]["Credit"].sum() - tb[tb["Act_MG"] == "I"]["Debit"].sum()
            te = tb[tb["Act_MG"] == "E"]["Debit"].sum() - tb[tb["Act_MG"] == "E"]["Credit"].sum()
            st.metric("Trading Income", f"{INR}{ti:,.0f}"); st.metric("Expenses", f"{INR}{te:,.0f}"); st.metric("Recorded Income less Expenses", f"{INR}{ti-te:,.0f}")
        with c2:
            cu = tb[tb["Act_Type"] == "Customer"].copy(); cu["O"] = cu["Debit"] - cu["Credit"]
            su = tb[tb["Act_Type"] == "Supplier"].copy(); su["O"] = su["Credit"] - su["Debit"]
            st.metric("Customer Net Debits (period)", f"{INR}{cu[cu['O']>0]['O'].sum():,.0f}"); st.metric("Supplier Net Credits (period)", f"{INR}{su[su['O']>0]['O'].sum():,.0f}")


    # ═══════════════════════ ANALYTICS ══════════════════════════════════════════
    def page_analytics_stock():
        import plotly.express as px
        import plotly.graph_objects as go
        hdr("\U0001F4C8 Stock Analytics"); sd, ed, fx = dfr("as", extra=1)
        movements = fbd(DS.stock_movements(), sd, ed)
        st.caption("Movements in each item’s sale unit; inward includes opening stock when its date is selected.")
        if movements.empty:
            st.info("No stock movements in the selected date range."); return
        s = movements[movements["direction"] == "Outward"]
        p = movements[movements["direction"] == "Inward"]
        sm = s.groupby(["month", "ITEM_NAME"]).agg(Sold=("q", "sum")).reset_index()
        pm = p.groupby(["month", "ITEM_NAME"]).agg(Purchased=("q", "sum")).reset_index()
        mv = pm.merge(sm, on=["month", "ITEM_NAME"], how="outer").fillna(0)
        item = fx[0].selectbox("Item", sorted(mv["ITEM_NAME"].dropna().unique()), key="as_i")
        im = mv[mv["ITEM_NAME"] == item].sort_values("month")
        if not im.empty:
            fig = go.Figure(); fig.add_trace(go.Bar(name="In", x=im["month"], y=im["Purchased"])); fig.add_trace(go.Bar(name="Out", x=im["month"], y=im["Sold"]))
            fig.update_layout(barmode="group", height=280, margin=dict(t=10, b=10)); st.plotly_chart(fig, width="stretch")
        ts = s.groupby("ITEM_NAME")["q"].sum().nlargest(20).reset_index()
        fig2 = px.bar(ts, y="ITEM_NAME", x="q", orientation="h", text_auto=".2s"); fig2.update_layout(height=420, margin=dict(t=10, b=10), yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig2, width="stretch")


    def page_analytics_sales():
        import plotly.express as px
        hdr("\U0001F4C8 Sales Analytics"); sd, ed, _ = dfr("asa")
        df = fbd(DS.sales(), sd, ed)
        d = df.groupby(df["Doc_Date"].dt.date)["BL_NETVAL"].sum().reset_index(); d.columns = ["Date", "Sales"]
        fig = px.line(d, x="Date", y="Sales"); fig.update_layout(height=230, margin=dict(t=10, b=10)); st.plotly_chart(fig, width="stretch")
        c1, c2 = st.columns(2)
        with c1:
            t = df.groupby("ITEM_NAME").agg(Revenue=("BL_NETVAL", "sum")).nlargest(20, "Revenue").reset_index()
            fig2 = px.bar(t, y="ITEM_NAME", x="Revenue", orientation="h", text_auto=".2s"); fig2.update_layout(height=420, margin=dict(t=10, b=10), yaxis=dict(autorange="reversed")); st.plotly_chart(fig2, width="stretch")
        with c2:
            g = df.groupby("GRP_NAME").agg(Revenue=("BL_NETVAL", "sum")).reset_index()
            fig3 = px.pie(g, names="GRP_NAME", values="Revenue", hole=.35); fig3.update_layout(height=420, margin=dict(t=10, b=10)); st.plotly_chart(fig3, width="stretch")
        mg = df.groupby("ITEM_NAME").agg(Revenue=("BL_NETVAL", "sum"), Cost=("Item_Cost", "sum")).nlargest(20, "Revenue").reset_index()
        mg["Margin"] = mg["Revenue"] - mg["Cost"]; mg["Margin%"] = (mg["Margin"] / mg["Revenue"].replace(0, float("nan")) * 100).round(1)
        mg = mg[["ITEM_NAME", "Revenue", "Margin", "Cost", "Margin%"]]
        st.dataframe(mg, width="stretch", hide_index=True, column_config={"Revenue": CC_AMT0, "Cost": CC_AMT0, "Margin": CC_AMT0})
        st.caption("Revenue includes GST. Margin is that recorded revenue less source Item_Cost; confirm the cost basis before using it as a profitability measure.")
        st.markdown("**Sales outlook — current and next financial year**")
        st.caption("Forecast training uses prior financial years, independently of the historical chart date filter. Amounts use recorded invoice totals including GST and invoice rounding.")
        from sales_forecast import project_sales
        outlook = project_sales(AllData.doc_header(), today())
        if not outlook["history"].empty:
            st.dataframe(outlook["history"].rename(columns={"Sales": "Sales (incl. GST)", "Months": "Months with sales"}), hide_index=True, width="stretch")
        if outlook["reason"]:
            st.info(outlook["reason"])
            return
        monthly = outlook["monthly"]
        this_year = monthly.loc[monthly.FY == current.label]
        next_year = monthly.loc[monthly.FY != current.label]
        if this_year.Actual.isna().all():
            st.info("No current-year actual sales are loaded. The outlook is based entirely on prior-year records.")
        a, b, c = st.columns(3)
        a.metric(f"FY {current.label} expected total", f"{INR}{this_year.Expected.sum():,.0f}")
        b.metric("Estimated remaining sales", f"{INR}{this_year.Remaining.sum():,.0f}")
        c.metric(f"FY {next_year.FY.iloc[0]} forecast", f"{INR}{next_year.Expected.sum():,.0f}")
        st.caption(f"Baseline: monthly sales in FY {outlook['baseline_year']}; annual growth assumption {outlook['growth']:.1%}, using the median of up to three consecutive historical year-on-year changes, limited to ±30%. Years need sales in all 12 months to qualify. Recorded actuals through {outlook['cutoff']:%d %b %Y}; a partial month's estimate cannot be below its recorded sales. Missing later records are estimated, not treated as zero sales.")
        fig4 = px.line(monthly, x="Month", y=["Actual", "Expected"], markers=True)
        fig4.update_layout(height=300, margin=dict(t=10, b=10)); st.plotly_chart(fig4, width="stretch")
        st.dataframe(monthly, hide_index=True, width="stretch", column_config={c: CC_AMT for c in ["Actual", "Expected", "Remaining"]})
        st.caption("This is a seasonal planning estimate, not a guarantee or a validated statistical confidence interval. Pricing, supply, promotions and missing source records can change outcomes.")


    def page_analytics_purchase():
        import plotly.express as px
        hdr("\U0001F4C8 Purchase Analytics"); sd, ed, _ = dfr("apa")
        st.caption("Purchase charts use taxable amounts excluding GST and other tax.")
        df = fbd(DS.purchases(), sd, ed)
        d = df.groupby(df["Doc_Date"].dt.date)["taxable_value"].sum().reset_index(); d.columns = ["Date", "Amount"]
        fig = px.bar(d, x="Date", y="Amount", text_auto=".2s"); fig.update_layout(height=230, margin=dict(t=10, b=10)); st.plotly_chart(fig, width="stretch")
        c1, c2 = st.columns(2)
        with c1:
            t = df.groupby("ITEM_NAME").agg(Amount=("taxable_value", "sum")).nlargest(15, "Amount").reset_index()
            fig2 = px.bar(t, y="ITEM_NAME", x="Amount", orientation="h", text_auto=".2s"); fig2.update_layout(height=380, margin=dict(t=10, b=10), yaxis=dict(autorange="reversed")); st.plotly_chart(fig2, width="stretch")
        with c2:
            ts = df.groupby("supplier_name").agg(Amount=("taxable_value", "sum")).nlargest(15, "Amount").reset_index()
            fig3 = px.bar(ts, y="supplier_name", x="Amount", orientation="h", text_auto=".2s"); fig3.update_layout(height=380, margin=dict(t=10, b=10), yaxis=dict(autorange="reversed")); st.plotly_chart(fig3, width="stretch")


    def page_analytics_gst():
        import plotly.express as px
        import plotly.graph_objects as go
        hdr("\U0001F4C8 GST Analytics"); sd, ed, _ = dfr("ag")
        s = fbd(DS.sales(), sd, ed); p = fbd(DS.purchases(), sd, ed)
        rs = s.groupby("Vat_Rate").agg(Taxable=("taxable_value", "sum"), Tax=("total_gst", "sum")).reset_index(); rs["Rate"] = rs["Vat_Rate"].astype(str) + "%"
        fig = px.bar(rs, x="Rate", y="Taxable", text_auto=".2s"); fig.update_layout(height=230, margin=dict(t=10, b=10)); st.plotly_chart(fig, width="stretch")
        sm = s.groupby("month").agg(Output=("total_gst", "sum")).reset_index(); pm = p.groupby("month").agg(Input=("total_gst", "sum")).reset_index()
        gt = sm.merge(pm, on="month", how="outer").fillna(0); gt["Net"] = gt["Output"] - gt["Input"]
        fig2 = go.Figure(); fig2.add_trace(go.Bar(name="Output", x=gt["month"], y=gt["Output"])); fig2.add_trace(go.Bar(name="Input", x=gt["month"], y=gt["Input"]))
        fig2.add_trace(go.Scatter(name="Net", x=gt["month"], y=gt["Net"], mode="lines+markers")); fig2.update_layout(barmode="group", height=320, margin=dict(t=10, b=10))
        st.plotly_chart(fig2, width="stretch")
        st.dataframe(gt, width="stretch", hide_index=True, column_config={"Output": CC_AMT0, "Input": CC_AMT0, "Net": CC_AMT0})


    # ═══════════════════════ ROUTER ═════════════════════════════════════════════
    def page_validation():
        from data_quality import validation_summary, invoice_reconciliation
        hdr("Data Validation")
        sd, ed, _ = dfr("validation")
        st.caption(f"Integrity checks cover the current FY. Invoice reconciliation uses {sd:%d %b %Y} to {ed:%d %b %Y}. New or changed Access files are imported automatically.")
        st.dataframe(validation_summary(DS), hide_index=True, width="stretch")
        st.markdown("**Invoice reconciliation**")
        st.caption("Invoice total minus inclusive line totals. Differences are shown explicitly, without changing the source values.")
        reconciliation = invoice_reconciliation(DS)
        reconciliation = reconciliation.loc[reconciliation.Doc_Id.isin(fbd(DS.doc_header(), sd, ed).Doc_Id)]
        summary = reconciliation.groupby("Type").agg(Invoices=("Doc_Id", "count"), Invoice_Total=("Bill_Amt", "sum"),
                                                      Line_Total=("Line_Total", "sum"), Difference=("Difference", "sum"))
        st.dataframe(summary, column_config={c: CC_AMT for c in ["Invoice_Total", "Line_Total", "Difference"]}, width="stretch")
        st.dataframe(reconciliation.loc[reconciliation.Difference.abs() > 0.01].sort_values("Difference"),
                     hide_index=True, width="stretch", column_config={c: CC_AMT for c in ["Bill_Amt", "Line_Total", "Difference"]})
        st.info("GST reports cover goods invoices. Financial reports show recorded ledger movements; the export uses implicit cash contra entries. Source cost values produce some negative item margins; verify these in the billing system before using margins for decisions.")


    PAGES = {
        "home": page_home,
        "sales_billwise": page_sales_billwise, "sales_datewise": page_sales_datewise, "sales_monthly": page_sales_monthly,
        "sales_hsn": page_sales_hsn, "sales_partywise": page_sales_partywise, "sales_gstno": page_sales_gstno,
        "purch_billwise": page_purch_billwise, "purch_datewise": page_purch_datewise, "purch_monthly": page_purch_monthly,
        "purch_hsn": page_purch_hsn, "purch_partywise": page_purch_partywise, "purch_gstno": page_purch_gstno,
        "summary_stock": page_summary_stock, "summary_sales": page_summary_sales, "summary_purchase": page_summary_purchase,
        "summary_gst": page_summary_gst, "summary_financial": page_summary_financial,
        "analytics_stock": page_analytics_stock, "analytics_sales": page_analytics_sales,
        "analytics_purchase": page_analytics_purchase, "analytics_gst": page_analytics_gst,
        "validation": page_validation,
    }
    PAGES.get(st.session_state.page, page_home)()
