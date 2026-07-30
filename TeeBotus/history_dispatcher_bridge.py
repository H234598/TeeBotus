from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import socket
import struct
import threading
import uuid
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from TeeBotus.runtime.accounts import InstanceSecretProvider

try:
    import fcntl
except ImportError:  # pragma: no cover - fcntl is unavailable on non-POSIX platforms.
    fcntl = None  # type: ignore[assignment]

LOGGER = logging.getLogger("TeeBotus.history_dispatcher_bridge")
PROTOCOL_VERSION = 1
PROVIDER_API_SCHEMA_VERSION = 2
TEEBOTUS_CAPABILITY_V2 = "history-dispatcher-telegram-v2"
PROVIDER_V2_OPERATIONS = (
    "provider.v2.claim",
    "provider.v2.renew",
    "provider.v2.register_recipients",
    "provider.v2.record_recipients",
    "provider.v2.complete",
    "provider.v2.heartbeat",
)
DEFAULT_FRAME_LIMIT = 8 * 1024 * 1024
MAX_SPOOL_EVENT_BYTES = 128 * 1024
MAX_SPOOL_EVENTS_PER_FLUSH = 100
CALLBACK_SPOOL_LOCK_FILENAME = ".CallbackSpool.lock"
PROVIDER_CALLBACK_SPOOL_LOCK_FILENAME = ".ProviderCallbackSpool.lock"
PROVIDER_CALLBACK_SPOOL_PURPOSE = "history-dispatcher-provider-v2-callback-spool"
PROVIDER_CALLBACK_SPOOL_MAGIC = b"TBHDPV2\x01"
PROVIDER_CALLBACK_SPOOL_NONCE_BYTES = 12
MAX_PROVIDER_SPOOL_PLAINTEXT_BYTES = 256 * 1024
MAX_PROVIDER_SPOOL_FILE_BYTES = (
    len(PROVIDER_CALLBACK_SPOOL_MAGIC)
    + PROVIDER_CALLBACK_SPOOL_NONCE_BYTES
    + MAX_PROVIDER_SPOOL_PLAINTEXT_BYTES
    + 32
)
PROVIDER_SPOOLABLE_OPERATIONS = frozenset(
    {
        "provider.v2.register_recipients",
        "provider.v2.record_recipients",
        "provider.v2.complete",
    }
)
_SAFE_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SAFE_OPAQUE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SAFE_CLAIM_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,512}$")


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
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise HistoryDispatcherProtocolError(
            "dispatcher request must contain finite JSON"
        ) from exc
    if len(payload) > max_bytes:
        raise HistoryDispatcherProtocolError(
            "dispatcher frame exceeds configured limit"
        )
    return struct.pack("!I", len(payload)) + payload


