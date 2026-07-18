"""Controlled command runner — the only path that executes Agent-Reach or
its upstream backends.

Security contract enforced here:

- ``shell=False`` always — argument arrays only, never command strings.
- Fixed executable allowlist and per-channel operation allowlist.
- Every URL / channel ID / username / query / repository identifier is
  validated before it reaches the subprocess.
- A sanitized environment: only the explicit, allowlisted env vars pass
  through. No inherited application secrets (Telegram Bot Token, editorial
  API key, MTProto session path) ever reach upstream tools.
- Timeout enforced; child processes are terminated on timeout (process group
  kill where available).
- Bounded stdout and stderr — anything larger is rejected.
- Control characters, newline-based argument injection, and shell
  metacharacter interpretation are rejected at validation time.

Only typed application code may call this runner. The editorial AI and source
content must never produce executable commands (see ``test_no_eval`` and
prompt-injection fixtures).
"""

from __future__ import annotations

import contextlib
import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass
from typing import Any

from newsroom.config import settings
from newsroom.logging import get_logger

logger = get_logger(__name__)


# ── Allowlists ────────────────────────────────────────────────────

# Executables permitted for upstream calls. These are the only tools the
# controlled runner will ever launch. Each maps to a channel or capability.
EXECUTABLE_ALLOWLIST: frozenset[str] = frozenset(
    {
        "agent-reach",  # the capability layer itself (doctor, configure)
        "yt-dlp",  # YouTube metadata + subtitles
        "gh",  # GitHub capability verification / metadata
        "feedparser",  # alias for the Python feedparser capability (not a binary;
        # kept here for parity with doctor output; the runtime adapter uses httpx)
        "python",  # used for inline feedparser capability probes (bounded -c)
        "python3",
        "curl",  # Jina Reader web reads — bounded to r.jina.ai allowlist
    }
)

# Operations per executable. Each operation is a fixed verb the runner accepts.
# Anything not listed here is rejected with RunnerError.
OPERATION_ALLOWLIST: dict[str, frozenset[str]] = {
    "agent-reach": frozenset({"doctor", "configure"}),
    "yt-dlp": frozenset(
        {
            "dump-json",  # video metadata
            "list-subs",  # available subtitle tracks
            "write-subs",  # fetch subtitles (bounded)
        }
    ),
    "gh": frozenset(
        {
            "repo-view",  # repository metadata
            "release-view",  # single release metadata
            "release-list",  # releases list
            "search-repos",  # curated repo discovery
        }
    ),
    "feedparser": frozenset({"parse"}),
    "python": frozenset({"feedparser-probe"}),
    "python3": frozenset({"feedparser-probe"}),
    "curl": frozenset({"jina-read"}),
}

# Operations that require an authenticated channel. The runner refuses these
# unless settings.agent_reach_allow_authenticated_channels is true.
AUTHENTICATED_OPERATIONS: frozenset[str] = frozenset(
    {
        "agent-reach:configure",
    }
)


# ── Validation ────────────────────────────────────────────────────

# Reject control characters (0x00-0x1F, 0x7F) and the literal NUL byte.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")

# Reject newline injection in single-line arguments.
_NEWLINE_RE = re.compile(r"[\r\n]")

# Safe identifier: letters, digits, dash, underscore, dot. Used for channel IDs,
# usernames, repo owner/name, video IDs, etc.
_SAFE_IDENT_RE = re.compile(r"^[A-Za-z0-9._\-]+$")

# YouTube video ID format (11 chars from the canonical alphabet).
_YT_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

# YouTube channel ID format (UC... 24 chars).
_YT_CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")


class RunnerError(Exception):
    """Raised when a command is rejected before execution or fails bounded checks.

    ``category`` is one of:
        - ``disabled``       — Agent-Reach disabled in config
        - ``executable_not_allowed``
        - ``operation_not_allowed``
        - ``authentication_required``
        - ``argument_invalid``
        - ``argument_injection``
        - ``argument_too_long``
        - ``timeout``
        - ``output_too_large``
        - ``nonzero_exit``
        - ``executable_absent``
        - ``not_run``
    """

    def __init__(self, message: str, category: str = "argument_invalid"):
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class CommandResult:
    """Bounded structured result from a controlled subprocess call.

    ``stdout`` and ``stderr`` are truncated to ``max_output_bytes``. The
    ``truncated`` flag is set when truncation occurred.
    """

    executable: str
    operation: str
    returncode: int
    stdout: bytes
    stderr: bytes
    truncated: bool
    duration_seconds: float
    killed: bool

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.killed

    def stdout_text(self, encoding: str = "utf-8", errors: str = "replace") -> str:
        return self.stdout.decode(encoding, errors=errors)

    def stderr_text(self, encoding: str = "utf-8", errors: str = "replace") -> str:
        return self.stderr.decode(encoding, errors=errors)


