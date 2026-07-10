from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from TeeBotus.runtime.actions import ExportFile, SendAttachment, SendEdit, SendPoll, SendReaction, SendReceipt, SendText, SendTyping
from TeeBotus.runtime.proactive_backends import matrix_proactive_sender, signal_proactive_sender, telegram_proactive_sender


def test_telegram_proactive_sender_uses_route_adapter_slot() -> None:
    class API:
        def __init__(self, message_id: int) -> None:
            self.message_id = message_id
            self.calls = []

        def send_message(self, chat_id: str, text: str) -> int:
            self.calls.append((chat_id, text))
            return self.message_id

    first = API(10)
    second = API(20)
    sender = telegram_proactive_sender({1: first, 2: second})

    sent_ref = sender({"adapter_slot": 2}, SendText("123", "hi"), {})

    assert sent_ref == 20
    assert first.calls == []
    assert second.calls == [("123", "hi")]


def test_signal_proactive_sender_calls_signalbot_send() -> None:
    class Bot:
        def __init__(self) -> None:
            self.calls = []

        def send(self, receiver: str, text: str, **kwargs) -> int:
            self.calls.append((receiver, text, kwargs))
            return 123456

    bot = Bot()
    sender = signal_proactive_sender(bot)

    sent_ref = asyncio.run(sender({"adapter_slot": 1}, SendText("+491", "hi", text_mode="styled"), {}))

    assert sent_ref == 123456
    assert bot.calls == [("+491", "hi", {"base64_attachments": None, "text_mode": "styled"})]


def test_signal_proactive_sender_coerces_link_preview_dict() -> None:
    from signalbot import LinkPreview

    class Bot:
        def __init__(self) -> None:
            self.calls = []

        def send(self, receiver: str, text: str, **kwargs) -> int:
            self.calls.append((receiver, text, kwargs))
            return 123456

    bot = Bot()
    sender = signal_proactive_sender(bot)

    sent_ref = asyncio.run(
        sender(
            {"adapter_slot": 1},
            SendText(
                "+491",
                "Link",
                link_preview={
                    "title": "Tee",
                    "description": "Kanne",
                    "url": "https://example.test/tee",
                    "base64_thumbnail": "dGVl",
                    "id": "preview-1",
                },
            ),
            {},
        )
    )

    assert sent_ref == 123456
    preview = bot.calls[0][2]["link_preview"]
    assert isinstance(preview, LinkPreview)
    assert preview.title == "Tee"
    assert preview.description == "Kanne"
    assert preview.url == "https://example.test/tee"
    assert preview.base64_thumbnail == "dGVl"
    assert preview.id == "preview-1"


def test_signal_proactive_sender_sends_attachment_base64() -> None:
    class Bot:
        def __init__(self) -> None:
            self.calls = []

        def send(self, receiver: str, text: str, **kwargs) -> int:
            self.calls.append((receiver, text, kwargs))
            return 123457

    bot = Bot()
    sender = signal_proactive_sender(bot)

    sent_ref = asyncio.run(
        sender(
            {"adapter_slot": 1},
            SendAttachment("+491", b"hello", "voice.ogg", "audio/ogg", caption="Sprachnotiz", view_once=True),
            {},
        )
    )

    assert sent_ref == 123457
    assert bot.calls == [
        (
            "+491",
            "Sprachnotiz",
            {
                "base64_attachments": ["aGVsbG8="],
                "view_once": True,
            },
        )
    ]


def test_signal_proactive_sender_sends_export_file_base64() -> None:
    class Bot:
        def __init__(self) -> None:
            self.calls = []

        async def send(self, receiver: str, text: str, **kwargs) -> int:
            self.calls.append((receiver, text, kwargs))
            return 123458

    bot = Bot()
    sender = signal_proactive_sender(bot)

    sent_ref = asyncio.run(sender({"adapter_slot": 1}, ExportFile("+491", "report.json", "application/json", b'{"ok":true}'), {}))

    assert sent_ref == 123458
    assert bot.calls == [("+491", "Export: report.json", {"base64_attachments": ["eyJvayI6dHJ1ZX0="]})]


def test_signal_proactive_sender_requires_numeric_timestamp() -> None:
    class Bot:
        def send(self, receiver: str, text: str, **kwargs) -> None:
            return None

    sender = signal_proactive_sender(Bot())

    try:
        asyncio.run(sender({"adapter_slot": 1}, SendText("+491", "hi"), {}))
    except RuntimeError as exc:
        assert "Signal text send returned no numeric timestamp" in str(exc)
    else:
        raise AssertionError("missing Signal timestamp should fail proactive dispatch")


def test_signal_proactive_sender_reuses_full_adapter_for_edit_poll_and_typing() -> None:
    class Bot:
        def __init__(self) -> None:
            self.calls = []

        async def send(self, receiver: str, text: str, **kwargs) -> int:
            self.calls.append(("send", receiver, text, kwargs))
            return 123459

        async def poll(self, receiver: str, question: str, answers: list[str], **kwargs) -> int:
            self.calls.append(("poll", receiver, question, tuple(answers), kwargs))
            return 123460

        async def start_typing(self, receiver: str) -> None:
            self.calls.append(("start_typing", receiver))

        async def stop_typing(self, receiver: str) -> None:
            self.calls.append(("stop_typing", receiver))

    bot = Bot()
    sender = signal_proactive_sender(bot)

    typing_ref = asyncio.run(sender({"adapter_slot": 1}, SendTyping("+491"), {}))
    edit_ref = asyncio.run(sender({"adapter_slot": 1}, SendEdit("+491", "123456", "korrigiert"), {}))
    poll_ref = asyncio.run(sender({"adapter_slot": 1}, SendPoll("+491", "Tee?", ("Ja", "Nein"), allow_multiple_selections=True), {}))

    assert typing_ref is None
    assert edit_ref == 123459
    assert poll_ref == 123460
    assert bot.calls == [
        ("start_typing", "+491"),
        ("stop_typing", "+491"),
        ("send", "+491", "korrigiert", {"edit_timestamp": 123456}),
        ("poll", "+491", "Tee?", ("Ja", "Nein"), {"allow_multiple_selections": True}),
    ]


