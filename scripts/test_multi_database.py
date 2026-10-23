"""Annual-file collisions, atomic imports, auto refresh and year-specific stock."""
from pathlib import Path
import sqlite3
import sys
import threading
import time

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config
import database_sync as sync
from data_store import DataStore as DS
from data_quality import invoice_reconciliation


def annual_tables(year):
    common = dict(Act_ID=10, Mode=0, Doc_Cancel=0, Bill_Qty=2, Supp_Billno="1", Supp_Billdate=f"{year}-04-02")
    header = pd.DataFrame([
        dict(common, Doc_Id=1, Doc_Date=f"{year}-03-31", Tt_Id=0, TSeries="OPB", TNo=1, Bill_Amt=1000),
        dict(common, Doc_Id=2, Doc_Date=f"{year}-04-03", Tt_Id=31, TSeries="3GST", TNo=1, Bill_Amt=210),
        dict(common, Doc_Id=3, Doc_Date=f"{year}-04-02", Tt_Id=5, TSeries="PUR", TNo=1, Act_ID=20, Bill_Amt=525),
    ])
    money = dict(IC_ID=100, BILL_FREE=0, CGSTAMT=5, SGSTAMT=5, IGSTAMT=0, Vat_Rate=5, cessAmt=0, CCAMT=0, stockconv=0)
    return {
        "Doc_Header": header,
        "Stock_Delv": pd.DataFrame([dict(money, DOC_ID=2, BILL_QTY=2, SRATE=105, BL_VALUE=210, BL_NETVAL=210, Item_Cost=180)]),
        "Stock_Recd": pd.DataFrame([
            dict(money, DOC_ID=1, BILL_QTY=10, IRATE=100, BL_VALUE=1000, BL_NETVAL=1000, CGSTAMT=0, SGSTAMT=0, Act_ID=0),
            dict(money, DOC_ID=3, BILL_QTY=5, IRATE=100, BL_VALUE=500, BL_NETVAL=525, CGSTAMT=12.5, SGSTAMT=12.5, Act_ID=20, stockconv=1),
        ]),
        "Accmst": pd.DataFrame([dict(Act_Id=10, Act_Name=f"Customer {year}", Act_Type="Customer", Act_MG="A", Act_Cat=0), dict(Act_Id=20, Act_Name=f"Supplier {year}", Act_Type="Supplier", Act_MG="L", Act_Cat=0)]),
        "AccAdr": pd.DataFrame([dict(Act_Id=10, GSTNO=""), dict(Act_Id=20, GSTNO=f"GST{year}")]),
        "NAME_TRAN": pd.DataFrame([dict(Doc_Id=2, Act_Name=f"Buyer {year}", Act_Town="Town", GSTNO="")]),
        "Items": pd.DataFrame([dict(ITEM_ID=50, ITEM_NAME=f"Oil {year}")]),
        "Item_Grp": pd.DataFrame([dict(IC_ID=100, ITEM_ID=50, GRP_ID=2, IssueConv=1, HSNCode="15121910", GST=5, Sale_PACK="Unit")]),
        "Groups": pd.DataFrame([dict(GRP_ID=2, GRP_NAME=f"Group {year}")]),
        "TTYPES": pd.DataFrame([dict(TT_ID=31)]),
        "DayBook": pd.DataFrame([dict(Doc_ID=2, Act_ID=10, TRDATE=f"{year}-04-03", AMOUNT=210, TYPE="D"), dict(Doc_ID=3, Act_ID=20, TRDATE=f"{year}-04-02", AMOUNT=525, TYPE="C")]),
    }


@pytest.fixture
def importer(tmp_path, monkeypatch):
    folder = tmp_path / "database"
    folder.mkdir()
    monkeypatch.setattr(config, "DATABASE_DIR", folder)
    monkeypatch.setattr(config, "IMPORT_CACHE", tmp_path / "cache.sqlite3")
    calls = []
    def read(path):
        calls.append(path.name)
        return annual_tables(int(path.stem[-4:]))
    worker = sync.DatabaseSync(folder, config.IMPORT_CACHE, reader=read, stable_seconds=0)
    worker.calls = calls
    st.cache_resource.clear()
    yield worker
    st.cache_resource.clear()


