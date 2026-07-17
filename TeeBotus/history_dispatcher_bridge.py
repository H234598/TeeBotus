from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import struct
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("TeeBotus.history_dispatcher_bridge")
PROTOCOL_VERSION = 1
DEFAULT_FRAME_LIMIT = 8 * 1024 * 1024
MAX_SPOOL_EVENT_BYTES = 128 * 1024
MAX_SPOOL_EVENTS_PER_FLUSH = 100


class HistoryDispatcherError(RuntimeError):
    pass


class HistoryDispatcherUnavailable(HistoryDispatcherError):
    pass


class HistoryDispatcherProtocolError(HistoryDispatcherError):
    pass


def _read_exact(connection: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = connection.recv(remaining)
        if not chunk:
            raise HistoryDispatcherProtocolError("truncated dispatcher frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _encode(value: object, *, max_bytes: int) -> bytes:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(payload) > max_bytes:
        raise HistoryDispatcherProtocolError("dispatcher frame exceeds configured limit")
    return struct.pack("!I", len(payload)) + payload


def _decode(connection: socket.socket, *, max_bytes: int) -> object:
    header = _read_exact(connection, 4)
    size = struct.unpack("!I", header)[0]
    if size <= 0 or size > max_bytes:
        raise HistoryDispatcherProtocolError("invalid dispatcher frame size")
    try:
        return json.loads(_read_exact(connection, size).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HistoryDispatcherProtocolError("invalid dispatcher JSON response") from exc


class HistoryDispatcherClient:
    def __init__(self, socket_path: str | Path, *, timeout_seconds: float = 10.0, frame_limit_bytes: int = DEFAULT_FRAME_LIMIT) -> None:
        self.socket_path = Path(socket_path).expanduser()
        self.timeout_seconds = max(0.25, min(float(timeout_seconds), 60.0))
        self.frame_limit_bytes = max(1024, min(int(frame_limit_bytes), 64 * 1024 * 1024))

    def request(self, operation: str, body: Mapping[str, Any] | None = None) -> dict[str, Any]:
        request = {
            "protocol_version": PROTOCOL_VERSION,
            "request_id": uuid.uuid4().hex,
            "operation": str(operation).strip(),
            "body": dict(body or {}),
        }
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(self.timeout_seconds)
                connection.connect(str(self.socket_path))
                connection.sendall(_encode(request, max_bytes=self.frame_limit_bytes))
                response = _decode(connection, max_bytes=self.frame_limit_bytes)
        except (OSError, TimeoutError) as exc:
            raise HistoryDispatcherUnavailable("History-Dispatcher socket unavailable") from exc
        if not isinstance(response, dict):
            raise HistoryDispatcherProtocolError("dispatcher response must be an object")
        return response

    async def request_async(self, operation: str, body: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return await asyncio.to_thread(self.request, operation, body)


class CallbackSpool:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)

    def enqueue(self, event: Mapping[str, Any]) -> Path:
        event_data = dict(event)
        event_id = str(event_data.get("event_id") or uuid.uuid4().hex)
        if not event_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for char in event_id):
            raise ValueError("invalid dispatcher callback event id")
        event_data["event_id"] = event_id
        raw = json.dumps(event_data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(raw) > MAX_SPOOL_EVENT_BYTES:
            raise ValueError("dispatcher callback event exceeds spool limit")
        target = self.root / f"{event_id}.json"
        temporary = self.root / f".{event_id}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        try:
            with temporary.open("wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            try:
                os.link(temporary, target)
            except FileExistsError:
                if target.is_symlink() or target.read_bytes() != raw:
                    raise ValueError(f"dispatcher callback event id already contains different payload: {event_id}")
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        return target

    def events(self, *, limit: int = MAX_SPOOL_EVENTS_PER_FLUSH) -> list[tuple[Path, dict[str, Any]]]:
        result: list[tuple[Path, dict[str, Any]]] = []
        max_events = max(1, min(int(limit), MAX_SPOOL_EVENTS_PER_FLUSH))
        for path in sorted(self.root.glob("*.json")):
            if len(result) >= max_events:
                break
            if path.is_symlink() or not path.is_file():
                continue
            try:
                if path.stat().st_size > MAX_SPOOL_EVENT_BYTES:
                    LOGGER.error("Ignoring oversized dispatcher spool event: %s", path.name)
                    continue
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                LOGGER.exception("Ignoring malformed dispatcher spool event: %s", path.name)
                continue
            if isinstance(value, dict):
                result.append((path, value))
        return result

    def discard(self, path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


class HistoryDispatcherBridge:
    def __init__(self, client: HistoryDispatcherClient, spool: CallbackSpool) -> None:
        self.client = client
        self.spool = spool

    async def status(self) -> dict[str, Any]:
        try:
            response = await self.client.request_async("status.get")
            return response.get("data", response) if response.get("ok") else {"ok": False, "error": response.get("error", {})}
        except HistoryDispatcherError as exc:
            return {"ok": False, "degraded": True, "error": str(exc)}

    async def claim(self, worker_id: str, *, limit: int = 20) -> dict[str, Any]:
        response = await self.client.request_async("dispatch.claim", {"worker_id": worker_id, "limit": limit})
        return response.get("data", response)

    async def complete(self, item_id: str, worker_id: str, results: Sequence[Mapping[str, Any]], *, reason: str = "") -> dict[str, Any]:
        response = await self.client.request_async("dispatch.complete", {
            "item_id": item_id,
            "worker_id": worker_id,
            "recipient_results": [dict(item) for item in results],
            "reason": reason,
        })
        return response.get("data", response)

    async def record_delivery(self, event: Mapping[str, Any]) -> dict[str, Any]:
        event_data = dict(event)
        try:
            response = await self.client.request_async("delivery.record", event_data)
            return response.get("data", response)
        except HistoryDispatcherError:
            spool_path = self.spool.enqueue(event_data)
            return {"ok": False, "spooled": True, "event_id": str(event_data.get("event_id") or spool_path.stem)}

    async def flush_spool(self) -> dict[str, int]:
        delivered = failed = 0
        for path, event in self.spool.events():
            try:
                response = await self.client.request_async("delivery.record", event)
                data = response.get("data", response)
                succeeded = response.get("ok") is True and isinstance(data, Mapping) and data.get("ok") is True
                if succeeded:
                    self.spool.discard(path)
                    delivered += 1
                else:
                    failed += 1
            except HistoryDispatcherError:
                failed += 1
                break
        return {"delivered": delivered, "failed": failed}
