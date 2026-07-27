"""Regression tests for Gate 6 production truth and stable identities."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from newsroom.editorial.persistence import cache_route_identity
from newsroom.pipeline.runner import (
    delivery_allowed_for_attempt,
    generation_method_for_attempt,
    report_story_ids_for_attempt,
)
from newsroom.scheduler import scheduled_boundary_job_id
from newsroom.sources.validation_sweep import safe_failure_category


def test_provider_switch_keeps_accepted_artifact_cache_identity():
    assert cache_route_identity("gemini", "gemini-3.6-flash") == cache_route_identity(
        "mistral", "mistral-large-2512"
    )


def test_fallback_report_is_not_mislabeled_ai():
    attempt = SimpleNamespace(provider="gemini", status="fallback", fallback_used=True)
    assert generation_method_for_attempt(attempt) == "deterministic"


def test_nonfallback_provider_report_is_ai():
    attempt = SimpleNamespace(provider="mistral", status="ok", fallback_used=False)
    assert generation_method_for_attempt(attempt) == "ai"


def test_deterministic_fallback_is_persisted_but_never_publicly_delivered():
    attempt = SimpleNamespace(provider="deterministic", status="fallback", fallback_used=True)
    assert delivery_allowed_for_attempt(attempt) is False


def test_valid_ai_report_is_publicly_deliverable():
    attempt = SimpleNamespace(provider="gemini", status="ok", fallback_used=False)
    assert delivery_allowed_for_attempt(attempt) is True


def test_report_lineage_contains_only_validated_final_output_stories():
    attempt = SimpleNamespace(
        output=SimpleNamespace(
            stories=[SimpleNamespace(story_id=3), SimpleNamespace(story_id=1)]
        )
    )
    assert report_story_ids_for_attempt([1, 2, 3], attempt) == [3, 1]


def test_scheduled_boundary_id_is_stable_for_same_tehran_window():
    when = datetime(2026, 7, 22, 6, 0, tzinfo=ZoneInfo("Asia/Tehran"))
    assert scheduled_boundary_job_id("06:00", when) == "scheduled_20260722_0600"
    assert scheduled_boundary_job_id("06:00", when) == scheduled_boundary_job_id("06:00", when)


def test_source_failures_are_reduced_to_safe_categories():
    assert safe_failure_category("HTTP 429 with provider detail") == "rate_limit"
    assert safe_failure_category("HTTP 503 upstream") == "provider_unavailable"
    assert safe_failure_category("Server closed the connection") == "network_error"
