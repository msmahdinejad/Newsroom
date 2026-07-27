"""Telegram bot — news report commands with access control and idempotency.

When TELEGRAM_BOT_ENABLED is false or token missing: idle with status
disabled/blocked — no network auth, no crash-loop.

Sole Bot API polling owner. No other process uses the token.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from newsroom.config import settings
from newsroom.control import ControlSnapshot, NewsroomControl
from newsroom.delivery.access import deny_message, is_authorized
from newsroom.delivery.client import TelegramBotClient, redact_token
from newsroom.delivery.i18n import bot_commands, help_text, menu_keyboard
from newsroom.delivery.i18n import text as localized_text
from newsroom.delivery.identity import command_request_key, identity_fingerprint
from newsroom.delivery.telegram import TelegramDelivery
from newsroom.logging import get_logger, setup_logging
from newsroom.storage.database import get_db
from newsroom.storage.models import (
    CommandRequest,
    Delivery,
    Report,
    TelegramUpdate,
)

logger = get_logger(__name__)

_DEFAULT_CONTROL = ControlSnapshot(
    report_language="fa",
    report_source_types=(),
    report_story_count=15,
    schedule_times=("00:00", "06:00", "12:00", "18:00"),
    schedule_enabled=True,
)
MENU_KEYBOARD = menu_keyboard("fa")
HELP_TEXT = help_text(_DEFAULT_CONTROL)

# Max update_id offset stored to survive restart
_STATUS_FILE = "/tmp/newsroom_bot_status.json"


def _bot_service_status() -> dict[str, Any]:
    if not settings.telegram_bot_enabled:
        return {"status": "disabled", "feature": "telegram_bot"}
    if not settings.telegram_bot_token:
        return {
            "status": "blocked_by_credentials",
            "feature": "telegram_bot",
            "missing": "TELEGRAM_BOT_TOKEN",
        }
    return {"status": "enabled", "feature": "telegram_bot"}


def _write_status(payload: dict[str, Any]) -> None:
    try:
        with open(_STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except OSError:
        pass


def _read_status() -> dict[str, Any]:
    try:
        with open(_STATUS_FILE, encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
        return data
    except Exception:
        return {}


class TelegramBot:
    """Sole Bot API polling owner with command idempotency and access control."""

    def __init__(self) -> None:
        self.api = TelegramBotClient()
        self._offset = 0
        self._last_update_ts: datetime | None = None
        self._last_delivery_ts: datetime | None = None
        self._bot_info: dict[str, Any] | None = None
        self._polling_alive = False

    async def start(self) -> None:
        setup_logging()
        status = _bot_service_status()

        if status["status"] != "enabled":
            logger.info(f"Telegram bot {status['status']} — idle (no network auth)")
            health = self._health_payload(status)
            _write_status(health)
            while True:
                await asyncio.sleep(3600)
            return

        logger.info("Starting Telegram bot (sole polling owner)")
        _write_status(self._health_payload(status))

        # Verify bot identity
        try:
            me = await self.api.get_me()
            self._bot_info = me.get("result", {})
            logger.info(
                f"Bot identity: @{self._bot_info.get('username', '?')} "
                f"id={self._bot_info.get('id', '?')} token={redact_token()}"
            )
        except Exception as e:
            logger.error(f"Bot identity query failed: {e}")
            _write_status(self._health_payload({
                **status,
                "degraded": ["identity_query_failed"],
            }))

        # Clear any webhook to ensure polling works
        await self.api.delete_webhook()
        with contextlib.suppress(Exception):
            language = self._control_snapshot().report_language
            await self.api.set_my_commands(bot_commands(language))

        self._polling_alive = True
        while True:
            try:
                await self._poll_updates()
                _write_status(self._health_payload(status))
            except Exception as e:
                self._polling_alive = False
                logger.error(f"Bot poll error: {e}")
                _write_status(self._health_payload({
                    **status,
                    "degraded": ["poll_error"],
                }))
                await asyncio.sleep(5)
                self._polling_alive = True

    async def _poll_updates(self) -> None:
        response = await self.api.get_updates(offset=self._offset)
        if not response.get("ok"):
            return
        for update in response.get("result", []):
            self._offset = update["update_id"] + 1
            await self._handle_update(update)

    async def _handle_update(self, update: dict[str, Any]) -> None:
        update_id = update["update_id"]
        update_type = "message" if "message" in update else "callback"

        # Idempotency: check if we already processed this update_id
        with get_db() as db:
            existing = db.query(TelegramUpdate).filter_by(update_id=update_id).first()
            if existing:
                logger.info(f"Update {update_id} already processed ({existing.result}) — skipping")
                return

        # Parse update
        if "message" in update:
            msg = update["message"]
            user_id = msg.get("from", {}).get("id")
            chat_id = msg["chat"]["id"]
            message_text = (msg.get("text") or msg.get("caption") or "").strip()
            command = message_text.lower() if message_text else ""
            document = msg.get("document")
        elif "callback_query" in update:
            cb = update["callback_query"]
            user_id = cb.get("from", {}).get("id")
            chat_id = cb["message"]["chat"]["id"]
            command = cb.get("data", "")
            document = None
            # Answer the callback query to remove the loading spinner
            with contextlib.suppress(Exception):
                await self.api.answer_callback_query(cb["id"])
        else:
            return

        self._last_update_ts = datetime.now(UTC)

        # Access control — checked on EVERY update, not just /start
        if not is_authorized(user_id):
            self._record_update(update_id, update_type, user_id, chat_id, command, "denied")
            # Deny without infrastructure details
            with contextlib.suppress(Exception):
                await self.api.send_message(chat_id, deny_message())
            return

        # Process command
        result = await self._dispatch_command(
            chat_id,
            command,
            user_id,
            update_id,
            update_type,
            document=document,
        )

        self._record_update(update_id, update_type, user_id, chat_id, command, result)
        if result == "ok" and "deliver" in command:
            self._last_delivery_ts = datetime.now(UTC)

    def _record_update(
        self,
        update_id: int,
        update_type: str,
        user_id: int | None,
        chat_id: int | str | None,
        command: str,
        result: str,
    ) -> None:
        """Persist update idempotency record."""
        try:
            with get_db() as db:
                existing = db.query(TelegramUpdate).filter_by(update_id=update_id).first()
                if existing:
                    return
                db.add(TelegramUpdate(
                    update_id=update_id,
                    update_type=update_type,
                    user_fingerprint=identity_fingerprint("user", user_id),
                    chat_fingerprint=identity_fingerprint("chat", chat_id),
                    command=command[:100],
                    result=result,
                ))
        except Exception as e:
            logger.error(f"Failed to record update {update_id}: {e}")

    async def _dispatch_command(
        self,
        chat_id: int | str,
        command: str,
        user_id: int | None,
        update_id: int,
        update_type: str,
        *,
        document: dict[str, Any] | None = None,
    ) -> str:
        """Route command to handler. Returns result string."""
        cmd = command.lower().strip()

        if cmd in ("/start", "/help", "help"):
            await self._send_menu(chat_id)
            return "ok"

        if cmd == "/settings" or cmd.startswith("/settings "):
            return await self._handle_settings(chat_id, cmd)

        if cmd == "/sources import":
            return await self._handle_source_import(chat_id, document)

        if cmd == "/sources list" or cmd.startswith("/sources list "):
            return await self._handle_source_list(chat_id, cmd)

        if cmd.startswith("/source "):
            return await self._handle_source_command(chat_id, cmd)

        if cmd == "/latest" or cmd == "latest":
            return await self._handle_latest(chat_id)

        if cmd == "/status" or cmd == "status":
            return await self._handle_status(chat_id)

        if cmd == "/sources" or cmd == "sources":
            return await self._handle_sources(chat_id)

        if cmd == "/schedule" or cmd == "schedule":
            return self._handle_schedule(chat_id)

        if cmd == "/collect" or cmd == "collect":
            return await self._handle_collect(chat_id)

        report_modes = {
            "/report": "manual",
            "report_now": "manual",
            "/report new": "manual_new",
            "report_new": "manual_new",
            "/report comprehensive": "manual_comprehensive",
            "report_comprehensive": "manual_comprehensive",
            "/report telegram": "platform_telegram",
            "report_telegram": "platform_telegram",
            "/report x": "platform_x",
            "report_x": "platform_x",
            "/report web": "platform_web",
            "report_web": "platform_web",
            "/report github": "platform_github",
            "report_github": "platform_github",
            "/report reddit": "platform_reddit",
            "report_reddit": "platform_reddit",
        }
        if cmd in report_modes:
            # Map command to pipeline mode
            mode = report_modes[cmd]
            return await self._handle_report(chat_id, mode, user_id, update_id)

        # Unknown command — show menu
        await self._send_menu(chat_id)
        return "ok"

    async def _send_menu(self, chat_id: int | str) -> None:
        try:
            snapshot = self._control_snapshot()
            await self.api.send_message(
                chat_id,
                help_text(snapshot),
                reply_markup=menu_keyboard(snapshot.report_language),
            )
        except Exception as e:
            logger.error(f"Send menu failed: {e}")

    def _control_snapshot(self) -> ControlSnapshot:
        with get_db() as db:
            return NewsroomControl(db).settings()

    def _language(self) -> str:
        try:
            return self._control_snapshot().report_language
        except Exception:
            return "fa"

    def _message(self, key: str, **values: Any) -> str:
        return localized_text(self._language(), key, **values)

    async def _handle_settings(self, chat_id: int | str, command: str) -> str:
        parts = command.split(maxsplit=2)
        try:
            with get_db() as db:
                control = NewsroomControl(db)
                if len(parts) == 1:
                    snapshot = control.settings()
                    response = help_text(snapshot)
                else:
                    section = parts[1]
                    value = parts[2].strip() if len(parts) > 2 else ""
                    if section == "language":
                        snapshot = control.configure(language=value)
                    elif section == "count":
                        snapshot = control.configure(story_count=int(value))
                    elif section == "schedule":
                        snapshot = (
                            control.configure(schedule_enabled=False)
                            if value.lower() == "off"
                            else control.configure(
                                schedule_times=value,
                                schedule_enabled=True,
                            )
                        )
                    elif section == "sources":
                        snapshot = control.configure(source_groups=value)
                    else:
                        raise ValueError(
                            "use language, count, schedule, or sources"
                        )
                    response = (
                        localized_text(
                            snapshot.report_language,
                            "settings_saved",
                        )
                        + "\n\n"
                        + help_text(snapshot)
                    )
            if len(parts) > 1 and parts[1] == "language":
                with contextlib.suppress(Exception):
                    await self.api.set_my_commands(
                        bot_commands(snapshot.report_language)
                    )
            await self._send_text(chat_id, response)
            return "ok"
        except (TypeError, ValueError) as exc:
            await self._send_text(
                chat_id,
                localized_text(
                    self._language(),
                    "bad_settings",
                    error=str(exc),
                ),
            )
            return "error"

    async def _handle_source_list(self, chat_id: int | str, command: str) -> str:
        parts = command.split()
        source_type: str | None = None
        page = 1
        if len(parts) >= 3:
            if parts[2].isdigit():
                page = int(parts[2])
            else:
                source_type = parts[2]
        if len(parts) >= 4 and parts[3].isdigit():
            page = int(parts[3])
        try:
            with get_db() as db:
                rows, total = NewsroomControl(db).list_sources(
                    source_type=source_type,
                    page=page,
                )
            language = self._language()
            heading = (
                f"📚 منابع — صفحه {page} از {total} رکورد"
                if language == "fa"
                else f"📚 Sources — page {page}, {total} records"
            )
            lines = [heading, "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"]
            for source in rows:
                state = "✅" if source.enabled else "⏸"
                lines.append(
                    f"{state} #{source.id} · {source.type} · {source.name}\n"
                    f"{source.url}"
                )
            if not rows:
                lines.append("—")
            await self._send_text(chat_id, "\n\n".join(lines))
            return "ok"
        except ValueError as exc:
            await self._send_text(
                chat_id,
                localized_text(
                    self._language(),
                    "source_command_error",
                    error=str(exc),
                ),
            )
            return "error"

    async def _handle_source_command(self, chat_id: int | str, command: str) -> str:
        parts = command.split()
        if len(parts) < 3 or parts[1] not in {"enable", "disable", "delete"}:
            await self._send_text(
                chat_id,
                "/source enable|disable <id>\n/source delete <id> confirm",
            )
            return "error"
        try:
            source_id = int(parts[2])
            action = parts[1]
            if action == "delete" and (
                len(parts) < 4 or parts[3].lower() != "confirm"
            ):
                await self._send_text(
                    chat_id,
                    localized_text(
                        self._language(),
                        "source_delete_confirm",
                        source_id=source_id,
                    ),
                )
                return "error"
            with get_db() as db:
                control = NewsroomControl(db)
                if action == "enable":
                    result = control.set_source_enabled(source_id, True)
                elif action == "disable":
                    result = control.set_source_enabled(source_id, False)
                else:
                    result = control.delete_source(source_id, confirmed=True)
            localized_action = {
                "fa": {
                    "enabled": "فعال شد",
                    "disabled": "غیرفعال شد",
                    "deleted": "آرشیو شد",
                },
                "en": {
                    "enabled": "enabled",
                    "disabled": "disabled",
                    "deleted": "archived",
                },
            }[self._language()][result.action]
            await self._send_text(
                chat_id,
                localized_text(
                    self._language(),
                    "source_changed",
                    source_id=result.source_id,
                    name=result.name,
                    action=localized_action,
                ),
            )
            return "ok"
        except LookupError:
            await self._send_text(
                chat_id,
                localized_text(self._language(), "source_not_found"),
            )
            return "error"
        except (TypeError, ValueError) as exc:
            await self._send_text(
                chat_id,
                localized_text(
                    self._language(),
                    "source_command_error",
                    error=str(exc),
                ),
            )
            return "error"

    async def _handle_source_import(
        self,
        chat_id: int | str,
        document: dict[str, Any] | None,
    ) -> str:
        if not document:
            await self._send_text(
                chat_id,
                localized_text(self._language(), "import_caption"),
            )
            return "error"
        if int(document.get("file_size") or 0) > 5 * 1024 * 1024:
            await self._send_text(
                chat_id,
                localized_text(self._language(), "import_too_large"),
            )
            return "error"
        try:
            filename = str(document.get("file_name") or "sources.csv")
            payload = await self.api.download_file(
                str(document["file_id"]),
                max_bytes=5 * 1024 * 1024,
            )
            with get_db() as db:
                result = NewsroomControl(db).import_sources(filename, payload)
            await self._send_text(
                chat_id,
                localized_text(
                    self._language(),
                    "import_done",
                    filename=result.filename,
                    created=result.created,
                    updated=result.updated,
                    skipped=result.skipped,
                ),
            )
            return "ok"
        except (KeyError, TypeError, ValueError) as exc:
            await self._send_text(
                chat_id,
                localized_text(
                    self._language(),
                    "import_error",
                    error=str(exc),
                ),
            )
            return "error"

    async def _handle_latest(self, chat_id: int | str) -> str:
        """Return latest persisted report — no collection, no generation."""
        try:
            with get_db() as db:
                # Prefer latest delivered report
                report = (
                    db.query(Report)
                    .join(Delivery, Delivery.report_id == Report.id)
                    .filter(Delivery.status == "delivered")
                    .order_by(Report.id.desc())
                    .first()
                )
                if not report:
                    # Fallback: latest report of any kind
                    report = db.query(Report).order_by(Report.id.desc()).first()

                if report:
                    from newsroom.delivery.render import render_report_html
                    chunks = render_report_html(report.content_fa)
                    for chunk in chunks:
                        await self.api.send_message(
                            chat_id,
                            chunk,
                            parse_mode=settings.telegram_parse_mode,
                        )
                    return "ok"
                else:
                    await self.api.send_message(chat_id, self._message("no_report"))
                    return "ok"
        except Exception as e:
            logger.error(f"/latest failed: {e}")
            with contextlib.suppress(Exception):
                await self.api.send_message(chat_id, self._message("latest_error"))
            return "error"

    async def _handle_status(self, chat_id: int | str) -> str:
        """Return the /status safe operational summary."""
        from newsroom.delivery.status_commands import status_text

        try:
            language = self._language()
            with get_db() as db:
                text = status_text(db, language)
            await self._send_text(chat_id, text)
            return "ok"
        except Exception as e:
            logger.error(f"/status failed: {e}")
            with contextlib.suppress(Exception):
                await self._send_text(chat_id, self._message("status_error"))
            return "error"

    async def _handle_sources(self, chat_id: int | str) -> str:
        """Return the /sources inventory summary."""
        from newsroom.delivery.status_commands import sources_text

        try:
            language = self._language()
            with get_db() as db:
                text = sources_text(db, language)
            await self._send_text(chat_id, text)
            return "ok"
        except Exception as e:
            logger.error(f"/sources failed: {e}")
            with contextlib.suppress(Exception):
                await self._send_text(chat_id, self._message("sources_error"))
            return "error"

    def _handle_schedule(self, chat_id: int | str) -> str:
        """Return the /schedule summary (synchronous, DB read-only)."""
        from newsroom.delivery.status_commands import schedule_text

        try:
            language = self._language()
            with get_db() as db:
                text = schedule_text(db, language)
            asyncio.get_running_loop().create_task(self._send_text(chat_id, text))
        except Exception as e:
            logger.error(f"/schedule failed: {e}")
            with contextlib.suppress(Exception):
                asyncio.get_running_loop().create_task(
                    self._send_text(chat_id, self._message("schedule_error"))
                )
        return "ok"

    async def _handle_collect(self, chat_id: int | str) -> str:
        """Run one bounded collection pass (no report generation)."""
        await self._send_text(chat_id, self._message("collecting"))
        try:
            from newsroom.pipeline.collect import collect_sources

            with get_db() as db:
                result = await collect_sources(
                    db,
                    limit_per_source=max(1, settings.collect_limit_per_source),
                    max_sources=max(1, settings.collect_max_sources_per_cycle),
                    source_spacing_seconds=max(
                        0.0,
                        settings.collect_source_spacing_seconds,
                    ),
                )
            await self._send_text(
                chat_id,
                self._message(
                    "collected",
                    items=result.get("new_items", 0),
                    sources=result.get("sources", 0),
                    failed=len(result.get("failed", [])),
                ),
            )
            return "ok"
        except Exception as e:
            logger.error(f"/collect failed: {e}")
            await self._send_text(chat_id, self._message("collect_error"))
            return "error"

    async def _handle_report(
        self,
        chat_id: int | str,
        mode: str,
        user_id: int | None,
        update_id: int,
    ) -> str:
        """Run pipeline under PostgreSQL lock with command idempotency."""
        # Same command from the same identities remains idempotent without
        # persisting the raw Telegram identifiers.
        user_fingerprint = identity_fingerprint("user", user_id)
        chat_fingerprint = identity_fingerprint("chat", chat_id)
        request_key = command_request_key(mode, user_id, chat_id, update_id)

        with get_db() as db:
            existing_req = db.query(CommandRequest).filter_by(request_key=request_key).first()
            if existing_req and existing_req.status == "running":
                await self._send_text(chat_id, self._message("generating"))
                return "busy"
            if existing_req and existing_req.status == "ok" and existing_req.report_id:
                # Already completed — return existing report
                report_id = existing_req.report_id
                db.close()
                await self._send_text(
                    chat_id,
                    self._message("existing_report", report_id=report_id),
                )
                return "ok"
            cooldown_seconds = max(0, settings.manual_cooldown_seconds)
            if cooldown_seconds:
                cutoff = datetime.now(UTC) - timedelta(seconds=cooldown_seconds)
                recent_req = (
                    db.query(CommandRequest)
                    .filter(
                        CommandRequest.request_key != request_key,
                        CommandRequest.user_fingerprint == user_fingerprint,
                        CommandRequest.chat_fingerprint == chat_fingerprint,
                        CommandRequest.status.in_(("running", "ok")),
                        CommandRequest.created_at >= cutoff,
                    )
                    .order_by(CommandRequest.created_at.desc())
                    .first()
                )
                if recent_req:
                    await self._send_text(
                        chat_id,
                        self._message("cooldown"),
                    )
                    return "busy"
            # Create or update request
            if existing_req:
                existing_req.status = "running"
                existing_req.finished_at = None
            else:
                req = CommandRequest(
                    request_key=request_key,
                    command=mode,
                    user_fingerprint=user_fingerprint,
                    chat_fingerprint=chat_fingerprint,
                    status="running",
                )
                db.add(req)
                db.flush()

        await self._send_text(chat_id, self._message("generating"))

        # Run pipeline via authoritative runner
        env = {
            **os.environ,
            "NEWSROOM_JOB_ID": f"manual_{mode}_{update_id}",
            "NEWSROOM_REPORT_MODE": mode,
        }
        loop = asyncio.get_running_loop()

        def _run() -> dict:
            os.environ.update(env)
            from newsroom.pipeline.runner import run_pipeline
            return run_pipeline()

        try:
            result = await loop.run_in_executor(None, _run)
        except Exception as e:
            logger.error(f"Report generation failed: {e}")
            self._finish_request(request_key, "error", None, None)
            await self._send_text(chat_id, self._message("generation_error"))
            return "error"

        if result.get("status") == "busy":
            self._finish_request(request_key, "busy", None, None)
            await self._send_text(chat_id, self._message("pipeline_busy"))
            return "busy"

        if result.get("status") == "ok_empty":
            self._finish_request(request_key, "ok", None, None)
            await self._send_text(chat_id, self._message("no_news"))
            return "ok"

        if result.get("status") != "ok":
            self._finish_request(request_key, "error", None, None)
            if result.get("status") == "ai_unavailable":
                await self._send_text(
                    chat_id,
                    self._message("ai_unavailable"),
                )
            else:
                await self._send_text(chat_id, self._message("generation_error"))
            return "error"

        result_report_id = result.get("report_id")
        if not result_report_id:
            self._finish_request(request_key, "ok", None, None)
            await self._send_text(chat_id, self._message("no_news"))
            return "ok"

        # Deliver the report
        delivery_id: int | None = None
        if settings.telegram_bot_ready():
            td = TelegramDelivery()
            try:
                with get_db() as db:
                    delivery_id = await td.deliver_report(
                        db, result_report_id, chat_id=chat_id
                    )
            finally:
                await td.close()

        self._finish_request(request_key, "ok", result_report_id, delivery_id)

        if delivery_id:
            await self._send_text(
                chat_id,
                self._message("report_delivered", report_id=result_report_id),
            )
        else:
            await self._send_text(
                chat_id,
                self._message(
                    "report_not_delivered",
                    report_id=result_report_id,
                ),
            )
        return "ok"

    def _finish_request(
        self,
        request_key: str,
        status: str,
        report_id: int | None,
        delivery_id: int | None,
    ) -> None:
        """Update command request record."""
        try:
            with get_db() as db:
                req = db.query(CommandRequest).filter_by(request_key=request_key).first()
                if req:
                    req.status = status
                    req.report_id = report_id
                    req.delivery_id = delivery_id
                    req.finished_at = datetime.now(UTC)
        except Exception as e:
            logger.error(f"Failed to finish request {request_key}: {e}")

    async def _send_text(self, chat_id: int | str, text: str) -> None:
        try:
            await self.api.send_message(chat_id, text)
        except Exception as e:
            logger.error(f"Send failed: {e}")

    def _health_payload(self, base_status: dict[str, Any]) -> dict[str, Any]:
        """Deep health check — more than process existence."""
        from newsroom.storage.database import db_health

        payload: dict[str, Any] = {
            **base_status,
            "timestamp": datetime.now(UTC).isoformat(),
            "polling_alive": self._polling_alive,
            "last_update": self._last_update_ts.isoformat() if self._last_update_ts else None,
            "last_delivery": self._last_delivery_ts.isoformat() if self._last_delivery_ts else None,
        }

        # DB connectivity
        payload["db_connected"] = db_health()

        # Authorized users nonempty
        allowed = settings.authorized_user_ids()
        payload["authorized_users_count"] = len(allowed)

        # Bot identity
        if self._bot_info:
            payload["bot_username"] = self._bot_info.get("username")

        # Degraded conditions
        degraded = []
        if base_status.get("status") == "enabled":
            if not payload["db_connected"]:
                degraded.append("database")
            if not allowed:
                degraded.append("empty_allowlist")
            if not self._polling_alive:
                degraded.append("polling_dead")
        if degraded:
            payload["degraded"] = degraded

        return payload


def main() -> None:
    bot = TelegramBot()
    asyncio.run(bot.start())


if __name__ == "__main__":
    main()
