from __future__ import annotations

import html
import json
import logging
import os
import re
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen


LOGGER = logging.getLogger("TeeBotus.llm.gemini_limits_refresh")

DEFAULT_GEMINI_FREE_TIER_LIMIT_SOURCE_URL = "https://ai.google.dev/gemini-api/docs/rate-limits"
DEFAULT_GEMINI_FREE_TIER_REFRESH_INTERVAL_SECONDS = 86_400
DEFAULT_GEMINI_FREE_TIER_FETCH_TIMEOUT_SECONDS = 20
GEMINI_FREE_TIER_LIMIT_CACHE_SCHEMA = 1

LimitValues = dict[str, int | None]
PayloadFetcher = Callable[[str, int], str]
DEFAULT_GEMINI_FREE_TIER_FALLBACK_MODELS: Mapping[str, LimitValues] = {
    "gemini-2.5-flash": {"rpm": 5, "tpm": 250_000, "rpd": 20},
    "gemini-3.5-flash": {"rpm": 5, "tpm": 250_000, "rpd": 20},
}

_REFRESH_THREAD_LOCK = threading.Lock()
_REFRESH_THREAD: threading.Thread | None = None


@dataclass(frozen=True)
class GeminiFreeTierRefreshResult:
    status: str
    cache_path: Path
    source_url: str
    models: int = 0
    fetched: bool = False
    skipped_reason: str = ""
    error: str = ""


def refresh_gemini_free_tier_limits_if_due(
    env: Mapping[str, str] | None = None,
    *,
    force: bool = False,
    now: Callable[[], datetime] | None = None,
    fetcher: PayloadFetcher | None = None,
    cache_path: Path | None = None,
) -> GeminiFreeTierRefreshResult:
    source = os.environ if env is None else env
    resolved_cache_path = cache_path or gemini_free_tier_limit_cache_path(source)
    source_url = _source_url(source)
    if not _parse_bool_env(_refresh_env(source, "ENABLED"), default=True):
        return GeminiFreeTierRefreshResult("disabled", resolved_cache_path, source_url, skipped_reason="refresh_disabled")
    interval_seconds = _refresh_interval_seconds(source)
    current_time = (now or _utcnow)()
    cache = _read_cache(resolved_cache_path)
    if (
        not force
        and not _refresh_due(cache, now=current_time, interval_seconds=interval_seconds)
        and not _cache_needs_default_fallback_upgrade(cache, source_url=source_url)
    ):
        return GeminiFreeTierRefreshResult(
            "skipped",
            resolved_cache_path,
            source_url,
            models=len(_cache_models(cache)),
            skipped_reason="fresh_cache",
        )
    try:
        payload = (fetcher or _fetch_text_payload)(source_url, _fetch_timeout_seconds(source))
        parsed = parse_gemini_free_tier_limits_payload(payload, source_url=source_url)
    except Exception as exc:  # noqa: BLE001 - refresh must not break bot startup.
        merged = dict(cache)
        merged.update(
            {
                "schema": GEMINI_FREE_TIER_LIMIT_CACHE_SCHEMA,
                "last_refresh_attempt_at": _format_datetime(current_time),
                "last_refresh_status": "error",
                "last_refresh_error": _safe_detail(f"{type(exc).__name__}: {exc}"),
                "source_url": source_url,
            }
        )
        _write_cache(resolved_cache_path, merged)
        return GeminiFreeTierRefreshResult(
            "error",
            resolved_cache_path,
            source_url,
            models=len(_cache_models(cache)),
            error=_safe_detail(f"{type(exc).__name__}: {exc}"),
        )
    if not parsed:
        fallback_models = _fallback_models_for_nonpublic_limit_source(payload, source_url=source_url)
        if fallback_models:
            detail = "public source does not expose per-model free-tier limits; using conservative defaults"
            cache_payload = {
                "schema": GEMINI_FREE_TIER_LIMIT_CACHE_SCHEMA,
                "fetched_at": _format_datetime(current_time),
                "last_refresh_attempt_at": _format_datetime(current_time),
                "last_refresh_status": "fallback_defaults",
                "last_refresh_error": detail,
                "source_url": source_url,
                "models": dict(fallback_models),
                "limits_source": "conservative_defaults",
            }
            _write_cache(resolved_cache_path, cache_payload)
            return GeminiFreeTierRefreshResult(
                "fallback_defaults",
                resolved_cache_path,
                source_url,
                models=len(fallback_models),
                fetched=True,
                error=detail,
            )
        merged = dict(cache)
        merged.update(
            {
                "schema": GEMINI_FREE_TIER_LIMIT_CACHE_SCHEMA,
                "last_refresh_attempt_at": _format_datetime(current_time),
                "last_refresh_status": "no_limits_found",
                "last_refresh_error": "source contained no parseable free-tier RPM/TPM/RPD table",
                "source_url": source_url,
            }
        )
        _write_cache(resolved_cache_path, merged)
        return GeminiFreeTierRefreshResult(
            "no_limits_found",
            resolved_cache_path,
            source_url,
            models=len(_cache_models(cache)),
            fetched=True,
            error="source contained no parseable free-tier RPM/TPM/RPD table",
        )
    normalized_models = {
        normalize_gemini_limit_model_name(model): values
        for model, values in parsed.items()
        if normalize_gemini_limit_model_name(model)
    }
    cache_payload = {
        "schema": GEMINI_FREE_TIER_LIMIT_CACHE_SCHEMA,
        "fetched_at": _format_datetime(current_time),
        "last_refresh_attempt_at": _format_datetime(current_time),
        "last_refresh_status": "ok",
        "source_url": source_url,
        "models": normalized_models,
    }
    _write_cache(resolved_cache_path, cache_payload)
    return GeminiFreeTierRefreshResult("ok", resolved_cache_path, source_url, models=len(normalized_models), fetched=True)


