# Deployment

## First deployment

```bash
git clone <repository-url> newsroom
cd newsroom
python scripts/bootstrap.py --source-mode default
```

Review all ignored local files, configure the intended integrations, then:

```bash
docker compose up -d --build --wait
docker compose ps
uv run newsroom health
```

## Production checklist

- Use a unique PostgreSQL password.
- Keep PostgreSQL bound to loopback or a protected private network.
- Enable only configured collectors.
- Use dedicated Telegram and X operational accounts.
- Keep provider, X, proxy, and Telegram access values in ignored local files.
- Complete bounded validation before enabling a provider model.
- Back up PostgreSQL and Docker volumes before upgrades.
- Configure host log rotation and disk monitoring.
- Run the public and runtime exposure audits.

## Upgrade

```bash
git pull --ff-only
uv sync --frozen --extra telegram
docker compose build
docker compose run --rm migrate
docker compose up -d --wait
```

Do not rewrite applied migrations. Add a new forward migration for schema
changes.

## Backup

Back up both the database and persistent volumes. A database-only example:

```bash
docker compose exec -T postgres \
  pg_dump -U newsroom -Fc newsroom > newsroom.dump
```

Store backups outside the repository with restricted access. Test restoration
regularly on an isolated database.

## Health and logs

```bash
docker compose ps
docker compose logs --tail 200
uv run newsroom health
uv run newsroom sources list
```

Logs and health output expose only safe categories and identifiers.

## Shutdown

```bash
docker compose down
```

This preserves named volumes. Do not add `--volumes` unless permanent data
destruction is explicitly intended and a verified backup exists.
