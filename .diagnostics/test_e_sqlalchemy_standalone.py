#!/usr/bin/env python3
"""Test E: Standalone SQLAlchemy connection."""
import sys, time, faulthandler
faulthandler.enable()
start = time.monotonic()

print(f"[{time.monotonic()-start:.3f}s] Python PID {sys.getpid()}", flush=True)

print(f"[{time.monotonic()-start:.3f}s] Importing SQLAlchemy...", flush=True)
from sqlalchemy import create_engine, pool, text

print(f"[{time.monotonic()-start:.3f}s] Creating engine...", flush=True)
engine = create_engine(
    'postgresql+psycopg://newsroom:newsroom_dev@127.0.0.1:55432/newsroom',
    poolclass=pool.NullPool,
    connect_args={'connect_timeout': 5}
)

print(f"[{time.monotonic()-start:.3f}s] Connecting...", flush=True)
with engine.connect() as conn:
    print(f"[{time.monotonic()-start:.3f}s] Executing SELECT 1...", flush=True)
    result = conn.execute(text('SELECT 1'))
    val = result.scalar()
    print(f"[{time.monotonic()-start:.3f}s] Result: {val}", flush=True)

print(f"[{time.monotonic()-start:.3f}s] SUCCESS", flush=True)
