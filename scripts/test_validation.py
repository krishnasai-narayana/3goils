"""Regression and real Streamlit interaction tests. Run: python -m pytest scripts/test_validation.py -q"""
import sys
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config
from data_store import DataStore as DS


def raw(name):
    return pd.read_csv(config.DATA_DIR / f"{name}.csv", low_memory=False)


def test_money_preserves_source_precision():
    assert DS.doc_header().Bill_Amt.sum() == pytest.approx(raw("Doc_Header").Bill_Amt.sum(), abs=0.001)


def test_purchase_facts_exclude_opening_stock_and_returns():
    assert set(DS.purchases().Tt_Id) <= set(config.PURCHASE_TT_IDS)
    assert len(DS.purchases()) == 302


@pytest.mark.parametrize("method", [DS.sales, DS.purchases])
def test_taxable_plus_tax_reconciles_to_line_net(method):
    d = method()
    assert np.allclose(d.taxable_value + d.total_gst + d.other_tax, d.BL_NETVAL, atol=0.011)


def test_stock_conversion_matches_source_flags():
    valid = raw("Doc_Header").query("Doc_Cancel == 0")
    inward = raw("Stock_Recd").loc[lambda d: d.DOC_ID.isin(valid.loc[valid.Tt_Id.isin(config.STOCK_INWARD_TT_IDS), "Doc_Id"])].merge(raw("Item_Grp")[["IC_ID", "IssueConv"]], on="IC_ID")
    q = (inward.BILL_QTY + inward.BILL_FREE) * inward.IssueConv.where(inward.stockconv == 1, 1)
    outward = raw("Stock_Delv").loc[lambda d: d.DOC_ID.isin(valid.loc[valid.Tt_Id.isin(config.STOCK_OUTWARD_TT_IDS), "Doc_Id"])]
    expected = q.groupby(inward.IC_ID).sum().subtract(
        (outward.BILL_QTY + outward.BILL_FREE).groupby(outward.IC_ID).sum(), fill_value=0)
    actual = DS.closing_stock().set_index("IC_ID").closing_qty
    assert np.allclose(actual.reindex(expected.index), expected)
    assert actual.sum() == pytest.approx(expected.sum())


def test_stock_cutoff_and_period_opening():
    before = DS.closing_stock(pd.Timestamp("2026-03-31").date())
    assert before.closing_qty.sum() == pytest.approx(39160)
    period = DS.closing_stock(DS.max_date(), pd.Timestamp("2026-04-01").date())
    assert np.allclose(period.opening_qty + period.total_inward - period.total_outward, period.closing_qty)
    assert np.allclose(period.closing_qty, DS.closing_stock().closing_qty)


def test_dimension_joins_preserve_source_rows_and_identifiers():
    h = raw("Doc_Header").query("Doc_Cancel == 0")
    for source, ids, facts in [("Stock_Delv", config.SALE_TT_IDS, DS.sales()),
                               ("Stock_Recd", config.PURCHASE_TT_IDS, DS.purchases())]:
        expected = raw(source).DOC_ID.isin(h.loc[h.Tt_Id.isin(ids), "Doc_Id"]).sum()
        assert len(facts) == expected
        assert facts.ITEM_NAME.notna().all()
        assert not facts.HSNCode.str.contains(r"\.0$", regex=True).any()


PAGES = ["home", "sales_billwise", "sales_datewise", "sales_monthly", "sales_hsn",
         "sales_partywise", "sales_gstno", "purch_billwise", "purch_datewise", "purch_monthly",
         "purch_hsn", "purch_partywise", "purch_gstno", "summary_stock", "summary_sales",
         "summary_purchase", "summary_gst", "summary_financial", "analytics_stock",
         "analytics_sales", "analytics_purchase", "analytics_gst", "validation"]


@pytest.mark.parametrize("page", PAGES)
def test_real_page_renders_and_handles_empty_range(page, monkeypatch):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at.session_state.page = page
    at.run()
    assert not at.exception, [x.message for x in at.exception]
    assert len(at.title) + len(at.markdown) > 0
    if page in ["home", "summary_stock", "validation"]:
        return
    if page.startswith("analytics_"):
        for widget in at.date_input:
            widget.set_value(DS.min_date())
    else:
        # A new FY without an annual file must stay empty rather than showing
        # the previous year's transactions.
        import reporting
        monkeypatch.setattr(reporting, "today", lambda: dt.date(2027, 10, 22))
    at.run()
    assert not at.exception, [x.message for x in at.exception]


