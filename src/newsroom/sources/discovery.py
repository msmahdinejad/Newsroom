"""Grounded source discovery with explicit approval before activation."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from sqlalchemy.orm import Session

from newsroom.control import NewsroomControl
from newsroom.editorial.router.config import load_router_config
from newsroom.editorial.router.types import ProviderConfig
from newsroom.sources.platforms import PLATFORM_BY_KEY
from newsroom.storage.models import DiscoveryJob, Source, SourceCandidate

_DEEP_AGENT = "deep-research-preview-04-2026"
_DISCOVERY_MODELS = (
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
)


@dataclass(frozen=True)
class ProbeResult:
    status: str
    source_type: str
    failure_category: str | None = None


@dataclass(frozen=True)
class DiscoveryResult:
    job_id: int
    status: str
    candidate_count: int
    interaction_id: str | None = None
    failure_category: str | None = None


class SourceProbe:
    """Bounded public-network probe with SSRF protection."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        client_factory: type[httpx.Client] = httpx.Client,
    ) -> None:
        self.timeout_seconds = max(1.0, timeout_seconds)
        self.client_factory = client_factory

    def probe(self, url: str, source_type: str) -> ProbeResult:
        parsed = urlparse(url)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.username
            or parsed.password
            or not parsed.hostname
            or not _public_hostname(parsed.hostname)
        ):
            return ProbeResult("failed", source_type, "unsafe_network_target")
        try:
            with self.client_factory(
                timeout=httpx.Timeout(
                    self.timeout_seconds,
                    connect=min(5.0, self.timeout_seconds),
                ),
                follow_redirects=False,
            ) as client:
                current_url = url
                for _redirect in range(4):
                    parsed = urlparse(current_url)
                    if (
                        parsed.scheme not in {"http", "https"}
                        or parsed.username
                        or parsed.password
                        or not parsed.hostname
                        or not _public_hostname(parsed.hostname)
                    ):
                        return ProbeResult(
                            "failed",
                            source_type,
                            "unsafe_network_target",
                        )
                    with client.stream(
                        "GET",
                        current_url,
                        headers={
                            "Range": "bytes=0-1023",
                            "User-Agent": "newsroom-source-discovery/1.0",
                        },
                    ) as response:
                        status = response.status_code
                        content_type = response.headers.get(
                            "content-type",
                            "",
                        ).casefold()
                        location = response.headers.get("location")
                    if status not in {301, 302, 303, 307, 308}:
                        break
                    if not location:
                        return ProbeResult(
                            "failed",
                            source_type,
                            "invalid_redirect",
                        )
                    current_url = urljoin(current_url, location)
                else:
                    return ProbeResult(
                        "failed",
                        source_type,
                        "redirect_limit",
                    )
            if status in {401, 403}:
                return ProbeResult("restricted", source_type, "access_restricted")
            if status >= 400:
                return ProbeResult("failed", source_type, f"http_{status}")
            detected_type = (
                "rss"
                if source_type == "web_page"
                and any(
                    marker in content_type
                    for marker in ("application/rss", "application/atom", "xml")
                )
                else source_type
            )
            return ProbeResult("reachable", detected_type)
        except httpx.TimeoutException:
            return ProbeResult("failed", source_type, "timeout")
        except httpx.HTTPError:
            return ProbeResult("failed", source_type, "network_error")


