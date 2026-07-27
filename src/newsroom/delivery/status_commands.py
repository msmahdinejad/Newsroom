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
        return nxt.strftime("%Y-%m-%d %H:%M") + " (\u062a\u0647\u0631\u0627\u0646)" if nxt else "—"
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
    """Reconciliation totals from the optional extended inventory."""
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
    accounted = sum(by_state.values())
    return {
        "total": total,
        "accounted": accounted,
        "reconciled": total == accounted,
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
                f"Inventory: {inv['total']} ({inv['accounted']} accounted)",
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
        "📊 \u0648\u0636\u0639\u06cc\u062a \u0633\u06cc\u0633\u062a\u0645 \u062e\u0628\u0631\u062e\u0648\u0627\u0646",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"\u0645\u0646\u0627\u0628\u0639 \u0641\u0639\u0627\u0644 (collectors): {active_sources}",
        f"\u0645\u0646\u0627\u0628\u0639 \u063a\u06cc\u0631\u0641\u0639\u0627\u0644: {inactive_sources}",
        f"\u0645\u0646\u0627\u0628\u0639 \u0646\u0627\u0633\u0627\u0644\u0645: {unhealthy}",
        f"\u0645\u0648\u062c\u0648\u062f\u06cc \u0645\u0646\u0627\u0628\u0639: {inv['total']} ({inv['accounted']})",
        f"\u0635\u0641 \u063a\u06cc\u0631\u0641\u0639\u0627\u0644/\u0646\u0627\u0645\u0639\u062a\u0628\u0631: {inv_inactive}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"\u0622\u062e\u0631\u06cc\u0646 \u062c\u0645\u0639‌\u0622\u0648\u0631\u06cc: {last['status']} @ {last['started_at']} ({last['items']} \u0622\u06cc\u062a\u0645)",
        f"\u0647\u0648\u0634 \u0645\u0635\u0646\u0648\u0639\u06cc \u062a\u062d\u0631\u06cc\u0631\u06cc\u0647: {'\u0641\u0639\u0627\u0644' if ed.get('enabled') else '\u063a\u06cc\u0631\u0641\u0639\u0627\u0644'} | {ed.get('provider','deterministic')}",
        f"\u0622\u062e\u0631\u06cc\u0646 \u062a\u062d\u0648\u06cc\u0644: {dlv['status']} @ {dlv['delivered_at']} ({dlv['message_ids_count']} \u067e\u06cc\u0627\u0645)",
        f"\u0646\u0634\u0627\u0646\u06af\u0631 \u0632\u0645\u0627\u0646‌\u0628\u0646\u062f\u06cc: {dlv['cursor_advanced_at']}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"\u06af\u0632\u0627\u0631\u0634 \u0628\u0639\u062f\u06cc: {_next_tehran_boundary(control.schedule_times) if control.schedule_enabled else '\u062e\u0627\u0645\u0648\u0634'}",
    ]
    return "\n".join(lines)


def sources_text(db: Session, language: str = "fa") -> str:
    inv = inventory_totals(db)
    if language == "en":
        lines = [
            "📚 Source inventory",
            f"Total: {inv['total']} ({inv['accounted']} accounted)",
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
        "📚 \u0622\u0645\u0627\u0631 \u0645\u0646\u0627\u0628\u0639",
        f"\u0645\u062c\u0645\u0648\u0639: {inv['total']} ({inv['accounted']})",
        f"\u0641\u0639\u0627\u0644: {inv['by_state'].get('active', 0)} | "
        f"\u063a\u06cc\u0631\u0641\u0639\u0627\u0644: {inv['by_state'].get('inactive', 0)} | "
        f"\u0646\u0627\u0645\u0639\u062a\u0628\u0631: {inv['by_state'].get('invalid', 0)}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "\u0628\u0647 \u062a\u0641\u06a9\u06cc\u06a9 \u067e\u0644\u062a\u0641\u0631\u0645:",
    ]
    for plat in sorted(inv["by_platform"]):
        ps = inv["by_platform"][plat]
        parts = [f"{k}:{v}" for k, v in sorted(ps.items()) if v]
        lines.append(f"• {plat}: " + " | ".join(parts))
    if inv["inactive_reasons"]:
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("\u062f\u0644\u0627\u06cc\u0644 \u063a\u06cc\u0631\u0641\u0639\u0627\u0644\u06cc:")
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
    schedule = schedule.translate(str.maketrans("0123456789", "\u06f0\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8\u06f9"))
    lines = [
        "⏰ \u0632\u0645\u0627\u0646‌\u0628\u0646\u062f\u06cc \u06af\u0632\u0627\u0631\u0634‌\u0647\u0627",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"\u06af\u0632\u0627\u0631\u0634‌\u0647\u0627\u06cc \u062e\u0648\u062f\u06a9\u0627\u0631 (\u062a\u0647\u0631\u0627\u0646): {schedule}",
        f"\u06af\u0632\u0627\u0631\u0634 \u0628\u0639\u062f\u06cc: {next_boundary}",
        f"\u062a\u0639\u062f\u0627\u062f \u062e\u0628\u0631 \u062f\u0631 \u06af\u0632\u0627\u0631\u0634 \u067e\u06cc\u0634‌\u0641\u0631\u0636: {control.report_story_count}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"\u0622\u062e\u0631\u06cc\u0646 \u062a\u062d\u0648\u06cc\u0644 \u0645\u0648\u0641\u0642: {dlv['cursor_advanced_at']}",
        f"\u06af\u0632\u0627\u0631\u0634 \u0646\u0634\u0627\u0646\u06af\u0631 \u0632\u0645\u0627\u0646‌\u0628\u0646\u062f\u06cc: #{dlv['cursor_report_id'] or '—'}",
        "\u0645\u062d\u062f\u0648\u062f\u0647 \u0641\u0642\u0637 \u067e\u0633 \u0627\u0632 \u062a\u062d\u0648\u06cc\u0644 \u06a9\u0627\u0645\u0644 \u067e\u06cc\u0634 \u0645\u06cc‌\u0631\u0648\u062f.",
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
