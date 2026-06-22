from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.base import LLMAPIError, LLMResponse
from TeeBotus.llm.capabilities import LITELLM_TEXT_CAPABILITIES
from TeeBotus.llm.free_tier import (
    GeminiBudgetReservation,
    GeminiFreeTierGuard,
    GeminiFreeTierLimits,
    estimate_litellm_input_tokens,
    provider_is_paid_google_gemini,
    quota_owner_id,
    resolve_gemini_free_tier_limits,
    route_uses_gemini_api,
    route_uses_google_gemini,
)
from TeeBotus.llm.keyring import RotatingAPIKeyRing
from TeeBotus.runtime.log_context import logging_context, next_llm_call_id

LOGGER = logging.getLogger("TeeBotus.llm.litellm_provider")
LOCAL_OLLAMA_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

LITELLM_PROVIDER_ALIASES = {
    "litellm",
    "litellm_gemini_stateless",
    "litellm_gemini_paid_stateless",
    "ollama",
    "huggingface",
    "hf",
    "groq",
    "gemini",
    "vertex_ai",
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
URL_CREDENTIAL_RE = re.compile(r"(?:[a-z][a-z0-9+.-]*://|(?:target|base_url|api_base|url)=)[^\s/@:=]+:[^\s/@]+@", re.IGNORECASE)
SECRET_ASSIGNMENT_RE = re.compile(
    r"\b([A-Za-z0-9_ -]*(?:api[_ -]?key|access[_ -]?token|auth[_ -]?token|bearer[_ -]?token|token|secret|password)[A-Za-z0-9_ -]*)\s*[:=]\s*([^,\s)]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LiteLLMSettings:
    model: str
    provider: str = "litellm"
    fallback_models: tuple[str, ...] = ()
    fallback_api_keys: Mapping[str, str] | None = None
    fallback_api_bases: Mapping[str, str] | None = None
    use_instruction_fallback_models: bool = True
    api_key: str = ""
    api_key_ring: tuple[str, ...] = ()
    api_base: str = ""
    timeout: int = 90
    temperature: float | None = None
    max_tokens: int | None = None
    service_tier: str = ""
    timeout_override: bool = False
    temperature_override: bool = False
    max_tokens_override: bool = False
    gemini_free_tier_limits: GeminiFreeTierLimits | None = None


class LiteLLMTextClient:
    """Text-only LiteLLM adapter.

    OpenAI-specific capabilities such as images, TTS, transcription, and
    previous_response_id remain owned by OpenAIClient until equivalent
    capability flags exist for other providers.
    """

    provider_name = "litellm"
    capabilities = LITELLM_TEXT_CAPABILITIES

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
            fallback_api_keys=None,
            fallback_api_bases=None,
            api_key=api_key,
            api_key_ring=(),
            api_base=api_base,
            timeout=timeout,
            temperature=temperature,
            max_tokens=max_tokens,
            service_tier="",
        )
        self.settings = resolved
        self.provider = normalize_llm_provider(resolved.provider)
        self.provider_name = self.provider if self.provider in {"litellm_gemini_stateless", "litellm_gemini_paid_stateless"} else "litellm"
        self.model = resolved.model.strip()
        self.fallback_models = tuple(item.strip() for item in resolved.fallback_models if item.strip())
        self.fallback_api_keys = {
            str(model or "").strip(): str(api_key or "").strip()
            for model, api_key in dict(resolved.fallback_api_keys or {}).items()
            if str(model or "").strip() and str(api_key or "").strip()
        }
        self.fallback_api_bases = {
            str(model or "").strip(): str(api_base or "").strip()
            for model, api_base in dict(resolved.fallback_api_bases or {}).items()
            if str(model or "").strip() and str(api_base or "").strip()
        }
        self.use_instruction_fallback_models = bool(resolved.use_instruction_fallback_models)
        self.api_key = resolved.api_key.strip()
        self.api_key_ring = RotatingAPIKeyRing(resolved.api_key_ring, name=f"{self.provider}:{self.model}") if resolved.api_key_ring else None
        self.api_base = resolved.api_base.strip()
        self.timeout = resolved.timeout
        self.temperature = resolved.temperature
        self.max_tokens = resolved.max_tokens
        self.service_tier = _normalize_litellm_service_tier(resolved.service_tier)
        self.gemini_free_tier_limits = _resolve_litellm_gemini_free_tier_limits(
            provider=self.provider,
            model=self.model,
            fallback_models=self.fallback_models,
            explicit_limits=resolved.gemini_free_tier_limits,
        )
        self.gemini_free_tier_guard = GeminiFreeTierGuard(self.gemini_free_tier_limits)

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

        if previous_response_id:
            LOGGER.debug("Ignoring previous_response_id for LiteLLM text provider; provider has no Responses state capability.")

        errors: list[str] = []
        base_kwargs = self._completion_kwargs(user_text, instructions)
        _validate_litellm_local_service_targets(models, base_kwargs, fallback_api_bases=self.fallback_api_bases)
        for model in models:
            for ring_key in self._api_key_attempts_for_model(model):
                kwargs = self._completion_kwargs_for_model(base_kwargs, model, api_key_override=ring_key)
                quota_owner = quota_owner_id(
                    api_key=str(kwargs.get("api_key") or ""),
                    provider=_quota_owner_provider(provider=self.provider, model=model),
                    model=model,
                    api_base=str(kwargs.get("api_base") or ""),
                )
                reservation = self._reserve_google_free_tier_budget(
                    quota_owner=quota_owner,
                    model=model,
                    kwargs=kwargs,
                    ring_key=ring_key,
                )
                if reservation is not None and not reservation.allowed:
                    errors.append(f"provider={self.provider} model={model}: {reservation.reason}")
                    LOGGER.warning(
                        "LiteLLM Gemini/Vertex free-tier guard skipped provider call for provider=%s model=%s: %s",
                        self.provider,
                        model,
                        reservation.reason,
                    )
                    if ring_key:
                        self.api_key_ring.mark_limited(ring_key)  # type: ignore[union-attr]
                        continue
                    continue
                call_id = next_llm_call_id("litellm")
                started_at = time.perf_counter()
                api_base_log = _safe_litellm_api_base(kwargs.get("api_base"))
                try:
                    with logging_context(
                        component="litellm",
                        operation="completion",
                        purpose=self.provider_name,
                        llm_call_id=call_id,
                        provider=self.provider,
                        model=model,
                        api_base=api_base_log,
                    ):
                        LOGGER.info(
                            "LiteLLM completion started call_id=%s provider=%s model=%s api_base=%s timeout=%s fallback_count=%s",
                            call_id,
                            self.provider,
                            model,
                            api_base_log,
                            kwargs.get("timeout"),
                            len(models) - 1,
                        )
                        response = completion(model=model, **kwargs)
                except Exception as exc:  # LiteLLM normalizes provider exceptions, but versions differ.
                    detail = _redact_litellm_error(exc, kwargs)
                    errors.append(f"provider={self.provider} model={model}: {type(exc).__name__}: {detail}")
                    LOGGER.warning("LiteLLM completion failed call_id=%s provider=%s model=%s: %s", call_id, self.provider, model, detail)
                    if ring_key and _is_usage_limit_error(exc, detail):
                        self.api_key_ring.mark_limited(ring_key)  # type: ignore[union-attr]
                        LOGGER.warning("Gemini/LiteLLM API key hit a usage limit; trying next configured key.")
                        continue
                    break
                text = _extract_litellm_text(response)
                if not text:
                    errors.append(f"provider={self.provider} model={model}: empty text")
                    LOGGER.warning("LiteLLM completion returned empty text for provider=%s model=%s.", self.provider, model)
                    break
                usage = _extract_usage(response)
                _add_litellm_response_cost(usage, response)
                LOGGER.info(
                    "LiteLLM completion finished call_id=%s provider=%s model=%s elapsed_ms=%s response_chars=%s usage=%s",
                    call_id,
                    self.provider,
                    model,
                    int((time.perf_counter() - started_at) * 1000),
                    len(text),
                    _compact_usage_for_log(usage),
                )
                if reservation is not None:
                    actual_input_tokens = _extract_input_tokens(usage)
                    if actual_input_tokens is not None:
                        self.gemini_free_tier_guard.adjust_reserved_tokens(
                            quota_owner=quota_owner,
                            model=model,
                            reserved_input_tokens=reservation.input_tokens,
                            actual_input_tokens=actual_input_tokens,
                        )
                if ring_key:
                    self.api_key_ring.mark_success(ring_key)  # type: ignore[union-attr]
                return LLMResponse(
                    text=text,
                    response_id=None,
                    provider=self.provider_name,
                    model=model,
                    usage=usage,
                )
        detail = "; ".join(errors) if errors else "no models attempted"
        raise LLMAPIError(f"LiteLLM completion failed for all configured models: {detail}")

    def _completion_kwargs(self, user_text: str, instructions: BotInstructions, *, api_key_override: str | None = None) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "messages": [
                {"role": "system", "content": instructions.openai_instructions_text()},
                {"role": "user", "content": user_text},
            ],
            "timeout": self.timeout
            if self.settings.timeout_override
            else (instructions.llm_timeout_seconds or instructions.openai_timeout_seconds or self.timeout),
        }
        max_tokens = self.max_tokens if self.settings.max_tokens_override else instructions.llm_max_output_tokens
        if max_tokens is None:
            max_tokens = self.max_tokens
        if max_tokens is None:
            max_tokens = instructions.openai_max_output_tokens
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        temperature = self.temperature if self.settings.temperature_override else instructions.llm_temperature
        if temperature is None:
            temperature = self.temperature
        if temperature is not None:
            kwargs["temperature"] = temperature
        api_base = (self.api_base or instructions.llm_base_url).strip()
        if api_base:
            kwargs["api_base"] = api_base
        api_key = str(api_key_override or "").strip() or _resolve_litellm_api_key(instructions, self.api_key)
        if api_key:
            kwargs["api_key"] = api_key
        return kwargs

    def _completion_kwargs_for_model(
        self,
        base_kwargs: dict[str, object],
        model: str,
        *,
        api_key_override: str | None = None,
    ) -> dict[str, object]:
        kwargs = dict(base_kwargs)
        api_base = self.fallback_api_bases.get(model)
        if api_base:
            kwargs["api_base"] = api_base
        api_key = self.fallback_api_keys.get(model)
        if api_key:
            kwargs["api_key"] = api_key
        ring_key = str(api_key_override or "").strip()
        if ring_key:
            kwargs["api_key"] = ring_key
        if self.service_tier and route_uses_google_gemini(provider=self.provider, model=model):
            kwargs["service_tier"] = self.service_tier
        return kwargs

    def _api_key_attempts_for_model(self, model: str) -> tuple[str | None, ...]:
        if self.api_key_ring is None:
            return (None,)
        if not route_uses_gemini_api(provider=self.provider, model=model):
            return (None,)
        return tuple(self.api_key_ring.ordered_keys())

    def _reserve_google_free_tier_budget(
        self,
        *,
        quota_owner: str,
        model: str,
        kwargs: Mapping[str, object],
        ring_key: str | None,
    ) -> GeminiBudgetReservation | None:
        if not route_uses_google_gemini(provider=self.provider, model=model):
            return None
        messages = kwargs.get("messages")
        if not isinstance(messages, Sequence):
            return None
        estimated_input_tokens = estimate_litellm_input_tokens(
            tuple(message for message in messages if isinstance(message, Mapping))
        )
        reservation = self.gemini_free_tier_guard.reserve(
            quota_owner=quota_owner,
            model=model,
            estimated_input_tokens=estimated_input_tokens,
        )
        if not reservation.allowed and ring_key:
            reservation = GeminiBudgetReservation(
                allowed=False,
                input_tokens=reservation.input_tokens,
                reason=f"{reservation.reason}; trying next configured project key",
            )
        return reservation


