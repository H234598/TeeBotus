from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from TeeBotus.runtime.accounts import ACCOUNT_MEMORY_EMBEDDING_DIMENSIONS
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
QDRANT_URL_ENV = "TEEBOTUS_QDRANT_URL"
QDRANT_USER_MEMORY_COLLECTION = "teebotus_user_memory"
QDRANT_BIBLIOTHEKAR_COLLECTION = "teebotus_bibliothekar_chunks"
DEFAULT_QDRANT_TIMEOUT_SECONDS = 0.35
MAX_QDRANT_RESPONSE_BYTES = 1_000_000
USER_MEMORY_QDRANT_EMBEDDING_MODEL = "teebotus-account-memory-hash"
USER_MEMORY_QDRANT_EMBEDDING_DIMENSIONS = ACCOUNT_MEMORY_EMBEDDING_DIMENSIONS
BIBLIOTHEKAR_QDRANT_EMBEDDING_MODEL = "BAAI/bge-m3"
BIBLIOTHEKAR_QDRANT_EMBEDDING_DIMENSIONS = 1024
DEFAULT_BIBLIOTHEKAR_EMBEDDING_DIMENSIONS = BIBLIOTHEKAR_QDRANT_EMBEDDING_DIMENSIONS
LOCAL_QDRANT_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
QDRANT_COLLECTION_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,255}$")


class QdrantError(RuntimeError):
    """Controlled Qdrant integration error for optional runtime diagnostics."""


@dataclass(frozen=True)
class QdrantHealth:
    target: str
    status: str
    ok: bool
    error: str = ""


@dataclass(frozen=True)
class QdrantCollectionSpec:
    name: str
    vector_size: int
    distance: str = "Cosine"
    embedding_model: str = ""


@dataclass(frozen=True)
class QdrantCollectionResult:
    name: str
    target: str
    status: str
    ok: bool
    error: str = ""
    actual_vector_size: int | None = None


QdrantOpener = Callable[..., Any]


def resolve_qdrant_url(value: object | None = None, *, env: Mapping[str, str] | None = None) -> str:
    if value is None:
        env_map = os.environ if env is None else env
        value = env_map.get(QDRANT_URL_ENV, DEFAULT_QDRANT_URL)
    raw = str(value or DEFAULT_QDRANT_URL).strip() or DEFAULT_QDRANT_URL
    try:
        parsed = urlparse(raw)
    except ValueError as exc:
        raise ValueError("Qdrant URL must be a valid URL.") from exc
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("Qdrant URL must include scheme and host.")
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Qdrant URL must use http or https.")
    host = (parsed.hostname or "").strip().casefold()
    if host not in LOCAL_QDRANT_HOSTS:
        raise ValueError("Qdrant URL must stay local on 127.0.0.1, localhost or ::1.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Qdrant URL must include a valid port if one is specified.") from exc
    if port is None:
        raise ValueError("Qdrant URL must include an explicit port.")
    if port <= 0:
        raise ValueError("Qdrant URL must include a valid port.")
    if parsed.username or parsed.password:
        raise ValueError("Qdrant URL must not contain credentials.")
    if parsed.query or parsed.fragment:
        raise ValueError("Qdrant URL must not contain query parameters or fragments.")
    if parsed.path not in {"", "/"}:
        raise ValueError("Qdrant URL must be a base URL without a path.")
    return raw.rstrip("/")


def qdrant_display_target(target: str) -> str:
    parsed = urlparse(target)
    host = parsed.hostname or target
    port = f":{parsed.port}" if parsed.port is not None else ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{host}{port}"


def check_qdrant_health(
    url: object | None = None,
    *,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float = DEFAULT_QDRANT_TIMEOUT_SECONDS,
    opener: QdrantOpener | None = None,
) -> QdrantHealth:
    try:
        target = resolve_qdrant_url(url, env=env)
    except ValueError as exc:
        return QdrantHealth(target=str(url or DEFAULT_QDRANT_URL), status="invalid", ok=False, error=str(exc))
    request = Request(f"{target}/collections", headers={"Accept": "application/json"})
    open_url = urlopen if opener is None else opener
    try:
        response = open_url(request, timeout=timeout_seconds)
        status_code = int(getattr(response, "status", getattr(response, "code", 200)) or 200)
        close = getattr(response, "close", None)
        if callable(close):
            close()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return QdrantHealth(target=target, status="unreachable", ok=False, error=_qdrant_error_text(exc))
    except Exception as exc:  # noqa: BLE001 - runtime-status must stay non-fatal for optional Qdrant.
        return QdrantHealth(target=target, status="unreachable", ok=False, error=_qdrant_error_text(exc))
    if 200 <= status_code < 300:
        return QdrantHealth(target=target, status="reachable", ok=True)
    return QdrantHealth(target=target, status="unreachable", ok=False, error=f"HTTP {status_code}")


