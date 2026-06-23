from __future__ import annotations

import logging
import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Any

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.base import LLMAPIError, LLMResponse
from TeeBotus.llm.capabilities import GEMINI_INTERACTIONS_CAPABILITIES
from TeeBotus.llm.free_tier import (
    GeminiBudgetReservation,
    GeminiFreeTierGuard,
    GeminiFreeTierLimits,
    estimate_litellm_input_tokens,
    provider_is_paid_google_gemini,
    provider_is_stateful_google_gemini,
    quota_owner_id,
    resolve_gemini_free_tier_limits,
)
from TeeBotus.llm.keyring import RotatingAPIKeyRing
from TeeBotus.llm.litellm_provider import normalize_llm_provider
from TeeBotus.llm.service_tier import normalize_service_tier

LOGGER = logging.getLogger("TeeBotus.llm.litellm_gemini_provider")
_USAGE_FIELD_NAMES = (
    "prompt_tokens",
    "completion_tokens",
    "input_tokens",
    "output_tokens",
    "input_token_count",
    "output_token_count",
    "total_input_tokens",
    "total_output_tokens",
    "input_tokens_by_modality",
    "output_tokens_by_modality",
    "total_token_count",
    "total_tokens",
    "cached_tokens",
    "total_cached_tokens",
    "cached_tokens_by_modality",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
    "reasoning_tokens",
    "total_reasoning_tokens",
    "total_tool_use_tokens",
    "tool_use_tokens_by_modality",
    "prompt_tokens_details",
    "completion_tokens_details",
    "input_tokens_details",
    "output_tokens_details",
)


@dataclass(frozen=True)
class LiteLLMGeminiStatefulSettings:
    model: str
    provider: str = "litellm_gemini_stateful"
    api_key: str = ""
    api_key_ring: tuple[str, ...] = ()
    timeout: int = 90
    temperature: float | None = None
    max_tokens: int | None = None
    service_tier: str = ""
    store: bool = True
    gemini_free_tier_limits: GeminiFreeTierLimits | None = None


