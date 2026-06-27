from typing import Optional

from .base_client import BaseLLMClient

# Providers that use the OpenAI-compatible chat completions API
_OPENAI_COMPATIBLE = (
    "openai", "xai", "deepseek", "qwen", "glm", "ollama", "openrouter", "minimax",
    "huoshan",
)

# Providers with dedicated (non-OpenAI) client classes.
_DEDICATED = ("anthropic", "google", "azure")


def builtin_provider_keys() -> tuple[str, ...]:
    """All built-in provider keys (OpenAI-compatible + dedicated clients)."""
    return _OPENAI_COMPATIBLE + _DEDICATED


def _is_openai_compatible(provider_lower: str) -> bool:
    """True for built-in OpenAI-compatible providers OR any custom provider.

    Custom providers (defined in settings.json) are always treated as
    OpenAI-compatible, since users define them as such.
    """
    if provider_lower in _OPENAI_COMPATIBLE:
        return True
    # Custom providers are stored by their exact name; check case-sensitively
    # against settings, but also accept the lowercased form for safety.
    try:
        from tradingagents.settings import list_custom_providers
        customs = list_custom_providers()
        return provider_lower in customs or provider_lower in {k.lower() for k in customs}
    except Exception:
        return False


def create_llm_client(
    provider: str,
    model: str,
    base_url: Optional[str] = None,
    **kwargs,
) -> BaseLLMClient:
    """Create an LLM client for the specified provider.

    Provider modules are imported lazily so that simply importing this
    factory (e.g. during test collection) does not pull in heavy LLM SDKs
    or fail when their API keys are absent.

    Args:
        provider: LLM provider name
        model: Model name/identifier
        base_url: Optional base URL for API endpoint
        **kwargs: Additional provider-specific arguments

    Returns:
        Configured BaseLLMClient instance

    Raises:
        ValueError: If provider is not supported
    """
    provider_lower = provider.lower()

    if _is_openai_compatible(provider_lower):
        from .openai_client import OpenAIClient
        return OpenAIClient(model, base_url, provider=provider, **kwargs)

    if provider_lower == "anthropic":
        from .anthropic_client import AnthropicClient
        return AnthropicClient(model, base_url, **kwargs)

    if provider_lower == "google":
        from .google_client import GoogleClient
        return GoogleClient(model, base_url, **kwargs)

    if provider_lower == "azure":
        from .azure_client import AzureOpenAIClient
        return AzureOpenAIClient(model, base_url, **kwargs)

    raise ValueError(f"Unsupported LLM provider: {provider}")
