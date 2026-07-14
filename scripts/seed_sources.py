"""Seed default news sources into the database.

Run this after any database reset to populate the source registry.
"""
import sys
from datetime import datetime, timezone

sys.path.insert(0, "src")

from newsroom.storage.database import engine
from newsroom.storage.models import Source
from sqlalchemy.orm import Session

DEFAULT_SOURCES = [
    # RSS feeds (8)
    ("Hacker News", "rss", "https://news.ycombinator.com/rss", "en", "high"),
    ("Python Insider", "rss", "https://blog.python.org/feeds/posts/default", "en", "high"),
    ("The Verge", "rss", "https://www.theverge.com/rss/index.xml", "en", "medium"),
    ("TechCrunch AI", "rss", "https://techcrunch.com/category/artificial-intelligence/feed/", "en", "high"),
    ("VentureBeat AI", "rss", "https://venturebeat.com/category/ai/feed/", "en", "high"),
    ("Ars Technica", "rss", "https://feeds.arstechnica.com/arstechnica/index.xml", "en", "medium"),
    ("Krebs on Security", "rss", "https://krebsonsecurity.com/feed/", "en", "high"),
    ("Google AI Blog", "rss", "https://blog.research.google/feeds/posts/default", "en", "high"),
    # GitHub releases (5)
    ("python/cpython", "github_releases", "https://github.com/python/cpython", "en", "medium"),
    ("pytorch/pytorch", "github_releases", "https://github.com/pytorch/pytorch", "en", "medium"),
    ("langchain-ai/langchain", "github_releases", "https://github.com/langchain-ai/langchain", "en", "high"),
    ("openai/openai-python", "github_releases", "https://github.com/openai/openai-python", "en", "medium"),
    ("vercel/next.js", "github_releases", "https://github.com/vercel/next.js", "en", "low"),
]


def seed():
    session = Session(engine)
    try:
        for name, stype, url, lang, priority in DEFAULT_SOURCES:
            existing = session.query(Source).filter_by(name=name).first()
            if not existing:
                src = Source(
                    name=name, type=stype, url=url,
                    language=lang, priority=priority,
                    enabled=True, consecutive_failures=0,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
                session.add(src)
        session.commit()
        count = session.query(Source).count()
        print(f"[OK] {count} sources in database")
    finally:
        session.close()


if __name__ == "__main__":
    seed()