class LiteLLMGeminiStatefulClient:
    provider_name = "litellm_gemini_stateful"
    provider = "litellm_gemini_stateful"
    capabilities = GEMINI_INTERACTIONS_CAPABILITIES

    def __init__(self, settings: LiteLLMGeminiStatefulSettings) -> None:
        self.settings = settings
        self.provider = _normalize_litellm_gemini_stateful_provider(settings.provider)
        self.provider_name = self.provider
        self.model = _litellm_gemini_model_id(settings.model)
        self.api_key = str(settings.api_key or "").strip()
        self.api_key_ring = RotatingAPIKeyRing(settings.api_key_ring, name=f"{self.provider}:{self.model}") if settings.api_key_ring else None
        self.timeout = _first_positive_int(settings.timeout, 90) or 90
        self.temperature = settings.temperature
        self.max_tokens = settings.max_tokens
        self.service_tier = normalize_service_tier(settings.service_tier)
        self.store = bool(settings.store)
        self.gemini_free_tier_limits = _resolve_litellm_gemini_free_tier_limits(
            provider=self.provider,
            model=self.model,
            explicit_limits=settings.gemini_free_tier_limits,
        )
        self.gemini_free_tier_guard = GeminiFreeTierGuard(self.gemini_free_tier_limits)

    def create_reply(
        self,
        user_text: str,
        instructions: BotInstructions,
        previous_response_id: str | None = None,
    ) -> LLMResponse:
        create_interaction = _load_litellm_create_interaction()
        key_attempts = self.api_key_ring.ordered_keys() if self.api_key_ring else (self.api_key or _fallback_gemini_api_key(),)
        key_attempts = tuple(key for key in key_attempts if str(key or "").strip())
        if not key_attempts:
            raise LLMAPIError("LiteLLM Gemini Stateful API key is missing")

        errors: list[str] = []
        for attempt_index, api_key in enumerate(key_attempts):
            reservation = self._reserve_google_free_tier_budget(
                api_key=api_key,
                user_text=user_text,
                instructions=instructions,
            )
            if reservation is not None and not reservation.allowed:
                errors.append(f"provider={self.provider} model={self.model}: {reservation.reason}")
                if self.api_key_ring:
                    self.api_key_ring.mark_limited(api_key)
                    continue
                break
            request = self._interaction_kwargs(
                user_text=user_text,
                instructions=instructions,
                api_key=api_key,
                previous_response_id=previous_response_id if attempt_index == 0 else None,
            )
            try:
                interaction = create_interaction(**request)
            except Exception as exc:  # noqa: BLE001 - provider boundary normalizes SDK failures.
                detail = _redact_litellm_gemini_error(exc, request)
                errors.append(f"provider={self.provider} model={self.model}: {type(exc).__name__}: {detail}")
                LOGGER.warning("LiteLLM Gemini Stateful interaction failed for model=%s: %s", self.model, detail)
                if self.api_key_ring and _is_usage_limit_error(exc, detail):
                    self.api_key_ring.mark_limited(api_key)
                    continue
                break
            text = _interaction_output_text(interaction)
            if not text:
                errors.append(f"provider={self.provider} model={self.model}: empty text")
                break
            usage = _interaction_usage(interaction)
            _add_litellm_response_cost(usage, interaction)
            if reservation is not None:
                actual_input_tokens = _extract_input_tokens(usage)
                if actual_input_tokens is not None:
                    self.gemini_free_tier_guard.adjust_reserved_tokens(
                        quota_owner=_gemini_quota_owner(api_key=api_key, provider=self.provider, model=self.model),
                        model=self.model,
                        reserved_input_tokens=reservation.input_tokens,
                        actual_input_tokens=actual_input_tokens,
                    )
            if self.api_key_ring:
                self.api_key_ring.mark_success(api_key)
            return LLMResponse(
                text=text,
                response_id=_interaction_id(interaction),
                provider=self.provider,
                model=self.model,
                service_tier=self.service_tier or None,
                usage=usage,
            )
        detail = "; ".join(errors) if errors else "no keys attempted"
        raise LLMAPIError(f"LiteLLM Gemini Stateful interaction failed for all configured keys: {detail}")

    def _interaction_kwargs(
        self,
        *,
        user_text: str,
        instructions: BotInstructions,
        api_key: str,
        previous_response_id: str | None,
    ) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "model": self.model,
            "input": str(user_text or ""),
            "system_instruction": instructions.openai_instructions_text(),
            "generation_config": _generation_config(self, instructions),
            "api_key": api_key,
            "timeout": self.timeout,
            "store": self.store,
        }
        previous = str(previous_response_id or "").strip()
        if previous:
            kwargs["previous_interaction_id"] = previous
        if self.service_tier:
            kwargs["service_tier"] = self.service_tier
        return kwargs

    def _reserve_google_free_tier_budget(
        self,
        *,
        api_key: str,
        user_text: str,
        instructions: BotInstructions,
    ) -> GeminiBudgetReservation | None:
        messages = (
            {"role": "system", "content": instructions.openai_instructions_text()},
            {"role": "user", "content": user_text},
        )
        estimated_input_tokens = estimate_litellm_input_tokens(messages)
        reservation = self.gemini_free_tier_guard.reserve(
            quota_owner=_gemini_quota_owner(api_key=api_key, provider=self.provider, model=self.model),
            model=self.model,
            estimated_input_tokens=estimated_input_tokens,
        )
        if not reservation.allowed and self.api_key_ring:
            return GeminiBudgetReservation(
                allowed=False,
                input_tokens=reservation.input_tokens,
                reason=f"{reservation.reason}; trying next configured project key",
            )
        return reservation


def _load_litellm_create_interaction() -> Any:
    try:
        import litellm
    except ImportError as exc:
        raise LLMAPIError("LiteLLM is not installed") from exc
    create_interaction = getattr(litellm, "create_interaction", None)
    if callable(create_interaction):
        return create_interaction
    interactions = getattr(litellm, "interactions", None)
    create = getattr(interactions, "create", None)
    if callable(create):
        return create
    raise LLMAPIError("Installed LiteLLM does not expose create_interaction/interactions.create")


def _generation_config(client: LiteLLMGeminiStatefulClient, instructions: BotInstructions) -> dict[str, object]:
    config: dict[str, object] = {}
    temperature = _first_optional_float(client.temperature, instructions.llm_temperature)
    if temperature is not None:
        config["temperature"] = temperature
    max_tokens = _first_positive_int(client.max_tokens, instructions.llm_max_output_tokens, instructions.openai_max_output_tokens)
    if max_tokens is not None:
        config["max_output_tokens"] = max_tokens
    return config


