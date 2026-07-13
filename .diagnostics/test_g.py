import os, time, faulthandler, sys
faulthandler.enable()
sys.stdout.reconfigure(line_buffering=True)
start = time.monotonic()
print(f"[{time.monotonic()-start:.3f}s] PID {os.getpid()}", flush=True)
print(f"[{time.monotonic()-start:.3f}s] Importing database module", flush=True)
from newsroom.storage import database
print(f"[{time.monotonic()-start:.3f}s] Module imported", flush=True)
print(f"[{time.monotonic()-start:.3f}s] Engine: {database.engine}", flush=True)
