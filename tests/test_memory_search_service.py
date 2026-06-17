from __future__ import annotations

from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, telegram_identity_key
from TeeBotus.runtime.memory_search import (
    KeywordMemorySearch,
    MemoryCandidate,
    MemorySearchConfig,
    MemorySearchService,
    QdrantMemorySearch,
    merge_memory_candidates,
)
from TeeBotus.runtime.qdrant import QdrantError
from TeeBotus.runtime.qdrant_memory import QdrantMemoryResult


def test_memory_search_config_is_opt_in() -> None:
    assert MemorySearchConfig.from_mapping({}) == MemorySearchConfig()
    enabled = MemorySearchConfig.from_mapping({"semantic_enabled": "ja", "semantic_backend": "qdrant", "local_limit": "3"})

    assert enabled.semantic_enabled is True
    assert enabled.semantic_backend == "qdrant"
    assert enabled.local_limit == 3


def test_merge_memory_candidates_deduplicates_and_prefers_multi_source_hits() -> None:
    merged = merge_memory_candidates(
        [MemoryCandidate("mem_a", 0.8, ("local",)), MemoryCandidate("mem_b", 0.7, ("local",))],
        [MemoryCandidate("mem_a", 0.75, ("qdrant",)), MemoryCandidate("mem_c", 0.95, ("qdrant",))],
        limit=3,
    )

    assert [candidate.memory_id for candidate in merged] == ["mem_a", "mem_c", "mem_b"]
    assert merged[0].sources == ("local", "qdrant")
    assert merged[0].score > 0.8


def test_memory_search_service_uses_local_search_by_default(tmp_path) -> None:
    store, account_id = _store_with_entries(tmp_path)
    service = MemorySearchService(account_store=store, instance_name="Depressionsbot")

    result = service.search(account_id, "Schlaf", limit=2)

    assert result.semantic_used is False
    assert result.semantic_error == ""
    assert result.entries
    assert result.entries[0]["id"] == "mem_sleep"
    assert result.candidates[0].sources == ("local",)


def test_keyword_memory_search_returns_local_candidates_without_decrypting_qdrant(tmp_path) -> None:
    store, account_id = _store_with_entries(tmp_path)
    search = KeywordMemorySearch(store)

    candidates = search.search(account_id, "Schlaf", limit=1)

    assert [candidate.memory_id for candidate in candidates] == ["mem_sleep"]
    assert candidates[0].sources == ("local",)


def test_memory_search_service_uses_qdrant_only_when_enabled(tmp_path) -> None:
    store, account_id = _store_with_entries(tmp_path)
    semantic_index = _FakeSemanticIndex(
        [
            QdrantMemoryResult(
                memory_id="mem_plan",
                account_id=account_id,
                instance_name="Depressionsbot",
                score=2.0,
                payload={"memory_id": "mem_plan", "account_id": account_id, "instance_name": "Depressionsbot"},
            )
        ]
    )
    service = MemorySearchService(
        account_store=store,
        instance_name="Depressionsbot",
        config=MemorySearchConfig(semantic_enabled=True, semantic_backend="qdrant"),
        qdrant_index=semantic_index,
    )

    result = service.search(account_id, "Tagesstruktur", limit=2)

    assert semantic_index.calls == [("Depressionsbot", account_id, "Tagesstruktur", 8)]
    assert result.semantic_used is True
    assert result.semantic_error == ""
    assert result.entries[0]["id"] == "mem_plan"
    assert "qdrant" in result.candidates[0].sources


def test_memory_search_service_filters_stale_qdrant_candidates_through_account_store(tmp_path) -> None:
    store, account_id = _store_with_entries(tmp_path)
    semantic_index = _FakeSemanticIndex(
        [
            QdrantMemoryResult(
                memory_id="mem_missing",
                account_id=account_id,
                instance_name="Depressionsbot",
                score=3.0,
                payload={"memory_id": "mem_missing", "account_id": account_id, "instance_name": "Depressionsbot"},
            ),
            QdrantMemoryResult(
                memory_id="mem_plan",
                account_id=account_id,
                instance_name="Depressionsbot",
                score=2.0,
                payload={"memory_id": "mem_plan", "account_id": account_id, "instance_name": "Depressionsbot"},
            ),
        ]
    )
    service = MemorySearchService(
        account_store=store,
        instance_name="Depressionsbot",
        config=MemorySearchConfig(semantic_enabled=True, semantic_backend="qdrant", local_limit=1),
        qdrant_index=semantic_index,
    )

    result = service.search(account_id, "Tagesstruktur", limit=2, exclude_ids=("mem_sleep",))

    assert [entry["id"] for entry in result.entries] == ["mem_plan"]
    assert [candidate.memory_id for candidate in result.candidates] == ["mem_plan"]
    assert "qdrant" in result.candidates[0].sources
    entries_by_id = {entry["id"]: entry for entry in store.read_memory_entries(account_id)}
    assert entries_by_id["mem_plan"]["access_count"] == 1
    assert entries_by_id["mem_plan"]["last_accessed_at"]
    assert entries_by_id["mem_sleep"].get("access_count") in (None, 0)
    assert entries_by_id["mem_sleep"].get("last_accessed_at") in (None, "")


