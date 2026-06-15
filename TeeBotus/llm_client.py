from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Protocol

from TeeBotus.instructions import BotInstructions

LOGGER = logging.getLogger("TeeBotus.llm_client")


class LLMAPIError(RuntimeError):
    """Raised when a configured text LLM provider cannot produce a reply."""


@dataclass(frozen=True)
class LLMResponse:
    text: str
    response_id: str | None = None
    service_tier: str | None = None


class BaseLLMClient(Protocol):
    def create_reply(
        self,
        user_text: str,
        instructions: BotInstructions,
        previous_response_id: str | None = None,
    ) -> LLMResponse:
        ...


class LiteLLMTextClient:
    """Text-only LiteLLM adapter.

    OpenAI-specific capabilities such as images, TTS, transcription, and
    previous_response_id remain owned by OpenAIClient until equivalent
    capability flags exist for other providers.
    """

    def __init__(self, *, api_key: str = "", api_base: str = "", timeout: int = 90) -> None:
        self.api_key = api_key.strip()
        self.api_base = api_base.strip()
        self.timeout = timeout

    def create_reply(
        self,
        user_text: str,
        instructions: BotInstructions,
        previous_response_id: str | None = None,
    ) -> LLMResponse:
        try:
            from litellm import completion
        except ImportError as exc:
            raise LLMAPIError("LiteLLM is not installed") from exc

        model = (instructions.llm_model or instructions.openai_model).strip()
        if not model:
            raise LLMAPIError("LiteLLM model must not be empty")

        kwargs: dict[str, object] = {
            "model": model,
            "messages": [
                {"role": "system", "content": instructions.openai_instructions_text()},
                {"role": "user", "content": user_text},
            ],
            "timeout": instructions.openai_timeout_seconds or self.timeout,
        }
        if instructions.openai_max_output_tokens is not None:
            kwargs["max_tokens"] = instructions.openai_max_output_tokens
        api_base = (instructions.llm_base_url or self.api_base).strip()
        if api_base:
            kwargs["api_base"] = api_base
        api_key = _resolve_litellm_api_key(instructions, self.api_key)
        if api_key:
            kwargs["api_key"] = api_key
        if previous_response_id:
            LOGGER.debug("Ignoring previous_response_id for LiteLLM text provider; provider has no Responses state capability.")

        try:
            response = completion(**kwargs)
        except Exception as exc:  # LiteLLM normalizes provider exceptions, but versions differ.
            raise LLMAPIError(f"LiteLLM completion failed: {exc}") from exc

        text = _extract_litellm_text(response)
        if not text:
            raise LLMAPIError("LiteLLM completion returned empty text")
        response_id = _response_value(response, "id")
        return LLMResponse(text=text, response_id=response_id if isinstance(response_id, str) else None)


def build_text_llm_client(
    *,
    instructions: BotInstructions,
    openai_client: object | None,
    default_api_key: str = "",
) -> object | None:
    provider = normalize_llm_provider(instructions.llm_provider)
    if provider == "openai":
        return openai_client
    if provider == "litellm":
        return LiteLLMTextClient(api_key=default_api_key, api_base=instructions.llm_base_url, timeout=instructions.openai_timeout_seconds)
    raise LLMAPIError(f"Unsupported LLM provider: {instructions.llm_provider}")


def normalize_llm_provider(value: str) -> str:
    normalized = str(value or "").strip().casefold().replace("-", "_")
    if normalized in {"", "openai", "responses", "openai_responses"}:
        return "openai"
    if normalized in {"litellm", "lite_llm", "llm"}:
        return "litellm"
    return normalized


def _resolve_litellm_api_key(instructions: BotInstructions, default_api_key: str) -> str:
    env_name = str(instructions.llm_api_key_env or "").strip()
    if env_name:
        return os.environ.get(env_name, "").strip()
    return default_api_key.strip()


def _extract_litellm_text(response: object) -> str:
    try:
        choices = response["choices"]  # type: ignore[index]
    except (KeyError, TypeError):
        choices = getattr(response, "choices", None)
    if not choices:
        return ""
    first = choices[0]
    try:
        message = first["message"]  # type: ignore[index]
    except (KeyError, TypeError):
        message = getattr(first, "message", None)
    if message is None:
        return ""
    try:
        content = message["content"]  # type: ignore[index]
    except (KeyError, TypeError):
        content = getattr(message, "content", "")
    return str(content or "").strip()


def _response_value(response: object, key: str) -> object:
    try:
        return response[key]  # type: ignore[index]
    except (KeyError, TypeError):
        return getattr(response, key, None)
