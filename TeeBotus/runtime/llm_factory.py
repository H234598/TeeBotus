from __future__ import annotations

import logging
import os
from typing import Any, Callable, Mapping

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.free_tier import resolve_gemini_free_tier_limits, route_uses_gemini_api, route_uses_google_gemini
from TeeBotus.llm.keyring import resolve_gemini_api_key_ring
from TeeBotus.llm.profiles import LLMProfile, LLMRoute, load_llm_profiles, select_llm_route
from TeeBotus.llm.service_tier import resolve_gemini_service_tier
from TeeBotus.llm_client import build_text_llm_client, normalize_llm_provider, parse_fallback_models
from TeeBotus.openai_client import OpenAIClient

LOGGER = logging.getLogger("TeeBotus.runtime.llm_factory")
LOCAL_OLLAMA_OFFLOAD_ENV = "TEEBOTUS_LLM_OFFLOAD_LOCAL_OLLAMA"
LOCAL_OLLAMA_OFFLOAD_PROFILE_ENV = "TEEBOTUS_LLM_OFFLOAD_LOCAL_OLLAMA_PROFILE"
LOCAL_OLLAMA_OFFLOAD_DEFAULT_PROFILE = "hf_pool_default"


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
    service_tier: str = "",
    gemini_key_scope: str = "",
    env: Mapping[str, str] | None = None,
    instance_name: str = "",
    allow_local_ollama_offload: bool = True,
    openai_client_factory: Callable[[str], object] = OpenAIClient,
) -> object | None:
    source = os.environ if env is None else env
    enabled_override = _parse_optional_bool(enabled)
    if enabled_override is False:
        return None
    if enabled_override is None and instructions.llm_enabled is False:
        return None
    requested_profile_name = str(profile or "").strip()
    runtime_profile_name = (
        _offloaded_profile_name(requested_profile_name, env=source, instance_name=instance_name)
        if allow_local_ollama_offload
        else requested_profile_name
    )
    route_purpose = str(purpose or "").strip()
    has_direct_provider = bool(str(provider or "").strip())
    has_direct_model = bool(str(model or "").strip())
    has_runtime_route_override = bool(runtime_profile_name or route_purpose or has_direct_provider or has_direct_model)
    profile_name = runtime_profile_name or (
        ""
        if has_runtime_route_override
        else (
            _offloaded_profile_name(str(instructions.llm_profile or "").strip(), env=source, instance_name=instance_name)
            if allow_local_ollama_offload
            else str(instructions.llm_profile or "").strip()
        )
    )
    remote_fallback_allowed = _parse_bool(allow_remote_fallback)
    if profile_name:
        return _build_profile_client(
            profile_name,
            instructions=instructions,
            openai_client=openai_client,
            default_api_key=default_api_key,
            override_api_key=api_key,
            fallback_models=fallback_models,
            allow_remote_fallback=remote_fallback_allowed,
            api_base=api_base,
            purpose=route_purpose,
            timeout=timeout,
            temperature=temperature,
            max_tokens=max_tokens,
            service_tier=service_tier,
            gemini_key_scope=gemini_key_scope,
            env=env,
            instance_name=instance_name,
            openai_client_factory=openai_client_factory,
        )
    if route_purpose and not (has_direct_provider or has_direct_model):
        route = select_llm_route(route_purpose, allow_remote_fallback=remote_fallback_allowed)
        if allow_local_ollama_offload:
            route = _offloaded_route(route, env=source, instance_name=instance_name)
        return _build_route_client(
            route,
            instructions=instructions,
            openai_client=openai_client,
            default_api_key=default_api_key,
            override_api_key=api_key,
            fallback_models=fallback_models,
            allow_remote_fallback=remote_fallback_allowed,
            api_base=api_base,
            timeout=timeout,
            temperature=temperature,
            max_tokens=max_tokens,
            service_tier=service_tier,
            gemini_key_scope=gemini_key_scope,
            env=source,
            instance_name=instance_name,
            openai_client_factory=openai_client_factory,
        )
    resolved_provider = normalize_llm_provider(provider or instructions.llm_provider)
    resolved_model = str(model or instructions.llm_model or "").strip()
    if allow_local_ollama_offload and _local_ollama_offload_enabled(source, instance_name) and _uses_local_ollama(resolved_provider, resolved_model):
        return _build_profile_client(
            _local_ollama_offload_profile(source, instance_name),
            instructions=instructions,
            openai_client=openai_client,
            default_api_key=default_api_key,
            override_api_key=api_key,
            fallback_models=fallback_models,
            allow_remote_fallback=True,
            api_base=api_base,
            purpose=route_purpose,
            timeout=timeout,
            temperature=temperature,
            max_tokens=max_tokens,
            service_tier=service_tier,
            gemini_key_scope=gemini_key_scope,
            env=source,
            instance_name=instance_name,
            openai_client_factory=openai_client_factory,
        )
    resolved_api_key = str(api_key or "").strip() or _compatible_default_api_key(resolved_provider, resolved_model, default_api_key)
    resolved_openai_client = openai_client
    return build_text_llm_client(
        instructions=instructions,
        openai_client=resolved_openai_client,
        default_api_key=resolved_api_key,
        provider=resolved_provider,
        model=resolved_model,
        fallback_models=filter_runtime_fallback_models(
            provider=resolved_provider,
            fallback_models=fallback_models or instructions.llm_fallback_models,
            allow_remote_fallback=remote_fallback_allowed,
        ),
        api_key=resolved_api_key,
        api_key_ring=_gemini_api_key_ring_for_route(
            env,
            instance_name=instance_name,
            provider=resolved_provider,
            model=resolved_model,
            fallback_models=filter_runtime_fallback_models(
                provider=resolved_provider,
                fallback_models=fallback_models or instructions.llm_fallback_models,
                allow_remote_fallback=remote_fallback_allowed,
            ),
            explicit_api_key=api_key,
            scope=gemini_key_scope,
        ),
        gemini_free_tier_limits=_gemini_free_tier_limits_for_route(
            env,
            instance_name=instance_name,
            provider=resolved_provider,
            model=resolved_model,
            fallback_models=filter_runtime_fallback_models(
                provider=resolved_provider,
                fallback_models=fallback_models or instructions.llm_fallback_models,
                allow_remote_fallback=remote_fallback_allowed,
            ),
        ),
        api_base=api_base,
        purpose=route_purpose or "normal_chat",
        timeout=timeout,
        temperature=temperature,
        max_tokens=max_tokens,
        service_tier=_gemini_service_tier_for_route(
            env,
            instance_name=instance_name,
            provider=resolved_provider,
            model=resolved_model,
            fallback_models=filter_runtime_fallback_models(
                provider=resolved_provider,
                fallback_models=fallback_models or instructions.llm_fallback_models,
                allow_remote_fallback=remote_fallback_allowed,
            ),
            explicit_service_tier=service_tier or instructions.llm_service_tier,
        ),
        use_instruction_fallback_models=False,
        env=env,
    )


