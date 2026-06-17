from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping

from TeeBotus.embedding.base import EmbeddingProvider
from TeeBotus.embedding.providers import FakeEmbeddingProvider, HFEmbeddingProvider


@dataclass(frozen=True)
class EmbeddingConfig:
    provider: str = "fake"
    model_name: str = "teebotus-fake-hash-embedding-v1"
    dimensions: int = 64
    endpoint: str = ""
    api_key_env: str = ""

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "EmbeddingConfig":
        source = data or {}
        return cls(
            provider=str(source.get("provider") or "fake").strip().casefold(),
            model_name=str(source.get("model_name") or source.get("model") or "teebotus-fake-hash-embedding-v1").strip(),
            dimensions=_positive_int(source.get("dimensions"), default=64),
            endpoint=str(source.get("endpoint") or "").strip(),
            api_key_env=str(source.get("api_key_env") or "").strip(),
        )


def build_embedding_provider(config: EmbeddingConfig, *, env: Mapping[str, str] | None = None) -> EmbeddingProvider:
    provider = str(config.provider or "").strip().casefold().replace("-", "_")
    if provider in {"", "fake", "hash", "local", "local_hash", "deterministic"}:
        return FakeEmbeddingProvider(model_name=config.model_name, dimensions=config.dimensions)
    if provider in {"hf", "huggingface", "hugging_face", "tei", "text_embeddings_inference", "openai_compatible", "openai_like", "http"}:
        source_env = os.environ if env is None else env
        api_key = source_env.get(config.api_key_env, "") if config.api_key_env else ""
        return HFEmbeddingProvider(
            model_name=config.model_name,
            dimensions=config.dimensions,
            endpoint=config.endpoint,
            api_key=api_key,
        )
    raise ValueError(f"Unsupported embedding provider: {config.provider}")


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, parsed)