def format_qdrant_status_line(health: QdrantHealth) -> str:
    line = f"qdrant={qdrant_display_target(health.target)} status={health.status}"
    if not health.ok:
        line += " fallback=keyword_memory_search"
    if health.error:
        line += f" error={health.error}"
    return line


def default_qdrant_collection_specs(
    *,
    user_memory_vector_size: int = USER_MEMORY_QDRANT_EMBEDDING_DIMENSIONS,
    user_memory_embedding_model: str = USER_MEMORY_QDRANT_EMBEDDING_MODEL,
    bibliothekar_vector_size: int = DEFAULT_BIBLIOTHEKAR_EMBEDDING_DIMENSIONS,
    bibliothekar_embedding_model: str = BIBLIOTHEKAR_QDRANT_EMBEDDING_MODEL,
) -> tuple[QdrantCollectionSpec, QdrantCollectionSpec]:
    return (
        QdrantCollectionSpec(
            name=QDRANT_USER_MEMORY_COLLECTION,
            vector_size=_validate_vector_size(user_memory_vector_size),
            embedding_model=str(user_memory_embedding_model or "").strip(),
        ),
        QdrantCollectionSpec(
            name=QDRANT_BIBLIOTHEKAR_COLLECTION,
            vector_size=_validate_vector_size(bibliothekar_vector_size),
            embedding_model=str(bibliothekar_embedding_model or "").strip(),
        ),
    )


def check_collection(
    spec: QdrantCollectionSpec,
    *,
    url: object | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float = DEFAULT_QDRANT_TIMEOUT_SECONDS,
    opener: QdrantOpener | None = None,
) -> QdrantCollectionResult:
    target = resolve_qdrant_url(url, env=env)
    name = _validate_collection_name(spec.name)
    request = Request(
        f"{target}/collections/{quote(name, safe='')}",
        method="GET",
        headers={"Accept": "application/json"},
    )
    open_url = urlopen if opener is None else opener
    try:
        response = open_url(request, timeout=timeout_seconds)
        try:
            status_code = int(getattr(response, "status", getattr(response, "code", 200)) or 200)
            raw = _read_response_body(response)
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
    except HTTPError as exc:
        if exc.code == 404:
            return QdrantCollectionResult(name=name, target=target, status="missing", ok=False, error="HTTP 404")
        return QdrantCollectionResult(name=name, target=target, status="unreachable", ok=False, error=_qdrant_error_text(exc))
    except (URLError, TimeoutError, OSError) as exc:
        return QdrantCollectionResult(name=name, target=target, status="unreachable", ok=False, error=_qdrant_error_text(exc))
    except Exception as exc:  # noqa: BLE001 - Qdrant remains optional and reports controlled failures.
        return QdrantCollectionResult(name=name, target=target, status="unreachable", ok=False, error=_qdrant_error_text(exc))
    if 200 <= status_code < 300:
        payload, payload_error = _collection_payload(raw)
        if payload_error:
            return QdrantCollectionResult(name=name, target=target, status="unavailable", ok=False, error=payload_error)
        actual_vector_size = _collection_vector_size(payload)
        if actual_vector_size is not None and actual_vector_size != spec.vector_size:
            return QdrantCollectionResult(
                name=name,
                target=target,
                status="schema_mismatch",
                ok=False,
                error=f"vector_size expected {spec.vector_size}, got {actual_vector_size}",
                actual_vector_size=actual_vector_size,
            )
        return QdrantCollectionResult(name=name, target=target, status="ready", ok=True)
    if status_code == 404:
        return QdrantCollectionResult(name=name, target=target, status="missing", ok=False, error="HTTP 404")
    return QdrantCollectionResult(name=name, target=target, status="unreachable", ok=False, error=f"HTTP {status_code}")


def check_default_collections(
    *,
    url: object | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float = DEFAULT_QDRANT_TIMEOUT_SECONDS,
    opener: QdrantOpener | None = None,
    specs: tuple[QdrantCollectionSpec, ...] | None = None,
) -> tuple[QdrantCollectionResult, ...]:
    return tuple(
        check_collection(spec, url=url, env=env, timeout_seconds=timeout_seconds, opener=opener)
        for spec in (specs or default_qdrant_collection_specs())
    )


def format_qdrant_collection_status_lines(
    health: QdrantHealth,
    *,
    collection_results: tuple[QdrantCollectionResult, ...] | None = None,
    specs: tuple[QdrantCollectionSpec, ...] | None = None,
) -> tuple[str, ...]:
    effective_specs = specs or default_qdrant_collection_specs()
    spec_by_name = {spec.name: spec for spec in effective_specs}
    if collection_results is None:
        collection_results = tuple(
            QdrantCollectionResult(
                name=spec.name,
                target=health.target,
                status="unavailable",
                ok=False,
                error=health.error if not health.ok else "",
            )
            for spec in effective_specs
        )
    lines: list[str] = []
    for result in collection_results:
        spec = spec_by_name.get(result.name)
        vector_size = f" vector_size={spec.vector_size}" if spec is not None else ""
        embedding_model = f" embedding_model={spec.embedding_model}" if spec is not None and spec.embedding_model else ""
        line = (
            f"qdrant_collection={result.name} target={qdrant_display_target(result.target)} "
            f"status={result.status}{vector_size}{embedding_model}"
        )
        if result.actual_vector_size is not None:
            line += f" actual_vector_size={result.actual_vector_size}"
        if result.error:
            line += f" error={result.error}"
        lines.append(line)
    return tuple(lines)


