from __future__ import annotations

import base64
import json
import os
import secrets
import shutil
import subprocess
import stat
import tempfile
import uuid
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

USER_MEMORY_ENCRYPTION_MAGIC = "TMBMEM1"
USER_MEMORY_ENCRYPTION_VERSION = 1
USER_MEMORY_ENCRYPTION_ALGORITHM = "AES-256-GCM"
USER_MEMORY_KEY_FILENAME = "User_Memory_Key.bin"
USER_MEMORY_KEY_BACKEND_ENV = "TELEGRAM_BOT_USER_MEMORY_KEY_BACKEND"
USER_MEMORY_KEY_BACKEND_KEYRING = "keyring"
USER_MEMORY_KEY_BACKEND_PASSPHRASE = "passphrase"
USER_MEMORY_PASSPHRASE_ENV = "TELEGRAM_BOT_USER_MEMORY_PASSPHRASE"
USER_MEMORY_PASSPHRASE_FILE_ENV = "TELEGRAM_BOT_USER_MEMORY_PASSPHRASE_FILE"
USER_MEMORY_PASSPHRASE_FILENAME = "User_Memory_Passphrase.key"
USER_MEMORY_PASSPHRASE_MAGIC = "TMBKEY1"
USER_MEMORY_PASSPHRASE_VERSION = 1
USER_MEMORY_PASSPHRASE_ALGORITHM = "AES-256-GCM+SCRYPT"
USER_MEMORY_PASSPHRASE_SALT_SIZE_BYTES = 16
USER_MEMORY_PASSPHRASE_NONCE_SIZE_BYTES = 12
USER_MEMORY_PASSPHRASE_SCRYPT_N = 2**15
USER_MEMORY_PASSPHRASE_SCRYPT_R = 8
USER_MEMORY_PASSPHRASE_SCRYPT_P = 1
MAX_PASSPHRASE_CHARS = 4096
MAX_PASSPHRASE_FILE_BYTES = 16 * 1024
MAX_PASSPHRASE_FILE_PATH_CHARS = 4096
MIN_PASSPHRASE_CHARS = 32
MIN_PASSPHRASE_DISTINCT_CHARS = 8
USER_MEMORY_KEY_SERVICE = "telegram-bot"
USER_MEMORY_KEY_PURPOSE = "user-memory-key"
USER_MEMORY_KEY_LABEL_PREFIX = "Telegram user memory key"
USER_MEMORY_KEY_SIZE_BYTES = 32
USER_MEMORY_NONCE_SIZE_BYTES = 12
SECRET_TOOL_COMMAND = "secret-tool"


class UserMemoryCryptoError(RuntimeError):
    pass


def ensure_user_memory_key(path: Path, *, instance_name: str = "", sender_id: str = "") -> bytes:
    scope = _resolve_keyring_scope(path, instance_name=instance_name, sender_id=sender_id)
    backend = _resolve_user_memory_key_backend()
    if backend == USER_MEMORY_KEY_BACKEND_KEYRING:
        return _ensure_user_memory_key_keyring(path, scope)
    if backend == USER_MEMORY_KEY_BACKEND_PASSPHRASE:
        return _ensure_user_memory_key_passphrase(path, scope)
    raise UserMemoryCryptoError(f"unsupported user memory key backend: {backend}")


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


def _resolve_keyring_scope(path: Path, *, instance_name: str, sender_id: str) -> tuple[str, str]:
    resolved_sender_id = _normalize_keyring_token(sender_id or path.parent.name, field_name="sender id")
    resolved_instance_name = _normalize_keyring_token(instance_name or _infer_instance_name(path), field_name="instance name")
    return resolved_instance_name, resolved_sender_id


def _infer_instance_name(path: Path) -> str:
    parts = list(path.parts)
    if "instances" in parts:
        index = parts.index("instances")
        if index + 1 < len(parts):
            return parts[index + 1]
    return ""


def _legacy_key_path(path: Path) -> Path:
    if path.name == USER_MEMORY_KEY_FILENAME:
        return path
    return path.parent / USER_MEMORY_KEY_FILENAME


def _normalize_keyring_token(value: str, *, field_name: str) -> str:
    token = str(value or "").strip()
    if not token:
        raise UserMemoryCryptoError(f"user memory {field_name} must not be empty")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in token):
        raise UserMemoryCryptoError(f"user memory {field_name} contains invalid control characters")
    return token


