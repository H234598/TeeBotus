from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

TOKEN_HEX_RE = re.compile(r"^[0-9a-f]{128}$")
ACCOUNT_SCHEMA_VERSION = 1
MAPPING_MAGIC = "TMBMAP1"
MAPPING_VERSION = 1
MAPPING_ALGORITHM = "AES-256-GCM"
TEEBOTUS_ENCRYPTION_MAGICS = {"TMBMAP1", "TMBMEM1", "TMBKEY1"}
ACCOUNT_INDEX_FILENAME = "Account_Index.json"
ACCOUNT_IDENTITIES_FILENAME = "Account_Identities.json"
ACCOUNT_SECRETS_FILENAME = "Account_Secrets.json"
ACCOUNTS_DIRNAME = "accounts"
ACCOUNT_PROFILE_FILENAME = "Account_Profile.json"
SECRET_VERIFIER_FILENAME = "Secret_Verifier.json"
USER_MEMORY_INDEX_FILENAME = "User_Memory_Index.json"
USER_MEMORY_ENTRIES_FILENAME = "User_Memory_Entries.jsonl"
USER_HABITS_FILENAME = "User_Habbits_and_behave.md"
OPENAI_STATE_FILENAME = "OpenAI_State.json"
SECRET_TOOL_COMMAND = "secret-tool"
INSTANCE_KEY_SIZE_BYTES = 32
INSTANCE_SECRET_SERVICE = "TeeBotus"
INSTANCE_PEPPER_PURPOSE = "account-secret-pepper"
INSTANCE_MAPPING_KEY_PURPOSE = "account-identity-mapping-key"
ACCOUNT_MEMORY_KEY_PURPOSE = "account-structured-memory-key"


class AccountStoreError(RuntimeError):
    """Raised for account-store integrity or crypto errors."""


class InstanceSecretProvider(Protocol):
    """Provider for per-instance secrets used by account authentication/storage."""

    def get_secret(self, instance_name: str, purpose: str) -> bytes:
        """Return a stable 32-byte secret for the given instance/purpose."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_sha512_token() -> str:
    return hashlib.sha512(secrets.token_bytes(64)).hexdigest()


def validate_sha512_token(value: str, *, field_name: str) -> str:
    token = str(value or "").strip().lower()
    if not TOKEN_HEX_RE.fullmatch(token):
        raise AccountStoreError(f"{field_name} must be a 128 character lowercase hex SHA-512 token")
    return token


def _safe_filename(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.:@+-]", "_", value.strip())
    if not safe:
        raise AccountStoreError("identity key must not be empty")
    return safe[:240]


def telegram_identity_key(sender_id: int | str) -> str:
    return f"telegram:user:{str(sender_id).strip()}"


def signal_identity_key(*, source_uuid: str = "", source_number: str = "", source: str = "") -> str:
    uuid_value = str(source_uuid or "").strip()
    if uuid_value:
        return f"signal:uuid:{uuid_value}"
    number_value = str(source_number or "").strip()
    if number_value:
        return f"signal:number:{number_value}"
    source_value = str(source or "").strip()
    if source_value:
        return f"signal:source:{source_value}"
    raise AccountStoreError("Signal identity needs source_uuid, source_number, or source")


@dataclass(frozen=True)
class StaticSecretProvider:
    """Test/development secret provider.

    Production should use SecretToolInstanceSecretProvider so the pepper and mapping key
    never live in repository files.
    """

    secret: bytes

    def get_secret(self, instance_name: str, purpose: str) -> bytes:
        if len(self.secret) != INSTANCE_KEY_SIZE_BYTES:
            raise AccountStoreError("static instance secret must be 32 bytes")
        return self.secret


class SecretToolInstanceSecretProvider:
    """Secret-Service provider backed by libsecret's `secret-tool` CLI."""

    def __init__(self, command: str = SECRET_TOOL_COMMAND) -> None:
        self.command = command

    def get_secret(self, instance_name: str, purpose: str) -> bytes:
        instance = _normalize_secret_token(instance_name, "instance")
        resolved_purpose = _normalize_secret_token(purpose, "purpose")
        existing = self._lookup(instance, resolved_purpose)
        if existing is not None:
            return existing
        key = secrets.token_bytes(INSTANCE_KEY_SIZE_BYTES)
        self._store(instance, resolved_purpose, key)
        confirmed = self._lookup(instance, resolved_purpose)
        if confirmed != key:
            raise AccountStoreError("secret-tool did not return the stored instance secret")
        return key

    def _secret_tool(self) -> str:
        binary = shutil.which(self.command)
        if binary is None:
            raise AccountStoreError("secret-tool is not installed")
        return binary

    def _attrs(self, instance_name: str, purpose: str) -> list[str]:
        return [
            "application",
            INSTANCE_SECRET_SERVICE,
            "instance",
            instance_name,
            "purpose",
            purpose,
        ]

    def _run(self, args: list[str], *, input_text: str = "") -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                [self._secret_tool(), *args],
                input=input_text,
                text=True,
                capture_output=True,
                check=False,
            )
        except OSError as exc:
            raise AccountStoreError("secret-tool could not be started") from exc

    def _lookup(self, instance_name: str, purpose: str) -> bytes | None:
        result = self._run(["lookup", *self._attrs(instance_name, purpose)])
        if result.returncode != 0:
            return None
        value = result.stdout.strip()
        if not value:
            return None
        try:
            secret = base64.urlsafe_b64decode(value.encode("ascii"))
        except Exception as exc:  # noqa: BLE001
            raise AccountStoreError("secret-tool returned invalid instance secret data") from exc
        if len(secret) != INSTANCE_KEY_SIZE_BYTES:
            raise AccountStoreError("instance secret has invalid length")
        return secret

    def _store(self, instance_name: str, purpose: str, secret: bytes) -> None:
        if len(secret) != INSTANCE_KEY_SIZE_BYTES:
            raise AccountStoreError("instance secret has invalid length")
        label = f"TeeBotus {purpose}: instance={instance_name}"
        result = self._run(
            ["store", "--label", label, *self._attrs(instance_name, purpose)],
            input_text=base64.urlsafe_b64encode(secret).decode("ascii") + "\n",
        )
        if result.returncode != 0:
            raise AccountStoreError("secret-tool could not store the instance secret")


