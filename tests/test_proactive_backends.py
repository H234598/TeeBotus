from __future__ import annotations

import asyncio
from types import SimpleNamespace

from TeeBotus.runtime.actions import ExportFile, SendAttachment, SendText
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
    assert bot.calls == [
        (
            "+491",
            "hi",
            {
                "mentions": None,
                "text_mode": "styled",
                "view_once": False,
                "link_preview": None,
            },
        )
    ]


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
                "mentions": None,
                "text_mode": None,
                "view_once": True,
                "link_preview": None,
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


def test_proactive_sender_reports_missing_slot() -> None:
    sender = telegram_proactive_sender({2: object()})

    try:
        sender({"adapter_slot": 3}, SendText("123", "hi"), {})
    except KeyError as exc:
        assert "adapter slot 3" in str(exc)
    else:
        raise AssertionError("missing adapter slot should fail")