def build_runtime_structured_decision_runner(
    *,
    instructions: BotInstructions | None = None,
    enabled: bool | str | None = None,
    runtime_llm_configured: bool = False,
    purpose: str = "structured_decision",
    allow_remote_fallback: bool | str = False,
    env: Mapping[str, str] | None = None,
) -> Callable[[str, type[Any]], Any] | None:
    enabled_override = _parse_optional_bool(enabled)
    if enabled_override is False:
        return None
    if enabled_override is None:
        structured_enabled = getattr(instructions, "structured_decision_enabled", None) if instructions is not None else None
        if structured_enabled is False:
            return None
        if runtime_llm_configured:
            pass
        elif structured_enabled is None and instructions is not None and not instructions.text_llm_enabled():
            return None
    try:
        from TeeBotus.decisions.pydantic_agent import build_router_pydantic_ai_model_runner
    except Exception as exc:  # noqa: BLE001 - optional Plan3 decision layer.
        LOGGER.info("Structured decision runner unavailable: %s: %s", type(exc).__name__, exc)
        return None
    try:
        runner = build_router_pydantic_ai_model_runner(
            purpose,
            allow_remote_fallback=_parse_bool(allow_remote_fallback),
            env=env,
        )
    except Exception as exc:  # noqa: BLE001 - missing providers/config must not break bot startup.
        LOGGER.info("Structured decision runner disabled: %s: %s", type(exc).__name__, exc)
        return None

    def guarded_runner(prompt: str, schema: type[Any]) -> Any:
        try:
            return runner(prompt, schema)
        except Exception as exc:  # noqa: BLE001 - structured subtasks are best-effort.
            schema_name = str(getattr(schema, "__name__", schema))
            LOGGER.warning(
                "Structured decision runner failed; using deterministic fallback: schema=%s error=%s retries=%s %s",
                schema_name,
                type(exc).__name__,
                getattr(runner, "pydantic_ai_output_retries", "n/a"),
                exc,
            )
            return None

    for name in (
        "llm_route",
        "llm_purpose",
        "llm_provider",
        "model_name",
        "llm_fallback_used",
        "llm_fallback_profile",
        "llm_fallback_model",
        "llm_primary_error",
        "pydantic_ai_model_name",
        "pydantic_ai_provider",
        "pydantic_ai_base_url",
        "hf_pool_name",
        "hf_pool_target",
        "hf_pool_request_model",
        "hf_pool_base_url",
    ):
        if hasattr(runner, name):
            setattr(guarded_runner, name, getattr(runner, name))
    return guarded_runner