def add(worker, year):
    file = worker.directory / f"3G{year}.mdb"
    file.write_bytes(str(year).encode())
    worker.sync_once()
    return file


def test_repeated_ids_and_invoice_numbers_never_cross_join(importer):
    add(importer, 2026)
    add(importer, 2025)
    with sync.read_snapshot():
        sales = DS.sales()
        assert len(sales) == 2
        assert sales.Doc_Id.nunique() == 2
        assert sales.document_key.nunique() == 2
        assert sales.bill_no.tolist() == ["3GST-1", "3GST-1"]
        assert set(sales.invoice_label) == {"3GST-1 | FY 2026-27 | 3G2026.mdb", "3GST-1 | FY 2025-26 | 3G2025.mdb"}
        for year in [2025, 2026]:
            row = sales[sales.financial_year == f"{year}-{str(year+1)[-2:]}"].iloc[0]
            assert row.customer_name == f"Buyer {year}"
            assert row.ITEM_NAME == f"Oil {year}"
            assert row.GRP_NAME == f"Group {year}"
            assert row.SRATE == 105
        assert len(DS.purchases()) == 2
        assert DS.daybook().Act_Name.nunique() == 4
        assert invoice_reconciliation().Difference.abs().sum() == 0


def test_unchanged_files_are_not_read_or_counted_again(importer):
    add(importer, 2026)
    version = sync.revision()
    importer.sync_once()
    assert importer.calls == ["3G2026.mdb"]
    assert sync.revision() == version
    assert len(DS.sales()) == 1


def test_changed_file_replaces_old_data_without_duplicate_invoices(importer):
    path = add(importer, 2026)
    old = DS.sales()
    def changed(_):
        tables = annual_tables(2026)
        tables["Stock_Delv"]["SRATE"] = 110
        return tables
    importer.reader = changed
    path.write_bytes(b"changed contents")
    importer.sync_once()
    new = DS.sales()
    assert new is not old
    assert len(new) == 1
    assert new.iloc[0].SRATE == 110
    assert old.iloc[0].SRATE == 105


def test_read_snapshot_stays_consistent_during_background_publish(importer):
    add(importer, 2026)
    with sync.read_snapshot():
        old_revision = sync.revision()
        old = DS.sales()
        add(importer, 2025)
        assert sync.revision() == old_revision
        assert DS.sales() is old
        assert len(DS.doc_header()) == 3
    assert sync.revision() > old_revision
    assert len(DS.sales()) == 2


def test_opening_stock_does_not_stack_across_financial_years(importer):
    add(importer, 2026)
    add(importer, 2025)
    assert DS.closing_stock().closing_qty.sum() == 13
    assert set(DS.closing_stock().ITEM_NAME) == {"Oil 2026"}
    old = DS.closing_stock(pd.Timestamp("2025-04-03").date())
    assert old.closing_qty.sum() == 13
    assert set(old.ITEM_NAME) == {"Oil 2025"}


def test_invalid_new_file_keeps_last_good_data(importer):
    add(importer, 2026)
    before = sync.revision()
    importer.reader = lambda _: {}
    add(importer, 2025)
    assert sync.revision() == before
    assert len(DS.sales()) == 1
    assert importer.status["3g2025.mdb"].startswith("Import failed")


def test_duplicate_copy_and_overlapping_year_are_not_double_counted(importer):
    original = add(importer, 2026)
    copy = importer.directory / "copy.mdb"
    copy.write_bytes(original.read_bytes())
    importer.sync_once()
    assert "Ignored identical copy" in importer.status["copy.mdb"]
    copy.write_bytes(b"different same year")
    importer.reader = lambda _: annual_tables(2026)
    importer.sync_once()
    assert "Financial year overlaps" in importer.status["copy.mdb"]
    assert len(DS.sales()) == 1