def normalize_llm_provider(value: str) -> str:
    normalized = str(value or "").strip().casefold().replace("-", "_")
    if normalized in {"", "openai", "responses", "openai_responses"}:
        return "openai"
    if normalized in {"litellm", "lite_llm", "llm"}:
        return "litellm"
    if normalized in {"litellm_gemini_stateless", "litellm_gemini_text", "gemini_stateless_litellm"}:
        return "litellm_gemini_stateless"
    if normalized in {
        "litellm_gemini_paid_stateless",
        "litellm_gemini_paid_state_less",
        "litellm_gemini_paid_text",
        "gemini_paid_stateless_litellm",
    }:
        return "litellm_gemini_paid_stateless"
    if normalized in {
        "litellm_gemini_stateful",
        "litellm_gemini_statefull",
        "litellm_gemini_interactions",
        "gemini_interactions",
        "google_interactions",
        "interactions",
        "gemini_stateful",
        "gemini_statefull",
    }:
        return "litellm_gemini_stateful"
    if normalized in {
        "litellm_gemini_paid_stateful",
        "litellm_gemini_paid_statefull",
        "litellm_gemini_paid_interactions",
        "gemini_paid_stateful",
        "gemini_paid_statefull",
        "gemini_paid_interactions",
    }:
        return "litellm_gemini_paid_stateful"
    if normalized in {"ollama", "local_ollama"}:
        return "ollama"
    if normalized in {"huggingface", "hugging_face", "hf"}:
        return "huggingface"
    if normalized in {"hf_pool", "hfpool", "huggingface_pool", "hugging_face_pool"}:
        return "hf_pool"
    if normalized in {"groq"}:
        return "groq"
    if normalized in {"gemini", "google", "google_ai"}:
        return "gemini"
    if normalized in {"vertex", "vertex_ai", "google_vertex", "google_vertex_ai"}:
        return "vertex_ai"
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
        "litellm_gemini_stateless": "gemini/",
        "litellm_gemini_paid_stateless": "gemini/",
        "vertex_ai": "vertex_ai/",
    }
    prefix = prefixes.get(provider, "")
    if prefix and not value.startswith(prefix):
        return f"{prefix}{value}"
    return value


