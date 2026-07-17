from __future__ import annotations

from types import SimpleNamespace

from TeeBotus.instructions import BotInstructions
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, telegram_identity_key
from TeeBotus.runtime.engine import _build_bibliothekar_context, _build_working_memory_context, _select_account_memory


def test_select_account_memory_falls_back_to_local_when_semantic_provider_is_invalid(tmp_path) -> None:
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
    instructions = BotInstructions(
        user_memory_enabled=True,
        memory_search_semantic_enabled=True,
        memory_search_semantic_backend="qdrant",
        memory_search_embedding_provider="cloud_magic",
    )

    selection = _select_account_memory(store, account_id, instructions, "Schlaf")

    assert "Schlaf und Abendroutine" in selection.prompt_text


def test_select_account_memory_falls_back_to_local_when_semantic_provider_would_be_remote(tmp_path) -> None:
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"a" * 32))
    account_id = store.resolve_or_create_account(telegram_identity_key(1234), display_label="Test")
    store.append_structured_memory_entry(
        account_id,
        {
            "id": "mem_sleep",
            "kind": "preference",
            "memory_type": "semantic",
            "user_text": "Lokale Transkription und Schlafroutine sind wichtig.",
            "keywords": ["lokal", "schlafroutine"],
        },
    )
    instructions = BotInstructions(
        user_memory_enabled=True,
        memory_search_semantic_enabled=True,
        memory_search_semantic_backend="qdrant",
        memory_search_embedding_provider="hf",
        memory_search_embedding_model="intfloat/multilingual-e5-small",
        memory_search_embedding_endpoint="",
    )

    selection = _select_account_memory(store, account_id, instructions, "Schlafroutine")

    assert "Lokale Transkription und Schlafroutine" in selection.prompt_text


def test_select_account_memory_honors_zero_source_limits(tmp_path, monkeypatch) -> None:
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
    calls: list[str] = []

    class _UnexpectedQdrantCall:
        def __init__(self, **_kwargs) -> None:
            pass

        def search(self, **_kwargs):  # pragma: no cover - zero limit must short-circuit first
            calls.append("search")
            raise AssertionError("zero semantic limit must not query Qdrant")

    monkeypatch.setattr("TeeBotus.runtime.engine.QdrantMemoryIndex", _UnexpectedQdrantCall)
    instructions = BotInstructions(
        user_memory_enabled=True,
        memory_search_semantic_enabled=True,
        memory_search_semantic_backend="qdrant",
        memory_search_embedding_provider="hash",
        memory_search_local_limit=0,
        memory_search_semantic_limit=0,
    )

    selection = _select_account_memory(store, account_id, instructions, "Schlaf")

    assert selection.prompt_text == ""
    assert calls == []


def test_select_account_memory_falls_back_to_local_on_unexpected_semantic_failure(tmp_path, monkeypatch) -> None:
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

    class BrokenQdrant:
        def __init__(self, **_kwargs) -> None:
            pass

        def search(self, **_kwargs):
            raise TypeError("malformed semantic response")

    monkeypatch.setattr("TeeBotus.runtime.engine.QdrantMemoryIndex", BrokenQdrant)
    instructions = BotInstructions(
        user_memory_enabled=True,
        memory_search_semantic_enabled=True,
        memory_search_semantic_backend="qdrant",
        memory_search_embedding_provider="hash",
    )

    selection = _select_account_memory(store, account_id, instructions, "Schlaf")

    assert "Schlaf und Abendroutine" in selection.prompt_text


def test_optional_context_sources_fail_open_on_unexpected_errors(monkeypatch) -> None:
    class BrokenWorkingMemory:
        def prepare(self, _query_text: str):
            raise RuntimeError("working memory unavailable")

    class BrokenBibliothekar:
        def search(self, _query_text: str, **_kwargs):
            raise RuntimeError("bibliothekar unavailable")

    monkeypatch.setattr(
        "TeeBotus.decisions.bibliothekar.decide_bibliothekar_query",
        lambda *_args, **_kwargs: SimpleNamespace(
            source="fallback",
            confidence=1.0,
            should_search=True,
            query="Depression",
            filters={},
        ),
    )

    assert _build_working_memory_context(BrokenWorkingMemory(), "Regel") == ""
    assert _build_bibliothekar_context(
        BrokenBibliothekar(),
        BotInstructions(bibliothekar_enabled=True),
        "Was steht zur Depression?",
    ) == ""
