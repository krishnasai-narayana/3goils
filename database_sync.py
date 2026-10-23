"""Incremental, read-only Access import with atomic publication to a local SQLite cache."""
from contextlib import contextmanager, closing
import datetime as dt
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
import time

import numpy as np
import pandas as pd
import config

LOG = logging.getLogger(__name__)
TABLE_COLUMNS = {
    "Doc_Header": "Doc_Id Doc_Date Tt_Id TSeries TNo Act_ID Mode Doc_Cancel Bill_Amt Bill_Qty Supp_Billno Supp_Billdate",
    "Stock_Delv": "DOC_ID IC_ID BILL_QTY BILL_FREE SRATE BL_VALUE BL_NETVAL Item_Cost CGSTAMT SGSTAMT IGSTAMT Vat_Rate stockconv cessAmt CCAMT",
    "Stock_Recd": "DOC_ID IC_ID BILL_QTY BILL_FREE IRATE BL_VALUE BL_NETVAL Act_ID CGSTAMT SGSTAMT IGSTAMT Vat_Rate stockconv cessAmt CCAMT",
    "Accmst": "Act_Id Act_Name Act_Type Act_MG Act_Cat",
    "AccAdr": "Act_Id GSTNO",
    "NAME_TRAN": "Doc_Id Act_Name Act_Town GSTNO",
    "Items": "ITEM_ID ITEM_NAME",
    "Item_Grp": "IC_ID ITEM_ID GRP_ID IssueConv HSNCode GST Sale_PACK",
    "Groups": "GRP_ID GRP_NAME",
    "TTYPES": "TT_ID",
    "DayBook": "Doc_ID Act_ID TRDATE AMOUNT TYPE",
}
_LOCAL = threading.local()
_WORKER = None
_WORKER_LOCK = threading.Lock()

def financial_year(dates):
    dates = pd.to_datetime(dates)
    year = dates.dt.year - (dates.dt.month < 4).astype(int)
    return year.astype(str) + "-" + ((year + 1) % 100).astype(str).str.zfill(2)

def fingerprint(path):
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}"

def read_access(path):
    import pyodbc
    from scripts.export_mdb import PASSWORD
    password = os.environ.get("THREEG_MDB_PASSWORD", PASSWORD)
    connection = pyodbc.connect(
        f"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={path};PWD={password};",
        readonly=True, timeout=15)
    try:
        tables = {}
        for name in TABLE_COLUMNS:
            cursor = connection.cursor().execute(f'SELECT * FROM [{name}]')
            tables[name] = pd.DataFrame.from_records(cursor.fetchall(), columns=[c[0] for c in cursor.description])
        return tables
    finally:
        connection.close()

