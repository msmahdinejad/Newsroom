"""Production multi-provider editorial routing public API."""

from newsroom.editorial.router.config import DEFAULT_MODELS, load_router_config
from newsroom.editorial.router.factory import create_router_from_local_env
from newsroom.editorial.router.http_transport import (
    HttpEditorialTransport,
    build_chat_payload,
    parse_retry_after,
)
from newsroom.editorial.router.key_pool import KeyLease, KeyPool
from newsroom.editorial.router.quota import QuotaController, QuotaReservation
from newsroom.editorial.router.router import MultiProviderRouter
from newsroom.editorial.router.types import (
    CircuitState,
    CircuitStateSnapshot,
    DispatchQueueFull,
    InMemoryRouterStateSink,
    KeyStateSnapshot,
    ManualClock,
    ModelHealthSnapshot,
    ModelRoute,
    ProviderCircuit,
    ProviderConfig,
    QuotaStateSnapshot,
    RateLimits,
    RouteAttemptEvent,
    RoutedEditorialResponse,
    RouteFailure,
    RouteFailureCategory,
    RouterConfig,
    RouterRequestContext,
    RouterStateSink,
    SystemClock,
    Usage,
)
from newsroom.editorial.router.validation import (
    AccessValidationResult,
    ModelValidationResult,
    ModelValidator,
)

__all__ = [
    "DEFAULT_MODELS",
    "AccessValidationResult",
    "CircuitState",
    "CircuitStateSnapshot",
    "DispatchQueueFull",
    "HttpEditorialTransport",
    "InMemoryRouterStateSink",
    "KeyLease",
    "KeyPool",
    "KeyStateSnapshot",
    "ManualClock",
    "ModelHealthSnapshot",
    "ModelRoute",
    "ModelValidationResult",
    "ModelValidator",
    "MultiProviderRouter",
    "ProviderCircuit",
    "ProviderConfig",
    "QuotaController",
    "QuotaReservation",
    "QuotaStateSnapshot",
    "RateLimits",
    "RouteAttemptEvent",
    "RouteFailure",
    "RouteFailureCategory",
    "RoutedEditorialResponse",
    "RouterConfig",
    "RouterRequestContext",
    "RouterStateSink",
    "SystemClock",
    "Usage",
    "build_chat_payload",
    "create_router_from_local_env",
    "load_router_config",
    "parse_retry_after",
]