def _resolve_litellm_api_key(instructions: BotInstructions, default_api_key: str) -> str:
    env_name = str(instructions.llm_api_key_env or "").strip()
    if env_name:
        return os.environ.get(env_name, "").strip() or default_api_key.strip()
    return default_api_key.strip()


def _normalize_litellm_service_tier(value: object) -> str:
    text = str(value or "").strip()
    normalized = text.casefold()
    if normalized in {"", "none", "null", "0", "false", "off", "disabled", "aus", "nein", "no"}:
        return ""
    if normalized == "flex":
        return "flex"
    return text


def _is_usage_limit_error(exc: Exception, redacted_detail: str) -> bool:
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if str(status or "").strip() == "429":
        return True
    text = f"{type(exc).__name__} {redacted_detail} {exc}".casefold()
    return any(
        marker in text
        for marker in (
            "429",
            "too many requests",
            "rate limit",
            "ratelimit",
            "resource_exhausted",
            "insufficient_quota",
            "quota exceeded",
            "quota_exceeded",
            "usage limit",
        )
    )


def _validate_litellm_local_service_targets(
    models: tuple[str, ...],
    kwargs: Mapping[str, object],
    *,
    fallback_api_bases: Mapping[str, str] | None = None,
) -> None:
    fallback_bases = fallback_api_bases or {}
    for model in models:
        if not _litellm_model_uses_ollama(model):
            continue
        api_base = str(fallback_bases.get(model) or kwargs.get("api_base") or "").strip()
        if not api_base:
            continue
        reason = _unsafe_local_ollama_api_base_reason(api_base)
        if reason:
            raise LLMAPIError(f"Unsafe Ollama api_base: {reason}")


