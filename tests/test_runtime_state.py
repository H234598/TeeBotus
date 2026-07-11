from __future__ import annotations

import json
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


class RecoveringProvider:
    def __init__(self, secret: bytes) -> None:
        self.secret = secret
        self.available = False

    def get_secret(self, instance_name: str, purpose: str) -> bytes:
        if not self.available:
            raise AccountStoreError("secret backend unavailable")
        return self.secret


ACCOUNT_ID = "a" * 128


def test_runtime_state_store_falls_back_to_memory_on_corrupt_persisted_link_notifications(tmp_path):
    runtime_dir = tmp_path / "Bot" / "data" / "runtime"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "Link_Notifications.json").write_text("{not-json", encoding="utf-8")

    state = RuntimeStateStore(tmp_path / "Bot" / "data", instance_name="Bot", secret_provider=StaticSecretProvider(b"s" * 32))

    assert state.link_notifications == {}
    assert state.link_notifications_persistence_error


def test_runtime_state_store_clears_removed_corrupt_link_notification_error(tmp_path):
    runtime_dir = tmp_path / "Bot" / "data" / "runtime"
    runtime_dir.mkdir(parents=True)
    corrupted = runtime_dir / "Link_Notifications.json"
    corrupted.write_text("{not-json", encoding="utf-8")

    state = RuntimeStateStore(tmp_path / "Bot" / "data", instance_name="Bot", secret_provider=StaticSecretProvider(b"s" * 32))
    corrupted.unlink()

    assert state.list_link_notifications(instance_name="Bot", account_id="a" * 128) == []
    assert state.link_notifications_persistence_error == ""


def test_runtime_state_store_keeps_link_vault_inside_runtime_root(tmp_path):
    data_dir = tmp_path / "Bot" / "data"
    runtime_dir = data_dir / "runtime"
    runtime_dir.mkdir(parents=True)
    outside = tmp_path / "outside-link-notifications.json"
    outside.write_text("sentinel", encoding="utf-8")
    link_path = runtime_dir / "Link_Notifications.json"
    link_path.symlink_to(outside)

    state = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=StaticSecretProvider(b"s" * 32))
    state.record_link_notification(
        instance_name="Bot",
        account_id="a" * 128,
        new_identity_key="signal:uuid:new",
        old_identity_key="telegram:user:1",
    )

    assert outside.read_text(encoding="utf-8") == "sentinel"
    assert state.link_notifications_persistence_error


def test_runtime_state_store_refuses_in_root_link_notification_symlink(tmp_path):
    data_dir = tmp_path / "Bot" / "data"
    runtime_dir = data_dir / "runtime"
    runtime_dir.mkdir(parents=True)
    redirected = runtime_dir / "redirected.json"
    redirected.write_text("sentinel", encoding="utf-8")
    link_path = runtime_dir / "Link_Notifications.json"
    link_path.symlink_to(redirected)

    state = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=StaticSecretProvider(b"s" * 32))
    state.record_link_notification(
        instance_name="Bot",
        account_id="a" * 128,
        new_identity_key="signal:uuid:new",
        old_identity_key="telegram:user:1",
    )

    assert redirected.read_text(encoding="utf-8") == "sentinel"
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


def test_runtime_state_store_reports_missing_link_secret_provider(tmp_path):
    state = RuntimeStateStore(tmp_path / "Bot" / "data", instance_name="Bot", secret_provider=None)
    account_id = "a" * 128

    state.record_link_notification(
        instance_name="Bot",
        account_id=account_id,
        new_identity_key="signal:uuid:new",
        old_identity_key="telegram:user:1",
    )

    assert state.list_link_notifications(instance_name="Bot", account_id=account_id)
    assert "no secret provider" in state.link_notifications_persistence_error


