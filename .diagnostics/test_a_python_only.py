#!/usr/bin/env python3
"""Test A: Python startup only."""
import sys
import time
start = time.monotonic()
print(f"[{time.monotonic()-start:.3f}s] Python started, PID {sys.getpid()}")
sys.exit(0)
