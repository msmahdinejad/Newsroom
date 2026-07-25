"""Audit exact local protected values without ever printing those values.

The audit reads ignored runtime files, scans the tracked tree, all Git blobs,
production logs, and PostgreSQL data, then emits only safe counts and labels.
It does not modify the repository, history, logs, or database.
"""

from __future__ import annotations

import json
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_FILES = (".env", ".env.providers.local", ".env.x.local")
PUBLIC_EMPTY_VALUES = {"", "true", "false", "none", "null", "0", "1"}
PROTECTED_ENV_KEYS = {
    "COLLECTION_PROXY_URL",
    "TELEGRAM_API_HASH",
    "TELEGRAM_API_ID",
    "TELEGRAM_AUTHORIZED_USER_IDS",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_PHONE",
    "TELEGRAM_PROXY_URL",
    "TELEGRAM_TEST_CHAT_ID",
}
LIST_VALUE_KEYS = {
    "GEMINI_API_KEYS",
    "GROQ_API_KEYS",
    "MISTRAL_API_KEYS",
    "NVIDIA_API_KEYS",
    "TELEGRAM_AUTHORIZED_USER_IDS",
}
SHORT_IDENTITY_KEYS = {
    "TELEGRAM_API_ID",
    "TELEGRAM_AUTHORIZED_USER_IDS",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_TEST_CHAT_ID",
}


def _run(*args: str) -> bytes:
    completed = subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return completed.stdout


def _protected_values() -> dict[str, bytes]:
    values: dict[str, bytes] = {}
    for filename in LOCAL_FILES:
        path = ROOT / filename
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, raw_value = line.split("=", 1)
            key = key.strip()
            value = raw_value.strip().strip("\"'")
            is_provider_secret = filename == ".env.providers.local" and (
                key.endswith("_API_KEYS") or key == "LLM_PROXY_URL"
            )
            is_x_secret = filename == ".env.x.local" and key in {
                "TWITTER_AUTH_TOKEN",
                "TWITTER_CT0",
            }
            is_runtime_secret = filename == ".env" and key in PROTECTED_ENV_KEYS
            if not (is_provider_secret or is_x_secret or is_runtime_secret):
                continue
            candidates = value.split(",") if key in LIST_VALUE_KEYS else [value]
            for index, candidate in enumerate(candidates, start=1):
                candidate = candidate.strip()
                minimum_length = 3 if key in SHORT_IDENTITY_KEYS else 12
                if (
                    candidate.lower() in PUBLIC_EMPTY_VALUES
                    or len(candidate) < minimum_length
                ):
                    continue
                suffix = f"[{index}]" if len(candidates) > 1 else ""
                values[f"{filename}:{key}{suffix}"] = candidate.encode()

    # Machine-specific paths are private release metadata even when they are
    # not credentials. Derive them portably so this public audit script does
    # not itself contain an operator name or path.
    home_path = str(Path.home()).encode()
    values["local-machine:home-path"] = home_path
    values["local-machine:portable-home-path"] = home_path.replace(b"\\", b"/")
    values["local-machine:json-escaped-home-path"] = home_path.replace(
        b"\\",
        b"\\\\",
    )
    return values


def _tracked_scan(values: dict[str, bytes]) -> dict[str, list[str]]:
    matches: dict[str, set[str]] = defaultdict(set)
    paths = _run("git", "ls-files").decode().splitlines()
    for relative in paths:
        path = ROOT / relative
        if not path.is_file():
            continue
        payload = path.read_bytes()
        for label, value in values.items():
            if value in payload:
                matches[label].add(relative.replace("\\", "/"))
    return {label: sorted(paths) for label, paths in matches.items()}


def _history_scan(values: dict[str, bytes]) -> dict[str, list[str]]:
    matches: dict[str, set[str]] = defaultdict(set)
    object_lines = _run("git", "rev-list", "--objects", "--all").decode().splitlines()
    object_paths: dict[str, str] = {}
    object_ids: list[str] = []
    for line in object_lines:
        object_id, _, path = line.partition(" ")
        object_ids.append(object_id)
        if path:
            object_paths.setdefault(object_id, path)

    process = subprocess.Popen(
        ["git", "cat-file", "--batch"],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    try:
        for object_id in object_ids:
            process.stdin.write(f"{object_id}\n".encode())
            process.stdin.flush()
            header = process.stdout.readline().decode("ascii", errors="replace").strip()
            parts = header.split()
            if len(parts) != 3:
                continue
            size = int(parts[2])
            payload = process.stdout.read(size)
            process.stdout.read(1)
            if parts[1] != "blob":
                continue
            for label, value in values.items():
                if value in payload:
                    safe_location = object_paths.get(object_id, f"blob:{object_id[:12]}")
                    matches[label].add(safe_location.replace("\\", "/"))
    finally:
        process.stdin.close()
        process.wait(timeout=30)
    return {label: sorted(paths) for label, paths in matches.items()}


def _external_scan(values: dict[str, bytes], *command: str) -> dict[str, bool]:
    try:
        payload = _run(*command)
    except (OSError, subprocess.CalledProcessError):
        return {"scan_unavailable": True}
    return {label: True for label, value in values.items() if value in payload}


def main() -> int:
    values = _protected_values()
    tracked = _tracked_scan(values)
    history = _history_scan(values)
    logs = _external_scan(values, "docker", "compose", "logs", "--no-color")
    database = _external_scan(
        values,
        "docker",
        "compose",
        "exec",
        "-T",
        "postgres",
        "pg_dump",
        "-U",
        "newsroom",
        "--data-only",
        "newsroom",
    )
    result = {
        "protected_value_count": len(values),
        "tracked_match_count": sum(len(paths) for paths in tracked.values()),
        "tracked_matches": tracked,
        "history_match_count": sum(len(paths) for paths in history.values()),
        "history_matches": history,
        "log_match_count": len(logs) if "scan_unavailable" not in logs else None,
        "log_matches": sorted(logs),
        "database_match_count": (
            len(database) if "scan_unavailable" not in database else None
        ),
        "database_matches": sorted(database),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if tracked or history or logs or database else 0


if __name__ == "__main__":
    raise SystemExit(main())
