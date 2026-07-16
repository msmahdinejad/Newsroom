# Legacy V1 (quarantined)

Dead / deferred runtime paths moved out of `src/` during Gate 1.

Files:
- `hermes.py` — V1 editorial with `eval(story.source_urls)` and missing `Digest` model
- `preview.py` — V1 digest preview with same `eval()` / `Digest` issues
- `bot_commands.py` — V1 bot handlers with file lock and hardcoded host path
- `telegram_mtproto.py` — MTProto collector deferred to Gate 2 (Telethon); not active

Not importable as package modules. Not on PYTHONPATH. Do not execute.
Safety tag `baseline-before-resume` retains prior tree.
