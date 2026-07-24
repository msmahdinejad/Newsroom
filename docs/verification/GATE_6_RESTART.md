# Gate 6 — Restart and Recovery Evidence

The full production Compose stack was rebuilt and force-recreated twice. The
one-time `telegram-authorize` helper is profile-gated and absent from the
default stack, leaving `telegram-ingestor` as the sole session owner.

After the final restart:

- PostgreSQL, collector, report worker, scheduler, Telegram output bot, and
  Agent-Reach worker are healthy and running;
- Telegram ingestor is authenticated, connected through the configured safe
  proxy transport, and healthy after restart;
- router provider/model validation, key/quota state, and the closed Gemini
  circuit survived;
- report 464, delivery 433, and Telegram message 54 survived; the next real
  18:00 Tehran job then completed report 466, delivery 435, and message 56;
- report 465/delivery 434/message 55 from the zero-provider no-news check
  survived;
- all active-source attempts and cursor/no-cursor accounting survived;
- all X cursor/post identities survived, and later worker reads remained
  duplicate-free;
- Agent-Reach image label/package versions remained pinned to
  `1494c2ab239e7355a77e7cceaf3271453a1f34b5`, Agent-Reach 1.5.0, and
  twitter-cli 0.8.5;
- the scheduler persisted exactly four Asia/Tehran cron jobs at
  00:00, 06:00, 12:00, and 18:00;
- PostgreSQL had zero idle-in-transaction connections.

Production services are left running. The Telegram ingestor is an
authenticated, healthy MTProto owner with durable cursor continuation.