def _normalize_secret_token(value: str, field_name: str) -> str:
    token = str(value or "").strip()
    if not token:
        raise AccountStoreError(f"{field_name} must not be empty")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in token):
        raise AccountStoreError(f"{field_name} contains invalid control characters")
    return token


def _safe_account_filename(value: str) -> str:
    filename = str(value or "").strip()
    if not filename:
        raise AccountStoreError("account filename must not be empty")
    candidate = Path(filename)
    if candidate.is_absolute() or len(candidate.parts) != 1 or filename in {".", ".."}:
        raise AccountStoreError("account filename must be a plain filename")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in filename):
        raise AccountStoreError("account filename contains invalid control characters")
    return filename


@dataclass(frozen=True)
class EncryptedJsonVault:
    instance_name: str
    provider: InstanceSecretProvider
    purpose: str = INSTANCE_MAPPING_KEY_PURPOSE

    @property
    def key(self) -> bytes:
        key = self.provider.get_secret(self.instance_name, self.purpose)
        if len(key) != INSTANCE_KEY_SIZE_BYTES:
            raise AccountStoreError("encrypted vault key has invalid length")
        return key

    def read_text(self, path: Path, default: str = "") -> str:
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return default
        if not raw.strip():
            return default
        return self.decrypt(raw, kind=path.name).decode("utf-8")

    def write_text(self, path: Path, text: str) -> None:
        _atomic_write_bytes(path, self.encrypt(str(text or "").encode("utf-8"), kind=path.name))

    def read_json(self, path: Path, default: dict[str, Any]) -> dict[str, Any]:
        text = self.read_text(path, "")
        if not text.strip():
            return dict(default)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AccountStoreError(f"encrypted JSON file is invalid: {path}") from exc
        if not isinstance(data, dict):
            raise AccountStoreError(f"encrypted JSON file must contain an object: {path}")
        return data

    def write_json(self, path: Path, data: dict[str, Any]) -> None:
        payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        self.write_text(path, payload)

    def read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        text = self.read_text(path, "")
        if not text.strip():
            return []
        rows: list[dict[str, Any]] = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AccountStoreError(f"encrypted JSONL file is invalid: {path}") from exc
            if not isinstance(data, dict):
                raise AccountStoreError(f"encrypted JSONL file must contain objects: {path}")
            rows.append(data)
        return rows

    def write_jsonl(self, path: Path, rows: list[dict[str, Any]]) -> None:
        text = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
        self.write_text(path, text)

    def encrypt(self, payload: bytes, *, kind: str) -> bytes:
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(self.key).encrypt(nonce, payload, self._aad(kind))
        envelope = {
            "magic": MAPPING_MAGIC,
            "version": MAPPING_VERSION,
            "algorithm": MAPPING_ALGORITHM,
            "kind": kind,
            "nonce": base64.urlsafe_b64encode(nonce).decode("ascii"),
            "ciphertext": base64.urlsafe_b64encode(ciphertext).decode("ascii"),
        }
        return json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"

    def decrypt(self, payload: bytes, *, kind: str) -> bytes:
        try:
            envelope = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AccountStoreError("encrypted envelope is malformed") from exc
        if not isinstance(envelope, dict):
            raise AccountStoreError("encrypted envelope must be an object")
        if envelope.get("magic") != MAPPING_MAGIC or envelope.get("version") != MAPPING_VERSION:
            raise AccountStoreError("encrypted envelope version is unsupported")
        if envelope.get("algorithm") != MAPPING_ALGORITHM:
            raise AccountStoreError("encrypted envelope algorithm is unsupported")
        if envelope.get("kind") != kind:
            raise AccountStoreError("encrypted envelope kind does not match")
        try:
            nonce = base64.urlsafe_b64decode(str(envelope["nonce"]).encode("ascii"))
            ciphertext = base64.urlsafe_b64decode(str(envelope["ciphertext"]).encode("ascii"))
        except Exception as exc:  # noqa: BLE001
            raise AccountStoreError("encrypted envelope fields are invalid") from exc
        if len(nonce) != 12:
            raise AccountStoreError("encrypted envelope nonce has invalid length")
        if not ciphertext:
            raise AccountStoreError("encrypted envelope ciphertext is empty")
        try:
            return AESGCM(self.key).decrypt(nonce, ciphertext, self._aad(kind))
        except InvalidTag as exc:
            raise AccountStoreError("encrypted envelope authentication failed") from exc

    def _aad(self, kind: str) -> bytes:
        return f"TeeBotus:{self.instance_name}:{self.purpose}:{kind}:v{MAPPING_VERSION}".encode("utf-8")


