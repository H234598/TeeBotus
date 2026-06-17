from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen

from TeeBotus.llm.hf_pool.redaction import redact_hf_secrets


@dataclass(frozen=True)
class HFPoolModelInfo:
    model: str
    context_length: int | None = None
    supports_tools: bool = False
    supports_structured_output: bool = False
    pricing: Mapping[str, Any] = field(default_factory=dict)
    latency_ms: int | None = None
    throughput_tokens_per_second: float | None = None


@dataclass(frozen=True)
class HFPoolModelsFeed:
    status: str
    source: str = ""
    models: tuple[HFPoolModelInfo, ...] = ()
    error: str = ""


HFPoolModelsOpener = Callable[..., Any]


def fetch_hf_pool_models(
    base_url: str,
    *,
    api_key: str = "",
    timeout_seconds: int = 10,
    opener: HFPoolModelsOpener | None = None,
) -> HFPoolModelsFeed:
    endpoint = _models_endpoint(base_url)
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(endpoint, method="GET", headers=headers)
    try:
        response = (opener or urlopen)(request, timeout=max(1, int(timeout_seconds)))
        status_code = int(getattr(response, "status", getattr(response, "code", 200)) or 200)
        raw = response.read() if hasattr(response, "read") else b"{}"
        close = getattr(response, "close", None)
        if callable(close):
            close()
        if not 200 <= status_code < 300:
            return HFPoolModelsFeed(status="unavailable", source=endpoint, error=f"HTTP {status_code}")
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except Exception as exc:  # noqa: BLE001 - models metadata is optional diagnostics.
        return HFPoolModelsFeed(status="unavailable", source=endpoint, error=redact_hf_secrets(f"{type(exc).__name__}: {exc}"))
    models = parse_hf_pool_models_payload(payload)
    if not models:
        return HFPoolModelsFeed(status="empty", source=endpoint, models=())
    return HFPoolModelsFeed(status="ok", source=endpoint, models=models)


def parse_hf_pool_models_payload(payload: object) -> tuple[HFPoolModelInfo, ...]:
    raw_models = _model_items(payload)
    models: list[HFPoolModelInfo] = []
    for item in raw_models:
        if not isinstance(item, Mapping):
            continue
        model = _first_text(item, "id", "model", "model_id", "name")
        if not model:
            continue
        models.append(
            HFPoolModelInfo(
                model=model,
                context_length=_first_positive_int(
                    item,
                    "context_length",
                    "max_context_length",
                    "context_window",
                    "max_context_window",
                    "max_input_tokens",
                    "max_total_tokens",
                    "max_sequence_length",
                ),
                supports_tools=_supports_capability(item, "tools", "tool_calling", "tool_calls", "function_calling"),
                supports_structured_output=_supports_capability(
                    item,
                    "structured_output",
                    "structured_outputs",
                    "json_schema",
                    "json_mode",
                    "response_format",
                ),
                pricing=_safe_mapping(item.get("pricing")),
                latency_ms=_first_positive_int(item, "latency_ms", "median_latency_ms", "p50_latency_ms", "latency"),
                throughput_tokens_per_second=_first_positive_float(
                    item,
                    "throughput_tokens_per_second",
                    "tokens_per_second",
                    "throughput",
                ),
            )
        )
    return tuple(models)


def model_info_by_id(models: tuple[HFPoolModelInfo, ...] | list[HFPoolModelInfo]) -> dict[str, HFPoolModelInfo]:
    return {model.model: model for model in models if model.model}


def _models_endpoint(base_url: str) -> str:
    base = str(base_url or "https://router.huggingface.co/v1").strip().rstrip("/")
    if base.endswith("/models"):
        return base
    return f"{base}/models"


def _model_items(payload: object) -> list[object]:
    if isinstance(payload, Mapping):
        data = payload.get("data")
        if isinstance(data, list):
            return list(data)
        models = payload.get("models")
        if isinstance(models, list):
            return list(models)
        if any(key in payload for key in ("id", "model", "model_id", "name")):
            return [payload]
    if isinstance(payload, list):
        return list(payload)
    return []


def _first_text(item: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        text = str(value or "").strip()
        if text and text.lower() not in {"none", "null"}:
            return text
    return ""


def _first_positive_int(item: Mapping[str, Any], *keys: str) -> int | None:
    for value in _candidate_values(item, keys):
        try:
            parsed = int(float(str(value).strip()))
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return None


def _first_positive_float(item: Mapping[str, Any], *keys: str) -> float | None:
    for value in _candidate_values(item, keys):
        try:
            parsed = float(str(value).strip())
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return None


def _candidate_values(item: Mapping[str, Any], keys: tuple[str, ...]) -> list[object]:
    values: list[object] = []
    for key in keys:
        values.append(item.get(key))
    for nested_key in ("limits", "metadata", "config", "parameters", "capabilities"):
        nested = item.get(nested_key)
        if isinstance(nested, Mapping):
            for key in keys:
                values.append(nested.get(key))
    return values


def _supports_capability(item: Mapping[str, Any], *names: str) -> bool:
    direct_keys = tuple(f"supports_{name}" for name in names) + names
    for value in _candidate_values(item, direct_keys):
        if _truthy(value):
            return True
    capability_names = {name.casefold() for name in names}
    for key in ("capabilities", "features", "supported_features"):
        value = item.get(key)
        if isinstance(value, Mapping):
            for capability_key, capability_value in value.items():
                normalized = str(capability_key or "").strip().casefold()
                if normalized in capability_names or normalized in {f"supports_{name}" for name in capability_names}:
                    if _truthy(capability_value):
                        return True
        elif isinstance(value, list):
            normalized_items = {str(entry or "").strip().casefold() for entry in value}
            if normalized_items.intersection(capability_names):
                return True
            if normalized_items.intersection({f"supports_{name}" for name in capability_names}):
                return True
    return False


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().casefold()
    return text in {"1", "true", "yes", "on", "supported", "available", "enabled"}


def _safe_mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    safe: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, str):
            safe[str(key)] = redact_hf_secrets(item)
        elif isinstance(item, (int, float, bool)) or item is None:
            safe[str(key)] = item
        elif isinstance(item, Mapping):
            safe[str(key)] = _safe_mapping(item)
    return safe
