from __future__ import annotations

from dataclasses import dataclass

from TeeBotus.embedding.base import EmbeddingProvider


@dataclass(frozen=True)
class EmbeddingProviderHealth:
    provider: str
    model: str
    dimensions: int
    status: str
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ready"


def check_embedding_provider(provider: EmbeddingProvider, *, purpose: str = "health") -> EmbeddingProviderHealth:
    try:
        vectors = provider.embed_texts(["health"], purpose=purpose)
        dimensions = int(getattr(provider, "dimensions", 0) or 0)
        if not vectors or len(vectors[0]) != dimensions:
            return EmbeddingProviderHealth(type(provider).__name__, provider.model_name, dimensions, "broken", "dimension mismatch")
        return EmbeddingProviderHealth(type(provider).__name__, provider.model_name, dimensions, "ready")
    except Exception as exc:  # noqa: BLE001 - health should be diagnostic and non-fatal.
        return EmbeddingProviderHealth(type(provider).__name__, getattr(provider, "model_name", ""), int(getattr(provider, "dimensions", 0) or 0), "unavailable", str(exc))
