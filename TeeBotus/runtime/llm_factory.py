from __future__ import annotations

import logging
import os
from dataclasses import replace
from typing import Any, Callable, Mapping

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.capabilities import OPENAI_CAPABILITIES
from TeeBotus.llm.profiles import LLMProfile, LLMRoute, load_llm_profiles, select_llm_route
from TeeBotus.llm_client import build_text_llm_client, normalize_llm_provider, parse_fallback_models
from TeeBotus.openai_client import OpenAIClient

LOGGER = logging.getLogger("TeeBotus.runtime.llm_factory")


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
    runtime_profile_name = str(profile or "").strip()
    route_purpose = str(purpose or "").strip()
    has_direct_provider = bool(str(provider or "").strip())
    has_direct_model = bool(str(model or "").strip())
    has_runtime_route_override = bool(runtime_profile_name or route_purpose or has_direct_provider or has_direct_model)
    profile_name = runtime_profile_name or ("" if has_runtime_route_override else str(instructions.llm_profile or "").strip())
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
            timeout=timeout,
            temperature=temperature,
            max_tokens=max_tokens,
            env=env,
            openai_client_factory=openai_client_factory,
        )
    if route_purpose and not (has_direct_provider or has_direct_model):
        route = select_llm_route(route_purpose, allow_remote_fallback=remote_fallback_allowed)
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
            env=env,
            openai_client_factory=openai_client_factory,
        )
    resolved_provider = normalize_llm_provider(provider or instructions.llm_provider)
    resolved_model = str(model or instructions.llm_model or "").strip()
    resolved_api_key = str(api_key or "").strip() or default_api_key
    resolved_openai_client = openai_client
    if resolved_provider == "openai" and resolved_openai_client is None and resolved_api_key:
        resolved_openai_client = openai_client_factory(resolved_api_key)
    if resolved_provider == "openai" and resolved_openai_client is not None and resolved_model:
        return _OpenAITextModelOverrideClient(resolved_openai_client, resolved_model)
    return build_text_llm_client(
        instructions=instructions,
        openai_client=resolved_openai_client,
        default_api_key=default_api_key,
        provider=resolved_provider,
        model=resolved_model,
        fallback_models=filter_runtime_fallback_models(
            provider=resolved_provider,
            fallback_models=fallback_models or instructions.llm_fallback_models,
            allow_remote_fallback=remote_fallback_allowed,
        ),
        api_key=resolved_api_key,
        api_base=api_base,
        purpose=route_purpose or "normal_chat",
        timeout=timeout,
        temperature=temperature,
        max_tokens=max_tokens,
        use_instruction_fallback_models=False,
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
            LOGGER.warning("Structured decision runner failed; using deterministic fallback: %s: %s", type(exc).__name__, exc)
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
    env: Mapping[str, str] | None,
    openai_client_factory: Callable[[str], object],
) -> object | None:
    source = os.environ if env is None else env
    profile_api_key = source.get(route.api_key_env, "").strip() if route.api_key_env else ""
    fallback_api_key = source.get(route.fallback_api_key_env, "").strip() if route.fallback_api_key_env else ""
    resolved_api_key = str(override_api_key or "").strip() or profile_api_key
    resolved_api_base = str(api_base or "").strip() or route.base_url
    resolved_provider = normalize_llm_provider(route.provider)
    resolved_openai_client = openai_client
    if resolved_provider == "openai" and resolved_openai_client is None:
        key = resolved_api_key or default_api_key
        resolved_openai_client = openai_client_factory(key) if key else None
    if resolved_provider == "openai" and resolved_openai_client is not None:
        return _OpenAITextModelOverrideClient(resolved_openai_client, route.model)
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
        default_api_key=resolved_api_key or default_api_key,
        provider=route.provider,
        model=route.model,
        fallback_models=resolved_fallback_models,
        fallback_api_keys={route.fallback_model: fallback_api_key} if route.fallback_model and fallback_api_key else None,
        fallback_api_bases={route.fallback_model: fallback_api_base} if route.fallback_model and fallback_api_base else None,
        api_key=resolved_api_key,
        api_base=resolved_api_base,
        purpose=route.purpose,
        timeout=timeout,
        temperature=temperature,
        max_tokens=max_tokens,
        use_instruction_fallback_models=False,
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
    resolved_api_base = str(api_base or "").strip() or profile.base_url
    resolved_provider = normalize_llm_provider(profile.provider)
    resolved_openai_client = openai_client
    if resolved_provider == "openai" and resolved_openai_client is None:
        key = resolved_api_key or default_api_key
        resolved_openai_client = openai_client_factory(key) if key else None
    if resolved_provider == "openai" and resolved_openai_client is not None:
        return _OpenAITextModelOverrideClient(resolved_openai_client, profile.model)
    return build_text_llm_client(
        instructions=instructions,
        openai_client=resolved_openai_client,
        default_api_key=resolved_api_key or default_api_key,
        provider=profile.provider,
        model=profile.model,
        fallback_models=filter_runtime_fallback_models(
            provider=profile.provider,
            fallback_models=fallback_models,
            allow_remote_fallback=allow_remote_fallback,
        ),
        api_key=resolved_api_key,
        api_base=resolved_api_base,
        purpose="normal_chat",
        timeout=timeout,
        temperature=temperature,
        max_tokens=max_tokens,
        use_instruction_fallback_models=False,
    )


def _require_profile(profiles: Mapping[str, LLMProfile], profile_name: str) -> LLMProfile:
    if profile_name not in profiles:
        raise KeyError(f"Unknown LLM profile: {profile_name}")
    return profiles[profile_name]


class _OpenAITextModelOverrideClient:
    capabilities = OPENAI_CAPABILITIES

    def __init__(self, client: object, model: str) -> None:
        self.client = client
        self.model = str(model or "").strip()

    def create_reply(self, user_text: str, instructions: BotInstructions, previous_response_id: str | None = None) -> Any:
        create_reply = getattr(self.client, "create_reply")
        effective_instructions = replace(instructions, openai_model=self.model) if self.model else instructions
        return create_reply(user_text, effective_instructions, previous_response_id)


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
    if value.startswith(("openai/", "huggingface/", "groq/", "gemini/", "vertex_ai/", "hf_pool/")):
        return True
    if provider == "litellm":
        return True
    if provider == "ollama":
        return False
    return provider in {"openai", "huggingface", "groq", "gemini", "vertex_ai", "hf_pool"}


__all__ = ["build_runtime_text_llm_client", "build_runtime_structured_decision_runner", "filter_runtime_fallback_models"]
