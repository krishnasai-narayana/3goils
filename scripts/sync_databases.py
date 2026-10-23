"""Import new/changed annual Access files once; the app also does this automatically."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
from database_sync import DatabaseSync


if __name__ == "__main__":
    worker = DatabaseSync(config.DATABASE_DIR, config.IMPORT_CACHE)
    worker.sync_once()
    for name, status in worker.status.items():
        print(f"{name}: {status}", flush=True)
    sys.exit(1 if any(value.startswith("Import failed") for value in worker.status.values()) else 0)