@dataclass
class AccountStore:
    root: Path
    instance_name: str
    secret_provider: InstanceSecretProvider = field(default_factory=SecretToolInstanceSecretProvider)
    create_dirs: bool = True

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        if self.create_dirs:
            self.accounts_dir.mkdir(parents=True, exist_ok=True)

    @property
    def vault(self) -> EncryptedJsonVault:
        return EncryptedJsonVault(self.instance_name, self.secret_provider)

    def vault_for_purpose(self, purpose: str) -> EncryptedJsonVault:
        return EncryptedJsonVault(self.instance_name, self.secret_provider, purpose=purpose)

    @property
    def account_memory_vault(self) -> EncryptedJsonVault:
        return self.vault_for_purpose(ACCOUNT_MEMORY_KEY_PURPOSE)

    @property
    def accounts_dir(self) -> Path:
        return self.root / ACCOUNTS_DIRNAME

    @property
    def account_index_path(self) -> Path:
        return self.root / ACCOUNT_INDEX_FILENAME

    @property
    def identities_path(self) -> Path:
        return self.root / ACCOUNT_IDENTITIES_FILENAME

    @property
    def secrets_path(self) -> Path:
        return self.root / ACCOUNT_SECRETS_FILENAME

    def account_dir(self, account_id: str) -> Path:
        return self.accounts_dir / validate_sha512_token(account_id, field_name="account_id")

    def resolve_or_create_account(self, identity_key: str, *, display_label: str = "") -> str:
        identities = self._load_identities()
        key = self._normalize_identity_key(identity_key)
        existing = identities.get(key, {}).get("account_id")
        if isinstance(existing, str) and TOKEN_HEX_RE.fullmatch(existing) and self._account_is_resolvable(existing):
            self._touch_identity(identities, key)
            return existing
        account_id = new_sha512_token()
        now = utc_now()
        account = {
            "schema_version": ACCOUNT_SCHEMA_VERSION,
            "instance": self.instance_name,
            "account_id": account_id,
            "created_at": now,
            "updated_at": now,
            "registered": False,
            "secret_exists": False,
            "linked_identities": [key],
            "status": "active",
        }
        self._write_account_profile(account_id, account)
        identities[key] = {
            "schema_version": ACCOUNT_SCHEMA_VERSION,
            "instance": self.instance_name,
            "identity_key": key,
            "account_id": account_id,
            "display_label": display_label,
            "first_seen_at": now,
            "last_seen_at": now,
        }
        self._save_identities(identities)
        self._upsert_account_index(account)
        return account_id

    def get_account_for_identity(self, identity_key: str) -> str | None:
        identities = self._load_identities()
        data = identities.get(self._normalize_identity_key(identity_key))
        if isinstance(data, dict):
            account_id = data.get("account_id")
            if isinstance(account_id, str) and TOKEN_HEX_RE.fullmatch(account_id):
                if self._account_is_resolvable(account_id):
                    return account_id
        return None

    def register_account(self, account_id: str) -> tuple[str, str]:
        account_id = validate_sha512_token(account_id, field_name="account_id")
        self._ensure_account_resolvable(account_id)
        secrets_doc = self._load_secrets()
        secret_data = secrets_doc.get(account_id)
        if isinstance(secret_data, dict) and secret_data.get("active") is True:
            raise AccountStoreError("account already has an active secret; rotate instead")
        return self.rotate_secret(account_id)

    def rotate_secret(self, account_id: str) -> tuple[str, str]:
        account_id = validate_sha512_token(account_id, field_name="account_id")
        self._ensure_account_resolvable(account_id)
        secret = new_sha512_token()
        verifier = self._secret_verifier(secret)
        now = utc_now()
        secret_payload = {
            "schema_version": ACCOUNT_SCHEMA_VERSION,
            "account_id": account_id,
            "verifier_algorithm": "HMAC-SHA512",
            "verifier": verifier,
            "active": True,
            "created_at": now,
            "rotated_at": now,
            "version": 1,
        }
        secrets_doc = self._load_secrets()
        old = secrets_doc.get(account_id)
        if isinstance(old, dict) and isinstance(old.get("version"), int):
            secret_payload["version"] = int(old["version"]) + 1
        secrets_doc[account_id] = secret_payload
        self._save_secrets(secrets_doc)
        self.vault.write_json(self.account_dir(account_id) / SECRET_VERIFIER_FILENAME, secret_payload)
        profile = self._read_account_profile(account_id)
        profile["registered"] = True
        profile["secret_exists"] = True
        profile["updated_at"] = now
        self._write_account_profile(account_id, profile)
        self._upsert_account_index(profile)
        return account_id, secret

    def verify_secret(self, account_id: str, account_secret: str) -> bool:
        try:
            account_id = validate_sha512_token(account_id, field_name="account_id")
            secret = validate_sha512_token(account_secret, field_name="account_secret")
        except AccountStoreError:
            return False
        if not self._account_is_resolvable(account_id):
            return False
        secrets_doc = self._load_secrets()
        payload = secrets_doc.get(account_id)
        if not isinstance(payload, dict) or payload.get("active") is not True:
            return False
        expected = str(payload.get("verifier") or "")
        actual = self._secret_verifier(secret)
        return hmac.compare_digest(expected, actual)

    def link_identity(self, identity_key: str, account_id: str, account_secret: str, *, display_label: str = "") -> dict[str, Any]:
        target_account_id = validate_sha512_token(account_id, field_name="account_id")
        self._ensure_account_resolvable(target_account_id)
        if not self.verify_secret(target_account_id, account_secret):
            raise AccountStoreError("ID or secret is invalid")
        key = self._normalize_identity_key(identity_key)
        current_account_id = self.get_account_for_identity(key)
        old_identity_keys = self.list_identities_for_account(target_account_id)
        now = utc_now()
        merged_from: str | None = None
        if current_account_id == target_account_id:
            identities = self._load_identities()
            self._touch_identity(identities, key)
            return {
                "account_id": target_account_id,
                "identity_key": key,
                "merged_from": None,
                "already_linked": True,
                "old_identity_keys": [],
            }
        if current_account_id and current_account_id != target_account_id:
            if not self._can_auto_merge_source_account(current_account_id, current_identity_key=key):
                raise AccountStoreError("current identity is already linked to another registered account; use account_edit")
            self.merge_accounts(current_account_id, target_account_id)
            merged_from = current_account_id
        identities = self._load_identities()
        previous_identity = identities.get(key)
        first_seen_at = previous_identity.get("first_seen_at", now) if isinstance(previous_identity, dict) else now
        identities[key] = {
            "schema_version": ACCOUNT_SCHEMA_VERSION,
            "instance": self.instance_name,
            "identity_key": key,
            "account_id": target_account_id,
            "display_label": display_label,
            "first_seen_at": first_seen_at,
            "last_seen_at": now,
        }
        self._save_identities(identities)
        self._add_identity_to_profile(target_account_id, key)
        return {
            "account_id": target_account_id,
            "identity_key": key,
            "merged_from": merged_from,
            "old_identity_keys": [identity for identity in old_identity_keys if identity != key],
        }

    def unlink_identity(self, identity_key: str) -> str | None:
        key = self._normalize_identity_key(identity_key)
        identities = self._load_identities()
        payload = identities.get(key)
        if not isinstance(payload, dict):
            return None
        account_id = payload.get("account_id")
        if not isinstance(account_id, str) or not TOKEN_HEX_RE.fullmatch(account_id):
            return None

        new_identities = dict(identities)
        new_identities.pop(key, None)
        profile_path = self.account_dir(account_id) / ACCOUNT_PROFILE_FILENAME
        if not profile_path.exists():
            # Stale mapping only: remove the mapping, but do not create a fresh profile
            # for a missing/tombstoned account during unlink cleanup.
            self._save_identities(new_identities)
            return account_id

        # Pre-read and validate the profile before mutating the identity mapping. If
        # the encrypted profile is unreadable, no mapping is removed.
        profile = self._read_account_profile(account_id)
        linked = [value for value in profile.get("linked_identities", []) if value != key]
        profile["linked_identities"] = linked
        profile["updated_at"] = utc_now()
        if not linked:
            profile["status"] = "orphaned"

        self._write_account_profile(account_id, profile)
        self._upsert_account_index(profile)
        self._save_identities(new_identities)
        return account_id

    def unlink_identity_if_linked_to(self, identity_key: str, expected_account_id: str) -> str | None:
        """Unlink an identity only if it still belongs to the expected account.

        This prevents stale WTF/security notifications from unlinking a communication
        path that has since been moved to a different account.
        """
        expected_account_id = validate_sha512_token(expected_account_id, field_name="expected_account_id")
        key = self._normalize_identity_key(identity_key)
        identities = self._load_identities()
        payload = identities.get(key)
        if not isinstance(payload, dict) or payload.get("account_id") != expected_account_id:
            return None
        return self.unlink_identity(key)

    def merge_accounts(self, source_account_id: str, target_account_id: str) -> None:
        source_account_id = validate_sha512_token(source_account_id, field_name="source_account_id")
        target_account_id = validate_sha512_token(target_account_id, field_name="target_account_id")
        self._ensure_account_resolvable(source_account_id)
        self._ensure_account_resolvable(target_account_id)
        if source_account_id == target_account_id:
            return
        source_dir = self.account_dir(source_account_id)
        target_dir = self.account_dir(target_account_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        self._merge_jsonl(source_dir / USER_MEMORY_ENTRIES_FILENAME, target_dir / USER_MEMORY_ENTRIES_FILENAME, vault=self.account_memory_vault)
        self._merge_json_objects(source_dir / USER_MEMORY_INDEX_FILENAME, target_dir / USER_MEMORY_INDEX_FILENAME, preserve_target=True, vault=self.account_memory_vault)
        self._merge_json_objects(source_dir / ACCOUNT_PROFILE_FILENAME, target_dir / ACCOUNT_PROFILE_FILENAME, preserve_target=True, vault=self.vault)
        self._merge_text(source_dir / USER_HABITS_FILENAME, target_dir / USER_HABITS_FILENAME, heading=f"Merged from {source_account_id}")
        self._merge_openai_state(source_dir / OPENAI_STATE_FILENAME, target_dir / OPENAI_STATE_FILENAME)
        identities = self._load_identities()
        for payload in identities.values():
            if isinstance(payload, dict) and payload.get("account_id") == source_account_id:
                payload["account_id"] = target_account_id
                self._add_identity_to_profile(target_account_id, str(payload.get("identity_key") or ""))
        self._save_identities(identities)
        tombstone = self._read_account_profile(source_account_id) if (source_dir / ACCOUNT_PROFILE_FILENAME).exists() else {}
        tombstone.update({"account_id": source_account_id, "status": "tombstoned", "merged_into": target_account_id, "updated_at": utc_now()})
        self.vault.write_json(source_dir / "Account_Tombstone.json", tombstone)
        self._remove_account_from_index(source_account_id)
        self._delete_dir_contents_except(source_dir, {"Account_Tombstone.json"})

    def account_summary(self, account_id: str) -> dict[str, Any]:
        account_id = validate_sha512_token(account_id, field_name="account_id")
        self._ensure_account_resolvable(account_id)
        profile = self._read_account_profile(account_id)
        secrets_doc = self._load_secrets()
        secret_payload = secrets_doc.get(account_id)
        secret_exists = bool(secret_payload.get("active")) if isinstance(secret_payload, dict) else False
        return {
            "account_id": account_id,
            "registered": bool(profile.get("registered")),
            "secret_exists": secret_exists,
            "linked_identities": self._active_identities_for_account(account_id),
            "status": profile.get("status", "unknown"),
        }

    def list_identities_for_account(self, account_id: str) -> list[str]:
        account_id = validate_sha512_token(account_id, field_name="account_id")
        self._ensure_account_resolvable(account_id)
        return self._active_identities_for_account(account_id)

    def read_memory_index(self, account_id: str) -> dict[str, Any]:
        return self._read_json_with_fallback(self.account_dir(account_id) / USER_MEMORY_INDEX_FILENAME, {}, vault=self.account_memory_vault)

    def write_memory_index(self, account_id: str, data: dict[str, Any]) -> None:
        self.account_memory_vault.write_json(self.account_dir(account_id) / USER_MEMORY_INDEX_FILENAME, data)

    def read_memory_entries(self, account_id: str) -> list[dict[str, Any]]:
        return self._read_jsonl_with_fallback(self.account_dir(account_id) / USER_MEMORY_ENTRIES_FILENAME, vault=self.account_memory_vault)

    def write_memory_entries(self, account_id: str, rows: list[dict[str, Any]]) -> None:
        self.account_memory_vault.write_jsonl(self.account_dir(account_id) / USER_MEMORY_ENTRIES_FILENAME, rows)

    def append_memory_entry(self, account_id: str, entry: dict[str, Any]) -> None:
        rows = self.read_memory_entries(account_id)
        rows.append(dict(entry))
        self.write_memory_entries(account_id, rows)

    def reset_structured_memory(self, account_id: str) -> None:
        self.write_memory_index(account_id, {})
        self.write_memory_entries(account_id, [])

    def read_openai_state(self, account_id: str) -> dict[str, Any]:
        return self._read_json_with_fallback(self.account_dir(account_id) / OPENAI_STATE_FILENAME, {}, vault=self.account_memory_vault)

    def write_openai_state(self, account_id: str, data: dict[str, Any]) -> None:
        self.account_memory_vault.write_json(self.account_dir(account_id) / OPENAI_STATE_FILENAME, data)

    def read_account_text(self, account_id: str, filename: str) -> str:
        account_id = validate_sha512_token(account_id, field_name="account_id")
        path = self.account_dir(account_id) / _safe_account_text_filename(filename)
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    def write_account_text(self, account_id: str, filename: str, text: str) -> None:
        account_id = validate_sha512_token(account_id, field_name="account_id")
        _atomic_write_text(self.account_dir(account_id) / _safe_account_text_filename(filename), str(text or ""))

    def unlink_identity_and_rotate_secret(self, identity_key: str, account_id: str) -> tuple[str | None, str]:
        unlinked_account_id = self.unlink_identity(identity_key)
        _, new_secret = self.rotate_secret(account_id)
        return unlinked_account_id, new_secret

    def _can_auto_merge_source_account(self, account_id: str, *, current_identity_key: str) -> bool:
        if not (self.account_dir(account_id) / ACCOUNT_PROFILE_FILENAME).exists():
            return False
        profile = self._read_account_profile(account_id)
        if profile.get("registered") or profile.get("secret_exists"):
            return False
        if profile.get("status", "active") not in {"active", "orphaned"}:
            return False
        linked = set(self._active_identities_for_account(account_id))
        return linked.issubset({current_identity_key})

    def _account_is_resolvable(self, account_id: str) -> bool:
        try:
            account_id = validate_sha512_token(account_id, field_name="account_id")
        except AccountStoreError:
            return False
        profile_path = self.account_dir(account_id) / ACCOUNT_PROFILE_FILENAME
        if not profile_path.exists():
            return False
        profile = self._read_account_profile(account_id)
        return profile.get("status") != "tombstoned"

    def _active_identities_for_account(self, account_id: str) -> list[str]:
        account_id = validate_sha512_token(account_id, field_name="account_id")
        identities = self._load_identities()
        active = [
            str(identity_key)
            for identity_key, payload in identities.items()
            if isinstance(payload, dict) and payload.get("account_id") == account_id
        ]
        return sorted(dict.fromkeys(active))

    def _read_json_with_fallback(self, path: Path, default: dict[str, Any], *, vault: EncryptedJsonVault) -> dict[str, Any]:
        if not path.exists():
            return dict(default)
        try:
            return vault.read_json(path, default)
        except AccountStoreError:
            if _looks_like_teebotus_encrypted_payload(path):
                raise
            return _read_json_object(path)

    def _write_json_with_vault(self, path: Path, data: dict[str, Any], *, vault: EncryptedJsonVault) -> None:
        vault.write_json(path, data)

    def _read_jsonl_with_fallback(self, path: Path, *, vault: EncryptedJsonVault) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        try:
            return vault.read_jsonl(path)
        except AccountStoreError:
            if _looks_like_teebotus_encrypted_payload(path):
                raise
            return _read_jsonl_plain(path)

    def _write_jsonl_with_vault(self, path: Path, rows: list[dict[str, Any]], *, vault: EncryptedJsonVault) -> None:
        vault.write_jsonl(path, rows)

    def _secret_verifier(self, secret: str) -> str:
        pepper = self.secret_provider.get_secret(self.instance_name, INSTANCE_PEPPER_PURPOSE)
        return hmac.new(pepper, secret.encode("utf-8"), hashlib.sha512).hexdigest()

    def _normalize_identity_key(self, value: str) -> str:
        key = str(value or "").strip()
        if not key:
            raise AccountStoreError("identity key must not be empty")
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in key):
            raise AccountStoreError("identity key contains invalid control characters")
        return key

    def _load_identities(self) -> dict[str, Any]:
        return self.vault.read_json(self.identities_path, {})

    def _save_identities(self, data: dict[str, Any]) -> None:
        self.vault.write_json(self.identities_path, data)

    def _load_secrets(self) -> dict[str, Any]:
        return self.vault.read_json(self.secrets_path, {})

    def _save_secrets(self, data: dict[str, Any]) -> None:
        self.vault.write_json(self.secrets_path, data)

    def _load_index(self) -> dict[str, Any]:
        return self.vault.read_json(self.account_index_path, {"schema_version": ACCOUNT_SCHEMA_VERSION, "accounts": {}})

    def _save_index(self, data: dict[str, Any]) -> None:
        self.vault.write_json(self.account_index_path, data)

    def _read_account_profile(self, account_id: str) -> dict[str, Any]:
        profile_path = self.account_dir(account_id) / ACCOUNT_PROFILE_FILENAME
        if not profile_path.exists():
            return {"schema_version": ACCOUNT_SCHEMA_VERSION, "instance": self.instance_name, "account_id": account_id, "linked_identities": [], "status": "active"}
        try:
            return self.vault.read_json(profile_path, {})
        except AccountStoreError:
            if _looks_like_teebotus_encrypted_payload(profile_path):
                raise
            return _read_json_object(profile_path)

    def _write_account_profile(self, account_id: str, profile: dict[str, Any]) -> None:
        self.vault.write_json(self.account_dir(account_id) / ACCOUNT_PROFILE_FILENAME, profile)

    def _account_is_usable(self, account_id: str) -> bool:
        return self._account_is_resolvable(account_id)

    def _ensure_account_exists(self, account_id: str) -> None:
        if not (self.account_dir(account_id) / ACCOUNT_PROFILE_FILENAME).exists():
            raise AccountStoreError("account does not exist")

    def _ensure_account_resolvable(self, account_id: str) -> None:
        if not self._account_is_resolvable(account_id):
            raise AccountStoreError("account is not active")

    def _ensure_account_usable(self, account_id: str) -> None:
        self._ensure_account_resolvable(account_id)

    def _upsert_account_index(self, profile: dict[str, Any]) -> None:
        index = self._load_index()
        accounts = index.setdefault("accounts", {})
        accounts[profile["account_id"]] = {
            "account_id": profile["account_id"],
            "status": profile.get("status", "active"),
            "registered": bool(profile.get("registered")),
            "linked_identity_count": len(profile.get("linked_identities", [])),
            "updated_at": profile.get("updated_at", utc_now()),
        }
        self._save_index(index)

    def _remove_account_from_index(self, account_id: str) -> None:
        index = self._load_index()
        accounts = index.setdefault("accounts", {})
        accounts.pop(account_id, None)
        self._save_index(index)

    def _touch_identity(self, identities: dict[str, Any], identity_key: str) -> None:
        if isinstance(identities.get(identity_key), dict):
            identities[identity_key]["last_seen_at"] = utc_now()
            self._save_identities(identities)

    def _add_identity_to_profile(self, account_id: str, identity_key: str) -> None:
        if not identity_key:
            return
        profile = self._read_account_profile(account_id)
        linked = list(profile.get("linked_identities", []))
        if identity_key not in linked:
            linked.append(identity_key)
        profile["linked_identities"] = linked
        profile["updated_at"] = utc_now()
        self._write_account_profile(account_id, profile)
        self._upsert_account_index(profile)

    def _merge_jsonl(self, source: Path, target: Path, *, vault: EncryptedJsonVault) -> None:
        if not source.exists():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        existing = self._read_jsonl_with_fallback(target, vault=vault) if target.exists() else []
        addition = self._read_jsonl_with_fallback(source, vault=vault)
        self._write_jsonl_with_vault(target, [*existing, *addition], vault=vault)

    def _merge_json_objects(self, source: Path, target: Path, *, preserve_target: bool = False, vault: EncryptedJsonVault) -> None:
        if not source.exists():
            return
        source_data = self._read_json_with_fallback(source, {}, vault=vault)
        target_data = self._read_json_with_fallback(target, {}, vault=vault) if target.exists() else {}
        if preserve_target:
            merged = {**source_data, **target_data}
        else:
            merged = {**target_data, **source_data}
        self._write_json_with_vault(target, merged, vault=vault)

    def _merge_openai_state(self, source: Path, target: Path) -> None:
        if not source.exists():
            return
        source_data = self._read_json_with_fallback(source, {}, vault=self.account_memory_vault)
        target_data = self._read_json_with_fallback(target, {}, vault=self.account_memory_vault) if target.exists() else {}
        selected = _choose_newer_state(source_data, target_data)
        self._write_json_with_vault(target, selected, vault=self.account_memory_vault)

    def _merge_text(self, source: Path, target: Path, *, heading: str) -> None:
        if not source.exists():
            return
        source_text = source.read_text(encoding="utf-8").strip()
        if not source_text:
            return
        target_text = target.read_text(encoding="utf-8") if target.exists() else ""
        addition = f"\n\n## {heading}\n\n{source_text}\n"
        _atomic_write_text(target, target_text.rstrip() + addition)

    def _delete_dir_contents_except(self, path: Path, keep: set[str]) -> None:
        if not path.exists():
            return
        for child in path.iterdir():
            if child.name in keep:
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink(missing_ok=True)


