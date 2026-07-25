"""GitHub releases collector."""

from typing import Any

import httpx

from newsroom.config import settings
from newsroom.logging import get_logger
from newsroom.sources.base import CollectionError, SourceCollector
from newsroom.sources.http_client import build_collection_client
from newsroom.storage.models import Source

logger = get_logger(__name__)


class GitHubCollector(SourceCollector):
    """Collect items from GitHub repository releases."""

    def __init__(self) -> None:
        self.client = build_collection_client(
            timeout=httpx.Timeout(
                connect=settings.collection_timeout_connect,
                read=settings.collection_timeout_read,
                write=30,
                pool=30,
            ),
            follow_redirects=True,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": settings.collection_user_agent,
            },
        )

    async def collect(self, source: Source) -> list[dict[str, Any]]:
        """Collect releases from GitHub repository."""
        try:
            owner, repo = self._parse_repo(source.url)

            api_url = f"https://api.github.com/repos/{owner}/{repo}/releases"
            logger.info(f"Fetching GitHub releases: {owner}/{repo}")
            response = await self.client.get(api_url)

            if response.status_code == 403:
                remaining = response.headers.get("X-RateLimit-Remaining", "0")
                if remaining == "0":
                    reset_time = response.headers.get("X-RateLimit-Reset", "unknown")
                    raise CollectionError(
                        f"Rate limit exceeded (resets at {reset_time})",
                        source.url,
                        recoverable=True,
                    )

            response.raise_for_status()
            releases = response.json()

            items = []
            for release in releases:
                if release.get("draft"):
                    continue
                items.append({
                    "type": "github_releases",
                    "source_id": source.id,
                    "source_name": source.name,
                    "source_url": source.url,
                    "release_id": release.get("id"),
                    "tag_name": release.get("tag_name", ""),
                    "name": release.get("name", "") or release.get("tag_name", ""),
                    "html_url": release.get("html_url", ""),
                    "body": release.get("body", ""),
                    "published_at": release.get("published_at"),
                    "author": release.get("author", {}).get("login", ""),
                    "prerelease": release.get("prerelease", False),
                    "assets": [
                        {
                            "name": a.get("name", ""),
                            "download_url": a.get("browser_download_url", ""),
                            "size": a.get("size", 0),
                        }
                        for a in release.get("assets", [])
                    ],
                })

            logger.info(f"Collected {len(items)} releases from {owner}/{repo}")
            return items

        except CollectionError:
            raise
        except httpx.HTTPStatusError as e:
            raise CollectionError(f"HTTP {e.response.status_code}", source.url, recoverable=True) from e
        except httpx.HTTPError as e:
            raise CollectionError(f"HTTP error: {e}", source.url, recoverable=True) from e
        except Exception as e:
            raise CollectionError(f"Unexpected: {e}", source.url, recoverable=False) from e

    def _parse_repo(self, source_url: str) -> tuple[str, str]:
        """Parse owner/repo from URL or shorthand."""
        if source_url.startswith("https://github.com/"):
            parts = source_url.replace("https://github.com/", "").rstrip("/").split("/", 1)
            if len(parts) < 2:
                raise CollectionError(f"Invalid URL: {source_url}", source_url, recoverable=False)
            # Remove extra path segments, keep owner/repo
            return parts[0], parts[1].split("/")[0]
        if "/" in source_url:
            parts = source_url.split("/", 1)
            return parts[0], parts[1].split("/")[0]
        raise CollectionError(f"Invalid format: {source_url}", source_url, recoverable=False)

    def validate_url(self, source_url: str) -> bool:
        return "github.com/" in source_url or source_url.count("/") == 1

    async def close(self) -> None:
        await self.client.aclose()
