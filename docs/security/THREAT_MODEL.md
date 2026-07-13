# Threat Model

## Assets

1. **Source Configuration**: URLs, API keys (future), credentials
2. **Collected Data**: Raw items, normalized items, clusters
3. **System Availability**: Ability to collect and process news
4. **Output Integrity**: Accuracy and source attribution in digests

## Threat Actors

### External Attackers
- **Motivation**: Disrupt service, inject false content
- **Capability**: Network-level attacks, malicious feeds
- **Likelihood**: Low (local deployment, no public exposure)

### Compromised Sources
- **Motivation**: Spread misinformation
- **Capability**: Publish false content to legitimate feeds
- **Likelihood**: Medium (RSS feeds can be compromised)

### Malicious Feeds
- **Motivation**: Exploit parsing vulnerabilities
- **Capability**: Crafted XML/JSON to trigger bugs
- **Likelihood**: Low but possible

## Threats & Mitigations

### T1: Malicious Feed Content
**Threat**: RSS feed contains XSS payloads, script tags, or malformed data  
**Impact**: Code execution, data corruption  
**Mitigation**: 
- HTML sanitization on all input
- No JavaScript execution
- Parser sandboxing (feedparser handles this)
- Content length limits (1MB)

### T2: Source Impersonation
**Threat**: Attacker registers look-alike domain to inject false content  
**Impact**: False information in digest  
**Mitigation**:
- HTTPS for all sources (enforced)
- Certificate validation
- Source URL verification
- Future: Source reputation scoring

### T3: Credential Exposure
**Threat**: API keys or credentials leaked in logs, code, or version control  
**Impact**: Unauthorized access to paid APIs or services  
**Mitigation**:
- Environment variables only
- `.gitignore` for `.env`
- No secrets in logs
- Log sanitization for URLs with tokens

### T4: SQL Injection
**Threat**: User input or malicious feed content contains SQL  
**Impact**: Database compromise  
**Mitigation**:
- SQLAlchemy ORM (parameterized queries)
- No raw SQL construction
- Input validation

### T5: Denial of Service (Feed Bomb)
**Threat**: Source returns gigabytes of data or infinite stream  
**Impact**: Disk exhaustion, memory exhaustion  
**Mitigation**:
- Content length limits (1MB per item)
- Connection timeout (30s)
- Read timeout (60s)
- Max items per fetch (1000)

### T6: Path Traversal
**Threat**: Malicious source URL or filename contains `../`  
**Impact**: Write files outside repository  
**Mitigation**:
- No file writes based on source data
- All paths constructed from constants
- URL validation rejects `file://`

### T7: Dependency Vulnerabilities
**Threat**: Python package has security flaw  
**Impact**: Varies by vulnerability  
**Mitigation**:
- Pin exact versions in requirements
- Regular updates via `uv pip compile`
- GitHub Dependabot alerts (future)

### T8: Resource Exhaustion
**Threat**: Processing too many items exhausts memory/CPU  
**Impact**: System unresponsive  
**Mitigation**:
- Batch processing (100 items)
- Memory limits per process
- Time limits per operation
- Database connection pooling

### T9: Data Loss
**Threat**: Database corruption, disk failure  
**Impact**: Loss of collected data  
**Mitigation**:
- Regular PostgreSQL backups
- Transaction rollback on errors
- Write-ahead logging (WAL)
- Future: Off-site backup

### T10: False Attribution
**Threat**: Digest attributes claim to wrong source  
**Impact**: Misinformation, credibility loss  
**Mitigation**:
- Immutable source URL in raw_items
- Foreign keys preserve provenance
- Source links in every digest entry
- No claim without source

## Security Requirements

### Input Validation
- [ ] Max content length enforced (1MB)
- [ ] URL scheme validation (https:// only)
- [ ] HTML sanitization on descriptions
- [ ] Feed size limits (1000 items)
- [ ] Connection timeouts (30s)

### Secret Management
- [ ] No secrets in code
- [ ] No secrets in logs
- [ ] Environment variables for credentials
- [ ] `.env` in `.gitignore`

### Output Safety
- [ ] No XSS in generated content
- [ ] Source URLs preserved
- [ ] No unattributed claims
- [ ] Safe for publication

### Operational Security
- [ ] Error messages don't leak internals
- [ ] Logs rotated and size-limited
- [ ] Database credentials restricted
- [ ] Docker containers run non-root (future)

## Out of Scope (MVP)

- Network-level attacks (no public exposure)
- Physical security (local deployment)
- Social engineering (no user accounts)
- Advanced persistent threats (not a target)
- Browser-based attacks (no web UI yet)

## Security Review Checklist

Before each release:
1. Audit dependencies for known CVEs
2. Review all secret handling code
3. Test with malicious feed samples
4. Verify input validation coverage
5. Check log output for sensitive data
6. Confirm all HTTPS, no HTTP
