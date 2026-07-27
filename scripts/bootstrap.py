"""Cross-platform first-run bootstrap for a clean clone.

The script creates ignored local configuration, installs dependencies, starts
PostgreSQL, applies migrations, and initializes the selected source profile.
It never accepts credentials as command-line arguments.
"""

from __future__ import annotations

import argparse
import secrets
import shutil
import subprocess
import sys
from pathlib import Path


class BootstrapError(RuntimeError):
    """Raised when a prerequisite or bootstrap command fails."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap a Newsroom clone")
    parser.add_argument(
        "--source-mode",
        choices=("empty", "default", "custom"),
        default="default",
        help="Initial source registry mode",
    )
    parser.add_argument(
        "--select",
        help="Comma-separated starter source keys for default mode",
    )
    parser.add_argument(
        "--source-file",
        help="CSV/XLSX source file for custom mode",
    )
    parser.add_argument(
        "--configuration-only",
        action="store_true",
        help="Create ignored local configuration without running tools",
    )
    parser.add_argument(
        "--start",
        action="store_true",
        help="Build and start the complete Compose stack after initialization",
    )
    parser.add_argument(
        "--production",
        action="store_true",
        help="Install runtime dependencies instead of developer tooling",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


def bootstrap(args: argparse.Namespace) -> None:
    root = args.root.expanduser().resolve()
    _validate_source_options(args, root)
    created = create_local_configuration(root)
    for filename in created:
        print(f"CREATE: {filename}")
    if args.configuration_only:
        print("OK: local configuration is ready")
        return

    _require_tool("uv")
    _require_tool("docker")
    _run(["docker", "compose", "version"], root)

    sync_command = ["uv", "sync", "--frozen", "--extra", "telegram"]
    if args.production:
        sync_command.append("--no-dev")
    else:
        sync_command.extend(["--extra", "dev"])
    _run(sync_command, root)
    _run(["docker", "compose", "up", "-d", "--wait", "postgres"], root)
    _run(["uv", "run", "alembic", "upgrade", "head"], root)

    source_command = [
        "uv",
        "run",
        "newsroom",
        "sources",
        "initialize",
        "--mode",
        args.source_mode,
        "--replace",
    ]
    if args.select:
        source_command.extend(["--select", args.select])
    if args.source_file:
        source_command.extend(
            ["--file", str((root / args.source_file).resolve())]
        )
    _run(source_command, root)

    if args.start:
        _run(["docker", "compose", "up", "-d", "--build", "--wait"], root)
    _run(["uv", "run", "newsroom", "health"], root)
    print("OK: Newsroom bootstrap completed")


def create_local_configuration(root: Path) -> tuple[str, ...]:
    """Create missing ignored configuration files and preserve existing ones."""
    templates = (
        (".env.example", ".env"),
        (".env.providers.example", ".env.providers.local"),
        (".env.x.example", ".env.x.local"),
    )
    created: list[str] = []
    for template_name, local_name in templates:
        template = root / template_name
        destination = root / local_name
        if destination.exists():
            continue
        if not template.is_file():
            raise BootstrapError(f"missing configuration template: {template_name}")
        content = template.read_text(encoding="utf-8")
        if local_name == ".env":
            content = _secure_database_defaults(content)
        destination.write_text(content, encoding="utf-8", newline="\n")
        created.append(local_name)
    return tuple(created)


def _secure_database_defaults(content: str) -> str:
    password = secrets.token_urlsafe(32)
    replacements = {
        "POSTGRES_PASSWORD=change-me": f"POSTGRES_PASSWORD={password}",
        (
            "DATABASE_URL=postgresql+psycopg://newsroom:change-me@"
            "127.0.0.1:55432/newsroom"
        ): (
            f"DATABASE_URL=postgresql+psycopg://newsroom:{password}@"
            "127.0.0.1:55432/newsroom"
        ),
    }
    for old, new in replacements.items():
        if old not in content:
            raise BootstrapError(
                "the application environment template has unexpected database defaults"
            )
        content = content.replace(old, new)
    return content


def _validate_source_options(args: argparse.Namespace, root: Path) -> None:
    if args.source_mode == "custom":
        if not args.source_file:
            raise BootstrapError("custom source mode requires --source-file")
        if not (root / args.source_file).expanduser().is_file():
            raise BootstrapError(f"source file does not exist: {args.source_file}")
    elif args.source_file:
        raise BootstrapError("--source-file is valid only with custom source mode")
    if args.source_mode != "default" and args.select:
        raise BootstrapError("--select is valid only with default source mode")


def _require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise BootstrapError(f"required tool is not available on PATH: {name}")


def _run(command: list[str], root: Path) -> None:
    print(f"RUN: {' '.join(command)}")
    completed = subprocess.run(command, cwd=root, check=False)
    if completed.returncode:
        raise BootstrapError(
            f"command failed with exit code {completed.returncode}: {command[0]}"
        )


def main() -> int:
    try:
        bootstrap(parse_args())
    except BootstrapError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
