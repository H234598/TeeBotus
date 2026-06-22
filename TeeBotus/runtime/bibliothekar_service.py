from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlparse

from TeeBotus.runtime.bibliothekar import (
    DEFAULT_MAX_CHUNKS,
    DEFAULT_MAX_PROMPT_CHARS,
    DEFAULT_MAX_QUOTE_CHARS,
    BibliothekarSelection,
    BibliothekarStore,
    _chunk_has_library_source_path,
    _chunk_prompt_item,
    _prompt_payload,
    _rank_chunks,
    _read_chunks,
)
from TeeBotus.runtime.qdrant import QDRANT_BIBLIOTHEKAR_COLLECTION


HAYSTACK_QDRANT_MODULES = ("haystack_integrations.document_stores.qdrant", "qdrant_haystack")
DEFAULT_BIBLIOTHEKAR_COLLECTION = QDRANT_BIBLIOTHEKAR_COLLECTION
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
LOCAL_QDRANT_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
REQUIRED_CITATION_CHUNK_FIELDS = (
    "chunk_id",
    "source_id",
    "title",
    "relative_path",
    "file_path",
    "file_sha256",
    "file_type",
    "language",
    "locator",
    "license",
    "ingested_at",
    "embedding_model",
)
REQUIRED_CITATION_CHUNK_KEYS = (
    *REQUIRED_CITATION_CHUNK_FIELDS,
    "author",
    "page_start",
    "page_end",
    "chapter",
    "section",
    "chunk_index",
)
CHUNK_FILTER_KEYS = frozenset(
    {
        "category",
        "categories",
        "topic",
        "topics",
        "keyword",
        "keywords",
        "file",
        "path",
        "relative_path",
        "file_type",
        "suffix",
        "extension",
        "title",
        "document",
        "document_id",
        "chunk",
        "chunk_id",
    }
)
DOCUMENT_STORE_FILTER_FIELD_MAP = {
    "category": "meta.categories",
    "categories": "meta.categories",
    "topic": "meta.topics",
    "topics": "meta.topics",
    "keyword": "meta.topics",
    "keywords": "meta.topics",
    "file": "meta.relative_path",
    "path": "meta.relative_path",
    "relative_path": "meta.relative_path",
    "file_type": "meta.file_type",
    "suffix": "meta.suffix",
    "extension": "meta.file_type",
    "document": "meta.document_id",
    "document_id": "meta.document_id",
    "chunk": "meta.chunk_id",
    "chunk_id": "meta.chunk_id",
}


@dataclass(frozen=True)
class BibliothekarQuery:
    text: str
    filters: Mapping[str, object] | None = None
    max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS
    max_chunks: int = DEFAULT_MAX_CHUNKS
    max_quote_chars: int = DEFAULT_MAX_QUOTE_CHARS


class BibliothekarBackend(Protocol):
    backend_name: str

    def search(self, query: BibliothekarQuery) -> BibliothekarSelection:
        ...

    def rebuild(self) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class BibliothekarServiceHealth:
    instance_name: str
    backend: str
    status: str
    collection: str = ""
    target: str = ""
    documents: int = 0
    chunks: int = 0
    store: str = ""
    error: str = ""


class LocalBibliothekarBackend:
    backend_name = "local"

    def __init__(self, store: BibliothekarStore) -> None:
        self.store = store

    def search(self, query: BibliothekarQuery) -> BibliothekarSelection:
        if query.max_prompt_chars < 1 or query.max_chunks < 1:
            return BibliothekarSelection("", ())
        if query.filters:
            self.store.ensure_current()
            index = _read_index(self.store.index_path)
            chunks = _apply_chunk_filters(_read_chunks(self.store.chunks_path), query.filters)
            return _selection_from_chunks(index, chunks, query)
        return self.store.select(
            query.text,
            max_prompt_chars=query.max_prompt_chars,
            max_chunks=query.max_chunks,
            max_quote_chars=query.max_quote_chars,
        )

    def rebuild(self) -> dict[str, Any]:
        return self.store.rebuild()