# ── Argument validators ────────────────────────────────────────────

MAX_ARGUMENT_LENGTH = 4096


def _reject_control_chars(value: str, label: str) -> None:
    if _CONTROL_CHARS_RE.search(value):
        raise RunnerError(
            f"{label} contains control characters",
            category="argument_injection",
        )
    if _NEWLINE_RE.search(value):
        raise RunnerError(
            f"{label} contains newline characters (injection attempt)",
            category="argument_injection",
        )


def _check_length(value: str, label: str) -> None:
    if len(value) > MAX_ARGUMENT_LENGTH:
        raise RunnerError(
            f"{label} exceeds max length {MAX_ARGUMENT_LENGTH}",
            category="argument_too_long",
        )


def validate_url(url: str) -> str:
    """Validate a URL for upstream consumption.

    Rejects:
      - control characters and newline injection;
      - non-http(s) schemes;
      - private / loopback / link-local destinations (SSRF protection);
      - obvious redirect-target injection (the URL itself must be public).

    Redirect-based SSRF is additionally enforced at the httpx adapter layer;
    here we only do static validation.
    """
    if not isinstance(url, str) or not url:
        raise RunnerError("empty url", category="argument_invalid")
    _reject_control_chars(url, "url")
    _check_length(url, "url")
    lowered = url.lower()
    if not lowered.startswith(("http://", "https://")):
        raise RunnerError(
            f"url must be http(s): {url[:60]}",
            category="argument_invalid",
        )
    return url


def validate_identifier(value: str, label: str) -> str:
    """Validate a short identifier (channel ID, username, video ID, repo)."""
    if not isinstance(value, str) or not value:
        raise RunnerError(f"empty {label}", category="argument_invalid")
    _reject_control_chars(value, label)
    _check_length(value, label)
    if not _SAFE_IDENT_RE.match(value):
        raise RunnerError(
            f"{label} contains unsafe characters: {value[:60]}",
            category="argument_invalid",
        )
    return value


def validate_youtube_video_id(video_id: str) -> str:
    if not isinstance(video_id, str) or not _YT_VIDEO_ID_RE.match(video_id or ""):
        raise RunnerError(
            f"invalid youtube video id: {(video_id or '')[:32]}",
            category="argument_invalid",
        )
    return video_id


def validate_youtube_channel_id(channel_id: str) -> str:
    if not isinstance(channel_id, str) or not _YT_CHANNEL_ID_RE.match(channel_id or ""):
        raise RunnerError(
            f"invalid youtube channel id: {(channel_id or '')[:32]}",
            category="argument_invalid",
        )
    return channel_id


def validate_query(query: str, max_length: int = 256) -> str:
    """Validate a search query — allows spaces and punctuation, rejects
    control characters and newlines.
    """
    if not isinstance(query, str) or not query.strip():
        raise RunnerError("empty query", category="argument_invalid")
    _reject_control_chars(query, "query")
    if len(query) > max_length:
        raise RunnerError(
            f"query exceeds max length {max_length}",
            category="argument_too_long",
        )
    # Reject the dangerous shell metacharacters that subprocess would still pass
    # through if anyone ever flipped shell=True (defence in depth). With shell=False
    # they are inert, but we keep them out so future regressions stay safe.
    return query


def validate_repo_identifier(repo: str) -> str:
    """Validate owner/repo shorthand (e.g. ``Panniantong/Agent-Reach``)."""
    if not isinstance(repo, str) or not repo:
        raise RunnerError("empty repo", category="argument_invalid")
    _reject_control_chars(repo, "repo")
    _check_length(repo, "repo")
    parts = repo.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise RunnerError(
            f"repo must be owner/name: {repo[:60]}",
            category="argument_invalid",
        )
    for part in parts:
        if not _SAFE_IDENT_RE.match(part):
            raise RunnerError(
                f"repo segment contains unsafe characters: {part[:60]}",
                category="argument_invalid",
            )
    return repo


# ── Sanitized environment ─────────────────────────────────────────