def start_gemini_free_tier_limit_refresh_background(
    env: Mapping[str, str] | None = None,
    *,
    instance_names: tuple[str, ...] = (),
) -> bool:
    source = dict(os.environ if env is None else env)
    if not _parse_bool_env(_refresh_env(source, "ENABLED"), default=True):
        return False
    if not _refresh_relevant_for_runtime(source, instance_names=instance_names):
        return False
    interval_seconds = max(60, _refresh_interval_seconds(source))
    global _REFRESH_THREAD
    with _REFRESH_THREAD_LOCK:
        if _REFRESH_THREAD is not None and _REFRESH_THREAD.is_alive():
            return False
        thread = threading.Thread(
            target=_refresh_loop,
            args=(source, interval_seconds),
            name="teebotus-gemini-free-tier-refresh",
            daemon=True,
        )
        _REFRESH_THREAD = thread
        thread.start()
    return True


def gemini_free_tier_limit_status_line(env: Mapping[str, str] | None = None, *, now: Callable[[], datetime] | None = None) -> str:
    source = os.environ if env is None else env
    cache_path = gemini_free_tier_limit_cache_path(source)
    source_url = _source_url(source)
    if not _parse_bool_env(_refresh_env(source, "ENABLED"), default=True):
        return f"gemini_free_tier_limits status=disabled source={_display_url(source_url)} cache={cache_path}"
    cache = _read_cache(cache_path)
    models = _cache_models(cache)
    status = str(cache.get("last_refresh_status") or ("ok" if models else "never")).strip()
    fetched_at = str(cache.get("fetched_at") or "never").strip()
    attempt_at = str(cache.get("last_refresh_attempt_at") or "never").strip()
    age = _cache_age_seconds(cache, now=(now or _utcnow)())
    age_part = f" age_seconds={age}" if age is not None else ""
    error = str(cache.get("last_refresh_error") or "").strip()
    error_part = f" error={_status_token(_safe_detail(error))}" if error else ""
    return (
        f"gemini_free_tier_limits status={_status_token(status)} source={_display_url(source_url)} "
        f"cache={cache_path} models={len(models)} fetched_at={_status_token(fetched_at)} "
        f"last_attempt_at={_status_token(attempt_at)} refresh_interval_seconds={_refresh_interval_seconds(source)}"
        f"{age_part}{error_part}"
    )


