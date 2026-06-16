from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.router import build_text_llm_client, normalize_llm_provider

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE_PATH = PROJECT_ROOT / "config" / "llm_profiles.yaml"
DEFAULT_ROUTING_PATH = PROJECT_ROOT / "config" / "llm_routing.yaml"
REMOTE_PROVIDERS = frozenset({"openai", "huggingface", "groq", "gemini"})


@dataclass(frozen=True)
class LLMProfile:
    name: str
    provider: str
    model: str
    base_url: str = ""
    api_key_env: str = ""

    @property
    def is_remote(self) -> bool:
        provider = normalize_llm_provider(self.provider)
        if provider in REMOTE_PROVIDERS:
            return True
        model = self.model.casefold()
        if model.startswith(("ollama/", "ollama_chat/")):
            return False
        if model.startswith(("huggingface/", "groq/", "gemini/", "openai/")):
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
    fallback_profile_name: str = ""
    fallback_model: str = ""
    fallback_api_key_env: str = ""
    fallback_base_url: str = ""

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
        if not isinstance(raw_profile, Mapping):
            continue
        profile = LLMProfile(
            name=str(name),
            provider=str(raw_profile.get("provider") or "").strip(),
            model=str(raw_profile.get("model") or "").strip(),
            base_url=str(raw_profile.get("base_url") or raw_profile.get("api_base") or "").strip(),
            api_key_env=str(raw_profile.get("api_key_env") or "").strip(),
        )
        if profile.provider and profile.model:
            profiles[profile.name] = profile
    return profiles


def load_llm_routing(path: str | Path = DEFAULT_ROUTING_PATH) -> tuple[str, dict[str, LLMRoutingRule]]:
    payload = _load_yaml_mapping(Path(path))
    default_profile = str(payload.get("default_profile") or "").strip()
    raw_purposes = payload.get("purposes")
    rules: dict[str, LLMRoutingRule] = {}
    if isinstance(raw_purposes, Mapping):
        for purpose, raw_rule in raw_purposes.items():
            if not isinstance(raw_rule, Mapping):
                continue
            name = normalize_llm_purpose(purpose)
            profile = str(raw_rule.get("profile") or "").strip()
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
    if rule.fallback:
        fallback = _require_profile(resolved_profiles, rule.fallback)
        if allow_remote_fallback or not fallback.is_remote:
            fallback_profile_name = fallback.name
            fallback_model = fallback.model
            fallback_api_key_env = fallback.api_key_env
            fallback_base_url = fallback.base_url
    return LLMRoute(
        purpose=purpose_name,
        profile_name=profile.name,
        provider=profile.provider,
        model=profile.model,
        base_url=profile.base_url,
        api_key_env=profile.api_key_env,
        fallback_profile_name=fallback_profile_name,
        fallback_model=fallback_model,
        fallback_api_key_env=fallback_api_key_env,
        fallback_base_url=fallback_base_url,
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
) -> object | None:
    route = select_llm_route(
        purpose,
        profiles=profiles,
        default_profile=default_profile,
        routing=routing,
        allow_remote_fallback=allow_remote_fallback,
    )
    source = os.environ if env is None else env
    api_key = source.get(route.api_key_env, "").strip() if route.api_key_env else ""
    fallback_api_key = source.get(route.fallback_api_key_env, "").strip() if route.fallback_api_key_env else ""
    return build_text_llm_client(
        instructions=instructions,
        openai_client=openai_client,
        provider=route.provider,
        model=route.model,
        fallback_models=route.fallback_models,
        fallback_api_keys={route.fallback_model: fallback_api_key} if route.fallback_model and fallback_api_key else None,
        fallback_api_bases={route.fallback_model: route.fallback_base_url} if route.fallback_model and route.fallback_base_url else None,
        api_key=api_key,
        api_base=route.base_url,
        use_instruction_fallback_models=False,
    )


def normalize_llm_purpose(value: object) -> str:
    text = str(value or "").strip().casefold()
    if not text:
        return "normal_chat"
    normalized = re.sub(r"[\s-]+", "_", text)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "normal_chat"


def _require_profile(profiles: Mapping[str, LLMProfile], name: str) -> LLMProfile:
    key = str(name or "").strip()
    if key not in profiles:
        raise KeyError(f"Unknown LLM profile: {key or '<empty>'}")
    return profiles[key]


def _optional_string(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.casefold() in {"", "none", "null"} else text


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
