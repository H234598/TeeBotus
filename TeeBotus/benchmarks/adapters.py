from __future__ import annotations

import asyncio
import importlib.metadata
import json
import statistics
import time
from typing import Any, Callable

from TeeBotus.adapters.matrix import matrix_message_to_event, send_matrix_actions
from TeeBotus.adapters.signal import send_signal_actions, signal_message_to_event
from TeeBotus.adapters.telegram import send_telegram_actions, telegram_message_to_event
from TeeBotus.benchmarks.core import BenchmarkResult, result
from TeeBotus.runtime.actions import SendText


def benchmark_adapter_contracts(*, iterations: int) -> BenchmarkResult:
    packages = ("signalbot", "nio-bot", "matrix-nio")

    def check() -> list[str]:
        return [importlib.metadata.version(package) for package in packages]

    errors = 0
    timings = []
    versions: list[str] = []
    for _ in range(iterations):
        try:
            timings.append(_timed_ms(lambda: versions.extend(check())))
        except importlib.metadata.PackageNotFoundError:
            errors += 1
    runtime_timings = []
    runtime_checks: list[dict[str, Any]] = []
    for _ in range(iterations):
        runtime_timings.append(_timed_ms(lambda: runtime_checks.append(_messenger_adapter_runtime_contract())))
    runtime_errors = sum(1 for check_result in runtime_checks if not check_result.get("ok"))
    latest_runtime = runtime_checks[-1] if runtime_checks else {}
    return result(
        name="messenger_adapter_runtime_contracts",
        category="messenger_adapters",
        iterations=iterations * 2,
        total_ms=sum(timings) + sum(runtime_timings),
        ok=errors == 0 and runtime_errors == 0,
        errors=errors + runtime_errors,
        payload_bytes=int(latest_runtime.get("payload_bytes") or 0),
        index_bytes=len(json.dumps({"packages": packages}, ensure_ascii=False).encode("utf-8")),
        details={
            "packages": packages,
            "version_reads": len(versions),
            "channels": ["telegram", "signal", "matrix"],
            "event_contracts": latest_runtime.get("event_contracts", {}),
            "send_contracts": latest_runtime.get("send_contracts", {}),
            "fake_network_sends": latest_runtime.get("fake_network_sends", 0),
            "network_calls": 0,
            "median_runtime_contract_ms": statistics.median(runtime_timings) if runtime_timings else 0.0,
        },
    )


def _messenger_adapter_runtime_contract() -> dict[str, Any]:
    telegram_api = _FakeTelegramAPI()
    telegram_event = telegram_message_to_event(
        {
            "message_id": 42,
            "chat": {"id": 1001, "type": "private"},
            "from": {"id": 2002, "first_name": "Ada", "username": "ada"},
            "text": "Hallo TeeBotus",
        },
        instance="Bench",
        adapter_slot=1,
    )
    telegram_refs = send_telegram_actions(telegram_api, [SendText("1001", "Telegram OK")])

    signal_message = _FakeSignalMessage()
    signal_event = signal_message_to_event(signal_message, instance="Bench", adapter_slot=1)
    signal_context = _FakeSignalContext(signal_message)
    signal_refs = asyncio.run(send_signal_actions(signal_context, [SendText("+491", "Signal OK")]))

    matrix_room = _FakeMatrixRoom()
    matrix_message = _FakeMatrixMessage()
    matrix_event = matrix_message_to_event(matrix_room, matrix_message, instance="Bench", adapter_slot=1)
    matrix_client = _FakeMatrixClient()
    matrix_refs = asyncio.run(send_matrix_actions(matrix_client, [SendText("!room:example", "Matrix OK")]))

    event_contracts = {
        "telegram": _adapter_event_contract(telegram_event, channel="telegram", chat_id="1001"),
        "signal": _adapter_event_contract(signal_event, channel="signal", chat_id="+491"),
        "matrix": _adapter_event_contract(matrix_event, channel="matrix", chat_id="!room:example"),
    }
    send_contracts = {
        "telegram": telegram_refs == [10001] and telegram_api.sent == [("1001", "Telegram OK")],
        "signal": signal_refs == [20001] and signal_context.sent == ["Signal OK"],
        "matrix": matrix_refs == ["$bench"] and matrix_client.sent_texts == [("!room:example", "Matrix OK")],
    }
    payload_texts = [
        telegram_event.text if telegram_event else "",
        signal_event.text if signal_event else "",
        matrix_event.text if matrix_event else "",
        *[text for _chat_id, text in telegram_api.sent],
        *signal_context.sent,
        *[text for _room_id, text in matrix_client.sent_texts],
    ]
    return {
        "ok": all(event_contracts.values()) and all(send_contracts.values()),
        "event_contracts": event_contracts,
        "send_contracts": send_contracts,
        "fake_network_sends": len(telegram_api.sent) + len(signal_context.sent) + len(matrix_client.sent_texts),
        "payload_bytes": sum(len(text.encode("utf-8")) for text in payload_texts),
    }


def _adapter_event_contract(event: Any, *, channel: str, chat_id: str) -> bool:
    return (
        event is not None
        and getattr(event, "channel", "") == channel
        and str(getattr(event, "chat_id", "")) == chat_id
        and bool(str(getattr(event, "identity_key", "")).strip())
        and bool(str(getattr(event, "text", "")).strip())
    )


class _FakeTelegramAPI:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_message(self, chat_id: Any, text: str) -> int:
        self.sent.append((str(chat_id), str(text)))
        return 10001


class _FakeSignalMessage:
    source_uuid = "signal-source-uuid"
    source_number = "+492"
    source = "+492"
    text = "Hallo Signal"
    timestamp = 123456789
    group = None
    attachments_local_filenames: list[str] = []
    base64_attachments: list[str] = []
    view_once = False

    def recipient(self) -> str:
        return "+491"


class _FakeSignalContext:
    def __init__(self, message: _FakeSignalMessage) -> None:
        self.message = message
        self.sent: list[str] = []

    async def send(self, text: str, **_kwargs: Any) -> int:
        self.sent.append(str(text))
        return 20001


class _FakeMatrixRoom:
    room_id = "!room:example"
    joined_count = 2
    invited_count = 0


class _FakeMatrixMessage:
    sender = "@ada:example"
    event_id = "$incoming"
    body = "Hallo Matrix"
    formatted_body = ""
    source = {"content": {"body": "Hallo Matrix", "msgtype": "m.text"}}


class _FakeMatrixResponse:
    event_id = "$bench"


class _FakeMatrixClient:
    def __init__(self) -> None:
        self.sent_texts: list[tuple[str, str]] = []

    async def send_message(self, room_id: str, text: str, **_kwargs: Any) -> _FakeMatrixResponse:
        self.sent_texts.append((str(room_id), str(text)))
        return _FakeMatrixResponse()

    async def room_send(self, *, room_id: str, content: dict[str, Any], **_kwargs: Any) -> _FakeMatrixResponse:
        self.sent_texts.append((str(room_id), str(content.get("body") or "")))
        return _FakeMatrixResponse()


def _timed_ms(func: Callable[[], Any]) -> float:
    start = time.perf_counter()
    func()
    return (time.perf_counter() - start) * 1000


__all__ = ["benchmark_adapter_contracts"]
