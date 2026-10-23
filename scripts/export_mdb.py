"""Export all tables from 3G2026.mdb to CSV files in data/.

Run this when the .mdb database is updated with new transactions.
Requires Windows with Microsoft Access ODBC driver installed.

Usage:
    cd 3goils-streamlit
    python scripts/export_mdb.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MDB_PATH = ROOT / "database" / "3G2026.mdb"
OUTPUT_DIR = ROOT / "data"
PASSWORD = "sl4l77"

def main():
    try:
        import pyodbc
        import pandas as pd
    except ImportError:
        sys.exit(
            f"Required Python package is missing for {sys.executable}. "
            "Install it with: python -m pip install pyodbc pandas"
        )

    if not MDB_PATH.exists():
        sys.exit(f"Database not found: {MDB_PATH}")

    DRIVER = "Microsoft Access Driver (*.mdb, *.accdb)"
    if DRIVER not in pyodbc.drivers():
        sys.exit(f"ODBC driver not found: '{DRIVER}'")

    conn = pyodbc.connect(f"DRIVER={{{DRIVER}}};DBQ={MDB_PATH};PWD={PASSWORD};")
    cursor = conn.cursor()

    tables = [r.table_name for r in cursor.tables(tableType="TABLE")
              if not r.table_name.startswith("MSys")]
    print(f"Found {len(tables)} tables in {MDB_PATH.name}")

    OUTPUT_DIR.mkdir(exist_ok=True)
    ok, fail = 0, 0

    for t in tables:
        try:
            df = pd.read_sql(f"SELECT * FROM [{t}]", conn)
            target = OUTPUT_DIR / f"{t}.csv"
            temporary = target.with_suffix(".csv.tmp")
            df.to_csv(temporary, index=False, encoding="utf-8-sig")
            temporary.replace(target)
            ok += 1
            print(f"  {t}: {len(df)} rows")
        except Exception as e:
            fail += 1
            print(f"  {t}: FAILED - {e}")

    conn.close()
    print(f"\nDone. {ok} exported, {fail} failed. Output: {OUTPUT_DIR}")

    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
