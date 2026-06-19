#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from TeeBotus.embedding import EmbeddingProvider, FakeEmbeddingProvider, check_embedding_provider  # noqa: E402
from TeeBotus.embedding.config import EmbeddingConfig, build_account_memory_embedding_provider  # noqa: E402
from TeeBotus.runtime.qdrant import resolve_qdrant_url  # noqa: E402


@dataclass(frozen=True)
class MemoryCase:
    memory_id: str
    text: str
    queries: tuple[str, ...]


CASES: tuple[MemoryCase, ...] = (
    MemoryCase(
        "mem_sleep_evening",
        "Der User profitiert von einer ruhigen Abendroutine, regelmaessigem Schlaf und weniger Bildschirmzeit vor dem Einschlafen.",
        (
            "Was hilft mir abends runterzukommen?",
            "Woran soll mich der Bot erinnern, wenn ich wieder zu spaet schlafen gehe?",
        ),
    ),
    MemoryCase(
        "mem_activation_walk",
        "Bei Antriebslosigkeit helfen kurze Spaziergaenge, kleine Aktivierungsschritte und danach eine einfache Belohnung.",
        (
            "Was kann ich tun, wenn ich gar nicht loskomme?",
            "Welche kleine Aufgabe hilft mir gegen den inneren Stillstand?",
        ),
    ),
    MemoryCase(
        "mem_family_conflict",
        "Familienstreit, Kritik und laute Konflikte sind wiederkehrende Trigger; der Bot soll dann langsam und stabilisierend reagieren.",
        (
            "Warum reagiere ich nach Stress mit meiner Familie so stark?",
            "Was weiss der Bot ueber Streit als Ausloeser?",
        ),
    ),
    MemoryCase(
        "mem_breathing_panic",
        "Bei Panik, Herzrasen und starker Anspannung hilft langsam ausatmen, Boden spuern und eine einfache Atemuebung.",
        (
            "Was hilft, wenn mein Puls hochgeht und ich Angst bekomme?",
            "Welche Uebung soll der Bot bei akuter Anspannung vorschlagen?",
        ),
    ),
    MemoryCase(
        "mem_medication_morning",
        "Der User moechte morgens an Medikamente, Wasser und die Apotheke erinnert werden, ohne Druck aufzubauen.",
        (
            "Woran soll ich morgens wegen Tabletten denken?",
            "Was war mit Apotheke und Einnahme geplant?",
        ),
    ),
    MemoryCase(
        "mem_city_weather",
        "Der User wohnt in Leipzig; Wetterchecks sollen maximal alle zwei Stunden erfolgen und in Antworten kurz beruecksichtigt werden.",
        (
            "Welche Stadt soll fuer Wetter genutzt werden?",
            "Wo wohne ich laut Memory?",
        ),
    ),
    MemoryCase(
        "mem_voice_dialect",
        "Der User mag leichten saechsischen Dialekt fuer TTS, wenn eine passende biografische Ortsbindung bestaetigt ist.",
        (
            "Welcher Dialekt passt fuer meine Sprachausgabe?",
            "Was soll beim TTS-Klang regional beachtet werden?",
        ),
    ),
    MemoryCase(
        "mem_privacy_confirmed",
        "Datenschutz wurde bestaetigt; der Bot darf nicht erneut fragen, bis ein Memory-Reset diese Einstellung entfernt.",
        (
            "Muss der Bot nochmal wegen Datenschutz fragen?",
            "Was gilt fuer meine Datenschutzbestaetigung?",
        ),
    ),
    MemoryCase(
        "mem_notifications_loud",
        "Der Bot soll den User bitten, seine Nachrichten laut zu stellen, und spaeter nachfragen, bis bestaetigt oder abgelehnt wurde.",
        (
            "Was war mit Benachrichtigungen auf laut?",
            "Soll der Bot nochmal fragen, ob Nachrichten hoerbar sind?",
        ),
    ),
    MemoryCase(
        "mem_work_focus",
        "Arbeitszeiten sollen aus Onlinezeiten und Schreibverhalten geschaetzt werden, damit proaktive Nachrichten nicht stoeren.",
        (
            "Wann soll der Bot mich tagsueber lieber nicht nerven?",
            "Wie werden Arbeits- und Ruhezeiten beruecksichtigt?",
        ),
    ),
    MemoryCase(
        "mem_library_sources",
        "Der Bibliothekar darf lokale Buecher als Referenz nutzen, abschnittsweise zitieren und muss genaue Quellenangaben liefern.",
        (
            "Darf der Bot aus meinen Buechern zitieren?",
            "Wie sollen Quellen aus der Bibliothek genannt werden?",
        ),
    ),
    MemoryCase(
        "mem_youtube_transcription",
        "YouTube-Links sollen lokal transkribiert werden, ohne OpenAI-Fallback, wenn der User sinngemaess Video zu Text fordert.",
        (
            "Was soll bei einem YouTube-Link mit Bitte um Text passieren?",
            "Soll fuer Videotranskription OpenAI benutzt werden?",
        ),
    ),
)

