from __future__ import annotations

from typing import Mapping, Protocol

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.base import LLMAPIError, LLMImage, LLMResponse, LLMVoice
from TeeBotus.llm.litellm_provider import (
    LITELLM_PROVIDER_ALIASES,
    LiteLLMSettings,
    LiteLLMTextClient,
    normalize_llm_provider,
    parse_fallback_models,
)


class BaseLLMClient(Protocol):
    def create_reply(
        self,
        user_text: str,
        instructions: BotInstructions,
        previous_response_id: str | None = None,
    ) -> LLMResponse:
        ...


class VoiceLLMClient(Protocol):
    def create_voice(self, text: str, instructions: BotInstructions) -> LLMVoice:
        ...


class ImageLLMClient(Protocol):
    def generate_image(self, prompt: str, instructions: BotInstructions, *, filename: str = "bild.png") -> LLMImage:
        ...


def build_text_llm_client(
    *,
    instructions: BotInstructions,
    openai_client: object | None,
    default_api_key: str = "",
    provider: str = "",
    model: str = "",
    fallback_models: str | tuple[str, ...] = (),
    fallback_api_keys: Mapping[str, str] | None = None,
    fallback_api_bases: Mapping[str, str] | None = None,
    api_key: str = "",
    api_base: str = "",
    purpose: str = "",
    timeout: int | str | None = None,
    temperature: float | str | None = None,
    max_tokens: int | str | None = None,
    use_instruction_fallback_models: bool = True,
) -> object | None:
    resolved_provider = normalize_llm_provider(provider or instructions.llm_provider)
    if resolved_provider == "openai":
        return openai_client
    if resolved_provider == "hf_pool":
        from TeeBotus.llm.hf_pool.provider import HFPoolProvider

        return HFPoolProvider(
            pool_name=model or "default",
            purpose=purpose or "normal_chat",
            fallback_client=_build_hf_pool_fallback_client(
                instructions=instructions,
                fallback_models=fallback_models,
                fallback_api_keys=fallback_api_keys,
                fallback_api_bases=fallback_api_bases,
                timeout=timeout,
                temperature=temperature,
                max_tokens=max_tokens,
            ),
        )
    if resolved_provider in LITELLM_PROVIDER_ALIASES:
        parsed_timeout = _parse_positive_int(timeout)
        parsed_temperature = _parse_optional_float(temperature)
        parsed_max_tokens = _parse_positive_int(max_tokens)
        return LiteLLMTextClient(
            LiteLLMSettings(
                provider=resolved_provider,
                model=model,
                fallback_models=parse_fallback_models(fallback_models),
                fallback_api_keys=fallback_api_keys,
                fallback_api_bases=fallback_api_bases,
                use_instruction_fallback_models=use_instruction_fallback_models,
                api_key=api_key or default_api_key,
                api_base=api_base or instructions.llm_base_url,
                timeout=parsed_timeout or instructions.llm_timeout_seconds or instructions.openai_timeout_seconds,
                temperature=parsed_temperature,
                max_tokens=parsed_max_tokens,
                timeout_override=parsed_timeout is not None,
                temperature_override=parsed_temperature is not None,
                max_tokens_override=parsed_max_tokens is not None,
            )
        )
    raise LLMAPIError(f"Unsupported LLM provider: {provider or instructions.llm_provider}")


def _build_hf_pool_fallback_client(
    *,
    instructions: BotInstructions,
    fallback_models: str | tuple[str, ...],
    fallback_api_keys: Mapping[str, str] | None,
    fallback_api_bases: Mapping[str, str] | None,
    timeout: int | str | None,
    temperature: float | str | None,
    max_tokens: int | str | None,
) -> object | None:
    models = parse_fallback_models(fallback_models)
    if not models:
        return None
    parsed_timeout = _parse_positive_int(timeout)
    parsed_temperature = _parse_optional_float(temperature)
    parsed_max_tokens = _parse_positive_int(max_tokens)
    primary_model = models[0]
    fallback_tail = models[1:]
    api_keys = dict(fallback_api_keys or {})
    api_bases = dict(fallback_api_bases or {})
    primary_api_key = str(api_keys.pop(primary_model, "") or "").strip()
    primary_api_base = str(api_bases.pop(primary_model, "") or "").strip()
    return LiteLLMTextClient(
        LiteLLMSettings(
            provider="litellm",
            model=primary_model,
            fallback_models=fallback_tail,
            fallback_api_keys=api_keys,
            fallback_api_bases=api_bases,
            use_instruction_fallback_models=False,
            api_key=primary_api_key,
            api_base=primary_api_base,
            timeout=parsed_timeout or instructions.llm_timeout_seconds or instructions.openai_timeout_seconds,
            temperature=parsed_temperature,
            max_tokens=parsed_max_tokens,
            timeout_override=parsed_timeout is not None,
            temperature_override=parsed_temperature is not None,
            max_tokens_override=parsed_max_tokens is not None,
        )
    )


def _parse_positive_int(value: int | str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _parse_optional_float(value: float | str | None) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


__all__ = [
    "BaseLLMClient",
    "ImageLLMClient",
    "LLMAPIError",
    "LLMImage",
    "LLMResponse",
    "LLMVoice",
    "LiteLLMSettings",
    "LiteLLMTextClient",
    "VoiceLLMClient",
    "build_text_llm_client",
    "normalize_llm_provider",
]