def test_runtime_state_store_rebuilds_cached_account_store_after_provider_swap(tmp_path):
    secret = b"s" * 32
    data_dir = tmp_path / "Bot" / "data"
    account_store = AccountStore(data_dir / "accounts", "Bot", secret_provider=StaticSecretProvider(secret))
    account_store.write_llm_state(ACCOUNT_ID, {"previous_response_id": "resp-recovered"})
    state = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=BrokenProvider())

    assert state.get_previous_response_id("Bot", ACCOUNT_ID) is None
    state.secret_provider = StaticSecretProvider(secret)

    assert state.get_previous_response_id("Bot", ACCOUNT_ID) == "resp-recovered"


def test_runtime_state_store_rechecks_secret_guard_after_provider_kind_swap(tmp_path, monkeypatch):
    state = RuntimeStateStore(tmp_path / "Bot" / "data", instance_name="Bot", secret_provider=StaticSecretProvider(b"s" * 32))
    guard_calls: list[str] = []
    monkeypatch.setattr(state, "_account_store_for_llm_state", lambda: guard_calls.append("checked"))

    state._guard_account_store_secrets()
    state.secret_provider = SecretToolInstanceSecretProvider(create_if_missing=False)
    state._guard_account_store_secrets()
    state._guard_account_store_secrets()

    assert guard_calls == ["checked"]


def test_runtime_state_store_treats_existing_dotted_instance_directory_as_directory(tmp_path):
    instance_dir = tmp_path / "Bot.v2"
    instance_dir.mkdir()

    state = RuntimeStateStore(instance_dir, secret_provider=StaticSecretProvider(b"s" * 32))

    assert state.instance_name == "Bot.v2"
    assert state.runtime_dir == instance_dir / "data" / "runtime"


def test_runtime_state_store_rejects_symlinked_instance_directory_before_mkdir(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    instance_link = tmp_path / "Bot"
    instance_link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(AccountStoreError, match="unsafe runtime directory"):
        RuntimeStateStore(instance_link, instance_name="Bot", secret_provider=StaticSecretProvider(b"s" * 32))

    assert not (outside / "data" / "runtime").exists()


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


def test_runtime_state_store_persists_link_notifications_after_recovery(tmp_path):
    state = RuntimeStateStore(tmp_path / "Bot" / "data", instance_name="Bot", secret_provider=BrokenProvider())
    account_id = "a" * 128
    state.record_link_notification(
        instance_name="Bot",
        account_id=account_id,
        new_identity_key="signal:uuid:new",
        old_identity_key="telegram:user:1",
    )
    state.secret_provider = StaticSecretProvider(b"s" * 32)

    assert state.list_link_notifications(instance_name="Bot", account_id=account_id)
    assert state.link_notifications_persistence_error == ""

    reloaded = RuntimeStateStore(tmp_path / "Bot" / "data", instance_name="Bot", secret_provider=StaticSecretProvider(b"s" * 32))
    assert reloaded.list_link_notifications(instance_name="Bot", account_id=account_id)


def test_runtime_state_store_persists_merged_notifications_after_recovery(tmp_path):
    data_dir = tmp_path / "Bot" / "data"
    account_id = "a" * 128
    provider = StaticSecretProvider(b"s" * 32)
    initial = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)
    initial.record_link_notification(
        instance_name="Bot",
        account_id=account_id,
        new_identity_key="signal:uuid:old",
        old_identity_key="telegram:user:old",
    )

    state = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=BrokenProvider())
    state.record_link_notification(
        instance_name="Bot",
        account_id=account_id,
        new_identity_key="signal:uuid:new",
        old_identity_key="telegram:user:new",
    )
    state.secret_provider = provider

    notifications = state.list_link_notifications(instance_name="Bot", account_id=account_id)
    assert {item["old_identity_key"] for item in notifications} == {"telegram:user:old", "telegram:user:new"}

    reloaded = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)
    assert {item["old_identity_key"] for item in reloaded.list_link_notifications(instance_name="Bot", account_id=account_id)} == {
        "telegram:user:old",
        "telegram:user:new",
    }


