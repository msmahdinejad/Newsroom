"""Provider-neutral token safety limits."""

PROVIDER_MAX_OUTPUT_TOKENS_CAP = 8_192
APP_SAFETY_OUTPUT_CAP = 8_192
APP_SAFETY_INPUT_CAP = 128_000
PROVIDER_MIN_TOKENS = 1


def effective_output_limit(configured: int) -> int:
    """Clamp an output-token request to the application safety boundary."""
    if configured <= 0:
        return PROVIDER_MIN_TOKENS
    return min(
        configured,
        PROVIDER_MAX_OUTPUT_TOKENS_CAP,
        APP_SAFETY_OUTPUT_CAP,
    )


def effective_input_limit(configured: int) -> int:
    """Clamp an input-token request to the application safety boundary."""
    if configured <= 0:
        return PROVIDER_MIN_TOKENS
    return min(configured, APP_SAFETY_INPUT_CAP)