def test_navigation_filters_and_invalid_date_range():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    at.button(key="b_sales_billwise").click().run()
    assert at.session_state.page == "sales_billwise"
    at.date_input(key="sbw_f").set_value(DS.max_date())
    at.date_input(key="sbw_t").set_value(DS.max_date()).run()
    customer = at.multiselect(key="sbw_c")
    customer.select(customer.options[0]).run()
    assert not at.exception
    assert at.dataframe[0].value.Customer_Name.nunique() == 1
    at.button(key="h_sbw").click().run()
    assert at.session_state.page == "home"
    at.date_input(key="h_f").set_value(DS.max_date())
    at.date_input(key="h_t").set_value(dt.date(2026,4,1)).run()
    assert len(at.error) == 1
    assert not at.exception


def test_home_full_range_totals_match_source_headers():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    at.date_input(key="h_f").set_value(dt.date(2026,4,1)).run()
    assert [m.value for m in at.metric] == ["₹70,156,990", "₹66,706,546", "7,425", "93"]


@pytest.mark.parametrize("page", ["sales_hsn", "purch_hsn"])
def test_hsn_taxable_total_matches_source_net_less_tax(page):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at.session_state.page = page
    at.run()
    prefix = "sh" if page == "sales_hsn" else "ph"
    at.date_input(key=f"{prefix}_f").set_value(dt.date(2026,4,1)).run()
    source = raw("Stock_Delv" if page == "sales_hsn" else "Stock_Recd")
    if page == "purch_hsn":
        source = source[source.DOC_ID.isin(raw("Doc_Header").query("Tt_Id in [5, 40]").Doc_Id)]
    expected = source.BL_NETVAL.sum() - source[["CGSTAMT", "SGSTAMT", "IGSTAMT", "cessAmt", "CCAMT"]].sum().sum()
    assert at.dataframe[0].value.Taxable.sum() == pytest.approx(expected, abs=0.01)


def test_stock_widget_changes_cutoff_balance():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at.session_state.page = "summary_stock"
    at.run()
    latest = at.dataframe[0].value.Balance.sum()
    at.date_input(key="ss_f").set_value(dt.date(2026,4,1))
    at.date_input(key="ss_t").set_value(dt.date(2026,4,1)).run()
    expected = DS.closing_stock(dt.date(2026,4,1),dt.date(2026,4,1)).closing_qty.sum()
    assert at.dataframe[0].value.Balance.sum() == pytest.approx(expected)
    assert at.dataframe[0].value.Opening.sum() == pytest.approx(39160)
    assert latest != expected


def test_invoice_sale_rate_and_amount_preserve_original_inclusive_values():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at.session_state.page = "sales_billwise"
    at.run()
    at.date_input(key="sbw_f").set_value(DS.max_date())
    at.date_input(key="sbw_t").set_value(DS.max_date()).run()
    at.multiselect(key="sbw_b").select("3GST-7425").run()
    assert not at.exception
    header = raw("Doc_Header").query("TSeries == '3GST' and TNo == 7425").iloc[0]
    expected = raw("Stock_Delv").loc[lambda d: d.DOC_ID == header.Doc_Id]
    shown = at.dataframe[0].value
    assert shown.Sale_Rate.tolist() == expected.SRATE.tolist()
    assert shown.Amount.tolist() == expected.BL_VALUE.tolist()
    assert shown.Quantity.tolist() == expected.BILL_QTY.tolist()


@pytest.mark.parametrize("page", ["sales_partywise", "summary_sales", "analytics_sales"])
def test_sales_reports_keep_gst_inclusive_amounts(page):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at.session_state.page = page
    at.run()
    if page != "analytics_sales":
        prefix = "sp" if page == "sales_partywise" else "ssu"
        at.date_input(key=f"{prefix}_f").set_value(dt.date(2026,4,1)).run()
    assert not at.exception
    expected = raw("Stock_Delv").BL_NETVAL.sum()
    if page == "sales_partywise":
        assert at.dataframe[0].value.Amount.sum() == pytest.approx(expected, abs=0.01)
    elif page == "summary_sales":
        assert at.metric[2].label == "Sales (incl. GST)"
        assert at.dataframe[1].value.Amount.sum() == pytest.approx(expected, abs=0.01)
        assert at.dataframe[2].value.Total.sum() == pytest.approx(expected, abs=0.01)
    else:
        top = DS.sales().groupby("ITEM_NAME").BL_NETVAL.sum().nlargest(20)
        assert at.dataframe[0].value.Revenue.sum() == pytest.approx(top.sum(), abs=0.01)
