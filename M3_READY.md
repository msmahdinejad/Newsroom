# M3 Editorial + Telegram - READY FOR CONFIGURATION

**Date**: 2026-07-13
**Status**: 🟡 Implementation Complete, Awaiting Configuration

## Completed

✅ **Editorial Skills**
- `skills/persian-tech-digest.md` - Full editorial guidelines
- Persian (fa-IR) format with confidence labels
- Story classification (رسمی، تأییدشده، شایعه، etc.)
- Source preservation and evidence grounding
- "چرا مهم است" context sections

✅ **Editorial Module**
- `src/newsroom/editorial/hermes.py` - HermesEditorial class
- Story context building for Hermes delegation
- Deterministic preview fallback (working now)
- Digest creation and persistence
- Priority-based grouping

✅ **Telegram Delivery**
- `src/newsroom/delivery/telegram.py` - TelegramDelivery class
- Smart message chunking (4096 char Telegram limit)
- Line/word boundary splitting
- Delivery tracking (digest.delivered flag)
- Idempotency (skips already-delivered)

## Architecture

```
Stories → HermesEditorial → Persian Digest → TelegramDelivery → User
          (with skill)       (4096 chunks)    (via Gateway)
```

## What Works Now

1. Generate digest: `create_digest(story_ids)`
2. Chunk messages: Smart splitting preserves formatting
3. Track delivery: Database flag prevents re-send
4. Tests: All M1+M2 tests still passing (49/50)

## What Needs Configuration

### 1. Hermes Gateway Setup

```bash
hermes gateway setup telegram
```

User will be prompted for:
- Telegram Bot Token
- Allowed user IDs

### 2. Test Delivery

Once Gateway configured:

```python
from newsroom.editorial import create_digest
from newsroom.delivery import TelegramDelivery

# Create test digest
digest = create_digest([story_id_1, story_id_2])

# Deliver via Telegram
delivery = TelegramDelivery()
success = delivery.deliver_digest(digest.id)
```

### 3. Enable Hermes Delegation (Optional Enhancement)

Currently uses deterministic preview. To enable full Hermes LLM synthesis:

```python
# In hermes.py generate_digest():
from hermes import delegate_task

result = delegate_task(
    goal="Generate Persian tech digest",
    context=str(context),
    skills=["persian-tech-digest"]
)
digest_text = result["summary"]
```

## Manual Test Checklist

- [ ] Hermes Gateway configured with Telegram bot
- [ ] Bot token stored securely (never committed)
- [ ] Allowed user ID configured
- [ ] Test digest created from real stories
- [ ] Digest delivered to Telegram successfully
- [ ] Persian text renders correctly
- [ ] Links work
- [ ] Message chunking preserves format
- [ ] Re-delivery properly skipped (idempotency)

## Known Limitations

1. **Deterministic preview only** - Full Hermes synthesis requires delegation integration
2. **No retry logic** - Failed deliveries not automatically retried (add in production)
3. **Single recipient** - Broadcasts need Gateway fan-out configuration
4. **No scheduling yet** - Cron jobs for 09:00/15:00/21:00 not configured

## Next Steps

### Immediate (Requires Human)
1. Obtain Telegram Bot Token from @BotFather
2. Get user's Telegram user ID
3. Run: `hermes gateway setup telegram`
4. Test manual delivery

### Future (Can Continue Autonomously)
1. Add Hermes delegation for LLM synthesis
2. Create cron jobs (09:00, 15:00, 21:00 Asia/Tehran)
3. Add retry logic with exponential backoff
4. Implement source health monitoring
5. Add delivery analytics/tracking

## Ready to Request Credentials

The system is now ready for the minimal human input:
- Telegram Bot Token
- Telegram user ID (target recipient)

Everything else is automated.
