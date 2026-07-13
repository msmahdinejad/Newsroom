import os, time, faulthandler, sys
faulthandler.enable()
sys.stdout.reconfigure(line_buffering=True)
start = time.monotonic()
print(f"[{time.monotonic()-start:.3f}s] PID {os.getpid()}", flush=True)
from newsroom.storage.database import engine
from sqlalchemy import text
print(f"[{time.monotonic()-start:.3f}s] Connecting", flush=True)
conn = engine.connect()
print(f"[{time.monotonic()-start:.3f}s] Querying", flush=True)
result = conn.execute(text('SELECT 1'))
print(f"[{time.monotonic()-start:.3f}s] Result: {result.scalar()}", flush=True)
conn.close()
print(f"[{time.monotonic()-start:.3f}s] OK", flush=True)
