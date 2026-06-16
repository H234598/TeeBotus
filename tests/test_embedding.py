from __future__ import annotations

import json

from TeeBotus.embedding import FakeEmbeddingProvider, HFEmbeddingProvider, KeywordRerankerProvider, check_embedding_provider
from TeeBotus.embedding.config import EmbeddingConfig
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