def test_runtime_state_store_reports_link_notification_unlink_error(tmp_path, monkeypatch):
    state = RuntimeStateStore(tmp_path / "Bot" / "data", instance_name="Bot", secret_provider=StaticSecretProvider(b"s" * 32))
    account_id = "a" * 128
    state.record_link_notification(
        instance_name="Bot",
        account_id=account_id,
        new_identity_key="signal:uuid:new",
        old_identity_key="telegram:user:1",
    )

    def refuse_unlink(_path):
        raise PermissionError("unlink blocked")

    monkeypatch.setattr(type(state.link_notifications_path), "unlink", refuse_unlink)
    assert state.pop_link_notification(instance_name="Bot", account_id=account_id, old_identity_key="telegram:user:1")
    assert "unlink blocked" in state.link_notifications_persistence_error


def test_runtime_state_store_reports_link_notification_write_error(tmp_path, monkeypatch):
    state = RuntimeStateStore(tmp_path / "Bot" / "data", instance_name="Bot", secret_provider=StaticSecretProvider(b"s" * 32))

    def refuse_write(_vault, _path, _payload):
        raise OSError("write blocked")

    monkeypatch.setattr("TeeBotus.runtime.state.EncryptedJsonVault.write_json", refuse_write)
    account_id = "a" * 128
    state.record_link_notification(
        instance_name="Bot",
        account_id=account_id,
        new_identity_key="signal:uuid:new",
        old_identity_key="telegram:user:1",
    )

    assert state.list_link_notifications(instance_name="Bot", account_id=account_id)
    assert "write blocked" in state.link_notifications_persistence_error


def test_runtime_state_store_reports_link_notification_read_error(tmp_path, monkeypatch):
    data_dir = tmp_path / "Bot" / "data"
    provider = StaticSecretProvider(b"s" * 32)
    initial = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)
    initial.record_link_notification(
        instance_name="Bot",
        account_id="a" * 128,
        new_identity_key="signal:uuid:new",
        old_identity_key="telegram:user:1",
    )

    def refuse_read(_vault, _path, _default):
        raise OSError("read blocked")

    monkeypatch.setattr("TeeBotus.runtime.state.EncryptedJsonVault.read_json", refuse_read)
    state = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)

    assert state.link_notifications == {}
    assert "read blocked" in state.link_notifications_persistence_error


def test_runtime_state_store_reports_link_notification_exists_error(tmp_path, monkeypatch):
    def refuse_exists(_path):
        raise OSError("exists blocked")

    path_type = type(tmp_path / "Bot" / "data" / "runtime" / "Link_Notifications.json")
    monkeypatch.setattr(path_type, "exists", refuse_exists)
    state = RuntimeStateStore(tmp_path / "Bot" / "data", instance_name="Bot", secret_provider=StaticSecretProvider(b"s" * 32))

    assert "exists blocked" in state.link_notifications_persistence_error


def test_runtime_state_store_uses_cache_when_llm_state_read_raises_oserror(tmp_path, monkeypatch):
    state = RuntimeStateStore(tmp_path / "Bot" / "data", instance_name="Bot", secret_provider=StaticSecretProvider(b"s" * 32))
    state.previous_response_ids[("Bot", ACCOUNT_ID)] = "cached-response"

    def refuse_read(_store, _account_id):
        raise OSError("state read blocked")

    monkeypatch.setattr("TeeBotus.runtime.state.AccountStore.read_llm_state", refuse_read)

    assert state.get_previous_response_id("Bot", ACCOUNT_ID) == "cached-response"
    assert "state read blocked" in state.llm_state_persistence_error


def test_runtime_state_store_reports_llm_state_write_oserror(tmp_path, monkeypatch):
    state = RuntimeStateStore(tmp_path / "Bot" / "data", instance_name="Bot", secret_provider=StaticSecretProvider(b"s" * 32))

    def refuse_write(_store, _account_id, _payload):
        raise OSError("state write blocked")

    monkeypatch.setattr("TeeBotus.runtime.state.AccountStore.write_llm_state", refuse_write)
    state.set_previous_response_id("Bot", ACCOUNT_ID, "response-id")

    assert state.previous_response_ids[("Bot", ACCOUNT_ID)] == "response-id"
    assert "state write blocked" in state.llm_state_persistence_error


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


