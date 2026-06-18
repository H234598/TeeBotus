from __future__ import annotations

import json
import os
import time
from typing import Any, Callable
from urllib.parse import urlparse

from TeeBotus.benchmarks.core import BenchmarkResult, result
from TeeBotus.embedding import FakeEmbeddingProvider
from TeeBotus.embedding.config import EmbeddingConfig, build_account_memory_embedding_provider
from TeeBotus.runtime.qdrant import check_qdrant_health, format_qdrant_status_line
from TeeBotus.runtime.qdrant_memory import QDRANT_MEMORY_PAYLOAD_SCHEMA_VERSION, QdrantMemoryIndex

_QDRANT_VECTOR_DIMENSION_CANDIDATES = (64, 128, 256, 384, 768, 1024)
_QDRANT_QUANTIZATION_PROFILES = {
    "float32": 4.0,
    "scalar_int8": 1.0,
    "binary": 0.125,
}


def benchmark_qdrant_health_quick(*, iterations: int) -> BenchmarkResult:
    opener = _BenchmarkQdrantOpener()
    lines: list[str] = []
    timings = [
        _timed_ms(lambda: lines.append(format_qdrant_status_line(check_qdrant_health("http://127.0.0.1:6333", opener=opener))))
        for _ in range(iterations)
    ]
    ok = bool(lines) and all("status=reachable" in line for line in lines)
    return result(
        name="qdrant_health_quick",
        category="qdrant",
        iterations=iterations,
        total_ms=sum(timings),
        ok=ok,
        errors=0 if ok else 1,
        payload_bytes=len("\n".join(lines).encode("utf-8")),
        index_bytes=len(json.dumps({"fake_requests": opener.request_count}, ensure_ascii=False).encode("utf-8")),
        note="fake_qdrant_health_no_server",
        details={
            "latest_status": lines[-1] if lines else "",
            "fake_requests": opener.request_count,
            "network_calls": 0,
        },
    )


def benchmark_qdrant_health_live() -> BenchmarkResult:
    target = os.environ.get("TEEBOTUS_QDRANT_URL", "http://127.0.0.1:6333").strip() or "http://127.0.0.1:6333"
    line_holder: list[str] = []
    health_holder: list[Any] = []

    def run_live_check() -> None:
        health = check_qdrant_health(target)
        health_holder.append(health)
        line_holder.append(format_qdrant_status_line(health))

    total_ms = _timed_ms(run_live_check)
    health = health_holder[-1] if health_holder else None
    reachable = str(getattr(health, "status", "") or "") == "reachable"
    reason = "" if reachable else (str(getattr(health, "error", "") or "") or f"qdrant status={getattr(health, 'status', 'unknown')}")
    return result(
        name="qdrant_health_live",
        category="qdrant",
        iterations=1 if reachable else 0,
        total_ms=total_ms,
        ok=reachable,
        skipped=not reachable,
        errors=0,
        payload_bytes=len("\n".join(line_holder).encode("utf-8")),
        index_bytes=len(json.dumps({"status_lines": len(line_holder)}, ensure_ascii=False).encode("utf-8")),
        note="explicit_live_qdrant_health",
        reason=reason,
        mode="live_qdrant",
        details={
            "target": target,
            "latest_status": line_holder[-1] if line_holder else "",
            "network_calls": 1,
            "provider_calls": 0,
            "remote_calls": 0,
        },
    )


