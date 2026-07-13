# Domain Glossary

## Core Concepts

**Source**
A configured external feed or API that provides raw items. Examples: RSS feed URL, GitHub release API endpoint. Each source has independent health tracking and retry logic.

**Raw Item**
Unprocessed data collected from a source. Stored exactly as received before any transformation. Never deleted.

**Normalized Item**
A raw item transformed into standard fields: title, description, published_at, source_url, content_hash. One raw item produces one normalized item.

**Content Hash**
SHA-256 hash of normalized title + description. Used for exact-duplicate detection.

**Source URL**
The canonical web address where a user can read the original content. Must be preserved through all processing stages.

**Event**
A real-world occurrence reported by one or more sources. Examples: "Python 3.13 released", "New AI model announced".

**Event Cluster**
A group of normalized items that report the same event. Clustering uses time windows and deterministic similarity.

**Digest Candidate**
A Persian-language summary packet for one event cluster, containing: headline, key points from sources, source URLs, timestamps. Created before AI synthesis.

**Persian Newsbrief**
The final output: a coherent Persian digest combining multiple digest candidates. Includes a main section for important items and "ریزخبرها" for low-priority items.

**ریزخبرها** (Micro-News)
Compact section at end of newsbrief for low-priority items. Single-line summaries with source links.

## Collection Terms

**Collection Run**
A single execution of the collection pipeline: fetch from all sources, normalize, deduplicate, group.

**Failed Source**
A source that returned an error during collection. Tracked separately and retried with exponential backoff.

**Duplicate**
Two normalized items with identical content hashes, or very similar URLs after normalization.

**URL Normalization**
Removing tracking parameters, lowercasing domain, stripping fragments. Used before deduplication.

## Time Concepts

**Published At**
The timestamp from the source when the item was originally published.

**Collected At**
The timestamp when our system fetched the item.

**Event Window**
A time range for grouping items into events. Items within the same window and with similar content may be the same event.

## Processing States

**Raw** → Item stored exactly as received  
**Normalized** → Transformed to standard schema  
**Deduplicated** → Exact duplicates removed  
**Clustered** → Grouped into events  
**Digest Candidate** → Persian summary prepared  
**Published** → Included in final newsbrief (future)

## Non-Domain Terms

Terms we explicitly avoid:
- "Article" (ambiguous - use Raw Item, Normalized Item, or Event)
- "Story" (ambiguous - use Event)
- "Feed Item" (too generic - specify Raw Item vs Normalized Item)
- "News" (too vague - use Event or Digest Candidate)