def _litellm_model_uses_ollama(model: object) -> bool:
    return str(model or "").strip().casefold().startswith(("ollama/", "ollama_chat/"))


def _unsafe_local_ollama_api_base_reason(api_base: str) -> str:
    text = str(api_base or "").strip()
    if not text:
        return ""
    if "://" not in text and not text.startswith("//"):
        text = f"http://{text}"
    try:
        parsed = urlsplit(text)
        port = parsed.port
    except ValueError:
        return "invalid URL"
    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        return "scheme must be http or https"
    if parsed.username or parsed.password:
        return "credentials are not allowed"
    if parsed.query or parsed.fragment:
        return "query and fragment are not allowed"
    host = (parsed.hostname or "127.0.0.1").strip().casefold()
    if host not in LOCAL_OLLAMA_HOSTS:
        return "host must be loopback"
    if port is not None and port <= 0:
        return "invalid port"
    return ""


def _redact_litellm_error(exc: Exception, kwargs: dict[str, object]) -> str:
    text = str(exc)
    api_key = str(kwargs.get("api_key") or "").strip()
    if api_key:
        text = text.replace(api_key, "<redacted>")
    text = URL_CREDENTIAL_RE.sub(lambda match: _redact_url_credentials(match.group(0)), text)
    text = SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=<redacted>", text)
    # Common provider-key shapes. Keep this conservative so normal diagnostics
    # remain readable while accidental secrets are removed.
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "sk-<redacted>", text)
    text = re.sub(r"\bxox[baprs]-[A-Za-z0-9_-]{8,}\b", "xox-<redacted>", text)
    text = re.sub(r"\bsyt_[A-Za-z0-9_=-]{8,}\b", "syt_<redacted>", text)
    text = re.sub(r"\bgh[pousr]_[A-Za-z0-9_]{8,}\b", "gh_<redacted>", text)
    text = re.sub(r"\bgithub_pat_[A-Za-z0-9_]{12,}\b", "github_pat_<redacted>", text)
    text = re.sub(r"\bglpat-[A-Za-z0-9_-]{8,}\b", "glpat-<redacted>", text)
    text = re.sub(r"\bhf_[A-Za-z0-9]{8,}\b", "hf_<redacted>", text)
    text = re.sub(r"\bgsk_[A-Za-z0-9]{8,}\b", "gsk_<redacted>", text)
    text = re.sub(r"\bAIza[0-9A-Za-z_-]{16,}\b", "AIza<redacted>", text)
    return text


