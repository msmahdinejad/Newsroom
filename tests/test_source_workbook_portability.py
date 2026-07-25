"""Portable and privacy-safe source workbook discovery."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

from newsroom.cli.commands import sources as sources_cli
from newsroom.sources.inventory import (
    _activation_reason,
    copy_workbook_to_import_dir,
    find_workbook,
    import_workbook,
)


def test_find_workbook_prefers_explicit_path(tmp_path: Path) -> None:
    workbook = tmp_path / "private" / "inventory.xlsx"
    workbook.parent.mkdir()
    workbook.touch()

    assert find_workbook(tmp_path, workbook) == workbook.resolve()


def test_find_workbook_uses_environment_path(tmp_path: Path, monkeypatch) -> None:
    workbook = tmp_path / "private" / "inventory.xlsx"
    workbook.parent.mkdir()
    workbook.touch()
    monkeypatch.setenv("NEWSROOM_SOURCE_WORKBOOK", str(workbook))

    assert find_workbook(tmp_path) == workbook.resolve()


def test_find_workbook_finds_canonical_repo_copy(tmp_path: Path) -> None:
    workbook = tmp_path / "config" / "import" / "source-radar.xlsx"
    workbook.parent.mkdir(parents=True)
    workbook.touch()

    assert find_workbook(tmp_path) == workbook.resolve()


def test_copy_workbook_is_idempotent_when_already_canonical(tmp_path: Path) -> None:
    workbook = tmp_path / "config" / "import" / "source-radar.xlsx"
    workbook.parent.mkdir(parents=True)
    workbook.touch()

    assert copy_workbook_to_import_dir(workbook, tmp_path).resolve() == workbook.resolve()


def test_sources_command_forwards_explicit_workbook() -> None:
    args = Namespace(sources_command="import", workbook="private/inventory.xlsx")
    with patch.object(sources_cli, "_do_import", return_value=0) as do_import:
        assert sources_cli.sources_command(args) == 0
    do_import.assert_called_once_with("private/inventory.xlsx")


def test_import_report_does_not_expose_absolute_owner_path(tmp_path: Path) -> None:
    workbook = tmp_path / "private" / "inventory.xlsx"
    with (
        patch("newsroom.sources.inventory._load_workbook_rows", return_value=[]),
        patch("newsroom.sources.inventory._parse_rows", return_value=[]),
    ):
        report = import_workbook(MagicMock(), workbook)

    assert report.workbook_path == "inventory.xlsx"


def test_activation_preserves_permanent_runtime_inactive_reason() -> None:
    inventory = MagicMock(
        validation_result="ok",
        operational_state="inactive",
        inactive_reason="channel_unresolvable",
        platform="Telegram",
        workbook_type="Channel",
        public_url="https://t.me/unresolvable",
    )

    assert (
        _activation_reason(
            inventory,
            x_auth_available=True,
            telegram_mtproto_available=True,
        )
        == "channel_unresolvable"
    )
