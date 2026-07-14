# ADR-005: Deterministic Fallback Editorial

## Status
Accepted

## Context
The mandate requires an `EditorialProvider` interface with LLM support and a
deterministic fallback. The LLM adapter is not yet connected because no
provider credentials are available through a secure supported interface for
headless pipeline use.

## Decision
Ship the deterministic Persian renderer (`PersianEditorial`) as the default
generation method. It produces structured 3-layer reports from evidence
packets without an LLM call. When an LLM adapter is connected later, it
replaces the renderer for stories that warrant synthesis, with the
deterministic path as fallback during outages.

## Rationale
- Pipeline must work autonomously without depending on interactive LLM sessions
- Evidence packets already contain structured facts — deterministic rendering
  produces readable Persian without synthesis
- LLM integration is a pluggable boundary, not a hard dependency
- The fallback clearly labels when synthesis was unavailable

## Consequences
- Reports are structurally complete but lack narrative synthesis
- `generation_method` field in `reports` table tracks which path was used
- Adding LLM later requires only implementing the `EditorialProvider` interface