def _first_optional_float(*values: object) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            parsed = float(str(value).strip())
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed) and parsed >= 0:
            return parsed
    return None


def _first_positive_int(*values: object) -> int | None:
    for value in values:
        if value is None:
            continue
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return None


def _fallback_gemini_api_key() -> str:
    google_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if google_key:
        return google_key
    return os.environ.get("GEMINI_API_KEY", "").strip()


def _litellm_gemini_model_id(value: object) -> str:
    model = str(value or "").strip()
    if model.casefold().startswith("models/"):
        model = model[len("models/") :]
    if model.casefold().startswith("gemini/"):
        model = f"gemini/{model[len('gemini/') :]}"
    elif model:
        model = f"gemini/{model}"
    return model or "gemini/gemini-3.5-flash"


def _normalize_litellm_gemini_stateful_provider(value: object) -> str:
    provider = normalize_llm_provider(str(value or ""))
    if provider_is_paid_google_gemini(provider):
        return "litellm_gemini_paid_stateful"
    if provider_is_stateful_google_gemini(provider):
        return "litellm_gemini_stateful"
    return "litellm_gemini_stateful"


def _resolve_litellm_gemini_free_tier_limits(
    *,
    provider: str,
    model: str,
    explicit_limits: GeminiFreeTierLimits | None,
) -> GeminiFreeTierLimits:
    if provider_is_paid_google_gemini(provider):
        return GeminiFreeTierLimits(enabled=False, requests_per_minute=None, input_tokens_per_minute=None, requests_per_day=None)
    return explicit_limits or resolve_gemini_free_tier_limits(provider=provider, model=model)


def _interaction_output_text(interaction: object) -> str:
    text = _interaction_content_text(_object_value(interaction, "output_text"))
    if text:
        return text
    outputs = _object_value(interaction, "outputs")
    if isinstance(outputs, Sequence) and not isinstance(outputs, (str, bytes, bytearray)):
        parts: list[str] = []
        for item in outputs:
            item_text = _interaction_content_text(item)
            if item_text:
                parts.append(item_text)
        if parts:
            return "\n".join(parts).strip()
    choices = _object_value(interaction, "choices")
    if isinstance(choices, Sequence) and not isinstance(choices, (str, bytes, bytearray)):
        parts = []
        for choice in choices:
            message = _object_value(choice, "message")
            content = _object_value(message, "content") if message is not None else ""
            content_text = _interaction_content_text(content)
            if content_text:
                parts.append(content_text)
        if parts:
            return "\n".join(parts).strip()
    steps = _object_value(interaction, "steps")
    if isinstance(steps, Sequence) and not isinstance(steps, (str, bytes, bytearray)):
        parts = []
        for step in steps:
            step_root = _object_value(step, "root")
            if step_root is not None and step_root is not step:
                root_text = _interaction_content_text(step_root)
                if root_text:
                    parts.append(root_text)
                    continue
            for attr in ("text", "content", "output_text", "delta", "step"):
                value_text = _interaction_content_text(_object_value(step, attr))
                if value_text:
                    parts.append(value_text)
            output = _object_value(step, "output")
            if isinstance(output, Sequence) and not isinstance(output, (str, bytes, bytearray)):
                for item in output:
                    item_text = _interaction_content_text(item)
                    if item_text:
                        parts.append(item_text)
        if parts:
            return "\n".join(parts).strip()
    return ""


def _interaction_content_text(content: object) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, Mapping):
        return _interaction_content_item_text(content)
    if isinstance(content, Sequence) and not isinstance(content, (str, bytes, bytearray)):
        parts = [_interaction_content_item_text(item) for item in content]
        return "\n".join(part for part in parts if part).strip()
    if isinstance(content, (int, float, bool)):
        return str(content).strip()
    return _interaction_content_item_text(content)


def _interaction_content_item_text(item: object) -> str:
    if isinstance(item, str):
        return item.strip()
    root = _object_value(item, "root")
    if root is not None and root is not item:
        root_text = _interaction_content_text(root)
        if root_text:
            return root_text
    item_type = str(_object_value(item, "type") or "").strip().casefold()
    if item_type and item_type not in {"text", "output_text", "refusal", "content.delta", "step.delta", "step.start"}:
        return ""
    for key in ("text", "content", "output_text", "refusal", "delta", "step", "value"):
        value = _object_value(item, key)
        if value is item:
            continue
        text = _interaction_content_text(value)
        if text:
            return text
    return ""