def test_runtime_state_store_serializes_security_event_rotation_and_append(tmp_path, monkeypatch):
    import TeeBotus.runtime.state as state_module

    provider = StaticSecretProvider(b"s" * 32)
    data_dir = tmp_path / "Bot" / "data"
    first = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)
    second = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)
    first_rotate_entered = threading.Event()
    release_first = threading.Event()
    second_done = threading.Event()
    errors: list[BaseException] = []
    original_rotate = state_module.rotate_runtime_text_file_if_needed

    def blocking_rotate(path):
        if not first_rotate_entered.is_set():
            first_rotate_entered.set()
            if not release_first.wait(timeout=2):
                raise RuntimeError("first security-event append was not released")
        return original_rotate(path)

    monkeypatch.setattr(state_module, "rotate_runtime_text_file_if_needed", blocking_rotate)

    def run_first() -> None:
        try:
            first.append_security_event({"event": "first"})
        except BaseException as exc:  # pragma: no cover - assertion below reports the error.
            errors.append(exc)

    def run_second() -> None:
        try:
            second.append_security_event({"event": "second"})
        except BaseException as exc:  # pragma: no cover - assertion below reports the error.
            errors.append(exc)
        finally:
            second_done.set()

    first_thread = threading.Thread(target=run_first)
    second_thread = threading.Thread(target=run_second)
    first_thread.start()
    assert first_rotate_entered.wait(timeout=1)
    second_thread.start()
    try:
        assert not second_done.wait(timeout=0.1)
    finally:
        release_first.set()
        first_thread.join(timeout=2)
        second_thread.join(timeout=2)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert errors == []
    events = [json.loads(line)["event"] for line in first.security_events_path.read_text(encoding="utf-8").splitlines()]
    assert events == ["first", "second"]


def test_runtime_state_store_refuses_security_event_symlink_target(tmp_path):
    data_dir = tmp_path / "Bot" / "data"
    runtime_dir = data_dir / "runtime"
    runtime_dir.mkdir(parents=True)
    outside = tmp_path / "outside-security-events.jsonl"
    security_path = runtime_dir / "Security_Events.jsonl"
    security_path.symlink_to(outside)
    state = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=StaticSecretProvider(b"s" * 32))

    with pytest.raises(AccountStoreError, match="unsafe security event path"):
        state.append_security_event({"event": "must-not-follow"})

    assert security_path.is_symlink()
    assert not outside.exists()
    assert state.security_events_persistence_error

    security_path.unlink()
    state.append_security_event({"event": "recovered"})

    assert state.security_events_persistence_error == ""
    assert json.loads(security_path.read_text(encoding="utf-8"))["event"] == "recovered"


def test_runtime_state_store_does_not_cache_unserializable_security_event(tmp_path):
    state = RuntimeStateStore(tmp_path / "Bot" / "data", instance_name="Bot", secret_provider=StaticSecretProvider(b"s" * 32))

    with pytest.raises(TypeError):
        state.append_security_event({"event": object()})

    assert state.security_events == []
    assert state.security_events_persistence_error


def test_runtime_state_store_reports_security_event_runtime_error(tmp_path, monkeypatch):
    import TeeBotus.runtime.state as state_module

    state = RuntimeStateStore(tmp_path / "Bot" / "data", instance_name="Bot", secret_provider=StaticSecretProvider(b"s" * 32))

    def refuse_open(_path):
        raise RuntimeError("security event open failed")

    monkeypatch.setattr(state_module, "_open_append_text_no_follow", refuse_open)
    with pytest.raises(RuntimeError, match="security event open failed"):
        state.append_security_event({"event": "runtime-error"})

    assert "security event open failed" in state.security_events_persistence_error


