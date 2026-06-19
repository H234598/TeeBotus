from __future__ import annotations

import pytest

from TeeBotus.runtime.accounts import (
    ACCOUNT_MEMORY_KEY_PURPOSE,
    AccountStore,
    AccountStoreError,
    LLM_STATE_FILENAME,
    OPENAI_STATE_FILENAME,
    SecretToolInstanceSecretProvider,
    StaticSecretProvider,
)
from TeeBotus.runtime.events import IncomingEvent, IncomingLinkPreview
from TeeBotus.runtime.sqlite_memory import SQLiteAccountMemoryBackend, SQLiteMemoryConfig
from TeeBotus.runtime.state import RuntimeStateStore


class BrokenProvider:
    def get_secret(self, instance_name: str, purpose: str) -> bytes:
        raise AccountStoreError("secret backend unavailable")


ACCOUNT_ID = "a" * 128


def test_runtime_state_store_falls_back_to_memory_on_corrupt_persisted_link_notifications(tmp_path):
    runtime_dir = tmp_path / "Bot" / "data" / "runtime"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "Link_Notifications.json").write_text("{not-json", encoding="utf-8")

    state = RuntimeStateStore(tmp_path / "Bot" / "data", instance_name="Bot", secret_provider=StaticSecretProvider(b"s" * 32))

    assert state.link_notifications == {}
    assert state.link_notifications_persistence_error


def test_runtime_state_store_keeps_link_notifications_in_memory_when_secret_backend_fails(tmp_path):
    state = RuntimeStateStore(tmp_path / "Bot" / "data", instance_name="Bot", secret_provider=BrokenProvider())

    state.record_link_notification(
        instance_name="Bot",
        account_id="a" * 128,
        new_identity_key="signal:uuid:new",
        old_identity_key="telegram:user:1",
    )

    assert state.list_link_notifications(instance_name="Bot", account_id="a" * 128)
    assert "secret backend unavailable" in state.link_notifications_persistence_error


def test_runtime_state_store_refuses_to_autocreate_llm_state_secret_for_existing_sqlite_memory(tmp_path, monkeypatch):
    data_dir = tmp_path / "Bot" / "data"
    accounts_root = data_dir / "accounts"
    SQLiteAccountMemoryBackend(
        instance_name="Bot",
        provider=StaticSecretProvider(b"s" * 32),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=accounts_root / "Account_Memory.sqlite3", fallback_path=None),
    ).write_entries(ACCOUNT_ID, [{"id": "mem_keep", "user_text": "nicht ueberschreiben"}])
    secret_provider = SecretToolInstanceSecretProvider(create_if_missing=True)
    monkeypatch.setattr(secret_provider, "_lookup", lambda _instance, _purpose: None)
    monkeypatch.setattr(
        secret_provider,
        "_store",
        lambda _instance, _purpose, _secret: pytest.fail("runtime state must not create a new memory secret over SQLite rows"),
    )
    state = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=secret_provider)

    state.set_previous_response_id("Bot", ACCOUNT_ID, "resp-1")

    assert "refusing to create missing instance secret for existing encrypted sqlite account memory" in state.llm_state_persistence_error
    assert not (accounts_root / "accounts" / ACCOUNT_ID / LLM_STATE_FILENAME).exists()


def test_runtime_state_store_persists_previous_llm_response_id(tmp_path, monkeypatch):
    monkeypatch.delenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", raising=False)
    monkeypatch.delenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", raising=False)
    monkeypatch.delenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_FALLBACK_PATH", raising=False)
    provider = StaticSecretProvider(b"s" * 32)
    data_dir = tmp_path / "Bot" / "data"
    account_store = AccountStore(data_dir / "accounts", "Bot", secret_provider=provider)
    account_store.write_llm_state(ACCOUNT_ID, {"kept": "value"})
    state = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)

    state.set_previous_response_id("Bot", ACCOUNT_ID, "resp-1")
    reloaded = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)

    assert reloaded.get_previous_response_id("Bot", ACCOUNT_ID) == "resp-1"
    llm_state_path = account_store.account_dir(ACCOUNT_ID) / LLM_STATE_FILENAME
    assert llm_state_path.exists()
    assert account_store.read_llm_state(ACCOUNT_ID)["kept"] == "value"
    assert account_store.read_llm_state(ACCOUNT_ID)["previous_response_id"] == "resp-1"
    assert llm_state_path.exists()


