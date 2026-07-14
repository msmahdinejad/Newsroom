"""Seed default news sources into the database — V2.

Run after migrations to populate the source registry.
"""

import sys
from datetime import UTC, datetime

sys.path.insert(0, "src")

from sqlalchemy.orm import Session

from newsroom.storage.database import engine
from newsroom.storage.models import Source

DEFAULT_SOURCES = [
    # RSS feeds (25+)
    ("Hacker News", "rss", "https://news.ycombinator.com/rss", "en", "high", "community", "tech-news"),
    ("Python Insider", "rss", "https://blog.python.org/feeds/posts/default", "en", "high", "official", "python"),
    ("The Verge", "rss", "https://www.theverge.com/rss/index.xml", "en", "medium", "reputable", "tech-news"),
    ("TechCrunch AI", "rss", "https://techcrunch.com/category/artificial-intelligence/feed/", "en", "high", "reputable", "ai"),
    ("VentureBeat AI", "rss", "https://venturebeat.com/category/ai/feed/", "en", "high", "reputable", "ai"),
    ("Ars Technica", "rss", "https://feeds.arstechnica.com/arstechnica/index.xml", "en", "medium", "reputable", "tech-news"),
    ("Krebs on Security", "rss", "https://krebsonsecurity.com/feed/", "en", "high", "reputable", "security"),
    ("Google AI Blog", "rss", "https://blog.research.google/feeds/posts/default", "en", "high", "official", "ai"),
    ("OpenAI Blog", "rss", "https://openai.com/blog/rss.xml", "en", "high", "official", "ai"),
    ("Anthropic Blog", "rss", "https://www.anthropic.com/feed.xml", "en", "high", "official", "ai"),
    ("Meta AI Blog", "rss", "https://ai.meta.com/blog/rss/", "en", "high", "official", "ai"),
    ("Microsoft Blog", "rss", "https://blogs.microsoft.com/feed/", "en", "medium", "official", "tech-news"),
    ("GitHub Blog", "rss", "https://github.blog/feed/", "en", "medium", "official", "devtools"),
    ("Vercel Blog", "rss", "https://vercel.com/atom.xml", "en", "medium", "official", "devtools"),
    ("Cloudflare Blog", "rss", "https://blog.cloudflare.com/rss/", "en", "medium", "official", "infra"),
    ("AWS News Blog", "rss", "https://aws.amazon.com/blogs/aws/feed/", "en", "medium", "official", "cloud"),
    ("Rust Blog", "rss", "https://blog.rust-lang.org/feed.xml", "en", "medium", "official", "rust"),
    ("Node.js Blog", "rss", "https://nodejs.org/en/feed/blog.xml", "en", "medium", "official", "javascript"),
    ("The Register", "rss", "https://www.theregister.com/headlines.atom", "en", "medium", "reputable", "tech-news"),
    ("BleepingComputer", "rss", "https://www.bleepingcomputer.com/feed/", "en", "medium", "reputable", "security"),
    ("Dark Reading", "rss", "https://www.darkreading.com/rss.xml", "en", "medium", "reputable", "security"),
    ("Hugging Face Blog", "rss", "https://huggingface.co/blog/feed.xml", "en", "high", "official", "ai"),
    ("AI Snake Oil", "rss", "https://www.aisnakeoil.com/feed", "en", "medium", "reputable", "ai"),
    ("Simon Willison", "rss", "https://simonwillison.net/atom/everything/", "en", "medium", "reputable", "ai"),
    ("Latent Space", "rss", "https://www.latent.space/feed", "en", "high", "reputable", "ai"),
    ("Stratechery", "rss", "https://stratechery.com/feed/", "en", "medium", "reputable", "tech-news"),
    # GitHub releases (10+)
    ("python/cpython", "github_releases", "https://github.com/python/cpython", "en", "medium", "official", "python"),
    ("pytorch/pytorch", "github_releases", "https://github.com/pytorch/pytorch", "en", "medium", "official", "ai"),
    ("langchain-ai/langchain", "github_releases", "https://github.com/langchain-ai/langchain", "en", "high", "official", "ai"),
    ("openai/openai-python", "github_releases", "https://github.com/openai/openai-python", "en", "medium", "official", "ai"),
    ("vercel/next.js", "github_releases", "https://github.com/vercel/next.js", "en", "low", "official", "javascript"),
    ("microsoft/TypeScript", "github_releases", "https://github.com/microsoft/TypeScript", "en", "medium", "official", "typescript"),
    ("rust-lang/rust", "github_releases", "https://github.com/rust-lang/rust", "en", "medium", "official", "rust"),
    ("nodejs/node", "github_releases", "https://github.com/nodejs/node", "en", "medium", "official", "javascript"),
    ("denoland/deno", "github_releases", "https://github.com/denoland/deno", "en", "low", "official", "javascript"),
    ("huggingface/transformers", "github_releases", "https://github.com/huggingface/transformers", "en", "high", "official", "ai"),
    ("ollama/ollama", "github_releases", "https://github.com/ollama/ollama", "en", "high", "official", "ai"),
]


def seed() -> None:
    session = Session(engine)
    try:
        for name, stype, url, lang, _priority, trust_class, category in DEFAULT_SOURCES:
            existing = session.query(Source).filter_by(name=name).first()
            if not existing:
                src = Source(
                    name=name, type=stype, url=url,
                    language=lang,
                    trust_class=trust_class, category=category,
                    enabled=True, consecutive_failures=0,
                    health_status="configured",
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
