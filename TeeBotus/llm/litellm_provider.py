from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.base import LLMAPIError, LLMResponse

LOGGER = logging.getLogger("TeeBotus.llm.litellm_provider")

LITELLM_PROVIDER_ALIASES = {
    "litellm",
    "ollama",
    "huggingface",
    "hf",
    "groq",
    "gemini",
}
KNOWN_LITELLM_MODEL_PREFIXES = (
    "openai/",
    "ollama/",
    "ollama_chat/",
    "huggingface/",
    "groq/",
    "gemini/",
    "anthropic/",
    "azure/",
    "bedrock/",
    "vertex_ai/",
    "together_ai/",
    "openrouter/",
)


@dataclass(frozen=True)
class LiteLLMSettings:
    model: str
    provider: str = "litellm"
    fallback_models: tuple[str, ...] = ()
    use_instruction_fallback_models: bool = True
    api_key: str = ""
    api_base: str = ""
    timeout: int = 90
    temperature: float | None = None
    max_tokens: int | None = None


class LiteLLMTextClient:
    """Text-only LiteLLM adapter.

    OpenAI-specific capabilities such as images, TTS, transcription, and
    previous_response_id remain owned by OpenAIClient until equivalent
    capability flags exist for other providers.
    """

    provider_name = "litellm"

    def __init__(
        self,
        settings: LiteLLMSettings | None = None,
        *,
        provider: str = "litellm",
        model: str = "",
        fallback_models: tuple[str, ...] = (),
        api_key: str = "",
        api_base: str = "",
        timeout: int = 90,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> None:
        resolved = settings or LiteLLMSettings(
            provider=provider,
            model=model,
            fallback_models=fallback_models,
            api_key=api_key,
            api_base=api_base,
            timeout=timeout,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self.settings = resolved
        self.provider = normalize_llm_provider(resolved.provider)
        self.model = resolved.model.strip()
        self.fallback_models = tuple(item.strip() for item in resolved.fallback_models if item.strip())
        self.use_instruction_fallback_models = bool(resolved.use_instruction_fallback_models)
        self.api_key = resolved.api_key.strip()
        self.api_base = resolved.api_base.strip()
        self.timeout = resolved.timeout
        self.temperature = resolved.temperature
        self.max_tokens = resolved.max_tokens

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

        models = _resolve_litellm_models(
            self.provider,
            instructions,
            self.model,
            self.fallback_models,
            use_instruction_fallback_models=self.use_instruction_fallback_models,
        )
        if not models:
            raise LLMAPIError("LiteLLM model must not be empty")

        kwargs = self._completion_kwargs(user_text, instructions)
        if previous_response_id:
            LOGGER.debug("Ignoring previous_response_id for LiteLLM text provider; provider has no Responses state capability.")

        errors: list[str] = []
        for model in models:
            try:
                response = completion(model=model, **kwargs)
            except Exception as exc:  # LiteLLM normalizes provider exceptions, but versions differ.
                detail = _redact_litellm_error(exc, kwargs)
                errors.append(f"provider={self.provider} model={model}: {type(exc).__name__}: {detail}")
                LOGGER.warning("LiteLLM completion failed for provider=%s model=%s: %s", self.provider, model, detail)
                continue
            text = _extract_litellm_text(response)
            if not text:
                errors.append(f"provider={self.provider} model={model}: empty text")
                LOGGER.warning("LiteLLM completion returned empty text for provider=%s model=%s.", self.provider, model)
                continue
            response_id = _response_value(response, "id")
            return LLMResponse(
                text=text,
                response_id=response_id if isinstance(response_id, str) else None,
                provider="litellm",
                model=model,
                usage=_extract_usage(response),
            )
        detail = "; ".join(errors) if errors else "no models attempted"
        raise LLMAPIError(f"LiteLLM completion failed for all configured models: {detail}")

    def _completion_kwargs(self, user_text: str, instructions: BotInstructions) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "messages": [
                {"role": "system", "content": instructions.openai_instructions_text()},
                {"role": "user", "content": user_text},
            ],
            "timeout": instructions.llm_timeout_seconds or instructions.openai_timeout_seconds or self.timeout,
        }
        max_tokens = instructions.llm_max_output_tokens if instructions.llm_max_output_tokens is not None else self.max_tokens
        if max_tokens is None:
            max_tokens = instructions.openai_max_output_tokens
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        temperature = instructions.llm_temperature if instructions.llm_temperature is not None else self.temperature
        if temperature is not None:
            kwargs["temperature"] = temperature
        api_base = (self.api_base or instructions.llm_base_url).strip()
        if api_base:
            kwargs["api_base"] = api_base
        api_key = _resolve_litellm_api_key(instructions, self.api_key)
        if api_key:
            kwargs["api_key"] = api_key
        return kwargs


def normalize_llm_provider(value: str) -> str:
    normalized = str(value or "").strip().casefold().replace("-", "_")
    if normalized in {"", "openai", "responses", "openai_responses"}:
        return "openai"
    if normalized in {"litellm", "lite_llm", "llm"}:
        return "litellm"
    if normalized in {"ollama", "local_ollama"}:
        return "ollama"
    if normalized in {"huggingface", "hugging_face", "hf"}:
        return "huggingface"
    if normalized in {"groq"}:
        return "groq"
    if normalized in {"gemini", "google", "google_ai"}:
        return "gemini"
    return normalized


def parse_fallback_models(value: str | tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(value, tuple):
        return tuple(str(item or "").strip() for item in value if str(item or "").strip())
    return tuple(part.strip() for part in str(value or "").split(",") if part.strip())


def _resolve_litellm_models(
    provider: str,
    instructions: BotInstructions,
    default_model: str,
    default_fallback_models: tuple[str, ...],
    *,
    use_instruction_fallback_models: bool = True,
) -> tuple[str, ...]:
    configured_model = (default_model or instructions.llm_model).strip()
    if not configured_model:
        if provider == "litellm":
            configured_model = instructions.openai_model.strip()
        else:
            raise LLMAPIError(f"LLM provider {provider} requires llm_model or TEEBOTUS_LLM_MODEL")
    fallback_models = default_fallback_models
    if not fallback_models and use_instruction_fallback_models:
        fallback_models = tuple(instructions.llm_fallback_models)
    ordered = [configured_model, *fallback_models]
    result: list[str] = []
    for model in ordered:
        normalized = _litellm_model_name(provider, model)
        if normalized and normalized not in result:
            result.append(normalized)
    return tuple(result)


def _litellm_model_name(provider: str, model: str) -> str:
    value = model.strip()
    if not value or provider == "litellm":
        return value
    if value.startswith(KNOWN_LITELLM_MODEL_PREFIXES):
        return value
    prefixes = {
        "ollama": "ollama/",
        "huggingface": "huggingface/",
        "groq": "groq/",
        "gemini": "gemini/",
    }
    prefix = prefixes.get(provider, "")
    if prefix and not value.startswith(prefix):
        return f"{prefix}{value}"
    return value


def _resolve_litellm_api_key(instructions: BotInstructions, default_api_key: str) -> str:
    env_name = str(instructions.llm_api_key_env or "").strip()
    if env_name:
        return os.environ.get(env_name, "").strip()
    return default_api_key.strip()


def _redact_litellm_error(exc: Exception, kwargs: dict[str, object]) -> str:
    text = str(exc)
    api_key = str(kwargs.get("api_key") or "").strip()
    if api_key:
        text = text.replace(api_key, "<redacted>")
    # Common provider-key shapes. Keep this conservative so normal diagnostics
    # remain readable while accidental secrets are removed.
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "sk-<redacted>", text)
    text = re.sub(r"\b(xox[baprs]-[A-Za-z0-9-]{8,})\b", "xox-<redacted>", text)
    return text


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


def _extract_usage(response: object) -> dict[str, Any]:
    usage = _response_value(response, "usage")
    if usage is None:
        return {}
    if isinstance(usage, dict):
        return dict(usage)
    if hasattr(usage, "model_dump"):
        try:
            payload = usage.model_dump()
        except Exception:
            payload = None
        if isinstance(payload, dict):
            return payload
    result: dict[str, Any] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = getattr(usage, key, None)
        if isinstance(value, int | float | str):
            result[key] = value
    return result


def _response_value(response: object, key: str) -> object:
    try:
        return response[key]  # type: ignore[index]
    except (KeyError, TypeError):
        return getattr(response, key, None)


__all__ = [
    "LITELLM_PROVIDER_ALIASES",
    "LiteLLMSettings",
    "LiteLLMTextClient",
    "normalize_llm_provider",
    "parse_fallback_models",
]
