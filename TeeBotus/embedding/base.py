from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class EmbeddingProvider(Protocol):
    model_name: str
    dimensions: int

    def embed_text(self, text: str) -> list[float]:
        ...

    def embed_texts(self, texts: list[str], *, purpose: str = "") -> list[list[float]]:
        ...


@dataclass(frozen=True)
class RerankResult:
    index: int
    document: str
    score: float


class RerankerProvider(Protocol):
    model_name: str

    def rerank(self, query: str, documents: list[str], *, top_k: int) -> list[RerankResult]:
        ...
