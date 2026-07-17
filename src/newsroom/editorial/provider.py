"""Provider-neutral editorial abstraction.

Application code depends on EditorialProvider, not on any vendor SDK.
The interface supports structured requests/responses, timeout, bounded
retries, usage metadata, latency, finish status, and typed error categories.
"""

from __future__ import annotations

import abc
import time

from newsroom.editorial.schema import (
    EditorialError,
    EditorialErrorCategory,
    EditorialRequest,
    EditorialResponse,
)


class EditorialProvider(abc.ABC):
    """Abstract editorial provider — all application code depends on this."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Provider name for metadata."""

    @property
    @abc.abstractmethod
    def model_name(self) -> str:
        """Model name for metadata."""

    @abc.abstractmethod
    def generate(self, request: EditorialRequest) -> EditorialResponse:
        """Generate a structured editorial response.

        Raises EditorialError on failure.
        """


def time_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


__all__ = [
    "EditorialProvider",
    "EditorialError",
    "EditorialErrorCategory",
    "EditorialRequest",
    "EditorialResponse",
    "time_ms",
]
