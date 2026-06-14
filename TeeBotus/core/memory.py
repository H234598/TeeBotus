from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import base64
import shutil
import subprocess

from TeeBotus.runtime.accounts import (
    AccountStore,
    AccountStoreError,
    USER_HABITS_FILENAME,
    USER_MEMORY_ENTRIES_FILENAME,
    USER_MEMORY_INDEX_FILENAME,
    telegram_identity_key,
)


@dataclass(frozen=True)
class AccountMemoryService:
    """Encrypted structured account-memory facade.

    Structured memory is stored under the TeeBotus account_id and written through the
    account store's encrypted account-memory vault. The human-maintained habits file
    remains plaintext by design, matching the existing privacy model.
    """

    account_store: AccountStore

    def account_dir(self, account_id: str) -> Path:
        return self.account_store.account_dir(account_id)

    def append_entry(self, account_id: str, entry: dict[str, Any]) -> None:
        self.account_store.append_memory_entry(account_id, dict(entry))

    def read_entries(self, account_id: str) -> list[dict[str, Any]]:
        return self.account_store.read_memory_entries(account_id)

    def read_index(self, account_id: str) -> dict[str, Any]:
        return self.account_store.read_memory_index(account_id)

    def write_index(self, account_id: str, index: dict[str, Any]) -> None:
        self.account_store.write_memory_index(account_id, dict(index))

    def reset_structured_memory(self, account_id: str) -> None:
        self.account_store.reset_structured_memory(account_id)

    def habits_path(self, account_id: str) -> Path:
        path = self.account_dir(account_id) / USER_HABITS_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("", encoding="utf-8")
        return path


@dataclass(frozen=True)
class MigrationResult:
    migrated: bool
    account_id: str
    legacy_path: Path
    target_path: Path
    encrypted_legacy: bool = False
    skipped_reason: str = ""


class LegacyMemoryMigrator:
    """Migrates legacy Telegram-sender memory into account-scoped memory.

    The migrator first loads and decrypts all legacy data into memory before creating
    or modifying an AccountStore entry. That prevents a failed encrypted legacy read
    from leaving behind an empty account mapping or partially migrated account.
    """

    def __init__(self, account_store: AccountStore, instance_dir: Path) -> None:
        self.account_store = account_store
        self.instance_dir = Path(instance_dir)

    def migrate_telegram_sender(self, sender_id: str) -> MigrationResult:
        legacy_path = self.instance_dir / "data" / "users" / str(sender_id)
        if not legacy_path.exists():
            return MigrationResult(False, "", legacy_path, Path(""), skipped_reason="legacy path does not exist")
        try:
            payload = self._load_legacy_payload(sender_id, legacy_path)
        except AccountStoreError as exc:
            return MigrationResult(False, "", legacy_path, Path(""), skipped_reason=str(exc))

        identity = telegram_identity_key(sender_id)
        account_id = self.account_store.resolve_or_create_account(identity)
        target_path = self.account_store.account_dir(account_id)
        self._write_loaded_payload(sender_id, account_id, payload, target_path)
        _safe_rmtree(legacy_path)
        return MigrationResult(True, account_id, legacy_path, target_path, encrypted_legacy=payload["encrypted_legacy"])

    def _load_legacy_payload(self, sender_id: str, legacy_path: Path) -> dict[str, Any]:
        index_path = legacy_path / USER_MEMORY_INDEX_FILENAME
        entries_path = legacy_path / USER_MEMORY_ENTRIES_FILENAME
        habits_path = legacy_path / USER_HABITS_FILENAME
        index_encrypted = _looks_encrypted(index_path)
        entries_encrypted = _looks_encrypted(entries_path)
        encrypted_legacy = bool(index_encrypted or entries_encrypted)
        key = None
        crypto = _legacy_crypto_module()
        if encrypted_legacy:
            if crypto is None:
                raise AccountStoreError("legacy encrypted user memory could not be decrypted: key is missing")
            key_path = legacy_path / getattr(crypto, "USER_MEMORY_KEY_FILENAME", "User_Memory_Key.bin")
            key = _load_existing_legacy_key(
                crypto,
                key_path,
                instance_name=self.account_store.instance_name,
                sender_id=str(sender_id),
            )

        index: dict[str, Any] = {}
        entries: list[dict[str, Any]] = []
        if index_path.exists():
            if index_encrypted:
                try:
                    index, _ = crypto.read_json(index_path, key, kind="index", default={})
                except Exception as exc:  # noqa: BLE001
                    raise AccountStoreError("legacy encrypted user memory index could not be decrypted") from exc
            else:
                index = _read_plain_json(index_path)
        if entries_path.exists():
            if entries_encrypted:
                try:
                    entries, _ = crypto.read_jsonl(entries_path, key, kind="entries")
                except Exception as exc:  # noqa: BLE001
                    raise AccountStoreError("legacy encrypted user memory entries could not be decrypted") from exc
            else:
                entries = _read_plain_jsonl(entries_path)
        habits_text = habits_path.read_text(encoding="utf-8", errors="replace").strip() if habits_path.exists() else ""
        if not index and not entries and not habits_text:
            raise AccountStoreError("no migratable legacy memory files")
        return {"index": index, "entries": entries, "habits_text": habits_text, "encrypted_legacy": encrypted_legacy}

    def _write_loaded_payload(self, sender_id: str, account_id: str, payload: dict[str, Any], target_path: Path) -> None:
        index = payload.get("index") if isinstance(payload.get("index"), dict) else {}
        entries = payload.get("entries") if isinstance(payload.get("entries"), list) else []
        habits_text = str(payload.get("habits_text") or "").strip()
        if index:
            existing_index = self.account_store.read_memory_index(account_id)
            self.account_store.write_memory_index(account_id, {**index, **existing_index})
        if entries:
            existing = self.account_store.read_memory_entries(account_id)
            self.account_store.write_memory_entries(account_id, [*existing, *entries])
        if habits_text:
            self._write_habits_text(sender_id, habits_text, target_path)

    def _write_habits_text(self, sender_id: str, habits_text: str, target_path: Path) -> None:
        target_path.mkdir(parents=True, exist_ok=True)
        target = target_path / USER_HABITS_FILENAME
        if target.exists() and target.read_text(encoding="utf-8", errors="replace").strip():
            existing = target.read_text(encoding="utf-8", errors="replace").rstrip()
            text = f"{existing}\n\n## Migrated from Telegram sender {sender_id}\n\n{habits_text}\n"
        else:
            text = habits_text + "\n"
        target.write_text(text, encoding="utf-8")


