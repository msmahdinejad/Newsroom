# Gate 3 Restart Evidence

**Status**: COMPLETED

## Restart Test
1. Ingestor started → authenticated as user 8819135988 (@iAmLiam2005)
2. `docker compose restart telegram-ingestor`
3. Ingestor reconnected → authenticated without new login code
4. Collection cycle ran → 30 items skipped (all overlap, no duplicates)
5. State remained coherent — cursors intact

## Session Persistence
- Session file: 28672 bytes in Docker volume telegram_sessions
- Survives container restart (volume-mounted)
- Survives container recreation (named volume)
- No re-authorization needed
