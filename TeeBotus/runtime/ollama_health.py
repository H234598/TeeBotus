from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

from TeeBotus.llm.profiles import load_llm_profiles, select_llm_route
from TeeBotus.runtime.config import AccountRunConfig, RuntimeConfig

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_MODEL_PREFIXES = ("ollama/", "ollama_chat/")
LOCAL_OLLAMA_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


@dataclass(frozen=True)
class OllamaServiceHealth:
    ok: bool
    target: str
    models: tuple[str, ...] = ()
    error: str = ""


def check_ollama_services(
    config: RuntimeConfig,
    *,
    timeout_seconds: float = 1.0,
    instructions_by_instance: Mapping[str, Any] | None = None,
) -> tuple[OllamaServiceHealth, ...]:
    base_urls = _ollama_base_urls(config, instructions_by_instance=instructions_by_instance)
    return tuple(check_ollama_service(base_url, timeout_seconds=timeout_seconds) for base_url in base_urls)


def check_ollama_service(base_url: str, *, timeout_seconds: float = 1.0) -> OllamaServiceHealth:
    safety_error = _unsafe_ollama_base_url_reason(base_url)
    if safety_error:
        target = _safe_ollama_target(base_url)
        return OllamaServiceHealth(False, target, error=safety_error)
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


def _ollama_base_urls(config: RuntimeConfig, *, instructions_by_instance: Mapping[str, Any] | None = None) -> tuple[str, ...]:
    result: list[str] = []
    for account in _accounts(config):
        instructions = (instructions_by_instance or {}).get(account.instance_name)
        for base_url in _account_ollama_base_urls(account, instructions):
            if base_url not in result:
                result.append(base_url)
    return tuple(result)


def _accounts(config: RuntimeConfig) -> tuple[AccountRunConfig, ...]:
    return tuple(account for instance in config.instances for account in instance.accounts)


def _account_ollama_base_urls(account: AccountRunConfig, instructions: Any | None = None) -> tuple[str, ...]:
    if _account_llm_disabled(account, instructions):
        return ()
    profile_name = _effective_profile_name(account, instructions)
    if profile_name:
        profile_url = _profile_ollama_base_url(account, profile_name=profile_name)
        return (profile_url,) if profile_url else ()
    route_url = _route_ollama_base_url(account)
    if route_url:
        return (route_url,)
    if _purpose_route_wins(account):
        return ()
    if _account_direct_uses_ollama(account, instructions):
        return (_account_direct_ollama_base_url(account, instructions),)
    return ()


def _account_llm_disabled(account: AccountRunConfig, instructions: Any | None = None) -> bool:
    enabled_override = _parse_optional_bool(account.llm_enabled)
    if enabled_override is False:
        return True
    return enabled_override is None and getattr(instructions, "llm_enabled", None) is False


def _account_direct_uses_ollama(account: AccountRunConfig, instructions: Any | None = None) -> bool:
    provider = _effective_text(account, instructions, "llm_provider", "llm_provider").casefold().replace("-", "_")
    if provider in {"ollama", "local_ollama"}:
        return True
    models = [
        _effective_text(account, instructions, "llm_model", "llm_model"),
        *_effective_fallback_models(account, instructions),
    ]
    return any(_model_uses_ollama(model) for model in models)


def _model_uses_ollama(model: object) -> bool:
    value = str(model or "").strip().casefold()
    return value.startswith(OLLAMA_MODEL_PREFIXES)


def _account_direct_ollama_base_url(account: AccountRunConfig, instructions: Any | None = None) -> str:
    base_url = _effective_text(account, instructions, "llm_base_url", "llm_base_url")
    if base_url:
        return base_url
    return DEFAULT_OLLAMA_BASE_URL


def _profile_ollama_base_url(account: AccountRunConfig, *, profile_name: str) -> str:
    if not profile_name:
        return ""
    try:
        profile = load_llm_profiles()[profile_name]
    except Exception:
        return ""
    if not (_provider_uses_ollama(profile.provider) or _model_uses_ollama(profile.model)):
        return ""
    return str(account.llm_base_url or "").strip() or profile.base_url or DEFAULT_OLLAMA_BASE_URL


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
    account_fallbacks = tuple(part.strip() for part in str(account.llm_fallback_models or "").split(",") if part.strip())
    fallback_models = account_fallbacks or route.fallback_models
    if _provider_uses_ollama(route.provider) or _model_uses_ollama(route.model) or any(_model_uses_ollama(model) for model in fallback_models):
        return str(account.llm_base_url or "").strip() or route.base_url or DEFAULT_OLLAMA_BASE_URL
    return ""