def cached_gemini_free_tier_limit_values(
    env: Mapping[str, str] | None = None,
    *,
    model: str,
) -> LimitValues:
    source = os.environ if env is None else env
    cache = _read_cache(gemini_free_tier_limit_cache_path(source))
    models = _cache_models(cache)
    normalized = normalize_gemini_limit_model_name(model)
    if not normalized:
        return {}
    values = models.get(normalized)
    if isinstance(values, Mapping):
        return _limit_values_from_mapping(values)
    return {}


def parse_gemini_free_tier_limits_payload(payload: str, *, source_url: str = "") -> dict[str, LimitValues]:
    text = str(payload or "")
    if not text.strip():
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return _parse_text_limit_rows(text)
    result: dict[str, LimitValues] = {}
    _collect_json_limit_rows(parsed, result)
    return result


def gemini_free_tier_limit_cache_path(env: Mapping[str, str] | None = None) -> Path:
    source = os.environ if env is None else env
    configured = str(source.get("TEEBOTUS_GEMINI_FREE_TIER_CACHE") or source.get("GEMINI_FREE_TIER_CACHE") or "").strip()
    if configured:
        return Path(configured).expanduser()
    cache_home = str(source.get("XDG_CACHE_HOME") or "").strip()
    base = Path(cache_home).expanduser() if cache_home else Path.home() / ".cache"
    return base / "teebotus" / "gemini_free_tier_limits.json"


