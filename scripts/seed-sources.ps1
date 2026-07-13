$ErrorActionPreference = "Stop"

Write-Host "Seeding initial sources..." -ForegroundColor Cyan

$sql = @"
-- RSS sources
INSERT INTO sources (name, type, url, language, priority, enabled)
VALUES 
  ('Python Blog', 'rss', 'https://blog.python.org/feeds/posts/default', 'en', 'high', true),
  ('PyPI Updates', 'rss', 'https://pypi.org/rss/updates.xml', 'en', 'medium', true),
  ('GitHub Engineering', 'rss', 'https://github.blog/feed/', 'en', 'medium', true)
ON CONFLICT (name) DO NOTHING;

-- GitHub sources
INSERT INTO sources (name, type, url, language, priority, enabled)
VALUES
  ('PyTorch', 'github_releases', 'pytorch/pytorch', 'en', 'high', true),
  ('Python CPython', 'github_releases', 'python/cpython', 'en', 'high', true),
  ('Pydantic', 'github_releases', 'pydantic/pydantic', 'en', 'medium', true)
ON CONFLICT (name) DO NOTHING;
"@

docker compose exec -T postgres psql -U newsroom -d newsroom -c $sql

if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] Sources seeded" -ForegroundColor Green
    
    # Show current sources
    docker compose exec postgres psql -U newsroom -d newsroom -c "SELECT name, type, enabled FROM sources ORDER BY priority DESC, name;"
    exit 0
} else {
    Write-Host "[ERROR] Failed to seed sources" -ForegroundColor Red
    exit 1
}
