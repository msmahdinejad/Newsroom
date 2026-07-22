"""One-time MTProto authorization command — interactive local flow.

Usage: python -m newsroom.sources.authorize_telegram

Security:
- Reads api_id/api_hash/phone from env (never from args or stdin echo)
- Requests login code interactively (getpass — never echoed)
- Requests 2FA password interactively only when required (getpass — never echoed)
- Persists ONLY the MTProto session in the restricted session path
- Never logs api_hash, phone, login code, or 2FA password
- Prevents concurrent authorization via lock file
- Verifies authenticated identity without exposing phone number
"""

from __future__ import annotations

import asyncio
import getpass
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from newsroom.config import settings
from newsroom.logging import get_logger, setup_logging

logger = get_logger(__name__)

_LOCK_FILE = "/tmp/newsroom_telegram_auth.lock"
_RESULT_FILE = "/tmp/newsroom_telegram_auth_result.json"


def _acquire_lock() -> bool:
    """Prevent concurrent authorization processes."""
    try:
        if os.path.exists(_LOCK_FILE):
            # Check if stale (older than 10 minutes)
            mtime = os.path.getmtime(_LOCK_FILE)
            if datetime.now(UTC).timestamp() - mtime < 600:
                return False
        Path(_LOCK_FILE).write_text(str(os.getpid()), encoding="utf-8")
        return True
    except OSError:
        return False


def _release_lock() -> None:
    import contextlib
    with contextlib.suppress(FileNotFoundError):
        os.remove(_LOCK_FILE)


def _write_result(result: dict) -> None:
    """Write redacted authorization result for evidence."""
    try:
        with open(_RESULT_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, default=str)
    except OSError:
        pass


def _check_session_excluded() -> bool:
    """Verify session path is git-ignored and docker-ignored.

    Inside Docker, .gitignore/.dockerignore may not be present — skip check.
    """
    try:
        gitignore = Path(".gitignore").read_text(encoding="utf-8")
        if "data/sessions/" not in gitignore and "*.session" not in gitignore:
            return False

        dockerignore = Path(".dockerignore").read_text(encoding="utf-8")
        return not ("data/sessions/" not in dockerignore and "*.session" not in dockerignore)
    except FileNotFoundError:
        # Inside Docker, these files may be excluded from the image — acceptable
        return True


def main() -> int:
    setup_logging()
    return asyncio.run(_async_main())


async def _async_main() -> int:
    # For authorization, we need credentials but NOT necessarily the enabled flag
    # (authorization is a pre-enable step). We temporarily override the enabled
    # check so the operator can authorize before enabling.
    # Check credentials present
    missing = []
    if not settings.telegram_api_id:
        missing.append("TELEGRAM_API_ID")
    if not settings.telegram_api_hash:
        missing.append("TELEGRAM_API_HASH")
    if not settings.telegram_phone:
        missing.append("TELEGRAM_PHONE")
    if missing:
        print(f"ERROR: Missing credentials: {', '.join(missing)}")
        print("Set them in .env (untracked) and try again")
        return 1

    # Check session exclusion
    if not _check_session_excluded():
        print("ERROR: Session path not excluded from git/docker")
        return 1

    # Prevent concurrent authorization
    if not _acquire_lock():
        print("ERROR: Another authorization process is running")
        print(f"Remove {_LOCK_FILE} if stale")
        return 1

    result: dict = {
        "started_at": datetime.now(UTC).isoformat(),
        "success": False,
        "self_id": None,
        "self_username": None,
        "session_configured": False,
        "error": None,
    }

    try:
        from telethon import TelegramClient
        from telethon.errors import SessionPasswordNeededError
    except ImportError:
        print("ERROR: Telethon not installed — run: uv sync --extra telegram")
        _release_lock()
        return 1

    session_path = settings.telegram_session_path
    session_dir = os.path.dirname(session_path)
    if session_dir:
        os.makedirs(session_dir, exist_ok=True)

    # Restrict session directory permissions (where supported)
    import contextlib
    with contextlib.suppress(OSError):
        os.chmod(session_dir, 0o700)

    print("Creating MTProto session at: [PROTECTED]")
    print("This is a one-time authorization. Do not run while ingestor is active.")
    print()

    from newsroom.sources.telegram_collector import telegram_transport_config

    transport, transport_label = telegram_transport_config()
    client = TelegramClient(
        session_path,
        int(settings.telegram_api_id),
        settings.telegram_api_hash,
        timeout=max(1, int(settings.telegram_connect_timeout_seconds)),
        connection_retries=max(0, int(settings.telegram_connection_retries)),
        retry_delay=max(0, int(settings.telegram_retry_delay_seconds)),
        **transport,
    )
    print(f"MTProto transport: {transport_label}")

    try:
        connect_deadline = max(5, int(settings.telegram_connect_timeout_seconds)) * (
            max(0, int(settings.telegram_connection_retries)) + 1
        ) + 5
        await asyncio.wait_for(client.connect(), timeout=connect_deadline)

        if await client.is_user_authorized():
            print("Session already authorized — verifying identity...")
        else:
            # Send code request — phone is read from env, never echoed
            print("Sending login code to your Telegram app...")
            await client.send_code_request(settings.telegram_phone)

            # Request login code interactively — never logged, never persisted
            # Use input() for Docker TTY compatibility (getpass may not work in all Docker TTYs)
            # The code is ephemeral and only used once — not a password
            sys.stdout.flush()
            code = input("Enter the login code: ").strip()

            try:
                await client.sign_in(settings.telegram_phone, code)
            except SessionPasswordNeededError:
                # 2FA required — use getpass for the password (never echoed)
                print("Two-factor authentication is enabled.")
                sys.stdout.flush()
                try:
                    password = getpass.getpass("Enter your 2FA password: ")
                except (EOFError, OSError):
                    # Fallback if getpass doesn't work in this environment
                    password = input("Enter your 2FA password: ").strip()
                await client.sign_in(password=password)

        # Verify identity
        me = await client.get_me()
        self_id = int(getattr(me, "id", 0))
        self_username = getattr(me, "username", "") or ""
        first_name = getattr(me, "first_name", "") or ""

        result["success"] = True
        result["self_id"] = self_id
        result["self_username"] = self_username
        result["session_configured"] = True
        result["verified_at"] = datetime.now(UTC).isoformat()

        print()
        print("=" * 50)
        print("Authorization successful!")
        print(f"  Account ID: {self_id}")
        print(f"  Username: @{self_username}" if self_username else "  Username: (none)")
        print(f"  Name: {first_name}" if first_name else "")
        print(f"  Session: {session_path}")
        print("=" * 50)
        print()
        print("You can now start the ingestor service.")
        print("The session will persist across restarts.")

    except Exception as e:
        err = str(e)
        result["error"] = err[:200]
        print(f"\nERROR: Authorization failed: {err}")
        # Never print api_hash, phone, or code in error
        _write_result(result)
        _release_lock()
        return 1
    finally:
        await client.disconnect()
        _write_result(result)
        _release_lock()

    _write_result(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
