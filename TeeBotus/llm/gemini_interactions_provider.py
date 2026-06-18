from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.base import LLMAPIError, LLMResponse
from TeeBotus.llm.capabilities import GEMINI_INTERACTIONS_CAPABILITIES
from TeeBotus.llm.free_tier import (
    GeminiBudgetReservation,
    GeminiFreeTierGuard,
    GeminiFreeTierLimits,
    estimate_litellm_input_tokens,
    quota_owner_id,
    resolve_gemini_free_tier_limits,
)
from TeeBotus.llm.keyring import RotatingAPIKeyRing
from TeeBotus.llm.service_tier import normalize_service_tier

LOGGER = logging.getLogger("TeeBotus.llm.gemini_interactions_provider")


@dataclass(frozen=True)
class GeminiInteractionsSettings:
    model: str
    api_key: str = ""
    api_key_ring: tuple[str, ...] = ()
    timeout: int = 90
    temperature: float | None = None
    max_tokens: int | None = None
    service_tier: str = ""
    store: bool = True
    gemini_free_tier_limits: GeminiFreeTierLimits | None = None


class GeminiInteractionsClient:
    provider_name = "gemini_interactions"
    provider = "gemini_interactions"
    capabilities = GEMINI_INTERACTIONS_CAPABILITIES

    def __init__(self, settings: GeminiInteractionsSettings) -> None:
        self.settings = settings
        self.model = _gemini_model_id(settings.model)
        self.api_key = str(settings.api_key or "").strip()
        self.api_key_ring = RotatingAPIKeyRing(settings.api_key_ring, name=f"gemini_interactions:{self.model}") if settings.api_key_ring else None
        self.timeout = max(1, int(settings.timeout or 90))
        self.temperature = settings.temperature
        self.max_tokens = settings.max_tokens
        self.service_tier = normalize_service_tier(settings.service_tier)
        self.store = bool(settings.store)
        self.gemini_free_tier_limits = settings.gemini_free_tier_limits or resolve_gemini_free_tier_limits(
            provider="gemini",
            model=f"gemini/{self.model}",
        )
        self.gemini_free_tier_guard = GeminiFreeTierGuard(self.gemini_free_tier_limits)

    def create_reply(
        self,
        user_text: str,
        instructions: BotInstructions,
        previous_response_id: str | None = None,
    ) -> LLMResponse:
        try:
            from google import genai
        except ImportError as exc:
            raise LLMAPIError("google-genai is not installed") from exc

        key_attempts = self.api_key_ring.ordered_keys() if self.api_key_ring else (self.api_key or os.environ.get("GEMINI_API_KEY", "").strip(),)
        key_attempts = tuple(key for key in key_attempts if str(key or "").strip())
        if not key_attempts:
            raise LLMAPIError("Gemini Interactions API key is missing")

        errors: list[str] = []
        for api_key in key_attempts:
            reservation = self._reserve_google_free_tier_budget(
                api_key=api_key,
                user_text=user_text,
                instructions=instructions,
            )
            if reservation is not None and not reservation.allowed:
                errors.append(f"model={self.model}: {reservation.reason}")
                if self.api_key_ring:
                    self.api_key_ring.mark_limited(api_key)
                    continue
                break
            try:
                client = genai.Client(api_key=api_key)
                request: dict[str, Any] = {
                    "input": str(user_text or ""),
                    "model": self.model,
                    "store": self.store,
                    "system_instruction": instructions.openai_instructions_text(),
                    "generation_config": _generation_config(self, instructions),
                    "response_modalities": ["text"],
                    "timeout": self.timeout,
                }
                if previous := str(previous_response_id or "").strip():
                    request["previous_interaction_id"] = previous
                if self.service_tier:
                    request["service_tier"] = self.service_tier
                interaction = client.interactions.create(**request)
            except Exception as exc:  # noqa: BLE001 - provider boundary normalizes SDK failures.
                detail = _redact_gemini_error(exc)
                errors.append(f"model={self.model}: {type(exc).__name__}: {detail}")
                LOGGER.warning("Gemini Interactions request failed for model=%s: %s", self.model, detail)
                if self.api_key_ring and _is_usage_limit_error(detail):
                    self.api_key_ring.mark_limited(api_key)
                    continue
                continue
            text = _interaction_output_text(interaction)
            if not text:
                errors.append(f"model={self.model}: empty text")
                continue
            if self.api_key_ring:
                self.api_key_ring.mark_success(api_key)
            return LLMResponse(
                text=text,
                response_id=_interaction_id(interaction),
                provider="gemini_interactions",
                model=f"gemini/{self.model}",
                service_tier=self.service_tier or None,
                usage=_interaction_usage(interaction),
            )
        detail = "; ".join(errors) if errors else "no keys attempted"
        raise LLMAPIError(f"Gemini Interactions request failed for all configured keys: {detail}")

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
            quota_owner=quota_owner_id(api_key=api_key, provider="gemini_interactions", model=self.model),
            model=f"gemini/{self.model}",
            estimated_input_tokens=estimated_input_tokens,
        )
        if not reservation.allowed and self.api_key_ring:
            return GeminiBudgetReservation(
                allowed=False,
                input_tokens=reservation.input_tokens,
                reason=f"{reservation.reason}; trying next configured project key",
            )
        return reservation