def _build_route_client(
    route: LLMRoute,
    *,
    instructions: BotInstructions,
    openai_client: object | None,
    default_api_key: str,
    override_api_key: str,
    fallback_models: str | tuple[str, ...],
    allow_remote_fallback: bool,
    api_base: str,
    timeout: int | str | None,
    temperature: float | str | None,
    max_tokens: int | str | None,
    service_tier: str,
    gemini_key_scope: str,
    env: Mapping[str, str] | None,
    instance_name: str,
    openai_client_factory: Callable[[str], object],
) -> object | None:
    source = os.environ if env is None else env
    profile_api_key = source.get(route.api_key_env, "").strip() if route.api_key_env else ""
    fallback_api_key = source.get(route.fallback_api_key_env, "").strip() if route.fallback_api_key_env else ""
    resolved_api_key = str(override_api_key or "").strip() or profile_api_key
    resolved_api_base = str(api_base or "").strip() or route.base_url
    resolved_provider = normalize_llm_provider(route.provider)
    resolved_openai_client = openai_client
    resolved_fallback_models = filter_runtime_fallback_models(
        provider=route.provider,
        fallback_models=fallback_models or route.fallback_models,
        allow_remote_fallback=allow_remote_fallback,
    )
    fallback_api_base = route.fallback_base_url
    if resolved_provider == "hf_pool" and str(api_base or "").strip() and route.fallback_model:
        fallback_api_base = str(api_base).strip()
    return build_text_llm_client(
        instructions=instructions,
        openai_client=resolved_openai_client,
        default_api_key=resolved_api_key or _compatible_default_api_key(route.provider, route.model, default_api_key),
        provider=route.provider,
        model=route.model,
        fallback_models=resolved_fallback_models,
        fallback_api_keys={route.fallback_model: fallback_api_key} if route.fallback_model and fallback_api_key else None,
        fallback_api_bases={route.fallback_model: fallback_api_base} if route.fallback_model and fallback_api_base else None,
        api_key=resolved_api_key,
        api_key_ring=_gemini_api_key_ring_for_route(
            source,
            instance_name=instance_name,
            provider=route.provider,
            model=route.model,
            fallback_models=resolved_fallback_models,
            explicit_api_key=override_api_key,
            scope=gemini_key_scope,
        ),
        gemini_free_tier_limits=_gemini_free_tier_limits_for_route(
            source,
            instance_name=instance_name,
            provider=route.provider,
            model=route.model,
            fallback_models=resolved_fallback_models,
        ),
        api_base=resolved_api_base,
        purpose=route.purpose,
        timeout=timeout,
        temperature=temperature,
        max_tokens=max_tokens,
        service_tier=_gemini_service_tier_for_route(
            source,
            instance_name=instance_name,
            provider=route.provider,
            model=route.model,
            fallback_models=resolved_fallback_models,
            explicit_service_tier=service_tier
            or route.service_tier
            or route.fallback_service_tier
            or instructions.llm_service_tier,
        ),
        use_instruction_fallback_models=False,
        env=source,
    )


