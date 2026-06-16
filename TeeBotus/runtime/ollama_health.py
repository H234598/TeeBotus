from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from TeeBotus.llm.profiles import load_llm_profiles, select_llm_route
from TeeBotus.runtime.config import AccountRunConfig, RuntimeConfig

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_MODEL_PREFIXES = ("ollama/", "ollama_chat/")


@dataclass(frozen=True)
class OllamaServiceHealth:
    ok: bool
    target: str
    models: tuple[str, ...] = ()
    error: str = ""


def check_ollama_services(config: RuntimeConfig, *, timeout_seconds: float = 1.0) -> tuple[OllamaServiceHealth, ...]:
    base_urls = _ollama_base_urls(config)
    return tuple(check_ollama_service(base_url, timeout_seconds=timeout_seconds) for base_url in base_urls)


def check_ollama_service(base_url: str, *, timeout_seconds: float = 1.0) -> OllamaServiceHealth:
    normalized = _normalize_ollama_base_url(base_url)
    target = _ollama_target(normalized)
    url = f"{normalized}/api/tags"
    request = urllib.request.Request(url, headers={"User-Agent": "TeeBotus/1 runtime-status"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, TimeoutError, urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return OllamaServiceHealth(False, target, error=str(exc))
    return OllamaServiceHealth(True, target, models=_extract_ollama_models(payload))


def _ollama_base_urls(config: RuntimeConfig) -> tuple[str, ...]:
    result: list[str] = []
    for account in _accounts(config):
        for base_url in _account_ollama_base_urls(account):
            if base_url not in result:
                result.append(base_url)
    return tuple(result)


def _accounts(config: RuntimeConfig) -> tuple[AccountRunConfig, ...]:
    return tuple(account for instance in config.instances for account in instance.accounts)


def _account_ollama_base_urls(account: AccountRunConfig) -> tuple[str, ...]:
    result: list[str] = []
    if _account_direct_uses_ollama(account):
        result.append(_account_direct_ollama_base_url(account))
    profile_url = _profile_ollama_base_url(account)
    if profile_url and profile_url not in result:
        result.append(profile_url)
    route_url = _route_ollama_base_url(account)
    if route_url and route_url not in result:
        result.append(route_url)
    return tuple(result)


def _account_direct_uses_ollama(account: AccountRunConfig) -> bool:
    provider = str(account.llm_provider or "").strip().casefold().replace("-", "_")
    if provider in {"ollama", "local_ollama"}:
        return True
    models = [account.llm_model, *str(account.llm_fallback_models or "").split(",")]
    return any(_model_uses_ollama(model) for model in models)


def _model_uses_ollama(model: object) -> bool:
    value = str(model or "").strip().casefold()
    return value.startswith(OLLAMA_MODEL_PREFIXES)


def _account_direct_ollama_base_url(account: AccountRunConfig) -> str:
    base_url = str(account.llm_base_url or "").strip()
    if base_url:
        return base_url
    return DEFAULT_OLLAMA_BASE_URL


def _profile_ollama_base_url(account: AccountRunConfig) -> str:
    profile_name = str(account.llm_profile or "").strip()
    if not profile_name:
        return ""
    try:
        profile = load_llm_profiles()[profile_name]
    except Exception:
        return ""
    if not (_provider_uses_ollama(profile.provider) or _model_uses_ollama(profile.model)):
        return ""
    return profile.base_url or DEFAULT_OLLAMA_BASE_URL


def _route_ollama_base_url(account: AccountRunConfig) -> str:
    purpose = str(account.llm_purpose or "").strip()
    if not purpose:
        return ""
    if str(account.llm_provider or "").strip() or str(account.llm_model or "").strip():
        return ""
    try:
        route = select_llm_route(purpose, allow_remote_fallback=_parse_bool(account.llm_allow_remote_fallback))
    except Exception:
        return ""
    if _provider_uses_ollama(route.provider) or _model_uses_ollama(route.model) or any(_model_uses_ollama(model) for model in route.fallback_models):
        return route.base_url or DEFAULT_OLLAMA_BASE_URL
    return ""


def _provider_uses_ollama(provider: object) -> bool:
    value = str(provider or "").strip().casefold().replace("-", "_")
    return value in {"ollama", "local_ollama"}


def _parse_bool(value: object) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "ja", "on", "enabled", "an"}


def _normalize_ollama_base_url(base_url: str) -> str:
    text = str(base_url or "").strip() or DEFAULT_OLLAMA_BASE_URL
    parsed = urlsplit(text)
    if not parsed.scheme:
        parsed = urlsplit(f"http://{text}")
    scheme = parsed.scheme or "http"
    hostname = parsed.hostname or "127.0.0.1"
    port = parsed.port or 11434
    netloc = f"{hostname}:{port}"
    path = parsed.path.rstrip("/")
    if path.endswith("/api"):
        path = path[: -len("/api")]
    return urlunsplit((scheme, netloc, path, "", ""))


def _ollama_target(base_url: str) -> str:
    parsed = urlsplit(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 11434
    return f"{host}:{port}"


def _extract_ollama_models(payload: object) -> tuple[str, ...]:
    if not isinstance(payload, dict):
        return ()
    models = payload.get("models")
    if not isinstance(models, list):
        return ()
    names: list[str] = []
    for item in models:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("model") or "").strip()
        if name and name not in names:
            names.append(name)
    return tuple(names)


__all__ = ["OllamaServiceHealth", "check_ollama_service", "check_ollama_services"]
