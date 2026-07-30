# Source discovery

Newsroom can ask Gemini to find durable sources for an operator-defined
subject. Discovery never expands the source adapter registry: candidates must
be Telegram channels, X profiles, subreddits, GitHub repositories, or public
websites/feeds.

## Safety model

1. The request is bounded to 50 candidates.
2. Access values are loaded only from ignored `.env.providers.local`.
3. The Gemini response must include Google Search grounding citations.
4. Candidate URLs are normalized into the closed platform registry.
5. Private, loopback, local, credential-bearing, and unsupported URLs are
   rejected.
6. Public URLs receive a bounded probe with validated redirects.
7. Candidates remain pending until explicit approval.

Only safe job metadata, public candidate URLs, public citations, validation
status, and the operator's decision are persisted. Provider access values are
never stored.

## Quick discovery

```bash
uv run newsroom sources discover \
  --subject "Independent cinema releases and film festivals" \
  --platforms telegram,x,reddit,github,web \
  --mode quick \
  --max-candidates 20
```

## Deep discovery

Deep mode starts a background Gemini Deep Research interaction:

```bash
uv run newsroom sources discover \
  --subject "Renewable energy policy and grid storage markets" \
  --platforms telegram,reddit,web \
  --mode deep

uv run newsroom sources discovery-poll 12
```

List and decide:

```bash
uv run newsroom sources candidates --job 12 --status pending
uv run newsroom sources approve 31
uv run newsroom sources reject 32
```

Approval creates or reuses one authoritative source-registry row. A reachable
candidate is still not a guarantee of editorial quality; operators should
review its scope, ownership, rights, and noise level.

The implementation follows the official Gemini
[Google Search](https://ai.google.dev/gemini-api/docs/google-search) and
[Deep Research](https://ai.google.dev/gemini-api/docs/deep-research)
Interactions API contracts.
