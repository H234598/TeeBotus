from __future__ import annotations

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


class BibliothekarService:
    def __init__(self, backend: BibliothekarBackend) -> None:
        self.backend = backend

    @classmethod
    def local(cls, instance_name: str, instances_dir: str | Path = "instances") -> BibliothekarService:
        return cls(LocalBibliothekarBackend(BibliothekarStore(instance_name, instances_dir)))

    @property
    def backend_name(self) -> str:
        return self.backend.backend_name

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


__all__ = [
    "BibliothekarBackend",
    "BibliothekarQuery",
    "BibliothekarService",
    "LocalBibliothekarBackend",
]
