from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol

from TeeBotus.runtime.bibliothekar import (
    DEFAULT_MAX_CHUNKS,
    DEFAULT_MAX_PROMPT_CHARS,
    DEFAULT_MAX_QUOTE_CHARS,
    BibliothekarSelection,
    BibliothekarStore,
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


class HaystackBibliothekarBackend:
    backend_name = "haystack"

    def __init__(
        self,
        *,
        instance_name: str,
        instances_dir: str | Path = "instances",
        collection: str = "teebotus_books",
        fallback_store: BibliothekarStore | None = None,
    ) -> None:
        self.instance_name = str(instance_name or "default")
        self.instances_dir = Path(instances_dir)
        self.collection = str(collection or "teebotus_books").strip() or "teebotus_books"
        self.fallback_store = fallback_store or BibliothekarStore(self.instance_name, self.instances_dir)

    def search(self, query: BibliothekarQuery) -> BibliothekarSelection:
        if not self.available:
            return BibliothekarSelection("", ())
        # The full Haystack/Qdrant pipeline is intentionally added behind this
        # backend later. Until then, the existing local store remains the source
        # of truth and keeps the bot usable.
        return LocalBibliothekarBackend(self.fallback_store).search(query)

    @property
    def available(self) -> bool:
        return _module_available("haystack") and _module_available("qdrant_haystack")


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
