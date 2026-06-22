from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from TeeBotus.llm.profiles import LLMProfile, LLMRoute, LLMRoutingRule, load_llm_profiles, load_llm_routing, select_llm_route

ROUTE_TO_FLOW = "llm_route_to"

_ROUTE_TO_RE = re.compile(r"^\s*/routeto(?P<target>[A-Za-z0-9_.:-]+)(?:@[^\s]+)?(?:\s+(?P<prompt>.*))?\s*$", re.IGNORECASE | re.DOTALL)
_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")

_PROFILE_ALIASES = {
    "ai": "openai_premium",
    "chatgpt": "openai_premium",
    "gpt": "openai_premium",
    "oai": "openai_premium",
    "openai": "openai_premium",
    "hf": "hf_pool_default",
    "huggingface": "hf_pool_default",
    "hfpool": "hf_pool_default",
    "huggingfacepool": "hf_pool_default",
    "hfmistral": "hf_mistral",
    "huggingfacemistral": "hf_mistral",
    "gemini": "gemini_flash_stateful",
    "google": "gemini_flash_stateful",
    "geminiflash": "gemini_flash_stateful",
    "geministateful": "gemini_flash_stateful",
    "geminiflashstateful": "gemini_flash_stateful",
    "geministateless": "gemini_flash_stateless",
    "geminiflashstateless": "gemini_flash_stateless",
    "geminipaid": "gemini_flash_paid_stateful",
    "geminipaidstateful": "gemini_flash_paid_stateful",
    "geminipaidstateless": "gemini_flash_paid_stateless",
    "gemini25": "gemini_2_5_flash_stateful",
    "gemini25flash": "gemini_2_5_flash_stateful",
    "gemini25stateful": "gemini_2_5_flash_stateful",
    "gemini25flashstateful": "gemini_2_5_flash_stateful",
    "gemini25stateless": "gemini_2_5_flash_stateless",
    "gemini25flashstateless": "gemini_2_5_flash_stateless",
    "gemini25paid": "gemini_2_5_flash_paid_stateful",
    "gemini25paidstateful": "gemini_2_5_flash_paid_stateful",
    "gemini25paidstateless": "gemini_2_5_flash_paid_stateless",
    "local": "local_ollama",
    "ollama": "local_ollama",
    "localollama": "local_ollama",
    "groq": "groq_fast",
    "vertex": "vertex_gemini_flash",
    "vertexgemini": "vertex_gemini_flash",
    "vertexgemini25": "vertex_gemini_2_5_flash",
}

_PURPOSE_ALIASES = {
    "normal": "normal_chat",
    "chat": "normal_chat",
    "normalchat": "normal_chat",
    "hard": "hard_reasoning",
    "reasoning": "hard_reasoning",
    "hardreasoning": "hard_reasoning",
    "cheap": "cheap_fast",
    "fast": "cheap_fast",
    "cheapfast": "cheap_fast",
    "private": "private",
    "bibliothekar": "bibliothekar_answer",
    "bibliothekaranswer": "bibliothekar_answer",
    "structured": "structured_decision",
    "decision": "structured_decision",
    "structureddecision": "structured_decision",
}


@dataclass(frozen=True)
class RouteToCommand:
    target: str
    prompt: str = ""


@dataclass(frozen=True)
class RouteToTarget:
    kind: str
    name: str
    provider: str
    model: str
    label: str


def parse_route_to_command(text: str) -> RouteToCommand | None:
    match = _ROUTE_TO_RE.match(str(text or ""))
    if not match:
        return None
    target = str(match.group("target") or "").strip()
    if not target:
        return None
    return RouteToCommand(target=target, prompt=str(match.group("prompt") or "").strip())