def ensure_collection(
    spec: QdrantCollectionSpec,
    *,
    url: object | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float = DEFAULT_QDRANT_TIMEOUT_SECONDS,
    opener: QdrantOpener | None = None,
) -> QdrantCollectionResult:
    target = resolve_qdrant_url(url, env=env)
    name = _validate_collection_name(spec.name)
    current = check_collection(spec, url=target, timeout_seconds=timeout_seconds, opener=opener)
    if current.status != "missing":
        return current
    vector_size = _validate_vector_size(spec.vector_size)
    distance = _validate_distance(spec.distance)
    body = json.dumps({"vectors": {"size": vector_size, "distance": distance}}, separators=(",", ":")).encode("utf-8")
    request = Request(
        f"{target}/collections/{quote(name, safe='')}",
        data=body,
        method="PUT",
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    open_url = urlopen if opener is None else opener
    try:
        response = open_url(request, timeout=timeout_seconds)
        status_code = int(getattr(response, "status", getattr(response, "code", 200)) or 200)
        close = getattr(response, "close", None)
        if callable(close):
            close()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return QdrantCollectionResult(name=name, target=target, status="unreachable", ok=False, error=_qdrant_error_text(exc))
    except Exception as exc:  # noqa: BLE001 - Qdrant remains optional and reports controlled failures.
        return QdrantCollectionResult(name=name, target=target, status="unreachable", ok=False, error=_qdrant_error_text(exc))
    if 200 <= status_code < 300:
        return QdrantCollectionResult(name=name, target=target, status="ready", ok=True)
    return QdrantCollectionResult(name=name, target=target, status="unreachable", ok=False, error=f"HTTP {status_code}")


def ensure_default_collections(
    *,
    url: object | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float = DEFAULT_QDRANT_TIMEOUT_SECONDS,
    opener: QdrantOpener | None = None,
    specs: tuple[QdrantCollectionSpec, ...] | None = None,
) -> tuple[QdrantCollectionResult, ...]:
    return tuple(
        ensure_collection(spec, url=url, env=env, timeout_seconds=timeout_seconds, opener=opener)
        for spec in (specs or default_qdrant_collection_specs())
    )


def _read_response_body(response: Any, *, max_bytes: int = MAX_QDRANT_RESPONSE_BYTES) -> bytes:
    read = getattr(response, "read", None)
    if not callable(read):
        return b""
    try:
        raw = read(max_bytes + 1)
    except TypeError:
        raw = read()
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if len(raw) > max_bytes:
        raise QdrantError("Qdrant response too large")
    return raw


def _collection_payload(raw: bytes) -> tuple[dict[str, Any] | None, str]:
    if not raw:
        return None, ""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"invalid JSON: {type(exc).__name__}"
    if not isinstance(payload, dict):
        return None, "unexpected JSON payload"
    return payload, ""


def _collection_vector_size(payload: dict[str, Any] | None) -> int | None:
    if not payload:
        return None
    result = payload.get("result") if isinstance(payload, dict) else None
    config = result.get("config") if isinstance(result, dict) else None
    params = config.get("params") if isinstance(config, dict) else None
    vectors = params.get("vectors") if isinstance(params, dict) else None
    if isinstance(vectors, dict) and "size" in vectors:
        return _optional_positive_int(vectors.get("size"))
    if isinstance(vectors, dict):
        for value in vectors.values():
            if isinstance(value, dict) and "size" in value:
                parsed = _optional_positive_int(value.get("size"))
                if parsed is not None:
                    return parsed
    return None


def _validate_collection_name(value: str) -> str:
    name = str(value or "").strip()
    if not QDRANT_COLLECTION_NAME_RE.fullmatch(name):
        raise ValueError("Qdrant collection name must contain only letters, numbers, underscore, dot or dash.")
    return name


def _validate_vector_size(value: int) -> int:
    size = int(value)
    if size < 1:
        raise ValueError("Qdrant vector size must be positive.")
    return size


def _optional_positive_int(value: object) -> int | None:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _validate_distance(value: str) -> str:
    distance = str(value or "Cosine").strip()
    allowed = {"Cosine", "Euclid", "Dot", "Manhattan"}
    normalized = {item.casefold(): item for item in allowed}
    resolved = normalized.get(distance.casefold())
    if resolved is None:
        raise ValueError("Qdrant distance must be Cosine, Euclid, Dot or Manhattan.")
    return resolved


def _qdrant_error_text(exc: BaseException) -> str:
    reason = getattr(exc, "reason", "")
    if reason:
        return str(reason)
    return str(exc) or exc.__class__.__name__
