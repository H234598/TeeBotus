from __future__ import annotations

from TeeBotus.llm.litellm_gemini_provider import LiteLLMGeminiStatefulClient, LiteLLMGeminiStatefulSettings


GeminiInteractionsSettings = LiteLLMGeminiStatefulSettings


class GeminiInteractionsClient(LiteLLMGeminiStatefulClient):
    """Backward-compatible Gemini Interactions name backed by LiteLLM."""


__all__ = ["GeminiInteractionsClient", "GeminiInteractionsSettings"]