def _build_profile_client(
    profile_name: str,
    *,
    instructions: BotInstructions,
    openai_client: object | None,
    default_api_key: str,
    override_api_key: str,
    fallback_models: str | tuple[str, ...],
    allow_remote_fallback: bool,
    api_base: str,
    purpose: str,
    timeout: int | str | None,
    temperature: float | str | None,
    max_tokens: int | str | None,
    service_tier: str,
    gemini_key_scope: str,
    env: Mapping[str, str] | None,
    instance_name: str,
    openai_client_factory: Callable[[str], object],
) -> object | None:
    profiles = load_llm_profiles()
    profile = _require_profile(profiles, profile_name)
    source = os.environ if env is None else env
    profile_api_key = source.get(profile.api_key_env, "").strip() if profile.api_key_env else ""
    resolved_api_key = str(override_api_key or "").strip() or profile_api_key
    resolved_api_base = str(api_base or "").strip() or profile.base_url
    resolved_openai_client = openai_client
    return build_text_llm_client(
        instructions=instructions,
        openai_client=resolved_openai_client,
        default_api_key=resolved_api_key or _compatible_default_api_key(profile.provider, profile.model, default_api_key),
        provider=profile.provider,
        model=profile.model,
        fallback_models=filter_runtime_fallback_models(
            provider=profile.provider,
            fallback_models=fallback_models,
            allow_remote_fallback=allow_remote_fallback,
        ),
        api_key=resolved_api_key,
        api_key_ring=_gemini_api_key_ring_for_route(
            source,
            instance_name=instance_name,
            provider=profile.provider,
            model=profile.model,
            fallback_models=filter_runtime_fallback_models(
                provider=profile.provider,
                fallback_models=fallback_models,
                allow_remote_fallback=allow_remote_fallback,
            ),
            explicit_api_key=override_api_key,
            scope=gemini_key_scope,
        ),
        gemini_free_tier_limits=_gemini_free_tier_limits_for_route(
            source,
            instance_name=instance_name,
            provider=profile.provider,
            model=profile.model,
            fallback_models=filter_runtime_fallback_models(
                provider=profile.provider,
                fallback_models=fallback_models,
                allow_remote_fallback=allow_remote_fallback,
            ),
        ),
        api_base=resolved_api_base,
        purpose=str(purpose or "").strip() or "normal_chat",
        timeout=timeout,
        temperature=temperature,
        max_tokens=max_tokens,
        service_tier=_gemini_service_tier_for_route(
            source,
            instance_name=instance_name,
            provider=profile.provider,
            model=profile.model,
            fallback_models=filter_runtime_fallback_models(
                provider=profile.provider,
                fallback_models=fallback_models,
                allow_remote_fallback=allow_remote_fallback,
            ),
            explicit_service_tier=service_tier or profile.service_tier or instructions.llm_service_tier,
        ),
        use_instruction_fallback_models=False,
        env=source,
    )


def _require_profile(profiles: Mapping[str, LLMProfile], profile_name: str) -> LLMProfile:
    if profile_name not in profiles:
        raise KeyError(f"Unknown LLM profile: {profile_name}")
    return profiles[profile_name]


def _offloaded_profile_name(profile_name: str, *, env: Mapping[str, str], instance_name: str) -> str:
    name = str(profile_name or "").strip()
    if not name:
        return name
    profiles = load_llm_profiles()
    profile = profiles.get(name)
    if profile is None or not _local_ollama_offload_enabled(env, instance_name):
        return name
    if not _uses_local_ollama(profile.provider, profile.model):
        return name
    offload_profile = _local_ollama_offload_profile(env, instance_name)
    LOGGER.info(
        "Offloading local Ollama LLM profile instance=%s from_profile=%s to_profile=%s.",
        instance_name or "unknown",
        name,
        offload_profile,
    )
    return offload_profile


def _offloaded_route(route: LLMRoute, *, env: Mapping[str, str], instance_name: str) -> LLMRoute:
    if not _local_ollama_offload_enabled(env, instance_name) or not _uses_local_ollama(route.provider, route.model):
        return route
    profile_name = _local_ollama_offload_profile(env, instance_name)
    profile = _require_profile(load_llm_profiles(), profile_name)
    LOGGER.info(
        "Offloading local Ollama LLM route instance=%s purpose=%s from_profile=%s to_profile=%s.",
        instance_name or "unknown",
        route.purpose,
        route.profile_name,
        profile_name,
    )
    return LLMRoute(
        purpose=route.purpose,
        profile_name=profile.name,
        provider=profile.provider,
        model=profile.model,
        base_url=profile.base_url,
        api_key_env=profile.api_key_env,
        service_tier=profile.service_tier,
        fallback_profile_name=route.fallback_profile_name,
        fallback_model=route.fallback_model,
        fallback_api_key_env=route.fallback_api_key_env,
        fallback_base_url=route.fallback_base_url,
        fallback_service_tier=route.fallback_service_tier,
    )


def _local_ollama_offload_enabled(env: Mapping[str, str], instance_name: str) -> bool:
    return _parse_bool(_first_instance_env(env, LOCAL_OLLAMA_OFFLOAD_ENV, instance_name))


def _local_ollama_offload_profile(env: Mapping[str, str], instance_name: str) -> str:
    return _first_instance_env(env, LOCAL_OLLAMA_OFFLOAD_PROFILE_ENV, instance_name).strip() or LOCAL_OLLAMA_OFFLOAD_DEFAULT_PROFILE


def _uses_local_ollama(provider: str, model: str) -> bool:
    normalized_provider = normalize_llm_provider(provider)
    normalized_model = str(model or "").strip().casefold()
    return normalized_provider == "ollama" or normalized_model.startswith(("ollama/", "ollama_chat/"))


