from __future__ import annotations

import json
import shutil
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from TeeBotus.benchmarks.core import BenchmarkResult, result
from TeeBotus.embedding import FakeEmbeddingProvider, KeywordRerankerProvider
from TeeBotus.runtime.bibliothekar import BibliothekarStore
from TeeBotus.runtime.bibliothekar_service import (
    BibliothekarQuery,
    BibliothekarService,
    HaystackBibliothekarBackend,
    LlamaIndexBibliothekarBackend,
    LocalBibliothekarBackend,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def benchmark_bibliothekar_local_query(*, iterations: int) -> BenchmarkResult:
    with tempfile.TemporaryDirectory(prefix="teebotus-bench-library-") as tmp:
        root = Path(tmp)
        library_dir = root / "instances" / "Bench" / "data" / "Bibliothek"
        _copy_benchmark_books(library_dir)
        store = BibliothekarStore("Bench", root / "instances")
        rebuild_ms = _timed_ms(store.rebuild)
        service = BibliothekarService(LocalBibliothekarBackend(store))
        timings = [_timed_ms(lambda: service.search("Therapie Schlaf", max_chunks=2)) for _ in range(iterations)]
        selection = service.search("Therapie Schlaf", max_chunks=2)
        index = json.loads(store.index_path.read_text(encoding="utf-8"))
        return result(
            name="bibliothekar_local_query",
            category="bibliothekar",
            iterations=iterations,
            total_ms=rebuild_ms + sum(timings),
            payload_bytes=store.chunks_path.stat().st_size,
            index_bytes=store.index_path.stat().st_size,
            details={
                "fixture": "tests/fixtures/books",
                "documents": len(index.get("documents", {})),
                "chunks": int(index.get("chunk_count") or 0),
                "median_query_ms": statistics.median(timings),
                **_bibliothekar_payload_details(selection.prompt_text),
            },
        )


def benchmark_bibliothekar_llamaindex_fake_query(*, iterations: int) -> BenchmarkResult:
    with tempfile.TemporaryDirectory(prefix="teebotus-bench-llamaindex-") as tmp:
        root = Path(tmp)
        library_dir = root / "instances" / "Bench" / "data" / "Bibliothek"
        _copy_benchmark_books(library_dir)
        backend = LlamaIndexBibliothekarBackend(
            instance_name="Bench",
            instances_dir=root / "instances",
            query_engine_factory=lambda source_store: _BenchmarkLlamaIndexQueryEngine(source_store),
        )
        rebuild_ms = _timed_ms(backend.rebuild)
        timings = [
            _timed_ms(
                lambda: backend.search(
                    BibliothekarQuery(
                        text="Therapie Schlaf",
                        max_chunks=2,
                        max_prompt_chars=5000,
                        max_quote_chars=500,
                    )
                )
            )
            for _ in range(iterations)
        ]
        selection = backend.search(
            BibliothekarQuery(
                text="Therapie Schlaf",
                max_chunks=2,
                max_prompt_chars=5000,
                max_quote_chars=500,
            )
        )
        private_filter_selection = backend.search(
            BibliothekarQuery(
                text="Therapie Schlaf",
                filters={"account_id": "private-account-id", "memory_id": "mem_private"},
                max_chunks=2,
                max_prompt_chars=5000,
                max_quote_chars=500,
            )
        )
        fallback_store = backend.fallback_store
        index = json.loads(fallback_store.index_path.read_text(encoding="utf-8"))
        private_filter_prompt = private_filter_selection.prompt_text
        return result(
            name="bibliothekar_llamaindex_fake_query",
            category="bibliothekar",
            iterations=iterations,
            total_ms=rebuild_ms + sum(timings),
            payload_bytes=fallback_store.chunks_path.stat().st_size,
            index_bytes=fallback_store.index_path.stat().st_size,
            note="fake_llamaindex_query_engine",
            details={
                "documents": len(index.get("documents", {})),
                "chunks": int(index.get("chunk_count") or 0),
                "fixture": "tests/fixtures/books",
                "query_engine": "fake_llamaindex_chunks",
                "median_query_ms": statistics.median(timings),
                "private_filter_selected_chunks": len(private_filter_selection.selected_ids),
                "private_filter_payload_leaked": any(marker in private_filter_prompt for marker in ("private-account-id", "mem_private")),
                **_bibliothekar_payload_details(selection.prompt_text),
            },
        )


def benchmark_bibliothekar_haystack_fake_query(*, iterations: int) -> BenchmarkResult:
    with tempfile.TemporaryDirectory(prefix="teebotus-bench-haystack-") as tmp:
        root = Path(tmp)
        library_dir = root / "instances" / "Bench" / "data" / "Bibliothek"
        _copy_benchmark_books(library_dir)
        document_store = _BenchmarkDocumentStore()
        backend = HaystackBibliothekarBackend(
            instance_name="Bench",
            instances_dir=root / "instances",
            collection="bench_books",
            document_store_factory=lambda: document_store,
            document_class=_BenchmarkDocument,
        )
        rebuild_ms = _timed_ms(backend.rebuild)
        timings = [
            _timed_ms(
                lambda: backend.search(
                    BibliothekarQuery(
                        text="Therapie Schlaf",
                        max_chunks=2,
                        max_prompt_chars=5000,
                        max_quote_chars=500,
                    )
                )
            )
            for _ in range(iterations)
        ]
        selection = backend.search(
            BibliothekarQuery(
                text="Therapie Schlaf",
                max_chunks=2,
                max_prompt_chars=5000,
                max_quote_chars=500,
            )
        )
        private_filter_selection = backend.search(
            BibliothekarQuery(
                text="Therapie Schlaf",
                filters={"account_id": "private-account-id", "memory_id": "mem_private"},
                max_chunks=2,
                max_prompt_chars=5000,
                max_quote_chars=500,
            )
        )
        fallback_store = backend.fallback_store
        index = json.loads(fallback_store.index_path.read_text(encoding="utf-8"))
        private_filter_prompt = private_filter_selection.prompt_text
        return result(
            name="bibliothekar_haystack_fake_query",
            category="bibliothekar",
            iterations=iterations,
            total_ms=rebuild_ms + sum(timings),
            payload_bytes=fallback_store.chunks_path.stat().st_size,
            index_bytes=fallback_store.index_path.stat().st_size,
            note="fake_haystack_document_store",
            details={
                "documents": len(index.get("documents", {})),
                "chunks": int(index.get("chunk_count") or 0),
                "fixture": "tests/fixtures/books",
                "document_store_documents": len(document_store.documents),
                "median_query_ms": statistics.median(timings),
                "private_filter_selected_chunks": len(private_filter_selection.selected_ids),
                "private_filter_payload_leaked": any(marker in private_filter_prompt for marker in ("private-account-id", "mem_private")),
                **_bibliothekar_payload_details(selection.prompt_text),
            },
        )


def benchmark_retrieval_embedding_reranker_matrix(*, iterations: int) -> BenchmarkResult:
    documents = [
        "Schlafhygiene und Tagesstruktur helfen bei depressiver Erschoepfung.",
        "Kaffee und Wetter sind Smalltalk und keine Therapiequelle.",
        "Aktivierung und kurze Spaziergaenge koennen stabilisieren.",
    ]
    query = "Schlaf Therapie Tagesstruktur"
    embedding_providers = [
        FakeEmbeddingProvider(model_name="intfloat/multilingual-e5-small", dimensions=16),
        FakeEmbeddingProvider(model_name="intfloat/multilingual-e5-base", dimensions=16),
        FakeEmbeddingProvider(model_name="BAAI/bge-m3", dimensions=16),
    ]
    embedding_timings: list[float] = []
    model_rankings: dict[str, list[int]] = {}
    for provider in embedding_providers:

        def run_provider(provider=provider) -> None:
            query_vector = provider.embed_text(query)
            doc_vectors = provider.embed_texts(documents, purpose="retrieval_benchmark")
            ranked = sorted(range(len(documents)), key=lambda index: _vector_cosine(query_vector, doc_vectors[index]), reverse=True)
            model_rankings[provider.model_name] = ranked

        embedding_timings.extend(_timed_ms(run_provider) for _ in range(iterations))

    reranker = KeywordRerankerProvider(model_name="BAAI/bge-reranker-v2-m3")
    reranker_timings = [_timed_ms(lambda: reranker.rerank(query, documents, top_k=2)) for _ in range(iterations)]
    reranked = reranker.rerank(query, documents, top_k=2)
    without_reranker_top = model_rankings.get("BAAI/bge-m3", [])[:2]
    with_reranker_top = [item.index for item in reranked]

    backend_timings: dict[str, float] = {}
    backend_selected: dict[str, int] = {}
    with tempfile.TemporaryDirectory(prefix="teebotus-bench-retrieval-") as tmp:
        root = Path(tmp)
        library_dir = root / "instances" / "Bench" / "data" / "Bibliothek"
        _copy_benchmark_books(library_dir)
        store = BibliothekarStore("Bench", root / "instances")
        local_backend = LocalBibliothekarBackend(store)
        local_backend.rebuild()
        backend_timings["local"] = sum(_timed_ms(lambda: local_backend.search(BibliothekarQuery(text=query, max_chunks=2))) for _ in range(iterations))
        backend_selected["local"] = len(local_backend.search(BibliothekarQuery(text=query, max_chunks=2)).selected_ids)

        document_store = _BenchmarkDocumentStore()
        haystack_backend = HaystackBibliothekarBackend(
            instance_name="Bench",
            instances_dir=root / "instances",
            collection="bench_books",
            document_store_factory=lambda: document_store,
            document_class=_BenchmarkDocument,
        )
        haystack_backend.rebuild()
        backend_timings["haystack_fake"] = sum(_timed_ms(lambda: haystack_backend.search(BibliothekarQuery(text=query, max_chunks=2))) for _ in range(iterations))
        backend_selected["haystack_fake"] = len(haystack_backend.search(BibliothekarQuery(text=query, max_chunks=2)).selected_ids)

        llama_backend = LlamaIndexBibliothekarBackend(
            instance_name="Bench",
            instances_dir=root / "instances",
            query_engine_factory=lambda source_store: _BenchmarkLlamaIndexQueryEngine(source_store),
        )
        backend_timings["llamaindex_fake"] = sum(_timed_ms(lambda: llama_backend.search(BibliothekarQuery(text=query, max_chunks=2))) for _ in range(iterations))
        backend_selected["llamaindex_fake"] = len(llama_backend.search(BibliothekarQuery(text=query, max_chunks=2)).selected_ids)

        payload_bytes = store.chunks_path.stat().st_size
        index_bytes = store.index_path.stat().st_size

    ok = (
        {"intfloat/multilingual-e5-small", "intfloat/multilingual-e5-base", "BAAI/bge-m3"}.issubset(model_rankings)
        and reranked
        and all(count >= 1 for count in backend_selected.values())
    )
    return result(
        name="retrieval_embedding_reranker_matrix",
        category="retrieval",
        iterations=iterations * (len(embedding_providers) + 1 + len(backend_timings)),
        total_ms=sum(embedding_timings) + sum(reranker_timings) + sum(backend_timings.values()),
        ok=ok,
        errors=0 if ok else 1,
        payload_bytes=payload_bytes,
        index_bytes=index_bytes,
        note="local_embedding_reranker_backend_matrix",
        details={
            "usermemory_models": ["intfloat/multilingual-e5-small", "intfloat/multilingual-e5-base"],
            "book_models": ["BAAI/bge-m3", "intfloat/multilingual-e5-base"],
            "model_rankings": model_rankings,
            "reranker": reranker.model_name,
            "reranker_backend": "keyword_overlap_fake",
            "reranker_comparison": {
                "without_reranker_model": "BAAI/bge-m3",
                "without_reranker_top": without_reranker_top,
                "with_reranker_model": reranker.model_name,
                "with_reranker_top": with_reranker_top,
                "changed_order": without_reranker_top != with_reranker_top,
            },
            "reranked_top": with_reranker_top,
            "backend_modes": ["local", "llamaindex_fake", "haystack_fake"],
            "backend_selected": backend_selected,
            "backend_total_ms": backend_timings,
            "network_calls": 0,
            "provider_calls": 0,
        },
    )


def _bibliothekar_payload_details(prompt_text: str) -> dict[str, Any]:
    required_fields = {
        "chunk_id",
        "source_id",
        "file",
        "file_path",
        "file_sha256",
        "file_type",
        "language",
        "locator",
        "license",
        "source_quality",
        "citation_quality",
        "ingested_at",
        "chunk_index",
        "embedding_model",
        "citation_format",
    }
    try:
        payload = json.loads(prompt_text)
    except json.JSONDecodeError:
        return {
            "citation_payload_bytes": len(prompt_text.encode("utf-8")),
            "selected_chunks": 0,
            "has_citation_format": False,
            "citation_required_fields": sorted(required_fields),
            "citation_missing_fields": sorted(required_fields),
            "provenance_fields_complete": False,
        }
    chunks = payload.get("selected_library_chunks") if isinstance(payload, dict) else None
    selected_chunks = chunks if isinstance(chunks, list) else []
    missing_fields = sorted(
        {
            field
            for chunk in selected_chunks
            if isinstance(chunk, dict)
            for field in required_fields
            if field not in chunk or chunk.get(field) in ("", None)
        }
    )
    return {
        "citation_payload_bytes": len(prompt_text.encode("utf-8")),
        "selected_chunks": len(selected_chunks),
        "has_citation_format": all(bool(chunk.get("citation_format")) for chunk in selected_chunks if isinstance(chunk, dict)),
        "citation_required_fields": sorted(required_fields),
        "citation_missing_fields": missing_fields,
        "provenance_fields_complete": bool(selected_chunks) and not missing_fields,
    }


def _vector_cosine(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    numerator = sum(float(a) * float(b) for a, b in zip(left, right))
    left_norm = sum(float(value) * float(value) for value in left) ** 0.5
    right_norm = sum(float(value) * float(value) for value in right) ** 0.5
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def _copy_benchmark_books(destination: Path) -> None:
    source = REPO_ROOT / "tests" / "fixtures" / "books"
    if not source.exists():
        raise FileNotFoundError(f"benchmark fixture directory is missing: {source}")
    destination.mkdir(parents=True, exist_ok=True)
    for path in source.rglob("*"):
        if path.is_file():
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def _timed_ms(func: Callable[[], Any]) -> float:
    start = time.perf_counter()
    func()
    return (time.perf_counter() - start) * 1000


class _BenchmarkDocument:
    def __init__(self, *, content: str, meta: dict[str, Any], id: str | None = None) -> None:
        self.content = content
        self.meta = meta
        self.id = id or str(meta.get("chunk_id", ""))


class _BenchmarkLlamaIndexQueryEngine:
    def __init__(self, source_store: BibliothekarStore) -> None:
        source_store.ensure_current()
        self.chunks = [json.loads(line) for line in source_store.chunks_path.read_text(encoding="utf-8").splitlines()]
        self.queries: list[str] = []

    def search(self, query_text: str) -> list[dict[str, Any]]:
        self.queries.append(query_text)
        return list(self.chunks)


class _BenchmarkDocumentStore:
    def __init__(self) -> None:
        self.documents: list[_BenchmarkDocument] = []

    def write_documents(self, documents: list[_BenchmarkDocument], **_kwargs: Any) -> None:
        by_id = {document.id: document for document in self.documents}
        for document in documents:
            by_id[document.id] = document
        self.documents = list(by_id.values())

    def filter_documents(self, **_kwargs: Any) -> list[_BenchmarkDocument]:
        return list(self.documents)


__all__ = [
    "benchmark_bibliothekar_haystack_fake_query",
    "benchmark_bibliothekar_llamaindex_fake_query",
    "benchmark_bibliothekar_local_query",
    "benchmark_retrieval_embedding_reranker_matrix",
]
