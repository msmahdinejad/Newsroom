"""Small, explicit bot locale catalog.

Persian and English are first-class. Adding a locale means extending this
catalog and the editorial language allowlist; no handler logic changes.
"""

from __future__ import annotations

from typing import Any

from newsroom.control import ControlSnapshot

_MESSAGES: dict[str, dict[str, str]] = {
    "fa": {
        "no_report": "📭 هنوز گزارشی تولید نشده است.",
        "latest_error": "❌ بازیابی آخرین گزارش ناموفق بود.",
        "status_error": "❌ دریافت وضعیت سیستم ناموفق بود.",
        "sources_error": "❌ دریافت اطلاعات منابع ناموفق بود.",
        "schedule_error": "❌ دریافت زمان‌بندی ناموفق بود.",
        "collecting": "⏳ جمع‌آوری منابع آغاز شد…",
        "collected": "✅ جمع‌آوری کامل شد: {items} آیتم تازه از {sources} منبع؛ {failed} شکست.",
        "collect_error": "❌ جمع‌آوری منابع ناموفق بود.",
        "generating": "⏳ گزارش با هوش مصنوعی در حال تولید است…",
        "existing_report": "✅ گزارش شماره {report_id} قبلاً تولید شده است.",
        "cooldown": "⏳ یک درخواست اخیر هنوز معتبر است؛ چند دقیقه دیگر دوباره تلاش کنید.",
        "generation_error": "❌ تولید گزارش ناموفق بود.",
        "pipeline_busy": "⏳ خط تولید مشغول است؛ کمی بعد دوباره تلاش کنید.",
        "no_news": "📭 در این بازه خبر تازه‌ای برای گزارش پیدا نشد.",
        "ai_unavailable": "⏳ هیچ مسیر معتبر هوش مصنوعی پاسخ قابل‌قبول نداد؛ گزارش بی‌کیفیت ارسال نشد.",
        "report_delivered": "✅ گزارش شماره {report_id} تولید و در تلگرام تحویل شد.",
        "report_not_delivered": "✅ گزارش شماره {report_id} تولید شد؛ مقصد تلگرام تنظیم نشده است.",
        "settings_saved": "✅ تنظیمات ذخیره شد.",
        "bad_settings": "❌ تنظیم نامعتبر است: {error}",
        "source_not_found": "❌ منبع پیدا نشد.",
        "source_changed": "✅ منبع #{source_id} «{name}» {action}.",
        "source_delete_confirm": "⚠️ برای آرشیو منبع، دستور را با confirm تکرار کنید:\n/source delete {source_id} confirm",
        "source_command_error": "❌ عملیات منبع ناموفق بود: {error}",
        "import_caption": "یک فایل CSV یا XLSX با کپشن /sources import ارسال کنید.",
        "import_too_large": "❌ فایل منبع باید حداکثر ۵ مگابایت باشد.",
        "import_done": "✅ فایل {filename}: {created} منبع ایجاد، {updated} به‌روزرسانی و {skipped} ردیف رد شد.",
        "import_error": "❌ واردکردن فایل ناموفق بود: {error}",
    },
    "en": {
        "no_report": "📭 No report has been generated yet.",
        "latest_error": "❌ The latest report could not be loaded.",
        "status_error": "❌ System status could not be loaded.",
        "sources_error": "❌ Source information could not be loaded.",
        "schedule_error": "❌ Schedule information could not be loaded.",
        "collecting": "⏳ Source collection started…",
        "collected": "✅ Collection complete: {items} new items from {sources} sources; {failed} failures.",
        "collect_error": "❌ Source collection failed.",
        "generating": "⏳ The AI report is being generated…",
        "existing_report": "✅ Report #{report_id} was already generated.",
        "cooldown": "⏳ A recent request is still valid; please try again in a few minutes.",
        "generation_error": "❌ Report generation failed.",
        "pipeline_busy": "⏳ The pipeline is busy; please try again shortly.",
        "no_news": "📭 No new reportable stories were found in this period.",
        "ai_unavailable": "⏳ No validated AI route returned acceptable copy; no low-quality report was sent.",
        "report_delivered": "✅ Report #{report_id} was generated and delivered to Telegram.",
        "report_not_delivered": "✅ Report #{report_id} was generated; no Telegram destination is configured.",
        "settings_saved": "✅ Settings saved.",
        "bad_settings": "❌ Invalid setting: {error}",
        "source_not_found": "❌ Source not found.",
        "source_changed": "✅ Source #{source_id} “{name}” was {action}.",
        "source_delete_confirm": "⚠️ Repeat the command with confirm to archive this source:\n/source delete {source_id} confirm",
        "source_command_error": "❌ Source operation failed: {error}",
        "import_caption": "Send a CSV or XLSX file with the caption /sources import.",
        "import_too_large": "❌ Source files must be no larger than 5 MiB.",
        "import_done": "✅ {filename}: {created} created, {updated} updated, {skipped} rejected.",
        "import_error": "❌ Source import failed: {error}",
    },
}