def _keyring_attributes(instance_name: str, sender_id: str) -> list[str]:
    return [
        "application",
        USER_MEMORY_KEY_SERVICE,
        "purpose",
        USER_MEMORY_KEY_PURPOSE,
        "instance",
        instance_name,
        "sender_id",
        sender_id,
    ]


def _keyring_label(instance_name: str, sender_id: str) -> str:
    return f"{USER_MEMORY_KEY_LABEL_PREFIX}: instance={instance_name}, sender_id={sender_id}"


def _secret_tool_path() -> str:
    binary = shutil.which(SECRET_TOOL_COMMAND)
    if binary is None:
        raise UserMemoryCryptoError("secret-tool is not installed")
    return binary


def _run_secret_tool(args: list[str], *, input_text: str = "") -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [_secret_tool_path(), *args],
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise UserMemoryCryptoError("secret-tool could not be started") from exc


def _lookup_keyring_key(scope: tuple[str, str]) -> bytes | None:
    instance_name, sender_id = scope
    result = _run_secret_tool(["lookup", *_keyring_attributes(instance_name, sender_id)])
    if result.returncode != 0:
        return None
    secret = result.stdout.strip()
    if not secret:
        return None
    try:
        key = base64.urlsafe_b64decode(secret.encode("ascii"))
    except Exception as exc:
        raise UserMemoryCryptoError("secret-tool returned invalid user memory key data") from exc
    if len(key) != USER_MEMORY_KEY_SIZE_BYTES:
        raise UserMemoryCryptoError("user memory key has invalid length")
    return key


def _store_keyring_key(scope: tuple[str, str], key: bytes) -> None:
    if len(key) != USER_MEMORY_KEY_SIZE_BYTES:
        raise UserMemoryCryptoError("user memory key has invalid length")
    instance_name, sender_id = scope
    result = _run_secret_tool(
        ["store", "--label", _keyring_label(instance_name, sender_id), *_keyring_attributes(instance_name, sender_id)],
        input_text=base64.urlsafe_b64encode(key).decode("ascii") + "\n",
    )
    if result.returncode != 0:
        raise UserMemoryCryptoError("secret-tool could not store the user memory key")


def _confirm_keyring_key(scope: tuple[str, str], expected_key: bytes) -> None:
    confirmed_key = _lookup_keyring_key(scope)
    if confirmed_key != expected_key:
        raise UserMemoryCryptoError("secret-tool did not return the stored user memory key")


def _clear_keyring_key(scope: tuple[str, str]) -> None:
    instance_name, sender_id = scope
    result = _run_secret_tool(["clear", *_keyring_attributes(instance_name, sender_id)])
    if result.returncode != 0:
        return


def _unlink_legacy_key_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise UserMemoryCryptoError("legacy user memory key file could not be removed") from exc


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


def _ensure_user_memory_key_keyring(path: Path, scope: tuple[str, str]) -> bytes:
    try:
        existing = _lookup_keyring_key(scope)
    except UserMemoryCryptoError:
        existing = None
    if existing is not None:
        return existing

    legacy_path = _legacy_key_path(path)
    if legacy_path.exists():
        payload = legacy_path.read_bytes()
        if len(payload) == USER_MEMORY_KEY_SIZE_BYTES:
            key = payload
            if _try_store_keyring_key(scope, key):
                _unlink_legacy_key_file(legacy_path)
            else:
                _write_passphrase_protected_key(legacy_path, key, _resolve_user_memory_passphrase(path))
            return key
        if _is_passphrase_encrypted_key_payload(payload):
            key = _decrypt_passphrase_protected_key(path, payload)
            if _try_store_keyring_key(scope, key):
                _unlink_legacy_key_file(legacy_path)
            return key
        raise UserMemoryCryptoError("user memory key file has invalid contents")

    key = secrets.token_bytes(USER_MEMORY_KEY_SIZE_BYTES)
    if not _try_store_keyring_key(scope, key):
        _write_passphrase_protected_key(legacy_path, key, _resolve_user_memory_passphrase(path))
    return key


def _try_store_keyring_key(scope: tuple[str, str], key: bytes) -> bool:
    try:
        _store_keyring_key(scope, key)
        _confirm_keyring_key(scope, key)
    except UserMemoryCryptoError:
        return False
    return True


