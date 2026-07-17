from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import asyncio
import json
from signalbot.message import MessageType

from TeeBotus.adapters.matrix import matrix_message_to_event, send_matrix_actions
from TeeBotus.adapters.signal import send_signal_actions, signal_message_to_event
from TeeBotus.adapters.telegram import (
    TELEGRAM_MESSAGE_CHUNK_SIZE,
    send_telegram_actions,
    split_telegram_message,
    telegram_message_to_event,
    telegram_update_message,
)
from TeeBotus.adapters.telegram_runtime import BotIdentity, _is_reply_to_bot
from TeeBotus.runtime.actions import (
    DelaySeconds,
    ExportFile,
    MessageButton,
    SendAttachment,
    SendEdit,
    SendPoll,
    SendReaction,
    SendReceipt,
    SendText,
    SendTyping,
    SetMatrixState,
    UpdateSignalContact,
    UpdateSignalGroup,
)


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
    view_once: bool = False
    link_previews: list[object] | None = None
    quote: object | None = None
    type: object = MessageType.DATA_MESSAGE
    raw_message: str | None = None

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


def test_signal_local_attachment_name_without_base64_is_preserved():
    event = signal_message_to_event(
        FakeSignalMessage(attachments_local_filenames=["voice.ogg"], base64_attachments=[]),
        instance="Bot",
        adapter_slot=1,
    )

    assert event is not None
    assert len(event.attachments) == 1
    assert event.attachments[0].filename == "voice.ogg"
    assert event.attachments[0].content_type == "audio/ogg"
    assert event.attachments[0].data == b""


def test_signal_sync_command_uses_raw_destination_as_chat_id():
    raw_message = json.dumps(
        {
            "envelope": {
                "source": "+own",
                "sourceUuid": "own-uuid",
                "timestamp": 123,
                "syncMessage": {
                    "sentMessage": {
                        "destination": "+491234",
                        "message": "/login " + ("a" * 128) + " " + ("b" * 128),
                    }
                },
            }
        }
    )
    event = signal_message_to_event(
        FakeSignalMessage(
            source="+own",
            source_uuid="own-uuid",
            source_number="+own",
            text="/login " + ("a" * 128) + " " + ("b" * 128),
            type=MessageType.SYNC_MESSAGE,
            raw_message=raw_message,
        ),
        instance="Bot",
        adapter_slot=1,
    )

    assert event is not None
    assert event.chat_id == "+491234"
    assert event.chat_type == "private"
    assert event.text.startswith("/login ")


def test_signal_sync_non_command_is_ignored():
    raw_message = json.dumps(
        {
            "envelope": {
                "source": "+own",
                "sourceUuid": "own-uuid",
                "timestamp": 123,
                "syncMessage": {"sentMessage": {"destination": "+491234", "message": "Hallo"}},
            }
        }
    )

    event = signal_message_to_event(
        FakeSignalMessage(
            source="+own",
            source_uuid="own-uuid",
            source_number="+own",
            text="Hallo",
            type=MessageType.SYNC_MESSAGE,
            raw_message=raw_message,
        ),
        instance="Bot",
        adapter_slot=1,
    )

    assert event is None


def test_signal_reply_text_falls_back_to_raw_quote_payload():
    raw_message = json.dumps(
        {
            "envelope": {
                "dataMessage": {
                    "message": "Antwort",
                    "quote": {"id": 321, "text": "Urspruengliche Nachricht"},
                }
            }
        }
    )

    event = signal_message_to_event(
        FakeSignalMessage(text="Antwort", raw_message=raw_message),
        instance="Bot",
        adapter_slot=1,
    )

    assert event is not None
    assert event.reply_to_text == "Urspruengliche Nachricht"


def test_signal_view_once_attachment_metadata_is_preserved():
    event = signal_message_to_event(
        FakeSignalMessage(attachments_local_filenames=["voice.ogg"], base64_attachments=["aGVsbG8="], view_once=True),
        instance="Bot",
        adapter_slot=1,
    )

    assert event is not None
    assert event.attachments[0].filename == "voice.ogg"
    assert event.attachments[0].view_once is True


def test_signal_attachment_names_and_base64_are_paired_by_index():
    event = signal_message_to_event(
        FakeSignalMessage(attachments_local_filenames=["one.mp3"], base64_attachments=["MQ==", "Mg=="]),
        instance="Bot",
        adapter_slot=1,
    )

    assert event is not None
    assert [attachment.filename for attachment in event.attachments] == ["one.mp3", "signal-attachment-2.bin"]
    assert [attachment.data for attachment in event.attachments] == [b"1", b"2"]


def test_signal_attachment_content_type_uses_filename_mimetype():
    event = signal_message_to_event(
        FakeSignalMessage(attachments_local_filenames=["photo.jpg", "report.pdf"], base64_attachments=["MQ==", "Mg=="]),
        instance="Bot",
        adapter_slot=1,
    )

    assert event is not None
    assert [attachment.content_type for attachment in event.attachments] == ["image/jpeg", "application/pdf"]


def test_signal_attachment_prefers_remote_filename_from_raw_message():
    raw_message = json.dumps(
        {
            "envelope": {
                "dataMessage": {
                    "message": "Foto",
                    "attachments": [{"id": "local-attachment-id", "filename": "photo.jpg"}],
                }
            }
        }
    )
    event = signal_message_to_event(
        FakeSignalMessage(
            attachments_local_filenames=["local-attachment-id"],
            base64_attachments=["MQ=="],
            raw_message=raw_message,
        ),
        instance="Bot",
        adapter_slot=1,
    )

    assert event is not None
    assert event.attachments[0].filename == "photo.jpg"
    assert event.attachments[0].content_type == "image/jpeg"


def test_signal_raw_attachment_without_local_data_is_preserved_as_metadata():
    raw_message = json.dumps(
        {
            "envelope": {
                "dataMessage": {
                    "message": "Foto",
                    "attachments": [{"id": "remote-attachment-id", "filename": "photo.jpg"}],
                }
            }
        }
    )
    event = signal_message_to_event(
        FakeSignalMessage(
            attachments_local_filenames=[],
            base64_attachments=[],
            raw_message=raw_message,
        ),
        instance="Bot",
        adapter_slot=1,
    )

    assert event is not None
    assert len(event.attachments) == 1
    assert event.attachments[0].filename == "photo.jpg"
    assert event.attachments[0].content_type == "image/jpeg"
    assert event.attachments[0].data == b""
    assert event.attachments[0].base64_data == ""


def test_signal_edit_attachment_prefers_remote_filename_from_raw_message():
    raw_message = json.dumps(
        {
            "envelope": {
                "editMessage": {
                    "dataMessage": {
                        "message": "Foto",
                        "attachments": [{"id": "local-attachment-id", "filename": "report.pdf"}],
                    }
                }
            }
        }
    )
    event = signal_message_to_event(
        FakeSignalMessage(
            attachments_local_filenames=["local-attachment-id"],
            base64_attachments=["MQ=="],
            raw_message=raw_message,
            type=MessageType.EDIT_MESSAGE,
        ),
        instance="Bot",
        adapter_slot=1,
    )

    assert event is not None
    assert event.attachments[0].filename == "report.pdf"
    assert event.attachments[0].content_type == "application/pdf"


def test_signal_quote_text_maps_to_reply_context():
    quote = type("Quote", (), {"text": "Vorheriger Text"})()
    event = signal_message_to_event(
        FakeSignalMessage(text="Antwort", quote=quote),  # type: ignore[call-arg]
        instance="Bot",
        adapter_slot=1,
    )

    assert event is not None
    assert event.text == "Antwort"
    assert event.reply_to_text == "Vorheriger Text"


def test_signal_link_previews_map_to_event_metadata():
    preview = type(
        "Preview",
        (),
        {
            "title": "TeeBotus",
            "url": "https://example.test/tee",
            "description": "Botlink",
            "base64_thumbnail": "aW1hZ2U=",
            "id": "preview-thumb",
        },
    )()

    event = signal_message_to_event(
        FakeSignalMessage(text="Schau mal", link_previews=[preview]),
        instance="Bot",
        adapter_slot=1,
    )

    assert event is not None
    assert len(event.link_previews) == 1
    assert event.link_previews[0].title == "TeeBotus"
    assert event.link_previews[0].url == "https://example.test/tee"
    assert event.link_previews[0].description == "Botlink"
    assert event.link_previews[0].base64_thumbnail == "aW1hZ2U="
    assert event.link_previews[0].id == "preview-thumb"


def test_signal_link_preview_only_message_is_user_content():
    preview = type(
        "Preview",
        (),
        {
            "title": "TeeBotus",
            "url": "https://example.test/tee",
            "description": "",
            "base64_thumbnail": "",
            "id": "",
        },
    )()

    event = signal_message_to_event(
        FakeSignalMessage(text="", link_previews=[preview]),
        instance="Bot",
        adapter_slot=1,
    )

    assert event is not None
    assert event.text == ""
    assert len(event.link_previews) == 1
    assert event.link_previews[0].url == "https://example.test/tee"


def test_signal_edit_message_uses_target_timestamp_as_message_ref():
    message = FakeSignalMessage(text="Bearbeitet", timestamp="200", type=MessageType.EDIT_MESSAGE)
    message.target_sent_timestamp = 100

    event = signal_message_to_event(message, instance="Bot", adapter_slot=1)

    assert event is not None
    assert event.event_id == "signal:200"
    assert event.message_ref == "100"
    assert event.text == "Bearbeitet"


def test_signal_non_content_message_types_are_ignored():
    for message_type in (
        MessageType.CONTACT_SYNC_MESSAGE,
        MessageType.DELETE_MESSAGE,
        MessageType.GROUP_UPDATE_MESSAGE,
        MessageType.REACTION_MESSAGE,
        MessageType.READ_MESSAGE,
        MessageType.SYNC_MESSAGE,
    ):
        event = signal_message_to_event(
            FakeSignalMessage(type=message_type, text="/account"),
            instance="Bot",
            adapter_slot=1,
        )

        assert event is None


def test_signal_message_without_identity_is_rejected():
    event = signal_message_to_event(
        FakeSignalMessage(source_uuid="", source_number="", source="", text="/account"),
        instance="Bot",
        adapter_slot=1,
    )

    assert event is None


def test_signal_message_without_recipient_is_rejected():
    class Message(FakeSignalMessage):
        def recipient(self) -> str:
            return ""

    event = signal_message_to_event(
        Message(text="/account"),
        instance="Bot",
        adapter_slot=1,
    )

    assert event is None


def test_signal_message_with_broken_recipient_is_rejected():
    class Message(FakeSignalMessage):
        def recipient(self) -> str:
            raise RuntimeError("signalbot recipient failed")

    event = signal_message_to_event(
        Message(text="/account"),
        instance="Bot",
        adapter_slot=1,
    )

    assert event is None


def test_signal_typing_is_stopped_after_followup_send():
    class Context:
        def __init__(self) -> None:
            self.calls = []

        async def start_typing(self) -> None:
            self.calls.append("start_typing")

        async def stop_typing(self) -> None:
            self.calls.append("stop_typing")

        async def send(self, text, **_kwargs):
            self.calls.append(("send", text))
            return 123

    context = Context()

    sent = asyncio.run(send_signal_actions(context, [SendTyping("+491"), SendText("+491", "hi")]))

    assert sent == [None, 123]
    assert context.calls == ["start_typing", ("send", "hi"), "stop_typing"]


def test_signal_send_delay_preserves_result_alignment(monkeypatch):
    class Context:
        def __init__(self) -> None:
            self.calls = []

        async def send(self, text, **_kwargs):
            self.calls.append(("send", text))
            return len(self.calls)

    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("TeeBotus.adapters.signal.asyncio.sleep", fake_sleep)

    context = Context()

    sent = asyncio.run(send_signal_actions(context, [SendText("+491", "vorher"), DelaySeconds(1.0), SendText("+491", "danach")]))

    assert sent == [1, None, 2]
    assert sleeps == [1.0]
    assert context.calls == [("send", "vorher"), ("send", "danach")]


def test_signal_send_reports_completed_action_before_later_failure():
    class Context:
        async def send(self, text, **_kwargs):
            if text == "danach":
                raise RuntimeError("temporary failure")
            return 101

    completed: list[str] = []

    try:
        asyncio.run(
            send_signal_actions(
                Context(),
                [SendText("+491", "vorher"), SendText("+491", "danach")],
                on_action_sent=lambda action, _ref: completed.append(action.text),
            )
        )
    except RuntimeError as exc:
        assert str(exc) == "temporary failure"
    else:
        raise AssertionError("later Signal action should fail")

    assert completed == ["vorher"]


def test_signal_unknown_action_preserves_result_alignment():
    class Context:
        async def send(self, text, **_kwargs):
            return 123

    sent = asyncio.run(send_signal_actions(Context(), [object(), SendText("+491", "hi")]))

    assert sent == [None, 123]