def text(language: str, key: str, **values: Any) -> str:
    catalog = _MESSAGES.get(language, _MESSAGES["fa"])
    template = catalog.get(key, _MESSAGES["fa"].get(key, key))
    return template.format(**values)


def menu_keyboard(language: str) -> dict[str, Any]:
    labels = (
        {
            "now": "گزارش فوری",
            "new": "خبرهای جدید",
            "telegram": "فقط تلگرام",
            "x": "فقط X",
            "web": "فقط وب‌سایت‌ها",
            "github": "فقط GitHub",
            "reddit": "فقط Reddit",
            "comprehensive": "گزارش جامع فعلی",
            "latest": "آخرین گزارش",
            "help": "راهنمای گزارش‌ها",
        }
        if language == "fa"
        else {
            "now": "Report now",
            "new": "New stories",
            "telegram": "Telegram only",
            "x": "X only",
            "web": "Web only",
            "github": "GitHub only",
            "reddit": "Reddit only",
            "comprehensive": "Comprehensive",
            "latest": "Latest report",
            "help": "Help & settings",
        }
    )
    return {
        "inline_keyboard": [
            [
                {"text": labels["now"], "callback_data": "report_now"},
                {"text": labels["new"], "callback_data": "report_new"},
            ],
            [
                {"text": labels["telegram"], "callback_data": "report_telegram"},
                {"text": labels["x"], "callback_data": "report_x"},
            ],
            [
                {"text": labels["web"], "callback_data": "report_web"},
                {"text": labels["github"], "callback_data": "report_github"},
            ],
            [
                {"text": labels["reddit"], "callback_data": "report_reddit"},
                {
                    "text": labels["comprehensive"],
                    "callback_data": "report_comprehensive",
                },
            ],
            [
                {"text": labels["latest"], "callback_data": "latest"},
                {"text": labels["help"], "callback_data": "help"},
            ],
        ]
    }


def bot_commands(language: str) -> list[dict[str, str]]:
    """Commands registered with Telegram's native command menu."""
    descriptions = (
        {
            "start": "بازکردن منوی Newsroom",
            "help": "راهنما و تنظیمات",
            "report": "ساخت گزارش برنامه‌نویسی",
            "latest": "نمایش آخرین گزارش",
            "settings": "تنظیم زبان، تعداد، منابع و زمان‌ها",
            "sources": "مشاهده و مدیریت منابع",
            "schedule": "نمایش زمان‌بندی",
            "status": "وضعیت امن سیستم",
            "collect": "جمع‌آوری فوری منابع",
        }
        if language == "fa"
        else {
            "start": "Open the Newsroom menu",
            "help": "Help and settings",
            "report": "Generate a programming report",
            "latest": "Show the latest report",
            "settings": "Configure language, count, sources and times",
            "sources": "View and manage sources",
            "schedule": "Show report schedule",
            "status": "Show safe system status",
            "collect": "Collect sources now",
        }
    )
    return [
        {"command": command, "description": description}
        for command, description in descriptions.items()
    ]


