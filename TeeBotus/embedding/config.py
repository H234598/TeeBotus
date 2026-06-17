from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlparse

from TeeBotus.embedding.base import EmbeddingProvider
from TeeBotus.embedding.providers import FakeEmbeddingProvider, HFEmbeddingProvider


LOCAL_EMBEDDING_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
LOCAL_EMBEDDING_PROVIDERS = frozenset({"", "fake", "hash", "local", "local_hash", "deterministic"})
HTTP_EMBEDDING_PROVIDERS = frozenset(
    {"hf", "huggingface", "hugging_face", "tei", "text_embeddings_inference", "openai_compatible", "openai_like", "http"}
)


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
    if provider in LOCAL_EMBEDDING_PROVIDERS:
        return FakeEmbeddingProvider(model_name=config.model_name, dimensions=config.dimensions)
    if provider in HTTP_EMBEDDING_PROVIDERS:
        source_env = os.environ if env is None else env
        api_key = source_env.get(config.api_key_env, "") if config.api_key_env else ""
        return HFEmbeddingProvider(
            model_name=config.model_name,
            dimensions=config.dimensions,
            endpoint=config.endpoint,
            api_key=api_key,
        )
    raise ValueError(f"Unsupported embedding provider: {config.provider}")


def build_account_memory_embedding_provider(config: EmbeddingConfig, *, env: Mapping[str, str] | None = None) -> EmbeddingProvider:
    provider = str(config.provider or "").strip().casefold().replace("-", "_")
    if provider in LOCAL_EMBEDDING_PROVIDERS:
        return build_embedding_provider(config, env=env)
    if provider in HTTP_EMBEDDING_PROVIDERS:
        _validate_local_account_memory_embedding_endpoint(config.endpoint)
        return build_embedding_provider(config, env=env)
    raise ValueError(f"Unsupported embedding provider: {config.provider}")


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, parsed)


def _validate_local_account_memory_embedding_endpoint(endpoint: str) -> None:
    raw = str(endpoint or "").strip()
    if not raw:
        raise ValueError("Account-memory embeddings require a local endpoint or the local hash provider.")
    try:
        parsed = urlparse(raw)
    except ValueError as exc:
        raise ValueError("Account-memory embedding endpoint must be a valid URL.") from exc
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("Account-memory embedding endpoint must include scheme and host.")
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Account-memory embedding endpoint must use http or https.")
    host = (parsed.hostname or "").strip().casefold()
    if host not in LOCAL_EMBEDDING_HOSTS:
        raise ValueError("Account-memory embedding endpoint must stay local on 127.0.0.1, localhost or ::1.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Account-memory embedding endpoint must include a valid port if one is specified.") from exc
    if port is None:
        raise ValueError("Account-memory embedding endpoint must include an explicit port.")
    if parsed.username or parsed.password:
        raise ValueError("Account-memory embedding endpoint must not contain credentials.")
    if parsed.query or parsed.fragment:
        raise ValueError("Account-memory embedding endpoint must not contain query parameters or fragments.")
