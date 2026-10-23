"""Measure actual Streamlit navigation and bill filters, preserving a JSON record.

Usage: python scripts/benchmark_app.py --output performance_before.json
"""
import argparse
import json
import sys
import time
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="performance_after.json")
    args = parser.parse_args()
    started = time.perf_counter()
    from streamlit.testing.v1 import AppTest
    import pandas as pd

    # Profile the script thread, rather than AppTest's waiting thread.
    prefix = "import cProfile as _cp\n_p = _cp.Profile()\n_p.enable()\ntry:\n"
    suffix = "\nfinally:\n    _p.disable()\n    st.session_state['_profile'] = sorted([(e.code.co_filename, e.code.co_name, e.totaltime, e.callcount) for e in _p.getstats() if hasattr(e.code, 'co_filename')], key=lambda e: e[2], reverse=True)[:25]\n"
    at = AppTest.from_string(prefix + textwrap.indent((ROOT / "app.py").read_text(encoding="utf-8"), "    ") + suffix, default_timeout=60)
    results = {"test_runtime_import_seconds": round(time.perf_counter() - started, 4), "timings": {}, "profiles": {}}

    def measure(name, action):
        start = time.perf_counter()
        action()
        elapsed = time.perf_counter() - start
        if at.exception:
            raise RuntimeError([e.message for e in at.exception])
        results["timings"][name] = round(elapsed, 4)
        results["profiles"][name] = at.session_state['_profile']
        (ROOT / args.output).write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"{name}: {elapsed:.4f}s", flush=True)

    measure("home_cold", lambda: at.run())
    measure("sales_first_navigation", lambda: at.button(key="b_sales_billwise").click().run())
    for n in range(3):
        measure(f"sales_warm_{n + 1}", lambda: at.run())
    from reporting import fiscal_bounds, today
    measure("sales_full_range", lambda: at.date_input(key="sbw_f").set_value(fiscal_bounds(today())[0]).run())
    results["full_range_displayed_rows"] = len(at.dataframe[0].value)
    results["full_range_total_rows"] = int(at.metric[1].value.replace(",", ""))
    results["full_range_bill_options"] = len(at.multiselect(key="sbw_b").options)
    results["full_range_customer_options"] = len(at.multiselect(key="sbw_c").options)
    measure("sales_full_range_warm", lambda: at.run())
    measure("sales_bill_filter", lambda: at.multiselect(key="sbw_b").select("3GST-7425").run())
    results["filtered_rows"] = len(at.dataframe[0].value)
    measure("return_home", lambda: at.button(key="h_sbw").click().run())
    measure("sales_repeat_navigation", lambda: at.button(key="b_sales_billwise").click().run())
    output = ROOT / args.output
    output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Saved {output}", flush=True)


if __name__ == "__main__":
    main()
