import os, time
start = time.monotonic()
print(f"[{time.monotonic()-start:.3f}s] Python PID {os.getpid()}")
