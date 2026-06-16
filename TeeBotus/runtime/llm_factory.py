from __future__ import annotations

import os
from typing import Any, Callable, Mapping

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.profiles import LLMProfile, LLMRoute, load_llm_profiles, select_llm_route
from TeeBotus.llm_client import build_text_llm_client, normalize_llm_provider
from TeeBotus.openai_client import OpenAIClient


def build_runtime_text_llm_client(
    *,
    instructions: BotInstructions,
    openai_client: object | None,
    default_api_key: str = "",
    enabled: bool | str | None = None,
    profile: str = "",
    purpose: str = "",
    allow_remote_fallback: bool | str = False,
    provider: str = "",
    model: str = "",
    fallback_models: str | tuple[str, ...] = (),
    api_key: str = "",
    api_base: str = "",
    timeout: int | str | None = None,
    temperature: float | str | None = None,
    max_tokens: int | str | None = None,
    env: Mapping[str, str] | None = None,
    openai_client_factory: Callable[[str], object] = OpenAIClient,
) -> object | None:
    enabled_override = _parse_optional_bool(enabled)
    if enabled_override is False:
        return None
    if enabled_override is None and instructions.llm_enabled is False:
        return None
    profile_name = str(profile or instructions.llm_profile or "").strip()
    if profile_name:
        return _build_profile_client(
            profile_name,
            instructions=instructions,
            openai_client=openai_client,
            default_api_key=default_api_key,
            override_api_key=api_key,
            fallback_models=fallback_models,
            timeout=timeout,
            temperature=temperature,
            max_tokens=max_tokens,
            env=env,
            openai_client_factory=openai_client_factory,
        )
    route_purpose = str(purpose or "").strip()
    has_direct_provider = bool(str(provider or "").strip())
    has_direct_model = bool(str(model or "").strip())
    if route_purpose and not (has_direct_provider or has_direct_model):
        route = select_llm_route(route_purpose, allow_remote_fallback=_parse_bool(allow_remote_fallback))
        return _build_route_client(
            route,
            instructions=instructions,
            openai_client=openai_client,
            default_api_key=default_api_key,
            override_api_key=api_key,
            fallback_models=fallback_models,
            timeout=timeout,
            temperature=temperature,
            max_tokens=max_tokens,
            env=env,
            openai_client_factory=openai_client_factory,
        )
    return build_text_llm_client(
        instructions=instructions,
        openai_client=openai_client,
        default_api_key=default_api_key,
        provider=provider,
        model=model,
        fallback_models=fallback_models,
        api_key=api_key,
        api_base=api_base,
        timeout=timeout,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _build_route_client(
    route: LLMRoute,
    *,
    instructions: BotInstructions,
    openai_client: object | None,
    default_api_key: str,
    override_api_key: str,
    fallback_models: str | tuple[str, ...],
    timeout: int | str | None,
    temperature: float | str | None,
    max_tokens: int | str | None,
    env: Mapping[str, str] | None,
    openai_client_factory: Callable[[str], object],
) -> object | None:
    source = os.environ if env is None else env
    profile_api_key = source.get(route.api_key_env, "").strip() if route.api_key_env else ""
    resolved_api_key = str(override_api_key or "").strip() or profile_api_key
    resolved_provider = normalize_llm_provider(route.provider)
    resolved_openai_client = openai_client
    if resolved_provider == "openai" and resolved_openai_client is None:
        key = resolved_api_key or default_api_key
        resolved_openai_client = openai_client_factory(key) if key else None
    resolved_fallback_models = fallback_models or route.fallback_models
    return build_text_llm_client(
        instructions=instructions,
        openai_client=resolved_openai_client,
        default_api_key=resolved_api_key or default_api_key,
        provider=route.provider,
        model=route.model,
        fallback_models=resolved_fallback_models,
        api_key=resolved_api_key,
        api_base=route.base_url,
        timeout=timeout,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _build_profile_client(
    profile_name: str,
    *,
    instructions: BotInstructions,
    openai_client: object | None,
    default_api_key: str,
    override_api_key: str,
    fallback_models: str | tuple[str, ...],
    timeout: int | str | None,
    temperature: float | str | None,
    max_tokens: int | str | None,
    env: Mapping[str, str] | None,
    openai_client_factory: Callable[[str], object],
) -> object | None:
    profiles = load_llm_profiles()
    profile = _require_profile(profiles, profile_name)
    source = os.environ if env is None else env
    profile_api_key = source.get(profile.api_key_env, "").strip() if profile.api_key_env else ""
    resolved_api_key = str(override_api_key or "").strip() or profile_api_key
    resolved_provider = normalize_llm_provider(profile.provider)
    resolved_openai_client = openai_client
    if resolved_provider == "openai" and resolved_openai_client is None:
        key = resolved_api_key or default_api_key
        resolved_openai_client = openai_client_factory(key) if key else None
    return build_text_llm_client(
        instructions=instructions,
        openai_client=resolved_openai_client,
        default_api_key=resolved_api_key or default_api_key,
        provider=profile.provider,
        model=profile.model,
        fallback_models=fallback_models,
        api_key=resolved_api_key,
        api_base=profile.base_url,
        timeout=timeout,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _require_profile(profiles: Mapping[str, LLMProfile], profile_name: str) -> LLMProfile:
    if profile_name not in profiles:
        raise KeyError(f"Unknown LLM profile: {profile_name}")
    return profiles[profile_name]


def _parse_bool(value: bool | str) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "yes", "ja", "on"}


def _parse_optional_bool(value: bool | str | None) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().casefold()
    if not text:
        return None
    if text in {"1", "true", "yes", "ja", "on", "enabled", "an"}:
        return True
    if text in {"0", "false", "no", "nein", "off", "disabled", "aus"}:
        return False
    return None


__all__ = ["build_runtime_text_llm_client"]