def test_runtime_state_store_migrates_previous_response_id_from_legacy_openai_state(tmp_path, monkeypatch):
    monkeypatch.delenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", raising=False)
    monkeypatch.delenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", raising=False)
    monkeypatch.delenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_FALLBACK_PATH", raising=False)
    provider = StaticSecretProvider(b"s" * 32)
    data_dir = tmp_path / "Bot" / "data"
    account_store = AccountStore(data_dir / "accounts", "Bot", secret_provider=provider)
    legacy_path = account_store.account_dir(ACCOUNT_ID) / OPENAI_STATE_FILENAME
    account_store.account_memory_vault.write_json(legacy_path, {"previous_response_id": "resp-legacy", "updated_at": "2026-06-01T00:00:00+00:00"})
    state = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)

    assert state.get_previous_response_id("Bot", ACCOUNT_ID) == "resp-legacy"
    assert (account_store.account_dir(ACCOUNT_ID) / LLM_STATE_FILENAME).exists()
    assert account_store.read_llm_state(ACCOUNT_ID)["previous_response_id"] == "resp-legacy"


def test_runtime_state_store_reset_clears_persisted_previous_llm_response_id(tmp_path):
    provider = StaticSecretProvider(b"s" * 32)
    data_dir = tmp_path / "Bot" / "data"
    account_store = AccountStore(data_dir / "accounts", "Bot", secret_provider=provider)
    state = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)

    state.set_previous_response_id("Bot", ACCOUNT_ID, "resp-1")
    state.reset_previous_response_id("Bot", ACCOUNT_ID)
    reloaded = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)

    assert reloaded.get_previous_response_id("Bot", ACCOUNT_ID) is None
    assert "previous_response_id" not in account_store.read_llm_state(ACCOUNT_ID)


def test_runtime_state_store_set_none_clears_previous_llm_response_id(tmp_path):
    provider = StaticSecretProvider(b"s" * 32)
    data_dir = tmp_path / "Bot" / "data"
    account_store = AccountStore(data_dir / "accounts", "Bot", secret_provider=provider)
    state = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)

    state.set_previous_response_id("Bot", ACCOUNT_ID, "resp-1")
    state.set_previous_response_id("Bot", ACCOUNT_ID, None)
    reloaded = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)

    assert state.get_previous_response_id("Bot", ACCOUNT_ID) is None
    assert reloaded.get_previous_response_id("Bot", ACCOUNT_ID) is None
    assert "previous_response_id" not in account_store.read_llm_state(ACCOUNT_ID)


def test_runtime_state_store_keeps_invalid_previous_response_account_id_in_memory(tmp_path):
    state = RuntimeStateStore(tmp_path / "Bot" / "data", instance_name="Bot", secret_provider=StaticSecretProvider(b"s" * 32))

    state.set_previous_response_id("Bot", "not-a-real-account-id", "resp-1")

    assert state.get_previous_response_id("Bot", "not-a-real-account-id") == "resp-1"
    assert state.llm_state_persistence_error
    assert state.openai_state_persistence_error


def test_incoming_event_with_reply_to_text_preserves_link_previews() -> None:
    preview = IncomingLinkPreview(title="TeeBotus", url="https://example.test/tee")
    event = IncomingEvent(
        event_id="signal:1",
        instance="Bot",
        channel="signal",
        adapter_slot=1,
        account_id="",
        identity_key="signal:uuid:1",
        chat_id="+491",
        chat_type="private",
        sender_id="1",
        text="Antwort",
        message_ref="1",
        link_previews=(preview,),
    )

    updated = event.with_reply_to_text("Vorher")

    assert updated.reply_to_text == "Vorher"
    assert updated.link_previews == (preview,)