def resolve_route_to_target(
    target: str,
    *,
    profiles: Mapping[str, LLMProfile] | None = None,
    default_profile: str = "",
    routing: Mapping[str, LLMRoutingRule] | None = None,
    allow_remote_fallback: bool = True,
) -> RouteToTarget:
    resolved_profiles = dict(profiles) if profiles is not None else load_llm_profiles()
    resolved_default = default_profile
    resolved_routing: Mapping[str, LLMRoutingRule]
    if routing is None:
        loaded_default, loaded_routing = load_llm_routing()
        resolved_default = resolved_default or loaded_default
        resolved_routing = loaded_routing
    else:
        resolved_routing = dict(routing)

    normalized = normalize_route_to_token(target)
    profile_name = _profile_name_for_target(normalized, resolved_profiles)
    if profile_name:
        profile = resolved_profiles[profile_name]
        return RouteToTarget(
            kind="profile",
            name=profile.name,
            provider=_display_provider(profile.provider, profile.model),
            model=profile.model,
            label=f"Profil {profile.name}",
        )

    purpose_name = _purpose_name_for_target(normalized, resolved_routing)
    if purpose_name:
        route = select_llm_route(
            purpose_name,
            profiles=resolved_profiles,
            default_profile=resolved_default,
            routing=resolved_routing,
            allow_remote_fallback=allow_remote_fallback,
        )
        return _target_from_route(route)

    raise KeyError(f"Unknown RouteTo target: {target}")


def route_to_known_targets(*, profiles: Mapping[str, LLMProfile] | None = None, routing: Mapping[str, LLMRoutingRule] | None = None) -> tuple[str, ...]:
    resolved_profiles = dict(profiles) if profiles is not None else load_llm_profiles()
    if routing is None:
        _default_profile, resolved_routing = load_llm_routing()
    else:
        resolved_routing = dict(routing)
    names = [
        "OpenAI/OAI",
        "HF/HFPool",
        "Gemini",
        "Ollama/Local",
        "Groq",
        "Vertex",
    ]
    names.extend(sorted(resolved_profiles))
    names.extend(sorted(f"purpose:{name}" for name in resolved_routing))
    return tuple(dict.fromkeys(names))


def normalize_route_to_token(value: object) -> str:
    return _NORMALIZE_RE.sub("", str(value or "").strip().casefold())


def _profile_name_for_target(normalized: str, profiles: Mapping[str, LLMProfile]) -> str:
    alias = _PROFILE_ALIASES.get(normalized, "")
    if alias in profiles:
        return alias
    for name in profiles:
        if normalize_route_to_token(name) == normalized:
            return name
    provider_matches = [
        name
        for name, profile in profiles.items()
        if normalize_route_to_token(profile.provider) == normalized or normalize_route_to_token(profile.model.split("/", maxsplit=1)[0]) == normalized
    ]
    if len(provider_matches) == 1:
        return provider_matches[0]
    return ""


def _purpose_name_for_target(normalized: str, routing: Mapping[str, LLMRoutingRule]) -> str:
    alias = _PURPOSE_ALIASES.get(normalized, "")
    if alias in routing:
        return alias
    for name in routing:
        if normalize_route_to_token(name) == normalized:
            return name
    return ""


def _target_from_route(route: LLMRoute) -> RouteToTarget:
    return RouteToTarget(
        kind="purpose",
        name=route.purpose,
        provider=_display_provider(route.provider, route.model),
        model=route.model,
        label=f"Route {route.purpose} -> Profil {route.profile_name}",
    )


def _display_provider(provider: str, model: str) -> str:
    normalized_provider = str(provider or "").strip()
    normalized_model = str(model or "").strip()
    if normalized_provider.casefold() == "litellm" and "/" in normalized_model:
        prefix = normalized_model.split("/", maxsplit=1)[0].strip()
        if prefix:
            return prefix
    return normalized_provider


__all__ = [
    "ROUTE_TO_FLOW",
    "RouteToCommand",
    "RouteToTarget",
    "normalize_route_to_token",
    "parse_route_to_command",
    "resolve_route_to_target",
    "route_to_known_targets",
]