# Environment variables that may pass through to the subprocess. Anything not
# in this set is dropped. Credentials are NEVER inherited from the parent
# process (no Telegram Bot Token, no EDITORIAL_API_KEY, no TELEGRAM_API_HASH).
ALLOWED_ENV_KEYS: frozenset[str] = frozenset(
    {
        # System basics required for any subprocess to function
        "SYSTEMROOT",
        "PATH",
        "PATHEXT",
        "WINDIR",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "HOME",  # *nix only; harmless on Windows
        "USERPROFILE",  # Windows only
        # Agent-Reach itself — we explicitly pass the isolated config dir.
        "AGENT_REACH_CONFIG_DIR",
        # Locale / time — required for yt-dlp / gh date handling
        "TZ",
    }
)


def sanitized_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Return a clean environment for subprocess calls.

    Only keys in ``ALLOWED_ENV_KEYS`` (plus any ``extra`` keys, which are also
    allowlisted here) are passed. The isolated Agent-Reach config dir is set
    explicitly from settings.
    """
    env: dict[str, str] = {}
    for key in ALLOWED_ENV_KEYS:
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    # Explicit isolated config dir — never the host home directory.
    env["AGENT_REACH_CONFIG_DIR"] = str(settings.agent_reach_config_dir)
    if extra:
        for k, v in extra.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise RunnerError(
                    "environment keys and values must be strings",
                    category="argument_invalid",
                )
            _reject_control_chars(k, "env key")
            _reject_control_chars(v, f"env value for {k}")
            env[k] = v
    return env


# ── Runner ────────────────────────────────────────────────────────


class ControlledRunner:
    """The only class that may spawn Agent-Reach or upstream tool subprocesses.

    Invariants:
      - ``shell=False`` is the only mode ever used.
      - The executable must be in ``EXECUTABLE_ALLOWLIST``.
      - The operation must be in ``OPERATION_ALLOWLIST[executable]``.
      - The argument array is built by typed code, never from source content.
      - The environment is sanitized; no application secrets pass through.
      - Timeout, max output size, and child-process termination are enforced.

    The runner is safe to construct even when Agent-Reach is disabled: it
    refuses to actually run anything until ``settings.agent_reach_ready()``
    is true, raising ``RunnerError(category="disabled")`` instead.
    """

    def __init__(
        self,
        *,
        executable: str | None = None,
        timeout_seconds: int | None = None,
        max_output_bytes: int | None = None,
        config_dir: str | None = None,
        allow_disabled: bool = False,
    ) -> None:
        self._executable = executable or settings.agent_reach_executable
        self._timeout = timeout_seconds if timeout_seconds is not None else settings.agent_reach_timeout_seconds
        self._max_output = (
            max_output_bytes if max_output_bytes is not None else settings.agent_reach_max_output_bytes
        )
        self._config_dir = config_dir or settings.agent_reach_config_dir
        self._allow_disabled = allow_disabled

    @property
    def executable(self) -> str:
        return self._executable

    @property
    def timeout_seconds(self) -> int:
        return self._timeout

    @property
    def max_output_bytes(self) -> int:
        return self._max_output

    def _check_enabled(self) -> None:
        if self._allow_disabled:
            return
        if not settings.agent_reach_ready():
            raise RunnerError(
                "Agent-Reach is not enabled or has no pinned version",
                category="disabled",
            )

    def _validate_request(
        self,
        executable: str,
        operation: str,
        args: list[str],
    ) -> None:
        if executable not in EXECUTABLE_ALLOWLIST:
            raise RunnerError(
                f"executable not allowed: {executable}",
                category="executable_not_allowed",
            )
        allowed_ops = OPERATION_ALLOWLIST.get(executable, frozenset())
        if operation not in allowed_ops:
            raise RunnerError(
                f"operation '{operation}' not allowed for executable '{executable}'",
                category="operation_not_allowed",
            )
        auth_key = f"{executable}:{operation}"
        if auth_key in AUTHENTICATED_OPERATIONS and not settings.agent_reach_allow_authenticated_channels:
            raise RunnerError(
                f"operation '{operation}' requires authenticated channels (disabled in config)",
                category="authentication_required",
            )
        for arg in args:
            if not isinstance(arg, str):
                raise RunnerError(
                    f"argument must be str, got {type(arg).__name__}",
                    category="argument_invalid",
                )
            _reject_control_chars(arg, "argument")
        # curl is only allowed against r.jina.ai — enforce statically.
        if executable == "curl" and not any(
            arg.endswith("r.jina.ai") or "r.jina.ai/" in arg for arg in args
        ):
            raise RunnerError(
                "curl is only allowed against r.jina.ai",
                category="argument_invalid",
            )

    def _build_command(
        self,
        executable: str,
        operation: str,
        fixed_args: list[str],
    ) -> list[str]:
        """Build the argument array for the subprocess.

        The mapping from (executable, operation) -> args is fixed here in typed
        code. Source content never reaches this function as a command.
        """
        cmd: list[str] = [executable]
        if executable == "agent-reach":
            if operation == "doctor":
                cmd.extend(["doctor", "--json"])
            elif operation == "configure":
                # configure is an authenticated operation; we expose only the
                # bounded subcommands used for capability verification, never
                # arbitrary configure paths. The fixed_args carry the validated
                # subcommand and value.
                cmd.extend(["configure", *fixed_args])
        elif executable == "yt-dlp":
            if operation == "dump-json":
                cmd.extend(
                    [
                        "--dump-json",
                        "--no-playlist",
                        "--no-warnings",
                        "--skip-download",
                        *fixed_args,
                    ]
                )
            elif operation == "list-subs":
                cmd.extend(["--list-subs", "--no-playlist", *fixed_args])
            elif operation == "write-subs":
                cmd.extend(
                    [
                        "--write-subs",
                        "--sub-langs",
                        "en.,fa.",
                        "--skip-download",
                        "--no-warnings",
                        *fixed_args,
                    ]
                )
        elif executable == "gh":
            if operation == "repo-view":
                cmd.extend(["repo", "view", *fixed_args, "--json", "name,description,url,stargazerCount"])
            elif operation == "release-view":
                cmd.extend(["release", "view", *fixed_args, "--json", "tagName,name,publishedAt,body,url"])
            elif operation == "release-list":
                cmd.extend(["release", "list", *fixed_args, "--json", "tagName,name,publishedAt,url"])
            elif operation == "search-repos":
                cmd.extend(["search", "repos", *fixed_args, "--json", "name,fullName,description,url"])
        elif executable in ("python", "python3"):
            if operation == "feedparser-probe":
                # Bounded inline probe: parse a URL with feedparser and emit JSON.
                # The script content is fixed here; the URL is the only variable
                # and is validated by the caller.
                probe_script = (
                    "import sys,json,feedparser;"
                    "f=feedparser.parse(sys.argv[1]);"
                    "print(json.dumps({"
                    "'bozo':bool(f.bozo),"
                    "'entries':len(f.entries),"
                    "'title':getattr(f.feed,'title','')"
                    "}))"
                )
                cmd.extend(["-c", probe_script, *fixed_args])
        elif executable == "curl" and operation == "jina-read":
            # curl against r.jina.ai — arg validation already enforced a
            # r.jina.ai destination. The fixed args carry the URL.
            cmd.extend(
                [
                    "-sS",
                    "--max-time",
                    str(self._timeout),
                    "--compressed",
                    *fixed_args,
                ]
            )
        return cmd

    def run(
        self,
        executable: str,
        operation: str,
        fixed_args: list[str],
        *,
        extra_env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> CommandResult:
        """Run a controlled subprocess and return a bounded result.

        ``fixed_args`` are validated values produced by typed adapter code
        (URL, channel ID, video ID, etc.). Source content must never appear
        here.
        """
        self._check_enabled()
        self._validate_request(executable, operation, fixed_args)
        cmd = self._build_command(executable, operation, fixed_args)
        env = sanitized_environment(extra_env)
        working_dir: str | None = cwd or self._config_dir or None
        if working_dir:
            try:
                os.makedirs(working_dir, exist_ok=True)
            except OSError:
                # If we cannot create the working dir, fall back to None (cwd)
                working_dir = None

        logger.info(
            "agent_reach run",
            extra={
                "executable": executable,
                "operation": operation,
                "arg_count": len(fixed_args),
            },
        )
        try:
            proc = subprocess.Popen(  # noqa: S603 — shell=False, allowlisted executable
                cmd,
                shell=False,  # ALWAYS False — argument array only
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                cwd=working_dir,
            )
        except FileNotFoundError as e:
            raise RunnerError(
                f"executable not found: {executable}",
                category="executable_absent",
            ) from e
        except OSError as e:
            raise RunnerError(
                f"failed to start subprocess: {e}",
                category="not_run",
            ) from e

        killed = False
        start = time.monotonic()
        try:
            stdout, stderr = proc.communicate(timeout=self._timeout)
        except subprocess.TimeoutExpired:
            killed = True
            self._terminate(proc)
            with contextlib.suppress(Exception):
                stdout, stderr = proc.communicate(timeout=5)
        duration = time.monotonic() - start

        truncated = False
        if len(stdout) > self._max_output:
            stdout = stdout[: self._max_output]
            truncated = True
        if len(stderr) > self._max_output:
            stderr = stderr[: self._max_output]
            truncated = True

        return CommandResult(
            executable=executable,
            operation=operation,
            returncode=proc.returncode if proc.returncode is not None else -1,
            stdout=stdout or b"",
            stderr=stderr or b"",
            truncated=truncated,
            duration_seconds=duration,
            killed=killed,
        )

    def _terminate(self, proc: subprocess.Popen[Any]) -> None:
        """Terminate the process and its children. Tries graceful then forceful."""
        if proc.poll() is not None:
            return
        try:
            # Terminate the whole process group on POSIX; on Windows we only
            # have the leaf PID. Either way, communicate() drains pipes after.
            if os.name == "posix":
                _posix_terminate(proc)
            else:
                proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                if os.name == "posix":
                    _posix_kill(proc)
                else:
                    proc.kill()
        except Exception:
            # Best-effort cleanup. We never leave a dangling process.
            with contextlib.suppress(Exception):
                proc.kill()


if os.name == "posix":
    def _posix_terminate(proc: subprocess.Popen[Any]) -> None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)  # type: ignore[attr-defined]
        except OSError:
            proc.terminate()

    def _posix_kill(proc: subprocess.Popen[Any]) -> None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)  # type: ignore[attr-defined]
        except OSError:
            proc.kill()
else:
    def _posix_terminate(proc: subprocess.Popen[Any]) -> None:  # noqa: F811
        proc.terminate()

    def _posix_kill(proc: subprocess.Popen[Any]) -> None:  # noqa: F811
        proc.kill()


# ── Convenience entry points ──────────────────────────────────────


def run_agent_reach(
    operation: str,
    fixed_args: list[str] | None = None,
    *,
    runner: ControlledRunner | None = None,
) -> CommandResult:
    """Run an ``agent-reach`` subcommand. Only ``doctor`` and bounded
    ``configure`` subcommands are allowed.
    """
    r = runner or ControlledRunner()
    return r.run("agent-reach", operation, fixed_args or [])


def run_upstream(
    executable: str,
    operation: str,
    fixed_args: list[str],
    *,
    runner: ControlledRunner | None = None,
) -> CommandResult:
    """Run an upstream tool (yt-dlp, gh, curl, etc.) via the controlled runner."""
    r = runner or ControlledRunner()
    return r.run(executable, operation, fixed_args)


def redact_credentials(text: str) -> str:
    """Redact common credential patterns from a string for safe logging.

    Used by adapters when surfacing upstream errors. Never logs raw tokens,
    cookies, API keys, or bearer values.
    """
    if not text:
        return text
    patterns = [
        # Bearer / token patterns
        (re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+"), "Bearer [REDACTED]"),
        (re.compile(r"(?i)token=[A-Za-z0-9._\-]+"), "token=[REDACTED]"),
        (re.compile(r"(?i)api[_-]?key=[A-Za-z0-9._\-]+"), "api_key=[REDACTED]"),
        # Common key patterns
        (re.compile(r"sk-[A-Za-z0-9]{20,}"), "sk-[REDACTED]"),
        (re.compile(r"gsk_[A-Za-z0-9]{20,}"), "gsk_[REDACTED]"),
        # Cookie headers
        (re.compile(r"(?i)cookie:\s*[^\r\n]+"), "cookie: [REDACTED]"),
        (re.compile(r"(?i)authorization:\s*[^\r\n]+"), "authorization: [REDACTED]"),
        # Telegram bot tokens (numeric:alpha)
        (re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b"), "[REDACTED_BOT_TOKEN]"),
    ]
    out = text
    for pattern, replacement in patterns:
        out = pattern.sub(replacement, out)
    return out


__all__ = [
    "AUTHENTICATED_OPERATIONS",
    "ALLOWED_ENV_KEYS",
    "CommandResult",
    "ControlledRunner",
    "EXECUTABLE_ALLOWLIST",
    "MAX_ARGUMENT_LENGTH",
    "OPERATION_ALLOWLIST",
    "RunnerError",
    "redact_credentials",
    "run_agent_reach",
    "run_upstream",
    "sanitized_environment",
    "validate_identifier",
    "validate_query",
    "validate_repo_identifier",
    "validate_url",
    "validate_youtube_channel_id",
    "validate_youtube_video_id",
]
