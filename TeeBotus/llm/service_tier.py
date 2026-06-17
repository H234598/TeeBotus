from __future__ import annotations

import os
from collections.abc import Mapping

from TeeBotus.llm.free_tier import route_uses_google_gemini

TRUE_VALUES = frozenset({"1", "true", "yes", "ja", "on", "enabled", "an", "flex"})
FALSE_VALUES = frozenset({"0", "false", "no", "nein", "off", "disabled", "aus", "none", "null"})


def resolve_gemini_service_tier(
    env: Mapping[str, str] | None = None,
    *,
    instance_name: str = "",
    provider: str,
    model: str,
    explicit_service_tier: str = "",
) -> str:
    explicit_present, explicit = _coerce_service_tier(explicit_service_tier)
    if explicit_present:
        return explicit
    if not route_uses_google_gemini(provider=provider, model=model):
        return ""
    source = os.environ if env is None else env
    token = _instance_token(instance_name)
    for key in _service_tier_keys(token):
        present, value = _coerce_service_tier(source.get(key, ""))
        if present:
            return value
    for key in _flex_flag_keys(token):
        value = str(source.get(key, "") or "").strip().casefold()
        if value in TRUE_VALUES:
            return "flex"
        if value in FALSE_VALUES:
            return ""
    return ""


def normalize_service_tier(value: object) -> str:
    return _coerce_service_tier(value)[1]


def _coerce_service_tier(value: object) -> tuple[bool, str]:
    text = str(value or "").strip()
    normalized = text.casefold()
    if not normalized:
        return False, ""
    if normalized in FALSE_VALUES:
        return True, ""
    if normalized == "flex":
        return True, "flex"
    return True, text


def _service_tier_keys(token: str) -> tuple[str, ...]:
    if token:
        return (
            f"TEEBOTUS_GEMINI_SERVICE_TIER_{token}",
            f"TEEBOTUS_GOOGLE_SERVICE_TIER_{token}",
            "TEEBOTUS_GEMINI_SERVICE_TIER",
            "TEEBOTUS_GOOGLE_SERVICE_TIER",
        )
    return ("TEEBOTUS_GEMINI_SERVICE_TIER", "TEEBOTUS_GOOGLE_SERVICE_TIER")


def _flex_flag_keys(token: str) -> tuple[str, ...]:
    if token:
        return (
            f"TEEBOTUS_GEMINI_FLEX_SERVICE_TIER_{token}",
            f"TEEBOTUS_GEMINI_FLEX_{token}",
            "TEEBOTUS_GEMINI_FLEX_SERVICE_TIER",
            "TEEBOTUS_GEMINI_FLEX",
        )
    return ("TEEBOTUS_GEMINI_FLEX_SERVICE_TIER", "TEEBOTUS_GEMINI_FLEX")


def _instance_token(instance_name: str) -> str:
    token = "".join(char if char.isalnum() else "_" for char in str(instance_name or "").strip().upper())
    return "_".join(part for part in token.split("_") if part)


__all__ = ["normalize_service_tier", "resolve_gemini_service_tier"]
