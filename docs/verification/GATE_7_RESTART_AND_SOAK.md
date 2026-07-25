# Gate 7 Restart and Soak Evidence

The complete Compose stack was rebuilt and restarted after the Gate 7
migration. At final inspection PostgreSQL, collector, report worker, scheduler,
Telegram bot, Telegram ingestor, and Agent-Reach worker were all healthy.

- PostgreSQL migration head: `0011_gate7_identity_privacy`.
- Scheduler: four Tehran jobs registered: 00:00, 06:00, 12:00, and 18:00.
- Telegram ingestor: preserved session exists, authenticated and connected over
  SOCKS5; 149 enabled/healthy channels; a newly persisted message and cursors
  survived restart.
- X: Agent-Reach reports the pinned revision
  `1494c2ab239e7355a77e7cceaf3271453a1f34b5`, healthy `twitter-cli` backend,
  and durable X account state after restart.
- Router: model health, key cooldown state, quotas, circuits, accepted
  artifacts, reports, deliveries, and provider route attempts remained in
  PostgreSQL across restart.

Bounded collector soak cycles used per-source advisory transaction locks,
twenty-source fair caps, one-second source spacing, and dedicated Telegram/X
ownership. No stuck pipeline job remained. Telegram and X duplicate identity
groups were both zero; the historical append-only RSS duplicate group was not
deleted and did not grow. Service logs were rotated and protected-value scans
were clean.