def validate_tables(tables):
    for name, columns in TABLE_COLUMNS.items():
        if name not in tables:
            raise ValueError(f"Missing required table: {name}")
        missing = set(columns.split()) - set(tables[name].columns)
        if missing:
            raise ValueError(f"{name}: missing columns {', '.join(sorted(missing))}")
        # Validate before publishing so a malformed annual file cannot replace
        # the last good cache and break pages or truncate their join keys.
        for col in set(columns.split()) & {"Doc_Id", "DOC_ID", "Doc_ID", "Act_Id", "Act_ID", "IC_ID", "ITEM_ID", "GRP_ID", "Tt_Id", "TT_ID", "TNo", "Mode", "Doc_Cancel"}:
            values = pd.to_numeric(tables[name][col], errors="raise").fillna(0)
            if (values.abs() > 2 ** 31 - 1).any() or (values % 1 != 0).any():
                raise ValueError(f"{name}: invalid Access Long identifier in {col}")
        for col in set(columns.split()) & {"Bill_Amt", "Bill_Qty", "BILL_QTY", "BILL_FREE", "SRATE", "IRATE", "BL_VALUE", "BL_NETVAL", "Item_Cost", "CGSTAMT", "SGSTAMT", "IGSTAMT", "Vat_Rate", "stockconv", "cessAmt", "CCAMT", "IssueConv", "GST", "AMOUNT"}:
            values = pd.to_numeric(tables[name][col], errors="raise").fillna(0)
            if not np.isfinite(values).all():
                raise ValueError(f"{name}: non-finite number in {col}")
    h = tables["Doc_Header"]
    if h.empty:
        raise ValueError("Database has no document headers")
    dates = pd.to_datetime(h.Doc_Date, errors="raise")
    if dates.isna().any():
        raise ValueError("Missing document date")
    for name, key in [("Doc_Header", "Doc_Id"), ("Accmst", "Act_Id"), ("AccAdr", "Act_Id"),
                      ("NAME_TRAN", "Doc_Id"), ("Items", "ITEM_ID"), ("Item_Grp", "IC_ID"), ("Groups", "GRP_ID")]:
        if tables[name][key].isna().any() or tables[name][key].duplicated().any():
            raise ValueError(f"{name}: missing/duplicate {key}")
    for name in ["Stock_Delv", "Stock_Recd"]:
        if not tables[name].DOC_ID.isin(h.Doc_Id).all():
            raise ValueError(f"{name}: document reference not found")
        if not tables[name].IC_ID.isin(tables["Item_Grp"].IC_ID).all():
            raise ValueError(f"{name}: item reference not found")
    for key, parent, parent_key in [("ITEM_ID", "Items", "ITEM_ID"), ("GRP_ID", "Groups", "GRP_ID")]:
        if not tables["Item_Grp"][key].isin(tables[parent][parent_key]).all():
            raise ValueError(f"Item_Grp: {parent} reference not found")
    business_dates = dates[h.Tt_Id != 0]
    if business_dates.empty:
        raise ValueError("No dated business transactions to identify the financial year")
    return sorted(financial_year(business_dates).unique().tolist())

def _quote(name):
    return '"' + name.replace('"', '""') + '"'

def _cell(value):
    if pd.isna(value):
        return None
    if isinstance(value, (dt.datetime, dt.date, pd.Timestamp)):
        return value.isoformat()
    return value.item() if hasattr(value, "item") else value

