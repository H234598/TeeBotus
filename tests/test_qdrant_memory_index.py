from __future__ import annotations

import json
from urllib.parse import urlparse

import pytest

from TeeBotus.embedding import FakeEmbeddingProvider
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, telegram_identity_key
from TeeBotus.runtime.qdrant import USER_MEMORY_QDRANT_EMBEDDING_DIMENSIONS, USER_MEMORY_QDRANT_EMBEDDING_MODEL
from TeeBotus.runtime.qdrant_memory import (
    QDRANT_MEMORY_PAYLOAD_SCHEMA,
    QDRANT_MEMORY_PAYLOAD_SCHEMA_VERSION,
    QDRANT_MEMORY_RESULT_PAYLOAD_KEYS,
    QdrantMemoryIndex,
    qdrant_memory_point_id,
)


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
    assert payload["schema_version"] == QDRANT_MEMORY_PAYLOAD_SCHEMA_VERSION
    assert payload["account_scope"]
    assert payload["account_scope"] != ACCOUNT_A
    assert "account_id" not in payload
    assert payload["instance_name"] == "Depressionsbot"
    assert ACCOUNT_A not in stored_json
    assert "source_sha256" not in payload
    assert "keyword_sha256" not in payload
    assert "kind" not in payload
    assert "memory_type" not in payload
    assert "importance" not in payload
    assert "salience" not in payload
    assert "created_at" not in payload
    assert "updated_at" not in payload

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
    point_id = index.index_memory(instance_name="Depressionsbot", account_id=ACCOUNT_A, entry={"id": "mem_a", "user_text": "Schlaf"})
    index.index_memory(instance_name="Depressionsbot", account_id=ACCOUNT_B, entry={"id": "mem_b", "user_text": "Schlaf"})
    index.index_memory(instance_name="Bote_der_Wahrheit", account_id=ACCOUNT_A, entry={"id": "mem_c", "user_text": "Schlaf"})

    results = index.search(instance_name="Depressionsbot", account_id=ACCOUNT_A, query="Schlaf", limit=10)

    assert [result.memory_id for result in results] == ["mem_a"]
    payload = fake_qdrant.points[point_id]["payload"]
    search_body = fake_qdrant.calls[-1]["body"]
    assert ACCOUNT_A not in json.dumps(search_body, ensure_ascii=False)
    assert search_body["filter"]["must"] == [
        {"key": "instance_name", "match": {"value": "Depressionsbot"}},
        {"key": "schema", "match": {"value": QDRANT_MEMORY_PAYLOAD_SCHEMA}},
        {"key": "account_scope", "match": {"value": payload["account_scope"]}},
        {"key": "schema_version", "match": {"value": QDRANT_MEMORY_PAYLOAD_SCHEMA_VERSION}},
        {"key": "embedding_model", "match": {"value": USER_MEMORY_QDRANT_EMBEDDING_MODEL}},
        {"key": "embedding_dimensions", "match": {"value": USER_MEMORY_QDRANT_EMBEDDING_DIMENSIONS}},
    ]


def test_qdrant_memory_search_filters_stale_vectors_after_embedding_model_change() -> None:
    fake_qdrant = _FakeQdrant()
    old_index = QdrantMemoryIndex(
        url="http://127.0.0.1:6333",
        opener=fake_qdrant,
        embedding_provider=FakeEmbeddingProvider(model_name="old-memory-model", dimensions=16),
    )
    new_index = QdrantMemoryIndex(
        url="http://127.0.0.1:6333",
        opener=fake_qdrant,
        embedding_provider=FakeEmbeddingProvider(model_name="new-memory-model", dimensions=16),
    )
    old_index.index_memory(instance_name="Depressionsbot", account_id=ACCOUNT_A, entry={"id": "mem_old", "user_text": "Schlaf"})
    new_index.index_memory(instance_name="Depressionsbot", account_id=ACCOUNT_A, entry={"id": "mem_new", "user_text": "Schlaf"})
    wrong_schema_point = new_index.index_memory(instance_name="Depressionsbot", account_id=ACCOUNT_A, entry={"id": "mem_wrong_schema", "user_text": "Schlaf"})
    fake_qdrant.points[wrong_schema_point]["payload"]["schema"] = "other_payload_schema"

    results = new_index.search(instance_name="Depressionsbot", account_id=ACCOUNT_A, query="Schlaf", limit=10)

    assert [result.memory_id for result in results] == ["mem_new"]
    search_body = fake_qdrant.calls[-1]["body"]
    assert {"key": "schema_version", "match": {"value": QDRANT_MEMORY_PAYLOAD_SCHEMA_VERSION}} in search_body["filter"]["must"]
    assert {"key": "embedding_model", "match": {"value": "new-memory-model"}} in search_body["filter"]["must"]
    assert {"key": "embedding_dimensions", "match": {"value": 16}} in search_body["filter"]["must"]


