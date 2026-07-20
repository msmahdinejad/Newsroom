"""Agent-Reach capability layer — controlled, allowlisted, non-shell boundary.

Public entry points:
- ``run_agent_reach`` / ``run_upstream`` — typed application code only; never
  invoked from editorial AI or from source content.
- ``AgentReachCapabilityRegistry`` — capability + backend registry.

The boundary contract:

  Newsroom source registry
    -> AgentReach capability resolver
    -> allowlisted platform adapter
    -> fixed upstream command (shell=False, arg array)
    -> bounded structured result
    -> Newsroom normalized item

Agent-Reach-specific types never leak past this package into the core pipeline.
"""

from newsroom.sources.agent_reach.adapters import (
    DEFAULT_WEB_ALLOWED_DOMAINS,
    GitHubDiscoveryCollector,
    LinkedInPublicReadCollector,
    RedditPublicReadCollector,
    SSRFError,
    WebPageReader,
    XPublicReadCollector,
    XTimelineCollector,
    YouTubeCollector,
    apply_default_production_decisions,
)
from newsroom.sources.agent_reach.registry import (
    AUTHENTICATED_BY_DEFAULT,
    CHANNELS,
    UNATTENDED_OK_BY_DEFAULT,
    AgentReachCapabilityRegistry,
    BackendState,
    CapabilityEntry,
    ChannelStatus,
    ProductionApproval,
)
from newsroom.sources.agent_reach.runner import (
    ALLOWED_ENV_KEYS,
    AUTHENTICATED_OPERATIONS,
    EXECUTABLE_ALLOWLIST,
    MAX_ARGUMENT_LENGTH,
    OPERATION_ALLOWLIST,
    CommandResult,
    ControlledRunner,
    RunnerError,
    redact_credentials,
    run_agent_reach,
    run_upstream,
    sanitized_environment,
    validate_identifier,
    validate_query,
    validate_repo_identifier,
    validate_url,
    validate_x_handle,
    validate_x_post_id,
    validate_youtube_channel_id,
    validate_youtube_video_id,
)

__all__ = [
    "AgentReachCapabilityRegistry",
    "ALLOWED_ENV_KEYS",
    "AUTHENTICATED_BY_DEFAULT",
    "AUTHENTICATED_OPERATIONS",
    "BackendState",
    "CapabilityEntry",
    "CHANNELS",
    "ChannelStatus",
    "CommandResult",
    "ControlledRunner",
    "DEFAULT_WEB_ALLOWED_DOMAINS",
    "EXECUTABLE_ALLOWLIST",
    "GitHubDiscoveryCollector",
    "LinkedInPublicReadCollector",
    "MAX_ARGUMENT_LENGTH",
    "OPERATION_ALLOWLIST",
    "ProductionApproval",
    "RedditPublicReadCollector",
    "RunnerError",
    "SSRFError",
    "UNATTENDED_OK_BY_DEFAULT",
    "WebPageReader",
    "XPublicReadCollector",
    "XTimelineCollector",
    "YouTubeCollector",
    "apply_default_production_decisions",
    "redact_credentials",
    "run_agent_reach",
    "run_upstream",
    "sanitized_environment",
    "validate_identifier",
    "validate_query",
    "validate_repo_identifier",
    "validate_url",
    "validate_x_handle",
    "validate_x_post_id",
    "validate_youtube_channel_id",
    "validate_youtube_video_id",
]