def benchmark_qdrant_vector_dimensions_quantization_quick(*, iterations: int) -> BenchmarkResult:
    dimension_profiles: list[dict[str, Any]] = []
    timings: list[float] = []
    repetitions = max(1, int(iterations))

    for dimensions in _QDRANT_VECTOR_DIMENSION_CANDIDATES:
        provider = FakeEmbeddingProvider(dimensions=dimensions)
        query_vector = provider.embed_text("Schlaf Tagesstruktur Termine Depressionsbot")
        memory_vector = provider.embed_text("Tagesstruktur und Schlaf helfen beim Planen von Terminen.")

        def run_dimension_probe() -> None:
            for _ in range(repetitions):
                _benchmark_dot(query_vector, memory_vector)

        total_ms = _timed_ms(run_dimension_probe)
        timings.append(total_ms)
        float32_bytes = int(dimensions * _QDRANT_QUANTIZATION_PROFILES["float32"])
        scalar_int8_bytes = int(dimensions * _QDRANT_QUANTIZATION_PROFILES["scalar_int8"])
        binary_bytes = max(1, int(dimensions * _QDRANT_QUANTIZATION_PROFILES["binary"]))
        dimension_profiles.append(
            {
                "dimensions": dimensions,
                "float32_bytes_per_vector": float32_bytes,
                "scalar_int8_bytes_per_vector": scalar_int8_bytes,
                "binary_bytes_per_vector": binary_bytes,
                "relative_float32_to_64d": round(float32_bytes / (64 * 4), 4),
                "dot_ops_per_search_candidate": dimensions,
                "probe_repetitions": repetitions,
                "probe_total_ms": round(total_ms, 6),
            }
        )

    float32_sizes = [profile["float32_bytes_per_vector"] for profile in dimension_profiles]
    dimension_cost_monotonic = all(
        next_size > current_size
        for current_size, next_size in zip(float32_sizes, float32_sizes[1:])
    )
    storage_ratio_1024_vs_64 = float32_sizes[-1] / float32_sizes[0] if float32_sizes else 0.0
    scalar_int8_ratio = (
        _QDRANT_QUANTIZATION_PROFILES["scalar_int8"] / _QDRANT_QUANTIZATION_PROFILES["float32"]
    )
    binary_ratio = _QDRANT_QUANTIZATION_PROFILES["binary"] / _QDRANT_QUANTIZATION_PROFILES["float32"]
    ok = (
        len(dimension_profiles) == len(_QDRANT_VECTOR_DIMENSION_CANDIDATES)
        and dimension_cost_monotonic
        and storage_ratio_1024_vs_64 == 16.0
        and scalar_int8_ratio == 0.25
        and binary_ratio == 0.03125
    )
    return result(
        name="qdrant_vector_dimensions_quantization_quick",
        category="qdrant",
        iterations=repetitions * len(_QDRANT_VECTOR_DIMENSION_CANDIDATES),
        total_ms=sum(timings),
        ok=ok,
        errors=0 if ok else 1,
        payload_bytes=len(json.dumps(dimension_profiles, ensure_ascii=False).encode("utf-8")),
        index_bytes=len(
            json.dumps(
                {
                    "dimension_candidates": _QDRANT_VECTOR_DIMENSION_CANDIDATES,
                    "quantization_profiles": _QDRANT_QUANTIZATION_PROFILES,
                },
                ensure_ascii=False,
            ).encode("utf-8")
        ),
        note="fake_qdrant_dimension_quantization_no_server",
        mode="local_fake",
        details={
            "dimension_candidates": list(_QDRANT_VECTOR_DIMENSION_CANDIDATES),
            "quantization_profiles": dict(_QDRANT_QUANTIZATION_PROFILES),
            "dimension_profiles": dimension_profiles,
            "storage_ratio_1024_vs_64": storage_ratio_1024_vs_64,
            "scalar_int8_ratio_vs_float32": scalar_int8_ratio,
            "binary_ratio_vs_float32": binary_ratio,
            "dimension_cost_monotonic": dimension_cost_monotonic,
            "estimated_only": True,
            "embedding_provider": "FakeEmbeddingProvider",
            "network_calls": 0,
            "provider_calls": 0,
            "remote_calls": 0,
        },
    )


def benchmark_qdrant_memory_index_quick(*, iterations: int) -> BenchmarkResult:
    opener = _BenchmarkQdrantOpener()
    index = QdrantMemoryIndex(
        url="http://127.0.0.1:6333",
        opener=opener,
        embedding_provider=FakeEmbeddingProvider(dimensions=16),
    )
    account_id = "a" * 128
    selected_ids: list[str] = []

    def run_once(i: int) -> None:
        memory_id = f"mem_bench_{i}"
        index.index_memory(
            instance_name="Bench",
            account_id=account_id,
            entry={
                "id": memory_id,
                "kind": "suicidal_ideation",
                "memory_type": "risk_signal",
                "user_text": "Schlaf und Tagesstruktur helfen beim Planen.",
                "telegram_user_id": "123456",
                "matrix_user_id": "@bench:example.test",
                "signal_source_uuid": "bench-source",
                "importance": 9,
                "salience": 10,
                "created_at": "2026-06-16T10:00:00Z",
                "updated_at": "2026-06-17T10:00:00Z",
                "keywords": ["schlaf", "tagesstruktur"],
            },
        )
        selected_ids.extend(result.memory_id for result in index.search(instance_name="Bench", account_id=account_id, query="Schlaf", limit=3))

    timings = [_timed_ms(lambda i=i: run_once(i)) for i in range(iterations)]
    stored_payloads = [point.get("payload", {}) for point in opener.points.values()]
    serialized_points = json.dumps(opener.points, ensure_ascii=False).casefold()
    cleartext_in_payload = "schlaf und tagesstruktur" in serialized_points or "user_text" in serialized_points
    messenger_identity_in_payload = any(marker in serialized_points for marker in ("telegram", "matrix", "signal_source", "bench-source"))
    account_id_in_payload = account_id in serialized_points
    content_hash_in_payload = "source_sha256" in serialized_points or "keyword_sha256" in serialized_points
    sensitive_metadata_in_payload = any(marker in serialized_points for marker in ("suicidal_ideation", "risk_signal", "2026-06"))
    remote_embedding_blocked = _account_memory_remote_embedding_blocked()
    schema_versions = sorted({payload.get("schema_version") for payload in stored_payloads if isinstance(payload, dict)})
    ok = (
        bool(selected_ids)
        and not cleartext_in_payload
        and not messenger_identity_in_payload
        and not account_id_in_payload
        and not content_hash_in_payload
        and not sensitive_metadata_in_payload
        and remote_embedding_blocked
        and schema_versions == [QDRANT_MEMORY_PAYLOAD_SCHEMA_VERSION]
    )
    return result(
        name="qdrant_memory_index_quick",
        category="qdrant",
        iterations=iterations,
        total_ms=sum(timings),
        ok=ok,
        errors=0 if ok else 1,
        payload_bytes=len(json.dumps(stored_payloads, ensure_ascii=False).encode("utf-8")),
        index_bytes=len(json.dumps({"points": len(opener.points), "selected": len(selected_ids)}, ensure_ascii=False).encode("utf-8")),
        note="fake_qdrant_memory_index_no_cleartext",
        details={
            "points": len(opener.points),
            "selected": len(selected_ids),
            "schema_versions": schema_versions,
            "cleartext_in_payload": cleartext_in_payload,
            "messenger_identity_in_payload": messenger_identity_in_payload,
            "account_id_in_payload": account_id_in_payload,
            "content_hash_in_payload": content_hash_in_payload,
            "sensitive_metadata_in_payload": sensitive_metadata_in_payload,
            "remote_embedding_blocked": remote_embedding_blocked,
            "fake_requests": opener.request_count,
            "network_calls": 0,
        },
    )