def _provider_uses_ollama(provider: object) -> bool:
    value = str(provider or "").strip().casefold().replace("-", "_")
    return value in {"ollama", "local_ollama"}


def _parse_bool(value: object) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "ja", "on", "enabled", "an"}


def _parse_optional_bool(value: object) -> bool | None:
    text = str(value or "").strip().casefold()
    if not text:
        return None
    if text in {"1", "true", "yes", "ja", "on", "enabled", "an"}:
        return True
    if text in {"0", "false", "no", "nein", "off", "disabled", "aus"}:
        return False
    return None


def _effective_text(account: AccountRunConfig, instructions: Any | None, account_attr: str, instruction_attr: str) -> str:
    account_value = str(getattr(account, account_attr, "") or "").strip()
    if account_value:
        return account_value
    if instructions is None:
        return ""
    value = getattr(instructions, instruction_attr, "")
    if isinstance(value, (tuple, list)):
        return ",".join(str(part or "").strip() for part in value if str(part or "").strip())
    return str(value or "").strip()


def _effective_profile_name(account: AccountRunConfig, instructions: Any | None) -> str:
    account_profile = str(account.llm_profile or "").strip()
    if account_profile:
        return account_profile
    if _has_runtime_llm_route_override(account):
        return ""
    return _effective_text(account, instructions, "llm_profile", "llm_profile")


def _has_runtime_llm_route_override(account: AccountRunConfig) -> bool:
    return any(str(getattr(account, attr, "") or "").strip() for attr in ("llm_purpose", "llm_provider", "llm_model"))


def _purpose_route_wins(account: AccountRunConfig) -> bool:
    return bool(str(account.llm_purpose or "").strip()) and not (
        str(account.llm_provider or "").strip() or str(account.llm_model or "").strip()
    )


def _effective_fallback_models(account: AccountRunConfig, instructions: Any | None) -> tuple[str, ...]:
    configured = str(account.llm_fallback_models or "").strip()
    if configured:
        return tuple(part.strip() for part in configured.split(",") if part.strip())
    if instructions is None:
        return ()
    return tuple(str(part or "").strip() for part in getattr(instructions, "llm_fallback_models", ()) if str(part or "").strip())


def _normalize_ollama_base_url(base_url: str) -> str:
    parsed = _parse_ollama_base_url(base_url)
    scheme = parsed.scheme or "http"
    hostname = parsed.hostname or "127.0.0.1"
    port = parsed.port or 11434
    netloc = f"{hostname}:{port}"
    path = parsed.path.rstrip("/")
    if path.endswith("/api"):
        path = path[: -len("/api")]
    return urlunsplit((scheme, netloc, path, "", ""))


def _unsafe_ollama_base_url_reason(base_url: str) -> str:
    try:
        parsed = _parse_ollama_base_url(base_url)
        port = parsed.port
    except ValueError:
        return "unsafe Ollama base_url: invalid URL"
    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        return "unsafe Ollama base_url: scheme must be http or https"
    if parsed.username or parsed.password:
        return "unsafe Ollama base_url: credentials are not allowed"
    if parsed.query or parsed.fragment:
        return "unsafe Ollama base_url: query and fragment are not allowed"
    host = (parsed.hostname or "127.0.0.1").strip().casefold()
    if host not in LOCAL_OLLAMA_HOSTS:
        return "unsafe Ollama base_url: host must be loopback"
    if port is not None and port <= 0:
        return "unsafe Ollama base_url: invalid port"
    return ""


def _parse_ollama_base_url(base_url: str):
    text = str(base_url or "").strip() or DEFAULT_OLLAMA_BASE_URL
    if "://" not in text and not text.startswith("//"):
        text = f"http://{text}"
    return urlsplit(text)


def _safe_ollama_target(base_url: str) -> str:
    try:
        parsed = _parse_ollama_base_url(base_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 11434
    except ValueError:
        return "invalid"
    return f"{host}:{port}"


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
