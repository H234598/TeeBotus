from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from TeeBotus.runtime.bibliothekar import (
    DEFAULT_MAX_CHUNKS,
    DEFAULT_MAX_PROMPT_CHARS,
    DEFAULT_MAX_QUOTE_CHARS,
    BibliothekarSelection,
    BibliothekarStore,
    _chunk_prompt_item,
    _prompt_payload,
    _rank_chunks,
    _read_chunks,
)


HAYSTACK_QDRANT_MODULES = ("haystack_integrations.document_stores.qdrant", "qdrant_haystack")
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
    "suffix": "meta.suffix",
    "extension": "meta.suffix",
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
        collection: str = "teebotus_books",
        fallback_store: BibliothekarStore | None = None,
        document_store_factory: Callable[[], Any] | None = None,
        document_class: type[Any] | None = None,
    ) -> None:
        self.instance_name = str(instance_name or "default")
        self.instances_dir = Path(instances_dir)
        self.collection = str(collection or "teebotus_books").strip() or "teebotus_books"
        self.fallback_store = fallback_store or BibliothekarStore(self.instance_name, self.instances_dir)
        self._document_store_factory = document_store_factory
        self._document_class = document_class
        self._document_store_cache: Any | None = None

    def search(self, query: BibliothekarQuery) -> BibliothekarSelection:
        if not self.available:
            return LocalBibliothekarBackend(self.fallback_store).search(query)
        try:
            document_store = self._document_store()
            chunks = self._chunks_from_document_store(document_store, filters=_document_store_filters(query.filters))
        except Exception:
            return LocalBibliothekarBackend(self.fallback_store).search(query)
        if not chunks:
            try:
                self.rebuild()
                chunks = self._chunks_from_document_store(document_store, filters=_document_store_filters(query.filters))
            except Exception:
                return LocalBibliothekarBackend(self.fallback_store).search(query)
        if not chunks:
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

        self._document_store_cache = QdrantDocumentStore(url="http://127.0.0.1:6333", index=self.collection)
        return self._document_store_cache

    def _document_from_chunk(self, chunk: Mapping[str, Any]) -> Any:
        meta = {
            "chunk_id": str(chunk.get("chunk_id", "")),
            "document_id": str(chunk.get("document_id", "")),
            "source_id": str(chunk.get("source_id", "")),
            "title": str(chunk.get("title", "")),
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
        try:
            existing = document_store.filter_documents()
        except AttributeError:
            return
        stale_ids = [
            str(getattr(document, "id", "") or "")
            for document in existing or []
            if str(getattr(document, "id", "") or "") and str(getattr(document, "id", "") or "") not in current_ids
        ]
        if not stale_ids:
            return
        try:
            document_store.delete_documents(document_ids=stale_ids)
        except AttributeError:
            return
        except TypeError:
            document_store.delete_documents(stale_ids)

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
            meta = getattr(document, "meta", None)
            if not isinstance(meta, Mapping):
                meta = {}
            text = str(getattr(document, "content", "") or "")
            chunk_id = str(meta.get("chunk_id") or getattr(document, "id", "") or "")
            if not chunk_id or not text:
                continue
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "document_id": str(meta.get("document_id", "")),
                    "source_id": str(meta.get("source_id", "")),
                    "title": str(meta.get("title", "")),
                    "relative_path": str(meta.get("relative_path", "")),
                    "file_path": str(meta.get("file_path", "") or meta.get("relative_path", "")),
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
                    "ingested_at": str(meta.get("ingested_at", "")),
                    "chunk_index": meta.get("chunk_index"),
                    "embedding_model": str(meta.get("embedding_model", "")),
                    "topics": list(meta.get("topics", [])) if isinstance(meta.get("topics"), list) else [],
                    "categories": list(meta.get("categories", [])) if isinstance(meta.get("categories"), list) else [],
                    "text": text,
                }
            )
        return chunks


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
                    collection=str(getattr(instructions, "bibliothekar_collection", "") or "teebotus_books"),
                )
            )
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
    collection = str(getattr(instructions, "bibliothekar_collection", "") or "teebotus_books")
    if not bool(getattr(instructions, "bibliothekar_enabled", True)):
        return BibliothekarServiceHealth(instance_name, backend, "disabled", collection=collection)
    if backend == "haystack":
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
                store="qdrant",
                error=f"missing optional dependency: {', '.join(missing)}",
            )
        haystack_backend = HaystackBibliothekarBackend(
            instance_name=instance_name,
            instances_dir=instances_dir,
            collection=collection,
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
                store="qdrant",
                error=str(exc),
            )
        documents = index.get("documents") if isinstance(index.get("documents"), dict) else {}
        return BibliothekarServiceHealth(
            instance_name,
            "haystack",
            "reachable",
            collection=collection,
            store="qdrant",
            documents=len(documents),
            chunks=int(index.get("chunk_count") or 0),
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
    return "local"


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
        values = list(_filter_values(raw_value))
        if not field or not values:
            continue
        conditions.append({"field": field, "operator": "in", "value": values})
    if not conditions:
        return None
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
    if key in {"suffix", "extension"}:
        return _any_exact_match(chunk.get("suffix"), values)
    if key in {"title"}:
        return _any_substring_match(chunk.get("title"), values)
    if key in {"document", "document_id"}:
        return _any_exact_match(chunk.get("document_id"), values)
    if key in {"chunk", "chunk_id"}:
        return _any_exact_match(chunk.get("chunk_id"), values)
    return True


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


def _any_exact_match(candidate: object, values: tuple[str, ...]) -> bool:
    candidate_values = _filter_values(candidate)
    return any(item in values for item in candidate_values)


def _any_substring_match(candidate: object, values: tuple[str, ...]) -> bool:
    candidate_values = _filter_values(candidate)
    return any(value in item for item in candidate_values for value in values)


def _normalize_filter_text(value: object) -> str:
    return str(value or "").strip().casefold()


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


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
    "LocalBibliothekarBackend",
    "check_bibliothekar_service",
]
