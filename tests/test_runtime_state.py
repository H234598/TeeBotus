from __future__ import annotations

from TeeBotus.runtime.accounts import AccountStoreError, SecretToolInstanceSecretProvider, StaticSecretProvider
from TeeBotus.runtime.actions import SendEdit, SendPoll, SendReaction, SendReceipt, SetMatrixState
from TeeBotus.runtime.events import IncomingEvent
from TeeBotus.runtime.telegram_bridge import TelegramRuntimeBridge
from TeeBotus.runtime.state import RuntimeStateStore


class BrokenProvider:
    def get_secret(self, instance_name: str, purpose: str) -> bytes:
        raise AccountStoreError("secret backend unavailable")


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


def test_telegram_bridge_defaults_to_secret_tool_provider(tmp_path):
    bridge = TelegramRuntimeBridge(instance_name="Bot", data_dir=tmp_path / "Bot" / "data")

    assert isinstance(bridge.account_store.secret_provider, SecretToolInstanceSecretProvider)
    assert bridge.state_store.secret_provider is bridge.account_store.secret_provider


def test_telegram_bridge_dispatches_edit_and_poll_actions(tmp_path):
    class Sender:
        def __init__(self) -> None:
            self.messages: list[str] = []
            self.edits: list[tuple[str, str]] = []
            self.polls: list[tuple[str, list[str], dict[str, object]]] = []

        def send_message(self, text: str) -> None:
            self.messages.append(text)

        def edit_message(self, message_ref: str, text: str) -> None:
            self.edits.append((message_ref, text))

        def send_poll(self, question: str, answers: list[str], **kwargs) -> None:
            self.polls.append((question, answers, kwargs))

    bridge = TelegramRuntimeBridge(
        instance_name="Bot",
        data_dir=tmp_path / "Bot" / "data",
        secret_provider=StaticSecretProvider(b"s" * 32),
    )
    event = _telegram_event()
    sender = Sender()

    bridge.dispatch_to_sender(
        sender,
        event,
        [
            SendEdit("123", "99", "korrigiert"),
            SendPoll("123", "Tee?", ("Ja", "Nein"), allow_multiple_selections=True),
        ],
    )

    assert sender.edits == [("99", "korrigiert")]
    assert sender.polls == [("Tee?", ["Ja", "Nein"], {"allow_multiple_selections": True})]
    refs = bridge.message_tracker.pop_for_cleanup(instance_name="Bot", channel="telegram", chat_id="123", count=1)
    assert len(refs) == 1
    assert refs[0].message_ref == "telegram-unknown"


def test_telegram_bridge_falls_back_for_poll_without_sender_poll_api(tmp_path):
    class Sender:
        def __init__(self) -> None:
            self.messages: list[str] = []

        def send_message(self, text: str) -> None:
            self.messages.append(text)

    bridge = TelegramRuntimeBridge(
        instance_name="Bot",
        data_dir=tmp_path / "Bot" / "data",
        secret_provider=StaticSecretProvider(b"s" * 32),
    )
    sender = Sender()

    bridge.dispatch_to_sender(sender, _telegram_event(), [SendPoll("123", "Tee?", ("Ja", "Nein"), track=False)])

    assert sender.messages == ["Tee?\n1. Ja\n2. Nein"]


def test_telegram_bridge_ignores_unsupported_cross_channel_actions(tmp_path):
    class Sender:
        def __init__(self) -> None:
            self.messages: list[str] = []

        def send_message(self, text: str) -> None:
            self.messages.append(text)

    bridge = TelegramRuntimeBridge(
        instance_name="Bot",
        data_dir=tmp_path / "Bot" / "data",
        secret_provider=StaticSecretProvider(b"s" * 32),
    )
    sender = Sender()

    bridge.dispatch_to_sender(
        sender,
        _telegram_event(),
        [
            SendReaction("123", "99", "\U0001f44d"),
            SendReceipt("123", "99"),
            SetMatrixState("123", "m.room.topic", {"topic": "Tee"}),
        ],
    )

    assert sender.messages == []


def _telegram_event() -> IncomingEvent:
    return IncomingEvent(
        event_id="telegram:1",
        instance="Bot",
        channel="telegram",
        adapter_slot=1,
        account_id="a" * 128,
        identity_key="telegram:user:1",
        chat_id="123",
        chat_type="private",
        sender_id="1",
        sender_name="Ada",
        sender_username="",
        sender_number="",
        text="/account",
        message_ref="1",
    )