class HaystackBibliothekarBackend:
    backend_name = "haystack"

    def __init__(
        self,
        *,
        instance_name: str,
        instances_dir: str | Path = "instances",
        collection: str = DEFAULT_BIBLIOTHEKAR_COLLECTION,
        qdrant_url: str = DEFAULT_QDRANT_URL,
        fallback_store: BibliothekarStore | None = None,
        document_store_factory: Callable[[], Any] | None = None,
        document_class: type[Any] | None = None,
    ) -> None:
        self.instance_name = str(instance_name or "default")
        self.instances_dir = Path(instances_dir)
        self.collection = str(collection or DEFAULT_BIBLIOTHEKAR_COLLECTION).strip() or DEFAULT_BIBLIOTHEKAR_COLLECTION
        self.qdrant_url = _normalize_local_qdrant_url(qdrant_url)
        self.fallback_store = fallback_store or BibliothekarStore(self.instance_name, self.instances_dir)
        self._document_store_factory = document_store_factory
        self._document_class = document_class
        self._document_store_cache: Any | None = None

    def search(self, query: BibliothekarQuery) -> BibliothekarSelection:
        if not self.available:
            return LocalBibliothekarBackend(self.fallback_store).search(query)
        try:
            document_store = self._document_store()
            chunks = self._search_document_store_chunks(document_store, query.filters)
        except Exception:
            return LocalBibliothekarBackend(self.fallback_store).search(query)
        if not chunks:
            try:
                self.rebuild()
                chunks = self._search_document_store_chunks(document_store, query.filters)
            except Exception:
                return LocalBibliothekarBackend(self.fallback_store).search(query)
        if not chunks:
            local_selection = LocalBibliothekarBackend(self.fallback_store).search(query)
            if local_selection.selected_ids:
                return local_selection
            return BibliothekarSelection("", ())
        self.fallback_store.ensure_current()
        index = _read_index(self.fallback_store.index_path)
        return _selection_from_chunks(index, _apply_chunk_filters(chunks, query.filters), query)

    def rebuild(self) -> dict[str, Any]:
        index = self.fallback_store.rebuild()
        if not self.available:
            return index
        chunks = _read_chunks(self.fallback_store.chunks_path)
        documents = [self._document_from_chunk(chunk) for chunk in chunks]
        document_store = self._document_store()
        self._delete_stale_documents(document_store, current_ids={str(getattr(document, "id", "")) for document in documents if str(getattr(document, "id", ""))})
        if documents:
            self._write_documents(document_store, documents)
        return index

    @property
    def available(self) -> bool:
        return self._document_store_factory is not None or (_module_available("haystack") and any(_module_available(name) for name in HAYSTACK_QDRANT_MODULES))

    def _document_store(self) -> Any:
        if self._document_store_cache is not None:
            return self._document_store_cache
        if self._document_store_factory is not None:
            self._document_store_cache = self._document_store_factory()
            return self._document_store_cache
        try:
            from haystack_integrations.document_stores.qdrant import QdrantDocumentStore  # type: ignore[import-not-found]
        except ModuleNotFoundError:
            from qdrant_haystack import QdrantDocumentStore  # type: ignore[import-not-found]

        self._document_store_cache = QdrantDocumentStore(url=self.qdrant_url, index=self.collection)
        return self._document_store_cache

    def _document_from_chunk(self, chunk: Mapping[str, Any]) -> Any:
        meta = {
            "chunk_id": str(chunk.get("chunk_id", "")),
            "instance_name": self.instance_name,
            "document_id": str(chunk.get("document_id", "")),
            "source_id": str(chunk.get("source_id", "")),
            "title": str(chunk.get("title", "")),
            "author": str(chunk.get("author", "")),
            "relative_path": str(chunk.get("relative_path", "")),
            "file_path": str(chunk.get("file_path", "") or chunk.get("relative_path", "")),
            "file_sha256": str(chunk.get("file_sha256", "")),
            "file_type": str(chunk.get("file_type", "")),
            "language": str(chunk.get("language", "")),
            "locator": str(chunk.get("locator", "")),
            "suffix": str(chunk.get("suffix", "")),
            "page_start": chunk.get("page_start"),
            "page_end": chunk.get("page_end"),
            "chapter": str(chunk.get("chapter", "")),
            "section": str(chunk.get("section", "")),
            "license": str(chunk.get("license", "")),
            "source_quality": str(chunk.get("source_quality", "")),
            "citation_quality": str(chunk.get("citation_quality", "")),
            "source_quality_reason": str(chunk.get("source_quality_reason", "")),
            "source_requires_human_review": bool(chunk.get("source_requires_human_review")),
            "source_harvest_route": str(chunk.get("source_harvest_route", "")),
            "ingested_at": str(chunk.get("ingested_at", "")),
            "chunk_index": chunk.get("chunk_index"),
            "embedding_model": str(chunk.get("embedding_model", "")),
            "topics": list(chunk.get("topics", [])) if isinstance(chunk.get("topics"), list) else [],
            "categories": list(chunk.get("categories", [])) if isinstance(chunk.get("categories"), list) else [],
        }
        document_class = self._document_class
        if document_class is None:
            from haystack import Document  # type: ignore[import-not-found]

            document_class = Document
        try:
            return document_class(content=str(chunk.get("text", "")), meta=meta, id=meta["chunk_id"])
        except TypeError:
            return document_class(content=str(chunk.get("text", "")), meta=meta)

    def _write_documents(self, document_store: Any, documents: list[Any]) -> None:
        try:
            from haystack.document_stores.types import DuplicatePolicy  # type: ignore[import-not-found]

            document_store.write_documents(documents, policy=DuplicatePolicy.OVERWRITE)
        except Exception:
            document_store.write_documents(documents)

    def _delete_stale_documents(self, document_store: Any, *, current_ids: set[str]) -> None:
        existing = self._existing_documents_for_cleanup(document_store)
        stale_ids = [
            str(getattr(document, "id", "") or "")
            for document in existing
            if self._document_belongs_to_instance(document)
            and str(getattr(document, "id", "") or "")
            and str(getattr(document, "id", "") or "") not in current_ids
        ]
        if not stale_ids:
            return
        try:
            document_store.delete_documents(document_ids=stale_ids)
        except AttributeError:
            return
        except TypeError:
            document_store.delete_documents(stale_ids)

    def _existing_documents_for_cleanup(self, document_store: Any) -> list[Any]:
        try:
            existing = document_store.filter_documents(filters=self._instance_document_store_filter())
        except AttributeError:
            return []
        except TypeError:
            return self._unfiltered_cleanup_documents(document_store)
        except Exception:
            return self._unfiltered_cleanup_documents(document_store)
        if existing:
            return list(existing)
        return self._unfiltered_cleanup_documents(document_store)

    def _unfiltered_cleanup_documents(self, document_store: Any) -> list[Any]:
        try:
            return list(document_store.filter_documents() or [])
        except AttributeError:
            return []
        except Exception:
            return []

    def _chunks_from_document_store(self, document_store: Any, *, filters: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        try:
            documents = document_store.filter_documents(filters=filters) if filters else document_store.filter_documents()
        except AttributeError:
            return []
        except TypeError:
            try:
                documents = document_store.filter_documents(filters=filters or {})
            except Exception:
                if not filters:
                    raise
                documents = document_store.filter_documents()
        except Exception:
            if not filters:
                raise
            documents = document_store.filter_documents()
        chunks: list[dict[str, Any]] = []
        for document in documents or []:
            if not self._document_belongs_to_instance(document):
                continue
            meta = getattr(document, "meta", None)
            if not isinstance(meta, Mapping):
                meta = {}
            text = str(getattr(document, "content", "") or "")
            chunk_id = str(meta.get("chunk_id") or getattr(document, "id", "") or "")
            relative_path = str(meta.get("relative_path", "") or meta.get("file_path", ""))
            chunk = {
                "chunk_id": chunk_id,
                "instance_name": str(meta.get("instance_name", "")),
                "document_id": str(meta.get("document_id", "")),
                "source_id": str(meta.get("source_id", "")),
                "title": str(meta.get("title", "")),
                "author": str(meta.get("author", "")),
                "relative_path": relative_path,
                "file_path": str(meta.get("file_path", "") or relative_path),
                "file_sha256": str(meta.get("file_sha256", "")),
                "file_type": str(meta.get("file_type", "")),
                "language": str(meta.get("language", "")),
                "locator": str(meta.get("locator", "")),
                "suffix": str(meta.get("suffix", "")),
                "page_start": meta.get("page_start"),
                "page_end": meta.get("page_end"),
                "chapter": str(meta.get("chapter", "")),
                "section": str(meta.get("section", "")),
                "license": str(meta.get("license", "")),
                "source_quality": str(meta.get("source_quality", "")),
                "citation_quality": str(meta.get("citation_quality", "")),
                "source_quality_reason": str(meta.get("source_quality_reason", "")),
                "source_requires_human_review": bool(meta.get("source_requires_human_review")),
                "source_harvest_route": str(meta.get("source_harvest_route", "")),
                "ingested_at": str(meta.get("ingested_at", "")),
                "chunk_index": meta.get("chunk_index"),
                "embedding_model": str(meta.get("embedding_model", "")),
                "topics": list(meta.get("topics", [])) if isinstance(meta.get("topics"), list) else [],
                "categories": list(meta.get("categories", [])) if isinstance(meta.get("categories"), list) else [],
                "text": text,
            }
            if not text or not _chunk_has_required_citation_metadata(chunk):
                continue
            chunks.append(chunk)
        return chunks

    def _document_store_filters(self, filters: Mapping[str, object] | None) -> dict[str, Any]:
        return _and_document_store_filters(self._instance_document_store_filter(), _document_store_filters(filters))

    def _instance_document_store_filter(self) -> dict[str, Any]:
        return {"operator": "AND", "conditions": [{"field": "meta.instance_name", "operator": "in", "value": [self.instance_name]}]}

    def _document_belongs_to_instance(self, document: Any) -> bool:
        meta = getattr(document, "meta", None)
        if not isinstance(meta, Mapping):
            return False
        return str(meta.get("instance_name") or "").strip().casefold() == self.instance_name.casefold()

    def _search_document_store_chunks(self, document_store: Any, filters: Mapping[str, object] | None) -> list[dict[str, Any]]:
        pushed_filters = self._document_store_filters(filters)
        active_filters = _active_chunk_filters(filters or {})
        chunks = self._chunks_from_document_store(document_store, filters=pushed_filters)
        if chunks:
            return _apply_chunk_filters(chunks, filters) if active_filters else chunks
        fallback_chunks = self._chunks_from_document_store(document_store)
        if active_filters:
            return _apply_chunk_filters(fallback_chunks, filters)
        return fallback_chunks


class LlamaIndexBibliothekarBackend:
    backend_name = "llamaindex"

    def __init__(
        self,
        *,
        instance_name: str,
        instances_dir: str | Path = "instances",
        query_engine_factory: Callable[[BibliothekarStore], Any] | None = None,
    ) -> None:
        self.instance_name = instance_name
        self.fallback_store = BibliothekarStore(instance_name, instances_dir)
        self._query_engine_factory = query_engine_factory
        self._query_engine_cache: Any | None = None
        self._query_engine_cache_signature: tuple[int, int, int, int] | None = None

    @property
    def available(self) -> bool:
        return self._query_engine_factory is not None or _module_available("llama_index.core")

    def search(self, query: BibliothekarQuery) -> BibliothekarSelection:
        if not self.available:
            return LocalBibliothekarBackend(self.fallback_store).search(query)
        try:
            self.fallback_store.ensure_current()
            chunks = self._chunks_from_query_engine(query)
        except Exception:
            return LocalBibliothekarBackend(self.fallback_store).search(query)
        if not chunks:
            return LocalBibliothekarBackend(self.fallback_store).search(query)
        index = _read_index(self.fallback_store.index_path)
        return _selection_from_chunks(index, _apply_chunk_filters(chunks, query.filters), query)

    def rebuild(self) -> dict[str, Any]:
        index = self.fallback_store.rebuild()
        self._query_engine_cache = None
        self._query_engine_cache_signature = None
        return index

    def _query_engine(self, max_chunks: int = DEFAULT_MAX_CHUNKS) -> Any:
        self.fallback_store.ensure_current()
        top_k = max(1, int(max_chunks or DEFAULT_MAX_CHUNKS))
        signature = (*self._chunk_store_signature(), 0 if self._query_engine_factory is not None else top_k)
        if self._query_engine_cache is not None and self._query_engine_cache_signature == signature:
            return self._query_engine_cache
        if self._query_engine_factory is not None:
            self._query_engine_cache = self._query_engine_factory(self.fallback_store)
            self._query_engine_cache_signature = (*self._chunk_store_signature(), 0)
            return self._query_engine_cache
        self._query_engine_cache = self._build_default_query_engine(top_k)
        self._query_engine_cache_signature = signature
        return self._query_engine_cache

    def _chunk_store_signature(self) -> tuple[int, int, int]:
        try:
            stat = self.fallback_store.chunks_path.stat()
        except FileNotFoundError:
            return (-1, -1, -1)
        return (int(stat.st_size), int(stat.st_mtime_ns), int(stat.st_ino))

    def _build_default_query_engine(self, max_chunks: int = DEFAULT_MAX_CHUNKS) -> Any:
        self.fallback_store.ensure_current()
        chunks = _read_chunks(self.fallback_store.chunks_path)
        documents = [_llamaindex_document_from_chunk(chunk) for chunk in chunks if _chunk_has_required_citation_metadata(chunk)]
        if not documents:
            return _StaticLlamaIndexRetriever([])
        try:
            from llama_index.core import VectorStoreIndex  # type: ignore[import-not-found]
        except ModuleNotFoundError as exc:
            raise RuntimeError("missing optional dependency: llama-index-core") from exc

        embed_model = _llamaindex_mock_embedding()
        index = _llamaindex_vector_index_from_documents(VectorStoreIndex, documents, embed_model)
        retriever = index.as_retriever(similarity_top_k=max(1, int(max_chunks or DEFAULT_MAX_CHUNKS)))
        return _LlamaIndexRetrieverAdapter(retriever)

    def _chunks_from_query_engine(self, query: BibliothekarQuery) -> list[dict[str, Any]]:
        engine = self._query_engine(query.max_chunks)
        for method_name in ("query", "chat", "search", "retrieve"):
            method = getattr(engine, method_name, None)
            if not callable(method):
                continue
            result = method(query.text)
            chunks = _coerce_query_engine_chunks(result)
            if chunks:
                return [chunk for chunk in chunks if self._chunk_belongs_to_instance(chunk)]
        return []

    def _chunk_belongs_to_instance(self, chunk: Mapping[str, Any]) -> bool:
        chunk_instance = str(chunk.get("instance_name") or "").strip()
        return not chunk_instance or chunk_instance.casefold() == self.instance_name.casefold()


class _StaticLlamaIndexRetriever:
    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        self.chunks = chunks

    def retrieve(self, _query_text: str) -> list[dict[str, Any]]:
        return self.chunks


class _LlamaIndexRetrieverAdapter:
    def __init__(self, retriever: Any) -> None:
        self.retriever = retriever

    def retrieve(self, query_text: str) -> list[Any]:
        return list(self.retriever.retrieve(query_text) or [])


class BibliothekarService:
    def __init__(self, backend: BibliothekarBackend) -> None:
        self.backend = backend

    @classmethod
    def local(cls, instance_name: str, instances_dir: str | Path = "instances") -> BibliothekarService:
        return cls(LocalBibliothekarBackend(BibliothekarStore(instance_name, instances_dir)))

    @classmethod
    def from_instructions(
        cls,
        instance_name: str,
        instances_dir: str | Path,
        instructions: object,
    ) -> BibliothekarService:
        backend = _normalize_backend(getattr(instructions, "bibliothekar_backend", "local"))
        if backend == "haystack":
            return cls(
                HaystackBibliothekarBackend(
                    instance_name=instance_name,
                    instances_dir=instances_dir,
                    collection=str(getattr(instructions, "bibliothekar_collection", "") or DEFAULT_BIBLIOTHEKAR_COLLECTION),
                    qdrant_url=str(getattr(instructions, "bibliothekar_qdrant_url", "") or DEFAULT_QDRANT_URL),
                )
            )
        if backend == "llamaindex":
            return cls(LlamaIndexBibliothekarBackend(instance_name=instance_name, instances_dir=instances_dir))
        return cls.local(instance_name, instances_dir)

    @property
    def backend_name(self) -> str:
        return self.backend.backend_name

    @property
    def collection(self) -> str:
        return str(getattr(self.backend, "collection", "") or "")

    def search(
        self,
        query_text: str,
        *,
        filters: Mapping[str, object] | None = None,
        max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS,
        max_chunks: int = DEFAULT_MAX_CHUNKS,
        max_quote_chars: int = DEFAULT_MAX_QUOTE_CHARS,
    ) -> BibliothekarSelection:
        return self.backend.search(
            BibliothekarQuery(
                text=query_text,
                filters=filters,
                max_prompt_chars=max_prompt_chars,
                max_chunks=max_chunks,
                max_quote_chars=max_quote_chars,
            )
        )

    def rebuild(self) -> dict[str, Any]:
        return self.backend.rebuild()

    def select(
        self,
        query_text: str,
        *,
        max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS,
        max_chunks: int = DEFAULT_MAX_CHUNKS,
        max_quote_chars: int = DEFAULT_MAX_QUOTE_CHARS,
    ) -> BibliothekarSelection:
        return self.search(
            query_text,
            max_prompt_chars=max_prompt_chars,
            max_chunks=max_chunks,
            max_quote_chars=max_quote_chars,
        )


def check_bibliothekar_service(instance_name: str, instances_dir: str | Path, instructions: object) -> BibliothekarServiceHealth:
    backend = _normalize_backend(getattr(instructions, "bibliothekar_backend", "local"))
    collection = str(getattr(instructions, "bibliothekar_collection", "") or DEFAULT_BIBLIOTHEKAR_COLLECTION)
    qdrant_url = str(getattr(instructions, "bibliothekar_qdrant_url", "") or DEFAULT_QDRANT_URL)
    if not bool(getattr(instructions, "bibliothekar_enabled", True)):
        return BibliothekarServiceHealth(instance_name, backend, "disabled", collection=collection, target=qdrant_url if backend == "haystack" else "")
    if backend == "haystack":
        try:
            qdrant_url = _normalize_local_qdrant_url(qdrant_url)
        except ValueError as exc:
            return BibliothekarServiceHealth(
                instance_name,
                "haystack",
                "unavailable",
                collection=collection,
                target=qdrant_url,
                store="qdrant",
                error=str(exc),
            )
        missing = []
        if not _module_available("haystack"):
            missing.append("haystack")
        if not any(_module_available(name) for name in HAYSTACK_QDRANT_MODULES):
            missing.append("haystack_integrations.document_stores.qdrant")
        if missing:
            return BibliothekarServiceHealth(
                instance_name,
                "haystack",
                "unavailable",
                collection=collection,
                target=qdrant_url,
                store="qdrant",
                error=f"missing optional dependency: {', '.join(missing)}",
            )
        haystack_backend = HaystackBibliothekarBackend(
            instance_name=instance_name,
            instances_dir=instances_dir,
            collection=collection,
            qdrant_url=qdrant_url,
        )
        try:
            document_store = haystack_backend._document_store()
            try:
                document_store.filter_documents()
            except TypeError:
                document_store.filter_documents(filters={})
        except Exception as exc:  # noqa: BLE001 - status should report backend reachability, not crash.
            return BibliothekarServiceHealth(
                instance_name,
                "haystack",
                "unreachable",
                collection=collection,
                target=qdrant_url,
                store="qdrant",
                error=f"{type(exc).__name__}: {exc}",
            )
        try:
            haystack_backend.fallback_store.ensure_current()
            index = _read_index(haystack_backend.fallback_store.index_path)
        except OSError as exc:
            return BibliothekarServiceHealth(
                instance_name,
                "haystack",
                "broken",
                collection=collection,
                target=qdrant_url,
                store="qdrant",
                error=str(exc),
            )
        documents = index.get("documents") if isinstance(index.get("documents"), dict) else {}
        return BibliothekarServiceHealth(
            instance_name,
            "haystack",
            "reachable",
            collection=collection,
            target=qdrant_url,
            store="qdrant",
            documents=len(documents),
            chunks=int(index.get("chunk_count") or 0),
        )
    if backend == "llamaindex":
        store = BibliothekarStore(instance_name, instances_dir)
        try:
            store.ensure_current()
            index = _read_index(store.index_path)
        except OSError as exc:
            return BibliothekarServiceHealth(instance_name, "llamaindex", "broken", error=str(exc))
        documents = index.get("documents") if isinstance(index.get("documents"), dict) else {}
        if not _module_available("llama_index.core"):
            return BibliothekarServiceHealth(
                instance_name,
                "llamaindex",
                "unavailable",
                collection=collection,
                documents=len(documents),
                chunks=int(index.get("chunk_count") or 0),
                store="json",
                error="missing optional dependency: llama-index-core",
            )
        backend = LlamaIndexBibliothekarBackend(instance_name=instance_name, instances_dir=instances_dir)
        try:
            backend._query_engine()
        except Exception as exc:  # noqa: BLE001 - runtime-status should diagnose optional pilot failures.
            return BibliothekarServiceHealth(
                instance_name,
                "llamaindex",
                "unavailable",
                collection=collection,
                documents=len(documents),
                chunks=int(index.get("chunk_count") or 0),
                store="json",
                error=f"llamaindex query engine unavailable: {type(exc).__name__}: {exc}",
            )
        return BibliothekarServiceHealth(
            instance_name,
            "llamaindex",
            "ready",
            collection=collection,
            documents=len(documents),
            chunks=int(index.get("chunk_count") or 0),
            store="llamaindex",
            target="local_in_memory",
        )
    store = BibliothekarStore(instance_name, instances_dir)
    try:
        store.ensure_current()
        index = _read_index(store.index_path)
    except OSError as exc:
        return BibliothekarServiceHealth(instance_name, "local", "broken", error=str(exc))
    documents = index.get("documents") if isinstance(index.get("documents"), dict) else {}
    return BibliothekarServiceHealth(
        instance_name,
        "local",
        "ready",
        collection=collection,
        documents=len(documents),
        chunks=int(index.get("chunk_count") or 0),
        store="json",
    )


def _normalize_backend(value: object) -> str:
    backend = str(value or "local").strip().casefold().replace("-", "_")
    if backend in {"haystack", "qdrant", "haystack_qdrant"}:
        return "haystack"
    if backend in {"llamaindex", "llama_index", "llamaindex_backend"}:
        return "llamaindex"
    return "local"


def _coerce_query_engine_chunks(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    items = value
    if hasattr(value, "source_nodes"):
        items = getattr(value, "source_nodes")
    if not isinstance(items, (list, tuple)):
        return []
    chunks: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            chunk = dict(item)
        else:
            node = getattr(item, "node", item)
            metadata = getattr(node, "metadata", None)
            if not isinstance(metadata, Mapping):
                metadata = {}
            text = _llamaindex_node_text(node)
            chunk = {**dict(metadata), "text": text}
        if _chunk_has_required_citation_metadata(chunk):
            chunks.append(chunk)
    return chunks


def _llamaindex_node_text(node: Any) -> str:
    text = getattr(node, "text", "")
    if text:
        return str(text)
    get_content = getattr(node, "get_content", None)
    if callable(get_content):
        try:
            return str(get_content())
        except TypeError:
            try:
                return str(get_content(metadata_mode="none"))
            except Exception:
                return ""
        except Exception:
            return ""
    return ""


def _llamaindex_document_from_chunk(chunk: Mapping[str, Any]) -> Any:
    try:
        from llama_index.core import Document  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise RuntimeError("missing optional dependency: llama-index-core") from exc
    metadata = {key: value for key, value in dict(chunk).items() if key != "text"}
    text = str(chunk.get("text") or "")
    chunk_id = str(chunk.get("chunk_id") or "")
    try:
        return Document(text=text, metadata=metadata, id_=chunk_id)
    except TypeError:
        return Document(text=text, metadata=metadata)


def _llamaindex_mock_embedding() -> Any:
    import_errors: list[str] = []
    for module_name in ("llama_index.core.embeddings", "llama_index.core.embeddings.mock_embed_model"):
        try:
            module = __import__(module_name, fromlist=["MockEmbedding"])
        except ModuleNotFoundError as exc:
            import_errors.append(str(exc))
            continue
        mock_embedding = getattr(module, "MockEmbedding", None)
        if mock_embedding is not None:
            return mock_embedding(embed_dim=384)
    raise RuntimeError("missing optional dependency: llama-index-core MockEmbedding: " + "; ".join(import_errors))


def _llamaindex_vector_index_from_documents(vector_store_index: Any, documents: list[Any], embed_model: Any) -> Any:
    for kwargs in (
        {"embed_model": embed_model, "show_progress": False},
        {"embed_model": embed_model},
    ):
        try:
            return vector_store_index.from_documents(documents, **kwargs)
        except TypeError:
            continue
    raise RuntimeError("llama-index-core VectorStoreIndex does not accept an explicit local embed_model")


def _normalize_local_qdrant_url(value: object) -> str:
    raw = str(value or DEFAULT_QDRANT_URL).strip() or DEFAULT_QDRANT_URL
    try:
        parsed = urlparse(raw)
    except ValueError as exc:
        raise ValueError("Bibliothekar Qdrant URL must be a valid URL.") from exc
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("Bibliothekar Qdrant URL must include scheme and host.")
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Bibliothekar Qdrant URL must use http or https.")
    host = (parsed.hostname or "").strip().casefold()
    if host not in LOCAL_QDRANT_HOSTS:
        raise ValueError("Bibliothekar Qdrant URL must stay local on 127.0.0.1, localhost or ::1.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Bibliothekar Qdrant URL must include a valid port if one is specified.") from exc
    if port is None:
        raise ValueError("Bibliothekar Qdrant URL must include an explicit port.")
    if port <= 0:
        raise ValueError("Bibliothekar Qdrant URL must include a valid port.")
    if parsed.username or parsed.password:
        raise ValueError("Bibliothekar Qdrant URL must not contain credentials.")
    if parsed.query or parsed.fragment:
        raise ValueError("Bibliothekar Qdrant URL must not contain query parameters or fragments.")
    if parsed.path not in {"", "/"}:
        raise ValueError("Bibliothekar Qdrant URL must be a base URL without a path.")
    return raw.rstrip("/")


def _selection_from_chunks(index: Mapping[str, Any], chunks: list[dict[str, Any]], query: BibliothekarQuery) -> BibliothekarSelection:
    if not chunks or query.max_prompt_chars < 1 or query.max_chunks < 1:
        return BibliothekarSelection("", ())
    selected = _rank_chunks(chunks, query.text)[: query.max_chunks]
    prompt_items: list[dict[str, Any]] = []
    selected_ids: list[str] = []
    for chunk in selected:
        item = _chunk_prompt_item(chunk, max_quote_chars=query.max_quote_chars)
        candidate_text = json.dumps(_prompt_payload(index, [*prompt_items, item]), ensure_ascii=False, indent=2)
        if len(candidate_text) > query.max_prompt_chars:
            if prompt_items:
                break
            item["quote"] = str(item.get("quote", ""))[: max(200, query.max_prompt_chars // 3)].rstrip() + "\n[gekuerzt]"
            candidate_text = json.dumps(_prompt_payload(index, [item]), ensure_ascii=False, indent=2)
            if len(candidate_text) > query.max_prompt_chars:
                break
        prompt_items.append(item)
        selected_ids.append(str(item["chunk_id"]))
    if not prompt_items:
        return BibliothekarSelection("", ())
    return BibliothekarSelection(
        prompt_text=json.dumps(_prompt_payload(index, prompt_items), ensure_ascii=False, indent=2),
        selected_ids=tuple(selected_ids),
    )


def _apply_chunk_filters(chunks: list[dict[str, Any]], filters: Mapping[str, object] | None) -> list[dict[str, Any]]:
    if not filters:
        return chunks
    active = _active_chunk_filters(filters)
    if not active:
        return chunks
    return [chunk for chunk in chunks if all(_chunk_matches_filter(chunk, key, value) for key, value in active.items())]


def _active_chunk_filters(filters: Mapping[str, object]) -> dict[str, object]:
    active: dict[str, object] = {}
    for raw_key, raw_value in filters.items():
        key = str(raw_key or "").strip().casefold()
        if key not in CHUNK_FILTER_KEYS or not _filter_values(raw_value):
            continue
        active[key] = raw_value
    return active


def _document_store_filters(filters: Mapping[str, object] | None) -> dict[str, Any] | None:
    if not filters:
        return None
    conditions = []
    for raw_key, raw_value in filters.items():
        key = str(raw_key or "").strip().casefold()
        field = DOCUMENT_STORE_FILTER_FIELD_MAP.get(key)
        values = list(_document_store_filter_values(key, _filter_values(raw_value)))
        if not field or not values:
            continue
        conditions.append({"field": field, "operator": "in", "value": values})
    if not conditions:
        return None
    return {"operator": "AND", "conditions": conditions}


def _and_document_store_filters(*filters: Mapping[str, Any] | None) -> dict[str, Any]:
    conditions: list[dict[str, Any]] = []
    for filter_doc in filters:
        if not isinstance(filter_doc, Mapping):
            continue
        if filter_doc.get("operator") == "AND" and isinstance(filter_doc.get("conditions"), list):
            conditions.extend(condition for condition in filter_doc["conditions"] if isinstance(condition, dict))
            continue
        conditions.append(dict(filter_doc))
    return {"operator": "AND", "conditions": conditions}


def _chunk_matches_filter(chunk: Mapping[str, Any], key: str, value: object) -> bool:
    values = _filter_values(value)
    if not values:
        return True
    if key in {"category", "categories"}:
        return _any_exact_match(chunk.get("categories"), values)
    if key in {"topic", "topics", "keyword", "keywords"}:
        return _any_exact_match(chunk.get("topics"), values)
    if key in {"file", "path", "relative_path"}:
        return _any_substring_match(chunk.get("relative_path"), values)
    if key == "suffix":
        return _any_exact_match(chunk.get("suffix"), _suffix_filter_values(values))
    if key in {"extension", "file_type"}:
        return _any_exact_match(chunk.get("file_type"), _extension_filter_values(values)) or _any_exact_match(
            chunk.get("suffix"),
            _suffix_filter_values(values),
        )
    if key in {"title"}:
        return _any_substring_match(chunk.get("title"), values)
    if key in {"document", "document_id"}:
        return _any_exact_match(chunk.get("document_id"), values)
    if key in {"chunk", "chunk_id"}:
        return _any_exact_match(chunk.get("chunk_id"), values)
    return True


def _chunk_has_required_citation_metadata(chunk: Mapping[str, Any]) -> bool:
    return bool(str(chunk.get("text") or "").strip()) and all(field in chunk for field in REQUIRED_CITATION_CHUNK_KEYS) and all(
        str(chunk.get(field) or "").strip() for field in REQUIRED_CITATION_CHUNK_FIELDS
    ) and _chunk_has_library_source_path(dict(chunk))


def _filter_values(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
    else:
        items = [value]
    return tuple(_normalize_filter_text(item) for item in items if _normalize_filter_text(item))


def _document_store_filter_values(key: str, values: tuple[str, ...]) -> tuple[str, ...]:
    if key == "suffix":
        return _suffix_filter_values(values)
    if key in {"extension", "file_type"}:
        return _extension_filter_values(values)
    return values


def _suffix_filter_values(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(f".{value.lstrip('.')}" for value in values if value.strip("."))


def _extension_filter_values(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(value.lstrip(".") for value in values if value.strip("."))


def _any_exact_match(candidate: object, values: tuple[str, ...]) -> bool:
    candidate_values = _filter_values(candidate)
    return any(item in values for item in candidate_values)


def _any_substring_match(candidate: object, values: tuple[str, ...]) -> bool:
    candidate_values = _filter_values(candidate)
    return any(value in item for item in candidate_values for value in values)


def _normalize_filter_text(value: object) -> str:
    return str(value or "").strip().casefold()


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


def _read_index(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


__all__ = [
    "BibliothekarBackend",
    "BibliothekarQuery",
    "BibliothekarService",
    "BibliothekarServiceHealth",
    "HaystackBibliothekarBackend",
    "LlamaIndexBibliothekarBackend",
    "LocalBibliothekarBackend",
    "check_bibliothekar_service",
]
