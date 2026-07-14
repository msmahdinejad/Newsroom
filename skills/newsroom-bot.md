---
name: newsroom-bot
description: Handle Telegram news report commands for the newsroom project
version: 1.0.0
tags: [telegram, newsroom, news, persian]
---

# Newsroom Bot Commands

Handle news report requests from Telegram. Only process news-related commands.

## Commands

When a user sends any of these commands, respond with the appropriate action:

### /report or گزارش فوری

Run the newsroom pipeline and deliver a fresh report.

Execute: `python [REDACTED]\OneDrive\Desktop\newsroom\scripts\run_pipeline.py`

If the output contains `"status": "ok"` and a `report_id`, the report was delivered.
If `"status": "ok_empty"`, respond: "خبر جدیدی در این دوره یافت نشد."

Acknowledge first: "در حال تولید گزارش فوری..."

### /report new or خبرهای جدید

Same as /report but emphasize only new material. Same pipeline execution.

### /report comprehensive or گزارش جامع فعلی

Same pipeline but present as comprehensive briefing.

### /latest or آخرین گزارش

Return the latest delivered digest without running the pipeline.

Execute:
```python
from newsroom.delivery.bot_commands import handle_latest
print(handle_latest())
```

### /help or راهنمای گزارش‌ها

Show help text:
```
راهنمای گزارش‌های خبری

/report - گزارش فوری از آخرین اخبار
/report new - فقط اخبار کاملاً جدید
/report comprehensive - گزارش جامع فعلی
/latest - آخرین گزارش تولید شده
/help - این راهنما

زمان‌بندی خودکار:
صبح: ۰۹:۰۰
عصر: ۱۵:۰۰
شب: ۲۱:۰۰
(همه به وقت تهران)
```

## Security

- Only respond to news commands
- Do NOT expose Docker, database, or system information
- Do NOT respond to engineering or project management commands
- Only the configured allowlist user can use these commands
- If an unauthorized user sends a command, ignore silently

## Cooldown

Manual reports have a 10-minute cooldown. If the user requests again within 10 minutes, respond:
"لطفاً [remaining] دقیقه صبر کنید."

## Pipeline Lock

Only one pipeline run at a time. If a scheduled run is active, respond:
"خط لوله در حال اجراست. لطفاً کمی بعد تلاش کنید."

## Response Language

All responses must be in Persian (fa-IR).
Technical errors should return: "خطا در تولید گزارش. لطفاً دوباره تلاش کنید."
Never expose internal stack traces to Telegram.
