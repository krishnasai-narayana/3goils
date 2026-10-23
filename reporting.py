"""Current-FY operational views; historical storage stays available to analytics."""
import datetime as dt
import pandas as pd
from data_store import DataStore, _load_raw


def today():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30))).date()


def fiscal_bounds(day):
    year = day.year - (day.month < 4)
    return dt.date(year, 4, 1), dt.date(year + 1, 3, 31)


def fiscal_label(day):
    start, end = fiscal_bounds(day)
    return f"{start.year}-{str(end.year)[-2:]}"


class CurrentFY:
    def __init__(self, day):
        self.start, self.end = fiscal_bounds(day)
        self.label = fiscal_label(day)
        headers = _load_raw()["dh"]
        business = headers[(headers.Tt_Id != 0) & (headers.financial_year == self.label)]
        self.sources = set(business.source_database)
        valid = business.loc[business.Doc_Cancel == 0]
        self.latest = valid.Doc_Date.max().date() if not valid.empty else day

    def _period(self, frame):
        lo, hi = int(self.start.strftime("%Y%m%d")), int(self.end.strftime("%Y%m%d"))
        return frame.loc[frame.dk.between(lo, hi) & frame.source_database.isin(self.sources)]

    def doc_header(self): return self._period(DataStore.doc_header())
    def sales(self): return self._period(DataStore.sales())
    def purchases(self): return self._period(DataStore.purchases())
    def sales_bill_lines(self): return self._period(DataStore.sales_bill_lines())
    def daybook(self): return self._period(DataStore.daybook())
    def stock_movements(self): return self._period(DataStore.stock_movements())

    def closing_stock(self, as_of=None, from_date=None):
        if not self.sources:
            return pd.DataFrame(columns=["IC_ID", "ITEM_NAME", "GRP_NAME", "Sale_PACK", "opening_qty", "total_inward", "total_outward", "closing_qty"])
        return DataStore.closing_stock(min(as_of or self.latest, self.end), max(from_date or self.start, self.start))

    def raw_table(self, key):
        frame = _load_raw()[key]
        frame = frame.loc[frame.source_database.isin(self.sources)]
        if key == "dh":
            in_year = frame.Doc_Date.between(pd.Timestamp(self.start), pd.Timestamp(self.end))
            opening = (frame.Tt_Id == 0) & (frame.Doc_Date == pd.Timestamp(self.start) - pd.Timedelta(days=1))
            return frame.loc[in_year | opening]
        if key in ["sd", "sr", "nt"]:
            column = "Doc_Id" if key == "nt" else "DOC_ID"
            return frame.loc[frame[column].isin(self.raw_table("dh").Doc_Id)]
        if key == "db":
            return self._period(frame)
        return frame
