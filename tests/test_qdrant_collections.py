from __future__ import annotations

import json

from TeeBotus.runtime.accounts import ACCOUNT_MEMORY_EMBEDDING_DIMENSIONS
from TeeBotus.runtime.bibliothekar import DEFAULT_EMBEDDING_MODEL
from TeeBotus.runtime.qdrant import (
    DEFAULT_BIBLIOTHEKAR_EMBEDDING_DIMENSIONS,
    QDRANT_BIBLIOTHEKAR_COLLECTION,
    QDRANT_USER_MEMORY_COLLECTION,
    QdrantCollectionSpec,
    default_qdrant_collection_specs,
    ensure_collection,
    ensure_default_collections,
)


class _Response:
    status = 200

    def close(self) -> None:
        return None


def test_default_qdrant_collection_specs_prepare_usermemory_and_bibliothekar() -> None:
    user_memory, bibliothekar = default_qdrant_collection_specs()

    assert user_memory.name == QDRANT_USER_MEMORY_COLLECTION
    assert user_memory.vector_size == ACCOUNT_MEMORY_EMBEDDING_DIMENSIONS
    assert user_memory.distance == "Cosine"
    assert user_memory.embedding_model == "teebotus-account-memory-hash"
    assert bibliothekar.name == QDRANT_BIBLIOTHEKAR_COLLECTION
    assert bibliothekar.vector_size == DEFAULT_BIBLIOTHEKAR_EMBEDDING_DIMENSIONS
    assert bibliothekar.distance == "Cosine"
    assert bibliothekar.embedding_model == DEFAULT_EMBEDDING_MODEL


def test_ensure_collection_sends_idempotent_put_with_vector_schema() -> None:
    calls: list[tuple[str, str, dict[str, object]]] = []

    def opener(request, *, timeout):
        assert timeout > 0
        calls.append((request.get_method(), request.full_url, json.loads(request.data.decode("utf-8"))))
        return _Response()

    result = ensure_collection(
        QdrantCollectionSpec(name="teebotus_user_memory", vector_size=64, distance="cosine"),
        url="http://127.0.0.1:6333",
        opener=opener,
    )

    assert result.ok is True
    assert result.status == "ready"
    assert result.name == "teebotus_user_memory"
    assert calls == [
        (
            "PUT",
            "http://127.0.0.1:6333/collections/teebotus_user_memory",
            {"vectors": {"size": 64, "distance": "Cosine"}},
        )
    ]


def test_ensure_default_collections_prepares_both_collections() -> None:
    urls: list[str] = []

    def opener(request, *, timeout):
        assert timeout > 0
        urls.append(request.full_url)
        return _Response()

    results = ensure_default_collections(url="http://127.0.0.1:6333", opener=opener)

    assert [result.name for result in results] == [QDRANT_USER_MEMORY_COLLECTION, QDRANT_BIBLIOTHEKAR_COLLECTION]
    assert all(result.ok for result in results)
    assert urls == [
        "http://127.0.0.1:6333/collections/teebotus_user_memory",
        "http://127.0.0.1:6333/collections/teebotus_bibliothekar_chunks",
    ]


def test_ensure_collection_rejects_unsafe_name_before_http() -> None:
    def opener(_request, *, timeout):  # pragma: no cover - must not be called
        raise AssertionError("unsafe collection name should fail before HTTP")

    try:
        ensure_collection(QdrantCollectionSpec(name="../bad", vector_size=64), opener=opener)
    except ValueError as exc:
        assert "collection name" in str(exc)
    else:
        raise AssertionError("expected unsafe collection name to fail")


def test_ensure_collection_reports_unreachable_without_crashing() -> None:
    def opener(_request, *, timeout):
        assert timeout > 0
        raise OSError("connection refused")

    result = ensure_collection(QdrantCollectionSpec(name="teebotus_user_memory", vector_size=64), opener=opener)

    assert result.ok is False
    assert result.status == "unreachable"
    assert "connection refused" in result.error
