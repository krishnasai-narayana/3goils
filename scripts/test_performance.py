"""Regression guards for lazy loading, single-run navigation and cached bill data."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import data_store
from data_store import DataStore as DS


def test_home_and_bill_page_load_only_the_tables_they_use(monkeypatch):
    st.cache_resource.clear()
    reads = []
    original = data_store._read
    def record_read(name, **kwargs):
        reads.append(name)
        return original(name, **kwargs)
    monkeypatch.setattr(data_store, "_read", record_read)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not at.exception
    assert reads == ["Doc_Header.csv"]
    at.button(key="b_sales_billwise").click().run()
    assert not at.exception
    assert "Stock_Delv.csv" in reads
    assert "Stock_Recd.csv" not in reads
    assert "DayBook.csv" not in reads
    assert "TTYPES.csv" not in reads
    assert len(reads) == len(set(reads))
    before = reads.copy()
    at.run()
    assert reads == before


def test_cached_tables_exclude_unused_access_fields():
    raw = data_store._load_raw()
    for key, (filename, _, _, _, _) in data_store._TABLES.items():
        table = raw[key]
        required = set(data_store.database_sync.TABLE_COLUMNS[filename[:-4]].split())
        assert required <= set(table)
        assert set(table) <= required | {"source_database", "source_index", "source_doc_id", "dk", "date_str", "month", "financial_year", "document_key"}


def test_navigation_does_not_render_the_previous_page_again(monkeypatch):
    calls = []
    original = DS.doc_header
    def get_headers():
        calls.append("home")
        return original()
    monkeypatch.setattr(DS, "doc_header", staticmethod(get_headers))
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert calls == ["home"]
    at.button(key="b_sales_billwise").click().run()
    assert not at.exception
    assert at.session_state.page == "sales_billwise"
    assert calls == ["home"]
    at.button(key="h_sbw").click().run()
    assert at.session_state.page == "home"
    assert calls == ["home", "home"]


def test_bill_data_is_cached_compact_and_already_sorted():
    lines = DS.sales_bill_lines()
    assert lines is DS.sales_bill_lines()
    assert len(lines.columns) == 14
    assert lines.dk.is_monotonic_decreasing
    assert len(lines) == len(DS.sales())
    expected = DS.sales()[lines.columns].sort_values(["dk", "TNo"], ascending=False, kind="stable").reset_index(drop=True)
    pd.testing.assert_frame_equal(lines, expected)


def test_reload_button_invalidates_the_derived_bill_cache():
    original = DS.sales_bill_lines()
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    at.button(key="reload_data").click().run()
    assert not at.exception
    refreshed = DS.sales_bill_lines()
    assert refreshed is not original
    pd.testing.assert_frame_equal(refreshed, original)
