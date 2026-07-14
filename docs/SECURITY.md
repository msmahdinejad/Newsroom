# Security

## Secrets
- No secrets in Git (.env in .gitignore)
- No secrets in Docker images
- No secrets in logs (structured JSON, no token/key fields)
- Source credentials stored as references (env var names, file paths), not values

## Injection prevention
- All collected content is untrusted data
- Evidence packets are bounded structured JSONB — no raw source text to LLM
- No eval() on stored data (replaced with JSONB dict access)
- URL validation in collectors
- Content-size limits (2MB default)
- Request timeouts on all HTTP clients

## Access control
- Telegram bot: allowlist of numeric user IDs
- Unauthorized users: silent deny (no operational details)
- No allow-all mode

## Container security
- Non-root user (newsroom)
- No unnecessary ports exposed
- Loopback-only DB binding
- Read-only mounts where practical

## Data retention
- Raw items: configurable (default 30 days)
- Normalized items: configurable (default 90 days)
- Stories/reports: persistent
- Media downloads: disabled by default

## Prompt injection
- Collected text never treated as agent instructions
- Evidence packets contain only structured facts, not raw source text
- LLM (when connected) receives bounded packets, not source URLs
