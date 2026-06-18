from __future__ import annotations

from TeeBotus.llm.base import BaseLLMClient, LLMAPIError, LLMError, LLMImage, LLMResponse, LLMVoice
from TeeBotus.llm.litellm_gemini_provider import LiteLLMGeminiStatefulClient, LiteLLMGeminiStatefulSettings
from TeeBotus.llm.litellm_provider import LiteLLMSettings, LiteLLMTextClient
from TeeBotus.llm.openai_provider import OpenAIProvider

_LAZY_EXPORTS = {
    "LLMProfile": ("TeeBotus.llm.profiles", "LLMProfile"),
    "LLMRoute": ("TeeBotus.llm.profiles", "LLMRoute"),
    "LLMRoutingRule": ("TeeBotus.llm.profiles", "LLMRoutingRule"),
    "build_profiled_text_llm_client": ("TeeBotus.llm.profiles", "build_profiled_text_llm_client"),
    "select_llm_route": ("TeeBotus.llm.profiles", "select_llm_route"),
    "build_text_llm_client": ("TeeBotus.llm.router", "build_text_llm_client"),
    "normalize_llm_provider": ("TeeBotus.llm.router", "normalize_llm_provider"),
}

__all__ = [
    "BaseLLMClient",
    "LLMAPIError",
    "LLMError",
    "LLMImage",
    "LLMResponse",
    "LLMVoice",
    "LiteLLMSettings",
    "LiteLLMGeminiStatefulClient",
    "LiteLLMGeminiStatefulSettings",
    "LiteLLMTextClient",
    "LLMProfile",
    "LLMRoute",
    "LLMRoutingRule",
    "OpenAIProvider",
    "build_profiled_text_llm_client",
    "build_text_llm_client",
    "normalize_llm_provider",
    "select_llm_route",
]


def __getattr__(name: str) -> object:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attribute_name = target
    from importlib import import_module

    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value