def _compatible_default_api_key(provider: str, model: str, default_api_key: str) -> str:
    """Keep an OpenAI runtime key away from non-OpenAI provider routes."""
    value = str(default_api_key or "").strip()
    if not value:
        return ""
    normalized_provider = normalize_llm_provider(provider)
    normalized_model = str(model or "").strip().casefold()
    if normalized_provider == "openai" or normalized_model.startswith("openai/"):
        return value
    return ""


def _first_instance_env(env: Mapping[str, str], base_key: str, instance_name: str) -> str:
    token = _instance_env_token(instance_name)
    if token:
        value = str(env.get(f"{base_key}_{token}", "") or "").strip()
        if value:
            return value
    return str(env.get(base_key, "") or "").strip()


def _instance_env_token(instance_name: str) -> str:
    token = "".join(char if char.isalnum() else "_" for char in str(instance_name or "").strip().upper())
    return "_".join(part for part in token.split("_") if part)


def _gemini_api_key_ring_for_route(
    env: Mapping[str, str] | None,
    *,
    instance_name: str,
    provider: str,
    model: str,
    fallback_models: str | tuple[str, ...] = (),
    explicit_api_key: str = "",
    scope: str = "",
) -> tuple[str, ...]:
    primary_uses_gemini = _route_uses_gemini_api(provider=provider, model=model)
    fallback_uses_gemini = any(
        _route_uses_gemini_api(provider=provider, model=fallback_model)
        for fallback_model in parse_fallback_models(fallback_models)
    )
    if str(explicit_api_key or "").strip() and primary_uses_gemini:
        return ()
    if not primary_uses_gemini and not fallback_uses_gemini:
        return ()
    return resolve_gemini_api_key_ring(env, instance_name=instance_name, scope=scope)


def _gemini_free_tier_limits_for_route(
    env: Mapping[str, str] | None,
    *,
    instance_name: str,
    provider: str,
    model: str,
    fallback_models: str | tuple[str, ...] = (),
):
    if route_uses_google_gemini(provider=provider, model=model):
        limit_model = model
    else:
        limit_model = next(
            (
                fallback_model
                for fallback_model in parse_fallback_models(fallback_models)
                if route_uses_google_gemini(provider=provider, model=fallback_model)
            ),
            "",
        )
    if not limit_model:
        return None
    return resolve_gemini_free_tier_limits(env, instance_name=instance_name, provider=provider, model=limit_model)


def _gemini_service_tier_for_route(
    env: Mapping[str, str] | None,
    *,
    instance_name: str,
    provider: str,
    model: str,
    fallback_models: str | tuple[str, ...] = (),
    explicit_service_tier: str = "",
) -> str:
    if route_uses_google_gemini(provider=provider, model=model):
        service_tier_model = model
    else:
        service_tier_model = next(
            (
                fallback_model
                for fallback_model in parse_fallback_models(fallback_models)
                if route_uses_google_gemini(provider=provider, model=fallback_model)
            ),
            model,
        )
    return resolve_gemini_service_tier(
        env,
        instance_name=instance_name,
        provider=provider,
        model=service_tier_model,
        explicit_service_tier=explicit_service_tier,
    )


def _route_uses_gemini_api(*, provider: str, model: str) -> bool:
    return route_uses_gemini_api(provider=provider, model=model)


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


def filter_runtime_fallback_models(
    *,
    provider: str,
    fallback_models: str | tuple[str, ...],
    allow_remote_fallback: bool,
) -> tuple[str, ...]:
    models = parse_fallback_models(fallback_models)
    if allow_remote_fallback:
        return models
    normalized_provider = normalize_llm_provider(provider)
    return tuple(model for model in models if not _is_remote_fallback_model(normalized_provider, model))


_filter_runtime_fallback_models = filter_runtime_fallback_models


def _is_remote_fallback_model(provider: str, model: str) -> bool:
    value = str(model or "").strip().casefold()
    if not value:
        return False
    if value.startswith(("ollama/", "ollama_chat/")):
        return False
    if route_uses_google_gemini(provider=provider, model=model):
        return True
    if value.startswith(("openai/", "huggingface/", "groq/", "gemini/", "vertex_ai/", "hf_pool/")):
        return True
    if provider == "litellm":
        return True
    if provider == "ollama":
        return False
    return provider in {"openai", "huggingface", "groq", "gemini", "vertex_ai", "hf_pool"}


__all__ = ["build_runtime_text_llm_client", "build_runtime_structured_decision_runner", "filter_runtime_fallback_models"]
