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
_QDRANT_USERMEMORY_BASELINE_DIMENSIONS = 64
_QDRANT_USERMEMORY_BASELINE_MODEL = "teebotus-account-memory-hash"
_QDRANT_USERMEMORY_SIDE_INDEX_DIMENSIONS = 384
_QDRANT_USERMEMORY_SIDE_INDEX_MODEL = "intfloat/multilingual-e5-small"


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


def benchmark_qdrant_usermemory_384d_side_index_quick(*, iterations: int) -> BenchmarkResult:
    repetitions = max(1, int(iterations))
    entries = _benchmark_usermemory_side_index_entries()
    queries = _benchmark_usermemory_side_index_queries()
    account_id = "b" * 128
    primary_opener = _BenchmarkQdrantOpener()
    side_opener = _BenchmarkQdrantOpener()
    primary_index = QdrantMemoryIndex(
        url="http://127.0.0.1:6333",
        opener=primary_opener,
        embedding_provider=FakeEmbeddingProvider(
            model_name=_QDRANT_USERMEMORY_BASELINE_MODEL,
            dimensions=_QDRANT_USERMEMORY_BASELINE_DIMENSIONS,
        ),
    )
    side_index = QdrantMemoryIndex(
        url="http://127.0.0.1:6333",
        opener=side_opener,
        embedding_provider=FakeEmbeddingProvider(
            model_name=_QDRANT_USERMEMORY_SIDE_INDEX_MODEL,
            dimensions=_QDRANT_USERMEMORY_SIDE_INDEX_DIMENSIONS,
        ),
    )
    timings = {
        "primary_index_ms": 0.0,
        "side_index_ms": 0.0,
        "primary_search_ms": 0.0,
        "side_search_ms": 0.0,
    }
    primary_results: list[dict[str, Any]] = []
    side_results: list[dict[str, Any]] = []
    for _ in range(repetitions):
        timings["primary_index_ms"] += _timed_ms(
            lambda: _benchmark_index_entries(primary_index, account_id=account_id, entries=entries)
        )
        timings["side_index_ms"] += _timed_ms(
            lambda: _benchmark_index_entries(side_index, account_id=account_id, entries=entries)
        )
        latest_primary: list[dict[str, Any]] = []
        latest_side: list[dict[str, Any]] = []
        timings["primary_search_ms"] += _timed_ms(
            lambda: latest_primary.extend(
                _benchmark_search_queries(primary_index, account_id=account_id, queries=queries)
            )
        )
        timings["side_search_ms"] += _timed_ms(
            lambda: latest_side.extend(_benchmark_search_queries(side_index, account_id=account_id, queries=queries))
        )
        primary_results = latest_primary
        side_results = latest_side
    primary_hits = _benchmark_top3_hits(primary_results)
    side_hits = _benchmark_top3_hits(side_results)
    combined_points = {"primary": primary_opener.points, "side": side_opener.points}
    stored_payloads = [
        point.get("payload", {})
        for points in (primary_opener.points, side_opener.points)
        for point in points.values()
    ]
    privacy_flags = _benchmark_qdrant_payload_privacy_flags(combined_points, account_id=account_id)
    embedding_dimensions = sorted(
        {
            payload.get("embedding_dimensions")
            for payload in stored_payloads
            if isinstance(payload, dict) and payload.get("embedding_dimensions")
        }
    )
    schema_versions = sorted({payload.get("schema_version") for payload in stored_payloads if isinstance(payload, dict)})
    primary_bytes = _QDRANT_USERMEMORY_BASELINE_DIMENSIONS * int(_QDRANT_QUANTIZATION_PROFILES["float32"])
    side_bytes = _QDRANT_USERMEMORY_SIDE_INDEX_DIMENSIONS * int(_QDRANT_QUANTIZATION_PROFILES["float32"])
    storage_ratio = side_bytes / primary_bytes
    ok = (
        len(primary_opener.points) == len(entries)
        and len(side_opener.points) == len(entries)
        and embedding_dimensions == [_QDRANT_USERMEMORY_BASELINE_DIMENSIONS, _QDRANT_USERMEMORY_SIDE_INDEX_DIMENSIONS]
        and schema_versions == [QDRANT_MEMORY_PAYLOAD_SCHEMA_VERSION]
        and primary_hits == len(queries)
        and side_hits == len(queries)
        and side_hits >= primary_hits
        and storage_ratio == 6.0
        and not any(privacy_flags.values())
    )
    return result(
        name="qdrant_usermemory_384d_side_index_quick",
        category="qdrant",
        iterations=repetitions * max(1, len(entries) + len(queries)),
        total_ms=sum(timings.values()),
        ok=ok,
        errors=0 if ok else 1,
        payload_bytes=len(json.dumps(stored_payloads, ensure_ascii=False).encode("utf-8")),
        index_bytes=len(json.dumps(combined_points, ensure_ascii=False).encode("utf-8")),
        note="fake_qdrant_384d_usermemory_side_index_no_server",
        mode="local_fake",
        details={
            "baseline_model": _QDRANT_USERMEMORY_BASELINE_MODEL,
            "baseline_dimensions": _QDRANT_USERMEMORY_BASELINE_DIMENSIONS,
            "side_index_model": _QDRANT_USERMEMORY_SIDE_INDEX_MODEL,
            "side_index_dimensions": _QDRANT_USERMEMORY_SIDE_INDEX_DIMENSIONS,
            "side_index_optional": True,
            "side_index_rebuildable": True,
            "embedding_provider": "FakeEmbeddingProvider",
            "fake_embedding_proxy": True,
            "entries": len(entries),
            "queries": len(queries),
            "primary_points": len(primary_opener.points),
            "side_points": len(side_opener.points),
            "primary_top3_hits": primary_hits,
            "side_top3_hits": side_hits,
            "primary_results": primary_results,
            "side_results": side_results,
            "storage_ratio_384d_vs_64d": storage_ratio,
            "primary_float32_bytes_per_vector": primary_bytes,
            "side_float32_bytes_per_vector": side_bytes,
            "side_scalar_int8_bytes_per_vector": int(
                _QDRANT_USERMEMORY_SIDE_INDEX_DIMENSIONS * _QDRANT_QUANTIZATION_PROFILES["scalar_int8"]
            ),
            "side_binary_bytes_per_vector": int(
                _QDRANT_USERMEMORY_SIDE_INDEX_DIMENSIONS * _QDRANT_QUANTIZATION_PROFILES["binary"]
            ),
            "timings": {key: round(value, 6) for key, value in timings.items()},
            "embedding_dimensions": embedding_dimensions,
            "schema_versions": schema_versions,
            **privacy_flags,
            "network_calls": 0,
            "provider_calls": 0,
            "remote_calls": 0,
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


def _benchmark_usermemory_side_index_entries() -> tuple[dict[str, Any], ...]:
    return (
        {
            "id": "mem_sleep_structure",
            "kind": "therapy_goal",
            "memory_type": "semantic",
            "user_text": "Schlaf Tagesstruktur Abendroutine helfen gegen Erschoepfung.",
            "bot_text": "Der Bot soll Schlaf und Tagesstruktur priorisieren.",
            "importance": 8,
            "salience": 9,
            "keywords": ["schlaf", "tagesstruktur", "abendroutine"],
        },
        {
            "id": "mem_activation_walk",
            "kind": "coping_strategy",
            "memory_type": "procedural",
            "user_text": "Bewegung Spaziergang Aktivierung hilft bei Antriebslosigkeit.",
            "bot_text": "Kurze Spaziergaenge koennen als Aktivierungsplan helfen.",
            "importance": 7,
            "salience": 8,
            "keywords": ["bewegung", "spaziergang", "aktivierung"],
        },
        {
            "id": "mem_family_trigger",
            "kind": "trigger",
            "memory_type": "semantic",
            "user_text": "Familienstreit Kritik Konflikt ist ein wiederkehrender Trigger.",
            "bot_text": "Bei Konflikten soll der Bot vorsichtig und stabilisierend reagieren.",
            "importance": 9,
            "salience": 9,
            "keywords": ["familienstreit", "kritik", "trigger"],
        },
        {
            "id": "mem_breathing_panic",
            "kind": "coping_strategy",
            "memory_type": "procedural",
            "user_text": "Atemuebung Panik Anspannung langsam ausatmen beruhigt.",
            "bot_text": "Bei Panik soll eine einfache Atemuebung vorgeschlagen werden.",
            "importance": 8,
            "salience": 8,
            "keywords": ["atemuebung", "panik", "anspannung"],
        },
        {
            "id": "mem_medication_routine",
            "kind": "task",
            "memory_type": "episodic",
            "user_text": "Medikamente Einnahme morgens Erinnerung Termin Apotheke.",
            "bot_text": "Der Bot darf an Medikamentenroutine und Apotheke erinnern.",
            "importance": 8,
            "salience": 7,
            "keywords": ["medikamente", "einnahme", "apotheke"],
        },
    )


def _benchmark_usermemory_side_index_queries() -> tuple[tuple[str, str], ...]:
    return (
        ("schlaf tagesstruktur abendroutine", "mem_sleep_structure"),
        ("bewegung spaziergang aktivierung", "mem_activation_walk"),
        ("familienstreit kritik trigger", "mem_family_trigger"),
        ("atemuebung panik anspannung", "mem_breathing_panic"),
        ("medikamente einnahme apotheke", "mem_medication_routine"),
    )


def _benchmark_index_entries(index: QdrantMemoryIndex, *, account_id: str, entries: tuple[dict[str, Any], ...]) -> list[str]:
    point_ids: list[str] = []
    for entry in entries:
        point_ids.append(index.index_memory(instance_name="Bench", account_id=account_id, entry=entry))
    return point_ids


def _benchmark_search_queries(
    index: QdrantMemoryIndex,
    *,
    account_id: str,
    queries: tuple[tuple[str, str], ...],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for query, expected_id in queries:
        matches = index.search(instance_name="Bench", account_id=account_id, query=query, limit=3)
        top_ids = [match.memory_id for match in matches]
        rows.append(
            {
                "query": query,
                "expected": expected_id,
                "top3": top_ids,
                "top1_hit": bool(top_ids) and top_ids[0] == expected_id,
                "top3_hit": expected_id in top_ids,
                "top_score": round(matches[0].score, 6) if matches else 0.0,
            }
        )
    return rows


def _benchmark_top3_hits(rows: list[dict[str, Any]]) -> int:
    return sum(1 for row in rows if row.get("top3_hit") is True)


def _benchmark_qdrant_payload_privacy_flags(points: Any, *, account_id: str) -> dict[str, bool]:
    serialized = json.dumps(points, ensure_ascii=False).casefold()
    return {
        "cleartext_in_payload": any(
            marker in serialized
            for marker in (
                "schlaf tagesstruktur",
                "bewegung spaziergang",
                "familienstreit kritik",
                "atemuebung panik",
                "medikamente einnahme",
                "user_text",
                "bot_text",
            )
        ),
        "messenger_identity_in_payload": any(
            marker in serialized for marker in ("telegram", "matrix", "signal_source", "bench-source")
        ),
        "account_id_in_payload": account_id in serialized,
        "content_hash_in_payload": "source_sha256" in serialized or "keyword_sha256" in serialized,
        "sensitive_metadata_in_payload": any(
            marker in serialized
            for marker in (
                "suicidal_ideation",
                "risk_signal",
                "therapy_goal",
                "coping_strategy",
                "familienstreit",
            )
        ),
    }


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
    "benchmark_qdrant_usermemory_384d_side_index_quick",
    "benchmark_qdrant_vector_dimensions_quantization_quick",
]