def test_runtime_state_store_reports_security_lock_error(tmp_path):
    data_dir = tmp_path / "Bot" / "data"
    runtime_dir = data_dir / "runtime"
    runtime_dir.mkdir(parents=True)
    outside = tmp_path / "outside-security-lock"
    lock_path = runtime_dir / ".Security_Events.jsonl.lock"
    lock_path.symlink_to(outside)
    state = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=StaticSecretProvider(b"s" * 32))

    with pytest.raises(AccountStoreError, match="unsafe runtime lock path"):
        state.append_security_event({"event": "lock-error"})

    assert "unsafe runtime lock path" in state.security_events_persistence_error
    assert not outside.exists()


def test_runtime_state_store_refuses_runtime_lock_symlink(tmp_path):
    data_dir = tmp_path / "Bot" / "data"
    runtime_dir = data_dir / "runtime"
    runtime_dir.mkdir(parents=True)
    outside = tmp_path / "outside-runtime-lock"
    lock_path = runtime_dir / ".Link_Notifications.json.lock"
    lock_path.symlink_to(outside)

    with pytest.raises(AccountStoreError, match="unsafe runtime lock path"):
        RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=StaticSecretProvider(b"s" * 32))

    assert not outside.exists()


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


def test_runtime_state_store_uses_read_error_snapshot_for_cache_fallback(tmp_path, monkeypatch):
    state = RuntimeStateStore(tmp_path / "Bot" / "data", instance_name="Bot", secret_provider=StaticSecretProvider(b"s" * 32))
    account_a = "a" * 128
    state.previous_response_ids[("Bot", account_a)] = "cached-a"

    def fake_read(_account_id: str) -> tuple[dict[str, str], str]:
        return {}, "account A unavailable"

    monkeypatch.setattr(state, "_read_llm_state", fake_read)

    assert state.get_previous_response_id("Bot", account_a) == "cached-a"


def test_runtime_state_store_does_not_overwrite_llm_state_after_read_failure(tmp_path, monkeypatch):
    state = RuntimeStateStore(tmp_path / "Bot" / "data", instance_name="Bot", secret_provider=StaticSecretProvider(b"s" * 32))
    writes: list[dict[str, object]] = []

    def failing_read(_account_id: str) -> tuple[dict[str, object], str]:
        state._set_llm_state_persistence_error("LLM state read failed")
        return {}, "LLM state read failed"

    monkeypatch.setattr(state, "_read_llm_state", failing_read)
    monkeypatch.setattr(state, "_write_llm_state", lambda _account_id, payload: writes.append(dict(payload)))

    state.set_previous_response_id("Bot", ACCOUNT_ID, "resp-new", provider="openai", model="gpt-5.5")

    assert writes == []
    assert state.previous_response_ids[("Bot", ACCOUNT_ID)] == "resp-new"
    assert state.llm_state_persistence_error == "LLM state read failed"


def test_runtime_state_store_aggregates_persistence_errors_per_account(tmp_path):
    state = RuntimeStateStore(tmp_path / "Bot" / "data", instance_name="Bot", secret_provider=StaticSecretProvider(b"s" * 32))
    account_a = "a" * 128
    account_b = "b" * 128

    state._set_llm_state_persistence_error("account A failed", account_id=account_a)
    state._set_llm_state_persistence_error("", account_id=account_b)

    assert state.llm_state_persistence_error == "account A failed"
    assert state.openai_state_persistence_error == "account A failed"

    state._set_llm_state_persistence_error("", account_id=account_a)

    assert state.llm_state_persistence_error == ""
    assert state.openai_state_persistence_error == ""


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