def test_signal_actions_accept_sync_signalbot_context_methods():
    class Context:
        def __init__(self) -> None:
            self.calls = []

        def start_typing(self) -> None:
            self.calls.append("start_typing")

        def stop_typing(self) -> None:
            self.calls.append("stop_typing")

        def send(self, text, **_kwargs):
            self.calls.append(("send", text))
            return 123

    context = Context()

    sent = asyncio.run(send_signal_actions(context, [SendTyping("+491"), SendText("+491", "hi")]))

    assert sent == [None, 123]
    assert context.calls == ["start_typing", ("send", "hi"), "stop_typing"]


def test_signal_typing_is_stopped_when_send_fails():
    class Context:
        def __init__(self) -> None:
            self.calls = []

        async def start_typing(self) -> None:
            self.calls.append("start_typing")

        async def stop_typing(self) -> None:
            self.calls.append("stop_typing")

        async def send(self, _text, **_kwargs):
            self.calls.append("send")
            raise OSError("send refused")

    context = Context()

    try:
        asyncio.run(send_signal_actions(context, [SendTyping("+491"), SendText("+491", "hi")]))
    except OSError as exc:
        assert "send refused" in str(exc)
    else:
        raise AssertionError("OSError was not raised")

    assert context.calls == ["start_typing", "send", "stop_typing"]


def test_signal_typing_to_other_chat_uses_bot_typing_and_stops_after_send():
    class Bot:
        def __init__(self) -> None:
            self.calls = []

        async def start_typing(self, receiver) -> None:
            self.calls.append(("start_typing", receiver))

        async def stop_typing(self, receiver) -> None:
            self.calls.append(("stop_typing", receiver))

        async def send(self, receiver, text, **kwargs):
            self.calls.append(("send", receiver, text, kwargs))
            return 456

    class Context:
        def __init__(self) -> None:
            self.bot = Bot()
            self.message = FakeSignalMessage(source="+491")
            self.context_calls = []

        async def start_typing(self) -> None:
            self.context_calls.append("start_typing")

        async def stop_typing(self) -> None:
            self.context_calls.append("stop_typing")

        async def send(self, text, **kwargs):
            self.context_calls.append(("send", text, kwargs))
            return 123

    context = Context()

    sent = asyncio.run(send_signal_actions(context, [SendTyping("+492"), SendText("+492", "hi")]))

    assert sent == [None, 456]
    assert context.context_calls == []
    assert context.bot.calls == [
        ("start_typing", "+492"),
        ("send", "+492", "hi", {"base64_attachments": None}),
        ("stop_typing", "+492"),
    ]


def test_signal_actions_accept_sync_signalbot_bot_methods_for_other_chat():
    class Bot:
        def __init__(self) -> None:
            self.calls = []

        def start_typing(self, receiver) -> None:
            self.calls.append(("start_typing", receiver))

        def stop_typing(self, receiver) -> None:
            self.calls.append(("stop_typing", receiver))

        def send(self, receiver, text, **kwargs):
            self.calls.append(("send", receiver, text, kwargs))
            return 456

    class Context:
        def __init__(self) -> None:
            self.bot = Bot()
            self.message = FakeSignalMessage(source="+491")

        def send(self, _text, **_kwargs):
            raise AssertionError("context.send should not be used for other chat")

    context = Context()

    sent = asyncio.run(send_signal_actions(context, [SendTyping("+492"), SendText("+492", "hi")]))

    assert sent == [None, 456]
    assert context.bot.calls == [
        ("start_typing", "+492"),
        ("send", "+492", "hi", {"base64_attachments": None}),
        ("stop_typing", "+492"),
    ]


def test_signal_send_uses_context_when_current_recipient_lookup_fails():
    class Message(FakeSignalMessage):
        def recipient(self) -> str:
            raise RuntimeError("signalbot recipient failed")

    class Context:
        def __init__(self) -> None:
            self.message = Message(source="+491")
            self.calls = []

        async def send(self, text, **kwargs):
            self.calls.append(("send", text, kwargs))
            return 123

    context = Context()

    sent = asyncio.run(send_signal_actions(context, [SendText("+491", "hi")]))

    assert sent == [123]
    assert context.calls == [("send", "hi", {"base64_attachments": None})]


def test_signal_send_text_appends_button_fallback():
    class Context:
        message = FakeSignalMessage(source="+491")

        def __init__(self) -> None:
            self.calls = []

        async def send(self, text, **kwargs):
            self.calls.append(("send", text, kwargs))
            return 124

    context = Context()

    sent = asyncio.run(send_signal_actions(context, [SendText("+491", "Frage?", buttons=(MessageButton("Ja", "ja"),))]))

    assert sent == [124]
    assert context.calls == [("send", "Frage?\n\nOptionen:\n- Ja: ja", {"base64_attachments": None})]


def test_signal_send_text_rejects_missing_timestamp():
    class Context:
        message = FakeSignalMessage(source="+491")

        async def send(self, _text, **_kwargs):
            return None

    try:
        asyncio.run(send_signal_actions(Context(), [SendText("+491", "hi")]))
    except RuntimeError as exc:
        assert "Signal text send returned no numeric timestamp" in str(exc)
    else:
        raise AssertionError("RuntimeError was not raised")


def test_signal_send_text_accepts_numeric_string_timestamp():
    class Context:
        message = FakeSignalMessage(source="+491")

        async def send(self, _text, **_kwargs):
            return "123456"

    sent = asyncio.run(send_signal_actions(Context(), [SendText("+491", "hi")]))

    assert sent == [123456]


def test_signal_typing_stops_previous_target_before_starting_new_target():
    class Bot:
        def __init__(self) -> None:
            self.calls = []

        async def start_typing(self, receiver) -> None:
            self.calls.append(("start_typing", receiver))

        async def stop_typing(self, receiver) -> None:
            self.calls.append(("stop_typing", receiver))

        async def send(self, receiver, text, **kwargs):
            self.calls.append(("send", receiver, text, kwargs))
            return 456

    class Context:
        def __init__(self) -> None:
            self.bot = Bot()
            self.message = FakeSignalMessage(source="+491")
            self.context_calls = []

        async def start_typing(self) -> None:
            self.context_calls.append("start_typing")

        async def stop_typing(self) -> None:
            self.context_calls.append("stop_typing")

        async def send(self, text, **kwargs):
            self.context_calls.append(("send", text, kwargs))
            return 123

    context = Context()

    sent = asyncio.run(send_signal_actions(context, [SendTyping("+491"), SendTyping("+492"), SendText("+492", "hi")]))

    assert sent == [None, None, 456]
    assert context.context_calls == ["start_typing", "stop_typing"]
    assert context.bot.calls == [
        ("start_typing", "+492"),
        ("send", "+492", "hi", {"base64_attachments": None}),
        ("stop_typing", "+492"),
    ]


def test_signal_reaction_uses_current_context_message():
    class Context:
        def __init__(self) -> None:
            self.message = FakeSignalMessage(source="+491", timestamp="123")
            self.reactions = []

        async def react(self, emoji):
            self.reactions.append(emoji)

    context = Context()

    sent = asyncio.run(send_signal_actions(context, [SendReaction("+491", "123", "\U0001f44d")]))

    assert sent == [None]
    assert context.reactions == ["\U0001f44d"]


def test_signal_receipt_uses_current_context_message():
    class Context:
        def __init__(self) -> None:
            self.message = FakeSignalMessage(source="+491", timestamp="123")
            self.receipts = []

        async def receipt(self, receipt_type):
            self.receipts.append(receipt_type)

    context = Context()

    sent = asyncio.run(send_signal_actions(context, [SendReceipt("+491", "123", "viewed")]))

    assert sent == [None]
    assert context.receipts == ["viewed"]


def test_signal_reaction_rejects_non_current_message_ref():
    class Context:
        def __init__(self) -> None:
            self.message = FakeSignalMessage(source="+491", timestamp="123")

        async def react(self, _emoji):
            raise AssertionError("react should not be called")

    try:
        asyncio.run(send_signal_actions(Context(), [SendReaction("+491", "999", "\U0001f44d")]))
    except RuntimeError as exc:
        assert "current message" in str(exc)
    else:
        raise AssertionError("RuntimeError was not raised")


def test_signal_reaction_requires_message_ref():
    class Context:
        def __init__(self) -> None:
            self.message = FakeSignalMessage(source="+491", timestamp="123")

        async def react(self, _emoji):
            raise AssertionError("react should not be called")

    try:
        asyncio.run(send_signal_actions(Context(), [SendReaction("+491", "", "\U0001f44d")]))
    except RuntimeError as exc:
        assert "requires a message_ref" in str(exc)
    else:
        raise AssertionError("RuntimeError was not raised")


def test_signal_receipt_requires_message_ref():
    class Context:
        def __init__(self) -> None:
            self.message = FakeSignalMessage(source="+491", timestamp="123")

        async def receipt(self, _receipt_type):
            raise AssertionError("receipt should not be called")

    try:
        asyncio.run(send_signal_actions(Context(), [SendReceipt("+491", "")]))
    except RuntimeError as exc:
        assert "requires a message_ref" in str(exc)
    else:
        raise AssertionError("RuntimeError was not raised")


def test_signal_edit_uses_context_edit_for_current_message():
    class Context:
        def __init__(self) -> None:
            self.message = FakeSignalMessage(source="+491", timestamp="123")
            self.edits = []

        async def edit(self, text, edit_timestamp, **kwargs):
            self.edits.append((text, edit_timestamp, kwargs))
            return 456

    context = Context()

    sent = asyncio.run(send_signal_actions(context, [SendEdit("+491", "123", "korrigiert")]))

    assert sent == [456]
    assert context.edits == [("korrigiert", 123, {})]


def test_signal_edit_to_other_chat_uses_bot_edit_timestamp():
    class Bot:
        def __init__(self) -> None:
            self.calls = []

        async def send(self, receiver, text, **kwargs):
            self.calls.append((receiver, text, kwargs))
            return 789

    class Context:
        def __init__(self) -> None:
            self.message = FakeSignalMessage(source="+491", timestamp="123")
            self.bot = Bot()

    context = Context()

    sent = asyncio.run(send_signal_actions(context, [SendEdit("+492", "555", "extern korrigiert")]))

    assert sent == [789]
    assert context.bot.calls == [("+492", "extern korrigiert", {"edit_timestamp": 555})]


def test_signal_edit_passes_signalbot_send_options():
    class Context:
        def __init__(self) -> None:
            self.message = FakeSignalMessage(source="+491", timestamp="123")
            self.edits = []

        async def edit(self, text, edit_timestamp, **kwargs):
            self.edits.append((text, edit_timestamp, kwargs))
            return 456

    context = Context()
    mentions = ({"author": "ada-uuid", "start": 6, "length": 4},)
    link_preview = object()

    sent = asyncio.run(
        send_signal_actions(
            context,
            [
                SendEdit(
                    "+491",
                    "123",
                    "Hallo @ada",
                    mentions=mentions,
                    text_mode="styled",
                    view_once=True,
                    link_preview=link_preview,
                )
            ],
        )
    )

    assert sent == [456]
    assert context.edits == [
        (
            "Hallo @ada",
            123,
            {
                "mentions": list(mentions),
                "text_mode": "styled",
                "view_once": True,
                "link_preview": link_preview,
            },
        )
    ]


def test_signal_edit_rejects_non_numeric_message_ref():
    class Context:
        message = FakeSignalMessage(source="+491", timestamp="123")

    try:
        asyncio.run(send_signal_actions(Context(), [SendEdit("+491", "$event", "nope")]))
    except RuntimeError as exc:
        assert "numeric message_ref" in str(exc)
    else:
        raise AssertionError("RuntimeError was not raised")


def test_signal_poll_uses_signalbot_poll():
    class Bot:
        def __init__(self) -> None:
            self.calls = []

        async def poll(self, receiver, question, answers, **kwargs):
            self.calls.append((receiver, question, answers, kwargs))
            return 678

    class Context:
        def __init__(self) -> None:
            self.message = FakeSignalMessage(source="+491")
            self.bot = Bot()

    context = Context()

    sent = asyncio.run(send_signal_actions(context, [SendPoll("+491", "Tee?", ("Ja", "Nein"), allow_multiple_selections=True)]))

    assert sent == [678]
    assert context.bot.calls == [("+491", "Tee?", ["Ja", "Nein"], {"allow_multiple_selections": True})]


def test_signal_poll_rejects_too_few_answers():
    class Bot:
        async def poll(self, *_args, **_kwargs):
            raise AssertionError("poll should not be called")

    class Context:
        message = FakeSignalMessage(source="+491")
        bot = Bot()

    try:
        asyncio.run(send_signal_actions(Context(), [SendPoll("+491", "Tee?", ("Ja",))]))
    except RuntimeError as exc:
        assert "at least two answers" in str(exc)
    else:
        raise AssertionError("RuntimeError was not raised")


