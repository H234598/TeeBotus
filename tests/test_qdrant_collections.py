from __future__ import annotations

import json

from TeeBotus.runtime.accounts import ACCOUNT_MEMORY_EMBEDDING_DIMENSIONS
from TeeBotus.runtime.qdrant import (
    BIBLIOTHEKAR_QDRANT_EMBEDDING_MODEL,
    DEFAULT_BIBLIOTHEKAR_EMBEDDING_DIMENSIONS,
    QDRANT_BIBLIOTHEKAR_COLLECTION,
    QDRANT_USER_MEMORY_COLLECTION,
    USER_MEMORY_QDRANT_EMBEDDING_DIMENSIONS,
    USER_MEMORY_QDRANT_EMBEDDING_MODEL,
    QdrantCollectionResult,
    QdrantCollectionSpec,
    QdrantHealth,
    check_collection,
    check_default_collections,
    default_qdrant_collection_specs,
    ensure_collection,
    ensure_default_collections,
    format_qdrant_collection_status_lines,
)


class _Response:
    def __init__(self, status: int = 200, payload: object | None = None) -> None:
        self.status = status
        self.payload = payload if payload is not None else {}

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def close(self) -> None:
        return None


def test_default_qdrant_collection_specs_prepare_usermemory_and_bibliothekar() -> None:
    user_memory, bibliothekar = default_qdrant_collection_specs()

    assert user_memory.name == QDRANT_USER_MEMORY_COLLECTION
    assert user_memory.vector_size == USER_MEMORY_QDRANT_EMBEDDING_DIMENSIONS
    assert user_memory.vector_size == ACCOUNT_MEMORY_EMBEDDING_DIMENSIONS
    assert user_memory.distance == "Cosine"
    assert user_memory.embedding_model == USER_MEMORY_QDRANT_EMBEDDING_MODEL
    assert bibliothekar.name == QDRANT_BIBLIOTHEKAR_COLLECTION
    assert bibliothekar.vector_size == DEFAULT_BIBLIOTHEKAR_EMBEDDING_DIMENSIONS
    assert bibliothekar.distance == "Cosine"
    assert bibliothekar.embedding_model == BIBLIOTHEKAR_QDRANT_EMBEDDING_MODEL


def test_default_qdrant_collection_specs_accept_usermemory_embedding_overrides() -> None:
    user_memory, _bibliothekar = default_qdrant_collection_specs(
        user_memory_vector_size=384,
        user_memory_embedding_model="intfloat/multilingual-e5-small",
    )

    assert user_memory.vector_size == 384
    assert user_memory.embedding_model == "intfloat/multilingual-e5-small"


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


def test_check_collection_uses_non_mutating_get() -> None:
    calls: list[tuple[str, str]] = []

    def opener(request, *, timeout):
        assert timeout > 0
        calls.append((request.get_method(), request.full_url))
        return _Response(200)

    result = check_collection(
        QdrantCollectionSpec(name="teebotus_user_memory", vector_size=64),
        url="http://127.0.0.1:6333",
        opener=opener,
    )

    assert result.ok is True
    assert result.status == "ready"
    assert calls == [("GET", "http://127.0.0.1:6333/collections/teebotus_user_memory")]


def test_check_collection_reports_vector_schema_mismatch() -> None:
    def opener(_request, *, timeout):
        assert timeout > 0
        return _Response(
            200,
            {
                "result": {
                    "config": {
                        "params": {
                            "vectors": {"size": 64, "distance": "Cosine"},
                        }
                    }
                }
            },
        )

    result = check_collection(
        QdrantCollectionSpec(name="teebotus_user_memory", vector_size=384),
        url="http://127.0.0.1:6333",
        opener=opener,
    )

    assert result.ok is False
    assert result.status == "schema_mismatch"
    assert result.actual_vector_size == 64
    assert result.error == "vector_size expected 384, got 64"


def test_check_default_collections_probes_both_without_creating() -> None:
    calls: list[tuple[str, str]] = []

    def opener(request, *, timeout):
        assert timeout > 0
        calls.append((request.get_method(), request.full_url))
        return _Response(200)

    results = check_default_collections(url="http://127.0.0.1:6333", opener=opener)

    assert [result.name for result in results] == [QDRANT_USER_MEMORY_COLLECTION, QDRANT_BIBLIOTHEKAR_COLLECTION]
    assert all(result.status == "ready" for result in results)
    assert calls == [
        ("GET", "http://127.0.0.1:6333/collections/teebotus_user_memory"),
        ("GET", "http://127.0.0.1:6333/collections/teebotus_bibliothekar_chunks"),
    ]