def test_runtime_state_store_retries_failed_reset_after_persistence_recovers(tmp_path):
    secret = b"s" * 32
    data_dir = tmp_path / "Bot" / "data"
    account_store = AccountStore(data_dir / "accounts", "Bot", secret_provider=StaticSecretProvider(secret))
    account_store.write_llm_state(ACCOUNT_ID, {"previous_response_id": "resp-old"})
    recovering_provider = RecoveringProvider(secret)
    state = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=recovering_provider)
    state.previous_response_ids[("Bot", ACCOUNT_ID)] = "resp-old"

    state.reset_previous_response_id("Bot", ACCOUNT_ID)
    assert ("Bot", ACCOUNT_ID) in state.pending_previous_response_resets

    recovering_provider.available = True
    assert state.get_previous_response_id("Bot", ACCOUNT_ID) is None
    assert ("Bot", ACCOUNT_ID) not in state.pending_previous_response_resets
    assert "previous_response_id" not in account_store.read_llm_state(ACCOUNT_ID)


def test_runtime_state_store_does_not_clear_new_response_after_failed_reset(tmp_path):
    secret = b"s" * 32
    data_dir = tmp_path / "Bot" / "data"
    account_store = AccountStore(data_dir / "accounts", "Bot", secret_provider=StaticSecretProvider(secret))
    account_store.write_llm_state(ACCOUNT_ID, {"previous_response_id": "resp-old"})
    recovering_provider = RecoveringProvider(secret)
    state = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=recovering_provider)
    state.previous_response_ids[("Bot", ACCOUNT_ID)] = "resp-old"

    state.reset_previous_response_id("Bot", ACCOUNT_ID)
    account_store.write_llm_state(ACCOUNT_ID, {"previous_response_id": "resp-new"})
    recovering_provider.available = True

    assert state.get_previous_response_id("Bot", ACCOUNT_ID) == "resp-new"
    assert ("Bot", ACCOUNT_ID) not in state.pending_previous_response_resets


def test_runtime_state_store_recovers_local_response_after_failed_reset(tmp_path):
    secret = b"s" * 32
    data_dir = tmp_path / "Bot" / "data"
    account_store = AccountStore(data_dir / "accounts", "Bot", secret_provider=StaticSecretProvider(secret))
    account_store.write_llm_state(ACCOUNT_ID, {"previous_response_id": "resp-old"})
    recovering_provider = RecoveringProvider(secret)
    state = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=recovering_provider)
    state.previous_response_ids[("Bot", ACCOUNT_ID)] = "resp-old"

    state.reset_previous_response_id("Bot", ACCOUNT_ID)
    state.set_previous_response_id("Bot", ACCOUNT_ID, "resp-local-new", provider="openai", model="gpt-5.5")
    recovering_provider.available = True

    assert state.get_previous_response_id("Bot", ACCOUNT_ID, provider="openai", model="gpt-5.5") == "resp-local-new"
    assert ("Bot", ACCOUNT_ID) not in state.pending_previous_response_resets
    assert account_store.read_llm_state(ACCOUNT_ID)["previous_response_id"] == "resp-local-new"


def test_runtime_state_store_serializes_set_and_reset_transitions(tmp_path, monkeypatch):
    state = RuntimeStateStore(tmp_path / "Bot" / "data", instance_name="Bot", secret_provider=StaticSecretProvider(b"s" * 32))
    write_entered = threading.Event()
    release_write = threading.Event()
    reset_finished = threading.Event()

    def blocking_write(*_args, **_kwargs):
        write_entered.set()
        assert release_write.wait(timeout=2)
        return True

    monkeypatch.setattr(state, "_write_llm_previous_response_id", blocking_write)
    setter = threading.Thread(
        target=state.set_previous_response_id,
        args=("Bot", ACCOUNT_ID, "response-id"),
    )
    setter.start()
    assert write_entered.wait(timeout=2)

    def reset() -> None:
        state.reset_previous_response_id("Bot", ACCOUNT_ID)
        reset_finished.set()

    resetter = threading.Thread(target=reset)
    resetter.start()
    assert not reset_finished.wait(timeout=0.1)

    release_write.set()
    setter.join(timeout=2)
    resetter.join(timeout=2)
    assert not setter.is_alive()
    assert not resetter.is_alive()
    assert reset_finished.is_set()


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