def _decode(connection: socket.socket, *, max_bytes: int) -> object:
    header = _read_exact(connection, 4)
    size = struct.unpack("!I", header)[0]
    if size <= 0 or size > max_bytes:
        raise HistoryDispatcherProtocolError("invalid dispatcher frame size")
    try:
        return json.loads(_read_exact(connection, size).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HistoryDispatcherProtocolError(
            "invalid dispatcher JSON response"
        ) from exc


def _request_id(value: str | None) -> str:
    candidate = uuid.uuid4().hex if value is None else str(value).strip()
    if not _SAFE_REQUEST_ID_RE.fullmatch(candidate):
        raise HistoryDispatcherProtocolError("invalid dispatcher request_id")
    return candidate


def _opaque_ref(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise HistoryDispatcherProtocolError(f"{field} must be a string")
    candidate = value.strip()
    if not _SAFE_OPAQUE_REF_RE.fullmatch(candidate):
        raise HistoryDispatcherProtocolError(f"{field} is invalid")
    return candidate


def _claim_token(value: object) -> str:
    if not isinstance(value, str) or not _SAFE_CLAIM_TOKEN_RE.fullmatch(value):
        raise HistoryDispatcherProtocolError("claim_token is invalid")
    return value


def _canonical_json_bytes(value: object, *, max_bytes: int) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("provider callback must contain finite JSON") from exc
    if len(encoded) > max_bytes:
        raise ValueError("provider callback exceeds spool limit")
    return encoded


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class HistoryDispatcherClient:
    def __init__(
        self,
        socket_path: str | Path,
        *,
        timeout_seconds: float = 10.0,
        frame_limit_bytes: int = DEFAULT_FRAME_LIMIT,
    ) -> None:
        self.socket_path = Path(socket_path).expanduser()
        self.timeout_seconds = max(0.25, min(float(timeout_seconds), 60.0))
        self.frame_limit_bytes = max(
            1024,
            min(int(frame_limit_bytes), 64 * 1024 * 1024),
        )

    def request(
        self,
        operation: str,
        body: Mapping[str, Any] | None = None,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        normalized_operation = str(operation or "").strip()
        if not normalized_operation or len(normalized_operation) > 128:
            raise HistoryDispatcherProtocolError("invalid dispatcher operation")
        request = {
            "protocol_version": PROTOCOL_VERSION,
            "request_id": _request_id(request_id),
            "operation": normalized_operation,
            "body": dict(body or {}),
        }
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(self.timeout_seconds)
                connection.connect(str(self.socket_path))
                connection.sendall(
                    _encode(request, max_bytes=self.frame_limit_bytes)
                )
                response = _decode(
                    connection,
                    max_bytes=self.frame_limit_bytes,
                )
        except (OSError, TimeoutError) as exc:
            raise HistoryDispatcherUnavailable(
                "History-Dispatcher socket unavailable"
            ) from exc
        if not isinstance(response, dict):
            raise HistoryDispatcherProtocolError(
                "dispatcher response must be an object"
            )
        return response

    async def request_async(
        self,
        operation: str,
        body: Mapping[str, Any] | None = None,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.request,
            operation,
            body,
            request_id=request_id,
        )


class CallbackSpool:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self._flush_thread_lock = threading.RLock()

    @contextmanager
    def flush_lock(self):
        with self._flush_thread_lock:
            lock_path = self.root / CALLBACK_SPOOL_LOCK_FILENAME
            with lock_path.open("a+") as handle:
                locked = False
                try:
                    os.chmod(lock_path, 0o600)
                    if fcntl is not None:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                        locked = True
                    yield
                finally:
                    if locked:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def enqueue(self, event: Mapping[str, Any]) -> Path:
        event_data = dict(event)
        event_id = str(event_data.get("event_id") or uuid.uuid4().hex)
        if not event_id or any(
            char
            not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
            for char in event_id
        ):
            raise ValueError("invalid dispatcher callback event id")
        event_data["event_id"] = event_id
        raw = _canonical_json_bytes(
            event_data,
            max_bytes=MAX_SPOOL_EVENT_BYTES,
        )
        target = self.root / f"{event_id}.json"
        temporary = self.root / (
            f".{event_id}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        )
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
                    raise ValueError(
                        "dispatcher callback event id already contains "
                        f"different payload: {event_id}"
                    )
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        return target

    def events(
        self,
        *,
        limit: int = MAX_SPOOL_EVENTS_PER_FLUSH,
    ) -> list[tuple[Path, dict[str, Any]]]:
        result: list[tuple[Path, dict[str, Any]]] = []
        max_events = max(1, min(int(limit), MAX_SPOOL_EVENTS_PER_FLUSH))
        for path in sorted(self.root.glob("*.json")):
            if len(result) >= max_events:
                break
            if path.is_symlink() or not path.is_file():
                continue
            try:
                if path.stat().st_size > MAX_SPOOL_EVENT_BYTES:
                    LOGGER.error(
                        "Ignoring oversized dispatcher spool event: %s",
                        path.name,
                    )
                    continue
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                LOGGER.exception(
                    "Ignoring malformed dispatcher spool event: %s",
                    path.name,
                )
                continue
            if isinstance(value, dict):
                result.append((path, value))
        return result

    def discard(self, path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


class ProviderCallbackSpool:
    """Encrypted owner-only spool for provider callbacks containing claim tokens."""

    def __init__(
        self,
        root: str | Path,
        *,
        secret_provider: InstanceSecretProvider,
        instance_name: str,
    ) -> None:
        normalized_instance = str(instance_name or "").strip()
        if (
            not normalized_instance
            or normalized_instance in {".", ".."}
            or "/" in normalized_instance
            or "\\" in normalized_instance
            or any(ord(char) < 0x20 for char in normalized_instance)
        ):
            raise ValueError("invalid provider spool instance name")
        key = secret_provider.get_secret(
            normalized_instance,
            PROVIDER_CALLBACK_SPOOL_PURPOSE,
        )
        if not isinstance(key, bytes) or len(key) != 32:
            raise ValueError("provider callback spool key must be 32 bytes")
        self.root = Path(root).expanduser()
        if self.root.is_symlink():
            raise ValueError("provider callback spool root must not be a symlink")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise ValueError("provider callback spool root must be a directory")
        os.chmod(self.root, 0o700)
        self.instance_name = normalized_instance
        self._key = bytes(key)
        self._aad = (
            PROVIDER_CALLBACK_SPOOL_MAGIC
            + b"\x00"
            + normalized_instance.encode("utf-8")
        )
        self._flush_thread_lock = threading.RLock()

    @contextmanager
    def flush_lock(self):
        with self._flush_thread_lock:
            lock_path = self.root / PROVIDER_CALLBACK_SPOOL_LOCK_FILENAME
            with lock_path.open("a+") as handle:
                locked = False
                try:
                    os.chmod(lock_path, 0o600)
                    if fcntl is not None:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                        locked = True
                    yield
                finally:
                    if locked:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _validate_envelope(
        self,
        event: Mapping[str, Any],
    ) -> dict[str, Any]:
        event_data = dict(event)
        operation = str(event_data.get("operation") or "").strip()
        if operation not in PROVIDER_SPOOLABLE_OPERATIONS:
            raise ValueError("provider callback operation is not spoolable")
        request_id = _request_id(
            str(event_data.get("request_id") or "").strip()
        )
        body = event_data.get("body")
        if not isinstance(body, Mapping):
            raise ValueError("provider callback body must be an object")
        normalized_body = dict(body)
        fingerprint = hashlib.sha256(
            _canonical_json_bytes(
                {
                    "operation": operation,
                    "request_id": request_id,
                    "body": normalized_body,
                },
                max_bytes=MAX_PROVIDER_SPOOL_PLAINTEXT_BYTES,
            )
        ).hexdigest()
        event_id = str(event_data.get("event_id") or f"provider-{fingerprint[:40]}")
        if not _SAFE_REQUEST_ID_RE.fullmatch(event_id):
            raise ValueError("invalid provider callback event id")
        normalized = {
            "event_id": event_id,
            "operation": operation,
            "request_id": request_id,
            "body": normalized_body,
        }
        _canonical_json_bytes(
            normalized,
            max_bytes=MAX_PROVIDER_SPOOL_PLAINTEXT_BYTES,
        )
        return normalized

    def _encrypt(self, event: Mapping[str, Any]) -> bytes:
        raw = _canonical_json_bytes(
            event,
            max_bytes=MAX_PROVIDER_SPOOL_PLAINTEXT_BYTES,
        )
        nonce = os.urandom(PROVIDER_CALLBACK_SPOOL_NONCE_BYTES)
        ciphertext = AESGCM(self._key).encrypt(nonce, raw, self._aad)
        return PROVIDER_CALLBACK_SPOOL_MAGIC + nonce + ciphertext

    def _decrypt(self, raw: bytes) -> dict[str, Any]:
        if (
            len(raw)
            <= len(PROVIDER_CALLBACK_SPOOL_MAGIC)
            + PROVIDER_CALLBACK_SPOOL_NONCE_BYTES
            or not raw.startswith(PROVIDER_CALLBACK_SPOOL_MAGIC)
        ):
            raise ValueError("invalid provider callback spool envelope")
        offset = len(PROVIDER_CALLBACK_SPOOL_MAGIC)
        nonce = raw[offset : offset + PROVIDER_CALLBACK_SPOOL_NONCE_BYTES]
        ciphertext = raw[offset + PROVIDER_CALLBACK_SPOOL_NONCE_BYTES :]
        try:
            plaintext = AESGCM(self._key).decrypt(
                nonce,
                ciphertext,
                self._aad,
            )
            value = json.loads(plaintext.decode("utf-8"))
        except (InvalidTag, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid encrypted provider callback") from exc
        if not isinstance(value, Mapping):
            raise ValueError("provider callback is not an object")
        return self._validate_envelope(value)

    def enqueue(self, event: Mapping[str, Any]) -> Path:
        event_data = self._validate_envelope(event)
        event_id = str(event_data["event_id"])
        target = self.root / f"{event_id}.bin"
        temporary = self.root / (
            f".{event_id}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        )
        encrypted = self._encrypt(event_data)
        try:
            with temporary.open("wb") as handle:
                handle.write(encrypted)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            try:
                os.link(temporary, target)
                _fsync_directory(self.root)
            except FileExistsError:
                if target.is_symlink() or not target.is_file():
                    raise ValueError("provider callback path is unsafe")
                existing = self._decrypt(target.read_bytes())
                if existing != event_data:
                    raise ValueError(
                        "provider callback event id already contains "
                        f"different payload: {event_id}"
                    )
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        return target

    def events(
        self,
        *,
        limit: int = MAX_SPOOL_EVENTS_PER_FLUSH,
    ) -> list[tuple[Path, dict[str, Any]]]:
        result: list[tuple[Path, dict[str, Any]]] = []
        max_events = max(1, min(int(limit), MAX_SPOOL_EVENTS_PER_FLUSH))
        for path in sorted(self.root.glob("*.bin")):
            if len(result) >= max_events:
                break
            if path.is_symlink() or not path.is_file():
                continue
            try:
                if path.stat().st_size > MAX_PROVIDER_SPOOL_FILE_BYTES:
                    LOGGER.error(
                        "Ignoring oversized provider callback: %s",
                        path.name,
                    )
                    continue
                event = self._decrypt(path.read_bytes())
            except (OSError, ValueError):
                LOGGER.exception(
                    "Ignoring malformed provider callback: %s",
                    path.name,
                )
                continue
            result.append((path, event))
        return result

    def discard(self, path: Path) -> None:
        try:
            path.unlink()
            _fsync_directory(self.root)
        except FileNotFoundError:
            pass


def _provider_response_data(
    response: Mapping[str, Any],
    *,
    operation: str,
) -> dict[str, Any]:
    if not isinstance(response, Mapping) or response.get("ok") is not True:
        error = response.get("error") if isinstance(response, Mapping) else None
        raise HistoryDispatcherProtocolError(
            str(error or f"History-Dispatcher {operation} failed")
        )
    data = response.get("data")
    if not isinstance(data, Mapping) or data.get("ok") is not True:
        error = data.get("error") if isinstance(data, Mapping) else None
        raise HistoryDispatcherProtocolError(
            str(error or f"History-Dispatcher {operation} returned invalid data")
        )
    return dict(data)


def _recipient_refs(values: object, *, field: str) -> list[str]:
    if not isinstance(values, list):
        raise HistoryDispatcherProtocolError(f"{field} must be an array")
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        recipient = _opaque_ref(value, field=field)
        if recipient in seen:
            raise HistoryDispatcherProtocolError(f"{field} contains duplicates")
        seen.add(recipient)
        result.append(recipient)
    return result


class HistoryDispatcherBridge:
    def __init__(
        self,
        client: HistoryDispatcherClient,
        spool: CallbackSpool,
        *,
        provider_spool: ProviderCallbackSpool | None = None,
    ) -> None:
        self.client = client
        self.spool = spool
        self.provider_spool = provider_spool

    async def status(self) -> dict[str, Any]:
        try:
            response = await self.client.request_async("status.get")
            return (
                response.get("data", response)
                if response.get("ok")
                else {"ok": False, "error": response.get("error", {})}
            )
        except HistoryDispatcherError as exc:
            return {"ok": False, "degraded": True, "error": str(exc)}

    async def claim(self, worker_id: str, *, limit: int = 20) -> dict[str, Any]:
        response = await self.client.request_async(
            "dispatch.claim",
            {"worker_id": worker_id, "limit": limit},
        )
        return response.get("data", response)

    async def complete(
        self,
        item_id: str,
        worker_id: str,
        results: Sequence[Mapping[str, Any]],
        *,
        reason: str = "",
    ) -> dict[str, Any]:
        response = await self.client.request_async(
            "dispatch.complete",
            {
                "item_id": item_id,
                "worker_id": worker_id,
                "recipient_results": [dict(item) for item in results],
                "reason": reason,
            },
        )
        return response.get("data", response)

    async def record_delivery(self, event: Mapping[str, Any]) -> dict[str, Any]:
        event_data = dict(event)
        try:
            response = await self.client.request_async(
                "delivery.record",
                event_data,
            )
            data = response.get("data", response)
            if (
                response.get("ok") is True
                and isinstance(data, Mapping)
                and data.get("ok") is True
            ):
                return dict(data)
            spool_path = self.spool.enqueue(event_data)
            return {
                "ok": False,
                "spooled": True,
                "event_id": str(
                    event_data.get("event_id") or spool_path.stem
                ),
                "error": response.get("error")
                or (
                    data.get("error")
                    if isinstance(data, Mapping)
                    else "dispatcher rejected event"
                ),
            }
        except HistoryDispatcherError:
            spool_path = self.spool.enqueue(event_data)
            return {
                "ok": False,
                "spooled": True,
                "event_id": str(
                    event_data.get("event_id") or spool_path.stem
                ),
            }

    async def flush_spool(self) -> dict[str, int]:
        with self.spool.flush_lock():
            delivered = failed = 0
            for path, event in self.spool.events():
                try:
                    response = await self.client.request_async(
                        "delivery.record",
                        event,
                    )
                    data = response.get("data", response)
                    succeeded = (
                        response.get("ok") is True
                        and isinstance(data, Mapping)
                        and data.get("ok") is True
                    )
                    if succeeded:
                        self.spool.discard(path)
                        delivered += 1
                    else:
                        failed += 1
                except HistoryDispatcherError:
                    failed += 1
                    break
            return {"delivered": delivered, "failed": failed}

    async def claim_provider_v2(
        self,
        worker_id: str,
        *,
        limit: int = 20,
        lease_seconds: int = 120,
        request_id: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized_worker = _opaque_ref(worker_id, field="worker_id")
        response = await self.client.request_async(
            "provider.v2.claim",
            {
                "target_id": "telegram",
                "provider_id": "teebotus",
                "worker_id": normalized_worker,
                "capability_version": TEEBOTUS_CAPABILITY_V2,
                "limit": max(1, min(int(limit), 100)),
                "lease_seconds": max(10, min(int(lease_seconds), 1800)),
            },
            request_id=_request_id(request_id),
        )
        data = _provider_response_data(
            response,
            operation="provider.v2.claim",
        )
        if data.get("schema_version") != PROVIDER_API_SCHEMA_VERSION:
            raise HistoryDispatcherProtocolError(
                "History-Dispatcher provider claim schema mismatch"
            )
        raw_claims = data.get("claims")
        if not isinstance(raw_claims, list):
            raise HistoryDispatcherProtocolError(
                "History-Dispatcher provider claim returned invalid claims"
            )
        claims: list[dict[str, Any]] = []
        seen_targets: set[str] = set()
        for index, raw_claim in enumerate(raw_claims):
            if not isinstance(raw_claim, Mapping):
                raise HistoryDispatcherProtocolError(
                    f"provider claim at index {index} is not an object"
                )
            claim = dict(raw_claim)
            target_delivery_id = _opaque_ref(
                claim.get("target_delivery_id"),
                field="target_delivery_id",
            )
            if target_delivery_id in seen_targets:
                raise HistoryDispatcherProtocolError(
                    "provider claim returned duplicate target delivery"
                )
            seen_targets.add(target_delivery_id)
            if claim.get("target_id") != "telegram":
                raise HistoryDispatcherProtocolError(
                    "provider claim target mismatch"
                )
            if claim.get("provider_id") != "teebotus":
                raise HistoryDispatcherProtocolError(
                    "provider claim provider mismatch"
                )
            if claim.get("capability_version") != TEEBOTUS_CAPABILITY_V2:
                raise HistoryDispatcherProtocolError(
                    "provider claim capability mismatch"
                )
            if claim.get("worker_id") != normalized_worker:
                raise HistoryDispatcherProtocolError(
                    "provider claim worker mismatch"
                )
            binding = claim.get("binding")
            if not isinstance(binding, Mapping):
                raise HistoryDispatcherProtocolError(
                    "provider claim binding is invalid"
                )
            if (
                binding.get("provider") != "teebotus"
                or binding.get("bridge_capability")
                != TEEBOTUS_CAPABILITY_V2
            ):
                raise HistoryDispatcherProtocolError(
                    "provider claim binding mismatch"
                )
            claim["claim_token"] = _claim_token(
                claim.get("claim_token")
            )
            if not isinstance(claim.get("payload"), Mapping):
                raise HistoryDispatcherProtocolError(
                    "provider claim payload is invalid"
                )
            claim["payload"] = dict(claim["payload"])
            claim["successful_recipient_refs"] = _recipient_refs(
                claim.get("successful_recipient_refs"),
                field="successful_recipient_refs",
            )
            claim["open_recipient_refs"] = _recipient_refs(
                claim.get("open_recipient_refs"),
                field="open_recipient_refs",
            )
            claims.append(claim)
        return claims

    async def renew_provider_v2_claim(
        self,
        *,
        target_delivery_id: str,
        worker_id: str,
        claim_token: str,
        lease_seconds: int = 120,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        response = await self.client.request_async(
            "provider.v2.renew",
            {
                "target_delivery_id": _opaque_ref(
                    target_delivery_id,
                    field="target_delivery_id",
                ),
                "worker_id": _opaque_ref(worker_id, field="worker_id"),
                "claim_token": _claim_token(claim_token),
                "lease_seconds": max(10, min(int(lease_seconds), 1800)),
            },
            request_id=_request_id(request_id),
        )
        return _provider_response_data(
            response,
            operation="provider.v2.renew",
        )

    async def _provider_callback(
        self,
        operation: str,
        body: Mapping[str, Any],
        *,
        request_id: str | None,
    ) -> dict[str, Any]:
        normalized_request_id = _request_id(request_id)
        normalized_body = dict(body)
        try:
            response = await self.client.request_async(
                operation,
                normalized_body,
                request_id=normalized_request_id,
            )
            return _provider_response_data(response, operation=operation)
        except HistoryDispatcherError as exc:
            if self.provider_spool is None:
                raise
            path = self.provider_spool.enqueue(
                {
                    "operation": operation,
                    "request_id": normalized_request_id,
                    "body": normalized_body,
                }
            )
            return {
                "ok": False,
                "spooled": True,
                "event_id": path.stem,
                "error": str(exc)[:240],
            }

    async def register_provider_v2_recipients(
        self,
        *,
        target_delivery_id: str,
        worker_id: str,
        claim_token: str,
        recipient_refs: Sequence[str],
        request_id: str | None = None,
    ) -> dict[str, Any]:
        normalized_refs = [
            _opaque_ref(value, field="recipient_ref")
            for value in recipient_refs
        ]
        if not normalized_refs or len(normalized_refs) > 32:
            raise HistoryDispatcherProtocolError(
                "recipient_refs count is invalid"
            )
        if len(normalized_refs) != len(set(normalized_refs)):
            raise HistoryDispatcherProtocolError(
                "recipient_refs contains duplicates"
            )
        return await self._provider_callback(
            "provider.v2.register_recipients",
            {
                "target_delivery_id": _opaque_ref(
                    target_delivery_id,
                    field="target_delivery_id",
                ),
                "worker_id": _opaque_ref(worker_id, field="worker_id"),
                "claim_token": _claim_token(claim_token),
                "recipient_refs": normalized_refs,
            },
            request_id=request_id,
        )

    async def record_provider_v2_recipients(
        self,
        *,
        target_delivery_id: str,
        worker_id: str,
        claim_token: str,
        outcomes: Sequence[Mapping[str, Any]],
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if not outcomes or len(outcomes) > 32:
            raise HistoryDispatcherProtocolError("outcomes count is invalid")
        normalized_outcomes: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in outcomes:
            if not isinstance(raw, Mapping):
                raise HistoryDispatcherProtocolError(
                    "recipient outcome must be an object"
                )
            outcome = dict(raw)
            recipient_ref = _opaque_ref(
                outcome.get("recipient_ref"),
                field="recipient_ref",
            )
            if recipient_ref in seen:
                raise HistoryDispatcherProtocolError(
                    "duplicate recipient outcome"
                )
            seen.add(recipient_ref)
            outcome["recipient_ref"] = recipient_ref
            normalized_outcomes.append(outcome)
        return await self._provider_callback(
            "provider.v2.record_recipients",
            {
                "target_delivery_id": _opaque_ref(
                    target_delivery_id,
                    field="target_delivery_id",
                ),
                "worker_id": _opaque_ref(worker_id, field="worker_id"),
                "claim_token": _claim_token(claim_token),
                "outcomes": normalized_outcomes,
            },
            request_id=request_id,
        )

    async def complete_provider_v2_claim(
        self,
        *,
        target_delivery_id: str,
        worker_id: str,
        claim_token: str,
        request_id: str | None = None,
        outcome: str | None = None,
        error_class: str = "",
        retry_after_seconds: int = 0,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "target_delivery_id": _opaque_ref(
                target_delivery_id,
                field="target_delivery_id",
            ),
            "worker_id": _opaque_ref(worker_id, field="worker_id"),
            "claim_token": _claim_token(claim_token),
            "retry_after_seconds": max(
                0,
                min(int(retry_after_seconds), 604800),
            ),
        }
        if outcome is not None:
            body["outcome"] = str(outcome).strip().casefold()
        if error_class:
            body["error_class"] = str(error_class).strip().casefold()
        return await self._provider_callback(
            "provider.v2.complete",
            body,
            request_id=request_id,
        )

    async def heartbeat_provider_v2(
        self,
        *,
        worker_id: str,
        state: str,
        details: Mapping[str, Any] | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        response = await self.client.request_async(
            "provider.v2.heartbeat",
            {
                "worker_id": _opaque_ref(worker_id, field="worker_id"),
                "target_id": "telegram",
                "provider_id": "teebotus",
                "capability_version": TEEBOTUS_CAPABILITY_V2,
                "state": _opaque_ref(state, field="state"),
                "details": dict(details or {}),
            },
            request_id=_request_id(request_id),
        )
        return _provider_response_data(
            response,
            operation="provider.v2.heartbeat",
        )

    async def flush_provider_v2_spool(self) -> dict[str, int]:
        if self.provider_spool is None:
            return {"delivered": 0, "failed": 0}
        with self.provider_spool.flush_lock():
            delivered = failed = 0
            for path, envelope in self.provider_spool.events():
                try:
                    response = await self.client.request_async(
                        str(envelope["operation"]),
                        dict(envelope["body"]),
                        request_id=str(envelope["request_id"]),
                    )
                    _provider_response_data(
                        response,
                        operation=str(envelope["operation"]),
                    )
                except HistoryDispatcherError:
                    failed += 1
                    break
                self.provider_spool.discard(path)
                delivered += 1
            return {"delivered": delivered, "failed": failed}
