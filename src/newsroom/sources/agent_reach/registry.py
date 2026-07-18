"""Agent-Reach capability + backend registry.

Parses ``agent-reach doctor --json`` output into a typed registry. The registry
records:

- channel name (web, youtube, x, reddit, github, rss, linkedin, instagram,
  facebook, tiktok, bilibili, xiaohongshu, v2ex, xueqiu, podcast, search);
- enabled state;
- Agent-Reach health (true/false/unknown);
- selected backend (e.g. ``yt-dlp``);
- fallback backends (e.g. ``OpenCLI``, ``bird``);
- authentication requirement;
- whether the channel is suitable for unattended operation;
- last successful check;
- failure category;
- degraded state;
- production approval state (``approved`` / ``approved_with_auth`` /
  ``manual_discovery_only`` / ``deferred`` / ``rejected``).

Doctor output is parsed defensively. A channel is not production-ready just
because the executable exists — the registry requires a bounded real read to
flip ``production_ready`` to True. A channel with no recorded backend is
``unavailable``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from newsroom.config import settings
from newsroom.sources.agent_reach.runner import (
    CommandResult,
    RunnerError,
    run_agent_reach,
)

# ── Enums-as-strings ─────────────────────────────────────────────

CHANNELS = (
    "web",
    "rss",
    "github",
    "youtube",
    "x",
    "reddit",
    "linkedin",
    "instagram",
    "facebook",
    "tiktok",
    "bilibili",
    "xiaohongshu",
    "v2ex",
    "xueqiu",
    "podcast",
    "search",
)

# Channels that require authentication by default (per upstream docs).
AUTHENTICATED_BY_DEFAULT: frozenset[str] = frozenset(
    {
        "x",  # search/timeline/monitoring need cookies or OpenCLI
        "reddit",  # rdt-cli needs login state
        "facebook",
        "instagram",
        "xiaohongshu",
        "linkedin",  # logged-in automation
    }
)

# Channels that the spec calls out as suitable for unattended operation once
# they pass a bounded real read. Updated by live verification.
UNATTENDED_OK_BY_DEFAULT: frozenset[str] = frozenset(
    {
        "web",
        "rss",
        "github",
        "youtube",
        "search",
    }
)


class ChannelStatus:
    """Status values for a channel."""

    AVAILABLE = "available"  # doctor reports healthy, but no bounded real read yet
    UNAVAILABLE = "unavailable"  # doctor reports unhealthy or no backend
    DEGRADED = "degraded"  # backend selected but last read failed
    PRODUCTION_READY = "production_ready"  # bounded real read succeeded
    NOT_CONFIGURED = "not_configured"  # channel not present in doctor output


class ProductionApproval:
    """Final production decision per channel."""

    APPROVED = "production ingestion approved"
    APPROVED_WITH_AUTH = "production ingestion approved with dedicated authentication"
    MANUAL_DISCOVERY = "manual discovery only"
    DEFERRED = "deferred"
    REJECTED = "rejected"


@dataclass
class CapabilityEntry:
    """Typed capability record for a single channel."""

    channel: str
    enabled: bool
    healthy: bool
    selected_backend: str
    fallback_backends: list[str] = field(default_factory=list)
    authentication_required: bool = False
    unattended_ok: bool = False
    last_success_at: str | None = None
    last_failure_at: str | None = None
    failure_category: str | None = None
    degraded: bool = False
    production_approval: str = ProductionApproval.DEFERRED
    production_ready: bool = False  # set only after a bounded real read
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BackendState:
    """Durable backend state record persisted by Newsroom (not Agent-Reach)."""

    channel: str
    pinned_version: str
    selected_backend: str
    fallback_backends: list[str]
    healthy: bool
    last_success_at: str | None
    last_failure_at: str | None
    failure_category: str | None
    degraded: bool
    production_ready: bool
    production_approval: str
    last_doctor_run_at: str
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AgentReachCapabilityRegistry:
    """In-memory registry of channels and their backend/health state.

    Construct from parsed doctor output, mutate via ``mark_success`` /
    ``mark_failure``, and persist via the caller (Newsroom owns durability).

    The registry is intentionally defensive: malformed doctor output produces
    an empty or partial registry — it never raises from data-shape issues.
    """

    def __init__(self, *, pinned_version: str = "", allow_authenticated: bool | None = None) -> None:
        self._pinned_version = pinned_version or settings.agent_reach_pinned_version
        self._allow_authenticated = (
            allow_authenticated
            if allow_authenticated is not None
            else settings.agent_reach_allow_authenticated_channels
        )
        self._entries: dict[str, CapabilityEntry] = {}
        # Initialize every known channel as not_configured.
        for ch in CHANNELS:
            self._entries[ch] = CapabilityEntry(
                channel=ch,
                enabled=False,
                healthy=False,
                selected_backend="",
                authentication_required=ch in AUTHENTICATED_BY_DEFAULT,
                unattended_ok=ch in UNATTENDED_OK_BY_DEFAULT,
                production_approval=ProductionApproval.DEFERRED,
            )
        self._last_doctor_run_at: str | None = None
        self._doctor_raw: dict[str, Any] | None = None
        self._doctor_parse_error: str | None = None

    # ── Access ───────────────────────────────────────────────────

    @property
    def pinned_version(self) -> str:
        return self._pinned_version

    @property
    def last_doctor_run_at(self) -> str | None:
        return self._last_doctor_run_at

    @property
    def doctor_parse_error(self) -> str | None:
        return self._doctor_parse_error

    @property
    def channels(self) -> tuple[str, ...]:
        return CHANNELS

    def get(self, channel: str) -> CapabilityEntry:
        if channel not in self._entries:
            raise KeyError(f"unknown channel: {channel}")
        return self._entries[channel]

    def all_entries(self) -> list[CapabilityEntry]:
        return [self._entries[c] for c in CHANNELS]

    def enabled_channels(self) -> list[CapabilityEntry]:
        return [e for e in self.all_entries() if e.enabled]

    def production_ready_channels(self) -> list[str]:
        return [e.channel for e in self.all_entries() if e.production_ready]

    # ── Mutation ─────────────────────────────────────────────────

    def set_production_approval(self, channel: str, approval: str, *, notes: str = "") -> None:
        entry = self.get(channel)
        entry.production_approval = approval
        if notes:
            entry.notes = notes

    def mark_success(
        self,
        channel: str,
        *,
        backend: str | None = None,
        at: str | None = None,
        production_ready: bool = False,
    ) -> None:
        entry = self.get(channel)
        if backend:
            entry.selected_backend = backend
        entry.healthy = True
        entry.degraded = False
        entry.failure_category = None
        entry.last_success_at = at or datetime.now(UTC).isoformat()
        if production_ready:
            entry.production_ready = True

    def mark_failure(
        self,
        channel: str,
        *,
        category: str,
        at: str | None = None,
    ) -> None:
        entry = self.get(channel)
        entry.healthy = False
        entry.degraded = True
        entry.failure_category = category
        entry.last_failure_at = at or datetime.now(UTC).isoformat()
        entry.production_ready = False

    # ── Doctor parsing ───────────────────────────────────────────

    def parse_doctor_output(self, stdout: str) -> None:
        """Parse ``agent-reach doctor --json`` output into the registry.

        Defensive: malformed JSON or missing fields leave the registry in a
        consistent, empty state. ``doctor_parse_error`` records the issue.
        """
        self._doctor_parse_error = None
        self._last_doctor_run_at = datetime.now(UTC).isoformat()
        if not stdout or not stdout.strip():
            self._doctor_parse_error = "empty doctor output"
            self._doctor_raw = None
            return
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as e:
            self._doctor_parse_error = f"invalid json: {e}"
            self._doctor_raw = None
            return
        if not isinstance(data, dict):
            self._doctor_parse_error = "doctor output is not a JSON object"
            self._doctor_raw = None
            return
        self._doctor_raw = data

        # Agent-Reach v1.5.0 doctor output shape:
        #   {
        #     "version": "1.5.0",
        #     "channels": {
        #       "youtube": {
        #         "available": true,
        #         "active_backend": "yt-dlp",
        #         "fallback_backends": ["OpenCLI"],
        #         "needs_auth": false,
        #         "unattended_ok": true
        #       },
        #       ...
        #     }
        #   }
        channels = data.get("channels")
        if not isinstance(channels, dict):
            # Some versions emit a list of channel objects; handle that too.
            if isinstance(channels, list):
                for item in channels:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("channel") or item.get("name") or "")
                    if name:
                        self._apply_channel_record(name, item)
                return
            self._doctor_parse_error = "doctor output has no 'channels' object"
            return
        for name, record in channels.items():
            if not isinstance(record, dict):
                continue
            self._apply_channel_record(str(name), record)

    def _apply_channel_record(self, name: str, record: dict[str, Any]) -> None:
        # Normalize the name to lower-case and only accept known channels.
        norm = name.lower()
        if norm not in self._entries:
            return
        entry = self._entries[norm]
        available = bool(record.get("available") or record.get("healthy") or record.get("ok"))
        backend = str(record.get("active_backend") or record.get("backend") or record.get("selected") or "")
        fallbacks = record.get("fallback_backends") or record.get("fallbacks") or []
        if not isinstance(fallbacks, list):
            fallbacks = []
        fallbacks = [str(b) for b in fallbacks if b]
        needs_auth = bool(record.get("needs_auth") or record.get("auth_required"))
        unattended = bool(record.get("unattended_ok", norm in UNATTENDED_OK_BY_DEFAULT))

        # Only flip enabled to True if the channel is in the configured allowlist.
        allowed = settings.agent_reach_allowed_channels_set()
        if norm in allowed and available and not (needs_auth and not self._allow_authenticated):
            entry.enabled = True
        entry.healthy = available
        entry.selected_backend = backend
        entry.fallback_backends = fallbacks
        entry.authentication_required = needs_auth or norm in AUTHENTICATED_BY_DEFAULT
        entry.unattended_ok = unattended
        if not backend:
            # No backend selected → unavailable regardless of health flag.
            entry.healthy = False

    # ── Live doctor run ───────────────────────────────────────────

    def run_doctor(self, runner_result: CommandResult | None = None) -> CapabilityEntry | None:
        """Run ``agent-reach doctor`` via the controlled runner and parse it.

        Returns the first production-ready entry, or None if doctor failed.

        When ``runner_result`` is supplied (e.g. by tests with a fake runner),
        the live subprocess call is skipped — this is the credential-free path.
        """
        if runner_result is None:
            try:
                result = run_agent_reach("doctor")
            except RunnerError:
                self._doctor_parse_error = "runner_disabled"
                return None
            if not result.ok:
                self._doctor_parse_error = f"doctor exit={result.returncode}"
                return None
            stdout = result.stdout_text()
        else:
            stdout = runner_result.stdout_text()
            if not runner_result.ok:
                self._doctor_parse_error = f"doctor exit={runner_result.returncode}"
        self.parse_doctor_output(stdout)
        if self._doctor_parse_error:
            return None
        # Return any production_ready entry; otherwise return the first available.
        ready = self.production_ready_channels()
        if ready:
            return self.get(ready[0])
        for entry in self.all_entries():
            if entry.healthy:
                return entry
        return None

    # ── Persistence shape ─────────────────────────────────────────

    def to_backend_states(self) -> list[BackendState]:
        out: list[BackendState] = []
        for entry in self.all_entries():
            out.append(
                BackendState(
                    channel=entry.channel,
                    pinned_version=self._pinned_version,
                    selected_backend=entry.selected_backend,
                    fallback_backends=entry.fallback_backends,
                    healthy=entry.healthy,
                    last_success_at=entry.last_success_at,
                    last_failure_at=entry.last_failure_at,
                    failure_category=entry.failure_category,
                    degraded=entry.degraded,
                    production_ready=entry.production_ready,
                    production_approval=entry.production_approval,
                    last_doctor_run_at=self._last_doctor_run_at or "",
                    notes=entry.notes,
                )
            )
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "pinned_version": self._pinned_version,
            "last_doctor_run_at": self._last_doctor_run_at,
            "doctor_parse_error": self._doctor_parse_error,
            "allow_authenticated": self._allow_authenticated,
            "channels": {c: self._entries[c].to_dict() for c in CHANNELS},
        }


__all__ = [
    "AgentReachCapabilityRegistry",
    "AUTHENTICATED_BY_DEFAULT",
    "BackendState",
    "CapabilityEntry",
    "CHANNELS",
    "ChannelStatus",
    "ProductionApproval",
    "UNATTENDED_OK_BY_DEFAULT",
]
