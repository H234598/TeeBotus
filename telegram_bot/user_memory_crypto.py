from __future__ import annotations

import base64
import json
import os
import secrets
import stat
import tempfile
import uuid
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

USER_MEMORY_ENCRYPTION_MAGIC = "TMBMEM1"
USER_MEMORY_ENCRYPTION_VERSION = 1
USER_MEMORY_ENCRYPTION_ALGORITHM = "AES-256-GCM"
USER_MEMORY_KEY_FILENAME = "User_Memory_Key.bin"
USER_MEMORY_KEY_SIZE_BYTES = 32
USER_MEMORY_NONCE_SIZE_BYTES = 12


class UserMemoryCryptoError(RuntimeError):
    pass


def ensure_user_memory_key(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        key = path.read_bytes()
        if len(key) != USER_MEMORY_KEY_SIZE_BYTES:
            raise UserMemoryCryptoError("user memory key has invalid length")
        return key

    key = secrets.token_bytes(USER_MEMORY_KEY_SIZE_BYTES)
    _write_private_bytes(path, key)
    return key


def is_encrypted_payload(payload: bytes) -> bool:
    if not isinstance(payload, bytes) or not payload.lstrip().startswith(b"{"):
        return False
    try:
        envelope = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(envelope, dict)
        and envelope.get("magic") == USER_MEMORY_ENCRYPTION_MAGIC
        and envelope.get("version") == USER_MEMORY_ENCRYPTION_VERSION
        and isinstance(envelope.get("ciphertext"), str)
    )


def encrypt_bytes(payload: bytes, key: bytes, *, kind: str) -> bytes:
    if not isinstance(payload, bytes):
        raise UserMemoryCryptoError("user memory payload must be bytes")
    if len(key) != USER_MEMORY_KEY_SIZE_BYTES:
        raise UserMemoryCryptoError("user memory key has invalid length")
    nonce = secrets.token_bytes(USER_MEMORY_NONCE_SIZE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, payload, _aad(kind))
    envelope = {
        "magic": USER_MEMORY_ENCRYPTION_MAGIC,
        "version": USER_MEMORY_ENCRYPTION_VERSION,
        "algorithm": USER_MEMORY_ENCRYPTION_ALGORITHM,
        "kind": _normalize_kind(kind),
        "nonce": base64.urlsafe_b64encode(nonce).decode("ascii"),
        "ciphertext": base64.urlsafe_b64encode(ciphertext).decode("ascii"),
    }
    return json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"


def decrypt_bytes(payload: bytes, key: bytes, *, kind: str, require_encrypted: bool = True) -> bytes:
    if not isinstance(payload, bytes):
        raise UserMemoryCryptoError("user memory payload must be bytes")
    if len(key) != USER_MEMORY_KEY_SIZE_BYTES:
        raise UserMemoryCryptoError("user memory key has invalid length")
    if not is_encrypted_payload(payload):
        if require_encrypted:
            raise UserMemoryCryptoError("user memory envelope is missing")
        return payload

    try:
        envelope = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UserMemoryCryptoError("user memory envelope is malformed") from exc
    if not isinstance(envelope, dict):
        raise UserMemoryCryptoError("user memory envelope must be an object")
    if envelope.get("magic") != USER_MEMORY_ENCRYPTION_MAGIC or envelope.get("version") != USER_MEMORY_ENCRYPTION_VERSION:
        raise UserMemoryCryptoError("user memory envelope version is unsupported")
    if envelope.get("algorithm") != USER_MEMORY_ENCRYPTION_ALGORITHM:
        raise UserMemoryCryptoError("user memory algorithm is unsupported")
    if envelope.get("kind") != _normalize_kind(kind):
        raise UserMemoryCryptoError("user memory kind does not match the requested use")

    try:
        nonce = base64.urlsafe_b64decode(str(envelope.get("nonce", "")).encode("ascii"))
        ciphertext = base64.urlsafe_b64decode(str(envelope.get("ciphertext", "")).encode("ascii"))
    except Exception as exc:
        raise UserMemoryCryptoError("user memory envelope fields are invalid") from exc
    if len(nonce) != USER_MEMORY_NONCE_SIZE_BYTES:
        raise UserMemoryCryptoError("user memory nonce has invalid length")

    try:
        return AESGCM(key).decrypt(nonce, ciphertext, _aad(kind))
    except InvalidTag as exc:
        raise UserMemoryCryptoError("user memory authentication failed") from exc


def read_text(path: Path, key: bytes, *, kind: str) -> tuple[str, bool]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return "", False
    if not raw:
        return "", True
    if is_encrypted_payload(raw):
        return decrypt_bytes(raw, key, kind=kind).decode("utf-8"), False
    return raw.decode("utf-8", errors="replace"), True


def write_text(path: Path, key: bytes, *, kind: str, text: str) -> None:
    payload = str(text or "").encode("utf-8")
    _write_private_bytes(path, encrypt_bytes(payload, key, kind=kind))


def read_json(path: Path, key: bytes, *, kind: str, default: dict[str, object]) -> tuple[dict[str, object], bool]:
    text, migrated = read_text(path, key, kind=kind)
    if not text.strip():
        return dict(default), migrated
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise UserMemoryCryptoError(f"user memory JSON for {path} is invalid") from exc
    if not isinstance(data, dict):
        raise UserMemoryCryptoError(f"user memory JSON for {path} must be an object")
    return data, migrated


def write_json(path: Path, key: bytes, *, kind: str, data: dict[str, object]) -> None:
    payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    _write_private_bytes(path, encrypt_bytes(payload, key, kind=kind))


def read_jsonl(path: Path, key: bytes, *, kind: str) -> tuple[list[dict[str, object]], bool]:
    text, migrated = read_text(path, key, kind=kind)
    if not text.strip():
        return [], migrated
    entries: list[dict[str, object]] = []
    stripped = text.strip()
    if stripped.startswith("["):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise UserMemoryCryptoError(f"user memory JSONL for {path} is invalid") from exc
        if not isinstance(payload, list):
            raise UserMemoryCryptoError(f"user memory JSONL for {path} must be a list or JSONL text")
        for entry in payload:
            if isinstance(entry, dict):
                entries.append(entry)
        return entries, migrated
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise UserMemoryCryptoError(f"user memory JSONL for {path} is invalid") from exc
        if not isinstance(payload, dict):
            raise UserMemoryCryptoError(f"user memory JSONL for {path} must contain objects")
        entries.append(payload)
    return entries, migrated


def write_jsonl(path: Path, key: bytes, *, kind: str, entries: list[dict[str, object]]) -> None:
    text = "\n".join(json.dumps(entry, ensure_ascii=False, sort_keys=True) for entry in entries)
    if text:
        text += "\n"
    _write_private_bytes(path, encrypt_bytes(text.encode("utf-8"), key, kind=kind))


def _aad(kind: str) -> bytes:
    return f"telegram-bot:{_normalize_kind(kind)}:v{USER_MEMORY_ENCRYPTION_VERSION}".encode("utf-8")


def _normalize_kind(kind: str) -> str:
    value = str(kind or "").strip().casefold()
    if not value:
        raise UserMemoryCryptoError("user memory kind must not be empty")
    return value


def _write_private_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=f".{uuid.uuid4().hex}.tmp", dir=str(path.parent))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
