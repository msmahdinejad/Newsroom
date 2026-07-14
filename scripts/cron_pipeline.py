#!/usr/bin/env python3
"""Newsroom scheduled pipeline — V2 cron entry point.

Calls the canonical run_pipeline.py which handles collect→deliver.
V2 pipeline does its own Telegram delivery via Bot API.
Empty stdout = silent. Non-empty = delivered verbatim.
"""
import json, os, subprocess, sys

PROJECT_DIR = r"[REDACTED]\OneDrive\Desktop\newsroom"

def main():
    result = subprocess.run(
        [sys.executable, os.path.join(PROJECT_DIR, "scripts", "run_pipeline.py")],
        capture_output=True, text=True, timeout=300, cwd=PROJECT_DIR,
        env={**os.environ, "NEWSROOM_JOB_ID": "scheduled"},
    )
    if result.returncode != 0:
        print(f"[ERROR] Pipeline failed: {result.stderr[:300]}")
        return

    for line in result.stdout.strip().split("\n"):
        if line.strip().startswith("{") and '"status"' in line:
            try:
                data = json.loads(line.strip())
                if data.get("status") == "ok_empty":
                    return  # silent
                if data.get("status") == "ok":
                    rid = data.get("report_id")
                    did = data.get("delivery_id")
                    if did:
                        # Pipeline delivered via Bot API — return content for verbatim
                        sys.path.insert(0, os.path.join(PROJECT_DIR, "src"))
                        from newsroom.storage.database import engine
                        from newsroom.storage.models import Report
                        from sqlalchemy.orm import Session
                        s = Session(engine)
                        r = s.query(Report).filter_by(id=rid).first()
                        if r and r.content_fa:
                            print(r.content_fa)
                        s.close()
                        return
                    elif rid:
                        # Delivery skipped (no bot token) — return content anyway
                        sys.path.insert(0, os.path.join(PROJECT_DIR, "src"))
                        from newsroom.storage.database import engine
                        from newsroom.storage.models import Report
                        from sqlalchemy.orm import Session
                        s = Session(engine)
                        r = s.query(Report).filter_by(id=rid).first()
                        if r and r.content_fa:
                            print(r.content_fa)
                        s.close()
                        return
            except json.JSONDecodeError:
                pass

if __name__ == "__main__":
    main()
