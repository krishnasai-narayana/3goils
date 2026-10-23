"""Operational FY isolation and deterministic seasonal forecast checks."""
import datetime as dt
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
from scripts.test_multi_database import importer, add, ROOT
from data_store import DataStore as DS
from reporting import CurrentFY, fiscal_bounds
from sales_forecast import project_sales
from data_quality import validation_summary
from scripts.test_multi_database import annual_tables
import reporting


def headers(years, amounts=None):
    rows = []
    for year in years:
        amount = (amounts or {}).get(year, 100)
        for month in range(12):
            date = pd.Timestamp(year, 4, 1) + pd.DateOffset(months=month)
            rows.append(dict(Doc_Id=len(rows)+1, Doc_Date=date, Tt_Id=31, Doc_Cancel=0, Bill_Amt=amount))
    return pd.DataFrame(rows)


@pytest.mark.parametrize("day,start", [(dt.date(2026,3,31),2025),(dt.date(2026,4,1),2026),(dt.date(2028,2,29),2027)])
def test_fiscal_rollover(day,start):
    assert fiscal_bounds(day)==(dt.date(start,4,1),dt.date(start+1,3,31))


def test_current_scope_does_not_expose_previous_year_or_reuse_its_stock(importer):
    add(importer,2025)
    store=CurrentFY(dt.date(2026,10,22))
    for name in ["doc_header","sales","purchases","daybook","sales_bill_lines","stock_movements","closing_stock"]:
        assert getattr(store,name)().empty
    add(importer,2026)
    store=CurrentFY(dt.date(2026,10,22))
    assert len(store.sales())==1
    assert store.sales().financial_year.tolist()==["2026-27"]
    assert store.closing_stock().closing_qty.sum()==13
    assert len(DS.sales())==2


def test_validation_excludes_historical_documents_even_inside_the_current_file(importer):
    tables=annual_tables(2026)
    old=tables["Doc_Header"].iloc[[1]].copy()
    old["Doc_Id"]=999
    old["Doc_Date"]="2025-08-01"
    old["Tt_Id"]=32
    tables["Doc_Header"]=pd.concat([tables["Doc_Header"],old],ignore_index=True)
    importer.reader=lambda _:tables
    add(importer,2026)
    store=CurrentFY(dt.date(2026,10,22))
    assert 999 not in store.raw_table("dh").Doc_Id.tolist()
    checks=validation_summary(store).set_index("Check")
    assert checks.loc["Services outside goods GST reports","Count"]==0


def test_old_analytics_selection_cannot_leak_into_operational_pages(importer,monkeypatch):
    monkeypatch.setattr(reporting,"today",lambda:dt.date(2026,10,22))
    add(importer,2025); add(importer,2026)
    at=AppTest.from_file(str(ROOT/"app.py"),default_timeout=60)
    at.session_state.page="analytics_sales"
    at.run()
    at.selectbox(key="financial_year").set_value("2025-26").run()
    assert at.date_input(key="asa_f").value.year==2025
    at.button(key="h_asa").click().run()
    assert not at.exception and not list(at.selectbox)
    at.button(key="b_sales_billwise").click().run()
    assert at.dataframe[0].value.Financial_Year.unique().tolist()==["2026-27"]
    at.date_input(key="sbw_f").set_value(dt.date(2026,4,3))
    at.date_input(key="sbw_t").set_value(dt.date(2026,4,3)).run()
    assert not at.exception
    assert at.dataframe[0].value.Financial_Year.unique().tolist()==["2026-27"]
    assert at.date_input(key="sbw_f").min==dt.date(2026,4,1)


def test_flat_history_and_no_current_data_produces_labelled_monthly_baseline():
    result=project_sales(headers([2024,2025]),dt.date(2026,10,22))
    assert not result["reason"] and result["growth"]==0
    assert len(result["monthly"])==24
    assert result["monthly"].Expected.sum()==2400
    assert result["monthly"].Actual.isna().all()


def test_growth_and_partial_month_preserve_observed_sales_and_exclude_future():
    data=headers([2023,2024,2025],{2023:100,2024:110,2025:121})
    extra=pd.DataFrame([dict(Doc_Id=100+i,Doc_Date=pd.Timestamp(date),Tt_Id=31,Doc_Cancel=cancel,Bill_Amt=amount)
        for i,(date,amount,cancel) in enumerate([("2026-04-02",20,0),("2026-05-05",200,0),("2026-06-01",999999,0),("2026-05-01",999999,1)])])
    result=project_sales(pd.concat([data,extra]),dt.date(2026,5,5))
    assert result["growth"]==pytest.approx(.1)
    rows=result["monthly"].set_index("Month")
    assert rows.loc["2026-04","Expected"]==20
    assert rows.loc["2026-05","Expected"]==200
    assert rows.loc["2026-05","Remaining"]==0
    assert rows.loc["2026-06","Expected"]==133.1
    assert rows.loc["2027-04","Expected"]==146.41
    assert result["history"].FY.tolist()==["2023-24","2024-25","2025-26"]


@pytest.mark.parametrize("years", [[2024], [2026]])
def test_forecast_requires_immediately_preceding_covered_year(years):
    result=project_sales(headers(years),dt.date(2026,10,22))
    assert result["reason"] and result["monthly"].empty


def test_partial_year_cannot_train_the_model_and_growth_is_bounded():
    data=headers([2024,2025],{2024:100,2025:1000})
    assert project_sales(data,dt.date(2026,10,22))["growth"]==.3
    assert project_sales(data.iloc[:-1],dt.date(2026,10,22))["reason"]


def test_zero_history_is_finite_nonnegative():
    result=project_sales(headers([2024,2025],{2024:0,2025:0}),dt.date(2026,10,22))
    assert result["growth"]==0 and result["monthly"].Expected.eq(0).all()


@pytest.mark.parametrize("page", ["home","sales_billwise","sales_datewise","sales_monthly","sales_hsn","sales_partywise","sales_gstno",
    "purch_billwise","purch_datewise","purch_monthly","purch_hsn","purch_partywise","purch_gstno",
    "summary_stock","summary_sales","summary_purchase","summary_gst","summary_financial","validation"])
def test_missing_current_year_never_displays_prior_transactions_on_any_standard_page(importer,monkeypatch,page):
    monkeypatch.setattr(reporting,"today",lambda:dt.date(2026,10,22))
    add(importer,2025)
    at=AppTest.from_file(str(ROOT/"app.py"),default_timeout=60)
    at.session_state.page=page
    at.run()
    assert not at.exception,[e.message for e in at.exception]
    assert not list(at.selectbox)
    assert any("No business data loaded" in x.value for x in at.info)
    for widget in at.date_input:
        assert widget.value.year==2026
    if page=="sales_billwise":
        assert at.dataframe[0].value.empty and at.metric[0].value=="0"
    if page=="summary_stock":
        assert at.dataframe[0].value.empty