def test_qdrant_memory_search_rejects_stale_results_even_if_backend_filter_leaks() -> None:
    class _LeakyQdrant(_FakeQdrant):
        def _search(self, body: dict[str, object]) -> list[dict[str, object]]:
            query = body["vector"]
            matches = [
                {"id": point_id, "score": _dot(query, point["vector"]), "payload": point["payload"]}
                for point_id, point in self.points.items()
                if isinstance(point.get("payload"), dict)
            ]
            matches.sort(key=lambda item: item["score"], reverse=True)
            return matches[: int(body.get("limit", 5))]

    fake_qdrant = _LeakyQdrant()
    old_index = QdrantMemoryIndex(
        url="http://127.0.0.1:6333",
        opener=fake_qdrant,
        embedding_provider=FakeEmbeddingProvider(model_name="old-memory-model", dimensions=16),
    )
    new_index = QdrantMemoryIndex(
        url="http://127.0.0.1:6333",
        opener=fake_qdrant,
        embedding_provider=FakeEmbeddingProvider(model_name="new-memory-model", dimensions=16),
    )
    old_index.index_memory(instance_name="Depressionsbot", account_id=ACCOUNT_A, entry={"id": "mem_old", "user_text": "Schlaf"})
    new_index.index_memory(instance_name="Depressionsbot", account_id=ACCOUNT_A, entry={"id": "mem_new", "user_text": "Schlaf"})

    results = new_index.search(instance_name="Depressionsbot", account_id=ACCOUNT_A, query="Schlaf", limit=10)

    assert [result.memory_id for result in results] == ["mem_new"]


def test_qdrant_memory_search_filters_stale_vectors_after_payload_schema_change() -> None:
    fake_qdrant = _FakeQdrant()
    index = QdrantMemoryIndex(url="http://127.0.0.1:6333", opener=fake_qdrant)
    stale_point_id = index.index_memory(
        instance_name="Depressionsbot",
        account_id=ACCOUNT_A,
        entry={"id": "mem_stale", "user_text": "Schlaf"},
    )
    index.index_memory(instance_name="Depressionsbot", account_id=ACCOUNT_A, entry={"id": "mem_current", "user_text": "Schlaf"})
    fake_qdrant.points[stale_point_id]["payload"]["schema_version"] = 0

    results = index.search(instance_name="Depressionsbot", account_id=ACCOUNT_A, query="Schlaf", limit=10)

    assert [result.memory_id for result in results] == ["mem_current"]


def test_qdrant_memory_search_sanitizes_result_payloads_even_if_backend_returns_extra_fields() -> None:
    fake_qdrant = _FakeQdrant()
    index = QdrantMemoryIndex(url="http://127.0.0.1:6333", opener=fake_qdrant)
    point_id = index.index_memory(
        instance_name="Depressionsbot",
        account_id=ACCOUNT_A,
        entry={"id": "mem_sensitive", "user_text": "Privater Inhalt"},
    )
    fake_qdrant.points[point_id]["payload"].update(
        {
            "account_id": ACCOUNT_A,
            "user_text": "Privater Inhalt",
            "clinical_category": "risk",
            "created_at": "2026-06-16T10:00:00Z",
        }
    )

    results = index.search(instance_name="Depressionsbot", account_id=ACCOUNT_A, query="Privat", limit=1)

    assert [result.memory_id for result in results] == ["mem_sensitive"]
    assert set(results[0].payload) == QDRANT_MEMORY_RESULT_PAYLOAD_KEYS
    result_json = json.dumps(results[0].payload, ensure_ascii=False).casefold()
    assert ACCOUNT_A not in result_json
    assert "privater inhalt" not in result_json
    assert "clinical_category" not in result_json
    assert "2026-06" not in result_json


def test_qdrant_memory_payload_excludes_messenger_identity_fields() -> None:
    fake_qdrant = _FakeQdrant()
    index = QdrantMemoryIndex(url="http://127.0.0.1:6333", opener=fake_qdrant)
    point_id = index.index_memory(
        instance_name="Depressionsbot",
        account_id=ACCOUNT_A,
        entry={
            "id": "mem_identity",
            "user_text": "Privater Inhalt",
            "telegram_user_id": "123456",
            "telegram_chat_id": "654321",
            "matrix_user_id": "@user:example.test",
            "signal_source_uuid": "source-uuid",
            "provider_user_id": "provider-user",
        },
    )

    stored_json = json.dumps(fake_qdrant.points[point_id]["payload"], ensure_ascii=False).casefold()

    assert "telegram" not in stored_json
    assert "matrix" not in stored_json
    assert "signal" not in stored_json
    assert "provider-user" not in stored_json
    assert "privater inhalt" not in stored_json