def test_signal_update_contact_uses_signalbot_update_contact():
    class Bot:
        def __init__(self) -> None:
            self.calls = []

        async def update_contact(self, receiver, **kwargs):
            self.calls.append((receiver, kwargs))

    class Context:
        bot = Bot()

    context = Context()

    sent = asyncio.run(send_signal_actions(context, [UpdateSignalContact("+491", expiration_in_seconds=3600, name="Ada")]))

    assert sent == [None]
    assert context.bot.calls == [("+491", {"expiration_in_seconds": 3600, "name": "Ada"})]


def test_signal_update_group_uses_signalbot_update_group():
    class Bot:
        def __init__(self) -> None:
            self.calls = []

        async def update_group(self, group_id, **kwargs):
            self.calls.append((group_id, kwargs))

    class Context:
        bot = Bot()

    context = Context()

    sent = asyncio.run(
        send_signal_actions(
            context,
            [
                UpdateSignalGroup(
                    "group-id",
                    base64_avatar="YXZhdGFy",
                    description="Beschreibung",
                    expiration_in_seconds=7200,
                    name="Teegruppe",
                )
            ],
        )
    )

    assert sent == [None]
    assert context.bot.calls == [
        (
            "group-id",
            {
                "base64_avatar": "YXZhdGFy",
                "description": "Beschreibung",
                "expiration_in_seconds": 7200,
                "name": "Teegruppe",
            },
        )
    ]


def test_signal_update_group_resolves_internal_id_with_signalbot_get_group():
    class Bot:
        def __init__(self) -> None:
            self.get_group_calls = []
            self.calls = []

        def get_group(self, internal_id):
            self.get_group_calls.append(internal_id)
            return {"id": "resolved-group-id", "internal_id": internal_id, "name": "Teegruppe"}

        async def update_group(self, group_id, **kwargs):
            self.calls.append((group_id, kwargs))

    class Context:
        bot = Bot()

    context = Context()

    sent = asyncio.run(send_signal_actions(context, [UpdateSignalGroup("internal-group-id", name="Neu")]))

    assert sent == [None]
    assert context.bot.get_group_calls == ["internal-group-id"]
    assert context.bot.calls == [("resolved-group-id", {"base64_avatar": None, "description": None, "expiration_in_seconds": None, "name": "Neu"})]


def test_signal_update_group_falls_back_when_signalbot_get_group_fails():
    class Bot:
        def __init__(self) -> None:
            self.calls = []

        def get_group(self, _internal_id):
            raise RuntimeError("group cache unavailable")

        async def update_group(self, group_id, **kwargs):
            self.calls.append((group_id, kwargs))

    class Context:
        bot = Bot()

    context = Context()

    sent = asyncio.run(send_signal_actions(context, [UpdateSignalGroup("group-id", description="Beschreibung")]))

    assert sent == [None]
    assert context.bot.calls == [("group-id", {"base64_avatar": None, "description": "Beschreibung", "expiration_in_seconds": None, "name": None})]


def test_signal_ignores_matrix_state_action():
    class Context:
        pass

    sent = asyncio.run(send_signal_actions(Context(), [SetMatrixState("+491", "m.room.topic", {"topic": "Tee"})]))

    assert sent == [None]


def test_signal_send_text_can_quote_current_message_with_bot_send():
    class Bot:
        def __init__(self) -> None:
            self.calls = []

        async def send(self, receiver, text, **kwargs):
            self.calls.append((receiver, text, kwargs))
            return 456

    class Context:
        def __init__(self) -> None:
            self.bot = Bot()
            self.message = FakeSignalMessage(text="Original", timestamp="123")
            self.context_calls = []

        async def send(self, text, **kwargs):
            self.context_calls.append((text, kwargs))
            return 123

    context = Context()

    sent = asyncio.run(send_signal_actions(context, [SendText("+491", "Antwort", reply_to_ref="123")]))

    assert sent == [456]
    assert context.context_calls == []
    assert context.bot.calls == [
        (
            "+491",
            "Antwort",
            {
                "base64_attachments": None,
                "quote_author": "+491",
                "quote_message": "Original",
                "quote_timestamp": 123,
            },
        )
    ]


def test_signal_send_text_prefers_context_reply_for_current_message():
    class Context:
        def __init__(self) -> None:
            self.message = FakeSignalMessage(text="Original", timestamp="123")
            self.reply_calls = []
            self.send_calls = []

        async def reply(self, text, **kwargs):
            self.reply_calls.append((text, kwargs))
            return 789

        async def send(self, text, **kwargs):
            self.send_calls.append((text, kwargs))
            return 123

    context = Context()

    sent = asyncio.run(send_signal_actions(context, [SendText("+491", "Antwort", reply_to_ref="123")]))

    assert sent == [789]
    assert context.reply_calls == [("Antwort", {"base64_attachments": None})]
    assert context.send_calls == []


def test_signal_send_text_keeps_manual_quote_for_edit_target_timestamp():
    class Bot:
        def __init__(self) -> None:
            self.calls = []

        async def send(self, receiver, text, **kwargs):
            self.calls.append((receiver, text, kwargs))
            return 456

    class Context:
        def __init__(self) -> None:
            self.bot = Bot()
            self.message = FakeSignalMessage(text="Bearbeitet", timestamp="200", type=MessageType.EDIT_MESSAGE)
            self.message.target_sent_timestamp = 100
            self.reply_calls = []

        async def reply(self, text, **kwargs):
            self.reply_calls.append((text, kwargs))
            return 789

        async def send(self, text, **kwargs):
            return 123

    context = Context()

    sent = asyncio.run(send_signal_actions(context, [SendText("+491", "Antwort", reply_to_ref="100")]))

    assert sent == [456]
    assert context.reply_calls == []
    assert context.bot.calls == [
        (
            "+491",
            "Antwort",
            {
                "base64_attachments": None,
                "quote_author": "+491",
                "quote_message": "Bearbeitet",
                "quote_timestamp": 100,
            },
        )
    ]


def test_signal_manual_quote_preserves_converted_mentions():
    class Bot:
        def __init__(self) -> None:
            self.calls = []

        async def send(self, receiver, text, **kwargs):
            self.calls.append((receiver, text, kwargs))
            return 456

    class Context:
        def __init__(self) -> None:
            self.bot = Bot()
            self.message = FakeSignalMessage(text="Hallo @ada", timestamp="200", type=MessageType.EDIT_MESSAGE)
            self.message.target_sent_timestamp = 100
            self.message.mentions = [{"uuid": "ada-uuid", "start": 6, "length": 4}]

        def _convert_receive_mentions_into_send_mentions(self, mentions):
            converted = [dict(mention) for mention in mentions]
            converted[0]["author"] = converted[0]["uuid"]
            return converted

        async def send(self, text, **kwargs):
            return 123

    context = Context()

    sent = asyncio.run(send_signal_actions(context, [SendText("+491", "Antwort", reply_to_ref="100")]))

    assert sent == [456]
    assert context.bot.calls[0][2]["quote_mentions"] == [{"uuid": "ada-uuid", "start": 6, "length": 4, "author": "ada-uuid"}]


def test_signal_send_text_falls_back_without_matching_quote_context():
    class Context:
        def __init__(self) -> None:
            self.message = FakeSignalMessage(text="Original", timestamp="123")
            self.calls = []

        async def send(self, text, **kwargs):
            self.calls.append((text, kwargs))
            return 123

    context = Context()

    sent = asyncio.run(send_signal_actions(context, [SendText("+491", "Antwort", reply_to_ref="999")]))

    assert sent == [123]
    assert context.calls == [("Antwort", {"base64_attachments": None})]


def test_signal_send_text_to_other_chat_uses_bot_send():
    class Bot:
        def __init__(self) -> None:
            self.calls = []

        async def send(self, receiver, text, **kwargs):
            self.calls.append((receiver, text, kwargs))
            return 456

    class Context:
        def __init__(self) -> None:
            self.bot = Bot()
            self.message = FakeSignalMessage(text="Original", source="+491")
            self.context_calls = []

        async def send(self, text, **kwargs):
            self.context_calls.append((text, kwargs))
            return 123

    context = Context()

    sent = asyncio.run(send_signal_actions(context, [SendText("+492", "Direktnachricht")]))

    assert sent == [456]
    assert context.context_calls == []
    assert context.bot.calls == [("+492", "Direktnachricht", {"base64_attachments": None})]


def test_signal_send_text_passes_signalbot_send_options():
    class Context:
        def __init__(self) -> None:
            self.message = FakeSignalMessage(source="+491")
            self.calls = []

        async def send(self, text, **kwargs):
            self.calls.append((text, kwargs))
            return 123

    context = Context()
    mentions = ({"author": "ada-uuid", "start": 6, "length": 4},)
    link_preview = object()

    sent = asyncio.run(
        send_signal_actions(
            context,
            [
                SendText(
                    "+491",
                    "Hallo @ada",
                    mentions=mentions,
                    text_mode="styled",
                    view_once=True,
                    link_preview=link_preview,
                )
            ],
        )
    )

    assert sent == [123]
    assert context.calls == [
        (
            "Hallo @ada",
            {
                "base64_attachments": None,
                "mentions": list(mentions),
                "text_mode": "styled",
                "view_once": True,
                "link_preview": link_preview,
            },
        )
    ]


def test_signal_send_text_coerces_link_preview_dict_to_signalbot_model():
    class Context:
        def __init__(self) -> None:
            self.message = FakeSignalMessage(source="+491")
            self.calls = []

        async def send(self, text, **kwargs):
            self.calls.append((text, kwargs))
            return 123

    context = Context()

    sent = asyncio.run(
        send_signal_actions(
            context,
            [
                SendText(
                    "+491",
                    "Link",
                    link_preview={
                        "base64_thumbnail": None,
                        "title": "TeeBotus",
                        "description": "Bot",
                        "url": "https://example.test/tee",
                    },
                )
            ],
        )
    )

    assert sent == [123]
    preview = context.calls[0][1]["link_preview"]
    assert preview.model_dump() == {
        "base64_thumbnail": None,
        "title": "TeeBotus",
        "description": "Bot",
        "url": "https://example.test/tee",
        "id": None,
    }


def test_signal_send_text_rejects_incomplete_link_preview_dict():
    class Context:
        def __init__(self) -> None:
            self.message = FakeSignalMessage(source="+491")

        async def send(self, _text, **_kwargs):
            raise AssertionError("send should not run with invalid link preview")

    try:
        asyncio.run(send_signal_actions(Context(), [SendText("+491", "Link", link_preview={"title": "missing url"})]))
    except RuntimeError as exc:
        assert str(exc) == "Signal link_preview requires title and url"
    else:
        raise AssertionError("RuntimeError was not raised")


def test_signal_send_attachment_uses_filename_when_caption_is_empty():
    class Context:
        def __init__(self) -> None:
            self.calls = []

        async def send(self, text, **kwargs):
            self.calls.append((text, kwargs))
            return 123

    context = Context()

    sent = asyncio.run(send_signal_actions(context, [SendAttachment("+491", b"hello", "voice.ogg", "audio/ogg")]))

    assert sent == [123]
    assert context.calls == [("voice.ogg", {"base64_attachments": ["aGVsbG8="]})]


def test_signal_send_attachment_to_other_chat_uses_bot_send():
    class Bot:
        def __init__(self) -> None:
            self.calls = []

        async def send(self, receiver, text, **kwargs):
            self.calls.append((receiver, text, kwargs))
            return 456

    class Context:
        def __init__(self) -> None:
            self.bot = Bot()
            self.message = FakeSignalMessage(source="+491")
            self.context_calls = []

        async def send(self, text, **kwargs):
            self.context_calls.append((text, kwargs))
            return 123

    context = Context()

    sent = asyncio.run(send_signal_actions(context, [SendAttachment("+492", b"hello", "voice.ogg", "audio/ogg")]))

    assert sent == [456]
    assert context.context_calls == []
    assert context.bot.calls == [("+492", "voice.ogg", {"base64_attachments": ["aGVsbG8="]})]


def test_signal_send_attachment_passes_signalbot_send_options():
    class Context:
        def __init__(self) -> None:
            self.calls = []

        async def send(self, text, **kwargs):
            self.calls.append((text, kwargs))
            return 123

    context = Context()

    sent = asyncio.run(
        send_signal_actions(
            context,
            [
                SendAttachment(
                    "+491",
                    b"hello",
                    "photo.jpg",
                    "image/jpeg",
                    caption="Bild",
                    text_mode="styled",
                    view_once=True,
                )
            ],
        )
    )

    assert sent == [123]
    assert context.calls == [
        (
            "Bild",
            {
                "base64_attachments": ["aGVsbG8="],
                "text_mode": "styled",
                "view_once": True,
            },
        )
    ]


