"""Verify the Gate 5 live report and its Telegram delivery."""
import sys

from sqlalchemy.orm import sessionmaker

from newsroom.storage.database import engine
from newsroom.storage.models import Delivery, Report


def main() -> int:
    factory = sessionmaker(bind=engine)
    with factory() as db:
        r = db.query(Report).filter_by(id=364).first()
        if r is None:
            print("report 364 not found")
            return 1
        out = []
        out.append(f"report id: {r.id}")
        out.append(f"mode: {r.report_mode}")
        out.append(f"method: {r.generation_method}")
        content = (r.content_fa or "")[:500]
        out.append(f"content (first 500 chars):\n{content}")
        out.append(f"story_ids: {r.story_ids}")
        td = db.query(Delivery).filter_by(report_id=364).first()
        if td:
            out.append(f"delivery id: {td.id}")
            out.append(f"delivery status: {td.status}")
            out.append(f"delivery message_ids: {td.message_ids}")
            out.append(f"delivery chunks: {td.delivered_chunks}/{td.total_chunks}")
        else:
            out.append("no delivery row")
        sys.stdout.buffer.write(("\n".join(out) + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
