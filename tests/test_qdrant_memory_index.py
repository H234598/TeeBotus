from __future__ import annotations

import json
from urllib.parse import urlparse

from TeeBotus.embedding import FakeEmbeddingProvider
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, telegram_identity_key
from TeeBotus.runtime.qdrant import USER_MEMORY_QDRANT_EMBEDDING_DIMENSIONS, USER_MEMORY_QDRANT_EMBEDDING_MODEL
from TeeBotus.runtime.qdrant_memory import QdrantMemoryIndex, qdrant_memory_point_id


ACCOUNT_A = "a" * 128
ACCOUNT_B = "b" * 128


class _Response:
    def __init__(self, payload: dict[str, object] | None = None, status: int = 200) -> None:
        self.payload = {} if payload is None else payload
        self.status = status

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
        self.calls.append({"method": request.get_method(), "path": parsed.path, "query": parsed.query, "body": body})
        if parsed.path.endswith("/points") and request.get_method() == "PUT":
            for point in body["points"]:
                self.points[str(point["id"])] = dict(point)
            return _Response({"result": {"operation_id": 1, "status": "completed"}})
        if parsed.path.endswith("/points/search") and request.get_method() == "POST":
            return _Response({"result": self._search(body)})
        if parsed.path.endswith("/points/delete") and request.get_method() == "POST":
            self._delete(body)
            return _Response({"result": {"operation_id": 2, "status": "completed"}})
        raise AssertionError(f"unexpected fake Qdrant request: {request.get_method()} {request.full_url}")

    def _search(self, body: dict[str, object]) -> list[dict[str, object]]:
        query = body["vector"]
        must = body.get("filter", {}).get("must", []) if isinstance(body.get("filter"), dict) else []
        limit = int(body.get("limit", 5))
        matches: list[dict[str, object]] = []
        for point_id, point in self.points.items():
            payload = point.get("payload")
            if not isinstance(payload, dict):
                continue
            if not _payload_matches(payload, must):
                continue
            score = _dot(query, point["vector"])
            matches.append({"id": point_id, "score": score, "payload": payload})
        matches.sort(key=lambda item: item["score"], reverse=True)
        return matches[:limit]

    def _delete(self, body: dict[str, object]) -> None:
        points = body.get("points")
        if isinstance(points, list):
            for point_id in points:
                self.points.pop(str(point_id), None)
            return
        must = body.get("filter", {}).get("must", []) if isinstance(body.get("filter"), dict) else []
        for point_id, point in list(self.points.items()):
            payload = point.get("payload")
            if isinstance(payload, dict) and _payload_matches(payload, must):
                self.points.pop(point_id, None)


def test_qdrant_memory_index_indexes_searches_and_deletes_without_cleartext() -> None:
    fake_qdrant = _FakeQdrant()
    index = QdrantMemoryIndex(
        url="http://127.0.0.1:6333",
        opener=fake_qdrant,
        embedding_provider=FakeEmbeddingProvider(dimensions=16),
    )
    entry = {
        "id": "mem_sleep",
        "kind": "preference",
        "memory_type": "semantic",
        "user_text": "Schlaf und Therapie helfen mir abends.",
        "bot_text": "Kleine Abendroutine vereinbart.",
        "keywords": ["schlaf", "therapie", "abendroutine"],
        "importance": 0.8,
        "salience": 0.7,
        "created_at": "2026-06-16T10:00:00Z",
        "updated_at": "2026-06-16T10:00:00Z",
    }

    point_id = index.index_memory(instance_name="Depressionsbot", account_id=ACCOUNT_A, entry=entry)
    stored_json = json.dumps(fake_qdrant.points[point_id], ensure_ascii=False).casefold()

    assert point_id == qdrant_memory_point_id(instance_name="Depressionsbot", account_id=ACCOUNT_A, memory_id="mem_sleep")
    assert "schlaf und therapie" not in stored_json
    assert "abendroutine" not in stored_json
    assert "user_text" not in stored_json
    assert "bot_text" not in stored_json
    payload = fake_qdrant.points[point_id]["payload"]
    assert payload["memory_id"] == "mem_sleep"
    assert payload["account_id"] == ACCOUNT_A
    assert payload["instance_name"] == "Depressionsbot"
    assert payload["keyword_sha256"]

    results = index.search(instance_name="Depressionsbot", account_id=ACCOUNT_A, query="Schlaf", limit=3)

    assert [result.memory_id for result in results] == ["mem_sleep"]

    index.delete_memory(instance_name="Depressionsbot", account_id=ACCOUNT_A, memory_id="mem_sleep")

    assert fake_qdrant.points == {}


