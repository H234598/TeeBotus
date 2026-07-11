from __future__ import annotations

import threading

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


def test_runtime_state_store_clears_link_persistence_error_after_recovery(tmp_path):
    state = RuntimeStateStore(tmp_path / "Bot" / "data", instance_name="Bot", secret_provider=BrokenProvider())
    account_id = "a" * 128
    state.record_link_notification(
        instance_name="Bot",
        account_id=account_id,
        new_identity_key="signal:uuid:new",
        old_identity_key="telegram:user:1",
    )
    state.secret_provider = StaticSecretProvider(b"s" * 32)

    state.pop_link_notification(instance_name="Bot", account_id=account_id, old_identity_key="telegram:user:1")

    assert state.link_notifications_persistence_error == ""


def test_runtime_state_store_refreshes_link_notifications_between_bridges(tmp_path):
    provider = StaticSecretProvider(b"s" * 32)
    data_dir = tmp_path / "Bot" / "data"
    account_id = "a" * 128
    first = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)
    second = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)

    first.record_link_notification(
        instance_name="Bot",
        account_id=account_id,
        new_identity_key="signal:uuid:new",
        old_identity_key="telegram:user:1",
    )

    assert second.list_link_notifications(instance_name="Bot", account_id=account_id)
    assert second.pop_link_notification(
        instance_name="Bot",
        account_id=account_id,
        old_identity_key="telegram:user:1",
    ) is not None
    assert first.list_link_notifications(instance_name="Bot", account_id=account_id) == []


def test_runtime_state_store_serializes_concurrent_link_notification_writes(tmp_path):
    provider = StaticSecretProvider(b"s" * 32)
    data_dir = tmp_path / "Bot" / "data"
    account_id = "a" * 128
    first = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)
    second = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)
    first_entered = threading.Event()
    second_attempted = threading.Event()
    second_entered = threading.Event()
    release_first = threading.Event()
    errors: list[BaseException] = []

    original_first_refresh = first._refresh_persisted_link_notifications

    def blocking_first_refresh() -> None:
        first_entered.set()
        if not release_first.wait(timeout=2):
            raise RuntimeError("first link-notification operation did not get released")
        original_first_refresh()

    original_second_refresh = second._refresh_persisted_link_notifications

    def observed_second_refresh() -> None:
        second_entered.set()
        original_second_refresh()

    first._refresh_persisted_link_notifications = blocking_first_refresh
    second._refresh_persisted_link_notifications = observed_second_refresh

    def run_first() -> None:
        try:
            first.record_link_notification(
                instance_name="Bot",
                account_id=account_id,
                new_identity_key="signal:uuid:first",
                old_identity_key="telegram:user:first",
            )
        except BaseException as exc:  # pragma: no cover - assertion below reports the error.
            errors.append(exc)

    def run_second() -> None:
        second_attempted.set()
        try:
            second.record_link_notification(
                instance_name="Bot",
                account_id=account_id,
                new_identity_key="signal:uuid:second",
                old_identity_key="telegram:user:second",
            )
        except BaseException as exc:  # pragma: no cover - assertion below reports the error.
            errors.append(exc)

    first_thread = threading.Thread(target=run_first)
    second_thread = threading.Thread(target=run_second)
    first_thread.start()
    assert first_entered.wait(timeout=1)
    second_thread.start()
    assert second_attempted.wait(timeout=1)
    try:
        assert not second_entered.wait(timeout=0.1)
    finally:
        release_first.set()
        first_thread.join(timeout=2)
        second_thread.join(timeout=2)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert errors == []
    refreshed = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)
    assert {item["old_identity_key"] for item in refreshed.list_link_notifications(instance_name="Bot", account_id=account_id)} == {
        "telegram:user:first",
        "telegram:user:second",
    }


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

    with account_store.account_memory_lock(ACCOUNT_ID):
        state.set_previous_response_id("Bot", ACCOUNT_ID, "resp-1")
    reloaded = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)

    assert reloaded.get_previous_response_id("Bot", ACCOUNT_ID) == "resp-1"
    llm_state_path = account_store.account_dir(ACCOUNT_ID) / LLM_STATE_FILENAME
    assert llm_state_path.exists()
    assert account_store.read_llm_state(ACCOUNT_ID)["kept"] == "value"
    assert account_store.read_llm_state(ACCOUNT_ID)["previous_response_id"] == "resp-1"
    assert llm_state_path.exists()


