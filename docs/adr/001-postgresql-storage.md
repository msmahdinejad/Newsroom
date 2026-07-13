# ADR-001: PostgreSQL for Primary Storage

**Status**: Accepted  
**Date**: 2026-07-13  
**Context**: Planning phase

## Decision

Use PostgreSQL 16 as the primary database for all storage needs.

## Context

Need persistent storage for:
- Source configuration
- Raw feed data (JSONB)
- Normalized items
- Event clusters
- Persian digest candidates

Considered alternatives:
1. **SQLite** - Simple, file-based
2. **PostgreSQL** - Full-featured RDBMS
3. **MongoDB** - Document store

## Rationale

PostgreSQL chosen because:
- JSONB for flexible raw data storage
- Full-text search (future feature)
- Time-series query optimization
- Strong ACID guarantees
- Transaction support for multi-stage processing
- Docker deployment well-understood
- Alembic integration mature

SQLite rejected:
- No concurrent write support
- Limited for future scaling
- No network access (harder to deploy)

MongoDB rejected:
- Overkill for MVP
- Less mature Python ORM ecosystem
- Schema flexibility not needed (we control all inputs)

## Consequences

**Positive**:
- Battle-tested for this use case
- Rich query capabilities
- Can handle future scale
- Native JSON support via JSONB

**Negative**:
- Requires Docker in development
- More complex than SQLite for local dev
- Need to manage migrations

**Mitigations**:
- Docker Compose makes local setup easy
- Alembic handles migrations automatically
- PowerShell scripts abstract complexity
