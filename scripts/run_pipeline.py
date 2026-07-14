#!/usr/bin/env python3
"""Newsroom pipeline runner - canonical scheduled execution path.

This script is used by cron jobs and manual triggers.
It runs the full pipeline: collect -> normalize -> dedupe -> cluster -> digest -> deliver.
All output is structured JSON for observability.
"""

import json
import os
import sys
from datetime import UTC, datetime

# Ensure project is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))


def run_pipeline():
    """Run the full newsroom pipeline."""
    result = {
        "job_id": os.environ.get("NEWSROOM_JOB_ID", "manual"),
        "start_time": datetime.now(UTC).isoformat(),
        "stages": [],
        "status": "running",
        "report_id": None,
        "delivery_id": None,
        "error": None,
    }

    def stage(name, status, detail=""):
        result["stages"].append({"name": name, "status": status, "detail": detail})
        print(json.dumps({"stage": name, "status": status, "detail": detail}, ensure_ascii=False))
        sys.stdout.flush()

    try:
        # Stage 1: Verify database
        stage("database", "starting")
        from sqlalchemy import text as sa_text

        from newsroom.storage.database import engine
        with engine.connect() as conn:
            conn.execute(sa_text("SELECT 1"))
        stage("database", "ok")

        # Stage 2: Collect from enabled sources
        stage("collect", "starting")
        import asyncio

        from sqlalchemy.orm import Session

        from newsroom.sources.rss import RSSCollector
        from newsroom.storage.models import RawItem, Source

        session = Session(engine)
        sources = session.query(Source).filter_by(enabled=True).all()
        stage("collect", "sources_found", f"{len(sources)} sources")

        rss = RSSCollector()
        total_collected = 0

        async def collect_all():
            """Collect from all sources in a single event loop."""
            nonlocal total_collected
            for source in sources:
                try:
                    if source.type == "rss":
                        items = await rss.collect(source.url)
                    elif source.type == "github_releases":
                        from newsroom.sources.github import GitHubCollector as GC
                        gh_local = GC()
                        items = await gh_local.collect(source.url)
                        await gh_local.close()
                    else:
                        continue

                    for item in items[:5]:
                        item_url = item.get("link") or item.get("html_url") or ""
                        if item_url:
                            existing = session.query(RawItem).filter(
                                RawItem.source_id == source.id,
                                RawItem.raw_data.like(f"%{item_url}%")
                            ).first()
                            if existing:
                                continue

                        raw = RawItem(
                            source_id=source.id,
                            raw_data=json.dumps(item, default=str, ensure_ascii=False),
                        )
                        session.add(raw)
                        total_collected += 1

                    source.last_success_at = datetime.now(UTC)
                    source.consecutive_failures = 0
                except Exception as e:
                    source.last_error_at = datetime.now(UTC)
                    source.last_error = str(e)[:500]
                    source.consecutive_failures += 1
                    stage("collect", "source_error", f"{source.name}: {str(e)[:100]}")

        asyncio.run(collect_all())

        session.commit()
        stage("collect", "ok", f"{total_collected} items collected")

        # Stage 3: Normalize
        stage("normalize", "starting")
        from newsroom.storage.models import NormalizedItem

        raw_items = session.query(RawItem).filter(
            ~RawItem.id.in_(
                session.query(NormalizedItem.raw_item_id)
            )
        ).all()

        normalized_count = 0
        for raw in raw_items:
            try:
                data = json.loads(raw.raw_data)
                # RSS items have title/link, GitHub releases have name/html_url
                title = data.get("title") or data.get("name") or "Untitled"
                url = data.get("link") or data.get("html_url") or data.get("url") or ""
                desc = data.get("description") or data.get("body") or data.get("summary") or ""
                norm = NormalizedItem(
                    raw_item_id=raw.id,
                    title=title[:500],
                    description=desc[:1000],
                    source_url=url,
                    content_hash=str(hash(title + url)),
                    normalized_url=url,
                )
                session.add(norm)
                normalized_count += 1
            except Exception:
                pass

        session.commit()
        stage("normalize", "ok", f"{normalized_count} items normalized")

        # Stage 4: Cluster
        stage("cluster", "starting")
        from newsroom.processing.cluster import Clusterer
        clusterer = Clusterer()

        non_dup_items = session.query(NormalizedItem).filter(
            NormalizedItem.is_duplicate == False  # noqa: E712
        ).all()
        item_ids = [i.id for i in non_dup_items]

        if item_ids:
            stats = clusterer.cluster_items(item_ids)
            stage("cluster", "ok", f"{stats['stories_created']} stories")
        else:
            stage("cluster", "ok", "0 stories (no items)")

        # Stage 5: Generate digest
        stage("digest", "starting")
        from newsroom.storage.models import Digest, Story

        stories = session.query(Story).order_by(Story.created_at.desc()).limit(20).all()
        story_ids = [s.id for s in stories]

        if not story_ids:
            stage("digest", "skipped", "no stories")
            result["status"] = "ok_empty"
            result["finish_time"] = datetime.now(UTC).isoformat()
            session.close()
            print(json.dumps(result, ensure_ascii=False))
            return

        from newsroom.digest.preview import PreviewGenerator
        gen = PreviewGenerator()
        digest_id = gen.create_digest(story_ids)
        result["report_id"] = digest_id
        stage("digest", "ok", f"digest {digest_id}")

        # Stage 6: Deliver via Hermes CLI
        stage("deliver", "starting")
        import subprocess

        digest = session.query(Digest).filter_by(id=digest_id).first()
        content = digest.content_fa if digest else ""

        if content and len(content) > 10:
            # Use hermes send CLI
            proc = subprocess.run(
                ["hermes", "send", "--to", "telegram", content],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode == 0:
                digest.delivered = True
                digest.delivered_at = datetime.now(UTC)
                session.commit()
                result["delivery_id"] = digest_id
                stage("deliver", "ok", f"delivered digest {digest_id}")
            else:
                stage("deliver", "error", proc.stderr[:200])
        else:
            stage("deliver", "skipped", "empty content")

        result["status"] = "ok"
        result["finish_time"] = datetime.now(UTC).isoformat()
        session.close()

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)[:500]
        result["finish_time"] = datetime.now(UTC).isoformat()
        stage("pipeline", "error", str(e)[:200])

    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    run_pipeline()