def test_qdrant_memory_payload_excludes_clinical_and_temporal_metadata() -> None:
    fake_qdrant = _FakeQdrant()
    index = QdrantMemoryIndex(url="http://127.0.0.1:6333", opener=fake_qdrant)
    point_id = index.index_memory(
        instance_name="Depressionsbot",
        account_id=ACCOUNT_A,
        entry={
            "id": "mem_sensitive_metadata",
            "kind": "suicidal_ideation",
            "memory_type": "risk_signal",
            "importance": 9,
            "salience": 10,
            "created_at": "2026-06-16T10:00:00Z",
            "updated_at": "2026-06-17T10:00:00Z",
            "valid_from": "2026-06-16",
            "valid_to": "2026-06-18",
            "user_text": "Privater Inhalt",
        },
    )

    payload = fake_qdrant.points[point_id]["payload"]
    stored_json = json.dumps(payload, ensure_ascii=False).casefold()

    assert set(payload) == {
        "schema",
        "schema_version",
        "instance_name",
        "account_scope",
        "memory_id",
        "embedding_model",
        "embedding_dimensions",
    }
    assert "suicidal_ideation" not in stored_json
    assert "risk_signal" not in stored_json
    assert "2026-06" not in stored_json
    assert "privater inhalt" not in stored_json


def test_qdrant_memory_delete_account_removes_only_matching_scope() -> None:
    fake_qdrant = _FakeQdrant()
    index = QdrantMemoryIndex(url="http://127.0.0.1:6333", opener=fake_qdrant)
    point_a = index.index_memory(instance_name="Depressionsbot", account_id=ACCOUNT_A, entry={"id": "mem_a", "user_text": "Schlaf"})
    point_b = index.index_memory(instance_name="Depressionsbot", account_id=ACCOUNT_B, entry={"id": "mem_b", "user_text": "Schlaf"})
    point_other_instance = index.index_memory(instance_name="Bote_der_Wahrheit", account_id=ACCOUNT_A, entry={"id": "mem_other", "user_text": "Schlaf"})
    point_other_schema = index.index_memory(instance_name="Depressionsbot", account_id=ACCOUNT_A, entry={"id": "mem_other_schema", "user_text": "Schlaf"})
    fake_qdrant.points[point_other_schema]["payload"]["schema"] = "other_payload_schema"
    scope_a = fake_qdrant.points[point_a]["payload"]["account_scope"]
    scope_b = fake_qdrant.points[point_b]["payload"]["account_scope"]

    index.delete_account(instance_name="Depressionsbot", account_id=ACCOUNT_A)

    remaining_payloads = [point["payload"] for point in fake_qdrant.points.values()]
    assert [payload["memory_id"] for payload in remaining_payloads] == ["mem_b", "mem_other"]
    assert point_other_instance in fake_qdrant.points
    current_delete_body = fake_qdrant.calls[-1]["body"]
    assert ACCOUNT_A not in json.dumps(current_delete_body, ensure_ascii=False)
    assert {"key": "schema", "match": {"value": QDRANT_MEMORY_PAYLOAD_SCHEMA}} not in current_delete_body["filter"]["must"]
    assert {"key": "account_scope", "match": {"value": scope_a}} in current_delete_body["filter"]["must"]
    assert {"key": "account_scope", "match": {"value": scope_b}} not in current_delete_body["filter"]["must"]


def test_qdrant_memory_delete_account_skips_legacy_raw_account_payloads_by_default() -> None:
    fake_qdrant = _FakeQdrant()
    index = QdrantMemoryIndex(url="http://127.0.0.1:6333", opener=fake_qdrant)
    legacy_point_id = "legacy-a"
    fake_qdrant.points[legacy_point_id] = {
        "id": legacy_point_id,
        "vector": [0.0] * USER_MEMORY_QDRANT_EMBEDDING_DIMENSIONS,
        "payload": {
            "schema": "teebotus_qdrant_memory_v1",
            "schema_version": 2,
            "instance_name": "Depressionsbot",
            "account_id": ACCOUNT_A,
            "memory_id": "legacy_mem",
        },
    }

    index.delete_account(instance_name="Depressionsbot", account_id=ACCOUNT_A)

    assert legacy_point_id in fake_qdrant.points
    assert ACCOUNT_A not in json.dumps(fake_qdrant.calls[-1]["body"], ensure_ascii=False)