def test_check_default_collections_uses_supplied_specs() -> None:
    sizes: list[int] = []

    def opener(_request, *, timeout):
        assert timeout > 0
        return _Response(
            200,
            {
                "result": {
                    "config": {
                        "params": {
                            "vectors": {"size": sizes.pop(0), "distance": "Cosine"},
                        }
                    }
                }
            },
        )

    specs = default_qdrant_collection_specs(
        user_memory_vector_size=384,
        user_memory_embedding_model="intfloat/multilingual-e5-small",
    )
    sizes.extend([384, DEFAULT_BIBLIOTHEKAR_EMBEDDING_DIMENSIONS])

    results = check_default_collections(url="http://127.0.0.1:6333", opener=opener, specs=specs)

    assert all(result.ok for result in results)


def test_format_qdrant_collection_status_lines_reports_specs_when_unavailable() -> None:
    health = QdrantHealth(target="http://127.0.0.1:6333", status="unreachable", ok=False, error="connection refused")

    lines = format_qdrant_collection_status_lines(health)

    assert lines == (
        "qdrant_collection=teebotus_user_memory target=127.0.0.1:6333 status=unavailable "
        f"vector_size={USER_MEMORY_QDRANT_EMBEDDING_DIMENSIONS} embedding_model={USER_MEMORY_QDRANT_EMBEDDING_MODEL} error=connection refused",
        "qdrant_collection=teebotus_bibliothekar_chunks target=127.0.0.1:6333 status=unavailable "
        f"vector_size={DEFAULT_BIBLIOTHEKAR_EMBEDDING_DIMENSIONS} embedding_model={BIBLIOTHEKAR_QDRANT_EMBEDDING_MODEL} error=connection refused",
    )


def test_format_qdrant_collection_status_lines_uses_supplied_specs() -> None:
    health = QdrantHealth(target="http://127.0.0.1:6333", status="unreachable", ok=False, error="connection refused")
    specs = default_qdrant_collection_specs(
        user_memory_vector_size=384,
        user_memory_embedding_model="intfloat/multilingual-e5-small",
    )

    lines = format_qdrant_collection_status_lines(health, specs=specs)

    assert lines[0] == (
        "qdrant_collection=teebotus_user_memory target=127.0.0.1:6333 status=unavailable "
        "vector_size=384 embedding_model=intfloat/multilingual-e5-small error=connection refused"
    )


def test_format_qdrant_collection_status_lines_reports_checked_results() -> None:
    health = QdrantHealth(target="http://127.0.0.1:6333", status="reachable", ok=True)
    results = (
        QdrantCollectionResult(QDRANT_USER_MEMORY_COLLECTION, "http://127.0.0.1:6333", "ready", True),
        QdrantCollectionResult(QDRANT_BIBLIOTHEKAR_COLLECTION, "http://127.0.0.1:6333", "missing", False, "HTTP 404"),
    )

    lines = format_qdrant_collection_status_lines(health, collection_results=results)

    assert lines[0].startswith("qdrant_collection=teebotus_user_memory target=127.0.0.1:6333 status=ready")
    assert lines[1].startswith("qdrant_collection=teebotus_bibliothekar_chunks target=127.0.0.1:6333 status=missing")
    assert "error=HTTP 404" in lines[1]


def test_format_qdrant_collection_status_lines_reports_actual_vector_size_on_mismatch() -> None:
    health = QdrantHealth(target="http://127.0.0.1:6333", status="reachable", ok=True)
    results = (
        QdrantCollectionResult(
            QDRANT_USER_MEMORY_COLLECTION,
            "http://127.0.0.1:6333",
            "schema_mismatch",
            False,
            "vector_size expected 384, got 64",
            actual_vector_size=64,
        ),
    )
    specs = (QdrantCollectionSpec(QDRANT_USER_MEMORY_COLLECTION, 384, embedding_model="intfloat/multilingual-e5-small"),)

    lines = format_qdrant_collection_status_lines(health, collection_results=results, specs=specs)

    assert lines == (
        "qdrant_collection=teebotus_user_memory target=127.0.0.1:6333 status=schema_mismatch "
        "vector_size=384 embedding_model=intfloat/multilingual-e5-small actual_vector_size=64 "
        "error=vector_size expected 384, got 64",
    )


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
