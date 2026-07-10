from __future__ import annotations

import asyncio
import json
import socketserver
import struct
import threading
import time
from pathlib import Path

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

