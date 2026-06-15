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
            return BibliothekarSelection("", ())
        try:
            document_store = self._document_store()
            chunks = self._chunks_from_document_store(document_store)
        except Exception:
            return LocalBibliothekarBackend(self.fallback_store).search(query)
        if not chunks:
            try:
                self.rebuild()
                chunks = self._chunks_from_document_store(document_store)
            except Exception:
                return LocalBibliothekarBackend(self.fallback_store).search(query)
        if not chunks:
            return BibliothekarSelection("", ())
        self.fallback_store.ensure_current()
        index = _read_index(self.fallback_store.index_path)
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

    def rebuild(self) -> dict[str, Any]:
        index = self.fallback_store.rebuild()
        if not self.available:
            return index
        chunks = _read_chunks(self.fallback_store.chunks_path)
        documents = [self._document_from_chunk(chunk) for chunk in chunks]
        if documents:
            self._write_documents(self._document_store(), documents)
        return index

    @property
    def available(self) -> bool:
        return self._document_store_factory is not None or (_module_available("haystack") and _module_available("qdrant_haystack"))

    def _document_store(self) -> Any:
        if self._document_store_cache is not None:
            return self._document_store_cache
        if self._document_store_factory is not None:
            self._document_store_cache = self._document_store_factory()
            return self._document_store_cache
        from qdrant_haystack import QdrantDocumentStore  # type: ignore[import-not-found]

        self._document_store_cache = QdrantDocumentStore(url="http://127.0.0.1:6333", index=self.collection)
        return self._document_store_cache

    def _document_from_chunk(self, chunk: Mapping[str, Any]) -> Any:
        meta = {
            "chunk_id": str(chunk.get("chunk_id", "")),
            "document_id": str(chunk.get("document_id", "")),
            "title": str(chunk.get("title", "")),
            "relative_path": str(chunk.get("relative_path", "")),
            "locator": str(chunk.get("locator", "")),
            "suffix": str(chunk.get("suffix", "")),
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

    def _chunks_from_document_store(self, document_store: Any) -> list[dict[str, Any]]:
        try:
            documents = document_store.filter_documents()
        except TypeError:
            documents = document_store.filter_documents(filters={})
        except AttributeError:
            return []
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
                    "title": str(meta.get("title", "")),
                    "relative_path": str(meta.get("relative_path", "")),
                    "locator": str(meta.get("locator", "")),
                    "suffix": str(meta.get("suffix", "")),
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
        backend = str(getattr(instructions, "bibliothekar_backend", "local") or "local").strip().casefold()
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
    backend = str(getattr(instructions, "bibliothekar_backend", "local") or "local").strip().casefold()
    collection = str(getattr(instructions, "bibliothekar_collection", "") or "teebotus_books")
    if not bool(getattr(instructions, "bibliothekar_enabled", True)):
        return BibliothekarServiceHealth(instance_name, backend, "disabled", collection=collection)
    if backend == "haystack":
        missing = [name for name in ("haystack", "qdrant_haystack") if not _module_available(name)]
        if missing:
            return BibliothekarServiceHealth(
                instance_name,
                "haystack",
                "unavailable",
                collection=collection,
                store="qdrant",
                error=f"missing optional dependency: {', '.join(missing)}",
            )
        return BibliothekarServiceHealth(instance_name, "haystack", "configured", collection=collection, store="qdrant")
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
