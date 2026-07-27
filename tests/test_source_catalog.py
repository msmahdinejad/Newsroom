"""Source catalog behavior through its public interface."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from newsroom.control import SourceCatalog
from newsroom.control.manager import ImportResult
from newsroom.storage.models import Source


def _import_result(total: int) -> ImportResult:
    return ImportResult(
        filename="sources.csv",
        total_rows=total,
        created=total,
        updated=0,
        skipped=0,
        errors=(),
    )


def test_packaged_catalog_has_unique_safe_keys() -> None:
    entries = SourceCatalog(MagicMock()).available()

    assert len(entries) >= 20
    assert len({entry.key for entry in entries}) == len(entries)
    assert any(entry.source_type == "telegram" for entry in entries)
    assert any(entry.source_type == "github_releases" for entry in entries)
    assert all(entry.url.startswith("https://") for entry in entries)


def test_default_mode_uses_default_subset() -> None:
    db = MagicMock()
    catalog = SourceCatalog(db)
    default_count = sum(entry.default_enabled for entry in catalog.available())

    with patch("newsroom.control.catalog.NewsroomControl") as control_type:
        control_type.return_value.import_sources.return_value = _import_result(default_count)
        result = catalog.apply("default")
        payload = control_type.return_value.import_sources.call_args.args[1]

    assert result.selected == default_count
    assert result.created == default_count
    assert b"https://t.me/" not in payload


def test_explicit_selection_can_choose_optional_telegram_source() -> None:
    db = MagicMock()
    catalog = SourceCatalog(db)

    with patch("newsroom.control.catalog.NewsroomControl") as control_type:
        control_type.return_value.import_sources.return_value = _import_result(1)
        result = catalog.apply(
            "default",
            selection=("telegram-coding-news",),
        )
        payload = control_type.return_value.import_sources.call_args.args[1]

    assert result.selected == 1
    assert b"https://t.me/codingnews" in payload
    assert b",true" in payload


def test_empty_replace_disables_without_deleting_history() -> None:
    source = Source(
        id=1,
        name="Existing",
        type="rss",
        url="https://example.com/feed",
        enabled=True,
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [source]

    result = SourceCatalog(db).apply("empty", replace=True)

    assert result.disabled_existing == 1
    assert source.enabled is False
    assert source.inactive_reason == "replaced_by_setup"
    db.delete.assert_not_called()


def test_custom_mode_requires_existing_file(tmp_path: Path) -> None:
    catalog = SourceCatalog(MagicMock())

    with pytest.raises(ValueError, match="requires --file"):
        catalog.apply("custom")
    with pytest.raises(ValueError, match="does not exist"):
        catalog.apply("custom", custom_file=tmp_path / "missing.csv")


def test_unknown_starter_key_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown starter source keys"):
        SourceCatalog(MagicMock()).apply(
            "default",
            selection=("not-in-the-catalog",),
        )
