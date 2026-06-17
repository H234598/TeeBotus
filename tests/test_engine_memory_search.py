from __future__ import annotations

from TeeBotus.instructions import BotInstructions
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, telegram_identity_key
from TeeBotus.runtime.engine import _select_account_memory


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
