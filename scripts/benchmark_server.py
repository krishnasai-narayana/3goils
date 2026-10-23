"""Time the running server over its real Streamlit WebSocket (no browser required)."""
import argparse
import json
import time
from pathlib import Path

from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
from websockets.sync.client import connect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8502)
    parser.add_argument("--output", default="performance_server_before.json")
    args = parser.parse_args()
    results = {}
    buttons = {}
    script_hash = ""
    with connect(f"ws://127.0.0.1:{args.port}/_stcore/stream", subprotocols=["streamlit"], open_timeout=15, max_size=30_000_000) as ws:
        def run(name, button=None):
            nonlocal script_hash
            request = BackMsg()
            request.rerun_script.page_script_hash = script_hash
            if button:
                widget = request.rerun_script.widget_states.widgets.add()
                widget.id = buttons[button]
                widget.trigger_value = True
            start = time.perf_counter()
            ws.send(request.SerializeToString())
            size = 0
            while True:
                raw = ws.recv(timeout=60)
                size += len(raw)
                msg = ForwardMsg()
                msg.ParseFromString(raw)
                kind = msg.WhichOneof("type")
                if kind == "new_session":
                    script_hash = msg.new_session.page_script_hash
                if kind == "delta" and msg.delta.WhichOneof("type") == "new_element":
                    element = msg.delta.new_element
                    if element.WhichOneof("type") == "button":
                        widget_id = element.button.id
                        buttons[widget_id.rsplit("-", 1)[-1]] = widget_id
                    if element.WhichOneof("type") == "exception":
                        raise RuntimeError(element.exception.message)
                if kind == "script_finished" and msg.script_finished != ForwardMsg.FINISHED_EARLY_FOR_RERUN:
                    results[name] = {"seconds": round(time.perf_counter() - start, 4), "bytes_received": size}
                    print(name, results[name], flush=True)
                    break
        run("home")
        run("sales_first_navigation", "b_sales_billwise")
        for n in range(3):
            run(f"sales_warm_{n + 1}")
        run("return_home", "h_sbw")
        run("sales_repeat_navigation", "b_sales_billwise")
    Path(args.output).write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
