"""Base protocol for source collectors."""

from abc import ABC, abstractmethod
from typing import Any

from newsroom.storage.models import Source


class SourceCollector(ABC):
    """Abstract base for all source collectors.

    Every adapter implements: health_check, collect (incremental via cursor),
    parse, and retry classification.
    """

    @abstractmethod
    async def collect(self, source: Source) -> list[dict[str, Any]]:
        """Collect items from source incrementally.

        Args:
            source: Source model with url, config, cursor state

        Returns:
            List of raw item dicts (stored as JSONB)
        """
        pass

    @abstractmethod
    def validate_url(self, source_url: str) -> bool:
        """Check if URL is valid for this collector type."""
        pass

    async def health_check(self, source: Source) -> bool:
        """Quick reachability check. Override for source-specific logic."""
        return self.validate_url(source.url)

    async def close(self) -> None:  # noqa: B027
        """Clean up resources (HTTP clients, sessions)."""
        pass


class CollectionError(Exception):
    """Raised when collection fails."""

    def __init__(self, message: str, source_url: str, recoverable: bool = True):
        super().__init__(message)
        self.source_url = source_url
        self.recoverable = recoverable


def classify_retry(error: Exception) -> str:
    """Classify an error for retry logic.

    Returns: retry/skip/fatal
    """
    if isinstance(error, CollectionError):
        return "retry" if error.recoverable else "skip"
    return "skip"