def test_signal_export_file_uses_caption_when_present():
    class Context:
        def __init__(self) -> None:
            self.calls = []

        async def send(self, text, **kwargs):
            self.calls.append((text, kwargs))
            return 123

    context = Context()

    sent = asyncio.run(
        send_signal_actions(
            context,
            [ExportFile("+491", "report.json", "application/json", b"{\"ok\": true}", caption="TeeBotus Account Export")],
        )
    )

    assert sent == [123]
    assert context.calls == [("TeeBotus Account Export", {"base64_attachments": ["eyJvayI6IHRydWV9"]})]


def test_telegram_message_without_chat_id_is_rejected():
    event = telegram_message_to_event(
        {"message_id": 1, "from": {"id": 42}, "chat": {}, "text": "hi"},
        instance="Bot",
        adapter_slot=1,
    )

    assert event is None


def test_telegram_message_uses_username_identity_fallback_without_sender_id():
    event = telegram_message_to_event(
        {
            "message_id": 1,
            "from": {"username": "Teladi", "first_name": "Te", "last_name": "Ladi"},
            "chat": {"id": 42, "type": "private"},
            "text": "hi",
        },
        instance="Bot",
        adapter_slot=1,
    )

    assert event is not None
    assert event.identity_key == "telegram:username:teladi"
    assert event.sender_id == ""
    assert event.sender_name == "Te Ladi"
    assert event.sender_username == "Teladi"


def test_telegram_message_uses_sender_chat_identity_fallback():
    event = telegram_message_to_event(
        {
            "message_id": 1,
            "sender_chat": {"id": -100123, "title": "Tee Kanal", "username": "TeeKanal"},
            "chat": {"id": -100123, "type": "channel", "title": "Tee Kanal"},
            "text": "hi",
        },
        instance="Bot",
        adapter_slot=1,
    )

    assert event is not None
    assert event.identity_key == "telegram:user:-100123"
    assert event.sender_id == "-100123"
    assert event.sender_name == "Tee Kanal"
    assert event.sender_username == "TeeKanal"


def test_telegram_channel_post_update_is_converted_to_event():
    event = telegram_message_to_event(
        update={
            "update_id": 10,
            "channel_post": {
                "message_id": 2,
                "sender_chat": {"id": -100123, "title": "Tee Kanal"},
                "chat": {"id": -100123, "type": "channel", "title": "Tee Kanal"},
                "text": "Kanalpost",
            },
        },
        instance="Bot",
        adapter_slot=1,
    )

    assert event is not None
    assert event.event_id == "telegram:2"
    assert event.text == "Kanalpost"
    assert event.chat_type == "group"


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


def test_telegram_send_delay_preserves_result_alignment(monkeypatch):
    class API:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def send_message(self, chat_id, text):
            self.calls.append((chat_id, text))
            return len(self.calls)

    sleeps: list[float] = []
    monkeypatch.setattr("TeeBotus.adapters.telegram.time.sleep", lambda seconds: sleeps.append(seconds))

    api = API()

    sent = send_telegram_actions(api, [SendText("1", "vorher"), DelaySeconds(1.0), SendText("1", "danach")])

    assert sent == [1, None, 2]
    assert sleeps == [1.0]
    assert api.calls == [("1", "vorher"), ("1", "danach")]


def test_telegram_direct_adapter_splits_long_text_with_reply_and_buttons():
    class API:
        def __init__(self) -> None:
            self.calls = []

        def send_message(self, chat_id, text, **kwargs):
            self.calls.append((chat_id, text, kwargs))
            return len(self.calls)

    api = API()

    sent = send_telegram_actions(
        api,
        [
            SendText(
                "1",
                "wort " * 1200,
                reply_to_ref="77",
                buttons=(MessageButton("Weiter", "weiter"),),
            )
        ],
    )

    assert len(api.calls) > 1
    assert sent == [len(api.calls)]
    assert all(len(text) <= TELEGRAM_MESSAGE_CHUNK_SIZE for _, text, _ in api.calls)
    assert json.loads(api.calls[0][2]["reply_parameters"]) == {"message_id": 77}
    assert "reply_parameters" not in api.calls[-1][2]
    assert "reply_markup" in api.calls[-1][2]


def test_telegram_chunks_respect_utf16_message_limit():
    chunks = split_telegram_message("😀" * 2500)

    assert len(chunks) > 1
    assert all(len(chunk.encode("utf-16-le")) // 2 <= TELEGRAM_MESSAGE_CHUNK_SIZE for chunk in chunks)
    assert "".join(chunks) == "😀" * 2500


def test_telegram_send_text_passes_formatted_text_when_supported():
    class API:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, dict[str, str]]] = []

        def send_message(self, chat_id, text, **kwargs):
            self.calls.append((chat_id, text, kwargs))
            return 1

    api = API()

    send_telegram_actions(
        api,
        [
            SendText(
                "@my_channel",
                "Release Log https://github.com/H234598/TeeBotus/releases",
                text_mode="html",
                formatted_text='<a href="https://github.com/H234598/TeeBotus/releases">Release Log</a>',
            )
        ],
    )

    assert api.calls == [
        (
            "@my_channel",
            "Release Log https://github.com/H234598/TeeBotus/releases",
            {
                "text_mode": "html",
                "formatted_text": '<a href="https://github.com/H234598/TeeBotus/releases">Release Log</a>',
            },
        )
    ]


def test_telegram_send_text_passes_reply_parameters_when_supported():
    class API:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, dict[str, str]]] = []

        def send_message(self, chat_id, text, **kwargs):
            self.calls.append((chat_id, text, kwargs))
            return 2

    api = API()

    sent = send_telegram_actions(api, [SendText("@my_channel", "Antwort", reply_to_ref="99")])

    assert sent == [2]
    assert json.loads(api.calls[0][2]["reply_parameters"]) == {"message_id": 99}


def test_telegram_send_text_passes_inline_buttons_when_supported():
    class API:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, dict[str, str]]] = []

        def send_message(self, chat_id, text, **kwargs):
            self.calls.append((chat_id, text, kwargs))
            return 7

    api = API()

    sent = send_telegram_actions(
        api,
        [
            SendText(
                "@my_channel",
                "Bitte waehlen",
                buttons=(
                    MessageButton("Ja", "ja"),
                    MessageButton("AGB", url="https://example.test/agb"),
                ),
            )
        ],
    )

    assert sent == [7]
    assert api.calls[0][0:2] == ("@my_channel", "Bitte waehlen")
    reply_markup = json.loads(api.calls[0][2]["reply_markup"])
    assert reply_markup == {
        "inline_keyboard": [[{"text": "Ja", "callback_data": "ja"}, {"text": "AGB", "url": "https://example.test/agb"}]]
    }


def test_telegram_send_text_appends_button_fallback_when_reply_markup_is_not_supported():
    class API:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def send_message(self, chat_id, text):
            self.calls.append((chat_id, text))
            return 8

    api = API()

    sent = send_telegram_actions(api, [SendText("@my_channel", "Bitte waehlen", buttons=(MessageButton("Ja", "ja"),))])

    assert sent == [8]
    assert api.calls == [("@my_channel", "Bitte waehlen\n\nOptionen:\n- Ja: ja")]


def test_telegram_send_text_does_not_swallow_real_type_error():
    class API:
        def send_message(self, chat_id, text, **kwargs):
            raise TypeError("text_mode must be html")

    try:
        send_telegram_actions(
            API(),
            [SendText("@my_channel", "Antwort", text_mode="html", formatted_text="<b>Antwort</b>")],
        )
    except TypeError as exc:
        assert str(exc) == "text_mode must be html"
    else:
        raise AssertionError("real text TypeError was swallowed")


def test_telegram_callback_query_maps_button_data_to_event_text():
    update = {
        "callback_query": {
            "id": "cb-1",
            "from": {"id": 456, "first_name": "Ada", "username": "ada"},
            "data": "ja",
            "message": {"message_id": 99, "chat": {"id": 123, "type": "private"}, "text": "Bitte waehlen"},
        }
    }

    message = telegram_update_message(update)
    event = telegram_message_to_event(update=update, instance="Depressionsbot", adapter_slot=1)

    assert message is not None
    assert message["callback_query_id"] == "cb-1"
    assert event is not None
    assert event.text == "ja"
    assert event.sender_id == "456"


def test_telegram_callback_query_preserves_bot_origin_for_group_routing():
    update = {
        "callback_query": {
            "id": "cb-group-1",
            "from": {"id": 456, "first_name": "Ada"},
            "data": "ja",
            "message": {
                "message_id": 99,
                "chat": {"id": -100, "type": "group"},
                "from": {"id": 99, "is_bot": True, "first_name": "Mondbot"},
                "text": "Bitte waehlen",
            },
        }
    }

    message = telegram_update_message(update)

    assert message is not None
    assert _is_reply_to_bot(message, BotIdentity(id=99, first_name="Mondbot")) is True


def test_telegram_send_edit_uses_optional_edit_message_text():
    class API:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, str]] = []

        def edit_message_text(self, chat_id, message_id, text):
            self.calls.append((chat_id, message_id, text))
            return 2

    api = API()

    sent = send_telegram_actions(api, [SendEdit("@my_channel", "99", "korrigiert")])

    assert sent == [2]
    assert api.calls == [("@my_channel", "99", "korrigiert")]


def test_telegram_send_edit_preserves_text_mode():
    class API:
        def __init__(self) -> None:
            self.calls = []

        def edit_message_text(self, chat_id, message_id, text, **kwargs):
            self.calls.append((chat_id, message_id, text, kwargs))
            return 2

    api = API()

    sent = send_telegram_actions(api, [SendEdit("@my_channel", "99", "<b>neu</b>", text_mode="html")])

    assert sent == [2]
    assert api.calls == [("@my_channel", "99", "<b>neu</b>", {"text_mode": "html"})]


def test_telegram_send_edit_does_not_swallow_real_type_error():
    class API:
        def edit_message_text(self, chat_id, message_id, text, **kwargs):
            raise TypeError("text_mode must be html")

    try:
        send_telegram_actions(API(), [SendEdit("@my_channel", "99", "<b>neu</b>", text_mode="html")])
    except TypeError as exc:
        assert str(exc) == "text_mode must be html"
    else:
        raise AssertionError("real edit TypeError was swallowed")


def test_telegram_send_edit_keeps_old_signature_usable():
    class API:
        def edit_message_text(self, chat_id, message_id, text):
            return 2

    sent = send_telegram_actions(API(), [SendEdit("@my_channel", "99", "neu", text_mode="html")])

    assert sent == [2]


def test_telegram_send_poll_uses_optional_send_poll():
    class API:
        def __init__(self) -> None:
            self.calls = []

        def send_poll(self, chat_id, question, answers, **kwargs):
            self.calls.append((chat_id, question, answers, kwargs))
            return 3

    api = API()

    sent = send_telegram_actions(api, [SendPoll("@my_channel", "Tee?", ("Ja", "Nein"), allow_multiple_selections=True)])

    assert sent == [3]
    assert api.calls == [
        ("@my_channel", "Tee?", ["Ja", "Nein"], {"allows_multiple_answers": True}),
    ]


def test_telegram_export_file_uses_optional_send_document():
    class API:
        def __init__(self) -> None:
            self.calls = []

        def send_document(self, chat_id, data, filename, content_type, **kwargs):
            self.calls.append((chat_id, data, filename, content_type, kwargs))
            return 4

    api = API()

    sent = send_telegram_actions(
        api,
        [ExportFile("@my_channel", "report.pdf", "application/pdf", b"%PDF", caption="Export")],
    )

    assert sent == [4]
    assert api.calls == [("@my_channel", b"%PDF", "report.pdf", "application/pdf", {"caption": "Export"})]


def test_telegram_attachment_and_export_preserve_reply_parameters():
    class API:
        def __init__(self) -> None:
            self.calls = []

        def send_document(self, chat_id, data, filename, content_type, **kwargs):
            self.calls.append((chat_id, data, filename, content_type, kwargs))
            return len(self.calls)

    api = API()

    sent = send_telegram_actions(
        api,
        [
            SendAttachment("@my_channel", b"data", "note.txt", reply_to_ref="99"),
            ExportFile("@my_channel", "report.pdf", "application/pdf", b"%PDF", reply_to_ref="99"),
        ],
    )

    assert sent == [1, 2]
    assert [call[-1]["reply_parameters"] for call in api.calls] == ['{"message_id":99}', '{"message_id":99}']


def test_telegram_audio_attachment_preserves_caption_and_text_mode():
    class API:
        def __init__(self) -> None:
            self.calls = []

        def send_voice(self, chat_id, data, filename, content_type, **kwargs):
            self.calls.append((chat_id, data, filename, content_type, kwargs))
            return 3

    api = API()

    sent = send_telegram_actions(
        api,
        [
            SendAttachment(
                "@my_channel",
                b"audio",
                "voice.ogg",
                "audio/ogg",
                caption="Hinweis",
                text_mode="html",
                reply_to_ref="99",
            )
        ],
    )

    assert sent == [3]
    assert api.calls == [
        (
            "@my_channel",
            b"audio",
            "voice.ogg",
            "audio/ogg",
            {"caption": "Hinweis", "text_mode": "html", "reply_parameters": '{"message_id":99}'},
        )
    ]