def test_qdrant_memory_index_default_embedding_matches_collection_contract() -> None:
    fake_qdrant = _FakeQdrant()
    index = QdrantMemoryIndex(url="http://127.0.0.1:6333", opener=fake_qdrant)

    point_id = index.index_memory(instance_name="Depressionsbot", account_id=ACCOUNT_A, entry={"id": "mem_sleep", "user_text": "Schlaf"})

    payload = fake_qdrant.points[point_id]["payload"]
    assert payload["embedding_model"] == USER_MEMORY_QDRANT_EMBEDDING_MODEL
    assert payload["embedding_dimensions"] == USER_MEMORY_QDRANT_EMBEDDING_DIMENSIONS
    assert len(fake_qdrant.points[point_id]["vector"]) == USER_MEMORY_QDRANT_EMBEDDING_DIMENSIONS


def test_qdrant_memory_search_is_scoped_by_instance_and_account() -> None:
    fake_qdrant = _FakeQdrant()
    index = QdrantMemoryIndex(url="http://127.0.0.1:6333", opener=fake_qdrant)
    index.index_memory(instance_name="Depressionsbot", account_id=ACCOUNT_A, entry={"id": "mem_a", "user_text": "Schlaf"})
    index.index_memory(instance_name="Depressionsbot", account_id=ACCOUNT_B, entry={"id": "mem_b", "user_text": "Schlaf"})
    index.index_memory(instance_name="Bote_der_Wahrheit", account_id=ACCOUNT_A, entry={"id": "mem_c", "user_text": "Schlaf"})

    results = index.search(instance_name="Depressionsbot", account_id=ACCOUNT_A, query="Schlaf", limit=10)

    assert [result.memory_id for result in results] == ["mem_a"]
    search_body = fake_qdrant.calls[-1]["body"]
    assert search_body["filter"]["must"] == [
        {"key": "instance_name", "match": {"value": "Depressionsbot"}},
        {"key": "account_id", "match": {"value": ACCOUNT_A}},
    ]


def test_qdrant_memory_delete_account_removes_only_matching_scope() -> None:
    fake_qdrant = _FakeQdrant()
    index = QdrantMemoryIndex(url="http://127.0.0.1:6333", opener=fake_qdrant)
    index.index_memory(instance_name="Depressionsbot", account_id=ACCOUNT_A, entry={"id": "mem_a", "user_text": "Schlaf"})
    index.index_memory(instance_name="Depressionsbot", account_id=ACCOUNT_B, entry={"id": "mem_b", "user_text": "Schlaf"})

    index.delete_account(instance_name="Depressionsbot", account_id=ACCOUNT_A)

    remaining_payloads = [point["payload"] for point in fake_qdrant.points.values()]
    assert [payload["memory_id"] for payload in remaining_payloads] == ["mem_b"]


def test_qdrant_memory_rebuild_uses_account_store_as_truth(tmp_path) -> None:
    fake_qdrant = _FakeQdrant()
    index = QdrantMemoryIndex(url="http://127.0.0.1:6333", opener=fake_qdrant)
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"a" * 32))
    account_id = store.resolve_or_create_account(telegram_identity_key(1234), display_label="Test")
    first_id = store.append_structured_memory_entry(account_id, {"id": "mem_one", "user_text": "Schlaf"})
    second_id = store.append_structured_memory_entry(account_id, {"id": "mem_two", "user_text": "Tagesstruktur"})
    old_point_id = index.index_memory(instance_name="Depressionsbot", account_id=account_id, entry={"id": "old", "user_text": "Alt"})

    rebuilt = index.rebuild(account_store=store, instance_name="Depressionsbot", account_id=account_id)

    assert old_point_id not in fake_qdrant.points
    assert set(rebuilt) == {
        qdrant_memory_point_id(instance_name="Depressionsbot", account_id=account_id, memory_id=first_id),
        qdrant_memory_point_id(instance_name="Depressionsbot", account_id=account_id, memory_id=second_id),
    }
    assert {point["payload"]["memory_id"] for point in fake_qdrant.points.values()} == {first_id, second_id}


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
