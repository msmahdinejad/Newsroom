# Gate 6 — Telegram MTProto Network Closure

## Session and transport

The existing MTProto session remained the sole property of
`telegram-ingestor`. It was not deleted, reset, copied, re-authorized, or
mounted into another long-running service.

The container-to-host probe classified the selected route as SOCKS5 by
protocol negotiation and proved that it could open a tunnel to the session's
Telegram DC. The other candidate host port was unreachable. The production
runtime uses the ignored local environment for its endpoint and exposes only
the safe transport label in health output.

The preserved Telethon session completed the MTProto handshake, reported
authorized, and remained connected after restart.

## Collection and restart evidence

One bounded cycle attempted all 157 configured Telegram sources:

- 149 completed successfully;
- 8 were isolated as `channel_unresolvable`;
- 8,852 new posts were persisted;
- later sources continued after each failed source.

The production ingestor then restarted, reconnected through the same safe
transport mode, and completed a 20-source continuation cycle. That cycle
persisted one new post, retained the existing cursor boundary for an unchanged
source, advanced its cursor timestamp, and left zero duplicate
channel/message identity pairs.

Production health after restart reports 149 configured, enabled, and healthy
Telegram channels with an authenticated, connected MTProto session.

## Safety

Proxy endpoints and credentials are absent from tracked files, documentation,
application logs, PostgreSQL, and health output. Only the proxy protocol and
Telethon connection mode are retained as safe operational metadata.

## Status

Telegram MTProto ingestion is operational through the configured host proxy.
The final external network blocker for Gate 6 is closed.
