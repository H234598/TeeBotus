from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.free_tier import resolve_gemini_free_tier_limits, route_uses_gemini_api, route_uses_google_gemini
from TeeBotus.llm.keyring import resolve_gemini_api_key_ring
from TeeBotus.llm.router import build_text_llm_client, normalize_llm_provider
from TeeBotus.llm.service_tier import resolve_gemini_service_tier

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE_PATH = PROJECT_ROOT / "config" / "llm_profiles.yaml"
DEFAULT_ROUTING_PATH = PROJECT_ROOT / "config" / "llm_routing.yaml"
REMOTE_PROVIDERS = frozenset(
    {
        "openai",
        "huggingface",
        "groq",
        "gemini",
        "gemini_interactions",
        "litellm_gemini_stateless",
        "litellm_gemini_stateful",
        "litellm_gemini_paid_stateless",
        "litellm_gemini_paid_stateful",
        "vertex_ai",
        "hf_pool",
    }
)


@dataclass(frozen=True)
class LLMProfile:
    name: str
    provider: str
    model: str
    base_url: str = ""
    api_key_env: str = ""
    service_tier: str = ""

    @property
    def is_remote(self) -> bool:
        provider = normalize_llm_provider(self.provider)
        if provider in REMOTE_PROVIDERS:
            return True
        model = self.model.casefold()
        if model.startswith(("ollama/", "ollama_chat/")):
            return False
        if model.startswith(("huggingface/", "groq/", "gemini/", "vertex_ai/", "openai/")):
            return True
        if provider == "litellm":
            return True
        return False


@dataclass(frozen=True)
class LLMRoutingRule:
    purpose: str
    profile: str
    fallback: str = ""


@dataclass(frozen=True)
class LLMRoute:
    purpose: str
    profile_name: str
    provider: str
    model: str
    base_url: str = ""
    api_key_env: str = ""
    service_tier: str = ""
    fallback_profile_name: str = ""
    fallback_model: str = ""
    fallback_api_key_env: str = ""
    fallback_base_url: str = ""
    fallback_service_tier: str = ""

    @property
    def fallback_models(self) -> tuple[str, ...]:
        return (self.fallback_model,) if self.fallback_model else ()


def load_llm_profiles(path: str | Path = DEFAULT_PROFILE_PATH) -> dict[str, LLMProfile]:
    payload = _load_yaml_mapping(Path(path))
    raw_profiles = payload.get("profiles")
    if not isinstance(raw_profiles, Mapping):
        return {}
    profiles: dict[str, LLMProfile] = {}
    for name, raw_profile in raw_profiles.items():
        if not isinstance(name, str):
            continue
        if not name.strip():
            continue
        if not isinstance(raw_profile, Mapping):
            continue
        profile = LLMProfile(
            name=name,
            provider=_config_string(raw_profile.get("provider")),
            model=_config_string(raw_profile.get("model")),
            base_url=_config_string(raw_profile.get("base_url") or raw_profile.get("api_base")),
            api_key_env=_config_string(raw_profile.get("api_key_env")),
            service_tier=_config_string(raw_profile.get("service_tier")),
        )
        if profile.provider and profile.model:
            profiles[profile.name] = profile
    return profiles


def load_llm_routing(path: str | Path = DEFAULT_ROUTING_PATH) -> tuple[str, dict[str, LLMRoutingRule]]:
    payload = _load_yaml_mapping(Path(path))
    default_profile = _config_string(payload.get("default_profile"))
    raw_purposes = payload.get("purposes")
    rules: dict[str, LLMRoutingRule] = {}
    if isinstance(raw_purposes, Mapping):
        for purpose, raw_rule in raw_purposes.items():
            if not isinstance(purpose, str):
                continue
            if not purpose.strip():
                continue
            if not isinstance(raw_rule, Mapping):
                continue
            name = normalize_llm_purpose(purpose)
            profile = _config_string(raw_rule.get("profile"))
            fallback = _optional_string(raw_rule.get("fallback"))
            if profile:
                rules[name] = LLMRoutingRule(purpose=name, profile=profile, fallback=fallback)
    return default_profile, rules


def select_llm_route(
    purpose: str,
    *,
    profiles: Mapping[str, LLMProfile] | None = None,
    default_profile: str = "",
    routing: Mapping[str, LLMRoutingRule] | None = None,
    allow_remote_fallback: bool = False,
) -> LLMRoute:
    resolved_profiles = dict(profiles) if profiles is not None else load_llm_profiles()
    if routing is None:
        loaded_default, loaded_routing = load_llm_routing()
        default_profile = default_profile or loaded_default
        resolved_routing = loaded_routing
    else:
        resolved_routing = dict(routing)
    purpose_name = normalize_llm_purpose(purpose)
    rule = resolved_routing.get(purpose_name) or LLMRoutingRule(purpose_name, default_profile)
    profile = _require_profile(resolved_profiles, rule.profile or default_profile)
    fallback_profile_name = ""
    fallback_model = ""
    fallback_api_key_env = ""
    fallback_base_url = ""
    fallback_service_tier = ""
    if rule.fallback:
        fallback = _require_profile(resolved_profiles, rule.fallback)
        if allow_remote_fallback or not fallback.is_remote:
            fallback_profile_name = fallback.name
            fallback_model = fallback.model
            fallback_api_key_env = fallback.api_key_env
            fallback_base_url = fallback.base_url
            fallback_service_tier = fallback.service_tier
    return LLMRoute(
        purpose=purpose_name,
        profile_name=profile.name,
        provider=profile.provider,
        model=profile.model,
        base_url=profile.base_url,
        api_key_env=profile.api_key_env,
        service_tier=profile.service_tier,
        fallback_profile_name=fallback_profile_name,
        fallback_model=fallback_model,
        fallback_api_key_env=fallback_api_key_env,
        fallback_base_url=fallback_base_url,
        fallback_service_tier=fallback_service_tier,
    )