def test_runtime_state_store_persists_llm_state_through_sql_backend(tmp_path, monkeypatch):
    data_dir = tmp_path / "Bot" / "data"
    sqlite_path = data_dir / "Account_Memory.sqlite3"
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", str(sqlite_path))
    monkeypatch.delenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_FALLBACK_PATH", raising=False)
    provider = StaticSecretProvider(b"s" * 32)
    state = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)

    state.set_previous_response_id("Bot", ACCOUNT_ID, "resp-sql", provider="openai", model="gpt-5.5")
    reloaded = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)

    account_store = AccountStore(data_dir / "accounts", "Bot", secret_provider=provider)
    assert account_store.read_llm_state(ACCOUNT_ID)["previous_response_id"] == "resp-sql"
    assert not (account_store.account_dir(ACCOUNT_ID) / LLM_STATE_FILENAME).exists()
    assert reloaded.get_previous_response_id("Bot", ACCOUNT_ID, provider="openai", model="gpt-5.5") == "resp-sql"


def test_runtime_state_store_scopes_previous_response_to_provider_and_model(tmp_path):
    provider = StaticSecretProvider(b"s" * 32)
    data_dir = tmp_path / "Bot" / "data"
    account_store = AccountStore(data_dir / "accounts", "Bot", secret_provider=provider)
    state = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)

    key_fingerprint = "a" * 64
    state.set_previous_response_id(
        "Bot",
        ACCOUNT_ID,
        "resp-openai",
        provider="openai",
        model="gpt-5.5",
        key_fingerprint=key_fingerprint,
    )
    reloaded = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)

    assert reloaded.get_previous_response_id(
        "Bot",
        ACCOUNT_ID,
        provider="openai",
        model="gpt-5.5",
        key_fingerprint=key_fingerprint,
    ) == "resp-openai"
    assert reloaded.get_previous_response_id(
        "Bot",
        ACCOUNT_ID,
        provider="openai",
        model="gpt-5.5",
        key_fingerprint="b" * 64,
    ) is None
    assert reloaded.get_previous_response_id("Bot", ACCOUNT_ID, provider="litellm_gemini_stateful", model="gemini/gemini-3.5-flash") is None
    assert reloaded.get_previous_response_id("Bot", ACCOUNT_ID, provider="openai", model="gpt-5.4") is None
    persisted = account_store.read_llm_state(ACCOUNT_ID)
    assert persisted["previous_response_provider"] == "openai"
    assert persisted["previous_response_model"] == "gpt-5.5"
    assert persisted["previous_response_key_fingerprint"] == key_fingerprint


def test_runtime_state_store_does_not_use_legacy_unscoped_id_for_scoped_lookup(tmp_path):
    provider = StaticSecretProvider(b"s" * 32)
    data_dir = tmp_path / "Bot" / "data"
    account_store = AccountStore(data_dir / "accounts", "Bot", secret_provider=provider)
    account_store.write_llm_state(ACCOUNT_ID, {"previous_response_id": "resp-legacy"})
    state = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)

    assert state.get_previous_response_id("Bot", ACCOUNT_ID, provider="openai", model="gpt-5.5") is None
    assert state.get_previous_response_id("Bot", ACCOUNT_ID) == "resp-legacy"


def test_runtime_state_store_scopes_key_fingerprint_only_lookup(tmp_path):
    provider = StaticSecretProvider(b"s" * 32)
    data_dir = tmp_path / "Bot" / "data"
    state = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)

    state.set_previous_response_id(
        "Bot",
        ACCOUNT_ID,
        "resp-scoped",
        provider="openai",
        model="gpt-5.5",
        key_fingerprint="a" * 64,
    )
    reloaded = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)

    assert reloaded.get_previous_response_id("Bot", ACCOUNT_ID, key_fingerprint="a" * 64) == "resp-scoped"
    assert reloaded.get_previous_response_id("Bot", ACCOUNT_ID, key_fingerprint="b" * 64) is None
    assert reloaded.get_previous_response_id(
        "Bot",
        ACCOUNT_ID,
        provider="openai",
        model="gpt-5.5",
        key_fingerprint="b" * 64,
    ) is None


def test_runtime_state_store_refreshes_persistent_llm_state_between_bridges(tmp_path, monkeypatch):
    monkeypatch.delenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", raising=False)
    monkeypatch.delenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", raising=False)
    monkeypatch.delenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_FALLBACK_PATH", raising=False)
    provider = StaticSecretProvider(b"s" * 32)
    data_dir = tmp_path / "Bot" / "data"
    first = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)
    second = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)
    scope = {"provider": "openai", "model": "gpt-5.5", "key_fingerprint": "a" * 64}

    first.set_previous_response_id("Bot", ACCOUNT_ID, "resp-1", **scope)
    assert first.get_previous_response_id("Bot", ACCOUNT_ID, **scope) == "resp-1"

    second.set_previous_response_id("Bot", ACCOUNT_ID, "resp-2", **scope)
    assert first.get_previous_response_id("Bot", ACCOUNT_ID, **scope) == "resp-2"

    second.reset_previous_response_id("Bot", ACCOUNT_ID)
    assert first.get_previous_response_id("Bot", ACCOUNT_ID, **scope) is None