class DatabaseSync:
    def __init__(self, directory, cache, reader=read_access, stable_seconds=2):
        self.directory, self.cache = Path(directory), Path(cache)
        self.reader, self.stable_seconds = reader, stable_seconds
        self.status = {}
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stopped = threading.Event()
        self._skipped = {}

    def _connect(self):
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.cache, timeout=15)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE IF NOT EXISTS _sources (source_index INTEGER PRIMARY KEY, name TEXT UNIQUE, fingerprint TEXT, sha256 TEXT, years TEXT, loaded_at TEXT)")
        connection.execute("CREATE TABLE IF NOT EXISTS _meta (revision INTEGER)")
        connection.execute("CREATE TABLE IF NOT EXISTS _source_ids (name TEXT PRIMARY KEY, source_index INTEGER UNIQUE)")
        if not connection.execute("SELECT count(*) FROM _meta").fetchone()[0]:
            connection.execute("INSERT INTO _meta VALUES (0)")
        connection.commit()
        return connection

    def _publish(self, connection, path, stamp, digest, years, tables):
        connection.execute("BEGIN IMMEDIATE")
        try:
            current = connection.execute("SELECT source_index, fingerprint FROM _sources WHERE name=?", (path.name.casefold(),)).fetchone()
            if current and current[1] == stamp:
                connection.rollback()
                return
            for other_name, other_years in connection.execute("SELECT name, years FROM _sources WHERE name != ?", (path.name.casefold(),)):
                if set(json.loads(other_years)) & set(years):
                    raise ValueError(f"Financial year overlaps {other_name}; keep one primary database per financial year")
            registered = connection.execute("SELECT source_index FROM _source_ids WHERE name=?", (path.name.casefold(),)).fetchone()
            index = current[0] if current else registered[0] if registered else connection.execute("SELECT COALESCE(MAX(source_index), -1)+1 FROM _source_ids").fetchone()[0]
            connection.execute("INSERT OR IGNORE INTO _source_ids VALUES (?,?)", (path.name.casefold(), index))
            for name, frame in tables.items():
                frame = frame.copy()
                frame["source_database"] = path.name
                frame["source_index"] = index
                columns = list(frame.columns)
                definition = ', '.join(f'{_quote(c)} ' + ("REAL" if pd.api.types.is_numeric_dtype(frame[c]) else "TEXT") for c in columns)
                connection.execute(f"CREATE TABLE IF NOT EXISTS {_quote(name)} ({definition})")
                known = {r[1] for r in connection.execute(f"PRAGMA table_info({_quote(name)})")}
                for col in set(columns) - known:
                    connection.execute(f"ALTER TABLE {_quote(name)} ADD COLUMN {_quote(col)}")
                connection.execute(f"DELETE FROM {_quote(name)} WHERE source_index=?", (index,))
                sql = f"INSERT INTO {_quote(name)} ({', '.join(map(_quote, columns))}) VALUES ({','.join('?' for _ in columns)})"
                connection.executemany(sql, (tuple(_cell(v) for v in row) for row in frame.itertuples(index=False, name=None)))
            connection.execute("INSERT OR REPLACE INTO _sources VALUES (?,?,?,?,?,?)", (index, path.name.casefold(), stamp, digest, json.dumps(years), dt.datetime.now(dt.timezone.utc).isoformat()))
            connection.execute("UPDATE _meta SET revision=revision+1")
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    def sync_once(self):
        with self._lock:
            paths = sorted((p for p in self.directory.glob('*') if p.suffix.lower() == '.mdb'), key=lambda p: p.name.casefold())
            if not paths and not self.cache.exists():
                return
            with closing(self._connect()) as connection:
                known = {r[0]: (r[1], r[2]) for r in connection.execute("SELECT name, fingerprint, sha256 FROM _sources")}
                removed = set(known) - {p.name.casefold() for p in paths}
                if removed:
                    connection.execute("BEGIN IMMEDIATE")
                    for name in removed:
                        index = connection.execute("SELECT source_index FROM _sources WHERE name=?", (name,)).fetchone()[0]
                        for table in TABLE_COLUMNS:
                            connection.execute(f"DELETE FROM {_quote(table)} WHERE source_index=?", (index,))
                        connection.execute("DELETE FROM _sources WHERE name=?", (name,))
                        del known[name]
                        self.status.pop(name, None)
                    connection.execute("UPDATE _meta SET revision=revision+1")
                    connection.commit()
                for path in paths:
                    name, stamp = path.name.casefold(), fingerprint(path)
                    if name in known and known[name][0] == stamp:
                        self.status[name] = "Ready"
                        continue
                    if time.time() - path.stat().st_mtime < self.stable_seconds:
                        self.status[name] = "Waiting for file copy to finish"
                        continue
                    if self._skipped.get(name, (None,))[0] == stamp:
                        self.status[name] = self._skipped[name][1]
                        continue
                    self.status[name] = "Importing"
                    try:
                        with path.open('rb') as stream:
                            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                        duplicate = next((other for other, (_, sha) in known.items() if sha == digest and other != name), None)
                        if duplicate:
                            self.status[name] = f"Ignored identical copy of {duplicate}"
                            self._skipped[name] = (stamp, self.status[name])
                            continue
                        if name in known and known[name][1] == digest:
                            connection.execute("UPDATE _sources SET fingerprint=? WHERE name=?", (stamp, name))
                            connection.commit()
                            self.status[name] = "Ready"
                            continue
                        tables = self.reader(path)
                        years = validate_tables(tables)
                        if fingerprint(path) != stamp:
                            raise ValueError("File changed during import; will retry after copying finishes")
                        self._publish(connection, path, stamp, digest, years, tables)
                        known[name] = (stamp, digest)
                        self.status[name] = "Ready"
                    except Exception as error:
                        self.status[name] = f"Import failed: {error}"
                        LOG.warning("Database import failed for %s: %s", path.name, error)

    def run(self):
        while not self._stopped.is_set():
            try:
                self.sync_once()
            except Exception as error:
                self.status["importer"] = f"Import failed: {error}"
                LOG.exception("Database scan failed")
            self._wake.wait(config.IMPORT_POLL_SECONDS)
            self._wake.clear()

    def request_scan(self):
        self._wake.set()

    def stop(self):
        self._stopped.set()
        self._wake.set()

