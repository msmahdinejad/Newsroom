"""Provider CLI regression tests."""

from __future__ import annotations

import argparse
import json
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from newsroom.cli.commands.providers import providers_command
from newsroom.editorial.router.validation import (
    AccessValidationResult,
    ModelValidationResult,
)
from newsroom.editorial.router_persistence import (
    KeyStateSnapshot,
    RouterPersistenceSnapshot,
    RouterRestoredState,
)


def test_status_materializes_safe_values_before_session_closes(capsys) -> None:
    model = MagicMock(
        provider="gemini",
        model="validated-model",
        validation_status="validated",
        enabled=True,
        latency_ms=42,
        last_success_at=datetime(2026, 7, 27, tzinfo=UTC),
        last_failure_category=None,
        supported_capabilities=["persian", "structured_output"],
    )
    db = MagicMock()
    model_query = MagicMock()
    model_query.order_by.return_value.all.return_value = [model]
    key_query = MagicMock()
    key_query.all.return_value = [
        ("gemini", "known-enabled", True),
        ("gemini", "stale-disabled", False),
    ]
    db.query.side_effect = [model_query, key_query]
    config = SimpleNamespace(
        providers=(
            SimpleNamespace(
                name="gemini",
                keys=("configured-key",),
            ),
        )
    )

    @contextmanager
    def fake_get_db():
        try:
            yield db
        finally:
            for name in (
                "provider",
                "model",
                "validation_status",
                "enabled",
                "latency_ms",
                "last_success_at",
                "last_failure_category",
                "supported_capabilities",
            ):
                delattr(model, name)

    args = argparse.Namespace(providers_command="status")
    with (
        patch(
            "newsroom.cli.commands.providers.get_db",
            fake_get_db,
        ),
        patch(
            "newsroom.cli.commands.providers.load_router_config",
            return_value=config,
        ),
    ):
        assert providers_command(args) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["models"][0]["provider"] == "gemini"
    assert payload["models"][0]["status"] == "validated"
    assert payload["key_counts"]["gemini"] == {
        "configured": 1,
        "enabled": 1,
    }


def test_validation_restores_models_but_rechecks_key_state(capsys) -> None:
    key_snapshot = KeyStateSnapshot(
        provider="gemini",
        key_fingerprint="a" * 64,
        enabled=False,
        last_use_at=None,
        failure_count=1,
        cooldown_until=None,
        last_failure_category="invalid_key",
        success_count=0,
    )
    restored = RouterRestoredState(
        validated_model_ids={"gemini": ("validated-model",)},
        snapshots=RouterPersistenceSnapshot(
            model_health=(),
            keys=(key_snapshot,),
            quotas=(),
            circuits=(),
        ),
    )
    sink = MagicMock()
    sink.load.return_value = restored
    router = MagicMock()
    router.validate_models.return_value = [
        ModelValidationResult(
            provider="gemini",
            model="validated-model",
            status="validated",
            latency_ms=10,
            failure_category=None,
            supported_capabilities=("structured",),
        )
    ]
    router.validate_access_values.return_value = [
        AccessValidationResult(
            provider="gemini",
            safe_id="gemini-key-1",
            model="validated-model",
            status="validated",
            latency_ms=10,
            failure_category=None,
        )
    ]
    args = argparse.Namespace(
        providers_command="validate",
        provider="gemini",
        model=["validated-model"],
        validate_keys=True,
    )

    with (
        patch(
            "newsroom.cli.commands.providers.PostgresRouterStateSink",
            return_value=sink,
        ),
        patch(
            "newsroom.cli.commands.providers.create_router_from_local_env",
            return_value=router,
        ) as create_router,
    ):
        assert providers_command(args) == 0

    create_kwargs = create_router.call_args.kwargs
    assert create_kwargs["validated_models"] == restored.validated_model_ids
    assert create_kwargs["restored_snapshot"].keys == ()
    assert json.loads(capsys.readouterr().out)["keys"][0]["status"] == "validated"
