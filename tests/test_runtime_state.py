from __future__ import annotations

from TeeBotus.runtime.accounts import AccountStore, AccountStoreError, StaticSecretProvider
from TeeBotus.runtime.events import IncomingEvent, IncomingLinkPreview
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


def test_runtime_state_store_persists_previous_openai_response_id(tmp_path):
    provider = StaticSecretProvider(b"s" * 32)
    data_dir = tmp_path / "Bot" / "data"
    account_store = AccountStore(data_dir / "accounts", "Bot", secret_provider=provider)
    account_store.write_openai_state(ACCOUNT_ID, {"kept": "value"})
    state = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)

    state.set_previous_response_id("Bot", ACCOUNT_ID, "resp-1")
    reloaded = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)

    assert reloaded.get_previous_response_id("Bot", ACCOUNT_ID) == "resp-1"
    assert account_store.read_openai_state(ACCOUNT_ID)["kept"] == "value"
    assert account_store.read_openai_state(ACCOUNT_ID)["previous_response_id"] == "resp-1"


def test_runtime_state_store_reset_clears_persisted_previous_openai_response_id(tmp_path):
    provider = StaticSecretProvider(b"s" * 32)
    data_dir = tmp_path / "Bot" / "data"
    account_store = AccountStore(data_dir / "accounts", "Bot", secret_provider=provider)
    state = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)

    state.set_previous_response_id("Bot", ACCOUNT_ID, "resp-1")
    state.reset_previous_response_id("Bot", ACCOUNT_ID)
    reloaded = RuntimeStateStore(data_dir, instance_name="Bot", secret_provider=provider)

    assert reloaded.get_previous_response_id("Bot", ACCOUNT_ID) is None
    assert "previous_response_id" not in account_store.read_openai_state(ACCOUNT_ID)


def test_runtime_state_store_keeps_invalid_previous_response_account_id_in_memory(tmp_path):
    state = RuntimeStateStore(tmp_path / "Bot" / "data", instance_name="Bot", secret_provider=StaticSecretProvider(b"s" * 32))

    state.set_previous_response_id("Bot", "not-a-real-account-id", "resp-1")

    assert state.get_previous_response_id("Bot", "not-a-real-account-id") == "resp-1"
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
