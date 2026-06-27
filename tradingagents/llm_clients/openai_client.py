import os
from typing import Any, Optional

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from .base_client import BaseLLMClient, normalize_content
from .validators import validate_model


class NormalizedChatOpenAI(ChatOpenAI):
    """ChatOpenAI with normalized content output.

    The Responses API returns content as a list of typed blocks
    (reasoning, text, etc.). ``invoke`` normalizes to string for
    consistent downstream handling. ``with_structured_output`` defaults
    to function-calling so the Responses-API parse path is avoided
    (langchain-openai's parse path emits noisy
    PydanticSerializationUnexpectedValue warnings per call without
    affecting correctness).

    Provider-specific quirks (e.g. DeepSeek's thinking mode) live in
    purpose-built subclasses below so this base class stays small.
    """

    def invoke(self, input, config=None, **kwargs):
        return normalize_content(super().invoke(input, config, **kwargs))

    def with_structured_output(self, schema, *, method=None, **kwargs):
        if method is None:
            method = "function_calling"
        return super().with_structured_output(schema, method=method, **kwargs)


def _input_to_messages(input_: Any) -> list:
    """Normalise a langchain LLM input to a list of message objects.

    Accepts a list of messages, a ``ChatPromptValue`` (from a
    ChatPromptTemplate), or anything else (treated as no messages).
    Used by providers that need to walk the outgoing message history;
    in particular DeepSeek thinking-mode propagation must work for
    both bare-list invocations and ChatPromptTemplate-driven ones, so
    treating only ``list`` here would silently skip half the call sites.
    """
    if isinstance(input_, list):
        return input_
    if hasattr(input_, "to_messages"):
        return input_.to_messages()
    return []


class DeepSeekChatOpenAI(NormalizedChatOpenAI):
    """DeepSeek-specific overrides on top of the OpenAI-compatible client.

    Two quirks that don't apply to other OpenAI-compatible providers:

    1. **Thinking-mode round-trip.** When DeepSeek's thinking models return
       a response with ``reasoning_content``, that field must be echoed
       back as part of the assistant message on the next turn or the API
       fails with HTTP 400. ``_create_chat_result`` captures the field on
       receive and ``_get_request_payload`` re-attaches it on send.

    2. **deepseek-reasoner has no tool_choice.** Structured output via
       function-calling is unavailable, so we raise NotImplementedError
       and let the agent factories fall back to free-text generation
       (see ``tradingagents/agents/utils/structured.py``).
    """

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        outgoing = payload.get("messages", [])
        for message_dict, message in zip(outgoing, _input_to_messages(input_)):
            if not isinstance(message, AIMessage):
                continue
            reasoning = message.additional_kwargs.get("reasoning_content")
            if reasoning is not None:
                message_dict["reasoning_content"] = reasoning
        return payload

    def _create_chat_result(self, response, generation_info=None):
        chat_result = super()._create_chat_result(response, generation_info)
        response_dict = (
            response
            if isinstance(response, dict)
            else response.model_dump(
                exclude={"choices": {"__all__": {"message": {"parsed"}}}}
            )
        )
        for generation, choice in zip(
            chat_result.generations, response_dict.get("choices", [])
        ):
            reasoning = choice.get("message", {}).get("reasoning_content")
            if reasoning is not None:
                generation.message.additional_kwargs["reasoning_content"] = reasoning
        return chat_result

    def with_structured_output(self, schema, *, method=None, **kwargs):
        if self.model_name == "deepseek-reasoner":
            raise NotImplementedError(
                "deepseek-reasoner does not support tool_choice; structured "
                "output is unavailable. Agent factories fall back to "
                "free-text generation automatically."
            )
        return super().with_structured_output(schema, method=method, **kwargs)

# Kwargs forwarded from user config to ChatOpenAI
_PASSTHROUGH_KWARGS = (
    "timeout", "max_retries", "reasoning_effort",
    "api_key", "callbacks", "http_client", "http_async_client",
)

