"""Real-data-only routing, India date defaults and future annual imports."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import sqlite3
import pytest
from streamlit.testing.v1 import AppTest
import config
import reporting
from data_store import DataStore as DS
from scripts.test_validation import PAGES
from scripts.test_multi_database import importer, add, ROOT
from scripts.test_multi_database import annual_tables


@pytest.mark.parametrize("page", PAGES)
def test_every_page_uses_its_requested_default_period(page,monkeypatch):
    day=dt.date(2026,10,22)
    monkeypatch.setattr(reporting,"today",lambda:day)
    at=AppTest.from_file(str(ROOT/"app.py"),default_timeout=60)
    at.session_state.page=page
    at.run()
    assert not at.exception,[e.message for e in at.exception]
    assert list(at.date_input)
    if page.startswith("analytics_"):
        assert at.selectbox(key="financial_year").value=="All years"
        assert [w.value for w in at.date_input]==[DS.min_date(),DS.max_date()]
    else:
        start = dt.date(2026,4,1) if page.startswith(("sales_", "purch_")) and not page.endswith("_billwise") else dt.date(2026,8,7)
        assert [w.value for w in at.date_input]==[start,dt.date(2026,8,7)]
        if page=="home":
            assert at.metric[2].value=="54"
        elif page=="sales_billwise":
            assert at.metric[0].value=="54" and len(at.dataframe[0].value)==120
        elif page in ["sales_datewise","sales_monthly","purch_datewise","purch_monthly"]:
            assert at.dataframe[0].value.Bills.sum()==(7425 if page.startswith("sales_") else 93)
    assert not any("SYNTHETIC" in w.value for w in at.warning)


@pytest.mark.parametrize("section,prefix,bill_prefix", [("sales","sdw","sbw"),("purch","pdw","pbw")])
def test_fy_report_and_billwise_navigation_restore_their_own_defaults(section,prefix,bill_prefix,monkeypatch):
    monkeypatch.setattr(reporting,"today",lambda:dt.date(2026,10,22))
    at=AppTest.from_file(str(ROOT/"app.py"),default_timeout=60).run()
    at.button(key=f"b_{section}_datewise").click().run()
    assert [w.value for w in at.date_input]==[dt.date(2026,4,1),dt.date(2026,8,7)]
    at.date_input(key=f"{prefix}_f").set_value(dt.date(2026,8,1)).run()
    at.button(key=f"h_{prefix}").click().run()
    at.button(key=f"b_{section}_billwise").click().run()
    assert [w.value for w in at.date_input]==[dt.date(2026,8,7)]*2
    at.button(key=f"h_{bill_prefix}").click().run()
    at.button(key=f"b_{section}_datewise").click().run()
    assert [w.value for w in at.date_input]==[dt.date(2026,4,1),dt.date(2026,8,7)]


@pytest.mark.parametrize("page", ["sales_datewise","purch_datewise"])
def test_full_fy_default_stays_in_current_year_and_expands_with_new_data(page,importer,monkeypatch):
    monkeypatch.setattr(reporting,"today",lambda:dt.date(2026,10,22))
    add(importer,2025)
    path=add(importer,2026)
    at=AppTest.from_file(str(ROOT/"app.py"),default_timeout=60)
    at.session_state.page=page
    at.run()
    assert [w.value for w in at.date_input]==[dt.date(2026,4,1),dt.date(2026,4,3)]
    assert at.dataframe[0].value.Bills.sum()==1
    tables=annual_tables(2026)
    tables["Doc_Header"].loc[lambda d:d.Doc_Id==2,"Doc_Date"]="2026-04-04"
    importer.reader=lambda _:tables
    path.write_bytes(b"new latest date")
    importer.sync_once()
    at.run()
    assert not at.exception
    assert [w.value for w in at.date_input]==[dt.date(2026,4,1),dt.date(2026,4,4)]
    assert at.dataframe[0].value.Bills.sum()==1


def test_all_years_range_expands_when_an_older_database_arrives(importer,monkeypatch):
    monkeypatch.setattr(reporting,"today",lambda:dt.date(2026,10,22))
    add(importer,2026)
    at=AppTest.from_file(str(ROOT/"app.py"),default_timeout=60)
    at.session_state.page="analytics_sales"
    at.run()
    assert at.selectbox(key="financial_year").value=="All years"
    add(importer,2025)
    at.run()
    assert not at.exception
    assert at.selectbox(key="financial_year").value=="All years"
    assert at.date_input(key="asa_f").value==dt.date(2025,3,31)
    assert "2025-26" in at.selectbox(key="financial_year").options
    at.selectbox(key="financial_year").set_value("2025-26").run()
    at.button(key="h_asa").click().run()
    assert at.date_input(key="h_f").value==dt.date(2026,4,3)
    at.button(key="b_analytics_sales").click().run()
    assert not at.exception
    assert at.selectbox(key="financial_year").value=="All years"


def test_standard_page_reopens_on_latest_date_after_a_custom_date(monkeypatch):
    monkeypatch.setattr(reporting,"today",lambda:dt.date(2026,10,22))
    at=AppTest.from_file(str(ROOT/"app.py"),default_timeout=60).run()
    at.button(key="b_sales_billwise").click().run()
    at.date_input(key="sbw_f").set_value(dt.date(2026,4,1)).run()
    assert len(at.dataframe[0].value)>0
    at.button(key="h_sbw").click().run()
    at.button(key="b_sales_billwise").click().run()
    assert not at.exception
    assert all(w.value==DS.max_date() for w in at.date_input)
    assert len(at.dataframe[0].value)==120


def test_newer_import_moves_default_day_forward(importer,monkeypatch):
    monkeypatch.setattr(reporting,"today",lambda:dt.date(2026,10,22))
    path=add(importer,2026)
    at=AppTest.from_file(str(ROOT/"app.py"),default_timeout=60).run()
    assert at.date_input(key="h_f").value==dt.date(2026,4,3)
    tables=annual_tables(2026)
    tables["Doc_Header"].loc[lambda d:d.Doc_Id==2,"Doc_Date"]="2026-04-04"
    importer.reader=lambda _:tables
    path.write_bytes(b"updated latest transaction")
    importer.sync_once()
    at.run()
    assert not at.exception
    assert [w.value for w in at.date_input]==[dt.date(2026,4,4)]*2
    assert at.metric[2].value=="1"


def test_cancelled_document_does_not_determine_default_day(importer):
    tables=annual_tables(2026)
    cancelled=tables["Doc_Header"].iloc[[1]].copy()
    cancelled["Doc_Id"]=999
    cancelled["Doc_Date"]="2026-10-20"
    cancelled["Doc_Cancel"]=1
    import pandas as pd
    tables["Doc_Header"]=pd.concat([tables["Doc_Header"],cancelled],ignore_index=True)
    importer.reader=lambda _:tables
    add(importer,2026)
    assert reporting.CurrentFY(dt.date(2026,10,22)).latest==dt.date(2026,4,3)


def test_removed_demo_cannot_be_selected_by_an_environment_flag(monkeypatch):
    assert not hasattr(config,"DEMO_MODE")
    assert config.DATA_DIR==config.ROOT_DIR/"data"
    assert config.DATABASE_DIR==config.ROOT_DIR/"database"
    assert not (ROOT/"demo_data").exists()
    assert not (ROOT/"scripts"/"generate_demo.py").exists()
    with sqlite3.connect(config.IMPORT_CACHE) as connection:
        assert connection.execute('SELECT name FROM _sources').fetchall()==[('3g2026.mdb',)]
    recorded=json.loads((ROOT/"synthetic_cleanup.json").read_text())
    assert hashlib.sha256((config.DATABASE_DIR/"3G2026.mdb").read_bytes()).hexdigest()==recorded["reference_sha256"]


@pytest.mark.parametrize("instant,expected",[(dt.datetime(2026,10,22,20,tzinfo=dt.timezone.utc),dt.date(2026,10,23)),
    (dt.datetime(2026,3,31,19,tzinfo=dt.timezone.utc),dt.date(2026,4,1))])
def test_today_uses_india_midnight_not_host_date(monkeypatch,instant,expected):
    original=dt.datetime
    class Frozen(original):
        @classmethod
        def now(cls,tz=None):return instant.astimezone(tz)
    monkeypatch.setattr(reporting.dt,"datetime",Frozen)
    assert reporting.today()==expected