def start():
    global _WORKER
    if os.environ.get("THREEG_AUTO_IMPORT", "1") == "0":
        return None
    with _WORKER_LOCK:
        if _WORKER is None:
            _WORKER = DatabaseSync(config.DATABASE_DIR, config.IMPORT_CACHE)
            threading.Thread(target=_WORKER.run, name="mdb-import", daemon=True).start()
    return _WORKER

def revision():
    snapshot = getattr(_LOCAL, "connection", None)
    if snapshot is not None:
        return _LOCAL.revision
    if not config.IMPORT_CACHE.exists():
        # No SQLite cache (e.g. Streamlit Cloud, CSV-only mode).
        # Use modification times of key CSV files as a revision signal so that
        # pushing new CSVs to GitHub causes the data cache to reload automatically.
        try:
            key_files = ["Doc_Header.csv", "Stock_Delv.csv", "Stock_Recd.csv", "DayBook.csv"]
            sig = ":".join(str(int((config.DATA_DIR / f).stat().st_mtime_ns))
                           for f in key_files if (config.DATA_DIR / f).exists())
            return int(hashlib.md5(sig.encode()).hexdigest(), 16)
        except Exception:
            return 0
    try:
        with closing(sqlite3.connect(config.IMPORT_CACHE, timeout=2)) as connection:
            return connection.execute("SELECT revision FROM _meta").fetchone()[0]
    except sqlite3.Error:
        return 0

@contextmanager
def read_snapshot():
    connection = None
    try:
        if config.IMPORT_CACHE.exists():
            connection = sqlite3.connect(config.IMPORT_CACHE, timeout=5)
            connection.execute("BEGIN")
            try:
                current = connection.execute("SELECT revision FROM _meta").fetchone()[0]
            except sqlite3.Error:
                current = 0
            _LOCAL.connection, _LOCAL.revision = connection, current
        yield
    finally:
        _LOCAL.connection = None
        if connection is not None:
            connection.close()

def read_table(filename, **kwargs):
    if revision() == 0:
        frame = pd.read_csv(config.DATA_DIR / filename, encoding="utf-8-sig", low_memory=False, **kwargs)
        sources = sorted(config.DATABASE_DIR.glob("*.mdb"))
        frame["source_database"] = sources[0].name if len(sources) == 1 else "legacy_csv"
        frame["source_index"] = 0
        return frame
    connection = getattr(_LOCAL, "connection", None)
    own_connection = connection is None
    if own_connection:
        connection = sqlite3.connect(config.IMPORT_CACHE, timeout=5)
    try:
        columns = kwargs.get("usecols")
        selection = ", ".join(map(_quote, list(columns) + ["source_database", "source_index"])) if columns is not None else "*"
        frame = pd.read_sql_query(f"SELECT {selection} FROM {_quote(Path(filename).stem)}", connection)
    finally:
        if own_connection:
            connection.close()
    for col, dtype in kwargs.get("dtype", {}).items():
        if col in frame:
            frame[col] = frame[col].astype(dtype)
    for col in kwargs.get("parse_dates") or []:
        frame[col] = pd.to_datetime(frame[col])
    return frame