def test_signal_proactive_sender_reuses_full_adapter_for_reaction_and_receipt() -> None:
    class Bot:
        def __init__(self) -> None:
            self.calls = []

        async def react(self, message, emoji: str) -> None:
            self.calls.append(("react", message.recipient(), message.timestamp, emoji))

        async def receipt(self, message, receipt_type: str) -> None:
            self.calls.append(("receipt", message.recipient(), message.timestamp, receipt_type))

    bot = Bot()
    sender = signal_proactive_sender(bot)

    reaction_ref = asyncio.run(sender({"adapter_slot": 1}, SendReaction("+491", "123456", "\U0001f44d"), {}))
    receipt_ref = asyncio.run(sender({"adapter_slot": 1}, SendReceipt("+491", "123456", "viewed"), {}))

    assert reaction_ref is None
    assert receipt_ref is None
    assert bot.calls == [
        ("react", "+491", "123456", "\U0001f44d"),
        ("receipt", "+491", "123456", "viewed"),
    ]


def test_signal_proactive_context_exposes_delete_contract() -> None:
    from TeeBotus.runtime.proactive_backends import _SignalProactiveContext

    class Bot:
        def __init__(self) -> None:
            self.calls = []

        async def remote_delete(self, receiver: str, timestamp: int) -> int:
            self.calls.append(("remote_delete", receiver, timestamp))
            return timestamp

        async def delete_attachment(self, attachment_filename: str) -> None:
            self.calls.append(("delete_attachment", attachment_filename))

    bot = Bot()
    context = _SignalProactiveContext(bot, "+491")

    delete_ref = asyncio.run(context.remote_delete(123456))
    attachment_ref = asyncio.run(context.delete_attachment("voice.ogg"))

    assert delete_ref == 123456
    assert attachment_ref is None
    assert bot.calls == [
        ("remote_delete", "+491", 123456),
        ("delete_attachment", "voice.ogg"),
    ]


def test_matrix_proactive_sender_calls_nio_bot_send_message() -> None:
    class Client:
        def __init__(self) -> None:
            self.calls = []

        async def send_message(self, room: str, content: str, **kwargs):
            self.calls.append((room, content, kwargs))
            return SimpleNamespace(event_id="$event")

    client = Client()
    sender = matrix_proactive_sender({1: client})

    sent_ref = asyncio.run(sender({"adapter_slot": 1}, SendText("!room:example.org", "hi"), {}))

    assert sent_ref == "$event"
    assert client.calls == [
        (
            "!room:example.org",
            "hi",
            {"message_type": "m.text", "clean_mentions": True},
        )
    ]


def test_matrix_proactive_sender_reuses_full_matrix_adapter_for_exports() -> None:
    class Client:
        def __init__(self) -> None:
            self.uploads = []
            self.sent = []

        async def upload(self, data_provider, **kwargs):
            self.uploads.append((data_provider.read(), kwargs))
            return SimpleNamespace(content_uri="mxc://example/report"), None

        async def room_send(self, **kwargs):
            self.sent.append(kwargs)
            return SimpleNamespace(event_id="$export")

    client = Client()
    sender = matrix_proactive_sender({1: client})

    sent_ref = asyncio.run(
        sender({"adapter_slot": 1}, ExportFile("!room:example.org", "report.json", "application/json", b'{"ok":true}', caption="Export"), {})
    )

    assert sent_ref == "$export"
    assert client.uploads == [
        (
            b'{"ok":true}',
            {
                "content_type": "application/json",
                "filename": "report.json",
                "filesize": 11,
                "encrypt": False,
            },
        )
    ]
    assert client.sent[0]["content"]["url"] == "mxc://example/report"
    assert client.sent[0]["content"]["body"] == "Export"


def test_matrix_proactive_sender_starts_lazy_client_before_dispatch() -> None:
    class Client:
        def __init__(self) -> None:
            self.started = False
            self.calls = []

        async def ensure_started(self) -> None:
            self.started = True

        async def send_message(self, room: str, content: str, **kwargs):
            self.calls.append((self.started, room, content, kwargs))
            return SimpleNamespace(event_id="$event")

    client = Client()
    sender = matrix_proactive_sender({1: client})

    sent_ref = asyncio.run(sender({"adapter_slot": 1}, SendText("!room:example.org", "hi"), {}))

    assert sent_ref == "$event"
    assert client.calls == [(True, "!room:example.org", "hi", {"message_type": "m.text", "clean_mentions": True})]


def test_proactive_sender_reports_missing_slot() -> None:
    sender = telegram_proactive_sender({2: object()})

    try:
        sender({"adapter_slot": 3}, SendText("123", "hi"), {})
    except KeyError as exc:
        assert "adapter slot 3" in str(exc)
    else:
        raise AssertionError("missing adapter slot should fail")


def test_proactive_sender_rejects_invalid_slot() -> None:
    sender = telegram_proactive_sender({1: object()})

    with pytest.raises(KeyError, match="invalid adapter slot"):
        sender({"adapter_slot": "broken"}, SendText("123", "hi"), {})