def normalize_gemini_limit_model_name(value: object) -> str:
    text = html.unescape(str(value or "")).strip().casefold()
    if not text:
        return ""
    if "/" in text:
        prefix, suffix = text.split("/", 1)
        if prefix in {"gemini", "vertex_ai", "google", "models"}:
            text = suffix
    if text.startswith("models/"):
        text = text.removeprefix("models/")
    text = text.replace("flash lite", "flash-lite").replace("flash_lite", "flash-lite")
    text = re.sub(r"[^a-z0-9.]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text


def _collect_json_limit_rows(obj: object, result: dict[str, LimitValues]) -> None:
    if isinstance(obj, Mapping):
        direct_model = _json_model_name(obj)
        direct_values = _limit_values_from_mapping(obj)
        if direct_model and direct_values and _json_tier_is_free_or_unspecified(obj):
            result[direct_model] = direct_values
        for key, value in obj.items():
            if isinstance(value, Mapping):
                nested_values = _limit_values_from_mapping(value)
                if _looks_like_gemini_model(key) and nested_values and _json_tier_is_free_or_unspecified(value):
                    result[str(key)] = nested_values
            _collect_json_limit_rows(value, result)
    elif isinstance(obj, list):
        for item in obj:
            _collect_json_limit_rows(item, result)


def _parse_text_limit_rows(payload: str) -> dict[str, LimitValues]:
    normalized_html = re.sub(r"</(?:tr|p|li|div|h[1-6])>", "\n", payload, flags=re.IGNORECASE)
    normalized_html = re.sub(r"</t[dh]>", " ", normalized_html, flags=re.IGNORECASE)
    text = html.unescape(re.sub(r"<[^>]+>", " ", normalized_html))
    result: dict[str, LimitValues] = {}
    row_re = re.compile(
        r"(?:\bfree\b\s+)?"
        r"(?P<model>Gemini\s+\d+(?:\.\d+)?\s+(?:Pro|Flash(?:[- ]Lite)?)(?:\s+(?:Preview|Experimental|TTS|Image|Audio|Live|Thinking))*)"
        r"(?:\s+\bfree\b)?"
        r"\s+(?P<rpm>\d[\d,]*|none|unlimited)"
        r"\s+(?P<tpm>\d[\d,]*|none|unlimited)"
        r"\s+(?P<rpd>\d[\d,]*|none|unlimited)\b",
        re.IGNORECASE,
    )
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if "gemini" not in line.casefold():
            continue
        for match in row_re.finditer(line):
            result[match.group("model")] = {
                "rpm": _parse_limit_number(match.group("rpm")),
                "tpm": _parse_limit_number(match.group("tpm")),
                "rpd": _parse_limit_number(match.group("rpd")),
            }
    return result


def _fallback_models_for_nonpublic_limit_source(payload: str, *, source_url: str) -> Mapping[str, LimitValues]:
    if not _is_default_gemini_limit_source(source_url):
        return {}
    text = _plain_text_from_payload(payload).casefold()
    if "view your active rate limits in ai studio" not in text:
        return {}
    if "specified rate limits are not guaranteed" not in text and "rate limits depend on" not in text:
        return {}
    return dict(DEFAULT_GEMINI_FREE_TIER_FALLBACK_MODELS)


def _plain_text_from_payload(payload: str) -> str:
    normalized_html = re.sub(r"</(?:tr|p|li|div|h[1-6])>", "\n", str(payload or ""), flags=re.IGNORECASE)
    normalized_html = re.sub(r"</t[dh]>", " ", normalized_html, flags=re.IGNORECASE)
    text = html.unescape(re.sub(r"<[^>]+>", " ", normalized_html))
    return re.sub(r"\s+", " ", text).strip()


def _limit_values_from_mapping(value: Mapping[str, object]) -> LimitValues:
    aliases = {
        "rpm": ("rpm", "requests_per_minute", "requestsPerMinute", "request_per_minute", "requests/minute"),
        "tpm": (
            "tpm",
            "input_tokens_per_minute",
            "inputTokensPerMinute",
            "tokens_per_minute",
            "tokensPerMinute",
            "input_tpm",
        ),
        "rpd": ("rpd", "requests_per_day", "requestsPerDay", "request_per_day", "requests/day"),
        "reserve_tokens": ("reserve_tokens", "reserve_input_tokens", "reserveInputTokens"),
    }
    result: LimitValues = {}
    for output_key, names in aliases.items():
        raw = _first_mapping_value(value, names)
        if raw is not None:
            result[output_key] = _parse_limit_number(raw)
    return result


def _first_mapping_value(value: Mapping[str, object], names: tuple[str, ...]) -> object | None:
    lowered = {str(key).casefold().replace("-", "_"): item for key, item in value.items()}
    for name in names:
        key = name.casefold().replace("-", "_")
        if key in lowered:
            return lowered[key]
    return None


def _json_model_name(value: Mapping[str, object]) -> str:
    for key in ("model", "model_name", "modelName", "name"):
        model = str(value.get(key) or "").strip()
        if _looks_like_gemini_model(model):
            return model
    return ""


def _json_tier_is_free_or_unspecified(value: Mapping[str, object]) -> bool:
    tier = str(value.get("tier") or value.get("usage_tier") or value.get("usageTier") or "").strip().casefold()
    return not tier or tier in {"free", "free_tier", "free-tier"}


def _looks_like_gemini_model(value: object) -> bool:
    return "gemini" in str(value or "").casefold()


def _parse_limit_number(value: object) -> int | None:
    text = str(value or "").strip().casefold().replace("_", "").replace(",", "")
    if text in {"", "none", "null", "unlimited", "off", "disabled", "*"}:
        return None
    try:
        parsed = int(float(text))
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _refresh_loop(env: Mapping[str, str], interval_seconds: int) -> None:
    while True:
        try:
            result = refresh_gemini_free_tier_limits_if_due(env)
            if result.status not in {"skipped", "ok"}:
                LOGGER.info("Gemini free-tier limit refresh status=%s detail=%s", result.status, result.error or result.skipped_reason)
        except Exception as exc:  # noqa: BLE001 - background refresh must stay non-fatal.
            LOGGER.warning("Gemini free-tier limit refresh failed: %s: %s", type(exc).__name__, exc)
        time.sleep(interval_seconds)


def _fetch_text_payload(source_url: str, timeout_seconds: int) -> str:
    url = str(source_url or "").strip()
    split = urlsplit(url)
    if split.scheme in {"", "file"}:
        path = Path(unquote(split.path if split.scheme == "file" else url)).expanduser()
        return path.read_text(encoding="utf-8")
    request = Request(url, headers={"User-Agent": "TeeBotus/1 gemini-free-tier-refresh"})
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - URL is explicit local runtime config.
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def _read_cache(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_cache(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _cache_models(cache: Mapping[str, object]) -> Mapping[str, object]:
    models = cache.get("models")
    return models if isinstance(models, Mapping) else {}


def _refresh_due(cache: Mapping[str, object], *, now: datetime, interval_seconds: int) -> bool:
    timestamp = str(cache.get("last_refresh_attempt_at") or cache.get("fetched_at") or "").strip()
    if not timestamp:
        return True
    last = _parse_datetime(timestamp)
    if last is None:
        return True
    return (now - last).total_seconds() >= max(0, interval_seconds)


def _cache_needs_default_fallback_upgrade(cache: Mapping[str, object], *, source_url: str) -> bool:
    models = _cache_models(cache)
    if models:
        if (
            _is_default_gemini_limit_source(source_url)
            and str(cache.get("limits_source") or "").strip().casefold() == "conservative_defaults"
        ):
            return bool(set(DEFAULT_GEMINI_FREE_TIER_FALLBACK_MODELS) - set(models))
        return False
    if not _is_default_gemini_limit_source(source_url):
        return False
    if str(cache.get("limits_source") or "").strip().casefold() == "conservative_defaults":
        return False
    status = str(cache.get("last_refresh_status") or "").strip().casefold()
    return status in {"", "never", "no_limits_found"}


def _is_default_gemini_limit_source(source_url: str) -> bool:
    return str(source_url or "").strip().rstrip("/").casefold() == DEFAULT_GEMINI_FREE_TIER_LIMIT_SOURCE_URL.rstrip("/").casefold()


def _cache_age_seconds(cache: Mapping[str, object], *, now: datetime) -> int | None:
    timestamp = str(cache.get("fetched_at") or "").strip()
    parsed = _parse_datetime(timestamp)
    if parsed is None:
        return None
    return max(0, int((now - parsed).total_seconds()))


def _parse_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _source_url(source: Mapping[str, str]) -> str:
    return str(
        source.get("TEEBOTUS_GEMINI_FREE_TIER_LIMITS_URL")
        or source.get("GEMINI_FREE_TIER_LIMITS_URL")
        or source.get("TEEBOTUS_GEMINI_FREE_TIER_SOURCE_URL")
        or DEFAULT_GEMINI_FREE_TIER_LIMIT_SOURCE_URL
    ).strip()


def _refresh_env(source: Mapping[str, str], suffix: str) -> str:
    for prefix in ("TEEBOTUS_GEMINI_FREE_TIER_REFRESH", "GEMINI_FREE_TIER_REFRESH"):
        value = str(source.get(f"{prefix}_{suffix}", "") or "").strip()
        if value:
            return value
    return ""


def _refresh_interval_seconds(source: Mapping[str, str]) -> int:
    return _parse_nonnegative_int(
        _refresh_env(source, "INTERVAL_SECONDS") or str(source.get("TEEBOTUS_GEMINI_FREE_TIER_REFRESH_SECONDS") or ""),
        default=DEFAULT_GEMINI_FREE_TIER_REFRESH_INTERVAL_SECONDS,
    )


def _fetch_timeout_seconds(source: Mapping[str, str]) -> int:
    return max(
        1,
        _parse_nonnegative_int(
            _refresh_env(source, "TIMEOUT_SECONDS"),
            default=DEFAULT_GEMINI_FREE_TIER_FETCH_TIMEOUT_SECONDS,
        ),
    )


def _refresh_relevant_for_runtime(source: Mapping[str, str], *, instance_names: tuple[str, ...]) -> bool:
    if not _is_default_gemini_limit_source(_source_url(source)):
        return True
    direct_names = (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "TEEBOTUS_GEMINI_API_KEY_RING",
        "GEMINI_API_KEY_RING",
        "TEEBOTUS_GEMINI_API_KEYS",
        "GEMINI_API_KEYS",
    )
    if any(str(source.get(name, "") or "").strip() for name in direct_names):
        return True
    if any(key.startswith(("TEEBOTUS_GEMINI_API_KEYS_ACCOUNT_", "GEMINI_API_KEYS_ACCOUNT_")) for key in source):
        return True
    for instance_name in instance_names:
        token = _env_token(instance_name)
        if not token:
            continue
        prefixes = (
            f"TEEBOTUS_GEMINI_API_KEYS_{token}_ACCOUNT_",
            f"GEMINI_API_KEYS_{token}_ACCOUNT_",
            f"TEEBOTUS_GEMINI_API_KEY_RING_{token}",
            f"GEMINI_API_KEY_RING_{token}",
        )
        if any(str(source.get(prefix, "") or "").strip() for prefix in prefixes if not prefix.endswith("_")):
            return True
        if any(key.startswith(prefix) for key in source for prefix in prefixes if prefix.endswith("_")):
            return True
    return False


def _parse_bool_env(value: str, *, default: bool) -> bool:
    text = str(value or "").strip().casefold()
    if not text:
        return default
    if text in {"1", "true", "yes", "ja", "on", "enabled", "an"}:
        return True
    if text in {"0", "false", "no", "nein", "off", "disabled", "aus"}:
        return False
    return default


def _parse_nonnegative_int(value: str, *, default: int) -> int:
    try:
        parsed = int(str(value or "").strip())
    except ValueError:
        return default
    return parsed if parsed >= 0 else default


def _env_token(value: str) -> str:
    token = "".join(char if char.isalnum() else "_" for char in str(value or "").strip().upper())
    return "_".join(part for part in token.split("_") if part)


def _display_url(value: str) -> str:
    text = str(value or "").strip()
    split = urlsplit(text)
    if split.scheme in {"http", "https"}:
        host = split.hostname or ""
        port = f":{split.port}" if split.port else ""
        path = split.path or "/"
        return f"{host}{port}{path}"
    if split.scheme == "file":
        return "file://<local>"
    if text:
        return "<local-file>"
    return "<none>"


def _safe_detail(value: str) -> str:
    text = str(value or "").replace("\n", " ").replace("\r", " ")
    text = re.sub(r"([?&](?:key|api_key|token|access_token|auth_token)=)[^&\s]+", r"\1<redacted>", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()[:240]


def _status_token(value: str) -> str:
    text = str(value or "").strip() or "<none>"
    return re.sub(r"\s+", "_", text)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "DEFAULT_GEMINI_FREE_TIER_LIMIT_SOURCE_URL",
    "GeminiFreeTierRefreshResult",
    "cached_gemini_free_tier_limit_values",
    "gemini_free_tier_limit_cache_path",
    "gemini_free_tier_limit_status_line",
    "normalize_gemini_limit_model_name",
    "parse_gemini_free_tier_limits_payload",
    "refresh_gemini_free_tier_limits_if_due",
    "start_gemini_free_tier_limit_refresh_background",
]
