"""GitHub releases collector."""

from typing import Any

import httpx

from newsroom.config import settings
from newsroom.logging import get_logger
from newsroom.sources.base import CollectionError, SourceCollector

logger = get_logger(__name__)


class GitHubCollector(SourceCollector):
    """Collect items from GitHub repository releases."""

    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=settings.collection_timeout_connect,
                read=settings.collection_timeout_read,
                write=None,
                pool=None,
            ),
            follow_redirects=True,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "newsroom/0.1.0",
            },
        )

    async def collect(self, source_url: str) -> list[dict[str, Any]]:
        """Collect releases from GitHub repository.

        Args:
            source_url: Repository in format "owner/repo"

        Returns:
            List of raw release items

        Raises:
            CollectionError: On fetch/parse failures
        """
        try:
            # Parse owner/repo from URL or owner/repo format
            if source_url.startswith("https://github.com/"):
                # Full URL: https://github.com/owner/repo
                parts = source_url.replace("https://github.com/", "").rstrip("/").split("/", 1)
                if len(parts) < 2:
                    raise CollectionError(
                        f"Invalid GitHub URL: {source_url}",
                        source_url,
                        recoverable=False,
                    )
                owner, repo = parts[0], parts[1]
            elif "/" in source_url:
                owner, repo = source_url.split("/", 1)
            else:
                raise CollectionError(
                    f"Invalid GitHub repo format: {source_url}",
                    source_url,
                    recoverable=False,
                )
            api_url = f"https://api.github.com/repos/{owner}/{repo}/releases"

            logger.info(f"Fetching GitHub releases: {source_url}")
            response = await self.client.get(api_url)

            # Check rate limit
            if response.status_code == 403:
                remaining = response.headers.get("X-RateLimit-Remaining", "0")
                if remaining == "0":
                    reset_time = response.headers.get("X-RateLimit-Reset", "unknown")
                    raise CollectionError(
                        f"GitHub rate limit exceeded (resets at {reset_time})",
                        source_url,
                        recoverable=True,
                    )

            response.raise_for_status()

            releases = response.json()

            items = []
            for release in releases:
                raw_item = {
                    "type": "github_releases",
                    "source_url": source_url,
                    "release_id": release.get("id"),
                    "tag_name": release.get("tag_name", ""),
                    "name": release.get("name", release.get("tag_name", "")),
                    "html_url": release.get("html_url", ""),
                    "body": release.get("body", ""),
                    "published_at": release.get("published_at"),
                    "author": release.get("author", {}).get("login"),
                    "prerelease": release.get("prerelease", False),
                    "draft": release.get("draft", False),
                    "assets": [
                        {
                            "name": asset.get("name"),
                            "download_url": asset.get("browser_download_url"),
                            "size": asset.get("size"),
                        }
                        for asset in release.get("assets", [])
                    ],
                    "raw_release": release,
                }
                items.append(raw_item)

            logger.info(f"Collected {len(items)} releases from {source_url}")
            return items

        except CollectionError:
            raise  # Re-raise CollectionError as-is
        except httpx.HTTPError as e:
            raise CollectionError(
                f"HTTP error: {e}",
                source_url,
                recoverable=True,
            ) from e
        except Exception as e:
            raise CollectionError(
                f"Unexpected error: {e}",
                source_url,
                recoverable=False,
            ) from e

    def validate_url(self, source_url: str) -> bool:
        """Check if URL looks like owner/repo format."""
        # ponytail: simple check, repo names can have slashes in subpaths
        parts = source_url.split("/")
        return len(parts) >= 2 and all(part.strip() for part in parts[:2])

    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()