def test_runtime_state_store_keeps_persistence_error_local_to_parallel_reads(tmp_path, monkeypatch):
    state = RuntimeStateStore(tmp_path / "Bot" / "data", instance_name="Bot", secret_provider=StaticSecretProvider(b"s" * 32))
    account_a = "a" * 128
    account_b = "b" * 128
    state.previous_response_ids[("Bot", account_a)] = "cached-a"
    a_started = threading.Event()
    b_read = threading.Event()
    release_a = threading.Event()
    results: dict[str, str | None] = {}
    errors: list[BaseException] = []

    def fake_read(account_id: str) -> tuple[dict[str, str], str]:
        if account_id == account_a:
            a_started.set()
            if not release_a.wait(timeout=2):
                raise RuntimeError("account A read was not released")
            return {}, "account A unavailable"
        b_read.set()
        return {"previous_response_id": "persisted-b"}, ""

    monkeypatch.setattr(state, "_read_llm_state", fake_read)

    def read_a() -> None:
        try:
            results["a"] = state.get_previous_response_id("Bot", account_a)
        except BaseException as exc:  # pragma: no cover - assertion below reports the error.
            errors.append(exc)

    def read_b() -> None:
        try:
            results["b"] = state.get_previous_response_id("Bot", account_b)
        except BaseException as exc:  # pragma: no cover - assertion below reports the error.
            errors.append(exc)

    thread_a = threading.Thread(target=read_a)
    thread_b = threading.Thread(target=read_b)
    thread_a.start()
    assert a_started.wait(timeout=1)
    thread_b.start()
    assert b_read.wait(timeout=1)
    release_a.set()
    thread_a.join(timeout=2)
    thread_b.join(timeout=2)

    assert not thread_a.is_alive()
    assert not thread_b.is_alive()
    assert errors == []
    assert results == {"a": "cached-a", "b": "persisted-b"}


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


def test_runtime_state_store_set_whitespace_clears_previous_llm_response_id(tmp_path):
    provider = StaticSecretProvider(b"s" * 32)
    data_dir = tmp_path / "Bot" / "data"
    account_store = AccountStore(data_dir / "accounts", "Bot", secret_provider=provider)
    state = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)

    state.set_previous_response_id("Bot", ACCOUNT_ID, "resp-1", provider="openai", model="gpt-5.5")
    state.set_previous_response_id("Bot", ACCOUNT_ID, "   ")
    reloaded = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)

    assert state.get_previous_response_id("Bot", ACCOUNT_ID) is None
    assert reloaded.get_previous_response_id("Bot", ACCOUNT_ID) is None
    assert "previous_response_id" not in account_store.read_llm_state(ACCOUNT_ID)


def test_runtime_state_store_reset_clears_orphaned_previous_response_scope(tmp_path):
    provider = StaticSecretProvider(b"s" * 32)
    data_dir = tmp_path / "Bot" / "data"
    account_store = AccountStore(data_dir / "accounts", "Bot", secret_provider=provider)
    account_store.write_llm_state(
        ACCOUNT_ID,
        {
            "kept": "value",
            "previous_response_provider": "openai",
            "previous_response_model": "gpt-5.5",
            "previous_response_key_fingerprint": "a" * 64,
        },
    )
    state = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)

    state.reset_previous_response_id("Bot", ACCOUNT_ID)

    persisted = account_store.read_llm_state(ACCOUNT_ID)
    assert persisted == {"kept": "value", "updated_at": persisted["updated_at"]}
    assert "previous_response_provider" not in persisted
    assert "previous_response_model" not in persisted
    assert "previous_response_key_fingerprint" not in persisted


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


@pytest.mark.parametrize(
    ("chat_type", "expected_private", "expected_group"),
    (
        ("private", True, False),
        ("Private", True, False),
        ("group", False, True),
        ("Group", False, True),
        ("GROUP", False, True),
    ),
)
def test_incoming_event_chat_type_properties_are_case_normalized(
    chat_type: str,
    expected_private: bool,
    expected_group: bool,
) -> None:
    event = IncomingEvent(
        event_id="signal:1",
        instance="Bot",
        channel="signal",
        adapter_slot=1,
        account_id="",
        identity_key="signal:uuid:1",
        chat_id="+491",
        chat_type=chat_type,  # type: ignore[arg-type]
        sender_id="1",
        text="Hallo",
        message_ref="1",
    )

    assert event.is_private is expected_private
    assert event.is_group is expected_group