def _looks_like_teebotus_encrypted_payload(path: Path) -> bool:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise AccountStoreError(f"could not inspect encrypted file: {path}") from exc
    return _is_any_teebotus_encrypted_payload(raw)


def _safe_account_text_filename(filename: str) -> str:
    value = str(filename or "").strip()
    path = Path(value)
    if not value or path.name != value or path.is_absolute() or value in {".", ".."}:
        raise AccountStoreError("account text filename must be a plain file name")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise AccountStoreError("account text filename contains invalid control characters")
    return value


def _is_any_teebotus_encrypted_payload(raw: bytes) -> bool:
    if not isinstance(raw, bytes) or not raw.lstrip().startswith(b"{"):
        return False
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, dict)
        and str(payload.get("magic") or "") in TEEBOTUS_ENCRYPTION_MAGICS
        and isinstance(payload.get("ciphertext"), str)
    )


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise AccountStoreError(f"JSON file is invalid: {path}") from exc
    if not isinstance(data, dict):
        raise AccountStoreError(f"JSON file must contain an object: {path}")
    return data


def _read_jsonl_plain(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return rows
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AccountStoreError(f"JSONL file is invalid: {path}") from exc
        if not isinstance(payload, dict):
            raise AccountStoreError(f"JSONL file must contain objects: {path}")
        rows.append(payload)
    return rows


def _choose_newer_state(source_data: dict[str, Any], target_data: dict[str, Any]) -> dict[str, Any]:
    source_updated = str(source_data.get("updated_at") or source_data.get("created_at") or "")
    target_updated = str(target_data.get("updated_at") or target_data.get("created_at") or "")
    if source_updated and (not target_updated or source_updated > target_updated):
        merged = {**target_data, **source_data}
    else:
        merged = {**source_data, **target_data}
    return merged


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _atomic_write_text(path, payload)


def _atomic_write_text(path: Path, text: str) -> None:
    _atomic_write_bytes(path, text.encode("utf-8"))


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    except OSError:
        pass
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
            temp_path.unlink(missing_ok=True)