def test_telegram_media_attachment_keeps_legacy_adapter_compatibility():
    class API:
        def __init__(self) -> None:
            self.calls = []

        def send_voice(self, chat_id, data, filename, content_type):
            self.calls.append(("voice", chat_id, data, filename, content_type))
            return 1

        def send_document(self, chat_id, data, filename, content_type):
            self.calls.append(("document", chat_id, data, filename, content_type))
            return 2

    api = API()

    sent = send_telegram_actions(
        api,
        [
            SendAttachment(
                "@my_channel",
                b"audio",
                "voice.ogg",
                "audio/ogg",
                caption="Hinweis",
                text_mode="html",
                reply_to_ref="99",
            ),
            SendAttachment(
                "@my_channel",
                b"document",
                "note.txt",
                "text/plain",
                caption="Hinweis",
                text_mode="html",
                reply_to_ref="99",
            ),
        ],
    )

    assert sent == [1, 2]
    assert api.calls == [
        ("voice", "@my_channel", b"audio", "voice.ogg", "audio/ogg"),
        ("document", "@my_channel", b"document", "note.txt", "text/plain"),
    ]


def test_telegram_media_adapter_does_not_swallow_real_type_error():
    class API:
        def send_voice(self, chat_id, data, filename, content_type, **kwargs):
            raise TypeError("caption must be a string")

    try:
        send_telegram_actions(
            API(),
            [SendAttachment("@my_channel", b"audio", "voice.ogg", "audio/ogg", caption="Hinweis")],
        )
    except TypeError as exc:
        assert str(exc) == "caption must be a string"
    else:
        raise AssertionError("real media TypeError was swallowed")


def test_telegram_export_file_falls_back_to_message_without_document_api():
    class API:
        def __init__(self) -> None:
            self.calls = []

        def send_message(self, chat_id, text):
            self.calls.append((chat_id, text))
            return 5

    api = API()

    sent = send_telegram_actions(
        api,
        [ExportFile("@my_channel", "report.pdf", "application/pdf", b"%PDF", reply_to_ref="99")],
    )

    assert sent == [5]
    assert api.calls == [("@my_channel", "Export erzeugt: report.pdf")]


def test_telegram_ignores_matrix_state_action():
    class API:
        pass

    sent = send_telegram_actions(API(), [SetMatrixState("@my_channel", "m.room.topic", {"topic": "Tee"})])

    assert sent == [None]


def test_telegram_ignores_signal_update_actions():
    class API:
        pass

    sent = send_telegram_actions(
        API(),
        [UpdateSignalContact("@my_channel", name="Ada"), UpdateSignalGroup("@my_channel", name="Teegruppe")],
    )

    assert sent == [None, None]


def test_telegram_unknown_action_preserves_result_alignment():
    class API:
        def send_message(self, chat_id, text):
            return 5

    sent = send_telegram_actions(API(), [object(), SendText("@my_channel", "hi")])

    assert sent == [None, 5]


def test_matrix_message_maps_sender_and_room_to_event():
    class Room:
        room_id = "!room:example"
        joined_count = 2

    class Message:
        event_id = "$event"
        sender = "@alice:example"
        body = "/account"

    event = matrix_message_to_event(Room(), Message(), instance="Bot", adapter_slot=1)

    assert event is not None
    assert event.channel == "matrix"
    assert event.identity_key == "matrix:user:@alice:example"
    assert event.chat_id == "!room:example"
    assert event.chat_type == "private"
    assert event.text == "/account"


def test_matrix_message_without_sender_is_rejected():
    class Room:
        room_id = "!room:example"
        joined_count = 2

    class Message:
        event_id = "$event"
        sender = ""
        body = "/account"

    assert matrix_message_to_event(Room(), Message(), instance="Bot", adapter_slot=1) is None


def test_matrix_message_uses_source_sender_fallback():
    class Room:
        room_id = "!room:example"
        joined_count = 2

    class Message:
        event_id = "$event"
        body = "/account"
        source = {"sender": "@alice:example", "content": {"body": "/account"}}

    event = matrix_message_to_event(Room(), Message(), instance="Bot", adapter_slot=1)

    assert event is not None
    assert event.identity_key == "matrix:user:@alice:example"
    assert event.sender_id == "@alice:example"
    assert event.sender_name == "@alice:example"


def test_matrix_message_uses_display_name_identity_fallback_without_sender():
    class Room:
        room_id = "!room:example"
        joined_count = 2

    class Message:
        event_id = "$event"
        body = "/account"
        source = {"unsigned": {"sender_display_name": "Alice Example"}, "content": {"body": "/account"}}

    event = matrix_message_to_event(Room(), Message(), instance="Bot", adapter_slot=1)

    assert event is not None
    assert event.identity_key.startswith("matrix:display:")
    assert event.sender_id == ""
    assert event.sender_name == "Alice Example"


def test_matrix_message_without_room_id_is_rejected():
    class Room:
        room_id = ""
        joined_count = 2

    class Message:
        event_id = "$event"
        sender = "@alice:example"
        body = "/account"

    assert matrix_message_to_event(Room(), Message(), instance="Bot", adapter_slot=1) is None


def test_matrix_notice_message_maps_to_text_event():
    class Room:
        room_id = "!room:example"
        joined_count = 2

    class Message:
        event_id = "$notice"
        sender = "@alice:example"
        body = "Statushinweis"
        source = {"content": {"msgtype": "m.notice", "body": "Statushinweis"}}

    event = matrix_message_to_event(Room(), Message(), instance="Bot", adapter_slot=1)

    assert event is not None
    assert event.text == "Statushinweis"
    assert event.message_ref == "$notice"
    assert event.attachments == ()


def test_matrix_message_maps_teebotus_link_preview_metadata():
    class Room:
        room_id = "!room:example"
        joined_count = 2

    class Message:
        event_id = "$link"
        sender = "@alice:example"
        body = "Link"
        source = {
            "content": {
                "msgtype": "m.text",
                "body": "Link",
                "com.teebotus.link_previews": [
                    {
                        "title": "TeeBotus",
                        "url": "https://example.test/tee",
                        "description": "Botlink",
                        "base64_thumbnail": "aW1hZ2U=",
                        "id": "preview-thumb",
                    }
                ],
            }
        }

    event = matrix_message_to_event(Room(), Message(), instance="Bot", adapter_slot=1)

    assert event is not None
    assert len(event.link_previews) == 1
    assert event.link_previews[0].title == "TeeBotus"
    assert event.link_previews[0].url == "https://example.test/tee"
    assert event.link_previews[0].description == "Botlink"
    assert event.link_previews[0].base64_thumbnail == "aW1hZ2U="
    assert event.link_previews[0].id == "preview-thumb"


def test_matrix_emote_message_maps_to_text_event():
    class Room:
        room_id = "!room:example"
        joined_count = 2

    class Message:
        event_id = "$emote"
        sender = "@alice:example"
        body = "winkt"
        source = {"content": {"msgtype": "m.emote", "body": "winkt"}}

    event = matrix_message_to_event(Room(), Message(), instance="Bot", adapter_slot=1)

    assert event is not None
    assert event.text == "winkt"
    assert event.message_ref == "$emote"
    assert event.attachments == ()


def test_matrix_unknown_message_type_maps_readable_body_to_text_event():
    class Room:
        room_id = "!room:example"
        joined_count = 2

    class Message:
        event_id = "$unknown"
        sender = "@alice:example"
        source = {"content": {"msgtype": "com.example.custom", "body": "Custom body"}}

    event = matrix_message_to_event(Room(), Message(), instance="Bot", adapter_slot=1)

    assert event is not None
    assert event.text == "Custom body"
    assert event.message_ref == "$unknown"
    assert event.attachments == ()


def test_matrix_media_message_maps_attachment_metadata():
    class Room:
        room_id = "!room:example"
        joined_count = 2

    class Message:
        event_id = "$event"
        sender = "@alice:example"
        body = "photo.jpg"
        url = "mxc://example/photo"
        source = {"content": {"msgtype": "m.image", "url": "mxc://example/photo", "info": {"mimetype": "image/jpeg"}}}

    event = matrix_message_to_event(Room(), Message(), instance="Bot", adapter_slot=1)

    assert event is not None
    assert len(event.attachments) == 1
    assert event.attachments[0].filename == "photo.jpg"
    assert event.attachments[0].content_type == "image/jpeg"
    assert event.attachments[0].data == b""
    assert event.attachments[0].base64_data == "mxc://example/photo"


def test_matrix_encrypted_media_message_maps_attachment_metadata():
    class Room:
        room_id = "!room:example"
        joined_count = 2

    class Message:
        event_id = "$event"
        sender = "@alice:example"
        body = "encrypted.jpg"
        source = {
            "content": {
                "msgtype": "m.image",
                "body": "encrypted.jpg",
                "file": {"url": "mxc://example/encrypted"},
                "info": {"mimetype": "image/jpeg"},
            }
        }

    event = matrix_message_to_event(Room(), Message(), instance="Bot", adapter_slot=1)

    assert event is not None
    assert event.text == "encrypted.jpg"
    assert len(event.attachments) == 1
    assert event.attachments[0].filename == "encrypted.jpg"
    assert event.attachments[0].content_type == "image/jpeg"
    assert event.attachments[0].data == b""
    assert event.attachments[0].base64_data == "mxc://example/encrypted"


def test_matrix_rich_reply_fallback_is_split_from_message_text():
    class Room:
        room_id = "!room:example"
        joined_count = 2

    class Message:
        event_id = "$event"
        sender = "@alice:example"
        body = "> <@bob:example> quoted line\n> second line\n\nactual reply"
        source = {"content": {"msgtype": "m.text", "body": body, "m.relates_to": {"m.in_reply_to": {"event_id": "$old"}}}}

    event = matrix_message_to_event(Room(), Message(), instance="Bot", adapter_slot=1)

    assert event is not None
    assert event.text == "actual reply"
    assert event.reply_to_text == "<@bob:example> quoted line\nsecond line"


def test_matrix_edit_message_uses_new_content_and_original_event_ref():
    class Room:
        room_id = "!room:example"
        joined_count = 2

    class Message:
        event_id = "$edit"
        sender = "@alice:example"
        body = "* Bearbeitet"
        source = {
            "content": {
                "msgtype": "m.text",
                "body": "* Bearbeitet",
                "m.new_content": {"msgtype": "m.text", "body": "Bearbeitet"},
                "m.relates_to": {"rel_type": "m.replace", "event_id": "$original"},
            }
        }

    event = matrix_message_to_event(Room(), Message(), instance="Bot", adapter_slot=1)

    assert event is not None
    assert event.event_id == "matrix:$edit"
    assert event.message_ref == "$original"
    assert event.text == "Bearbeitet"
    assert event.reply_to_text is None


def test_matrix_file_message_prefers_filename_from_content():
    class Room:
        room_id = "!room:example"
        joined_count = 2

    class Message:
        event_id = "$event"
        sender = "@alice:example"
        body = "fallback.bin"
        url = "mxc://example/file"
        source = {"content": {"msgtype": "m.file", "filename": "report.pdf", "url": "mxc://example/file"}}

    event = matrix_message_to_event(Room(), Message(), instance="Bot", adapter_slot=1)

    assert event is not None
    assert event.attachments[0].filename == "report.pdf"
    assert event.attachments[0].content_type == "application/octet-stream"


def test_matrix_file_message_uses_content_body_as_filename_fallback():
    class Room:
        room_id = "!room:example"
        joined_count = 2

    class Message:
        event_id = "$event"
        sender = "@alice:example"
        url = "mxc://example/file"
        source = {"content": {"msgtype": "m.file", "body": "report.pdf", "url": "mxc://example/file"}}

    event = matrix_message_to_event(Room(), Message(), instance="Bot", adapter_slot=1)

    assert event is not None
    assert event.attachments[0].filename == "report.pdf"
    assert event.text == "report.pdf"


def test_matrix_room_without_member_state_is_not_private():
    class Room:
        room_id = "!room:example"
        joined_count = 0

    class Message:
        event_id = "$event"
        sender = "@alice:example"
        body = "/account"

    event = matrix_message_to_event(Room(), Message(), instance="Bot", adapter_slot=1)

    assert event is not None
    assert event.chat_type == "group"


def test_matrix_empty_message_is_ignored():
    class Room:
        room_id = "!room:example"
        joined_count = 2

    class Message:
        event_id = "$event"
        sender = "@alice:example"
        body = ""
        source = {"content": {"msgtype": "m.text", "body": ""}}

    assert matrix_message_to_event(Room(), Message(), instance="Bot", adapter_slot=1) is None