# Provider base URLs and API key env vars
_PROVIDER_CONFIG = {
    "xai": ("https://api.x.ai/v1", "XAI_API_KEY"),
    "deepseek": ("https://api.deepseek.com", "DEEPSEEK_API_KEY"),
    "qwen": ("https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY"),
    "glm": ("https://api.z.ai/api/paas/v4/", "ZHIPU_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "ollama": ("http://localhost:11434/v1", None),
    "minimax": ("https://api.minimax.chat/v1", "MINIMAX_API_KEY"),
    # 火山方舟（Volcengine Ark）— OpenAI 兼容网关，常用于中转 GLM/Doubao 等。
    "huoshan": ("https://ark.cn-beijing.volces.com/api/coding/v3", "HUOSHAN_API_KEY"),
}


class OpenAIClient(BaseLLMClient):
    """Client for OpenAI, Ollama, OpenRouter, and xAI providers.

    For native OpenAI models, uses the Responses API (/v1/responses) which
    supports reasoning_effort with function tools across all model families
    (GPT-4.1, GPT-5). Third-party compatible providers (xAI, OpenRouter,
    Ollama) use standard Chat Completions.
    """

    def __init__(
        self,
        model: str,
        base_url: Optional[str] = None,
        provider: str = "openai",
        **kwargs,
    ):
        super().__init__(model, base_url, **kwargs)
        self.provider = provider.lower()

    def get_llm(self) -> Any:
        """Return configured ChatOpenAI instance."""
        self.warn_if_unknown_model()
        llm_kwargs = {"model": self.model}

        # Resolve provider endpoint: (default_base_url, api_key_env).
        # Built-ins come from _PROVIDER_CONFIG; custom providers from settings.json.
        default_base, api_key_env = self._resolve_provider_endpoint()

        # base_url precedence: explicit client base_url (e.g. request config's
        # backend_url) > provider default (built-in or custom).
        resolved_base = self.base_url or default_base

        # api_key precedence: settings.json api_key (frontend-managed) >
        # env var (the provider's api_key_env, for .env users) > kwargs.
        # settings.json wins so the frontend can override .env without restart.
        settings_key = self._settings_api_key()
        api_key = settings_key or (os.environ.get(api_key_env) if api_key_env else None)

        if resolved_base is not None or api_key_env is not None or settings_key:
            llm_kwargs["base_url"] = resolved_base
            if api_key_env or settings_key:
                if api_key:
                    llm_kwargs["api_key"] = api_key
                elif "api_key" not in self.kwargs:
                    # No key anywhere — fail with a clear message naming the env
                    # var (for .env users) and mentioning frontend settings.
                    hint = (
                        f"请在 .env 设置 `{api_key_env}`，或在前端「模型配置」填入 API Key。"
                        if api_key_env
                        else f"请在前端「模型配置」填入 {self.provider} 的 API Key。"
                    )
                    raise RuntimeError(
                        f"未找到 {self.provider} 的 API Key。{hint}"
                    )
            else:
                # ollama: no key expected, use a placeholder.
                llm_kwargs["api_key"] = "ollama"
        elif self.base_url:
            llm_kwargs["base_url"] = self.base_url

        # Forward user-provided kwargs
        for key in _PASSTHROUGH_KWARGS:
            if key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]

        # Native OpenAI: use Responses API for consistent behavior across
        # all model families. Third-party providers use Chat Completions.
        if self.provider == "openai":
            llm_kwargs["use_responses_api"] = True

        # DeepSeek's thinking-mode quirks live in their own subclass so the
        # base NormalizedChatOpenAI stays free of provider-specific branches.
        chat_cls = DeepSeekChatOpenAI if self.provider == "deepseek" else NormalizedChatOpenAI
        return chat_cls(**llm_kwargs)

    def _settings_api_key(self) -> Optional[str]:
        """Return the api_key saved for this provider in settings.json, or None.

        Looks up the exact provider name, then the lowercased form. Returns
        None if no key is stored (so .env env-var fallback applies).
        """
        try:
            from tradingagents.settings import get_provider_api_key
            k = get_provider_api_key(self.provider) or get_provider_api_key(self.provider.lower())
            return k or None
        except Exception:
            return None

    def _resolve_provider_endpoint(self) -> tuple:
        """Return (default_base_url, api_key_env) for this provider.

        Checks the hardcoded built-in map first, then settings.json custom
        providers. Returns (None, None) for unknown providers (e.g. a plain
        OpenAI call with an explicit base_url and api_key in kwargs).
        """
        if self.provider in _PROVIDER_CONFIG:
            return _PROVIDER_CONFIG[self.provider]
        try:
            from tradingagents.settings import get_custom_provider
            # Custom providers are stored by exact name; the factory passes the
            # original-case name. Try exact then lowercased.
            cp = get_custom_provider(self.provider) or get_custom_provider(self.provider.lower())
            if cp:
                return cp.get("base_url"), cp.get("api_key_env")
        except Exception:
            pass
        return (None, None)

    def validate_model(self) -> bool:
        """Validate model for the provider."""
        return validate_model(self.provider, self.model)
