from __future__ import annotations

import json
import logging
from pathlib import Path

from TeeBotus import __version__
from TeeBotus.runtime.accounts import AccountStore, AccountStoreError, SecretToolInstanceSecretProvider, telegram_identity_key

LOGGER = logging.getLogger("TeeBotus")
USER_MEMORY_INDEX_FILENAME = "User_Memory_Index.json"
USER_MEMORY_ENTRIES_FILENAME = "User_Memory_Entries.jsonl"
ACCOUNT_MEMORY_FILENAMES = frozenset(
    {
        USER_MEMORY_INDEX_FILENAME,
        USER_MEMORY_ENTRIES_FILENAME,
    }
)


def build_status_reply(*, sender_id: str, instance_name: str, project_root: Path) -> str:
    account_dir = account_memory_dir_for_sender(sender_id, instance_name=instance_name, project_root=project_root)
    memory_size = memory_files_size(account_dir)
    encryption_status = memory_encryption_status(account_dir)
    return "\n".join(
        [
            "Status: Laeuft",
            f"Version: {__version__}",
            f"Groesse deiner Nutzermemorys: {format_byte_size(memory_size)}",
            f"Userfiles-Verschluesselung: {encryption_status}",
        ]
    )


def account_memory_dir_for_sender(sender_id: str, *, instance_name: str, project_root: Path) -> Path | None:
    if not sender_id or not instance_name:
        return None
    try:
        store = AccountStore(
            project_root / "instances" / instance_name / "data" / "accounts",
            instance_name,
            secret_provider=SecretToolInstanceSecretProvider(),
            create_dirs=False,
        )
        account_id = store.get_account_for_identity(telegram_identity_key(sender_id))
    except (AccountStoreError, OSError):
        LOGGER.exception("Failed to resolve account memory directory for status.")
        return None
    if not account_id:
        return None
    account_dir = project_root / "instances" / instance_name / "data" / "accounts" / "accounts" / account_id
    return account_dir if account_dir.is_dir() else None


def memory_files_size(directory: Path | None) -> int:
    if directory is None or not directory.exists():
        return 0
    total = 0
    for path in directory.rglob("*"):
        if not path.is_file() or path.name not in ACCOUNT_MEMORY_FILENAMES:
            continue
        try:
            total += path.stat().st_size
        except OSError:
            LOGGER.exception("Failed to stat user memory file %s.", path)
    return total


def memory_encryption_status(directory: Path | None) -> str:
    if directory is None or not directory.exists():
        return "kein Account-Memory gefunden"
    structured_files = [directory / USER_MEMORY_INDEX_FILENAME, directory / USER_MEMORY_ENTRIES_FILENAME]
    existing_structured = [path for path in structured_files if path.exists()]
    encrypted_structured = [path for path in existing_structured if looks_like_encrypted_payload(path)]
    if not existing_structured:
        return "keine strukturierten Userfiles"
    if len(encrypted_structured) == len(existing_structured):
        return "Userfiles verschluesselt"
    return "Userfiles nicht vollstaendig verschluesselt"


def looks_like_encrypted_payload(path: Path) -> bool:
    try:
        raw = path.read_bytes()
    except OSError:
        return False
    if not raw.lstrip().startswith(b"{"):
        return False
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("magic") == "TMBMAP1" and isinstance(payload.get("ciphertext"), str)


def format_byte_size(size: int) -> str:
    value = float(max(0, size))
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{value:.2f} TB"
