from __future__ import annotations

import asyncio
from types import SimpleNamespace

from TeeBotus.runtime.actions import SendText
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


def test_proactive_sender_reports_missing_slot() -> None:
    sender = telegram_proactive_sender({2: object()})

    try:
        sender({"adapter_slot": 3}, SendText("123", "hi"), {})
    except KeyError as exc:
        assert "adapter slot 3" in str(exc)
    else:
        raise AssertionError("missing adapter slot should fail")
