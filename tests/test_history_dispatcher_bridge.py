from __future__ import annotations

import asyncio
import json
import socketserver
import struct
import threading
import time
from pathlib import Path

import pytest

from TeeBotus.history_dispatcher_bridge import (
    CallbackSpool,
    HistoryDispatcherBridge,
    HistoryDispatcherClient,
)


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        raw_size = self.rfile.read(4)
        if len(raw_size) != 4:
            return
        size = struct.unpack("!I", raw_size)[0]
        request = json.loads(self.rfile.read(size).decode("utf-8"))
        operation = request["operation"]
        if operation == "status.get":
            data = {"service": "history-dispatcher", "ok": True}
        else:
            data = {"ok": True, "event_id": request.get("body", {}).get("event_id", "")}
        response = json.dumps({"ok": True, "data": data}, separators=(",", ":")).encode("utf-8")
        self.wfile.write(struct.pack("!I", len(response)) + response)


class _Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def _dispatcher(tmp_path: Path) -> tuple[_Server, threading.Thread]:
    path = tmp_path / "runtime/control.sock"
    path.parent.mkdir(parents=True)
    server = _Server(str(path), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    for _ in range(100):
        if path.exists():
            break
        time.sleep(0.01)
    return server, thread


def test_bridge_async_status_and_receipt_round_trip(tmp_path: Path) -> None:
    server, thread = _dispatcher(tmp_path)
    bridge = HistoryDispatcherBridge(
        HistoryDispatcherClient(tmp_path / "runtime/control.sock"),
        CallbackSpool(tmp_path / "spool"),
    )

    async def run() -> None:
        status = await bridge.status()
        assert status["service"] == "history-dispatcher"
        receipt = await bridge.record_delivery({
            "event_id": "event-1",
            "item_id": "item-1",
            "recipient_id": "recipient-1",
            "event_type": "delivered",
        })
        assert receipt["ok"] is True

    asyncio.run(run())
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def test_bridge_spools_when_dispatcher_is_unavailable(tmp_path: Path) -> None:
    spool = CallbackSpool(tmp_path / "spool")
    bridge = HistoryDispatcherBridge(
        HistoryDispatcherClient(tmp_path / "missing.sock", timeout_seconds=0.25),
        spool,
    )

    async def run() -> None:
        result = await bridge.record_delivery({
            "event_id": "event-2",
            "item_id": "item-2",
            "recipient_id": "recipient-2",
            "event_type": "read",
        })
        assert result["spooled"] is True

    asyncio.run(run())
    assert len(spool.events()) == 1


def test_callback_spool_persists_generated_event_id(tmp_path: Path) -> None:
    spool = CallbackSpool(tmp_path / "spool")

    path = spool.enqueue({"item_id": "item-3", "recipient_id": "recipient-3", "event_type": "sent"})

    events = spool.events()
    assert len(events) == 1
    assert events[0][0] == path
    assert events[0][1]["event_id"] == path.stem


def test_callback_spool_does_not_overwrite_conflicting_event_id(tmp_path: Path) -> None:
    spool = CallbackSpool(tmp_path / "spool")
    path = spool.enqueue({"event_id": "same-event", "event_type": "sent"})

    assert spool.enqueue({"event_id": "same-event", "event_type": "sent"}) == path
    with pytest.raises(ValueError, match="different payload"):
        spool.enqueue({"event_id": "same-event", "event_type": "delivered"})
    assert path.read_text(encoding="utf-8") == '{"event_id":"same-event","event_type":"sent"}'


def test_callback_spool_skips_invalid_files_without_starving_valid_batch_entries(tmp_path: Path) -> None:
    spool = CallbackSpool(tmp_path / "spool")
    for index in range(100):
        (spool.root / f"000-invalid-{index:03d}.json").write_text("{broken", encoding="utf-8")
    valid = spool.enqueue({"event_id": "999-valid", "item_id": "item", "event_type": "delivered"})

    events = spool.events(limit=100)

    assert events == [(valid, {"event_id": "999-valid", "item_id": "item", "event_type": "delivered"})]


def test_bridge_keeps_spooled_event_when_inner_dispatcher_result_fails(tmp_path: Path) -> None:
    spool = CallbackSpool(tmp_path / "spool")

    class InnerFailureClient:
        async def request_async(self, _operation: str, _body: object) -> dict[str, object]:
            return {"ok": True, "data": {"ok": False, "error": "missing item"}}

    bridge = HistoryDispatcherBridge(InnerFailureClient(), spool)  # type: ignore[arg-type]
    spool.enqueue({"event_id": "event-inner-failure", "item_id": "missing", "recipient_id": "admin", "event_type": "sent"})

    result = asyncio.run(bridge.flush_spool())

    assert result == {"delivered": 0, "failed": 1}
    assert len(spool.events()) == 1


def test_bridge_keeps_spooled_event_when_dispatcher_response_has_no_data(tmp_path: Path) -> None:
    spool = CallbackSpool(tmp_path / "spool")

    class EmptyResponseClient:
        async def request_async(self, _operation: str, _body: object) -> dict[str, object]:
            return {"ok": True, "data": None}

    bridge = HistoryDispatcherBridge(EmptyResponseClient(), spool)  # type: ignore[arg-type]
    spool.enqueue({"event_id": "event-empty-response", "item_id": "item", "recipient_id": "admin", "event_type": "sent"})

    result = asyncio.run(bridge.flush_spool())

    assert result == {"delivered": 0, "failed": 1}
    assert len(spool.events()) == 1