def test_matrix_room_with_only_one_known_member_is_not_private():
    class Room:
        room_id = "!room:example"
        joined_count = 1

    class Message:
        event_id = "$event"
        sender = "@alice:example"
        body = "/account"

    event = matrix_message_to_event(Room(), Message(), instance="Bot", adapter_slot=1)

    assert event is not None
    assert event.chat_type == "group"


def test_matrix_send_text_uses_room_send():
    class Response:
        event_id = "$sent"

    class Client:
        def __init__(self) -> None:
            self.calls = []

        async def room_send(self, **kwargs):
            self.calls.append(kwargs)
            return Response()

    client = Client()

    sent = asyncio.run(send_matrix_actions(client, [SendText("!room:example", "hi")]))

    assert sent == ["$sent"]
    assert client.calls == [
        {
            "room_id": "!room:example",
            "message_type": "m.room.message",
            "content": {"msgtype": "m.text", "body": "hi"},
        }
    ]


def test_matrix_send_delay_preserves_result_alignment(monkeypatch):
    class Response:
        def __init__(self, event_id: str) -> None:
            self.event_id = event_id

    class Client:
        def __init__(self) -> None:
            self.calls = []

        async def room_send(self, **kwargs):
            self.calls.append(kwargs["content"]["body"])
            return Response(f"$sent-{len(self.calls)}")

    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("TeeBotus.adapters.matrix.asyncio.sleep", fake_sleep)

    client = Client()

    sent = asyncio.run(send_matrix_actions(client, [SendText("!room:example", "vorher"), DelaySeconds(1.0), SendText("!room:example", "danach")]))

    assert sent == ["$sent-1", None, "$sent-2"]
    assert sleeps == [1.0]
    assert client.calls == ["vorher", "danach"]


def test_matrix_send_reports_completed_action_before_later_failure():
    class Response:
        def __init__(self, event_id: str) -> None:
            self.event_id = event_id

    class Client:
        def __init__(self) -> None:
            self.calls = []

        async def room_send(self, **kwargs):
            text = kwargs["content"]["body"]
            self.calls.append(text)
            if text == "danach":
                raise RuntimeError("temporary failure")
            return Response("$before")

    completed: list[str] = []

    try:
        asyncio.run(
            send_matrix_actions(
                Client(),
                [SendText("!room:example", "vorher"), SendText("!room:example", "danach")],
                on_action_sent=lambda action, _ref: completed.append(action.text),
            )
        )
    except RuntimeError as exc:
        assert str(exc) == "temporary failure"
    else:
        raise AssertionError("later Matrix action should fail")

    assert completed == ["vorher"]


def test_matrix_send_text_rejects_response_without_event_id():
    class Response:
        pass

    class Client:
        async def room_send(self, **_kwargs):
            return Response()

    try:
        asyncio.run(send_matrix_actions(Client(), [SendText("!room:example", "hi")]))
    except RuntimeError as exc:
        assert "Matrix text send returned no event_id" in str(exc)
    else:
        raise AssertionError("RuntimeError was not raised")


def test_matrix_send_text_prefers_niobot_send_message():
    class Response:
        event_id = "$sent"

    class Client:
        def __init__(self) -> None:
            self.calls = []

        async def send_message(self, room_id, text, **kwargs):
            self.calls.append((room_id, text, kwargs))
            return Response()

    client = Client()

    sent = asyncio.run(send_matrix_actions(client, [SendText("!room:example", "hi")]))

    assert sent == ["$sent"]
    assert client.calls == [("!room:example", "hi", {"message_type": "m.text", "clean_mentions": True})]


def test_matrix_send_text_appends_button_fallback():
    class Response:
        event_id = "$sent"

    class Client:
        def __init__(self) -> None:
            self.calls = []

        async def send_message(self, room_id, text, **kwargs):
            self.calls.append((room_id, text, kwargs))
            return Response()

    client = Client()

    sent = asyncio.run(send_matrix_actions(client, [SendText("!room:example", "Frage?", buttons=(MessageButton("Ja", "ja"),))]))

    assert sent == ["$sent"]
    assert client.calls == [("!room:example", "Frage?\n\nOptionen:\n- Ja: ja", {"message_type": "m.text", "clean_mentions": True})]


def test_matrix_send_text_can_reply_with_niobot_send_message():
    class Response:
        event_id = "$sent"

    class Client:
        def __init__(self) -> None:
            self.calls = []

        async def send_message(self, room_id, text, **kwargs):
            self.calls.append((room_id, text, kwargs))
            return Response()

    client = Client()

    sent = asyncio.run(send_matrix_actions(client, [SendText("!room:example", "hi", reply_to_ref="$old")]))

    assert sent == ["$sent"]
    assert client.calls == [("!room:example", "hi", {"message_type": "m.text", "clean_mentions": True, "reply_to": "$old"})]


def test_matrix_send_text_fallback_can_reply_with_relates_to():
    class Response:
        event_id = "$sent"

    class Client:
        def __init__(self) -> None:
            self.calls = []

        async def room_send(self, **kwargs):
            self.calls.append(kwargs)
            return Response()

    client = Client()

    sent = asyncio.run(send_matrix_actions(client, [SendText("!room:example", "hi", reply_to_ref="$old")]))

    assert sent == ["$sent"]
    assert client.calls[0]["content"] == {
        "msgtype": "m.text",
        "body": "hi",
        "m.relates_to": {"m.in_reply_to": {"event_id": "$old"}},
    }


def test_matrix_send_text_html_uses_formatted_room_send_content():
    class Response:
        event_id = "$sent"

    class Client:
        def __init__(self) -> None:
            self.calls = []

        async def send_message(self, *_args, **_kwargs):
            raise AssertionError("send_message should not be used for Matrix HTML content")

        async def room_send(self, **kwargs):
            self.calls.append(kwargs)
            return Response()

    client = Client()

    sent = asyncio.run(
        send_matrix_actions(
            client,
            [SendText("!room:example", "<strong>Hallo</strong><br>Matrix", text_mode="html")],
        )
    )

    assert sent == ["$sent"]
    assert client.calls == [
        {
            "room_id": "!room:example",
            "message_type": "m.room.message",
            "content": {
                "msgtype": "m.text",
                "body": "Hallo\nMatrix",
                "format": "org.matrix.custom.html",
                "formatted_body": "<strong>Hallo</strong><br>Matrix",
            },
        }
    ]


def test_matrix_send_text_with_mentions_uses_room_send_mentions_content():
    class Response:
        event_id = "$sent"

    class Client:
        def __init__(self) -> None:
            self.calls = []

        async def send_message(self, *_args, **_kwargs):
            raise AssertionError("send_message should not be used when m.mentions are needed")

        async def room_send(self, **kwargs):
            self.calls.append(kwargs)
            return Response()

    client = Client()

    sent = asyncio.run(
        send_matrix_actions(
            client,
            [
                SendText(
                    "!room:example",
                    "hi @alice",
                    mentions=({"user_id": "@alice:example"}, {"author": "not-a-matrix-id"}),
                )
            ],
        )
    )

    assert sent == ["$sent"]
    assert client.calls == [
        {
            "room_id": "!room:example",
            "message_type": "m.room.message",
            "content": {
                "msgtype": "m.text",
                "body": "hi @alice",
                "m.mentions": {"user_ids": ["@alice:example"]},
            },
        }
    ]


def test_matrix_send_text_preserves_link_preview_metadata():
    class Response:
        event_id = "$sent"

    class Client:
        def __init__(self) -> None:
            self.calls = []

        async def send_message(self, *_args, **_kwargs):
            raise AssertionError("send_message should not be used when link preview metadata is needed")

        async def room_send(self, **kwargs):
            self.calls.append(kwargs)
            return Response()

    client = Client()

    sent = asyncio.run(
        send_matrix_actions(
            client,
            [
                SendText(
                    "!room:example",
                    "Link",
                    link_preview={
                        "title": "TeeBotus",
                        "url": "https://example.test/tee",
                        "description": "Bot",
                        "base64_thumbnail": "aW1hZ2U=",
                        "id": "preview-thumb",
                    },
                )
            ],
        )
    )

    assert sent == ["$sent"]
    assert client.calls[0]["content"] == {
        "msgtype": "m.text",
        "body": "Link",
        "com.teebotus.link_previews": [
            {
                "title": "TeeBotus",
                "url": "https://example.test/tee",
                "description": "Bot",
                "base64_thumbnail": "aW1hZ2U=",
                "id": "preview-thumb",
            }
        ],
    }


def test_matrix_view_once_text_sends_notice_without_original_content():
    class Response:
        event_id = "$notice"

    class Client:
        def __init__(self) -> None:
            self.calls = []

        async def send_message(self, room_id, text, **kwargs):
            self.calls.append((room_id, text, kwargs))
            return Response()

    client = Client()

    sent = asyncio.run(send_matrix_actions(client, [SendText("!room:example", "geheim", view_once=True)]))

    assert sent == ["$notice"]
    assert client.calls == [
        (
            "!room:example",
            "Nachricht konnte nicht gesendet werden: Matrix view_once text is not supported",
            {"message_type": "m.notice", "clean_mentions": True},
        )
    ]


def test_matrix_send_typing_uses_room_typing():
    class Client:
        def __init__(self) -> None:
            self.calls = []

        async def room_typing(self, room_id, typing_state, timeout=0):
            self.calls.append((room_id, typing_state, timeout))

    client = Client()

    sent = asyncio.run(send_matrix_actions(client, [SendTyping("!room:example")]))

    assert sent == [None]
    assert client.calls == [("!room:example", True, 3000)]


def test_matrix_send_typing_failure_does_not_block_followup_text():
    class Response:
        event_id = "$sent"

    class Client:
        def __init__(self) -> None:
            self.sends = []

        async def room_typing(self, _room_id, _typing_state, timeout=0):
            raise OSError("typing refused")

        async def room_send(self, **kwargs):
            self.sends.append(kwargs)
            return Response()

    client = Client()

    sent = asyncio.run(send_matrix_actions(client, [SendTyping("!room:example"), SendText("!room:example", "hi")]))

    assert sent == [None, "$sent"]
    assert client.sends[0]["content"] == {"msgtype": "m.text", "body": "hi"}


def test_matrix_send_reaction_uses_annotation_event():
    class Response:
        event_id = "$reaction"

    class Client:
        def __init__(self) -> None:
            self.calls = []

        async def room_send(self, **kwargs):
            self.calls.append(kwargs)
            return Response()

    client = Client()

    sent = asyncio.run(send_matrix_actions(client, [SendReaction("!room:example", "$old", "\U0001f44d")]))

    assert sent == ["$reaction"]
    assert client.calls == [
        {
            "room_id": "!room:example",
            "message_type": "m.reaction",
            "content": {
                "m.relates_to": {
                    "rel_type": "m.annotation",
                    "event_id": "$old",
                    "key": "\U0001f44d",
                }
            },
        }
    ]


def test_matrix_send_reaction_prefers_niobot_add_reaction():
    class Response:
        event_id = "$reaction"

    class Client:
        def __init__(self) -> None:
            self.calls = []

        async def add_reaction(self, room_id, event_id, emoji):
            self.calls.append((room_id, event_id, emoji))
            return Response()

        async def room_send(self, **_kwargs):
            raise AssertionError("room_send should not be used when add_reaction is available")

    client = Client()

    sent = asyncio.run(send_matrix_actions(client, [SendReaction("!room:example", "$old", "\U0001f44d")]))

    assert sent == ["$reaction"]
    assert client.calls == [("!room:example", "$old", "\U0001f44d")]


def test_matrix_send_receipt_uses_update_receipt_marker():
    class Response:
        pass

    class Client:
        def __init__(self) -> None:
            self.receipts = []

        async def update_receipt_marker(self, room_id, event_id, receipt_type=None):
            self.receipts.append((room_id, event_id, receipt_type))
            return Response()

    client = Client()

    sent = asyncio.run(send_matrix_actions(client, [SendReceipt("!room:example", "$old")]))

    assert sent == [None]
    assert len(client.receipts) == 1
    assert client.receipts[0][0:2] == ("!room:example", "$old")


def test_matrix_send_receipt_rejects_dict_error_response():
    class Client:
        async def update_receipt_marker(self, _room_id, _event_id, receipt_type=None):
            return {"errcode": "M_FORBIDDEN", "error": "receipt refused"}

    try:
        asyncio.run(send_matrix_actions(Client(), [SendReceipt("!room:example", "$old")]))
    except RuntimeError as exc:
        assert str(exc) == "M_FORBIDDEN: receipt refused"
    else:
        raise AssertionError("RuntimeError was not raised")


def test_matrix_send_receipt_fallback_uses_private_read_event_for_viewed():
    class Response:
        pass

    class Client:
        def __init__(self) -> None:
            self.receipts = []

        async def room_read_markers(self, room_id, fully_read_event, read_event=None, private_read_event=None):
            self.receipts.append((room_id, fully_read_event, read_event, private_read_event))
            return Response()

    client = Client()

    sent = asyncio.run(send_matrix_actions(client, [SendReceipt("!room:example", "$old", "viewed")]))

    assert sent == [None]
    assert client.receipts == [("!room:example", "$old", None, "$old")]


