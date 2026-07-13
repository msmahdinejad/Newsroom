# Persian AI Newsroom

Local-first automated newsroom for Persian technology and AI updates.

## Quick Start (Windows)

### Prerequisites
- Windows 10/11
- Docker Desktop installed and running
- Python 3.12
- uv installed: `pip install uv`
- PowerShell 5.1 or PowerShell 7

### Setup

```powershell
# Clone repository
git clone <repo-url> newsroom
cd newsroom

# Run setup (installs dependencies, starts database, runs migrations)
.\scripts\setup.ps1

# Verify system health
.\scripts\health.ps1
```

### Basic Usage

```powershell
# Validate sources without collecting
.\scripts\validate-sources.ps1

# Collect from all enabled sources
.\scripts\collect.ps1

# Process collected items (normalize, deduplicate, cluster, digest)
.\scripts\process.ps1

# Or run the complete pipeline
.\scripts\run-all.ps1

# View logs
.\scripts\logs.ps1

# Reset test data
.\scripts\reset-test-data.ps1
```

### Development

```powershell
# Run tests
.\scripts\test.ps1

# Run linters
.\scripts\lint.ps1

# Database management
.\scripts\db-up.ps1      # Start PostgreSQL
.\scripts\db-down.ps1    # Stop PostgreSQL
.\scripts\migrate.ps1    # Apply migrations
```

## Architecture

```
External Sources → Collection → Normalization → Deduplication
                                                      ↓
Persian Digest ← Digest Generation ← Event Clustering
```

See `docs/architecture/ARCHITECTURE.md` for details.

## Project Structure

```
newsroom/
├── newsroom/              # Python package
│   ├── sources/          # RSS/Atom/GitHub collectors
│   ├── storage/          # Database models and migrations
│   ├── processing/       # Normalization, deduplication, clustering
│   ├── digest/           # Persian digest generation
│   └── cli/              # Command-line interface
├── scripts/              # PowerShell automation scripts
├── docs/                 # Documentation
│   ├── architecture/    # Technical design
│   ├── security/        # Threat model
│   ├── policies/        # Source and data retention policies
│   ├── milestones/      # Project plan
│   └── acceptance/      # Acceptance tests
├── docker-compose.yml   # PostgreSQL container
├── CONSTITUTION.md      # Project principles
├── CONTEXT.md          # Domain glossary
├── TASKS.md            # Implementation tasks
└── STATUS.md           # Project status
```

## Key Features

✅ **Collection Without AI**: Continues working when LLMs unavailable  
✅ **Source Isolation**: Failed sources don't break others  
✅ **Evidence Preservation**: Every claim links to original source  
✅ **Deterministic First**: Hash-based deduplication, keyword clustering  
✅ **Windows Native**: PowerShell scripts, native Python via uv  
✅ **Persian Output**: Digest candidates with source attribution  

## Configuration

Create `.env` from `.env.example`:

```bash
cp .env.example .env
# Edit .env with your settings
```

See `.env.example` for required variables.

## Adding Sources

### RSS/Atom Feed
```sql
INSERT INTO sources (name, type, url, language, priority)
VALUES ('Python Blog', 'rss', 'https://blog.python.org/feeds/posts/default', 'en', 'high');
```

### GitHub Releases
```sql
INSERT INTO sources (name, type, url, language, priority)
VALUES ('PyTorch', 'github_releases', 'pytorch/pytorch', 'en', 'high');
```

See `docs/policies/SOURCE_POLICY.md` for guidelines.

## Testing

```powershell
# Run all tests
.\scripts\test.ps1

# Run specific test file
uv run pytest tests/test_rss.py

# Run with coverage
uv run pytest --cov=newsroom --cov-report=html
```

## Documentation

- **CONSTITUTION.md** - Project principles and constraints
- **CONTEXT.md** - Domain glossary (ubiquitous language)
- **docs/PRODUCT_SPEC.md** - Product requirements
- **docs/architecture/** - Technical design and database schema
- **docs/security/THREAT_MODEL.md** - Security analysis
- **docs/policies/** - Source and retention policies
- **docs/acceptance/** - Acceptance test criteria

## Deployment (Future)

MVP runs locally. For VPS deployment:

```bash
# On Linux server
docker compose up -d
docker compose exec app python -m newsroom.cli collect
```

See deployment guide (future) for production setup.

## Troubleshooting

### Database won't start
```powershell
# Check Docker Desktop is running
docker ps

# Check port 5432 not in use
netstat -an | findstr :5432

# Restart
.\scripts\db-down.ps1
.\scripts\db-up.ps1
```

### Collection fails
```powershell
# Validate sources first
.\scripts\validate-sources.ps1

# Check health status
.\scripts\health.ps1

# Review logs
.\scripts\logs.ps1
```

### Tests fail
```powershell
# Reset test database
.\scripts\reset-test-data.ps1

# Run tests with verbose output
uv run pytest -v
```

## Contributing

See `CONSTITUTION.md` for project principles.

1. All changes require tests
2. Run linters before commit: `.\scripts\lint.ps1`
3. Update CONTEXT.md if adding domain terms
4. Document ADRs for architectural decisions
5. Update STATUS.md with progress

## Security

- Never commit `.env`, credentials, or session files
- All external content sanitized on input
- Source URLs preserved for attribution
- See `docs/security/THREAT_MODEL.md` for details

## License

[To be determined]

## Status

Current phase: Planning Complete  
See STATUS.md for detailed progress.