def _load_existing_legacy_key(crypto: Any, key_path: Path, *, instance_name: str, sender_id: str) -> bytes:
    """Load an existing legacy user-memory key without creating fresh key state.

    ``user_memory_crypto.ensure_user_memory_key`` may create or migrate key material
    as a side effect. Migration reads must be boring: if the old key cannot be read
    without mutation, the migrator reports a skipped migration and leaves the legacy
    directory untouched.
    """
    if key_path.exists():
        try:
            payload = key_path.read_bytes()
        except OSError as exc:
            raise AccountStoreError("legacy encrypted user memory key could not be read") from exc
        expected_size = int(getattr(crypto, "USER_MEMORY_KEY_SIZE_BYTES", 32))
        if len(payload) == expected_size:
            return payload
        is_passphrase_payload = getattr(crypto, "_is_passphrase_encrypted_key_payload", None)
        decrypt_passphrase_payload = getattr(crypto, "_decrypt_passphrase_protected_key", None)
        if callable(is_passphrase_payload) and callable(decrypt_passphrase_payload):
            try:
                if is_passphrase_payload(payload):
                    return decrypt_passphrase_payload(key_path, payload)
            except Exception as exc:  # noqa: BLE001
                raise AccountStoreError("legacy passphrase-protected user memory key could not be decrypted") from exc
        raise AccountStoreError("legacy encrypted user memory key file has unsupported contents")

    key = _lookup_legacy_keyring_key(crypto, instance_name=instance_name, sender_id=sender_id)
    if key is not None:
        return key
    raise AccountStoreError("legacy encrypted user memory could not be decrypted: key is missing")


def _lookup_legacy_keyring_key(crypto: Any, *, instance_name: str, sender_id: str) -> bytes | None:
    command_name = getattr(crypto, "SECRET_TOOL_COMMAND", "secret-tool")
    binary = shutil.which(command_name)
    if binary is None:
        return None
    service = getattr(crypto, "USER_MEMORY_KEY_SERVICE", "telegram-bot")
    purpose = getattr(crypto, "USER_MEMORY_KEY_PURPOSE", "user-memory-key")
    size = int(getattr(crypto, "USER_MEMORY_KEY_SIZE_BYTES", 32))
    try:
        result = subprocess.run(
            [
                binary,
                "lookup",
                "application",
                service,
                "purpose",
                purpose,
                "instance",
                instance_name,
                "sender_id",
                sender_id,
            ],
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        key = base64.urlsafe_b64decode(result.stdout.strip().encode("ascii"))
    except Exception as exc:  # noqa: BLE001
        raise AccountStoreError("legacy keyring returned invalid user memory key data") from exc
    if len(key) != size:
        raise AccountStoreError("legacy user memory key has invalid length")
    return key


def _legacy_crypto_module():
    try:
        from TeeBotus import user_memory_crypto  # type: ignore
    except Exception:  # pragma: no cover - absent in isolated patch tests
        return None
    return user_memory_crypto


def _looks_encrypted(path: Path) -> bool:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return False
    if not raw.lstrip().startswith(b"{"):
        return False
    try:
        import json

        payload = json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return False
    return (
        isinstance(payload, dict)
        and str(payload.get("magic") or "") in {"TMBMEM1", "TMBMAP1", "TMBKEY1"}
        and isinstance(payload.get("ciphertext"), str)
    )


def _read_plain_json(path: Path) -> dict[str, Any]:
    import json

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise AccountStoreError(f"legacy JSON file could not be read: {path}") from exc
    if not isinstance(payload, dict):
        raise AccountStoreError(f"legacy JSON file must contain an object: {path}")
    return payload


def _read_plain_jsonl(path: Path) -> list[dict[str, Any]]:
    import json

    rows: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        raise AccountStoreError(f"legacy JSONL file could not be read: {path}") from exc
    for line in text.splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _safe_rmtree(path: Path) -> None:
    import shutil

    if path.exists():
        shutil.rmtree(path)