class GeminiSourceDiscovery:
    """Create, poll and approve grounded candidates from Gemini Search."""

    def __init__(
        self,
        db: Session,
        *,
        provider_file: str | Path | None = None,
        probe: SourceProbe | None = None,
        client_factory: type[httpx.Client] = httpx.Client,
        timeout_seconds: float = 45.0,
    ) -> None:
        self.db = db
        self.provider_file = (
            provider_file
            if provider_file is not None
            else os.environ.get(
                "LLM_PROVIDER_ENV_FILE",
                ".env.providers.local",
            )
        )
        self.probe = probe or SourceProbe()
        self.client_factory = client_factory
        self.timeout_seconds = max(1.0, timeout_seconds)

    def start(
        self,
        *,
        subject: str,
        platforms: tuple[str, ...],
        mode: str = "quick",
        max_candidates: int = 20,
    ) -> DiscoveryResult:
        normalized_subject = " ".join(subject.split())
        if not 10 <= len(normalized_subject) <= 2_000:
            raise ValueError("discovery subject must be between 10 and 2000 characters")
        selected_platforms = _normalize_platforms(platforms)
        if mode not in {"quick", "deep"}:
            raise ValueError("discovery mode must be quick or deep")
        limit = max(1, min(50, int(max_candidates)))
        provider, model = self._gemini_route()
        job = DiscoveryJob(
            subject=normalized_subject,
            requested_platforms=list(selected_platforms),
            mode=mode,
            status="running",
            provider="gemini",
            model=model,
            started_at=datetime.now(UTC),
        )
        self.db.add(job)
        self.db.flush()
        prompt = _discovery_prompt(normalized_subject, selected_platforms, limit)
        if mode == "deep":
            body, failure = self._request(
                provider,
                "POST",
                "interactions",
                payload={
                    "agent": _DEEP_AGENT,
                    "input": prompt,
                    "tools": [{"type": "google_search"}],
                    "agent_config": {
                        "type": "deep-research",
                        "thinking_summaries": "none",
                        "visualization": "off",
                        "collaborative_planning": False,
                    },
                    "background": True,
                },
            )
            if failure:
                return self._fail(job, failure)
            interaction_id = str(body.get("id") or "")
            if not interaction_id:
                return self._fail(job, "malformed_response")
            job.interaction_id = interaction_id
            self.db.flush()
            return DiscoveryResult(
                job.id,
                job.status,
                0,
                interaction_id=interaction_id,
            )

        body, failure = self._request(
            provider,
            "POST",
            "interactions",
            payload={
                "model": model,
                "input": prompt,
                "tools": [{"type": "google_search"}],
            },
        )
        if failure:
            return self._fail(job, failure)
        return self._complete(job, body, limit)

    def poll(self, job_id: int, *, max_candidates: int = 20) -> DiscoveryResult:
        job = self.db.get(DiscoveryJob, int(job_id))
        if not isinstance(job, DiscoveryJob):
            raise LookupError("discovery job not found")
        if job.status in {"completed", "failed"}:
            return DiscoveryResult(
                job.id,
                job.status,
                job.candidate_count,
                interaction_id=job.interaction_id,
                failure_category=job.failure_category,
            )
        if job.mode != "deep" or not job.interaction_id:
            raise ValueError("only a running deep discovery job can be polled")
        provider, _model = self._gemini_route()
        body, failure = self._request(
            provider,
            "GET",
            f"interactions/{job.interaction_id}",
        )
        if failure:
            return self._fail(job, failure)
        remote_status = str(body.get("status") or "").casefold()
        if remote_status == "failed":
            return self._fail(job, "provider_failed")
        if remote_status != "completed":
            return DiscoveryResult(
                job.id,
                "running",
                job.candidate_count,
                interaction_id=job.interaction_id,
            )
        return self._complete(
            job,
            body,
            max(1, min(50, int(max_candidates))),
        )

    def candidates(
        self,
        *,
        job_id: int | None = None,
        approval_status: str | None = None,
    ) -> tuple[SourceCandidate, ...]:
        query = self.db.query(SourceCandidate)
        if job_id is not None:
            query = query.filter(SourceCandidate.job_id == int(job_id))
        if approval_status is not None:
            if approval_status not in {"pending", "approved", "rejected"}:
                raise ValueError("invalid approval status")
            query = query.filter(SourceCandidate.approval_status == approval_status)
        return tuple(
            query.order_by(
                SourceCandidate.score.desc(),
                SourceCandidate.id,
            ).all()
        )

    def approve(self, candidate_id: int) -> SourceCandidate:
        candidate = self.db.get(SourceCandidate, int(candidate_id))
        if not isinstance(candidate, SourceCandidate):
            raise LookupError("source candidate not found")
        if candidate.approval_status == "rejected":
            raise ValueError("rejected candidate cannot be approved")
        if candidate.validation_status not in {"reachable", "existing"}:
            raise ValueError("candidate must pass a bounded probe before approval")
        result = NewsroomControl(self.db).add_source(
            name=candidate.name,
            source_type=candidate.source_type,
            url=candidate.normalized_url,
            category="discovered",
            trust_class="community",
            enabled=True,
        )
        candidate.approval_status = "approved"
        candidate.source_id = result.source_id
        candidate.decided_at = datetime.now(UTC)
        self.db.flush()
        return candidate

    def reject(self, candidate_id: int) -> SourceCandidate:
        candidate = self.db.get(SourceCandidate, int(candidate_id))
        if not isinstance(candidate, SourceCandidate):
            raise LookupError("source candidate not found")
        if candidate.approval_status == "approved":
            raise ValueError("approved candidate must be disabled in the source registry")
        candidate.approval_status = "rejected"
        candidate.decided_at = datetime.now(UTC)
        self.db.flush()
        return candidate

    def _gemini_route(self) -> tuple[ProviderConfig, str]:
        config = load_router_config(self.provider_file)
        try:
            provider = config.provider("gemini")
        except KeyError as exc:
            raise ValueError("Gemini is not configured for source discovery") from exc
        if not provider.keys:
            raise ValueError("Gemini access is not configured for source discovery")
        model = next(
            (model for model in _DISCOVERY_MODELS if model in provider.models),
            None,
        )
        if model is None:
            raise ValueError("no search-compatible Gemini model is configured")
        return provider, model

    def _request(
        self,
        provider: ProviderConfig,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        api_base = _interactions_base(str(provider.api_base))
        client_kwargs: dict[str, Any] = {
            "timeout": httpx.Timeout(
                self.timeout_seconds,
                connect=min(15.0, self.timeout_seconds),
            )
        }
        config = load_router_config(self.provider_file)
        if config.proxy_url:
            client_kwargs["proxy"] = config.proxy_url
        for key_value in provider.keys:
            try:
                with self.client_factory(**client_kwargs) as client:
                    response = client.request(
                        method,
                        f"{api_base}/{path.lstrip('/')}",
                        json=payload,
                        headers={
                            "x-goog-api-key": key_value,
                            "Content-Type": "application/json",
                        },
                    )
            except httpx.TimeoutException:
                return {}, "timeout"
            except httpx.HTTPError:
                return {}, "network_error"
            if response.status_code in {401, 403}:
                continue
            if response.status_code == 429:
                return {}, "project_rate_limit"
            if response.status_code >= 500:
                return {}, "provider_error"
            if response.status_code < 200 or response.status_code >= 300:
                return {}, f"provider_http_{response.status_code}"
            try:
                body = response.json()
            except ValueError:
                return {}, "malformed_response"
            return body if isinstance(body, dict) else {}, None
        return {}, "invalid_key"

    def _complete(
        self,
        job: DiscoveryJob,
        body: dict[str, Any],
        limit: int,
    ) -> DiscoveryResult:
        citations = _interaction_citations(body)
        records = _candidate_records(_interaction_text(body))
        if not records:
            records = [
                {
                    "url": citation["url"],
                    "name": citation["title"],
                    "rationale": "",
                }
                for citation in citations
            ]
        requested = frozenset(job.requested_platforms)
        seen: set[str] = set()
        count = 0
        for record in records:
            if count >= limit:
                break
            classified = classify_source_url(record["url"])
            if classified is None:
                continue
            platform, source_type, normalized_url = classified
            if platform not in requested or normalized_url in seen:
                continue
            # A model-proposed URL is never activatable solely on model output:
            # the response must carry grounding evidence and the URL must pass
            # the bounded public-network probe below.
            if not citations:
                continue
            seen.add(normalized_url)
            existing = (
                self.db.query(Source)
                .filter(
                    Source.type == source_type,
                    Source.url == normalized_url,
                )
                .first()
            )
            if isinstance(existing, Source):
                probe = ProbeResult("existing", source_type)
            else:
                probe = self.probe.probe(normalized_url, source_type)
            candidate = SourceCandidate(
                job_id=job.id,
                platform=platform,
                source_type=probe.source_type,
                name=str(
                    record.get("name") or urlparse(normalized_url).hostname or "Discovered source"
                )[:255],
                url=record["url"],
                normalized_url=normalized_url,
                rationale=str(record.get("rationale") or "")[:1_000],
                citations=citations[:5],
                score=_candidate_score(platform, probe.status),
                validation_status=probe.status,
                failure_category=probe.failure_category,
                approval_status="pending",
                source_id=existing.id if isinstance(existing, Source) else None,
            )
            self.db.add(candidate)
            count += 1
        job.status = "completed"
        job.candidate_count = count
        job.completed_at = datetime.now(UTC)
        self.db.flush()
        return DiscoveryResult(
            job.id,
            job.status,
            count,
            interaction_id=job.interaction_id,
        )

    def _fail(self, job: DiscoveryJob, category: str) -> DiscoveryResult:
        job.status = "failed"
        job.failure_category = category
        job.completed_at = datetime.now(UTC)
        self.db.flush()
        return DiscoveryResult(
            job.id,
            job.status,
            job.candidate_count,
            interaction_id=job.interaction_id,
            failure_category=category,
        )


def classify_source_url(url: str) -> tuple[str, str, str] | None:
    """Normalize one grounded URL into the closed source platform registry."""
    parsed = urlparse(url.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        return None
    host = parsed.hostname.casefold().removeprefix("www.")
    unsupported_platform_hosts = {
        "discord.com",
        "facebook.com",
        "instagram.com",
        "linkedin.com",
        "tiktok.com",
        "youtu.be",
        "youtube.com",
    }
    if any(
        host == blocked or host.endswith(f".{blocked}") for blocked in unsupported_platform_hosts
    ):
        return None
    path = re.sub(r"/+", "/", parsed.path).rstrip("/")
    query = parsed.query if host not in {"t.me", "x.com", "twitter.com"} else ""
    if host in {"t.me", "telegram.me"}:
        segments = [segment for segment in path.split("/") if segment]
        if segments[:1] == ["s"]:
            segments = segments[1:]
        reserved = {
            "addlist",
            "addstickers",
            "c",
            "joinchat",
            "login",
            "proxy",
            "share",
        }
        if (
            len(segments) == 1
            and segments[0].casefold() not in reserved
            and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", segments[0])
        ):
            channel_path = f"/{segments[0]}"
            return (
                "telegram",
                "telegram",
                urlunparse(("https", "t.me", channel_path, "", "", "")),
            )
        return None
    if host in {"x.com", "twitter.com"}:
        segments = [segment for segment in path.split("/") if segment]
        reserved = {
            "compose",
            "explore",
            "hashtag",
            "home",
            "i",
            "intent",
            "messages",
            "search",
            "settings",
        }
        if (
            len(segments) == 1
            and segments[0].casefold() not in reserved
            and re.fullmatch(r"[A-Za-z0-9_]{1,15}", segments[0])
        ):
            return (
                "x",
                "x_timeline",
                urlunparse(("https", "x.com", f"/{segments[0]}", "", "", "")),
            )
        return None
    if host in {"reddit.com", "old.reddit.com"} and re.match(
        r"^/r/[^/]+",
        path,
        re.IGNORECASE,
    ):
        subreddit = "/".join(path.split("/")[:3])
        return (
            "reddit",
            "reddit_subreddit",
            urlunparse(("https", "reddit.com", subreddit, "", "", "")),
        )
    if host == "github.com":
        parts = [part for part in path.split("/") if part]
        if len(parts) >= 2:
            repo_path = f"/{parts[0]}/{parts[1]}"
            return (
                "github",
                "github_releases",
                urlunparse(("https", "github.com", repo_path, "", "", "")),
            )
    if _safe_public_host_syntax(host):
        return (
            "web",
            "web_page",
            urlunparse(("https", host, path or "/", "", query, "")),
        )
    return None


def _normalize_platforms(platforms: tuple[str, ...]) -> tuple[str, ...]:
    values = tuple(dict.fromkeys(value.strip().lower() for value in platforms))
    if not values or values == ("all",):
        return tuple(PLATFORM_BY_KEY)
    unknown = set(values) - PLATFORM_BY_KEY.keys()
    if unknown:
        raise ValueError("platforms must use: telegram, x, reddit, github, web")
    return values


def _discovery_prompt(
    subject: str,
    platforms: tuple[str, ...],
    limit: int,
) -> str:
    return (
        "Find durable, high-signal public news sources for this subject:\n"
        f"{subject}\n\n"
        f"Allowed platforms only: {', '.join(platforms)}. "
        "For Telegram return public t.me channel URLs; for X return profile URLs; "
        "for Reddit return subreddit URLs; for GitHub return owner/repository URLs; "
        "for websites return the publication home page or feed. Do not return individual "
        "news articles, private groups, search pages, or unsupported platforms. "
        f"Return at most {limit} candidates as a JSON object with a candidates array. "
        "Each candidate has name, url, and one-sentence rationale. Cite every candidate "
        "with Google Search grounding."
    )


def _interaction_text(body: dict[str, Any]) -> str:
    texts: list[str] = []
    for step in body.get("steps") or []:
        if step.get("type") != "model_output":
            continue
        for block in step.get("content") or []:
            if block.get("type") == "text" and block.get("text"):
                texts.append(str(block["text"]))
    return "\n".join(texts)


def _interaction_citations(body: dict[str, Any]) -> list[dict[str, str]]:
    citations: list[dict[str, str]] = []
    seen: set[str] = set()
    for step in body.get("steps") or []:
        if step.get("type") != "model_output":
            continue
        for block in step.get("content") or []:
            for annotation in block.get("annotations") or []:
                if annotation.get("type") != "url_citation":
                    continue
                url = str(annotation.get("url") or "")
                if url and url not in seen:
                    seen.add(url)
                    citations.append(
                        {
                            "url": url,
                            "title": str(annotation.get("title") or ""),
                        }
                    )
    return citations


def _candidate_records(text: str) -> list[dict[str, str]]:
    raw = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    if fenced:
        raw = fenced.group(1)
    else:
        start, end = raw.find("{"), raw.rfind("}")
        raw = raw[start : end + 1] if start >= 0 and end > start else ""
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return []
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in decoded.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        raw_url = str(item.get("url") or "")
        classified = classify_source_url(raw_url)
        if classified is not None and classified[2] not in seen:
            seen.add(classified[2])
            records.append(
                {
                    "url": raw_url,
                    "name": str(item.get("name") or ""),
                    "rationale": str(item.get("rationale") or ""),
                }
            )
    return records


def _interactions_base(api_base: str) -> str:
    parsed = urlparse(api_base)
    if parsed.hostname == "generativelanguage.googleapis.com":
        path = parsed.path.replace("/openai", "").rstrip("/")
        return urlunparse((parsed.scheme or "https", parsed.netloc, path, "", "", ""))
    return "https://generativelanguage.googleapis.com/v1beta"


def _candidate_score(platform: str, status: str) -> float:
    return min(
        1.0,
        0.4
        + (0.4 if status in {"reachable", "existing"} else 0.0)
        + (0.1 if platform in {"telegram", "github", "reddit", "x"} else 0.0),
    )


def _public_hostname(hostname: str) -> bool:
    if not _safe_public_host_syntax(hostname):
        return False
    try:
        addresses = {
            item[4][0] for item in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        }
    except socket.gaierror:
        return False
    if not addresses:
        return False
    return all(ipaddress.ip_address(address).is_global for address in addresses)


def _safe_public_host_syntax(hostname: str) -> bool:
    """Reject obvious local targets without DNS I/O in pure URL classification."""
    normalized = hostname.casefold().rstrip(".")
    if normalized in {"localhost", "host.docker.internal"} or normalized.endswith(
        (".local", ".localhost", ".internal")
    ):
        return False
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return "." in normalized and not normalized.startswith(".")
    return address.is_global