def _ensure_user_memory_key_passphrase(path: Path, scope: tuple[str, str]) -> bytes:
    payload_path = _legacy_key_path(path)
    passphrase = _resolve_user_memory_passphrase(path)

    if payload_path.exists():
        payload = payload_path.read_bytes()
        if len(payload) == USER_MEMORY_KEY_SIZE_BYTES:
            key = payload
            _write_passphrase_protected_key(payload_path, key, passphrase)
            _clear_keyring_key(scope)
            return key
        if _is_passphrase_encrypted_key_payload(payload):
            key = _decrypt_passphrase_protected_key(path, payload, passphrase=passphrase)
            _write_passphrase_protected_key(payload_path, key, passphrase)
            _clear_keyring_key(scope)
            return key
        raise UserMemoryCryptoError("user memory key file has invalid contents")

    try:
        existing = _lookup_keyring_key(scope)
    except UserMemoryCryptoError:
        existing = None
    if existing is not None:
        _write_passphrase_protected_key(payload_path, existing, passphrase)
        _clear_keyring_key(scope)
        return existing

    key = secrets.token_bytes(USER_MEMORY_KEY_SIZE_BYTES)
    _write_passphrase_protected_key(payload_path, key, passphrase)
    return key


def _resolve_user_memory_key_backend() -> str:
    value = os.environ.get(USER_MEMORY_KEY_BACKEND_ENV, USER_MEMORY_KEY_BACKEND_KEYRING)
    normalized = str(value or "").strip().casefold().replace("_", "-")
    aliases = {
        "": USER_MEMORY_KEY_BACKEND_KEYRING,
        "keyring": USER_MEMORY_KEY_BACKEND_KEYRING,
        "secret-service": USER_MEMORY_KEY_BACKEND_KEYRING,
        "secretservice": USER_MEMORY_KEY_BACKEND_KEYRING,
        "pass": USER_MEMORY_KEY_BACKEND_PASSPHRASE,
        "password": USER_MEMORY_KEY_BACKEND_PASSPHRASE,
        "passphrase": USER_MEMORY_KEY_BACKEND_PASSPHRASE,
    }
    try:
        return aliases[normalized]
    except KeyError as exc:
        raise UserMemoryCryptoError(
            f"unsupported user memory key backend: {value}; choose one of: {USER_MEMORY_KEY_BACKEND_KEYRING}, {USER_MEMORY_KEY_BACKEND_PASSPHRASE}"
        ) from exc


def _resolve_user_memory_passphrase(path: Path) -> str:
    explicit_env = os.environ.get(USER_MEMORY_PASSPHRASE_ENV)
    if explicit_env is not None and explicit_env.strip():
        return _normalize_passphrase(explicit_env, source="environment")

    explicit_file = os.environ.get(USER_MEMORY_PASSPHRASE_FILE_ENV)
    if explicit_file is not None and explicit_file.strip():
        return _load_or_create_passphrase_file(Path(explicit_file.strip()), source="explicit file")

    return _load_or_create_default_passphrase(path)


def _load_or_create_default_passphrase(path: Path) -> str:
    passphrase_path = _default_passphrase_file(path)
    return _load_or_create_passphrase_file(passphrase_path, source="default file")


def _load_or_create_passphrase_file(path: Path, *, source: str) -> str:
    if not path.is_absolute():
        raise UserMemoryCryptoError("user memory passphrase file path must be absolute")
    if len(str(path)) > MAX_PASSPHRASE_FILE_PATH_CHARS:
        raise UserMemoryCryptoError("user memory passphrase file path is too large")
    if path.exists():
        return _load_passphrase_file(path, source=source)
    passphrase = _new_generated_passphrase()
    _write_passphrase_file(path, passphrase)
    return passphrase


def _default_passphrase_file(path: Path) -> Path:
    instance_data_dir = _instance_data_dir_for_memory_path(path)
    return instance_data_dir / USER_MEMORY_PASSPHRASE_FILENAME


def _instance_data_dir_for_memory_path(path: Path) -> Path:
    parts = list(path.parts)
    if "users" in parts:
        index = parts.index("users")
        if index >= 1:
            return Path(*parts[:index])
    return path.parent


