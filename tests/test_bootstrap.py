"""Clean-clone bootstrap configuration tests."""

import argparse
from pathlib import Path

import pytest

from scripts.bootstrap import (
    BootstrapError,
    _validate_source_options,
    create_local_configuration,
)

MAIN_TEMPLATE = """\
DATABASE_URL=postgresql+psycopg://newsroom:change-me@127.0.0.1:55432/newsroom
POSTGRES_PASSWORD=change-me
"""


def _templates(root: Path) -> None:
    (root / ".env.example").write_text(MAIN_TEMPLATE, encoding="utf-8")
    (root / ".env.providers.example").write_text(
        "LLM_ROUTER_ENABLED=false\nGEMINI_API_KEYS=\n",
        encoding="utf-8",
    )
    (root / ".env.x.example").write_text(
        "TWITTER_AUTH_TOKEN=\nTWITTER_CT0=\n",
        encoding="utf-8",
    )


def test_configuration_creation_is_secure_and_idempotent(tmp_path: Path) -> None:
    _templates(tmp_path)

    created = create_local_configuration(tmp_path)
    first_application_env = (tmp_path / ".env").read_text(encoding="utf-8")
    created_again = create_local_configuration(tmp_path)

    assert created == (".env", ".env.providers.local", ".env.x.local")
    assert created_again == ()
    assert "change-me" not in first_application_env
    assert "POSTGRES_PASSWORD=" in first_application_env
    assert (tmp_path / ".env.providers.local").is_file()
    assert (tmp_path / ".env.x.local").is_file()


def test_configuration_creation_preserves_existing_local_files(tmp_path: Path) -> None:
    _templates(tmp_path)
    (tmp_path / ".env").write_text("LOCAL_SENTINEL=preserve\n", encoding="utf-8")

    create_local_configuration(tmp_path)

    assert (tmp_path / ".env").read_text(encoding="utf-8") == "LOCAL_SENTINEL=preserve\n"


def test_custom_mode_requires_a_file(tmp_path: Path) -> None:
    args = argparse.Namespace(
        source_mode="custom",
        source_file=None,
        select=None,
    )

    with pytest.raises(BootstrapError, match="requires --source-file"):
        _validate_source_options(args, tmp_path)
