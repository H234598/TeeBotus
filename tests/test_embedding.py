from __future__ import annotations

import json

import pytest

from TeeBotus.embedding import FakeEmbeddingProvider, HFEmbeddingProvider, KeywordRerankerProvider, check_embedding_provider
from TeeBotus.embedding.config import EmbeddingConfig, build_account_memory_embedding_provider, build_embedding_provider
from TeeBotus.embedding.qdrant_bibliothekar import QdrantBibliothekarIndex
from TeeBotus.embedding.qdrant_memory import QdrantMemoryIndex


class _Response:
    def __init__(self, payload: object, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def close(self) -> None:
        return None


def test_fake_embedding_provider_supports_batch_interface() -> None:
    provider = FakeEmbeddingProvider(dimensions=8)

    vectors = provider.embed_texts(["Schlaf", "Schlaf"], purpose="memory")

    assert len(vectors) == 2
    assert vectors[0] == vectors[1]
    assert len(vectors[0]) == 8
    assert provider.embed_text("Schlaf") == vectors[0]


def test_hf_embedding_provider_uses_injected_feature_extraction_opener() -> None:
    calls: list[dict[str, object]] = []

    def opener(request, *, timeout):
        calls.append(
            {
                "url": request.full_url,
                "timeout": timeout,
                "authorization": request.get_header("Authorization"),
                "body": json.loads(request.data.decode("utf-8")),
            }
        )
        return _Response([[0.1, 0.2], [0.3, 0.4]])

    provider = HFEmbeddingProvider(model_name="intfloat/multilingual-e5-small", dimensions=2, api_key="hf_TEST123456", timeout_seconds=5, opener=opener)

    vectors = provider.embed_texts(["eins", "zwei"], purpose="test")

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert calls == [
        {
            "url": "https://api-inference.huggingface.co/pipeline/feature-extraction/intfloat/multilingual-e5-small",
            "timeout": 5,
            "authorization": "Bearer hf_TEST123456",
            "body": {"inputs": ["eins", "zwei"], "options": {"wait_for_model": True}},
        }
    ]


def test_hf_embedding_provider_normalizes_openai_and_token_vector_shapes() -> None:
    openai_provider = HFEmbeddingProvider(
        dimensions=2,
        endpoint="http://127.0.0.1:8080/embeddings",
        opener=lambda _request, *, timeout: _Response({"data": [{"embedding": [0.1, 0.2]}]}),
    )
    token_provider = HFEmbeddingProvider(
        dimensions=2,
        opener=lambda _request, *, timeout: _Response([[[1.0, 3.0], [3.0, 5.0]]]),
    )

    assert openai_provider.embed_text("eins") == [0.1, 0.2]
    assert token_provider.embed_text("eins") == [2.0, 4.0]


def test_embedding_health_and_keyword_reranker_are_local() -> None:
    health = check_embedding_provider(FakeEmbeddingProvider(dimensions=8))
    reranker = KeywordRerankerProvider()

    ranked = reranker.rerank("Schlaf Therapie", ["Kaffee", "Therapie und Schlaf", "Schlaf"], top_k=2)

    assert health.ok is True
    assert health.status == "ready"
    assert [item.document for item in ranked] == ["Therapie und Schlaf", "Schlaf"]


def test_embedding_config_and_qdrant_wrapper_imports() -> None:
    config = EmbeddingConfig.from_mapping({"provider": "hf", "model": "intfloat/multilingual-e5-small", "dimensions": "384"})

    assert config.provider == "hf"
    assert config.model_name == "intfloat/multilingual-e5-small"
    assert config.dimensions == 384
    assert QdrantMemoryIndex.__name__ == "QdrantMemoryIndex"
    assert QdrantBibliothekarIndex.__name__ == "QdrantBibliothekarIndex"


def test_build_embedding_provider_keeps_local_hash_provider_offline() -> None:
    provider = build_embedding_provider(
        EmbeddingConfig(provider="local-hash", model_name="teebotus-account-memory-hash", dimensions=16)
    )

    assert isinstance(provider, FakeEmbeddingProvider)
    assert provider.model_name == "teebotus-account-memory-hash"
    assert len(provider.embed_text("Schlafroutine")) == 16


def test_build_embedding_provider_builds_hf_provider_from_config_env() -> None:
    provider = build_embedding_provider(
        EmbeddingConfig(
            provider="tei",
            model_name="intfloat/multilingual-e5-small",
            dimensions=384,
            endpoint="http://127.0.0.1:8080/embeddings",
            api_key_env="HF_TOKEN",
        ),
        env={"HF_TOKEN": "hf_TEST123456"},
    )

    assert isinstance(provider, HFEmbeddingProvider)
    assert provider.model_name == "intfloat/multilingual-e5-small"
    assert provider.dimensions == 384
    assert provider.endpoint == "http://127.0.0.1:8080/embeddings"
    assert provider.api_key == "hf_TEST123456"


def test_build_account_memory_embedding_provider_keeps_hash_local() -> None:
    provider = build_account_memory_embedding_provider(
        EmbeddingConfig(provider="hash", model_name="teebotus-account-memory-hash", dimensions=16)
    )

    assert isinstance(provider, FakeEmbeddingProvider)
    assert provider.model_name == "teebotus-account-memory-hash"


def test_build_account_memory_embedding_provider_allows_local_http_endpoint() -> None:
    provider = build_account_memory_embedding_provider(
        EmbeddingConfig(
            provider="tei",
            model_name="intfloat/multilingual-e5-small",
            dimensions=384,
            endpoint="http://localhost:8080/embeddings",
            api_key_env="HF_TOKEN",
        ),
        env={"HF_TOKEN": "hf_TEST123456"},
    )

    assert isinstance(provider, HFEmbeddingProvider)
    assert provider.endpoint == "http://localhost:8080/embeddings"
    assert provider.api_key == "hf_TEST123456"


def test_build_account_memory_embedding_provider_rejects_remote_defaults_and_hosts() -> None:
    with pytest.raises(ValueError, match="Account-memory embeddings require a local endpoint"):
        build_account_memory_embedding_provider(EmbeddingConfig(provider="hf", model_name="intfloat/multilingual-e5-small"))
    with pytest.raises(ValueError, match="must stay local"):
        build_account_memory_embedding_provider(
            EmbeddingConfig(
                provider="tei",
                model_name="intfloat/multilingual-e5-small",
                endpoint="https://api-inference.huggingface.co/embeddings",
            )
        )
    with pytest.raises(ValueError, match="must include an explicit port"):
        build_account_memory_embedding_provider(
            EmbeddingConfig(
                provider="openai-compatible",
                model_name="intfloat/multilingual-e5-small",
                endpoint="http://localhost/embeddings",
            )
        )


def test_build_embedding_provider_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unsupported embedding provider"):
        build_embedding_provider(EmbeddingConfig(provider="cloud_magic"))