def help_text(snapshot: ControlSnapshot) -> str:
    schedule = " | ".join(snapshot.schedule_times) if snapshot.schedule_enabled else "OFF"
    if snapshot.report_language == "fa":
        schedule = schedule.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
    source_scope = (
        ", ".join(snapshot.report_source_types)
        if snapshot.report_source_types
        else ("همهٔ منابع فعال" if snapshot.report_language == "fa" else "all enabled sources")
    )
    if snapshot.report_language == "en":
        return (
            "👋 Welcome to Newsroom\n\n"
            "A programming-first newsroom that collects, verifies, summarizes and "
            "delivers grounded reports with strong Telegram coverage.\n\n"
            "REPORTS\n"
            "/report — default programming report\n"
            "/report new — only undelivered stories\n"
            "/report comprehensive — extended report\n"
            "/report telegram|x|web|github|reddit — platform-only report\n"
            "/latest — last delivered report\n\n"
            "SETTINGS\n"
            "/settings — current preferences\n"
            "/settings language fa|en\n"
            "/settings count 1..50\n"
            "/settings schedule HH:MM,HH:MM or off\n"
            "/settings sources all|telegram,x,web,github,reddit,youtube\n\n"
            "SOURCES\n"
            "/sources — inventory summary\n"
            "/sources list [type] [page]\n"
            "/source enable|disable <id>\n"
            "/source delete <id> confirm — safe archive; history is retained\n"
            "Upload CSV/XLSX with caption /sources import. Columns: "
            "name,type,url,language,category,trust_class,enabled\n\n"
            "OPERATIONS\n"
            "/status · /collect · /schedule\n\n"
            f"Current: language=en · stories={snapshot.report_story_count} · "
            f"sources={source_scope} · Tehran schedule={schedule}"
        )
    return (
        "👋 به Newsroom خوش آمدید\n"
        "🤖 راهنمای خبرخوان\n\n"
        "خبرخوان حرفه‌ایِ برنامه‌نویسی که منابع را جمع‌آوری و راستی‌آزمایی می‌کند "
        "و با تمرکز ویژه بر تلگرام، گزارش مستند می‌سازد.\n\n"
        "گزارش‌ها\n"
        "/report — گزارش پیش‌فرض برنامه‌نویسی\n"
        "/report new — فقط خبرهای تحویل‌نشده\n"
        "/report comprehensive — گزارش گسترده\n"
        "/report telegram|x|web|github|reddit — گزارش جامع همان پلتفرم\n"
        "/latest — آخرین گزارش تحویل‌شده\n\n"
        "تنظیمات\n"
        "/settings — نمایش تنظیمات فعلی\n"
        "/settings language fa|en\n"
        "/settings count 1..50\n"
        "/settings schedule HH:MM,HH:MM یا off\n"
        "/settings sources all|telegram,x,web,github,reddit,youtube\n\n"
        "مدیریت منابع\n"
        "/sources — خلاصه موجودی\n"
        "/sources list [type] [page]\n"
        "/source enable|disable <id>\n"
        "/source delete <id> confirm — آرشیو امن؛ سوابق حذف نمی‌شوند\n"
        "برای افزودن گروهی، CSV/XLSX را با کپشن /sources import بفرستید. ستون‌ها: "
        "name,type,url,language,category,trust_class,enabled\n\n"
        "عملیات\n"
        "/status · /collect · /schedule\n\n"
        f"تنظیم فعلی: زبان=fa · تعداد خبر={snapshot.report_story_count} · "
        f"منابع={source_scope} · زمان تهران={schedule}"
    )
