"""Audit the public repository and optional local runtime for private material."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_FILES = (".env", ".env.providers.local", ".env.x.local")
PUBLIC_EMPTY_VALUES = {"", "true", "false", "none", "null", "0", "1", "change-me"}
SECRET_KEY_PATTERN = re.compile(
    r"(?:API_KEYS?|API_HASH|API_ID|TOKEN|SECRET|PASSWORD|COOKIE|CT0|"
    r"AUTHORIZATION|PROXY_URL|MTPROXY_HOST|PHONE|CHAT_ID|USER_IDS)$"
)
ARABIC_SCRIPT_PATTERN = re.compile("[\u0600-\u06ff]")
FORBIDDEN_TRACKED_PREFIXES = (
    ".diagnostics/",
    ".specify/",
    "backups/",
    "data/",
    "docs/audit/",
    "docs/verification/",
)
FORBIDDEN_TRACKED_SUFFIXES = (
    ".db",
    ".log",
    ".session",
    ".sqlite",
    ".sqlite3",
    ".xlsx",
)
ALLOWED_PUBLIC_DATA = {
    "examples/sources.custom.example.csv",
    "src/newsroom/resources/sources.default.csv",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime",
        action="store_true",
        help="Also scan Compose logs and the local PostgreSQL database",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="Also scan Git history for exact locally configured protected values",
    )
    return parser.parse_args()


def _run(*args: str) -> bytes:
    completed = subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return completed.stdout


def _tracked_paths() -> tuple[str, ...]:
    """Return every file that would be present in the next public commit."""
    return tuple(
        _run(
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
        )
        .decode()
        .splitlines()
    )


def _protected_values() -> dict[str, bytes]:
    values: dict[str, bytes] = {}
    for filename in LOCAL_FILES:
        path = ROOT / filename
        if not path.is_file():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, raw_value = line.split("=", 1)
            key = key.strip()
            value = raw_value.strip().strip("\"'")
            if not SECRET_KEY_PATTERN.search(key):
                continue
            candidates = value.split(",") if key.endswith(("KEYS", "USER_IDS")) else [value]
            for index, candidate in enumerate(candidates, start=1):
                candidate = candidate.strip()
                if candidate.lower() in PUBLIC_EMPTY_VALUES or len(candidate) < 3:
                    continue
                label = f"{filename}:{key}"
                if len(candidates) > 1:
                    label += f"[{index}]"
                values[label] = candidate.encode()

    home = str(Path.home()).encode()
    values["local-machine:home-path"] = home
    values["local-machine:portable-home-path"] = home.replace(b"\\", b"/")
    values["local-machine:escaped-home-path"] = home.replace(b"\\", b"\\\\")
    return values


def _exact_value_scan(
    values: dict[str, bytes],
    paths: tuple[str, ...],
) -> dict[str, list[str]]:
    matches: dict[str, set[str]] = defaultdict(set)
    for relative in paths:
        path = ROOT / relative
        if not path.is_file():
            continue
        payload = path.read_bytes()
        for label, value in values.items():
            if value and value in payload:
                matches[label].add(relative.replace("\\", "/"))
    return {label: sorted(locations) for label, locations in matches.items()}


def _public_tree_violations(paths: tuple[str, ...]) -> list[str]:
    violations: list[str] = []
    for relative in paths:
        normalized = relative.replace("\\", "/")
        lower = normalized.lower()
        if normalized in ALLOWED_PUBLIC_DATA:
            continue
        if lower in LOCAL_FILES:
            violations.append(normalized)
            continue
        if lower.startswith(FORBIDDEN_TRACKED_PREFIXES):
            violations.append(normalized)
            continue
        if lower.endswith(FORBIDDEN_TRACKED_SUFFIXES):
            violations.append(normalized)
    return sorted(violations)


def _non_english_text(paths: tuple[str, ...]) -> list[str]:
    matches: list[str] = []
    for relative in paths:
        path = ROOT / relative
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if ARABIC_SCRIPT_PATTERN.search(text):
            matches.append(relative.replace("\\", "/"))
    return sorted(matches)


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
                if value and value in payload:
                    matches[label].add(
                        object_paths.get(object_id, f"blob:{object_id[:12]}").replace("\\", "/")
                    )
    finally:
        process.stdin.close()
        process.wait(timeout=30)
    return {label: sorted(locations) for label, locations in matches.items()}


def _external_scan(values: dict[str, bytes], *command: str) -> dict[str, bool] | None:
    try:
        payload = _run(*command)
    except (OSError, subprocess.CalledProcessError):
        return None
    return {label: True for label, value in values.items() if value and value in payload}


def main() -> int:
    args = parse_args()
    paths = _tracked_paths()
    protected_values = _protected_values()
    tracked_matches = _exact_value_scan(protected_values, paths)
    forbidden_paths = _public_tree_violations(paths)
    non_english_files = _non_english_text(paths)
    history_matches = _history_scan(protected_values) if args.history else {}
    logs = None
    database = None
    if args.runtime:
        logs = _external_scan(
            protected_values,
            "docker",
            "compose",
            "logs",
            "--no-color",
        )
        database = _external_scan(
            protected_values,
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
        "tracked_files": len(paths),
        "protected_values_checked": len(protected_values),
        "protected_value_matches": tracked_matches,
        "forbidden_tracked_paths": forbidden_paths,
        "arabic_script_files": non_english_files,
        "history_matches": history_matches,
        "runtime_log_matches": None if logs is None else sorted(logs),
        "runtime_database_matches": None if database is None else sorted(database),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    failed = any(
        (
            tracked_matches,
            forbidden_paths,
            non_english_files,
            history_matches,
            logs,
            database,
        )
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