def _interaction_id(interaction: object) -> str | None:
    value = _object_value(interaction, "id")
    return value if isinstance(value, str) and value.strip() else None


def _interaction_usage(interaction: object) -> dict[str, Any]:
    usage = _object_value(interaction, "usage")
    if usage is None:
        return {}
    if isinstance(usage, Mapping):
        return dict(usage)
    model_dump = _object_value(usage, "model_dump")
    if callable(model_dump):
        try:
            payload = model_dump()
        except Exception:
            payload = None
        if isinstance(payload, dict) and any(value is not None for value in payload.values()):
            result = {key: value for key, value in payload.items() if value is not None}
            _fill_usage_attrs(result, usage)
            return result
    result: dict[str, Any] = {}
    _fill_usage_attrs(result, usage)
    return result


def _fill_usage_attrs(result: dict[str, Any], usage: object) -> None:
    for name in _USAGE_FIELD_NAMES:
        value = _object_value(usage, name)
        if value is not None and result.get(name) is None:
            result[name] = value


def _extract_input_tokens(usage: Mapping[str, Any]) -> int | None:
    for key in ("prompt_tokens", "input_tokens", "input_token_count", "total_input_tokens"):
        parsed = _parse_nonnegative_token_count(usage.get(key))
        if parsed is not None:
            return parsed
    return _sum_token_breakdown(usage.get("input_tokens_by_modality"))


def _sum_token_breakdown(value: object, *, depth: int = 0) -> int | None:
    if depth > 4:
        return None
    if isinstance(value, Mapping):
        items = (value,)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items = tuple(value)
    else:
        return None
    total = 0
    found = False
    for item in items:
        parsed = _token_breakdown_item_count(item, depth=depth)
        if parsed is not None:
            total += parsed
            found = True
    return total if found else None


def _token_breakdown_item_count(item: object, *, depth: int = 0) -> int | None:
    for key in ("tokens", "token_count", "count"):
        token_value = _object_value(item, key)
        if token_value is None:
            continue
        parsed = _parse_nonnegative_token_count(token_value)
        if parsed is not None:
            return parsed
    if not isinstance(item, Mapping):
        return _parse_nonnegative_token_count(item)
    total = 0
    found = False
    for value in item.values():
        parsed = _parse_nonnegative_token_count(value)
        if parsed is None:
            parsed = _sum_token_breakdown(value, depth=depth + 1)
        if parsed is None:
            continue
        total += parsed
        found = True
    return total if found else None


def _parse_nonnegative_token_count(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        return None
    if isinstance(value, Decimal):
        if not value.is_finite() or value != value.to_integral_value():
            return None
    if isinstance(value, Fraction) and value.denominator != 1:
        return None
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= 0 else None


def _add_litellm_response_cost(usage: dict[str, Any], response: object) -> None:
    cost = _litellm_response_cost(response)
    if cost is not None:
        usage.setdefault("response_cost", cost)


def _litellm_response_cost(response: object) -> object | None:
    hidden = _object_value(response, "_hidden_params")
    value = _object_value(hidden, "response_cost") if hidden is not None else None
    if value is None:
        value = _object_value(response, "response_cost")
    return value


def _gemini_quota_owner(*, api_key: str, provider: str, model: str) -> str:
    owner_provider = "google_gemini_paid" if provider_is_paid_google_gemini(provider) else "google_gemini"
    return quota_owner_id(api_key=api_key, provider=owner_provider, model=model or provider)


def _object_value(source: object, key: str) -> object:
    if source is None:
        return None
    try:
        return source[key]  # type: ignore[index]
    except Exception:
        pass
    try:
        return getattr(source, key, None)
    except Exception:
        return None


def _redact_litellm_gemini_error(exc: Exception, kwargs: Mapping[str, object]) -> str:
    from TeeBotus.llm.litellm_provider import _redact_litellm_error

    return _redact_litellm_error(exc, dict(kwargs))


def _is_usage_limit_error(exc: Exception, redacted_detail: str) -> bool:
    from TeeBotus.llm.litellm_provider import _is_usage_limit_error as litellm_is_usage_limit_error

    return litellm_is_usage_limit_error(exc, redacted_detail)


__all__ = [
    "LiteLLMGeminiStatefulClient",
    "LiteLLMGeminiStatefulSettings",
]
