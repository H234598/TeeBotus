from __future__ import annotations

import json
from urllib.parse import urlparse

from TeeBotus.embedding import FakeEmbeddingProvider
from TeeBotus.runtime.qdrant_bibliothekar import (
    BGE_M3_EMBEDDING_DIMENSIONS,
    BGE_M3_EMBEDDING_MODEL,
    QdrantBibliothekarIndex,
    bge_m3_embedding_provider,
    qdrant_bibliothekar_point_id,
)


class _Response:
    def __init__(self, payload: dict[str, object] | None = None) -> None:
        self.payload = {} if payload is None else payload
        self.status = 200

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def close(self) -> None:
        return None


class _FakeQdrant:
    def __init__(self) -> None:
        self.points: dict[str, dict[str, object]] = {}
        self.calls: list[dict[str, object]] = []

    def __call__(self, request, *, timeout):
        assert timeout > 0
        body = json.loads(request.data.decode("utf-8")) if request.data else {}
        parsed = urlparse(request.full_url)
        self.calls.append({"method": request.get_method(), "path": parsed.path, "body": body})
        if parsed.path.endswith("/points") and request.get_method() == "PUT":
            for point in body["points"]:
                self.points[str(point["id"])] = dict(point)
            return _Response({"result": {"status": "completed"}})
        if parsed.path.endswith("/points/search") and request.get_method() == "POST":
            return _Response({"result": self._search(body)})
        if parsed.path.endswith("/points/delete") and request.get_method() == "POST":
            self._delete(body)
            return _Response({"result": {"status": "completed"}})
        raise AssertionError(f"unexpected fake Qdrant request: {request.get_method()} {request.full_url}")

    def _search(self, body: dict[str, object]) -> list[dict[str, object]]:
        query = body["vector"]
        must = body.get("filter", {}).get("must", []) if isinstance(body.get("filter"), dict) else []
        results: list[dict[str, object]] = []
        for point_id, point in self.points.items():
            payload = point.get("payload")
            if not isinstance(payload, dict) or not _payload_matches(payload, must):
                continue
            results.append({"id": point_id, "score": _dot(query, point["vector"]), "payload": payload})
        results.sort(key=lambda item: item["score"], reverse=True)
        return results[: int(body.get("limit", 5))]

    def _delete(self, body: dict[str, object]) -> None:
        must = body.get("filter", {}).get("must", []) if isinstance(body.get("filter"), dict) else []
        for point_id, point in list(self.points.items()):
            payload = point.get("payload")
            if isinstance(payload, dict) and _payload_matches(payload, must):
                self.points.pop(point_id, None)


def test_qdrant_bibliothekar_index_indexes_test_chunks_without_chunk_text() -> None:
    fake_qdrant = _FakeQdrant()
    index = QdrantBibliothekarIndex(
        url="http://127.0.0.1:6333",
        opener=fake_qdrant,
        embedding_provider=FakeEmbeddingProvider(dimensions=16),
    )
    chunk = _chunk("chunk_sleep", text="Schlafhygiene und Tagesstruktur helfen bei depressiver Erschoepfung.")

    point_ids = index.index_chunks(instance_name="Depressionsbot", chunks=[chunk])

    assert point_ids == (qdrant_bibliothekar_point_id(instance_name="Depressionsbot", chunk_id="chunk_sleep"),)
    stored_json = json.dumps(fake_qdrant.points[point_ids[0]], ensure_ascii=False).casefold()
    assert "schlafhygiene und tagesstruktur" not in stored_json
    assert "text_sha256" in stored_json
    payload = fake_qdrant.points[point_ids[0]]["payload"]
    assert payload["chunk_id"] == "chunk_sleep"
    assert payload["title"] == "Therapiehandbuch"
    assert payload["relative_path"] == "therapie.txt"


def test_qdrant_bibliothekar_search_is_scoped_by_instance() -> None:
    fake_qdrant = _FakeQdrant()
    index = QdrantBibliothekarIndex(url="http://127.0.0.1:6333", opener=fake_qdrant, embedding_provider=FakeEmbeddingProvider(dimensions=16))
    index.index_chunks(instance_name="Depressionsbot", chunks=[_chunk("chunk_a", text="Schlaf")])
    index.index_chunks(instance_name="Bote_der_Wahrheit", chunks=[_chunk("chunk_b", text="Schlaf")])

    results = index.search(instance_name="Depressionsbot", query="Schlaf", limit=10)

    assert [result.chunk_id for result in results] == ["chunk_a"]
    search_body = fake_qdrant.calls[-1]["body"]
    assert search_body["filter"]["must"] == [{"key": "instance_name", "match": {"value": "Depressionsbot"}}]


def test_qdrant_bibliothekar_delete_instance_removes_only_matching_chunks() -> None:
    fake_qdrant = _FakeQdrant()
    index = QdrantBibliothekarIndex(url="http://127.0.0.1:6333", opener=fake_qdrant, embedding_provider=FakeEmbeddingProvider(dimensions=16))
    index.index_chunks(instance_name="Depressionsbot", chunks=[_chunk("chunk_a", text="Schlaf")])
    index.index_chunks(instance_name="Bote_der_Wahrheit", chunks=[_chunk("chunk_b", text="Schlaf")])

    index.delete_instance(instance_name="Depressionsbot")

    assert [point["payload"]["chunk_id"] for point in fake_qdrant.points.values()] == ["chunk_b"]


def test_bge_m3_embedding_provider_is_prepared_but_not_default() -> None:
    provider = bge_m3_embedding_provider()

    assert provider.model_name == BGE_M3_EMBEDDING_MODEL
    assert provider.dimensions == BGE_M3_EMBEDDING_DIMENSIONS


def _chunk(chunk_id: str, *, text: str) -> dict[str, object]:
    return {
        "chunk_id": chunk_id,
        "document_id": "doc_1",
        "source_id": "sha256:abc",
        "title": "Therapiehandbuch",
        "author": "Autor",
        "relative_path": "therapie.txt",
        "file_path": "therapie.txt",
        "file_sha256": "abc",
        "file_type": "txt",
        "language": "de",
        "locator": "Zeilen 1-1",
        "page_start": 1,
        "page_end": 1,
        "chapter": "",
        "section": "Zeilen 1-1",
        "license": "private",
        "ingested_at": "2026-06-16T10:00:00Z",
        "chunk_index": 1,
        "topics": ["schlaf"],
        "categories": ["therapie"],
        "text": text,
    }


def _payload_matches(payload: dict[str, object], must: list[dict[str, object]]) -> bool:
    for condition in must:
        key = condition.get("key")
        match = condition.get("match")
        expected = match.get("value") if isinstance(match, dict) else None
        if payload.get(key) != expected:
            return False
    return True


def _dot(left: object, right: object) -> float:
    if not isinstance(left, list) or not isinstance(right, list):
        return 0.0
    return float(sum(float(a) * float(b) for a, b in zip(left, right)))
