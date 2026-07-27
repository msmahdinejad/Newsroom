"""Production Agent-Reach capability doctor and bounded X timeline worker."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from newsroom.config import settings
from newsroom.logging import get_logger, setup_logging
from newsroom.pipeline.social_collect import collect_agent_reach_sources
from newsroom.sources.agent_reach.adapters import (
    apply_default_production_decisions,
    upgrade_x_to_production,
)
from newsroom.sources.agent_reach.registry import AgentReachCapabilityRegistry
from newsroom.sources.agent_reach.runner import ControlledRunner, RunnerError, validate_x_handle
from newsroom.storage.database import get_db
from newsroom.storage.models import AgentReachBackendState, Source, SourceInventory

logger = get_logger(__name__)

PINNED_REVISION = "1494c2ab239e7355a77e7cceaf3271453a1f34b5"
_STATUS_FILE = Path("/tmp/newsroom_agent_reach_status.json")


def _write_status(payload: dict[str, Any]) -> None:
    """Persist only safe aggregate runtime metadata."""
    safe = {
        key: payload[key]
        for key in (
            "status",
            "doctor_status",
            "doctor_at",
            "x_auth_configured",
            "x_inventory_activated",
            "x_sources_attempted",
            "x_new_items",
            "x_failures",
            "last_cycle_at",
            "failure_category",
        )
        if key in payload
    }
    with contextlib.suppress(OSError):
        _STATUS_FILE.write_text(json.dumps(safe, ensure_ascii=False, default=str), encoding="utf-8")


def _x_access_env() -> dict[str, str]:
    auth_token = os.environ.get("TWITTER_AUTH_TOKEN", "")
    ct0 = os.environ.get("TWITTER_CT0", "")
    if not auth_token or not ct0:
        return {}
    return {"TWITTER_AUTH_TOKEN": auth_token, "TWITTER_CT0": ct0}


def _x_handle(inventory: SourceInventory) -> str:
    candidate = (inventory.handle or "").strip().lstrip("@")
    if not candidate:
        parts = [part for part in urlparse(inventory.public_url).path.split("/") if part]
        candidate = parts[0] if parts else ""
    return validate_x_handle(candidate)


def _unique_source_name(session: Session, base: str, workbook_id: int) -> str:
    candidate = base or f"x-source-{workbook_id}"
    existing = session.query(Source).filter_by(name=candidate).first()
    if existing is None or existing.workbook_id == workbook_id:
        return candidate
    return f"{candidate} [#{workbook_id}]"


def activate_x_inventory_sources(session: Session) -> dict[str, int]:
    """Account for workbook X rows without calling untested rows active."""
    report = {"eligible": 0, "activated": 0, "updated": 0, "invalid": 0}
    rows = (
        session.query(SourceInventory)
        .filter(SourceInventory.platform == "X / Twitter")
        .order_by(SourceInventory.workbook_id)
        .all()
    )
    for inventory in rows:
        if inventory.validation_result != "ok":
            report["invalid"] += 1
            continue
        try:
            handle = _x_handle(inventory)
        except RunnerError:
            inventory.operational_state = "inactive"
            inventory.inactive_reason = "x_invalid_handle"
            report["invalid"] += 1
            continue

        report["eligible"] += 1
        source = (
            session.query(Source).filter_by(stable_identity=inventory.stable_identity).first()
            if inventory.stable_identity
            else None
        )
        if source is None and inventory.source_id:
            source = session.get(Source, inventory.source_id)

        config = {
            "handle": handle,
            "auth_token_env": "TWITTER_AUTH_TOKEN",
            "ct0_env": "TWITTER_CT0",
            "max_posts": 20,
            "include_replies": False,
            "include_reposts": False,
        }
        if source is None:
            source = Source(
                name=_unique_source_name(session, inventory.name, inventory.workbook_id),
                type="x_timeline",
                url=inventory.public_url,
                language=(inventory.language or "en")[:10],
                category=(inventory.topic or "general")[:100],
                trust_class="reputable",
                enabled=False,
                config=config,
                stable_identity=inventory.stable_identity,
                workbook_id=inventory.workbook_id,
                platform=inventory.platform,
                inactive_reason="x_pending_live_validation",
                health_status="configured",
                validation_status="untested",
                no_cursor_reason="x_pending_live_validation",
            )
            session.add(source)
            session.flush()
            report["activated"] += 1
        else:
            preserved = dict(source.config or {})
            preserved.update(config)
            source.config = preserved
            source.type = "x_timeline"
            source.url = inventory.public_url
            source.stable_identity = inventory.stable_identity
            source.workbook_id = inventory.workbook_id
            source.platform = inventory.platform
            if source.health_status not in ("healthy", "degraded"):
                source.health_status = "configured"
            report["updated"] += 1

        if source.last_attempt_at is None:
            source.last_attempt_at = source.last_success_at or source.last_error_at
        is_live_valid = bool(source.last_attempt_at and source.last_success_at)
        source.enabled = is_live_valid
        if is_live_valid:
            source.validation_status = "valid"
            source.failure_category = None
            source.no_cursor_reason = None
            source.inactive_reason = None
        elif source.last_attempt_at:
            source.validation_status = "failed"
            source.failure_category = source.failure_category or "x_collection_failed"
            source.no_cursor_reason = source.no_cursor_reason or "collection_failed_before_cursor"
            source.inactive_reason = source.inactive_reason or "x_collection_failed"
        else:
            source.validation_status = "untested"
            source.no_cursor_reason = "x_pending_live_validation"
            source.inactive_reason = "x_pending_live_validation"

        inventory.source_id = source.id
        inventory.operational_state = "active" if is_live_valid else "inactive"
        inventory.inactive_reason = None if is_live_valid else source.inactive_reason
    session.flush()
    return report


def reconcile_x_inventory_sources(session: Session) -> None:
    """Mirror bounded live-attempt outcomes to the workbook inventory."""
    rows = (
        session.query(SourceInventory)
        .filter(SourceInventory.platform == "X / Twitter")
        .order_by(SourceInventory.workbook_id)
        .all()
    )
    for inventory in rows:
        source = session.get(Source, inventory.source_id) if inventory.source_id else None
        if source is None:
            inventory.operational_state = "inactive"
            inventory.inactive_reason = "x_source_not_materialized"
            continue
        is_live_valid = bool(
            source.last_attempt_at
            and source.validation_status == "valid"
            and source.last_success_at
        )
        source.enabled = is_live_valid
        inventory.operational_state = "active" if is_live_valid else "inactive"
        inventory.inactive_reason = None if is_live_valid else (
            source.inactive_reason or source.failure_category or "x_pending_live_validation"
        )
    session.flush()


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _persist_registry(session: Session, registry: AgentReachCapabilityRegistry) -> None:
    for state in registry.to_backend_states():
        row = session.query(AgentReachBackendState).filter_by(channel=state.channel).first()
        if row is None:
            row = AgentReachBackendState(channel=state.channel)
            session.add(row)
        row.pinned_version = PINNED_REVISION
        row.selected_backend = state.selected_backend
        row.fallback_backends = state.fallback_backends
        row.healthy = state.healthy
        row.last_success_at = _parse_datetime(state.last_success_at)
        row.last_failure_at = _parse_datetime(state.last_failure_at)
        row.failure_category = state.failure_category
        row.degraded = state.degraded
        row.production_ready = state.production_ready
        row.production_approval = state.production_approval
        row.last_doctor_run_at = _parse_datetime(state.last_doctor_run_at)
        row.notes = state.notes
    session.flush()


def _run_doctor() -> AgentReachCapabilityRegistry:
    registry = AgentReachCapabilityRegistry(
        pinned_version=PINNED_REVISION,
        allow_authenticated=True,
    )
    runner = ControlledRunner()
    try:
        result = runner.run("agent-reach", "doctor", [], extra_env=_x_access_env() or None)
        registry.run_doctor(result)
    except RunnerError as exc:
        logger.error("Agent-Reach doctor failed", extra={"failure_category": exc.category})
    apply_default_production_decisions(registry)
    return registry


async def run_cycle() -> dict[str, Any]:
    """Run one doctor + bounded sequential X batch."""
    status: dict[str, Any] = {
        "status": "running",
        "x_auth_configured": bool(_x_access_env()),
        "last_cycle_at": datetime.now(UTC).isoformat(),
    }
    registry = _run_doctor()
    status["doctor_status"] = "error" if registry.doctor_parse_error else "ok"
    status["doctor_at"] = datetime.now(UTC).isoformat()

    with get_db() as db:
        if status["x_auth_configured"]:
            activation = activate_x_inventory_sources(db)
            status["x_inventory_activated"] = activation["activated"] + activation["updated"]
        _persist_registry(db, registry)

    if not status["x_auth_configured"]:
        status.update(
            {
                "status": "degraded",
                "x_sources_attempted": 0,
                "x_new_items": 0,
                "x_failures": 0,
                "failure_category": "x_auth_not_configured",
            }
        )
        _write_status(status)
        return status

    with get_db() as db:
        result = await collect_agent_reach_sources(
            db,
            source_type="x_timeline",
            limit_per_source=20,
            max_sources=max(1, settings.x_worker_batch_size),
            min_source_spacing_seconds=max(0, settings.x_worker_spacing_seconds),
            include_disabled=True,
        )

    with get_db() as db:
        reconcile_x_inventory_sources(db)

    successes = sum(1 for item in result["detail"] if item.get("status") == "ok")
    if successes:
        upgrade_x_to_production(registry)
        with get_db() as db:
            _persist_registry(db, registry)

    status.update(
        {
            "status": "healthy" if successes or result["sources"] == 0 else "degraded",
            "x_sources_attempted": result["sources"],
            "x_new_items": result["new_items"],
            "x_failures": len(result["failed"]),
        }
    )
    if result["failed"] and not successes:
        status["failure_category"] = "x_collection_failed"
    _write_status(status)
    return status


async def _run_worker() -> None:
    while True:
        try:
            result = await run_cycle()
            logger.info(
                "Agent-Reach worker cycle complete",
                extra={
                    "status": result["status"],
                    "x_sources_attempted": result.get("x_sources_attempted", 0),
                    "x_new_items": result.get("x_new_items", 0),
                    "x_failures": result.get("x_failures", 0),
                },
            )
        except Exception as exc:
            category = type(exc).__name__
            logger.error("Agent-Reach worker cycle failed", extra={"failure_category": category})
            _write_status(
                {
                    "status": "degraded",
                    "failure_category": category,
                    "last_cycle_at": datetime.now(UTC).isoformat(),
                }
            )
        await asyncio.sleep(max(30, settings.x_worker_poll_seconds))


def main() -> None:
    setup_logging()
    if settings.agent_reach_pinned_version != PINNED_REVISION:
        raise RuntimeError("Agent-Reach pinned revision mismatch")
    asyncio.run(_run_worker())


if __name__ == "__main__":
    main()