def _generation_config(client: GeminiInteractionsClient, instructions: BotInstructions) -> dict[str, object]:
    config: dict[str, object] = {}
    temperature = client.temperature if client.temperature is not None else instructions.llm_temperature
    if temperature is not None:
        config["temperature"] = float(temperature)
    max_tokens = client.max_tokens if client.max_tokens is not None else instructions.llm_max_output_tokens
    if max_tokens is None:
        max_tokens = instructions.openai_max_output_tokens
    if max_tokens is not None:
        config["max_output_tokens"] = int(max_tokens)
    return config


def _gemini_model_id(value: object) -> str:
    model = str(value or "").strip()
    for prefix in ("gemini/", "models/"):
        if model.startswith(prefix):
            model = model[len(prefix) :]
    return model or "gemini-3.5-flash"


def _interaction_output_text(interaction: object) -> str:
    text = getattr(interaction, "output_text", "")
    if isinstance(text, str) and text.strip():
        return text.strip()
    steps = getattr(interaction, "steps", None)
    if isinstance(steps, Sequence):
        parts: list[str] = []
        for step in steps:
            for attr in ("text", "content", "output_text"):
                value = getattr(step, attr, "")
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())
            output = getattr(step, "output", None)
            if isinstance(output, Sequence) and not isinstance(output, (str, bytes, bytearray)):
                for item in output:
                    item_text = getattr(item, "text", "")
                    if isinstance(item_text, str) and item_text.strip():
                        parts.append(item_text.strip())
        if parts:
            return "\n".join(parts).strip()
    return ""


def _interaction_id(interaction: object) -> str | None:
    value = getattr(interaction, "id", "")
    return value if isinstance(value, str) and value.strip() else None


def _interaction_usage(interaction: object) -> dict[str, Any]:
    usage = getattr(interaction, "usage", None)
    if usage is None:
        return {}
    if isinstance(usage, Mapping):
        return dict(usage)
    if hasattr(usage, "model_dump"):
        try:
            payload = usage.model_dump()
        except Exception:
            payload = {}
        return payload if isinstance(payload, dict) else {}
    result: dict[str, Any] = {}
    for name in ("input_tokens", "output_tokens", "total_tokens", "cached_tokens"):
        value = getattr(usage, name, None)
        if value is not None:
            result[name] = value
    return result


def _redact_gemini_error(exc: Exception) -> str:
    text = str(exc or "")
    text = re.sub(r"\bAIza[0-9A-Za-z_-]{16,}\b", "AIza<redacted>", text)
    text = re.sub(r"(?i)(api[_ -]?key|token|secret|password)\s*[:=]\s*([^,\s)]+)", r"\1=<redacted>", text)
    return text.replace("\r", " ").replace("\n", " ").strip()


def _is_usage_limit_error(detail: str) -> bool:
    lowered = str(detail or "").casefold()
    return any(
        marker in lowered
        for marker in (
            "429",
            "rate limit",
            "ratelimit",
            "quota",
            "resource_exhausted",
            "too many requests",
            "usage limit",
        )
    )


__all__ = ["GeminiInteractionsClient", "GeminiInteractionsSettings"]
