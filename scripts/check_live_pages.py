"""Exercise all routes through the running server's Streamlit WebSocket.

This verifies server execution and delivered widgets, not browser layout.
"""
import argparse
import datetime as dt
import io
import json
from pathlib import Path
import sqlite3
import sys
import time
import urllib.request

import pandas as pd
import pyarrow.ipc
from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8503)
    parser.add_argument("--output", default="all_pages_live_results.json")
    args = parser.parse_args()
    base = f"http://127.0.0.1:{args.port}"
    with sqlite3.connect(f"file:{config.IMPORT_CACHE.as_posix()}?mode=ro", uri=True) as connection:
        headers = pd.read_sql_query('SELECT Doc_Date, Tt_Id, Doc_Cancel FROM Doc_Header', connection)
    dates = pd.to_datetime(headers.Doc_Date)
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30))).date()
    year = today.year - (today.month < 4)
    current = headers.Tt_Id.ne(0) & headers.Doc_Cancel.eq(0) & dates.between(f"{year}-04-01", f"{year + 1}-03-31")
    latest = dates[current].max().date() if current.any() else today
    operational_defaults = [latest.isoformat()] * 2
    analytics_defaults = [dates.min().date().isoformat(), dates.max().date().isoformat()]
    with urllib.request.urlopen(base + "/_stcore/health", timeout=10) as response:
        assert response.read() == b"ok"
    results, buttons, script_hash = {}, {}, ""
    with connect(base.replace("http", "ws") + "/_stcore/stream", origin=base,
                 subprotocols=["streamlit"], open_timeout=15, max_size=30_000_000) as ws:
        def run(name, key=None):
            nonlocal script_hash, buttons
            request = BackMsg()
            request.rerun_script.page_script_hash = script_hash
            if key:
                state = request.rerun_script.widget_states.widgets.add()
                state.id = buttons[key]
                state.trigger_value = True
            started = time.perf_counter()
            ws.send(request.SerializeToString())
            found, dates, metrics, rows = {}, [], [], []
            while True:
                msg = ForwardMsg()
                msg.ParseFromString(ws.recv(timeout=90))
                kind = msg.WhichOneof("type")
                if kind == "new_session":
                    script_hash = msg.new_session.page_script_hash
                if kind == "delta" and msg.delta.WhichOneof("type") == "new_element":
                    e = msg.delta.new_element
                    typ = e.WhichOneof("type")
                    if typ == "exception":
                        raise RuntimeError(f"{name}: {e.exception.message}")
                    if typ == "button":
                        found[e.button.id.rsplit("-", 1)[-1]] = e.button.id
                    elif typ == "date_input":
                        dates.extend(e.date_input.default)
                    elif typ == "metric":
                        metrics.append({"label": e.metric.label, "value": e.metric.body})
                    elif typ == "dataframe":
                        frame = pyarrow.ipc.open_stream(io.BytesIO(e.dataframe.arrow_data.data)).read_all()
                        rows.append(frame.num_rows)
                if kind == "script_finished" and msg.script_finished != ForwardMsg.FINISHED_EARLY_FOR_RERUN:
                    buttons = found
                    assert len(dates) == 2, (name, dates)
                    full_fy = name.startswith(("sales_", "purch_")) and not name.endswith("_billwise")
                    expected = analytics_defaults if name.startswith("analytics_") else ([f"{year}-04-01", latest.isoformat()] if full_fy else operational_defaults)
                    assert dates == expected, (name, dates, expected)
                    results[name] = dict(seconds=round(time.perf_counter() - started, 3), dates=dates, metrics=metrics, table_rows=rows)
                    print(name, results[name]["seconds"], "seconds", flush=True)
                    return
        run("home")
        routes = [key for key in buttons if key.startswith("b_")]
        assert len(routes) == 22
        for key in routes:
            page = key[2:]
            run(page, key)
            home = next(k for k in buttons if k.startswith("h_"))
            run("home", home)
    result = {"checked_at": dt.datetime.now(dt.timezone.utc).isoformat(), "url": base,
              "routes_passed": len(results), "pages": results}
    Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=True), encoding="utf-8")


if __name__ == "__main__":
    main()