FILLER_TOPICS = (
    "Kueche Einkauf Rezept Suppe Vorrat Wochenende",
    "Linux Fenster Monitor Tastatur Neustart Paket Update",
    "Garten Balkon Pflanzen Giessen Erde Sonne",
    "Musik Playlist Aufnahme Lautstaerke Kopfhoerer",
    "Fahrrad Reifen Licht Strecke Bahnhof",
    "Projekt Plan Review Dokumentation Testlauf",
    "Haushalt Waesche Geschirr Staubsaugen Kalender",
    "Finanzen Rechnung Konto Steuer Beleg",
    "Leseliste Roman Kapitel Notiz Regal",
    "Spielstand Karte Level Puzzle Pause",
)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    sizes = _positive_ints(args.sizes)
    dimensions = _positive_ints(args.dimensions)
    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    provider_specs = _provider_specs(dimensions, env=os.environ)
    provider_health = [_provider_health(spec) for spec in provider_specs]
    local_results: list[dict[str, Any]] = []
    qdrant_results: list[dict[str, Any]] = []
    for spec in provider_specs:
        try:
            provider = _build_provider(spec)
        except Exception as exc:  # noqa: BLE001 - benchmark report should contain bad optional configs.
            local_results.append(_provider_skipped_result(spec, reason=f"provider config failed: {exc}"))
            continue
        health = check_embedding_provider(provider, purpose="semantic-index-benchmark")
        if not health.ok:
            local_results.append(_provider_skipped_result(spec, reason=health.error or health.status))
            continue
        for size in sizes:
            if spec["kind"] == "real_local" and size > args.real_provider_max_size:
                local_results.append(_provider_skipped_result(spec, size=size, reason="above real-provider max size"))
                continue
            local_results.append(_benchmark_local(provider, spec=spec, size=size, batch_size=args.batch_size))
    if args.live_qdrant:
        qdrant_results = _benchmark_qdrant(
            provider_specs=provider_specs,
            sizes=sizes,
            qdrant_max_size=max(1, int(args.qdrant_max_size)),
            qdrant_url=args.qdrant_url,
            batch_size=args.qdrant_batch_size,
            run_id=run_id,
            cleanup=not args.keep_qdrant_collections,
        )
    else:
        qdrant_results.append({"status": "skipped", "reason": "live qdrant disabled"})
    report = {
        "schema_version": 1,
        "generated_at": generated_at,
        "requested_sizes": sizes,
        "requested_dimensions": dimensions,
        "cases": len(CASES),
        "queries": sum(len(case.queries) for case in CASES),
        "provider_health": provider_health,
        "local_recall_latency": local_results,
        "qdrant_recall_latency_quantization": qdrant_results,
        "notes": [
            "Hash provider is deterministic and local but not semantic; it exposes synonym/paraphrase misses.",
            "SentenceTransformer provider is real local inference and local-cache-only by default.",
            "TEI/OpenAI-compatible embedding endpoints must stay on localhost for account-memory use.",
            "Qdrant benchmark uses temporary collections and excludes cleartext payloads beyond benchmark memory IDs.",
        ],
    }
    json_path = output_dir / f"TeeBotus_semantic_index_benchmark_{run_id}.json"
    md_path = output_dir / f"TeeBotus_semantic_index_benchmark_{run_id}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(_render_markdown(report, json_path=json_path), encoding="utf-8")
    print(f"wrote {md_path}")
    print(f"wrote {json_path}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark TeeBotus semantic usermemory side indexes.")
    parser.add_argument("--output-dir", default="/home/teladi/Downloads")
    parser.add_argument("--sizes", type=int, nargs="+", default=[1000, 10000, 100000])
    parser.add_argument("--dimensions", type=int, nargs="+", default=[64, 384, 1024])
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--real-provider-max-size", type=int, default=100000)
    parser.add_argument("--live-qdrant", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--qdrant-url", default=os.environ.get("TEEBOTUS_QDRANT_URL", "http://127.0.0.1:6333"))
    parser.add_argument("--qdrant-max-size", type=int, default=100000)
    parser.add_argument("--qdrant-batch-size", type=int, default=128)
    parser.add_argument("--keep-qdrant-collections", action="store_true")
    return parser


def _provider_specs(dimensions: Iterable[int], *, env: dict[str, str]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for dimension in dimensions:
        specs.append(
            {
                "label": f"hash_{dimension}d",
                "kind": "hash",
                "provider": "hash",
                "model": f"teebotus-account-memory-hash-{dimension}d",
                "dimensions": int(dimension),
            }
        )
    if 384 in set(dimensions):
        specs.append(
            {
                "label": "local_sentence_transformer_384d",
                "kind": "real_local",
                "provider": env.get("TEEBOTUS_MEMORY_384D_PROVIDER", "sentence-transformers"),
                "model": env.get("TEEBOTUS_MEMORY_384D_MODEL", "sentence-transformers/all-MiniLM-L6-v2"),
                "dimensions": 384,
                "endpoint": env.get("TEEBOTUS_MEMORY_384D_ENDPOINT", ""),
            }
        )
    if 1024 in set(dimensions):
        specs.append(
            {
                "label": "local_sentence_transformer_1024d",
                "kind": "real_local",
                "provider": env.get("TEEBOTUS_MEMORY_1024D_PROVIDER", "sentence-transformers"),
                "model": env.get("TEEBOTUS_MEMORY_1024D_MODEL", "BAAI/bge-m3"),
                "dimensions": 1024,
                "endpoint": env.get("TEEBOTUS_MEMORY_1024D_ENDPOINT", ""),
            }
        )
    return specs


def _provider_health(spec: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        provider = _build_provider(spec)
    except Exception as exc:  # noqa: BLE001 - surface optional provider config errors.
        return {
            "label": spec["label"],
            "provider": spec["provider"],
            "model": spec["model"],
            "dimensions": spec["dimensions"],
            "kind": spec["kind"],
            "status": "unavailable",
            "ok": False,
            "error": f"provider config failed: {exc}",
            "health_ms": round((time.perf_counter() - started) * 1000, 3),
        }
    health = check_embedding_provider(provider, purpose="semantic-index-health")
    return {
        "label": spec["label"],
        "provider": spec["provider"],
        "model": spec["model"],
        "dimensions": spec["dimensions"],
        "kind": spec["kind"],
        "status": health.status,
        "ok": health.ok,
        "error": health.error,
        "health_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def _build_provider(spec: dict[str, Any]) -> EmbeddingProvider:
    if spec["provider"] == "hash":
        return FakeEmbeddingProvider(model_name=spec["model"], dimensions=int(spec["dimensions"]))
    return build_account_memory_embedding_provider(
        EmbeddingConfig(
            provider=str(spec["provider"]),
            model_name=str(spec["model"]),
            dimensions=int(spec["dimensions"]),
            endpoint=str(spec.get("endpoint") or ""),
        )
    )


def _provider_skipped_result(spec: dict[str, Any], *, size: int = 0, reason: str) -> dict[str, Any]:
    return {
        "status": "skipped",
        "provider_label": spec["label"],
        "provider": spec["provider"],
        "model": spec["model"],
        "dimensions": spec["dimensions"],
        "size": size,
        "reason": reason,
    }


def _benchmark_local(provider: EmbeddingProvider, *, spec: dict[str, Any], size: int, batch_size: int) -> dict[str, Any]:
    ids, texts = _dataset(size)
    queries = _queries()
    started = time.perf_counter()
    matrix = _embed_matrix(provider, texts, batch_size=batch_size)
    rebuild_ms = (time.perf_counter() - started) * 1000
    query_timings: list[float] = []
    hits = {1: 0, 3: 0, 5: 0}
    top_examples: list[dict[str, Any]] = []
    id_to_position = {memory_id: index for index, memory_id in enumerate(ids)}
    for query_text, expected_id in queries:
        query_vector = _embed_matrix(provider, [query_text], batch_size=1)[0]
        started_query = time.perf_counter()
        scores = matrix @ query_vector
        top_positions = _top_k_positions(scores, k=5)
        query_timings.append((time.perf_counter() - started_query) * 1000)
        top_ids = [ids[position] for position in top_positions]
        for k in hits:
            if expected_id in top_ids[:k]:
                hits[k] += 1
        if len(top_examples) < 6:
            top_examples.append(
                {
                    "query": query_text,
                    "expected": expected_id,
                    "expected_position": id_to_position.get(expected_id, -1),
                    "top5": top_ids,
                    "top_score": round(float(scores[top_positions[0]]), 6) if len(top_positions) else 0.0,
                }
            )
    total_queries = len(queries)
    result = {
        "status": "ok",
        "backend": "local_numpy",
        "provider_label": spec["label"],
        "provider": spec["provider"],
        "model": spec["model"],
        "dimensions": int(spec["dimensions"]),
        "size": int(size),
        "entries": len(ids),
        "queries": total_queries,
        "rebuild_ms": round(rebuild_ms, 3),
        "query_median_ms": round(_median(query_timings), 4),
        "query_p95_ms": round(_p95(query_timings), 4),
        "recall_at_1": round(hits[1] / total_queries, 4),
        "recall_at_3": round(hits[3] / total_queries, 4),
        "recall_at_5": round(hits[5] / total_queries, 4),
        "float32_vector_bytes": int(size * int(spec["dimensions"]) * 4),
        "top_examples": top_examples,
    }
    del matrix
    gc.collect()
    return result


def _benchmark_qdrant(
    *,
    provider_specs: list[dict[str, Any]],
    sizes: list[int],
    qdrant_max_size: int,
    qdrant_url: str,
    batch_size: int,
    run_id: str,
    cleanup: bool,
) -> list[dict[str, Any]]:
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.http import models
    except Exception as exc:  # noqa: BLE001 - optional benchmark dependency.
        return [{"status": "skipped", "reason": f"qdrant_client unavailable: {exc}"}]
    try:
        target = resolve_qdrant_url(qdrant_url)
        client = QdrantClient(url=target, timeout=120)
        client.get_collections()
    except Exception as exc:  # noqa: BLE001 - live qdrant is optional.
        return [{"status": "skipped", "reason": f"qdrant unavailable: {exc}", "qdrant_url": qdrant_url}]
    results: list[dict[str, Any]] = []
    for spec in provider_specs:
        if spec["kind"] != "hash":
            try:
                candidate_provider = _build_provider(spec)
            except Exception as exc:  # noqa: BLE001 - optional provider config.
                results.append(_provider_skipped_result(spec, reason=f"provider config failed for qdrant: {exc}"))
                continue
            health = check_embedding_provider(candidate_provider, purpose="qdrant-semantic-index-health")
            if not health.ok:
                results.append(_provider_skipped_result(spec, reason=f"provider unavailable for qdrant: {health.error or health.status}"))
                continue
            provider = candidate_provider
        else:
            provider = _build_provider(spec)
        for size in sizes:
            if size > qdrant_max_size:
                results.append(_provider_skipped_result(spec, size=size, reason="above qdrant max size"))
                continue
            for quantized in (False, True):
                results.append(
                    _benchmark_qdrant_collection(
                        client=client,
                        models=models,
                        provider=provider,
                        spec=spec,
                        size=size,
                        batch_size=batch_size,
                        quantized=quantized,
                        run_id=run_id,
                        cleanup=cleanup,
                    )
                )
    return results


def _benchmark_qdrant_collection(
    *,
    client: Any,
    models: Any,
    provider: EmbeddingProvider,
    spec: dict[str, Any],
    size: int,
    batch_size: int,
    quantized: bool,
    run_id: str,
    cleanup: bool,
) -> dict[str, Any]:
    collection = f"teebotus_bench_mem_{int(spec['dimensions'])}d_{size}_{'int8' if quantized else 'float'}_{run_id}".lower()
    ids, texts = _dataset(size)
    queries = _queries()
    try:
        _create_qdrant_collection(client, models, collection, int(spec["dimensions"]), quantized=quantized)
    except Exception as exc:  # noqa: BLE001 - collection config can vary by Qdrant version.
        return {
            "status": "skipped",
            "backend": "qdrant",
            "collection": collection,
            "quantized": quantized,
            "provider_label": spec["label"],
            "dimensions": spec["dimensions"],
            "size": size,
            "reason": f"collection create failed: {exc}",
        }
    try:
        started = time.perf_counter()
        point_count = _upsert_qdrant_points(client, models, collection, provider, ids, texts, batch_size=batch_size)
        rebuild_ms = (time.perf_counter() - started) * 1000
        hits = {1: 0, 3: 0, 5: 0}
        query_timings: list[float] = []
        top_examples: list[dict[str, Any]] = []
        for query_text, expected_id in queries:
            query_vector = provider.embed_text(query_text)
            params = None
            if quantized:
                params = models.SearchParams(
                    quantization=models.QuantizationSearchParams(ignore=False, rescore=True, oversampling=2.0)
                )
            started_query = time.perf_counter()
            response = client.query_points(
                collection_name=collection,
                query=query_vector,
                search_params=params,
                limit=5,
                with_payload=True,
                with_vectors=False,
            )
            query_timings.append((time.perf_counter() - started_query) * 1000)
            points = list(getattr(response, "points", []) or [])
            top_ids = [str((getattr(point, "payload", {}) or {}).get("memory_id", "")) for point in points]
            for k in hits:
                if expected_id in top_ids[:k]:
                    hits[k] += 1
            if len(top_examples) < 6:
                top_examples.append(
                    {
                        "query": query_text,
                        "expected": expected_id,
                        "top5": top_ids,
                        "top_score": round(float(getattr(points[0], "score", 0.0)), 6) if points else 0.0,
                    }
                )
        total_queries = len(queries)
        return {
            "status": "ok",
            "backend": "qdrant",
            "collection": collection,
            "quantized": quantized,
            "provider_label": spec["label"],
            "provider": spec["provider"],
            "model": spec["model"],
            "dimensions": int(spec["dimensions"]),
            "size": int(size),
            "points": point_count,
            "queries": total_queries,
            "rebuild_ms": round(rebuild_ms, 3),
            "query_median_ms": round(_median(query_timings), 4),
            "query_p95_ms": round(_p95(query_timings), 4),
            "recall_at_1": round(hits[1] / total_queries, 4),
            "recall_at_3": round(hits[3] / total_queries, 4),
            "recall_at_5": round(hits[5] / total_queries, 4),
            "float32_vector_bytes": int(size * int(spec["dimensions"]) * 4),
            "top_examples": top_examples,
        }
    except Exception as exc:  # noqa: BLE001 - keep later benchmark rows alive.
        return {
            "status": "error",
            "backend": "qdrant",
            "collection": collection,
            "quantized": quantized,
            "provider_label": spec["label"],
            "dimensions": spec["dimensions"],
            "size": size,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        if cleanup:
            try:
                client.delete_collection(collection)
            except Exception:
                pass


def _create_qdrant_collection(client: Any, models: Any, collection: str, dimensions: int, *, quantized: bool) -> None:
    try:
        client.delete_collection(collection)
    except Exception:
        pass
    quantization_config = None
    if quantized:
        quantization_config = models.ScalarQuantization(
            scalar=models.ScalarQuantizationConfig(type=models.ScalarType.INT8, quantile=0.99, always_ram=True)
        )
    client.create_collection(
        collection_name=collection,
        vectors_config=models.VectorParams(size=int(dimensions), distance=models.Distance.COSINE),
        quantization_config=quantization_config,
    )


def _upsert_qdrant_points(
    client: Any,
    models: Any,
    collection: str,
    provider: EmbeddingProvider,
    ids: list[str],
    texts: list[str],
    *,
    batch_size: int,
) -> int:
    point_count = 0
    for start in range(0, len(ids), max(1, int(batch_size))):
        batch_ids = ids[start : start + batch_size]
        batch_texts = texts[start : start + batch_size]
        vectors = provider.embed_texts(batch_texts, purpose="qdrant-semantic-index-benchmark")
        points = [
            models.PointStruct(
                id=start + offset,
                vector=vector,
                payload={"memory_id": memory_id},
            )
            for offset, (memory_id, vector) in enumerate(zip(batch_ids, vectors))
        ]
        client.upsert(collection_name=collection, points=points, wait=True)
        point_count += len(points)
    return point_count


def _dataset(size: int) -> tuple[list[str], list[str]]:
    ids = [case.memory_id for case in CASES]
    texts = [case.text for case in CASES]
    target = max(len(ids), int(size))
    index = 0
    while len(ids) < target:
        topic = FILLER_TOPICS[index % len(FILLER_TOPICS)]
        ids.append(f"filler_{index:06d}")
        texts.append(f"Unwichtige Nebenmemory {index}: {topic}. Diese Information dient nur als realistische Accountgroesse.")
        index += 1
    return ids[:target], texts[:target]


def _queries() -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for case in CASES:
        for query in case.queries:
            rows.append((query, case.memory_id))
    return rows


def _embed_matrix(provider: EmbeddingProvider, texts: list[str], *, batch_size: int):
    import numpy as np

    dimensions = int(provider.dimensions)
    matrix = np.empty((len(texts), dimensions), dtype=np.float32)
    for start in range(0, len(texts), max(1, int(batch_size))):
        batch = texts[start : start + batch_size]
        vectors = provider.embed_texts(batch, purpose="semantic-index-benchmark")
        if len(vectors) != len(batch):
            raise RuntimeError(f"embedding provider returned {len(vectors)} vectors for {len(batch)} texts")
        matrix[start : start + len(batch)] = np.asarray(vectors, dtype=np.float32)
    return matrix


def _top_k_positions(scores: Any, *, k: int) -> list[int]:
    import numpy as np

    if len(scores) <= k:
        return [int(index) for index in np.argsort(scores)[::-1]]
    candidate_positions = np.argpartition(scores, -k)[-k:]
    ordered = candidate_positions[np.argsort(scores[candidate_positions])[::-1]]
    return [int(index) for index in ordered]


def _positive_ints(values: Iterable[int]) -> list[int]:
    parsed = sorted({max(1, int(value)) for value in values})
    if not parsed:
        raise SystemExit("at least one positive integer is required")
    return parsed


def _median(values: list[float]) -> float:
    return float(statistics.median(values)) if values else 0.0


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95)))
    return float(ordered[index])


def _render_markdown(report: dict[str, Any], *, json_path: Path) -> str:
    lines: list[str] = [
        "# TeeBotus Semantic Memory Index Benchmark",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- json: `{json_path}`",
        f"- requested_sizes: `{report['requested_sizes']}`",
        f"- requested_dimensions: `{report['requested_dimensions']}`",
        f"- paraphrased_queries: `{report['queries']}`",
        "",
        "## Provider Health",
        "",
        "| label | kind | provider | model | dim | status | error |",
        "|---|---:|---|---|---:|---|---|",
    ]
    for item in report["provider_health"]:
        lines.append(
            "| {label} | {kind} | {provider} | {model} | {dimensions} | {status} | {error} |".format(
                label=item["label"],
                kind=item["kind"],
                provider=item["provider"],
                model=item["model"],
                dimensions=item["dimensions"],
                status=item["status"],
                error=_md_cell(item.get("error", "")),
            )
        )
    lines.extend(
        [
            "",
            "## Local Recall And Latency",
            "",
            "| provider | dim | size | status | rebuild ms | q50 query ms | q95 query ms | R@1 | R@3 | R@5 | reason |",
            "|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for item in report["local_recall_latency"]:
        lines.append(_result_row(item))
    lines.extend(
        [
            "",
            "## Qdrant Recall, Latency, Quantization",
            "",
            "| provider | dim | size | quantized | status | rebuild ms | q50 query ms | q95 query ms | R@1 | R@3 | R@5 | reason/error |",
            "|---|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for item in report["qdrant_recall_latency_quantization"]:
        lines.append(_qdrant_row(item))
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- 64D ist der robuste, billige Baseline-Index. Er ist schnell, aber Hash-Embeddings verstehen Synonyme nur begrenzt.",
            "- 384D ist der sinnvolle Nebenindex fuer kompaktere echte Sentence-Transformer-Modelle.",
            "- 1024D ist der reichere Nebenindex fuer grosse Embedding-Modelle wie BGE-M3; er kostet gegenueber 64D etwa 16x Float32-Vektorspeicher.",
            "- Scalar-INT8-Quantisierung senkt den Vektorspeicher grob auf 25 Prozent, muss aber pro Collection gegen Recall und Latenz gemessen werden.",
            "- Echte lokale ST-Provider wurden nur ausgefuehrt, wenn das Modell lokal verfuegbar war; es gibt keinen Cloud-Fallback.",
            "",
        ]
    )
    return "\n".join(lines)


def _result_row(item: dict[str, Any]) -> str:
    return (
        "| {provider_label} | {dimensions} | {size} | {status} | {rebuild_ms} | {query_median_ms} | "
        "{query_p95_ms} | {recall_at_1} | {recall_at_3} | {recall_at_5} | {reason} |"
    ).format(
        provider_label=item.get("provider_label", ""),
        dimensions=item.get("dimensions", ""),
        size=item.get("size", ""),
        status=item.get("status", ""),
        rebuild_ms=item.get("rebuild_ms", ""),
        query_median_ms=item.get("query_median_ms", ""),
        query_p95_ms=item.get("query_p95_ms", ""),
        recall_at_1=item.get("recall_at_1", ""),
        recall_at_3=item.get("recall_at_3", ""),
        recall_at_5=item.get("recall_at_5", ""),
        reason=_md_cell(item.get("reason", "")),
    )


def _qdrant_row(item: dict[str, Any]) -> str:
    reason = item.get("reason") or item.get("error") or ""
    return (
        "| {provider_label} | {dimensions} | {size} | {quantized} | {status} | {rebuild_ms} | "
        "{query_median_ms} | {query_p95_ms} | {recall_at_1} | {recall_at_3} | {recall_at_5} | {reason} |"
    ).format(
        provider_label=item.get("provider_label", ""),
        dimensions=item.get("dimensions", ""),
        size=item.get("size", ""),
        quantized=item.get("quantized", ""),
        status=item.get("status", ""),
        rebuild_ms=item.get("rebuild_ms", ""),
        query_median_ms=item.get("query_median_ms", ""),
        query_p95_ms=item.get("query_p95_ms", ""),
        recall_at_1=item.get("recall_at_1", ""),
        recall_at_3=item.get("recall_at_3", ""),
        recall_at_5=item.get("recall_at_5", ""),
        reason=_md_cell(reason),
    )


def _md_cell(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())
