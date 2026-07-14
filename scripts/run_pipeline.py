#!/usr/bin/env python3
"""Newsroom pipeline runner — canonical scheduled execution path.

Runs: collect → normalize → dedupe → cluster → evidence → report → deliver.
All output is structured JSON for observability.
"""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def run_pipeline() -> dict:
    """Run the full newsroom pipeline."""
    result = {
        "job_id": os.environ.get("NEWSROOM_JOB_ID", "manual"),
        "report_mode": os.environ.get("NEWSROOM_REPORT_MODE", "scheduled"),
        "schedule_label": os.environ.get("NEWSROOM_SCHEDULE_LABEL", ""),
        "start_time": datetime.now(timezone.utc).isoformat(),
        "stages": [],
        "status": "running",
        "report_id": None,
        "delivery_id": None,
        "error": None,
    }

    def stage(name: str, status: str, detail: str = "") -> None:
        entry = {"name": name, "status": status, "detail": detail}
        result["stages"].append(entry)
        print(json.dumps({"stage": name, "status": status, "detail": detail}, ensure_ascii=False))
        sys.stdout.flush()

    try:
        # Stage 1: Database check
        stage("database", "starting")
        from sqlalchemy import text as sa_text
        from sqlalchemy.orm import Session

        from newsroom.storage.database import engine
        with engine.connect() as conn:
            conn.execute(sa_text("SELECT 1"))
        stage("database", "ok")

        # Stage 2: Collect
        stage("collect", "starting")
        import asyncio

        from newsroom.sources.github import GitHubCollector
        from newsroom.sources.rss import RSSCollector
        from newsroom.storage.models import RawItem, Source

        session = Session(engine)
        sources = session.query(Source).filter_by(enabled=True).all()
        stage("collect", "sources_found", f"{len(sources)} sources")

        rss = RSSCollector()
        gh = GitHubCollector()
        total_collected = 0

        async def collect_all():
            nonlocal total_collected
            for source in sources:
                try:
                    if source.type == "rss":
                        items = await rss.collect(source)
                    elif source.type == "github_releases":
                        items = await gh.collect(source)
                    else:
                        continue

                    for item in items[:10]:
                        import hashlib
                        item_url = item.get("link") or item.get("html_url") or ""
                        raw_hash = hashlib.sha256(
                            (item_url + item.get("title", "")).encode()
                        ).hexdigest()

                        existing = session.query(RawItem).filter(
                            RawItem.source_id == source.id,
                            RawItem.content_hash == raw_hash,
                        ).first()
                        if existing:
                            continue

                        raw = RawItem(
                            source_id=source.id,
                            raw_data=item,
                            content_hash=raw_hash,
                        )
                        session.add(raw)
                        total_collected += 1

                    source.last_success_at = datetime.now(timezone.utc)
                    source.consecutive_failures = 0
                    source.health_status = "healthy"
                except Exception as e:
                    source.last_error_at = datetime.now(timezone.utc)
                    source.last_error = str(e)[:500]
                    source.consecutive_failures += 1
                    if source.consecutive_failures >= 3:
                        source.health_status = "degraded"
                    stage("collect", "source_error", f"{source.name}: {str(e)[:100]}")

            await rss.close()
            await gh.close()

        asyncio.run(collect_all())

        session.commit()
        stage("collect", "ok", f"{total_collected} items collected")

        # Stage 3: Normalize
        stage("normalize", "starting")
        from newsroom.processing.normalize import Normalizer
        from newsroom.storage.models import NormalizedItem

        normalizer = Normalizer()
        raw_items = session.query(RawItem).filter(
            ~RawItem.id.in_(session.query(NormalizedItem.raw_item_id))
        ).all()

        normalized_count = 0
        for raw in raw_items:
            try:
                norm_data = normalizer.normalize(raw.raw_data)
                norm = NormalizedItem(
                    raw_item_id=raw.id,
                    title=norm_data["title"][:500],
                    description=norm_data.get("description", "")[:2000],
                    source_url=norm_data["source_url"],
                    canonical_url=norm_data.get("canonical_url", ""),
                    published_at=norm_data.get("published_at"),
                    language=norm_data.get("language"),
                    content_hash=norm_data["content_hash"],
                    url_hash=norm_data.get("url_hash", ""),
                )
                session.add(norm)
                normalized_count += 1
            except Exception as e:
                stage("normalize", "item_error", f"raw {raw.id}: {str(e)[:80]}")

        session.commit()
        stage("normalize", "ok", f"{normalized_count} items normalized")

        # Stage 4: Deduplicate
        stage("dedupe", "starting")
        from newsroom.processing.dedupe import Deduplicator

        deduper = Deduplicator()
        non_dup = session.query(NormalizedItem).filter(
            NormalizedItem.is_duplicate == False  # noqa: E712
        ).all()
        if non_dup:
            dedup_stats = deduper.deduplicate_batch(session, [i.id for i in non_dup])
            session.commit()
            stage("dedupe", "ok", f"{dedup_stats}")
        else:
            stage("dedupe", "ok", "no items")

        # Stage 5: Cluster
        stage("cluster", "starting")
        from newsroom.processing.cluster import Clusterer

        clusterer = Clusterer()
        non_dup = session.query(NormalizedItem).filter(
            NormalizedItem.is_duplicate == False  # noqa: E712
        ).all()
        if non_dup:
            cluster_stats = clusterer.cluster_items(session, [i.id for i in non_dup])
            session.commit()
            stage("cluster", "ok", f"{cluster_stats}")
        else:
            stage("cluster", "ok", "no items")

        # Stage 6: Evidence
        stage("evidence", "starting")
        from newsroom.processing.evidence import EvidenceBuilder
        from newsroom.storage.models import Story

        evidence_builder = EvidenceBuilder()
        stories = session.query(Story).order_by(Story.created_at.desc()).limit(30).all()
        if stories:
            ev_stats = evidence_builder.build_for_stories(session, [s.id for s in stories])
            session.commit()
            stage("evidence", "ok", f"{ev_stats}")
        else:
            stage("evidence", "skipped", "no stories")

        # Stage 7: Report generation
        stage("report", "starting")
        story_ids = [s.id for s in stories] if stories else []
        report_mode = result["report_mode"]

        if not story_ids:
            stage("report", "skipped", "no stories")
            result["status"] = "ok_empty"
            result["finish_time"] = datetime.now(timezone.utc).isoformat()
            session.close()
            print(json.dumps(result, ensure_ascii=False))
            return result

        from newsroom.editorial.persian import PersianEditorial

        editorial = PersianEditorial()
        report_id = editorial.generate_report(session, story_ids, report_mode=report_mode)
        session.commit()
        result["report_id"] = report_id
        stage("report", "ok", f"report {report_id}")

        # Stage 8: Deliver
        stage("deliver", "starting")
        from newsroom.config import settings as cfg
        from newsroom.delivery.telegram import TelegramDelivery

        td = TelegramDelivery()
        if td.configured:
            delivery_id = asyncio.run(td.deliver_report(session, report_id))
            asyncio.run(td.close())
            if delivery_id:
                result["delivery_id"] = delivery_id
                stage("deliver", "ok", f"delivery {delivery_id}")
            else:
                stage("deliver", "failed", "delivery returned None")
        else:
            stage("deliver", "skipped", "Telegram not configured")

        result["status"] = "ok"
        result["finish_time"] = datetime.now(timezone.utc).isoformat()
        session.close()

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)[:500]
        result["finish_time"] = datetime.now(timezone.utc).isoformat()
        stage("pipeline", "error", str(e)[:200])

    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    run_pipeline()
