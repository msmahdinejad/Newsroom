"""Shared bounded FIFO dispatcher with provider concurrency and spacing."""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from collections.abc import Callable
from typing import TypeVar

from newsroom.editorial.router.quota import QuotaController
from newsroom.editorial.router.types import (
    Clock,
    DispatchQueueFull,
    ModelRoute,
    RouterStateSink,
    SystemClock,
    Usage,
)
from newsroom.editorial.schema import EditorialResponse

T = TypeVar("T", bound=EditorialResponse)


class QueuedDispatcher:
    """Synchronous production seam with FIFO backpressure across callers.

    The current editorial pipeline is synchronous. Concurrent scheduler/manual
    callers therefore enter this shared queue from threads; provider work stays
    bounded without requiring an event-loop conversion.
    """

    def __init__(
        self,
        *,
        max_queue_size: int = 32,
        clock: Clock | None = None,
        quota: QuotaController | None = None,
        sink: RouterStateSink | None = None,
    ) -> None:
        self.max_queue_size = max(1, max_queue_size)
        self.clock = clock or SystemClock()
        self.quota = quota or QuotaController(clock=self.clock, sink=sink)
        self._condition = threading.Condition(threading.RLock())
        self._waiting: deque[object] = deque()
        self._active: dict[str, int] = defaultdict(int)
        self._last_started: dict[tuple[str, str], float] = {}

    @property
    def queued_count(self) -> int:
        with self._condition:
            return len(self._waiting)

    def dispatch(
        self,
        route: ModelRoute,
        estimated_input_tokens: int,
        call: Callable[[], T],
        *,
        key_fingerprint: str | None = None,
    ) -> T:
        ticket = object()
        admitted = False
        with self._condition:
            if len(self._waiting) >= self.max_queue_size:
                raise DispatchQueueFull()
            self._waiting.append(ticket)
            while True:
                at_front = bool(self._waiting and self._waiting[0] is ticket)
                capacity = self._active[route.provider] < max(1, route.concurrency)
                if at_front and capacity:
                    self._waiting.popleft()
                    self._active[route.provider] += 1
                    admitted = True
                    break
                self._condition.wait()

        reservation = None
        try:
            self._apply_spacing(route)
            reservation = self.quota.reserve(
                route,
                estimated_input_tokens,
                key_fingerprint=key_fingerprint,
            )
            response = call()
            self.quota.reconcile(reservation, Usage.from_response(response))
            return response
        finally:
            if admitted:
                with self._condition:
                    self._active[route.provider] = max(0, self._active[route.provider] - 1)
                    self._condition.notify_all()

    def _apply_spacing(self, route: ModelRoute) -> None:
        spacing_key = (route.provider, route.quota_scope)
        while True:
            with self._condition:
                now = self.clock.monotonic()
                previous = self._last_started.get(spacing_key)
                wait = 0.0 if previous is None else max(0.0, previous + route.min_spacing_seconds - now)
                if wait <= 0:
                    self._last_started[spacing_key] = now
                    return
            self.clock.sleep(wait)