def test_memory_search_service_refills_limit_after_dropping_stale_qdrant_candidates(tmp_path) -> None:
    store, account_id = _store_with_entries(tmp_path)
    semantic_index = _FakeSemanticIndex(
        [
            QdrantMemoryResult(
                memory_id="mem_missing",
                account_id=account_id,
                instance_name="Depressionsbot",
                score=3.0,
                payload={"memory_id": "mem_missing", "account_id": account_id, "instance_name": "Depressionsbot"},
            ),
            QdrantMemoryResult(
                memory_id="mem_plan",
                account_id=account_id,
                instance_name="Depressionsbot",
                score=2.0,
                payload={"memory_id": "mem_plan", "account_id": account_id, "instance_name": "Depressionsbot"},
            ),
        ]
    )
    service = MemorySearchService(
        account_store=store,
        instance_name="Depressionsbot",
        config=MemorySearchConfig(semantic_enabled=True, semantic_backend="qdrant", local_limit=1, semantic_limit=2),
        qdrant_index=semantic_index,
    )

    result = service.search(account_id, "Schlaf", limit=2)

    assert [candidate.memory_id for candidate in result.candidates] == ["mem_plan", "mem_sleep"]
    assert [entry["id"] for entry in result.entries] == ["mem_plan", "mem_sleep"]


def test_qdrant_memory_search_wraps_semantic_results_and_respects_excludes(tmp_path) -> None:
    _store, account_id = _store_with_entries(tmp_path)
    semantic_index = _FakeSemanticIndex(
        [
            QdrantMemoryResult(
                memory_id="mem_plan",
                account_id=account_id,
                instance_name="Depressionsbot",
                score=2.0,
                payload={},
            ),
            QdrantMemoryResult(
                memory_id="mem_sleep",
                account_id=account_id,
                instance_name="Depressionsbot",
                score=1.5,
                payload={},
            ),
        ]
    )
    search = QdrantMemorySearch(semantic_index, "Depressionsbot")

    candidates = search.search(account_id, "Tagesstruktur", limit=5, exclude_ids=("mem_sleep",))

    assert [candidate.memory_id for candidate in candidates] == ["mem_plan"]
    assert candidates[0].sources == ("qdrant",)
    assert semantic_index.calls == [("Depressionsbot", account_id, "Tagesstruktur", 5)]


def test_memory_search_service_falls_back_to_local_when_qdrant_fails(tmp_path) -> None:
    store, account_id = _store_with_entries(tmp_path)
    service = MemorySearchService(
        account_store=store,
        instance_name="Depressionsbot",
        config=MemorySearchConfig(semantic_enabled=True, semantic_backend="qdrant"),
        qdrant_index=_FailingSemanticIndex(),
    )

    result = service.search(account_id, "Schlaf", limit=2)

    assert result.semantic_used is True
    assert "qdrant down" in result.semantic_error
    assert result.entries[0]["id"] == "mem_sleep"
    assert result.candidates[0].sources == ("local",)


def test_account_store_read_memory_entries_by_ids_preserves_requested_order(tmp_path) -> None:
    store, account_id = _store_with_entries(tmp_path)

    rows = store.read_memory_entries_by_ids(account_id, ["mem_plan", "missing", "mem_sleep"])

    assert [row["id"] for row in rows] == ["mem_plan", "mem_sleep"]


class _FakeSemanticIndex:
    def __init__(self, results: list[QdrantMemoryResult]) -> None:
        self.results = tuple(results)
        self.calls: list[tuple[str, str, str, int]] = []

    def search(self, *, instance_name: str, account_id: str, query: str, limit: int):
        self.calls.append((instance_name, account_id, query, limit))
        return self.results


class _FailingSemanticIndex:
    def search(self, **_kwargs):
        raise QdrantError("qdrant down")


def _store_with_entries(tmp_path) -> tuple[AccountStore, str]:
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"a" * 32))
    account_id = store.resolve_or_create_account(telegram_identity_key(1234), display_label="Test")
    store.append_structured_memory_entry(
        account_id,
        {
            "id": "mem_sleep",
            "kind": "preference",
            "memory_type": "semantic",
            "user_text": "Schlaf und Abendroutine sind wichtig.",
            "keywords": ["schlaf", "abendroutine"],
        },
    )
    store.append_structured_memory_entry(
        account_id,
        {
            "id": "mem_plan",
            "kind": "plan",
            "memory_type": "procedural",
            "user_text": "Tagesstruktur mit Spaziergang planen.",
            "keywords": ["tagesstruktur", "spaziergang"],
        },
    )
    return store, account_id
