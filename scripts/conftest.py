import os

# Unit/UI tests control source imports explicitly; never start a production poller.
os.environ.setdefault("THREEG_AUTO_IMPORT", "0")
