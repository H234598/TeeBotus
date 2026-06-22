from __future__ import annotations

import hashlib
import math
import os
import secrets
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from TeeBotus.llm.gemini_limits_refresh import cached_gemini_free_tier_limit_values


_QUOTA_OWNER_FINGERPRINT_KEY = secrets.token_bytes(32)
DEFAULT_GEMINI_FREE_TIER_RPM = 5
DEFAULT_GEMINI_FREE_TIER_TPM = 250_000
DEFAULT_GEMINI_FREE_TIER_RPD = 20
DEFAULT_GEMINI_FREE_TIER_RESERVE_TOKENS = 2_048
PAID_GEMINI_PROVIDERS = frozenset(
    {
        "litellm_gemini_paid_stateless",
        "litellm_gemini_paid_stateful",
        "litellm_gemini_paid_statefull",
    }
)
STATEFUL_GEMINI_PROVIDERS = frozenset(
    {
        "gemini_interactions",
        "litellm_gemini_stateful",
        "litellm_gemini_statefull",
        "litellm_gemini_paid_stateful",
        "litellm_gemini_paid_statefull",
    }
)


@dataclass(frozen=True)
class GeminiFreeTierLimits:
    requests_per_minute: int | None = DEFAULT_GEMINI_FREE_TIER_RPM
    input_tokens_per_minute: int | None = DEFAULT_GEMINI_FREE_TIER_TPM
    requests_per_day: int | None = DEFAULT_GEMINI_FREE_TIER_RPD
    reserve_input_tokens: int = DEFAULT_GEMINI_FREE_TIER_RESERVE_TOKENS
    enabled: bool = True

    @property
    def active(self) -> bool:
        return self.enabled and any(
            limit is not None
            for limit in (self.requests_per_minute, self.input_tokens_per_minute, self.requests_per_day)
        )

    def status_summary(self) -> str:
        if not self.active:
            return "off"
        return (
            "on("
            f"rpm={_format_limit(self.requests_per_minute)},"
            f"tpm={_format_limit(self.input_tokens_per_minute)},"
            f"rpd={_format_limit(self.requests_per_day)},"
            f"reserve={max(0, int(self.reserve_input_tokens))}"
            ")"
        )


@dataclass(frozen=True)
class GeminiBudgetReservation:
    allowed: bool
    input_tokens: int = 0
    reason: str = ""


