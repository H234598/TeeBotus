from __future__ import annotations

from dataclasses import dataclass

import asyncio
import json
from signalbot.message import MessageType

from TeeBotus.adapters.matrix import matrix_message_to_event, send_matrix_actions
from TeeBotus.adapters.signal import send_signal_actions, signal_message_to_event
from TeeBotus.adapters.telegram import send_telegram_actions, telegram_message_to_event
from TeeBotus.runtime.actions import ExportFile, SendAttachment, SendEdit, SendPoll, SendReaction, SendReceipt, SendText, SendTyping


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
    assert event.attachments[0].base64_data == ""


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


def test_matrix_media_without_plain_url_does_not_create_empty_attachment():
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
    assert event.attachments == ()


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
    assert client.calls == [("!room:example", "hi", {"message_type": "m.text"})]


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
    assert client.calls == [("!room:example", "hi", {"message_type": "m.text", "reply_to": "$old"})]


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
    assert kwargs == {}
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
    assert kwargs == {}
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
    assert kwargs == {"reply_to": "$old"}


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
        {"message_type": "m.notice"},
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
        {"message_type": "m.notice"},
    )
