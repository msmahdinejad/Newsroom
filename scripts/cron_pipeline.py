#!/usr/bin/env python3
"""Newsroom scheduled pipeline — V2 cron entry point (Hermes secondary).

Invokes the same authoritative runner as Docker scheduler / CLI / bot:
  newsroom.pipeline.runner (via scripts/run_pipeline.py).
Empty stdout = silent. Non-empty = delivered verbatim.
"""
import json
import os
import subprocess
import sys

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> None:
    result = subprocess.run(
        [sys.executable, os.path.join(PROJECT_DIR, "scripts", "run_pipeline.py")],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=PROJECT_DIR,
        env={**os.environ, "NEWSROOM_JOB_ID": "hermes_cron"},
    )
    if result.returncode == 2:
        # busy lock — silent for watchdog
        return
    if result.returncode != 0:
        print(f"[ERROR] Pipeline failed: {(result.stderr or result.stdout)[:300]}")
        return

    for line in result.stdout.strip().split("\n"):
        if line.strip().startswith("{") and '"status"' in line:
            try:
                data = json.loads(line.strip())
            except json.JSONDecodeError:
                continue
            if data.get("status") in ("ok_empty", "busy"):
                return
            if data.get("status") == "ok":
                rid = data.get("report_id")
                if not rid:
                    return
                sys.path.insert(0, os.path.join(PROJECT_DIR, "src"))
                from sqlalchemy.orm import Session

                from newsroom.storage.database import engine
                from newsroom.storage.models import Report

                s = Session(engine)
                try:
                    r = s.query(Report).filter_by(id=rid).first()
                    if r and r.content_fa:
                        print(r.content_fa)
                finally:
                    s.close()
                return


if __name__ == "__main__":
    main()