class _BenchmarkQdrantResponse:
    def __init__(self, payload: dict[str, Any] | None = None, status: int = 200) -> None:
        self.payload = {} if payload is None else payload
        self.status = status

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def close(self) -> None:
        return None


class _BenchmarkQdrantOpener:
    def __init__(self) -> None:
        self.points: dict[str, dict[str, Any]] = {}
        self.request_count = 0

    def __call__(self, request: Any, *, timeout: float) -> _BenchmarkQdrantResponse:
        if timeout <= 0:
            raise RuntimeError("timeout must be positive")
        self.request_count += 1
        parsed = urlparse(request.full_url)
        body = json.loads(request.data.decode("utf-8")) if getattr(request, "data", None) else {}
        method = request.get_method()
        if parsed.path == "/collections":
            return _BenchmarkQdrantResponse({"result": {"collections": []}})
        if parsed.path.endswith("/points/search") and method == "POST":
            return _BenchmarkQdrantResponse({"result": self._search(body)})
        if parsed.path.endswith("/points/delete") and method == "POST":
            self._delete(body)
            return _BenchmarkQdrantResponse({"result": {"status": "completed"}})
        if parsed.path.endswith("/points") and method == "PUT":
            for point in body.get("points", []):
                if isinstance(point, dict) and point.get("id"):
                    self.points[str(point["id"])] = dict(point)
            return _BenchmarkQdrantResponse({"result": {"status": "completed"}})
        raise RuntimeError(f"unexpected fake qdrant request: {method} {request.full_url}")

    def _search(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        query = body.get("vector", [])
        limit = int(body.get("limit", 5) or 5)
        must = body.get("filter", {}).get("must", []) if isinstance(body.get("filter"), dict) else []
        results: list[dict[str, Any]] = []
        for point_id, point in self.points.items():
            payload = point.get("payload")
            if not isinstance(payload, dict) or not _benchmark_payload_matches(payload, must):
                continue
            results.append({"id": point_id, "score": _benchmark_dot(query, point.get("vector", [])), "payload": payload})
        results.sort(key=lambda item: item["score"], reverse=True)
        return results[:limit]

    def _delete(self, body: dict[str, Any]) -> None:
        points = body.get("points")
        if isinstance(points, list):
            for point_id in points:
                self.points.pop(str(point_id), None)
            return
        must = body.get("filter", {}).get("must", []) if isinstance(body.get("filter"), dict) else []
        for point_id, point in list(self.points.items()):
            payload = point.get("payload")
            if isinstance(payload, dict) and _benchmark_payload_matches(payload, must):
                self.points.pop(point_id, None)


def _benchmark_payload_matches(payload: dict[str, Any], must: list[Any]) -> bool:
    for condition in must:
        if not isinstance(condition, dict):
            continue
        key = condition.get("key")
        match = condition.get("match")
        expected = match.get("value") if isinstance(match, dict) else None
        if payload.get(key) != expected:
            return False
    return True


def _benchmark_dot(left: Any, right: Any) -> float:
    if not isinstance(left, list) or not isinstance(right, list):
        return 0.0
    return float(sum(float(a) * float(b) for a, b in zip(left, right)))


def _account_memory_remote_embedding_blocked() -> bool:
    try:
        build_account_memory_embedding_provider(
            EmbeddingConfig(provider="hf", model_name="intfloat/multilingual-e5-small", dimensions=384)
        )
    except ValueError as exc:
        return "local endpoint" in str(exc)
    return False


def _timed_ms(func: Callable[[], Any]) -> float:
    start = time.perf_counter()
    func()
    return (time.perf_counter() - start) * 1000


__all__ = [
    "benchmark_qdrant_health_live",
    "benchmark_qdrant_health_quick",
    "benchmark_qdrant_memory_index_quick",
    "benchmark_qdrant_vector_dimensions_quantization_quick",
]
