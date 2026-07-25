# Product Specification: Persian AI Newsroom MVP

## Problem Statement

Technology and AI move fast. Persian-speaking developers, researchers, and tech professionals need timely, source-grounded updates about releases, research, and developments. Manually monitoring dozens of RSS feeds, GitHub releases, and social channels is time-consuming and error-prone.

## Solution

A local-first automated newsroom that:
- Continuously collects from configured public sources
- Deduplicates and groups related reports
- Generates Persian digest candidates with preserved source links
- Runs entirely on a local Windows machine
- Can later deploy to a Linux VPS

## User Stories

### Collection
1. As a newsroom operator, I want to configure RSS feed URLs, so that I can monitor specific technology sites
2. As a newsroom operator, I want to configure GitHub repositories for release monitoring, so that I track important project releases
3. As a newsroom operator, I want collection to continue when AI is unavailable, so that I don't miss items during outages
4. As a newsroom operator, I want failed sources isolated, so that one broken feed doesn't stop others
5. As a newsroom operator, I want to manually trigger collection, so that I can test before scheduling

### Deduplication
6. As a newsroom operator, I want exact duplicate removal, so that the same item from multiple feeds appears once
7. As a newsroom operator, I want URL normalization, so that tracking parameters don't create false duplicates
8. As a newsroom operator, I want content-hash matching, so that identical content with different URLs is detected

### Event Grouping
9. As a newsroom operator, I want items about the same event grouped together, so that I see one entry for "Python 3.13 released" instead of five
10. As a newsroom operator, I want time-window clustering, so that related items published within hours are considered together
11. As a newsroom operator, I want source URLs preserved in clusters, so that every claim traces to original sources

### Persian Output
12. As a reader, I want a Persian digest candidate for each event, so that I can read about tech developments in Persian
13. As a reader, I want important items in the main section, so that I see significant developments first
14. As a reader, I want low-priority items in ریزخبرها section, so that I can scan minor updates quickly
15. As a reader, I want source links in every entry, so that I can verify claims and read full details

### Operations
16. As a newsroom operator, I want PowerShell scripts for all operations, so that I can run on Windows without WSL
17. As a newsroom operator, I want clear success/failure output, so that I know if operations completed
18. As a newsroom operator, I want Docker Compose for PostgreSQL, so that I have consistent database environment
19. As a newsroom operator, I want health check command, so that I can verify system status
20. As a newsroom operator, I want to reset test data, so that I can start fresh during development

## Implementation Decisions

### Architecture: Modular Monolith
Single Python codebase with clear module boundaries:
- `newsroom.sources` - RSS/Atom/GitHub collection
- `newsroom.storage` - SQLAlchemy models, database access
- `newsroom.processing` - Normalization, deduplication, clustering
- `newsroom.digest` - Persian candidate generation
- `newsroom.cli` - Command-line interface

### Database: PostgreSQL 16
- SQLAlchemy 2 for ORM
- Alembic for migrations
- Runs in Docker Desktop during development
- Tables: sources, raw_items, normalized_items, event_clusters, digest_candidates

### Collection Strategy
- httpx for async HTTP requests
- feedparser for RSS/Atom parsing
- GitHub REST API for releases (public, no auth in MVP)
- Per-source error handling and retry
- Store raw responses before any processing

### Deduplication Algorithm
Deterministic stages:
1. Exact content hash matching (SHA-256 of title + description)
2. URL normalization: lowercase domain, remove tracking params, strip fragments
3. Normalized URL matching

### Event Clustering Algorithm
Deterministic approach:
1. Time window: 24 hours
2. Keyword extraction from titles
3. Keyword overlap threshold: 50% of keywords match
4. Manual review flag for borderline cases

### Persian Generation
MVP: Template-based with source preservation
- Headline from most authoritative source
- Key points list from all sources
- Source attribution for each point
- Later: Hermes Agent for editorial synthesis

### Testing Strategy
- pytest with fixtures for test database
- Integration tests use real PostgreSQL in Docker
- Contract tests for external APIs (recorded responses)
- No mocking of database layer

## Out of Scope (MVP)

### Not Included in First Release
- Telegram channel monitoring (requires auth)
- X/Twitter scraping (requires auth and browser)
- Reddit monitoring
- YouTube monitoring
- LinkedIn monitoring
- Semantic embeddings
- Full AI editorial synthesis (templates only)
- Automated publishing
- Web interface
- Scheduling (manual execution only in MVP)

### Future Enhancements
- Agent-Reach integration
- Automated scheduling via cron/Task Scheduler
- Web dashboard
- Multi-language output (English, Arabic)
- Sentiment analysis
- Trend detection

## Further Notes

### Windows Development Path
All development happens on Windows 10/11:
- uv for Python environment
- PowerShell for automation
- Docker Desktop for PostgreSQL only
- Native Python execution (not in container)

### Linux Deployment Path
Preserved for VPS deployment:
- Docker Compose includes Python container
- All scripts have Bash equivalents (future)
- Environment-agnostic Python code

### Source Credibility (Future)
MVP treats all sources equally. Future versions may:
- Weight sources by credibility
- Flag unverified claims
- Require multiple sources for major claims