def test_removed_file_disappears_and_readded_file_keeps_identity(importer):
    original = add(importer, 2026)
    add(importer, 2025)
    key = DS.sales().loc[lambda d: d.financial_year == "2026-27", "Doc_Id"].iloc[0]
    original.unlink()
    importer.sync_once()
    assert DS.financial_years() == ["2025-26"]
    add(importer, 2026)
    assert DS.sales().loc[lambda d: d.financial_year == "2026-27", "Doc_Id"].iloc[0] == key


def test_partial_file_waits_without_opening_access(importer):
    importer.stable_seconds = 60
    add(importer, 2026)
    assert importer.calls == []
    assert importer.status["3g2026.mdb"].startswith("Waiting")


def test_year_selector_and_repeated_bill_filter(importer):
    add(importer, 2026)
    add(importer, 2025)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at.session_state.page = "analytics_sales"
    at.run()
    at.selectbox(key="financial_year").set_value("2025-26").run()
    at.button(key="h_asa").click().run()
    at.button(key="b_sales_billwise").click().run()
    at.date_input(key="sbw_f").set_value(pd.Timestamp("2026-04-03").date())
    at.date_input(key="sbw_t").set_value(pd.Timestamp("2026-04-03").date()).run()
    assert not at.exception
    assert at.dataframe[0].value.Financial_Year.unique().tolist() == ["2026-27"]
    assert at.dataframe[0].value.Sale_Rate.tolist() == [105]
    assert len(at.multiselect(key="sbw_b").options) == 1
    assert not list(at.selectbox)


def test_poller_revision_refreshes_open_dashboard(importer):
    add(importer, 2026)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at.session_state.page = "analytics_sales"
    at.run()
    add(importer, 2025)
    at.run()
    assert not at.exception
    assert "2025-26" in at.selectbox(key="financial_year").options


def test_background_scan_picks_up_a_new_file_without_manual_refresh(importer):
    thread = threading.Thread(target=importer.run, daemon=True)
    thread.start()
    try:
        (importer.directory / "3G2026.mdb").write_bytes(b"2026")
        # Wake the normal folder scan so the test need not wait the production 10s interval.
        importer.request_scan()
        deadline = time.monotonic() + 5
        while importer.status.get("3g2026.mdb") != "Ready" and time.monotonic() < deadline:
            threading.Event().wait(0.01)
        assert importer.status.get("3g2026.mdb") == "Ready"
        assert len(DS.sales()) == 1
    finally:
        importer.stop()
        thread.join(timeout=5)
        assert not thread.is_alive()


def test_failed_sqlite_publication_rolls_back_all_changed_tables(importer):
    path = add(importer, 2026)
    before = sync.revision()
    connection = sqlite3.connect(config.IMPORT_CACHE)
    connection.execute("CREATE TRIGGER reject_receipts BEFORE INSERT ON Stock_Recd BEGIN SELECT RAISE(FAIL, 'test storage failure'); END")
    connection.commit()
    connection.close()
    def modified(_):
        tables = annual_tables(2026)
        tables["Doc_Header"].loc[lambda d: d.Doc_Id == 2, "Bill_Amt"] = 230
        return tables
    importer.reader = modified
    path.write_bytes(b"new content")
    importer.sync_once()
    assert sync.revision() == before
    assert sync.read_table("Doc_Header.csv").query("Doc_Id == 2").Bill_Amt.iloc[0] == 210
    assert len(DS.sales()) == 1


@pytest.mark.parametrize("page", ["sales_datewise", "sales_monthly", "sales_hsn", "sales_partywise", "sales_gstno",
    "purch_billwise", "purch_datewise", "purch_monthly", "purch_hsn", "purch_partywise", "purch_gstno",
    "summary_stock", "summary_sales", "summary_purchase", "summary_gst", "summary_financial",
    "analytics_stock", "analytics_sales", "analytics_purchase", "analytics_gst", "validation"])
def test_all_reports_render_with_colliding_annual_ids(importer, page):
    add(importer, 2026)
    add(importer, 2025)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at.session_state.page = page
    at.run()
    assert not at.exception, [e.message for e in at.exception]