def test_matrix_send_receipt_requires_supported_api():
    class Client:
        pass

    try:
        asyncio.run(send_matrix_actions(Client(), [SendReceipt("!room:example", "$old")]))
    except RuntimeError as exc:
        assert "Matrix receipt API is required" in str(exc)
    else:
        raise AssertionError("RuntimeError was not raised")


def test_matrix_send_edit_uses_replacement_event():
    class Response:
        event_id = "$edit"

    class Client:
        def __init__(self) -> None:
            self.calls = []

        async def room_send(self, **kwargs):
            self.calls.append(kwargs)
            return Response()

    client = Client()

    sent = asyncio.run(send_matrix_actions(client, [SendEdit("!room:example", "$old", "korrigiert")]))

    assert sent == ["$edit"]
    assert client.calls == [
        {
            "room_id": "!room:example",
            "message_type": "m.room.message",
            "content": {
                "msgtype": "m.text",
                "body": "* korrigiert",
                "m.new_content": {"msgtype": "m.text", "body": "korrigiert"},
                "m.relates_to": {"rel_type": "m.replace", "event_id": "$old"},
            },
        }
    ]


def test_matrix_send_edit_prefers_niobot_edit_message_without_mentions():
    class Response:
        event_id = "$edit"

    class Room:
        room_id = "!room:example"

    class Client:
        def __init__(self) -> None:
            self.calls = []
            self.rooms = {"!room:example": Room()}

        async def edit_message(self, room, event_id, content, **kwargs):
            self.calls.append((room, event_id, content, kwargs))
            return Response()

        async def room_send(self, **_kwargs):
            raise AssertionError("room_send should not be used when edit_message is available")

    client = Client()

    sent = asyncio.run(send_matrix_actions(client, [SendEdit("!room:example", "$old", "korrigiert")]))

    assert sent == ["$edit"]
    assert client.calls == [(client.rooms["!room:example"], "$old", "korrigiert", {"message_type": "m.text", "clean_mentions": True})]


def test_matrix_send_edit_uses_niobot_edit_message_with_room_id_when_room_is_unknown():
    class Response:
        event_id = "$edit"

    class Client:
        def __init__(self) -> None:
            self.calls = []

        async def edit_message(self, room, event_id, content, **kwargs):
            self.calls.append((room, event_id, content, kwargs))
            return Response()

        async def room_send(self, **kwargs):
            raise AssertionError("room_send should not be used when edit_message accepts a room_id")

    client = Client()

    sent = asyncio.run(send_matrix_actions(client, [SendEdit("!room:example", "$old", "korrigiert")]))

    assert sent == ["$edit"]
    assert client.calls == [("!room:example", "$old", "korrigiert", {"message_type": "m.text", "clean_mentions": True})]


def test_matrix_send_edit_preserves_mentions_in_replacement_content():
    class Response:
        event_id = "$edit"

    class Client:
        def __init__(self) -> None:
            self.calls = []

        async def room_send(self, **kwargs):
            self.calls.append(kwargs)
            return Response()

    client = Client()

    sent = asyncio.run(
        send_matrix_actions(
            client,
            [
                SendEdit(
                    "!room:example",
                    "$old",
                    "hi @alice",
                    mentions=({"user_id": "@alice:example"}, {"author": "signal-user"}),
                )
            ],
        )
    )

    assert sent == ["$edit"]
    content = client.calls[0]["content"]
    assert content["m.mentions"] == {"user_ids": ["@alice:example"]}
    assert content["m.new_content"]["m.mentions"] == {"user_ids": ["@alice:example"]}


def test_matrix_send_edit_html_uses_formatted_replacement_content():
    class Response:
        event_id = "$edit"

    class Client:
        def __init__(self) -> None:
            self.calls = []

        async def edit_message(self, *_args, **_kwargs):
            raise AssertionError("edit_message should not be used for Matrix HTML content")

        async def room_send(self, **kwargs):
            self.calls.append(kwargs)
            return Response()

    client = Client()

    sent = asyncio.run(send_matrix_actions(client, [SendEdit("!room:example", "$old", "<em>neu</em>", text_mode="html")]))

    assert sent == ["$edit"]
    content = client.calls[0]["content"]
    assert content == {
        "msgtype": "m.text",
        "body": "* neu",
        "m.new_content": {
            "msgtype": "m.text",
            "body": "neu",
            "format": "org.matrix.custom.html",
            "formatted_body": "<em>neu</em>",
        },
        "m.relates_to": {"rel_type": "m.replace", "event_id": "$old"},
        "format": "org.matrix.custom.html",
        "formatted_body": "* <em>neu</em>",
    }


def test_matrix_view_once_edit_sends_notice_without_original_content():
    class Response:
        event_id = "$notice"

    class Client:
        def __init__(self) -> None:
            self.calls = []

        async def edit_message(self, *_args, **_kwargs):
            raise AssertionError("edit_message must not receive view_once Matrix content")

        async def send_message(self, room_id, text, **kwargs):
            self.calls.append((room_id, text, kwargs))
            return Response()

    client = Client()

    sent = asyncio.run(send_matrix_actions(client, [SendEdit("!room:example", "$old", "geheim", view_once=True)]))

    assert sent == ["$notice"]
    assert client.calls == [
        (
            "!room:example",
            "Nachricht konnte nicht bearbeitet werden: Matrix view_once edits are not supported",
            {"message_type": "m.notice", "clean_mentions": True},
        )
    ]


def test_matrix_send_poll_uses_poll_start_event():
    class Response:
        event_id = "$poll"

    class Client:
        def __init__(self) -> None:
            self.calls = []

        async def room_send(self, **kwargs):
            self.calls.append(kwargs)
            return Response()

    client = Client()

    sent = asyncio.run(send_matrix_actions(client, [SendPoll("!room:example", "Tee?", ("Ja", "Nein"), True)]))

    assert sent == ["$poll"]
    content = client.calls[0]["content"]
    assert client.calls[0]["room_id"] == "!room:example"
    assert client.calls[0]["message_type"] == "m.room.message"
    assert content["msgtype"] == "org.matrix.msc3381.poll.start"
    assert content["org.matrix.msc3381.poll.start"] == {
        "max_selections": 2,
        "question": {"org.matrix.msc1767.text": "Tee?"},
        "answers": [
            {"id": "1", "org.matrix.msc1767.text": "Ja"},
            {"id": "2", "org.matrix.msc1767.text": "Nein"},
        ],
    }
    assert content["body"] == "Tee?\n(Mehrfachauswahl)\n1. Ja\n2. Nein"


def test_matrix_set_state_uses_room_put_state():
    class Response:
        pass

    class Client:
        def __init__(self) -> None:
            self.calls = []

        async def room_put_state(self, **kwargs):
            self.calls.append(kwargs)
            return Response()

    client = Client()

    sent = asyncio.run(
        send_matrix_actions(
            client,
            [SetMatrixState("!room:example", "m.room.topic", {"topic": "Tee"}, state_key="")],
        )
    )

    assert sent == [None]
    assert client.calls == [
        {
            "room_id": "!room:example",
            "event_type": "m.room.topic",
            "content": {"topic": "Tee"},
            "state_key": "",
        }
    ]


def test_matrix_set_state_rejects_dict_error_response():
    class Client:
        async def room_put_state(self, **_kwargs):
            return {"errcode": "M_FORBIDDEN", "error": "state refused"}

    try:
        asyncio.run(
            send_matrix_actions(
                Client(),
                [SetMatrixState("!room:example", "m.room.topic", {"topic": "Tee"}, state_key="")],
            )
        )
    except RuntimeError as exc:
        assert str(exc) == "M_FORBIDDEN: state refused"
    else:
        raise AssertionError("RuntimeError was not raised")


def test_matrix_set_topic_prefers_niobot_update_room_topic():
    class Response:
        pass

    class Client:
        def __init__(self) -> None:
            self.calls = []

        async def update_room_topic(self, room_id, topic):
            self.calls.append(("update_room_topic", room_id, topic))
            return Response()

        async def room_put_state(self, **_kwargs):
            raise AssertionError("room_put_state should not be used when update_room_topic is available")

    client = Client()

    sent = asyncio.run(
        send_matrix_actions(
            client,
            [SetMatrixState("!room:example", "m.room.topic", {"topic": "Tee"}, state_key="")],
        )
    )

    assert sent == [None]
    assert client.calls == [("update_room_topic", "!room:example", "Tee")]


def test_matrix_set_topic_with_state_key_uses_room_put_state():
    class Response:
        pass

    class Client:
        def __init__(self) -> None:
            self.calls = []

        async def update_room_topic(self, _room_id, _topic):
            raise AssertionError("update_room_topic cannot set non-empty state_key")

        async def room_put_state(self, **kwargs):
            self.calls.append(kwargs)
            return Response()

    client = Client()

    sent = asyncio.run(
        send_matrix_actions(
            client,
            [SetMatrixState("!room:example", "m.room.topic", {"topic": "Tee"}, state_key="@ada:example")],
        )
    )

    assert sent == [None]
    assert client.calls == [
        {
            "room_id": "!room:example",
            "event_type": "m.room.topic",
            "content": {"topic": "Tee"},
            "state_key": "@ada:example",
        }
    ]


def test_matrix_ignores_signal_update_actions():
    class Client:
        pass

    sent = asyncio.run(
        send_matrix_actions(
            Client(),
            [
                UpdateSignalContact("!room:example", name="Ada"),
                UpdateSignalGroup("!room:example", name="Teegruppe"),
            ],
        )
    )

    assert sent == [None, None]


def test_matrix_unknown_action_preserves_result_alignment():
    class Response:
        event_id = "$sent"

    class Client:
        async def send_message(self, *_args, **_kwargs):
            return Response()

    sent = asyncio.run(send_matrix_actions(Client(), [object(), SendText("!room:example", "hi")]))

    assert sent == [None, "$sent"]


def test_matrix_export_file_uploads_file_before_room_send():
    class UploadResponse:
        content_uri = "mxc://example/export"

    class SendResponse:
        event_id = "$sent"

    class Client:
        def __init__(self) -> None:
            self.uploads = []
            self.sends = []

        async def upload(self, data_provider, **kwargs):
            self.uploads.append((data_provider.read(), kwargs))
            return UploadResponse(), None

        async def room_send(self, **kwargs):
            self.sends.append(kwargs)
            return SendResponse()

    client = Client()

    sent = asyncio.run(
        send_matrix_actions(
            client,
            [ExportFile("!room:example", "report.json", "application/json", b"{\"ok\": true}", caption="Export")],
        )
    )

    assert sent == ["$sent"]
    assert client.uploads == [
        (
            b"{\"ok\": true}",
            {
                "content_type": "application/json",
                "filename": "report.json",
                "filesize": 12,
                "encrypt": False,
            },
        )
    ]
    assert client.sends == [
        {
            "room_id": "!room:example",
            "message_type": "m.room.message",
            "content": {
                "msgtype": "m.file",
                "body": "Export",
                "filename": "report.json",
                "url": "mxc://example/export",
                "info": {"mimetype": "application/json", "size": 12},
            },
        }
    ]


def test_matrix_send_attachment_fallback_uses_media_msgtype_from_content_type():
    class UploadResponse:
        content_uri = "mxc://example/photo"

    class SendResponse:
        event_id = "$sent"

    class Client:
        def __init__(self) -> None:
            self.sends = []

        async def upload(self, _data_provider, **_kwargs):
            return UploadResponse(), None

        async def room_send(self, **kwargs):
            self.sends.append(kwargs)
            return SendResponse()

    client = Client()

    sent = asyncio.run(send_matrix_actions(client, [SendAttachment("!room:example", b"img", "photo.jpg", "image/jpeg")]))

    assert sent == ["$sent"]
    assert client.sends[0]["content"]["msgtype"] == "m.image"
    assert client.sends[0]["content"]["info"]["mimetype"] == "image/jpeg"


def test_matrix_attachment_response_without_event_id_sends_notice():
    class UploadResponse:
        content_uri = "mxc://example/photo"

    class MissingEventResponse:
        pass

    class NoticeResponse:
        event_id = "$notice"

    class Client:
        def __init__(self) -> None:
            self.sends = []

        async def upload(self, _data_provider, **_kwargs):
            return UploadResponse(), None

        async def room_send(self, **kwargs):
            self.sends.append(kwargs)
            if len(self.sends) == 1:
                return MissingEventResponse()
            return NoticeResponse()

    client = Client()

    sent = asyncio.run(send_matrix_actions(client, [SendAttachment("!room:example", b"img", "photo.jpg", "image/jpeg")]))

    assert sent == ["$notice"]
    assert client.sends[0]["content"]["body"] == "photo.jpg"
    assert client.sends[1]["content"]["msgtype"] == "m.notice"
    assert "Matrix attachment send returned no event_id" in client.sends[1]["content"]["body"]


