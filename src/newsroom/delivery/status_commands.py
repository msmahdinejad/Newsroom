"""Owner-restricted Telegram status commands — safe operational summaries.

Returns Persian-language operational information for the owner-restricted
bot commands (/status, /sources, /collect, /schedule). Never includes local
access values, personal identifiers, session-file contents, tokens, or
protected configuration — only aggregate counts, states, and timestamps.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from newsroom.config import settings
from newsroom.logging import get_logger
from newsroom.storage.models import (
    CollectionRun,
    Delivery,
    EditorialHealth,
    ReportCursor,
    Source,
    SourceInventory,
)

logger = get_logger(__name__)

SCHEDULED_CURSOR_KEY = "scheduled_delivery"


def _safe_ts(ts: datetime | None) -> str:
    if ts is None:
        return "—"
    return ts.strftime("%Y-%m-%d %H:%M UTC")


def _next_tehran_boundary(schedule_times: tuple[str, ...]) -> str:
    """Return the next configured Asia/Tehran report boundary."""
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(settings.timezone or "Asia/Tehran")
        now = datetime.now(tz)
        nxt = None
        for value in schedule_times:
            hour_text, minute_text = value.split(":", maxsplit=1)
            cand = now.replace(
                hour=int(hour_text),
                minute=int(minute_text),
                second=0,
                microsecond=0,
            )
            if cand <= now:
                from datetime import timedelta

                cand = cand + timedelta(days=1)
            if nxt is None or cand < nxt:
                nxt = cand
        return nxt.strftime("%Y-%m-%d %H:%M") + " (تهران)" if nxt else "—"
    except Exception:
        return "—"


def source_totals(db: Session) -> dict[str, dict[str, int]]:
    """Source counts by platform and operational state (enabled/health)."""
    rows = db.execute(
        select(Source.platform, Source.enabled, Source.health_status, func.count(Source.id))
        .group_by(Source.platform, Source.enabled, Source.health_status)
    ).all()
    by_platform: dict[str, dict[str, int]] = {}
    for platform, enabled, health, cnt in rows:
        plat = platform or "legacy"
        bucket = by_platform.setdefault(plat, {"active": 0, "inactive": 0, "healthy": 0, "degraded": 0, "unavailable": 0, "configured": 0})
        if enabled:
            bucket["active"] += int(cnt)
        else:
            bucket["inactive"] += int(cnt)
        if health:
            bucket[health] = bucket.get(health, 0) + int(cnt)
    return by_platform


def inventory_totals(db: Session) -> dict[str, Any]:
    """Reconciliation totals from the authoritative source_inventory."""
    total = db.query(SourceInventory).count()
    by_state: dict[str, int] = {}
    by_platform: dict[str, dict[str, int]] = {}
    inactive_reasons: dict[str, int] = {}
    for inv in db.query(SourceInventory).all():
        by_state[inv.operational_state] = by_state.get(inv.operational_state, 0) + 1
        ps = by_platform.setdefault(inv.platform, {})
        ps[inv.operational_state] = ps.get(inv.operational_state, 0) + 1
        if inv.inactive_reason:
            inactive_reasons[inv.inactive_reason] = inactive_reasons.get(inv.inactive_reason, 0) + 1
    return {
        "total": total,
        "expected": 1344,
        "reconciled": total == 1344,
        "by_state": by_state,
        "by_platform": by_platform,
        "inactive_reasons": inactive_reasons,
    }


def last_collection(db: Session) -> dict[str, Any]:
    run = (
        db.query(CollectionRun)
        .order_by(CollectionRun.started_at.desc())
        .first()
    )
    if not run:
        return {"status": "none", "started_at": "—", "items": 0}
    return {
        "status": run.status,
        "started_at": _safe_ts(run.started_at),
        "items": run.items_collected,
        "source_id": run.source_id,
    }


def editorial_state(db: Session) -> dict[str, Any]:
    h = db.query(EditorialHealth).first()
    if not h:
        return {
            "enabled": settings.editorial_enabled,
            "provider": "multi_provider_router",
            "has_model": False,
        }
    return {
        "enabled": h.enabled,
        "provider": h.provider,
        "has_model": bool(h.model),
        "last_success": _safe_ts(h.last_success_at),
        "last_failure": _safe_ts(h.last_failure_at),
        "fallback_count": h.fallback_count,
        "rate_limited": h.rate_limited,
    }


def last_delivery(db: Session) -> dict[str, Any]:
    d = db.query(Delivery).order_by(Delivery.id.desc()).first()
    cursor = db.query(ReportCursor).filter_by(cursor_key=SCHEDULED_CURSOR_KEY).first()
    return {
        "status": d.status if d else "none",
        "delivered_at": _safe_ts(d.delivered_at) if d else "—",
        "message_ids_count": len(d.message_ids) if d and d.message_ids else 0,
        "cursor_report_id": cursor.report_id if cursor else None,
        "cursor_advanced_at": _safe_ts(cursor.advanced_at) if cursor else "—",
    }


def status_text(db: Session, language: str = "fa") -> str:
    """Compose the localized /status summary."""
    from newsroom.control import NewsroomControl

    control = NewsroomControl(db).settings()
    inv = inventory_totals(db)
    last = last_collection(db)
    ed = editorial_state(db)
    dlv = last_delivery(db)
    active_sources = db.query(Source).filter(Source.enabled.is_(True)).count()
    inactive_sources = db.query(Source).filter(Source.enabled.is_(False)).count()
    unhealthy = (
        db.query(Source)
        .filter(Source.enabled.is_(True), Source.health_status.in_(["degraded", "unavailable"]))
        .count()
    )
    inv_inactive = inv["by_state"].get("inactive", 0) + inv["by_state"].get("invalid", 0)

    if language == "en":
        return "\n".join(
            [
                "📊 Newsroom status",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                f"Active collectors: {active_sources}",
                f"Inactive sources: {inactive_sources}",
                f"Unhealthy active sources: {unhealthy}",
                f"Inventory: {inv['total']}/{inv['expected']} ({'✓' if inv['reconciled'] else '✗'})",
                f"Inactive/invalid queue: {inv_inactive}",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                f"Last collection: {last['status']} @ {last['started_at']} ({last['items']} items)",
                f"Editorial AI: {'enabled' if ed.get('enabled') else 'disabled'} | {ed.get('provider','deterministic')}",
                f"Last delivery: {dlv['status']} @ {dlv['delivered_at']} ({dlv['message_ids_count']} messages)",
                f"Scheduled cursor: {dlv['cursor_advanced_at']}",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                f"Next report: {_next_tehran_boundary(control.schedule_times) if control.schedule_enabled else 'OFF'}",
            ]
        )
    lines = [
        "📊 وضعیت سیستم خبرخوان",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"منابع فعال (collectors): {active_sources}",
        f"منابع غیرفعال: {inactive_sources}",
        f"منابع ناسالم: {unhealthy}",
        f"موجودی منابع: {inv['total']}/{inv['expected']} ({'✓' if inv['reconciled'] else '✗'})",
        f"صف غیرفعال/نامعتبر: {inv_inactive}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"آخرین جمع‌آوری: {last['status']} @ {last['started_at']} ({last['items']} آیتم)",
        f"هوش مصنوعی تحریریه: {'فعال' if ed.get('enabled') else 'غیرفعال'} | {ed.get('provider','deterministic')}",
        f"آخرین تحویل: {dlv['status']} @ {dlv['delivered_at']} ({dlv['message_ids_count']} پیام)",
        f"نشانگر زمان‌بندی: {dlv['cursor_advanced_at']}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"گزارش بعدی: {_next_tehran_boundary(control.schedule_times) if control.schedule_enabled else 'خاموش'}",
    ]
    return "\n".join(lines)


def sources_text(db: Session, language: str = "fa") -> str:
    inv = inventory_totals(db)
    if language == "en":
        lines = [
            "📚 Source inventory",
            f"Total: {inv['total']}/{inv['expected']}",
            f"Active: {inv['by_state'].get('active', 0)} | "
            f"Inactive: {inv['by_state'].get('inactive', 0)} | "
            f"Invalid: {inv['by_state'].get('invalid', 0)}",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "By platform:",
        ]
        for platform in sorted(inv["by_platform"]):
            states = inv["by_platform"][platform]
            parts = [f"{key}:{value}" for key, value in sorted(states.items()) if value]
            lines.append(f"• {platform}: " + " | ".join(parts))
        return "\n".join(lines)
    lines = [
        "📚 آمار منابع",
        f"مجموع: {inv['total']}/{inv['expected']}",
        f"فعال: {inv['by_state'].get('active', 0)} | "
        f"غیرفعال: {inv['by_state'].get('inactive', 0)} | "
        f"نامعتبر: {inv['by_state'].get('invalid', 0)}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "به تفکیک پلتفرم:",
    ]
    for plat in sorted(inv["by_platform"]):
        ps = inv["by_platform"][plat]
        parts = [f"{k}:{v}" for k, v in sorted(ps.items()) if v]
        lines.append(f"• {plat}: " + " | ".join(parts))
    if inv["inactive_reasons"]:
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("دلایل غیرفعالی:")
        for reason, cnt in sorted(inv["inactive_reasons"].items(), key=lambda x: -x[1]):
            lines.append(f"• {reason}: {cnt}")
    return "\n".join(lines)


def schedule_text(db: Session, language: str = "fa") -> str:
    from newsroom.control import NewsroomControl

    control = NewsroomControl(db).settings()
    dlv = last_delivery(db)
    schedule = "  •  ".join(control.schedule_times) if control.schedule_enabled else "OFF"
    next_boundary = (
        _next_tehran_boundary(control.schedule_times)
        if control.schedule_enabled
        else "OFF"
    )
    if language == "en":
        return "\n".join(
            [
                "⏰ Report schedule",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                f"Automatic reports (Tehran): {schedule}",
                f"Next report: {next_boundary}",
                f"Stories per default report: {control.report_story_count}",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                f"Last successful delivery: {dlv['cursor_advanced_at']}",
                f"Scheduled cursor report: #{dlv['cursor_report_id'] or '—'}",
                "The cursor advances only after complete delivery.",
            ]
        )
    schedule = schedule.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
    lines = [
        "⏰ زمان‌بندی گزارش‌ها",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"گزارش‌های خودکار (تهران): {schedule}",
        f"گزارش بعدی: {next_boundary}",
        f"تعداد خبر در گزارش پیش‌فرض: {control.report_story_count}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"آخرین تحویل موفق: {dlv['cursor_advanced_at']}",
        f"گزارش نشانگر زمان‌بندی: #{dlv['cursor_report_id'] or '—'}",
        "محدوده فقط پس از تحویل کامل پیش می‌رود.",
    ]
    return "\n".join(lines)


__all__ = [
    "editorial_state",
    "inventory_totals",
    "last_collection",
    "last_delivery",
    "schedule_text",
    "source_totals",
    "sources_text",
    "status_text",
]