def _redact_url_credentials(value: str) -> str:
    text = str(value or "")
    return re.sub(r"(?<=://)[^\s/@:=]+:[^\s/@]+@", "<redacted>@", text)


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


def _extract_input_tokens(usage: Mapping[str, Any]) -> int | None:
    for key in ("prompt_tokens", "input_tokens", "input_token_count", "total_input_tokens"):
        value = usage.get(key)
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed >= 0:
            return parsed
    return None


def _add_litellm_response_cost(usage: dict[str, Any], response: object) -> None:
    cost = _litellm_response_cost(response)
    if cost is not None:
        usage.setdefault("response_cost", cost)


def _litellm_response_cost(response: object) -> object | None:
    hidden = _response_value(response, "_hidden_params")
    value = _response_value(hidden, "response_cost") if hidden is not None else None
    if value is None:
        value = _response_value(response, "response_cost")
    return value


def _quota_owner_provider(*, provider: str, model: str) -> str:
    if route_uses_google_gemini(provider=provider, model=model):
        return "google_gemini_paid" if provider_is_paid_google_gemini(provider) else "google_gemini"
    return provider


def _safe_litellm_api_base(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    split = urlsplit(text)
    if not split.scheme or not split.netloc:
        return text[:160]
    host = split.hostname or ""
    port = f":{split.port}" if split.port is not None else ""
    path = split.path.rstrip("/")
    return f"{split.scheme}://{host}{port}{path}"[:160]


def _compact_usage_for_log(usage: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("input_tokens", "prompt_tokens", "output_tokens", "completion_tokens", "total_tokens")
    return {key: usage[key] for key in keys if key in usage}


def _resolve_litellm_gemini_free_tier_limits(
    *,
    provider: str,
    model: str,
    fallback_models: tuple[str, ...] = (),
    explicit_limits: GeminiFreeTierLimits | None,
) -> GeminiFreeTierLimits:
    if provider_is_paid_google_gemini(provider):
        return GeminiFreeTierLimits(enabled=False, requests_per_minute=None, input_tokens_per_minute=None, requests_per_day=None)
    if route_uses_google_gemini(provider=provider, model=model):
        return explicit_limits or resolve_gemini_free_tier_limits(provider=provider, model=model)
    fallback_model = next(
        (candidate for candidate in fallback_models if route_uses_google_gemini(provider=provider, model=candidate)),
        "",
    )
    if fallback_model:
        return explicit_limits or resolve_gemini_free_tier_limits(provider=provider, model=fallback_model)
    return GeminiFreeTierLimits(enabled=False, requests_per_minute=None, input_tokens_per_minute=None, requests_per_day=None)


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