def test_matrix_export_file_prefers_niobot_file_attachment():
    class Response:
        event_id = "$sent"

    class Client:
        def __init__(self) -> None:
            self.calls = []

        async def send_message(self, room_id, content=None, file=None, **kwargs):
            self.calls.append((room_id, content, file, kwargs))
            return Response()

    client = Client()

    sent = asyncio.run(
        send_matrix_actions(
            client,
            [ExportFile("!room:example", "report.json", "application/json", b"{\"ok\": true}", caption="Export")],
        )
    )

    assert sent == ["$sent"]
    assert len(client.calls) == 1
    room_id, content, file, kwargs = client.calls[0]
    assert room_id == "!room:example"
    assert content == "Export"
    assert kwargs == {"clean_mentions": True}
    assert file.file_name == "report.json"
    assert file.mime_type == "application/json"
    assert file.size == 12
    assert file.file.getvalue() == b"{\"ok\": true}"


def test_matrix_image_attachment_prefers_niobot_image_attachment():
    class Response:
        event_id = "$sent"

    class Client:
        def __init__(self) -> None:
            self.calls = []

        async def send_message(self, room_id, content=None, file=None, **kwargs):
            self.calls.append((room_id, content, file, kwargs))
            return Response()

    client = Client()

    sent = asyncio.run(send_matrix_actions(client, [SendAttachment("!room:example", b"img", "photo.jpg", "image/jpeg")]))

    assert sent == ["$sent"]
    room_id, content, file, kwargs = client.calls[0]
    assert room_id == "!room:example"
    assert content == "photo.jpg"
    assert kwargs == {"clean_mentions": True}
    assert file.as_body("photo.jpg")["msgtype"] == "m.image"
    assert file.mime_type == "image/jpeg"
    assert file.size == 3


def test_matrix_file_attachment_can_reply_with_niobot_send_message():
    class Response:
        event_id = "$sent"

    class Client:
        def __init__(self) -> None:
            self.calls = []

        async def send_message(self, room_id, content=None, file=None, **kwargs):
            self.calls.append((room_id, content, file, kwargs))
            return Response()

    client = Client()

    sent = asyncio.run(
        send_matrix_actions(
            client,
            [
                SendAttachment(
                    "!room:example",
                    b"hello",
                    "report.txt",
                    "text/plain",
                    caption="Bericht",
                    reply_to_ref="$old",
                )
            ],
        )
    )

    assert sent == ["$sent"]
    room_id, content, file, kwargs = client.calls[0]
    assert room_id == "!room:example"
    assert content == "Bericht"
    assert file.file_name == "report.txt"
    assert kwargs == {"clean_mentions": True, "reply_to": "$old"}


def test_matrix_attachment_with_mentions_uses_room_send_content():
    class UploadResponse:
        content_uri = "mxc://example/report"

    class SendResponse:
        event_id = "$sent"

    class Client:
        def __init__(self) -> None:
            self.uploads = []
            self.sends = []

        async def send_message(self, *_args, **_kwargs):
            raise AssertionError("send_message should not be used when m.mentions are needed")

        async def upload(self, data_provider, **kwargs):
            self.uploads.append((data_provider.read(), kwargs))
            return UploadResponse(), None

        async def room_send(self, **kwargs):
            self.sends.append(kwargs)
            return SendResponse()

    client = Client()

    sent = asyncio.run(
        send_matrix_actions(
            client,
            [
                SendAttachment(
                    "!room:example",
                    b"hello",
                    "report.txt",
                    "text/plain",
                    caption="Bericht fuer @alice",
                    mentions=({"user_id": "@alice:example"}, {"author": "signal-user"}),
                )
            ],
        )
    )

    assert sent == ["$sent"]
    assert client.uploads[0][0] == b"hello"
    assert client.uploads[0][1]["encrypt"] is False
    assert client.sends[0]["content"] == {
        "msgtype": "m.file",
        "body": "Bericht fuer @alice",
        "filename": "report.txt",
        "url": "mxc://example/report",
        "info": {"mimetype": "text/plain", "size": 5},
        "m.mentions": {"user_ids": ["@alice:example"]},
    }


def test_matrix_attachment_html_caption_uses_formatted_room_send_content():
    class UploadResponse:
        content_uri = "mxc://example/report"

    class SendResponse:
        event_id = "$sent"

    class Client:
        def __init__(self) -> None:
            self.uploads = []
            self.sends = []

        async def send_message(self, *_args, **_kwargs):
            raise AssertionError("send_message should not be used for Matrix HTML captions")

        async def upload(self, data_provider, **kwargs):
            self.uploads.append((data_provider.read(), kwargs))
            return UploadResponse(), None

        async def room_send(self, **kwargs):
            self.sends.append(kwargs)
            return SendResponse()

    client = Client()

    sent = asyncio.run(
        send_matrix_actions(
            client,
            [
                SendAttachment(
                    "!room:example",
                    b"hello",
                    "report.txt",
                    "text/plain",
                    caption="<strong>Bericht</strong>",
                    text_mode="html",
                )
            ],
        )
    )

    assert sent == ["$sent"]
    assert client.uploads[0][0] == b"hello"
    assert client.uploads[0][1]["encrypt"] is False
    assert client.sends[0]["content"] == {
        "msgtype": "m.file",
        "body": "Bericht",
        "filename": "report.txt",
        "url": "mxc://example/report",
        "info": {"mimetype": "text/plain", "size": 5},
        "format": "org.matrix.custom.html",
        "formatted_body": "<strong>Bericht</strong>",
    }


def test_matrix_attachment_in_encrypted_room_uploads_encrypted_file_metadata():
    class UploadResponse:
        content_uri = "mxc://example/secret"

    class SendResponse:
        event_id = "$sent"

    keys = {
        "v": "v2",
        "key": {"kty": "oct", "k": "secret-key"},
        "iv": "secret-iv",
        "hashes": {"sha256": "secret-hash"},
    }

    class Client:
        def __init__(self) -> None:
            self.rooms = {"!room:example": SimpleNamespace(encrypted=True)}
            self.uploads = []
            self.sends = []

        async def send_message(self, *_args, **_kwargs):
            raise AssertionError("send_message should not be used for encrypted Matrix uploads")

        async def upload(self, data_provider, **kwargs):
            self.uploads.append((data_provider.read(), kwargs))
            return UploadResponse(), keys

        async def room_send(self, **kwargs):
            self.sends.append(kwargs)
            return SendResponse()

    client = Client()

    sent = asyncio.run(send_matrix_actions(client, [SendAttachment("!room:example", b"secret", "secret.bin", "application/octet-stream")]))

    assert sent == ["$sent"]
    assert client.uploads == [
        (
            b"secret",
            {
                "content_type": "application/octet-stream",
                "filename": "secret.bin",
                "filesize": 6,
                "encrypt": True,
            },
        )
    ]
    assert client.sends[0]["content"] == {
        "msgtype": "m.file",
        "body": "secret.bin",
        "filename": "secret.bin",
        "info": {"mimetype": "application/octet-stream", "size": 6},
        "file": {
            "v": "v2",
            "key": {"kty": "oct", "k": "secret-key"},
            "iv": "secret-iv",
            "hashes": {"sha256": "secret-hash"},
            "url": "mxc://example/secret",
        },
    }


def test_matrix_view_once_attachment_sends_notice_without_uploading_file():
    class Response:
        event_id = "$notice"

    class Client:
        def __init__(self) -> None:
            self.uploads = []
            self.sends = []

        async def upload(self, data_provider, **kwargs):
            self.uploads.append((data_provider.read(), kwargs))
            raise AssertionError("view_once Matrix attachment must not be uploaded")

        async def room_send(self, **kwargs):
            self.sends.append(kwargs)
            return Response()

    client = Client()

    sent = asyncio.run(
        send_matrix_actions(
            client,
            [SendAttachment("!room:example", b"secret", "secret.bin", "application/octet-stream", view_once=True)],
        )
    )

    assert sent == ["$notice"]
    assert client.uploads == []
    assert client.sends == [
        {
            "room_id": "!room:example",
            "message_type": "m.room.message",
            "content": {
                "msgtype": "m.notice",
                "body": "Datei konnte nicht gesendet werden: secret.bin (Matrix view_once attachments are not supported)",
            },
        }
    ]


def test_matrix_niobot_file_send_error_sends_notice():
    class Response:
        event_id = "$sent"

    class SendError:
        message = "send refused"
        status_code = "M_FORBIDDEN"

    class Client:
        def __init__(self) -> None:
            self.calls = []

        async def send_message(self, room_id, content=None, file=None, **kwargs):
            self.calls.append((room_id, content, file, kwargs))
            if file is not None:
                return SendError()
            return Response()

    client = Client()

    sent = asyncio.run(
        send_matrix_actions(
            client,
            [ExportFile("!room:example", "report.json", "application/json", b"{\"ok\": true}", caption="Export")],
        )
    )

    assert sent == ["$sent"]
    assert len(client.calls) == 2
    assert client.calls[0][1] == "Export"
    assert client.calls[0][2].file_name == "report.json"
    assert client.calls[1] == (
        "!room:example",
        "Datei konnte nicht gesendet werden: report.json (M_FORBIDDEN: send refused)",
        None,
        {"message_type": "m.notice", "clean_mentions": True},
    )


def test_matrix_export_upload_failure_sends_notice_and_continues_actions():
    class Response:
        def __init__(self, event_id: str) -> None:
            self.event_id = event_id

    class Client:
        def __init__(self) -> None:
            self.sends = []

        async def upload(self, _data_provider, **_kwargs):
            raise OSError("upload refused")

        async def room_send(self, **kwargs):
            self.sends.append(kwargs)
            return Response(f"$sent-{len(self.sends)}")

    client = Client()

    sent = asyncio.run(
        send_matrix_actions(
            client,
            [
                ExportFile("!room:example", "report.json", "application/json", b"{\"ok\": true}", caption="Export"),
                SendText("!room:example", "danach"),
            ],
        )
    )

    assert sent == ["$sent-1", "$sent-2"]
    assert client.sends[0] == {
        "room_id": "!room:example",
        "message_type": "m.room.message",
        "content": {
            "msgtype": "m.notice",
            "body": "Datei konnte nicht gesendet werden: report.json (upload refused)",
        },
    }
    assert client.sends[1]["content"] == {"msgtype": "m.text", "body": "danach"}


def test_matrix_file_room_send_error_sends_notice_and_continues_actions():
    class Response:
        def __init__(self, event_id: str) -> None:
            self.event_id = event_id

    class SendError:
        message = "send refused"
        status_code = "M_FORBIDDEN"

    class UploadResponse:
        content_uri = "mxc://example/report"

    class Client:
        def __init__(self) -> None:
            self.sends = []

        async def upload(self, _data_provider, **_kwargs):
            return UploadResponse(), None

        async def room_send(self, **kwargs):
            self.sends.append(kwargs)
            if len(self.sends) == 1:
                return SendError()
            return Response(f"$sent-{len(self.sends)}")

    client = Client()

    sent = asyncio.run(
        send_matrix_actions(
            client,
            [
                ExportFile("!room:example", "report.json", "application/json", b"{\"ok\": true}", caption="Export"),
                SendText("!room:example", "danach"),
            ],
        )
    )

    assert sent == ["$sent-2", "$sent-3"]
    assert client.sends[0]["content"]["body"] == "Export"
    assert client.sends[1] == {
        "room_id": "!room:example",
        "message_type": "m.room.message",
        "content": {
            "msgtype": "m.notice",
            "body": "Datei konnte nicht gesendet werden: report.json (M_FORBIDDEN: send refused)",
        },
    }
    assert client.sends[2]["content"] == {"msgtype": "m.text", "body": "danach"}


def test_matrix_export_upload_failure_prefers_niobot_notice_message():
    class Response:
        def __init__(self, event_id: str) -> None:
            self.event_id = event_id

    class Client:
        def __init__(self) -> None:
            self.calls = []

        async def send_message(self, room_id, text, **kwargs):
            self.calls.append((room_id, text, kwargs))
            if "file" in kwargs:
                raise OSError("send refused")
            return Response(f"$sent-{len(self.calls)}")

    client = Client()

    sent = asyncio.run(
        send_matrix_actions(
            client,
            [ExportFile("!room:example", "report.json", "application/json", b"{\"ok\": true}", caption="Export")],
        )
    )

    assert sent == ["$sent-2"]
    assert client.calls[0][0] == "!room:example"
    assert client.calls[0][1] == "Export"
    assert client.calls[0][2]["file"].file_name == "report.json"
    assert client.calls[1] == (
        "!room:example",
        "Datei konnte nicht gesendet werden: report.json (send refused)",
        {"message_type": "m.notice", "clean_mentions": True},
    )
