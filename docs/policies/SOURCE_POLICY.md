# Source Policy

## Approved Source Types (MVP)

### RSS/Atom Feeds
**Criteria**:
- Must use HTTPS
- Public access (no authentication)
- Technology or AI focus
- Persian, English, or Arabic content
- Updates at least weekly

**Examples**:
- Hacker News RSS
- Python.org blog feed
- TechCrunch AI section
- arXiv cs.AI recent submissions

**Rejected**:
- HTTP-only feeds (security)
- Paywalled content (access)
- High-volume feeds (>500 items/day in MVP)

### GitHub Releases
**Criteria**:
- Public repositories only
- Active maintenance (commit in last 6 months)
- Technology/AI/ML projects
- Official releases (not every commit)

**Examples**:
- python/cpython
- pytorch/pytorch
- microsoft/typescript
- langchain-ai/langchain

**Rejected**:
- Private repositories (no auth in MVP)
- Personal forks (prefer upstream)
- Archived projects (no longer maintained)

## Source Validation

Before adding a source:
1. Verify HTTPS access
2. Test feed parsing (download sample)
3. Check update frequency
4. Confirm content quality (manual review of 10 items)
5. Add to sources table with metadata

## Source Health Monitoring

### Health States
- **Healthy**: Last 3 fetches successful
- **Degraded**: 1-2 failures in last 3 fetches
- **Failing**: 3+ consecutive failures
- **Disabled**: Manually disabled by operator

### Failure Handling
- Exponential backoff: 1m, 5m, 15m, 1h, 6h, 24h
- After 24h of failures, mark as Failing
- Alert operator (future: notification)
- Continue monitoring other sources

### Re-enabling
- Failing sources automatically retried daily
- If successful, reset to Healthy
- If still failing after 7 days, require manual review

## Content Restrictions

### Prohibited Content
- Illegal content (per Iranian law)
- Explicit adult content
- Malware distribution
- Spam or pure advertising
- Personal attacks or doxxing

### Action on Violation
1. Disable source immediately
2. Mark all recent items for review
3. Remove from digest candidates
4. Document reason in sources table
5. Consider permanent ban

## Source Attribution

Every digest entry must:
- Link to original source URL
- Show source name/domain
- Preserve publication timestamp
- Never modify quotes or claims

## Future Source Types

Deferred to post-MVP:
- Telegram channels (requires auth)
- X/Twitter (requires auth + browser)
- Reddit (API rate limits)
- YouTube (video processing complexity)
- LinkedIn (auth complexity)
- Mastodon (decentralized, complex)

## Source Configuration Format

```yaml
sources:
  - name: "Python Blog"
    type: rss
    url: "https://blog.python.org/feeds/posts/default"
    language: en
    priority: high
    categories: [python, releases]
    
  - name: "PyTorch Releases"
    type: github_releases
    repo: "pytorch/pytorch"
    language: en
    priority: high
    categories: [ml, frameworks]
```

## Review Schedule

- Monthly: Review all source health status
- Quarterly: Audit source quality (manual sampling)
- Yearly: Re-validate all source choices