def test_qdrant_memory_delete_account_can_explicitly_remove_legacy_raw_account_payloads() -> None:
    fake_qdrant = _FakeQdrant()
    index = QdrantMemoryIndex(url="http://127.0.0.1:6333", opener=fake_qdrant)
    legacy_point_id = "legacy-a"
    schema_less_legacy_point_id = "legacy-schema-less"
    fake_qdrant.points[legacy_point_id] = {
        "id": legacy_point_id,
        "vector": [0.0] * USER_MEMORY_QDRANT_EMBEDDING_DIMENSIONS,
        "payload": {
            "schema": "teebotus_qdrant_memory_v1",
            "schema_version": 2,
            "instance_name": "Depressionsbot",
            "account_id": ACCOUNT_A,
            "memory_id": "legacy_mem",
        },
    }
    fake_qdrant.points[schema_less_legacy_point_id] = {
        "id": schema_less_legacy_point_id,
        "vector": [0.0] * USER_MEMORY_QDRANT_EMBEDDING_DIMENSIONS,
        "payload": {
            "instance_name": "Depressionsbot",
            "account_id": ACCOUNT_A,
            "memory_id": "schema_less_legacy_mem",
        },
    }

    index.delete_account(
        instance_name="Depressionsbot",
        account_id=ACCOUNT_A,
        include_legacy_raw_account_id_cleanup=True,
    )

    assert legacy_point_id not in fake_qdrant.points
    assert schema_less_legacy_point_id not in fake_qdrant.points
    assert {"key": "schema", "match": {"value": QDRANT_MEMORY_PAYLOAD_SCHEMA}} not in fake_qdrant.calls[-1]["body"]["filter"]["must"]
    assert {"key": "account_id", "match": {"value": ACCOUNT_A}} in fake_qdrant.calls[-1]["body"]["filter"]["must"]


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
    upsert_calls = [call for call in fake_qdrant.calls if call["method"] == "PUT" and call["path"] == "/collections/teebotus_user_memory/points"]
    assert len(upsert_calls[-1]["body"]["points"]) == 2


def test_qdrant_memory_rebuild_clears_empty_account_cache(tmp_path) -> None:
    fake_qdrant = _FakeQdrant()
    index = QdrantMemoryIndex(url="http://127.0.0.1:6333", opener=fake_qdrant)
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"a" * 32))
    account_id = store.resolve_or_create_account(telegram_identity_key(1234), display_label="Test")
    old_point_id = index.index_memory(instance_name="Depressionsbot", account_id=account_id, entry={"id": "old", "user_text": "Alt"})

    rebuilt = index.rebuild(account_store=store, instance_name="Depressionsbot", account_id=account_id)

    assert rebuilt == ()
    assert old_point_id not in fake_qdrant.points
    upsert_calls = [call for call in fake_qdrant.calls if call["method"] == "PUT" and call["path"] == "/collections/teebotus_user_memory/points"]
    assert len(upsert_calls) == 1


def test_qdrant_memory_rebuild_preserves_cache_when_account_store_is_unreadable() -> None:
    fake_qdrant = _FakeQdrant()
    index = QdrantMemoryIndex(url="http://127.0.0.1:6333", opener=fake_qdrant)
    old_point_id = index.index_memory(instance_name="Depressionsbot", account_id=ACCOUNT_A, entry={"id": "old", "user_text": "Alt"})

    class BrokenAccountStore:
        def read_memory_entries(self, _account_id):
            raise RuntimeError("account store unreadable")

    with pytest.raises(RuntimeError, match="account store unreadable"):
        index.rebuild(account_store=BrokenAccountStore(), instance_name="Depressionsbot", account_id=ACCOUNT_A)  # type: ignore[arg-type]

    assert old_point_id in fake_qdrant.points
    assert all(call["path"] != "/collections/teebotus_user_memory/points/delete" for call in fake_qdrant.calls)


def test_qdrant_memory_rebuild_preserves_cache_when_entry_is_not_indexable() -> None:
    fake_qdrant = _FakeQdrant()
    index = QdrantMemoryIndex(url="http://127.0.0.1:6333", opener=fake_qdrant)
    old_point_id = index.index_memory(instance_name="Depressionsbot", account_id=ACCOUNT_A, entry={"id": "old", "user_text": "Alt"})

    class BrokenEntryStore:
        def read_memory_entries(self, _account_id):
            return [{"user_text": "missing id"}]

    with pytest.raises(ValueError, match="memory entry must contain id"):
        index.rebuild(account_store=BrokenEntryStore(), instance_name="Depressionsbot", account_id=ACCOUNT_A)  # type: ignore[arg-type]

    assert old_point_id in fake_qdrant.points
    assert all(call["path"] != "/collections/teebotus_user_memory/points/delete" for call in fake_qdrant.calls)


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
