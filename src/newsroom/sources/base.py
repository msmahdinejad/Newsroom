"""Base protocol for source collectors."""

from abc import ABC, abstractmethod
from typing import Any


class SourceCollector(ABC):
    """Abstract base for all source collectors."""

    @abstractmethod
    async def collect(self, source_url: str) -> list[dict[str, Any]]:
        """Collect items from source.

        Args:
            source_url: The source URL or identifier

        Returns:
            List of raw items (dicts to be stored as JSON)

        Raises:
            CollectionError: On fetch/parse failures
        """
        pass

    @abstractmethod
    def validate_url(self, source_url: str) -> bool:
        """Check if URL is valid for this collector type.

        Args:
            source_url: URL to validate

        Returns:
            True if valid for this collector type
        """
        pass


class CollectionError(Exception):
    """Raised when collection fails."""

    def __init__(self, message: str, source_url: str, recoverable: bool = True):
        super().__init__(message)
        self.source_url = source_url
        self.recoverable = recoverable
