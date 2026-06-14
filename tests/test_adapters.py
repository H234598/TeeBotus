from __future__ import annotations

from dataclasses import dataclass

from TeeBotus.adapters.signal import signal_message_to_event
from TeeBotus.adapters.telegram import send_telegram_actions, telegram_message_to_event
from TeeBotus.runtime.actions import SendText, SendTyping


@dataclass
class FakeSignalMessage:
    source_uuid: str = "uuid-1"
    source_number: str = "+491"
    source: str = "+491"
    timestamp: str = "123"
    text: str = ""
    group: str = ""
    attachments_local_filenames: list[str] | None = None
    base64_attachments: list[str] | None = None

    def recipient(self) -> str:
        return self.source


def test_signal_attachments_without_local_filename_get_stable_fallback_name():
    event = signal_message_to_event(
        FakeSignalMessage(attachments_local_filenames=[], base64_attachments=["aGVsbG8="]),
        instance="Bot",
        adapter_slot=1,
    )

    assert len(event.attachments) == 1
    assert event.attachments[0].filename == "signal-attachment-1.bin"
    assert event.attachments[0].data == b"hello"


def test_telegram_message_without_chat_id_is_rejected():
    event = telegram_message_to_event(
        {"message_id": 1, "from": {"id": 42}, "chat": {}, "text": "hi"},
        instance="Bot",
        adapter_slot=1,
    )

    assert event is None


def test_telegram_send_keeps_string_chat_ids_for_channels():
    class API:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, str]] = []

        def send_message(self, chat_id, text):
            self.calls.append(("message", chat_id, text))
            return 1

        def send_chat_action(self, chat_id, action):
            self.calls.append(("action", chat_id, action))

    api = API()

    send_telegram_actions(api, [SendText("@my_channel", "hi"), SendTyping("@my_channel")])

    assert api.calls == [("message", "@my_channel", "hi"), ("action", "@my_channel", "typing")]
