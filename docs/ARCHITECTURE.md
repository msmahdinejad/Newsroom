# Architecture

## Services
```
┌──────────┐     ┌──────────────┐     ┌────────────────┐
│ collector│────▶│ raw_items    │────▶│ report-worker  │
└──────────┘     │ (JSONB)      │     │ normalize→     │
                 └──────────────┘     │ dedupe→cluster │
┌──────────┐                          └───────┬────────┘
│scheduler │──trigger──┐                      ▼
│09/15/21  │           │              ┌──────────────┐
└──────────┘           │              │ reports      │
                       ▼              └──────┬───────┘
              ┌──────────────┐              ▼
              │ run_pipeline │       ┌──────────────┐
              │ (subprocess) │       │ deliveries   │
              └──────────────┘       └──────┬───────┘
                                            ▼
                                     ┌──────────────┐
                                     │ telegram-bot │
                                     │ (Bot API)    │
                                     └──────────────┘
```

## Data flow
collect → raw_items → normalize → normalized_items → dedupe → cluster → stories → evidence → reports → deliveries

## DB
PostgreSQL 16, 13 tables, Alembic migrations. Inside Docker: `postgres:5432`. Host: `127.0.0.1:55432`.
