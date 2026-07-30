"""Grounded source discovery stays bounded, closed, and approval-gated."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from newsroom.sources.discovery import (
    GeminiSourceDiscovery,
    ProbeResult,
    SourceProbe,
    classify_source_url,
)
from newsroom.storage.models import DiscoveryJob, SourceCandidate


@pytest.mark.parametrize(
    ("raw_url", "expected"),
    [
        (
            "https://t.me/s/python",
            ("telegram", "telegram", "https://t.me/python"),
        ),
        (
            "https://twitter.com/python",
            ("x", "x_timeline", "https://x.com/python"),
        ),
        (
            "https://old.reddit.com/r/python/comments/anything",
            ("reddit", "reddit_subreddit", "https://reddit.com/r/python"),
        ),
        (
            "https://github.com/python/cpython/issues/1",
            ("github", "github_releases", "https://github.com/python/cpython"),
        ),
        (
            "https://example.org/feed.xml?format=rss",
            (
                "web",
                "web_page",
                "https://example.org/feed.xml?format=rss",
            ),
        ),
    ],
)
def test_classify_source_url_uses_only_closed_platforms(
    raw_url: str,
    expected: tuple[str, str, str],
) -> None:
    assert classify_source_url(raw_url) == expected


@pytest.mark.parametrize(
    "raw_url",
    [
        "file:///etc/passwd",
        "http://localhost/admin",
        "http://127.0.0.1/admin",
        "https://t.me/share/url",
        "https://t.me/+private-invite",
        "https://x.com/python/status/123",
        "https://youtube.com/@channel",
    ],
)
def test_classify_source_url_rejects_unsafe_or_unsupported_targets(
    raw_url: str,
) -> None:
    assert classify_source_url(raw_url) is None


class _Response:
    status_code = 200

    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body

    def json(self) -> dict[str, Any]:
        return self._body


class _Client:
    response_body: dict[str, Any] = {}
    request_headers: dict[str, str] = {}

    def __init__(self, **_kwargs: Any) -> None:
        pass

    def __enter__(self) -> _Client:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def request(
        self,
        _method: str,
        _url: str,
        *,
        json: dict[str, Any] | None,
        headers: dict[str, str],
    ) -> _Response:
        del json
        type(self).request_headers = headers
        return _Response(type(self).response_body)


class _ReachableProbe:
    def probe(self, _url: str, source_type: str) -> ProbeResult:
        return ProbeResult("reachable", source_type)


def _provider_file(tmp_path: Path) -> Path:
    path = tmp_path / ".env.providers.local"
    path.write_text(
        "\n".join(
            [
                "LLM_PROVIDER_ORDER=gemini",
                "GEMINI_API_KEYS=temporary-test-value",
                "GEMINI_MODELS=gemini-3.6-flash",
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_quick_discovery_persists_only_safe_grounded_candidate_metadata(
    tmp_path: Path,
) -> None:
    candidate_url = "https://t.me/python"
    _Client.response_body = {
        "steps": [
            {
                "type": "model_output",
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "candidates": [
                                    {
                                        "name": "Python",
                                        "url": candidate_url,
                                        "rationale": "Public programming channel.",
                                    }
                                ]
                            }
                        ),
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": "https://example.org/directory/python",
                                "title": "Public channel directory",
                            }
                        ],
                    }
                ],
            }
        ]
    }
    db = MagicMock()
    query = db.query.return_value
    query.filter.return_value.first.return_value = None
    persisted: list[object] = []

    def _add(row: object) -> None:
        persisted.append(row)
        if isinstance(row, DiscoveryJob):
            row.id = 41

    db.add.side_effect = _add
    discovery = GeminiSourceDiscovery(
        db,
        provider_file=_provider_file(tmp_path),
        probe=_ReachableProbe(),  # type: ignore[arg-type]
        client_factory=_Client,  # type: ignore[arg-type]
    )

    result = discovery.start(
        subject="Python language releases and developer ecosystem",
        platforms=("telegram",),
        max_candidates=3,
    )

    assert result.status == "completed"
    assert result.candidate_count == 1
    candidate = next(row for row in persisted if isinstance(row, SourceCandidate))
    assert candidate.normalized_url == candidate_url
    assert candidate.approval_status == "pending"
    assert candidate.validation_status == "reachable"
    assert "temporary-test-value" not in repr(persisted)
    assert _Client.request_headers["x-goog-api-key"] == "temporary-test-value"


def test_probe_rejects_private_target_before_network_access() -> None:
    client_factory = MagicMock()
    result = SourceProbe(client_factory=client_factory).probe(
        "http://127.0.0.1/internal",
        "web_page",
    )

    assert result.failure_category == "unsafe_network_target"
    client_factory.assert_not_called()


def test_provider_config_must_use_canonical_local_filename(
    tmp_path: Path,
) -> None:
    discovery = GeminiSourceDiscovery(
        MagicMock(),
        provider_file=tmp_path / "other.env",
    )
    with pytest.raises(ValueError, match="canonical"):
        discovery.start(
            subject="Open source database releases and engineering updates",
            platforms=("github",),
        )


def test_default_provider_file_uses_container_mount_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_file = _provider_file(tmp_path)
    monkeypatch.setenv("LLM_PROVIDER_ENV_FILE", str(provider_file))

    discovery = GeminiSourceDiscovery(MagicMock())
    provider, model = discovery._gemini_route()

    assert Path(discovery.provider_file) == provider_file
    assert provider.name == "gemini"
    assert model == "gemini-3.6-flash"