def _load_passphrase_file(path: Path, *, source: str) -> str:
    if not path.is_absolute():
        raise UserMemoryCryptoError("user memory passphrase file path must be absolute")
    if len(str(path)) > MAX_PASSPHRASE_FILE_PATH_CHARS:
        raise UserMemoryCryptoError("user memory passphrase file path is too large")
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise UserMemoryCryptoError(f"user memory passphrase file does not exist: {path}") from exc
    except OSError as exc:
        raise UserMemoryCryptoError("user memory passphrase file could not be read") from exc
    if len(raw) > MAX_PASSPHRASE_FILE_BYTES:
        raise UserMemoryCryptoError("user memory passphrase file is too large")
    _ensure_private_file(path, field_name="user memory passphrase file")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UserMemoryCryptoError("user memory passphrase file must be valid UTF-8") from exc
    return _normalize_passphrase(text.strip(), source=source)


def _normalize_passphrase(value: str, *, source: str) -> str:
    if not isinstance(value, str):
        raise UserMemoryCryptoError("user memory passphrase must be text")
    passphrase = value.strip()
    if _contains_forbidden_chars(passphrase):
        raise UserMemoryCryptoError(f"user memory passphrase from {source} contains invalid control characters")
    if not passphrase:
        raise UserMemoryCryptoError(f"user memory passphrase from {source} must not be empty")
    if _decoded_generated_passphrase_bytes(passphrase) is not None:
        return passphrase
    if len(passphrase) < MIN_PASSPHRASE_CHARS or len(set(passphrase)) < MIN_PASSPHRASE_DISTINCT_CHARS:
        raise UserMemoryCryptoError(f"user memory passphrase from {source} is not strong enough")
    if len(passphrase.encode("utf-8")) > MAX_PASSPHRASE_CHARS:
        raise UserMemoryCryptoError(f"user memory passphrase from {source} is too large")
    return passphrase


def _new_generated_passphrase() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(USER_MEMORY_KEY_SIZE_BYTES)).decode("ascii")


def _decoded_generated_passphrase_bytes(value: str) -> bytes | None:
    try:
        decoded = base64.urlsafe_b64decode(value.encode("ascii"))
    except Exception:
        return None
    if len(decoded) < USER_MEMORY_KEY_SIZE_BYTES:
        return None
    if len(set(decoded)) < MIN_PASSPHRASE_DISTINCT_CHARS:
        return None
    return decoded


def _write_passphrase_file(path: Path, passphrase: str) -> None:
    _write_private_bytes(path, (passphrase.strip() + "\n").encode("utf-8"))


def _ensure_private_file(path: Path, *, field_name: str) -> None:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError as exc:
        raise UserMemoryCryptoError(f"{field_name} does not exist") from exc
    except OSError as exc:
        raise UserMemoryCryptoError(f"{field_name} could not be inspected") from exc
    if mode & 0o077:
        raise UserMemoryCryptoError(f"{field_name} must be private")


def _write_passphrase_protected_key(path: Path, key: bytes, passphrase: str) -> None:
    if len(key) != USER_MEMORY_KEY_SIZE_BYTES:
        raise UserMemoryCryptoError("user memory key has invalid length")
    payload = _encrypt_user_memory_key_with_passphrase(key, passphrase)
    _write_private_bytes(path, payload)


def _decrypt_passphrase_protected_key(path: Path, payload: bytes, *, passphrase: str | None = None) -> bytes:
    if passphrase is None:
        passphrase = _resolve_user_memory_passphrase(path)
    key = _decrypt_user_memory_key_with_passphrase(payload, passphrase)
    if len(key) != USER_MEMORY_KEY_SIZE_BYTES:
        raise UserMemoryCryptoError("user memory key has invalid length")
    return key


