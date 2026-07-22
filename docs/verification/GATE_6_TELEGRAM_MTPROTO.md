# Gate 6 — Telegram MTProto Network Diagnosis

## Session and ownership

The existing MTProto session was preserved throughout diagnosis. It was not
deleted, reset, re-authorized, copied into another service, or mounted into the
Agent-Reach worker. `telegram-ingestor` remains the sole session owner.

## Bounded diagnosis

The production session identifies Telegram DC 1. Host and container probes
were performed without mutating the session:

- host IPv4 direct TCP to the session DC timed out;
- host IPv6 had no usable route;
- the container completed a TCP connection to the DC, but the MTProto
  handshake timed out or was closed;
- Telethon abridged, intermediate, full, and obfuscated TCP modes all failed
  with the same bounded connection-timeout category;
- Windows firewall profiles were enabled but had no outbound deny rule for
  this traffic;
- WinHTTP was direct, and no active HTTP, SOCKS, MTProxy, VPN, or service-level
  proxy route was configured;
- restarting the ingestor preserved the session and reproduced the same
  bounded result.

All 157 configured Telegram sources have durable attempt records, safe failure
categories, and explicit no-cursor reasons. The ingestor health remains
truthfully degraded; it does not claim authentication failure or a healthy
MTProto connection.

## External blocker

The current host network path permits a container TCP SYN to the Telegram DC
but drops or blocks the subsequent MTProto payload across every tested Telethon
transport. Direct host TCP is also blocked and IPv6 is unavailable. With no
working proxy/VPN/MTProxy route configured, the application cannot obtain the
required successful connection or a newly collected Telegram post.

Gate 6 therefore cannot be marked `VERIFIED` on this host until outbound
MTProto reachability is restored or an owner-approved working proxy route is
provided. The native audited collector remains in place and will recover using
the preserved session when the external route becomes available.