class GeminiFreeTierGuard:
    """Process-local quota guard for Google's per-project Gemini free tier."""

    def __init__(
        self,
        limits: GeminiFreeTierLimits | None = None,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.limits = limits or GeminiFreeTierLimits()
        self._now = now or _utcnow

    def reserve(self, *, quota_owner: str, model: str, estimated_input_tokens: int) -> GeminiBudgetReservation:
        if not self.limits.active:
            return GeminiBudgetReservation(allowed=True, input_tokens=max(0, int(estimated_input_tokens)))
        state = _budget_state_for(quota_owner=quota_owner, model=model)
        requested_tokens = max(0, int(estimated_input_tokens))
        now = self._now()
        minute_bucket = int(now.timestamp() // 60)
        day_bucket = _pacific_day(now)
        with state.lock:
            if state.minute_bucket != minute_bucket:
                state.minute_bucket = minute_bucket
                state.minute_requests = 0
                state.minute_input_tokens = 0
            if state.day_bucket != day_bucket:
                state.day_bucket = day_bucket
                state.day_requests = 0

            rpd = self.limits.requests_per_day
            if rpd is not None and state.day_requests >= rpd:
                return GeminiBudgetReservation(False, requested_tokens, f"RPD free-tier budget exhausted ({state.day_requests}/{rpd})")

            rpm = self.limits.requests_per_minute
            if rpm is not None and state.minute_requests >= rpm:
                return GeminiBudgetReservation(
                    False,
                    requested_tokens,
                    f"RPM free-tier budget exhausted ({state.minute_requests}/{rpm})",
                )

            tpm = self.limits.input_tokens_per_minute
            reserve = max(0, int(self.limits.reserve_input_tokens))
            if tpm is not None and state.minute_input_tokens + requested_tokens + reserve > tpm:
                return GeminiBudgetReservation(
                    False,
                    requested_tokens,
                    "TPM free-tier budget would be exceeded "
                    f"({state.minute_input_tokens}+{requested_tokens}+reserve:{reserve}/{tpm})",
                )

            state.minute_requests += 1
            state.day_requests += 1
            state.minute_input_tokens += requested_tokens
        return GeminiBudgetReservation(True, requested_tokens)

    def adjust_reserved_tokens(self, *, quota_owner: str, model: str, reserved_input_tokens: int, actual_input_tokens: int) -> None:
        if not self.limits.active:
            return
        delta = int(actual_input_tokens) - int(reserved_input_tokens)
        if delta == 0:
            return
        state = _budget_state_for(quota_owner=quota_owner, model=model)
        now = self._now()
        minute_bucket = int(now.timestamp() // 60)
        day_bucket = _pacific_day(now)
        with state.lock:
            if state.minute_bucket != minute_bucket or state.day_bucket != day_bucket:
                return
            state.minute_input_tokens = max(0, state.minute_input_tokens + delta)


class _BudgetState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.minute_bucket = -1
        self.minute_requests = 0
        self.minute_input_tokens = 0
        self.day_bucket = ""
        self.day_requests = 0


_BUDGET_REGISTRY_LOCK = threading.Lock()
_BUDGET_REGISTRY: dict[tuple[str, str], _BudgetState] = {}


def resolve_gemini_free_tier_limits(
    env: Mapping[str, str] | None = None,
    *,
    instance_name: str = "",
    provider: str = "",
    model: str = "",
) -> GeminiFreeTierLimits:
    if not route_uses_google_gemini(provider=provider, model=model):
        return GeminiFreeTierLimits(enabled=False, requests_per_minute=None, input_tokens_per_minute=None, requests_per_day=None)
    if provider_is_paid_google_gemini(provider):
        return GeminiFreeTierLimits(enabled=False, requests_per_minute=None, input_tokens_per_minute=None, requests_per_day=None)
    source = os.environ if env is None else env
    token = _env_token(instance_name)
    cached = cached_gemini_free_tier_limit_values(source, model=str(model or ""))
    default_rpm = _cached_int(cached, "rpm", DEFAULT_GEMINI_FREE_TIER_RPM)
    default_tpm = _cached_int(cached, "tpm", DEFAULT_GEMINI_FREE_TIER_TPM)
    default_rpd = _cached_int(cached, "rpd", DEFAULT_GEMINI_FREE_TIER_RPD)
    default_reserve = _cached_int(cached, "reserve_tokens", DEFAULT_GEMINI_FREE_TIER_RESERVE_TOKENS)
    enabled = _parse_bool_env(_first_env(source, token=token, suffix="ENABLED"), default=True)
    return GeminiFreeTierLimits(
        enabled=enabled,
        requests_per_minute=_parse_optional_nonnegative_int(
            _first_env(source, token=token, suffix="RPM"),
            default=default_rpm,
        ),
        input_tokens_per_minute=_parse_optional_nonnegative_int(
            _first_env(source, token=token, suffix="TPM"),
            default=default_tpm,
        ),
        requests_per_day=_parse_optional_nonnegative_int(
            _first_env(source, token=token, suffix="RPD"),
            default=default_rpd,
        ),
        reserve_input_tokens=_parse_nonnegative_int(
            _first_env(source, token=token, suffix="RESERVE_TOKENS"),
            default=default_reserve,
        ),
    )


def estimate_litellm_input_tokens(messages: Sequence[Mapping[str, Any]]) -> int:
    chars = 0
    for message in messages:
        chars += len(str(message.get("role") or ""))
        chars += _content_length(message.get("content"))
    # A conservative character estimate is sufficient for a local guard. The
    # provider remains the authority and still returns 429 if its live quota is lower.
    return max(1, math.ceil(chars / 3) + 8 * len(messages))


def route_uses_google_gemini(*, provider: str, model: object) -> bool:
    normalized_provider = _normalize_gemini_provider(provider)
    normalized_model = str(model or "").strip().casefold()
    return normalized_provider in {
        "gemini",
        "gemini_interactions",
        "litellm_gemini_stateless",
        "litellm_gemini_stateful",
        "litellm_gemini_paid_stateless",
        "litellm_gemini_paid_stateful",
        "litellm_gemini_paid_statefull",
        "vertex_ai",
        "google_vertex",
        "google_vertex_ai",
    } or normalized_model.startswith(("gemini/", "vertex_ai/"))


def route_uses_gemini_api(*, provider: str, model: object) -> bool:
    normalized_provider = _normalize_gemini_provider(provider)
    normalized_model = str(model or "").strip().casefold()
    return normalized_provider in {
        "gemini",
        "gemini_interactions",
        "litellm_gemini_stateless",
        "litellm_gemini_stateful",
        "litellm_gemini_paid_stateless",
        "litellm_gemini_paid_stateful",
        "litellm_gemini_paid_statefull",
    } or normalized_model.startswith("gemini/")


def provider_is_paid_google_gemini(provider: object) -> bool:
    return _normalize_gemini_provider(provider) in PAID_GEMINI_PROVIDERS


def provider_is_stateful_google_gemini(provider: object) -> bool:
    return _normalize_gemini_provider(provider) in STATEFUL_GEMINI_PROVIDERS


def _normalize_gemini_provider(provider: object) -> str:
    try:
        from TeeBotus.llm.litellm_provider import normalize_llm_provider

        return normalize_llm_provider(str(provider or ""))
    except Exception:
        return str(provider or "").strip().casefold().replace("-", "_")


def quota_owner_id(*, api_key: str, provider: str, model: str, api_base: str = "") -> str:
    owner = str(api_key or "").strip() or str(api_base or "").strip() or f"{provider}:{model}"
    digest = hashlib.blake2b(
        owner.encode("utf-8", errors="replace"),
        digest_size=8,
        key=_QUOTA_OWNER_FINGERPRINT_KEY,
    ).hexdigest()
    return f"{provider}:{model}:{digest}"


def reset_gemini_free_tier_budget_state() -> None:
    with _BUDGET_REGISTRY_LOCK:
        _BUDGET_REGISTRY.clear()


def _budget_state_for(*, quota_owner: str, model: str) -> _BudgetState:
    key = (str(quota_owner or "").strip(), str(model or "").strip())
    with _BUDGET_REGISTRY_LOCK:
        state = _BUDGET_REGISTRY.get(key)
        if state is None:
            state = _BudgetState()
            _BUDGET_REGISTRY[key] = state
        return state


def _content_length(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value)
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return sum(_content_length(item) for item in value)
    if isinstance(value, Mapping):
        return sum(_content_length(item) for item in value.values())
    return len(str(value))


def _first_env(source: Mapping[str, str], *, token: str, suffix: str) -> str:
    names = []
    if token:
        names.extend(
            (
                f"TEEBOTUS_GEMINI_FREE_TIER_{token}_{suffix}",
                f"GEMINI_FREE_TIER_{token}_{suffix}",
            )
        )
    names.extend((f"TEEBOTUS_GEMINI_FREE_TIER_{suffix}", f"GEMINI_FREE_TIER_{suffix}"))
    for name in names:
        value = str(source.get(name, "") or "").strip()
        if value:
            return value
    return ""


def _parse_bool_env(value: str, *, default: bool) -> bool:
    text = str(value or "").strip().casefold()
    if not text:
        return default
    if text in {"1", "true", "yes", "ja", "on", "enabled", "an"}:
        return True
    if text in {"0", "false", "no", "nein", "off", "disabled", "aus"}:
        return False
    return default


def _parse_optional_nonnegative_int(value: str, *, default: int) -> int | None:
    text = str(value or "").strip().casefold()
    if not text:
        return default
    if text in {"none", "null", "unlimited", "off", "disabled"}:
        return None
    try:
        parsed = int(text)
    except ValueError:
        return default
    return parsed if parsed >= 0 else default


def _parse_nonnegative_int(value: str, *, default: int) -> int:
    try:
        parsed = int(str(value or "").strip())
    except ValueError:
        return default
    return parsed if parsed >= 0 else default


def _cached_int(values: Mapping[str, int | None], key: str, default: int) -> int:
    value = values.get(key)
    return value if isinstance(value, int) and value >= 0 else default


def _pacific_day(now: datetime) -> str:
    try:
        pacific = ZoneInfo("America/Los_Angeles")
    except ZoneInfoNotFoundError:
        pacific = timezone.utc
    return now.astimezone(pacific).date().isoformat()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _env_token(value: str) -> str:
    token = "".join(char if char.isalnum() else "_" for char in str(value or "").strip().upper())
    return "_".join(part for part in token.split("_") if part)


def _format_limit(value: int | None) -> str:
    return "none" if value is None else str(value)


__all__ = [
    "GeminiBudgetReservation",
    "GeminiFreeTierGuard",
    "GeminiFreeTierLimits",
    "estimate_litellm_input_tokens",
    "quota_owner_id",
    "provider_is_paid_google_gemini",
    "provider_is_stateful_google_gemini",
    "reset_gemini_free_tier_budget_state",
    "resolve_gemini_free_tier_limits",
    "route_uses_gemini_api",
    "route_uses_google_gemini",
]