def _encrypt_user_memory_key_with_passphrase(key: bytes, passphrase: str) -> bytes:
    if len(key) != USER_MEMORY_KEY_SIZE_BYTES:
        raise UserMemoryCryptoError("user memory key has invalid length")
    normalized_passphrase = _normalize_passphrase(passphrase, source="passphrase")
    salt = secrets.token_bytes(USER_MEMORY_PASSPHRASE_SALT_SIZE_BYTES)
    nonce = secrets.token_bytes(USER_MEMORY_PASSPHRASE_NONCE_SIZE_BYTES)
    wrapping_key = _derive_passphrase_key(normalized_passphrase, salt)
    ciphertext = AESGCM(wrapping_key).encrypt(nonce, key, _passphrase_aad())
    envelope = {
        "magic": USER_MEMORY_PASSPHRASE_MAGIC,
        "version": USER_MEMORY_PASSPHRASE_VERSION,
        "algorithm": USER_MEMORY_PASSPHRASE_ALGORITHM,
        "salt": base64.urlsafe_b64encode(salt).decode("ascii"),
        "nonce": base64.urlsafe_b64encode(nonce).decode("ascii"),
        "ciphertext": base64.urlsafe_b64encode(ciphertext).decode("ascii"),
    }
    return json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"


def _decrypt_user_memory_key_with_passphrase(payload: bytes, passphrase: str) -> bytes:
    if not _is_passphrase_encrypted_key_payload(payload):
        if len(payload) == USER_MEMORY_KEY_SIZE_BYTES:
            return payload
        raise UserMemoryCryptoError("user memory key file has invalid contents")
    try:
        envelope = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UserMemoryCryptoError("user memory key file is malformed") from exc
    if not isinstance(envelope, dict):
        raise UserMemoryCryptoError("user memory key file must be an object")
    if envelope.get("magic") != USER_MEMORY_PASSPHRASE_MAGIC or envelope.get("version") != USER_MEMORY_PASSPHRASE_VERSION:
        raise UserMemoryCryptoError("user memory key file version is unsupported")
    if envelope.get("algorithm") != USER_MEMORY_PASSPHRASE_ALGORITHM:
        raise UserMemoryCryptoError("user memory key algorithm is unsupported")
    try:
        salt = base64.urlsafe_b64decode(str(envelope.get("salt", "")).encode("ascii"))
        nonce = base64.urlsafe_b64decode(str(envelope.get("nonce", "")).encode("ascii"))
        ciphertext = base64.urlsafe_b64decode(str(envelope.get("ciphertext", "")).encode("ascii"))
    except Exception as exc:
        raise UserMemoryCryptoError("user memory key file fields are invalid") from exc
    if len(salt) != USER_MEMORY_PASSPHRASE_SALT_SIZE_BYTES:
        raise UserMemoryCryptoError("user memory key salt has invalid length")
    if len(nonce) != USER_MEMORY_PASSPHRASE_NONCE_SIZE_BYTES:
        raise UserMemoryCryptoError("user memory key nonce has invalid length")
    normalized_passphrase = _normalize_passphrase(passphrase, source="passphrase")
    wrapping_key = _derive_passphrase_key(normalized_passphrase, salt)
    try:
        key = AESGCM(wrapping_key).decrypt(nonce, ciphertext, _passphrase_aad())
    except InvalidTag as exc:
        raise UserMemoryCryptoError("user memory key authentication failed") from exc
    if len(key) != USER_MEMORY_KEY_SIZE_BYTES:
        raise UserMemoryCryptoError("user memory key has invalid length")
    return key


def _derive_passphrase_key(passphrase: str, salt: bytes) -> bytes:
    if len(salt) != USER_MEMORY_PASSPHRASE_SALT_SIZE_BYTES:
        raise UserMemoryCryptoError("user memory key salt has invalid length")
    kdf = Scrypt(
        salt=salt,
        length=USER_MEMORY_KEY_SIZE_BYTES,
        n=USER_MEMORY_PASSPHRASE_SCRYPT_N,
        r=USER_MEMORY_PASSPHRASE_SCRYPT_R,
        p=USER_MEMORY_PASSPHRASE_SCRYPT_P,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def _passphrase_aad() -> bytes:
    return f"telegram-bot:user-memory-key:{USER_MEMORY_PASSPHRASE_VERSION}".encode("utf-8")


def _is_passphrase_encrypted_key_payload(payload: bytes) -> bool:
    if not isinstance(payload, bytes) or not payload.lstrip().startswith(b"{"):
        return False
    try:
        envelope = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(envelope, dict)
        and envelope.get("magic") == USER_MEMORY_PASSPHRASE_MAGIC
        and envelope.get("version") == USER_MEMORY_PASSPHRASE_VERSION
        and isinstance(envelope.get("ciphertext"), str)
    )


def _contains_forbidden_chars(value: str) -> bool:
    return any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
