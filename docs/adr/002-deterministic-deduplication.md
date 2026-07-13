# ADR-002: Deterministic Deduplication Before AI

**Status**: Accepted  
**Date**: 2026-07-13  
**Context**: Planning phase

## Decision

Use deterministic algorithms (hash matching, URL normalization) for deduplication. Defer semantic similarity and embeddings to post-MVP.

## Context

Need to identify duplicate items from multiple sources. Three approaches considered:

1. **Content hash only** - SHA-256 of title+description
2. **Content hash + URL normalization** - Add URL-based deduplication
3. **Semantic embeddings** - Vector similarity with transformers

## Rationale

Chosen approach: #2 (hash + URL normalization)

**Why deterministic first**:
- Works without LLM/embeddings
- Fast (no API calls or model inference)
- Reproducible results
- No vector database needed
- Good enough for MVP (catches exact duplicates and obvious variants)

**Why defer semantic similarity**:
- Adds infrastructure complexity (vector DB or embeddings table)
- Requires model management (which embedding model? updates?)
- API costs (if using hosted embeddings)
- Unclear if needed (deterministic may be sufficient)

**Constitution principle**: "Deterministic First" - use deterministic algorithms before probabilistic ones.

## Implementation

Stage 1: Content hash
- SHA-256 of normalized title + description
- Catches identical content with different URLs

Stage 2: URL normalization
- Lowercase domain
- Remove tracking parameters (utm_*, fbclid, etc)
- Strip URL fragments (#)
- Catches same content at same URL with tracking

Future Stage 3: Semantic similarity (if needed)
- Only add if deterministic stages miss important duplicates
- Would use sentence-transformers locally (no API calls)
- Threshold tuning required

## Consequences

**Positive**:
- Simple implementation
- No external dependencies
- No API costs
- Fast execution
- Easy to test and debug

**Negative**:
- Won't catch paraphrased duplicates
- Won't catch translated duplicates
- May miss duplicates with minor content differences

**Mitigations**:
- Monitor false negatives during testing
- Add semantic stage if needed
- Event clustering provides second deduplication pass
- Manual review process can flag issues

## Success Criteria

Acceptable if deterministic deduplication catches >90% of duplicates in real-world testing. If <90%, add semantic similarity stage.