def build_profiled_text_llm_client(
    *,
    purpose: str,
    instructions: BotInstructions,
    openai_client: object | None,
    profiles: Mapping[str, LLMProfile] | None = None,
    default_profile: str = "",
    routing: Mapping[str, LLMRoutingRule] | None = None,
    env: Mapping[str, str] | None = None,
    allow_remote_fallback: bool = False,
    instance_name: str = "",
) -> object | None:
    route = select_llm_route(
        purpose,
        profiles=profiles,
        default_profile=default_profile,
        routing=routing,
        allow_remote_fallback=allow_remote_fallback,
    )
    source = os.environ if env is None else env
    api_key = resolve_profile_api_key(
        source,
        route.api_key_env,
        provider=route.provider,
        model=route.model,
        instance_name=instance_name,
    )
    fallback_api_key = resolve_profile_api_key(
        source,
        route.fallback_api_key_env,
        provider="litellm",
        model=route.fallback_model,
        instance_name=instance_name,
    )
    gemini_key_model = _first_google_gemini_model(route)
    uses_gemini_api = _route_uses_gemini_api(route.provider, route.model) or _route_uses_gemini_api(
        route.provider,
        route.fallback_model,
    )
    return build_text_llm_client(
        instructions=instructions,
        openai_client=openai_client,
        provider=route.provider,
        model=route.model,
        fallback_models=route.fallback_models,
        fallback_api_keys={route.fallback_model: fallback_api_key} if route.fallback_model and fallback_api_key else None,
        fallback_api_bases={route.fallback_model: route.fallback_base_url} if route.fallback_model and route.fallback_base_url else None,
        api_key=api_key,
        api_key_ring=resolve_gemini_api_key_ring(source) if uses_gemini_api else (),
        gemini_free_tier_limits=resolve_gemini_free_tier_limits(source, provider=route.provider, model=gemini_key_model)
        if gemini_key_model
        else None,
        service_tier=resolve_gemini_service_tier(
            source,
            provider=route.provider,
            model=gemini_key_model or route.model,
            explicit_service_tier=route.service_tier or route.fallback_service_tier or instructions.llm_service_tier,
        ),
        api_base=route.base_url,
        purpose=route.purpose,
        use_instruction_fallback_models=False,
        env=source,
    )


def resolve_profile_api_key(
    source: Mapping[str, str],
    api_key_env: str,
    *,
    provider: str,
    model: object,
    instance_name: str = "",
) -> str:
    """Resolve instance-scoped OpenAI keys before the global profile key."""
    env_name = str(api_key_env or "").strip()
    if not env_name:
        return ""
    normalized_provider = normalize_llm_provider(provider)
    normalized_model = str(model or "").strip().casefold()
    uses_openai = normalized_provider == "openai" or (
        normalized_provider == "litellm"
        and (normalized_model.startswith("openai/") or env_name.casefold() == "openai_api_key")
    )
    if uses_openai:
        token = _instance_env_token(instance_name)
        if token:
            candidates = [f"{env_name}_{token}"]
            if env_name != "OPENAI_API_KEY":
                candidates.append(f"OPENAI_API_KEY_{token}")
            for candidate in candidates:
                value = str(source.get(candidate, "") or "").strip()
                if value:
                    return value
    return str(source.get(env_name, "") or "").strip()


def normalize_llm_purpose(value: object) -> str:
    text = str(value or "").strip().casefold()
    if not text:
        return "normal_chat"
    normalized = re.sub(r"[\s-]+", "_", text)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "normal_chat"


def _route_uses_gemini_api(provider: str, model: str) -> bool:
    return route_uses_gemini_api(provider=provider, model=model)


def _first_google_gemini_model(route: LLMRoute) -> str:
    if route_uses_google_gemini(provider=route.provider, model=route.model):
        return route.model
    if route_uses_google_gemini(provider=route.provider, model=route.fallback_model):
        return route.fallback_model
    return ""


def _require_profile(profiles: Mapping[str, LLMProfile], name: str) -> LLMProfile:
    key = str(name or "").strip()
    if key not in profiles:
        raise KeyError(f"Unknown LLM profile: {key or '<empty>'}")
    return profiles[key]


def _optional_string(value: object) -> str:
    if value is None:
        return ""
    text = _config_string(value)
    return "" if text.casefold() in {"", "none", "null"} else text


def _config_string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _instance_env_token(instance_name: str) -> str:
    token = "".join(char if char.isalnum() else "_" for char in str(instance_name or "").strip().upper())
    return "_".join(part for part in token.split("_") if part)


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-not-found]
    except Exception:
        return _parse_simple_yaml_mapping(text)
    payload = yaml.safe_load(text) or {}
    return payload if isinstance(payload, dict) else {}


def _parse_simple_yaml_mapping(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for line in text.splitlines():
        stripped = line.split("#", maxsplit=1)[0].rstrip()
        if not stripped:
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        key, sep, value = stripped.strip().partition(":")
        if not sep:
            continue
        while stack and indent <= stack[-1][0]:
            stack.pop()
        current = stack[-1][1]
        parsed_value: Any
        if value.strip():
            parsed_value = _parse_scalar(value.strip())
            current[key] = parsed_value
        else:
            parsed_value = {}
            current[key] = parsed_value
            stack.append((indent, parsed_value))
    return root


def _parse_scalar(value: str) -> object:
    text = value.strip().strip("\"'")
    if text.casefold() in {"null", "none"}:
        return None
    if text.casefold() == "true":
        return True
    if text.casefold() == "false":
        return False
    return text
