"""Run the full pipeline for Gate 4 live delivery verification."""
import json
import os
import sys

os.environ["NEWSROOM_REPORT_MODE"] = "manual"
os.environ["NEWSROOM_JOB_ID"] = "gate4_live_delivery"

from newsroom.pipeline.runner import run_pipeline

result = run_pipeline()

# Write result to file
with open("pipeline_result.json", "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2, ensure_ascii=False, default=str)

print(f"Pipeline exit code: {result.get('exit_code')}", file=sys.stderr)
print(f"Status: {result.get('status')}", file=sys.stderr)
print(f"Report ID: {result.get('report_id')}", file=sys.stderr)
print(f"Delivery ID: {result.get('delivery_id')}", file=sys.stderr)
print(f"Stages: {len(result.get('stages', []))}", file=sys.stderr)
for s in result.get("stages", []):
    print(f"  {s['name']}: {s['status']} {s.get('detail', '')}", file=sys.stderr)
