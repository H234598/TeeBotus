from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Mapping

from TeeBotus import __version__
from TeeBotus.core.version_notifications import DEFAULT_REPO_URL, github_repo_url
from TeeBotus.runtime.accounts import (
    ACCOUNTS_DIRNAME,
    TOKEN_HEX_RE,
    AccountStore,
    AccountStoreError,
    SecretToolInstanceSecretProvider,
    telegram_identity_key,
)
from TeeBotus.runtime.proactive_agent import proactive_agent_instance_enabled

LOGGER = logging.getLogger("TeeBotus")
USER_MEMORY_INDEX_FILENAME = "User_Memory_Index.json"
USER_MEMORY_ENTRIES_FILENAME = "User_Memory_Entries.jsonl"
ACCOUNT_MEMORY_FILENAMES = frozenset(
    {
        USER_MEMORY_INDEX_FILENAME,
        USER_MEMORY_ENTRIES_FILENAME,
    }
)
STATUS_COMMAND_ALIASES = frozenset(
    {
        "/status",
        "/info",
        "/about",
        "/version",
        "/versions",
        "/programm",
        "/program",
    }
)


def build_status_reply(
    *,
    sender_id: str = "",
    instance_name: str,
    project_root: Path,
    account_id: str = "",
    account_store: AccountStore | None = None,
    proactive_model_planner: str = "",
    llm_enabled: bool | None = None,
    llm_provider: str = "",
    llm_model: str = "",
    llm_fallback_models: tuple[str, ...] | list[str] | str = (),
    env: Mapping[str, str] | None = None,
) -> str:
    resolved_account_id = _resolve_status_account_id(sender_id=sender_id, account_id=account_id, account_store=account_store)
    account_resolved = bool(resolved_account_id)
    if resolved_account_id and account_store is not None:
        account_dir = _account_memory_dir_from_store(account_store, resolved_account_id)
    elif resolved_account_id:
        account_dir = account_memory_dir_for_account(resolved_account_id, instance_name=instance_name, project_root=project_root)
    else:
        account_dir = account_memory_dir_for_sender(sender_id, instance_name=instance_name, project_root=project_root)
        account_resolved = account_dir is not None
    memory_size = account_memory_payload_size(
        account_store=account_store,
        account_id=resolved_account_id,
        fallback_directory=account_dir,
    )
    encryption_status = memory_encryption_status(account_dir, account_store=account_store, account_id=resolved_account_id)
    commit_history_url = github_commit_history_url(project_root)
    status_name = _status_display_name(instance_name)
    return "\n".join(
        [
            f"{status_name} Status:",
            "",
            "System",
            "- Status: laeuft",
            f"- Version: {__version__} Wirt Commits {commit_history_url}",
            "",
            "LLM",
            f"- Textantworten: {_llm_enabled_status(llm_enabled)}",
            f"- Provider: {_safe_status_value(llm_provider, default='openai')}",
            f"- Modell: {_safe_status_value(llm_model, default='openai-default')}",
            f"- Fallback-Modelle: {_fallback_model_count(llm_fallback_models)}",
            "",
            "Deine Daten",
            f"- Nutzermemory: {_memory_status_text(account_resolved=account_resolved, memory_size=memory_size)}",
            f"- Userfiles: {encryption_status}",
            "",
            *_proactive_agent_status_lines(
                account_store=account_store,
                account_id=resolved_account_id,
                instance_name=instance_name,
                proactive_model_planner=proactive_model_planner,
                env=env,
            ),
        ]
    )


def _llm_enabled_status(value: bool | None) -> str:
    if value is None:
        return "unbekannt"
    return "ja" if value else "nein"


def _safe_status_value(value: str, *, default: str) -> str:
    text = str(value or "").strip()
    return text if text else default


def _fallback_model_count(value: tuple[str, ...] | list[str] | str) -> str:
    if isinstance(value, str):
        count = len([part for part in value.split(",") if part.strip()])
    else:
        count = len([part for part in value if str(part or "").strip()])
    return str(count)


def _status_display_name(instance_name: str) -> str:
    return str(instance_name or "").strip() or "TeeBotus"


def _memory_status_text(*, account_resolved: bool, memory_size: int) -> str:
    if not account_resolved:
        return "Account nicht zugeordnet"
    return format_byte_size(memory_size)


def _resolve_status_account_id(*, sender_id: str, account_id: str, account_store: AccountStore | None) -> str:
    if account_id:
        return account_id
    if account_store is None or not sender_id:
        return ""
    try:
        return account_store.get_account_for_identity(telegram_identity_key(sender_id)) or ""
    except (AccountStoreError, OSError):
        LOGGER.exception("Failed to resolve account id for status.")
        return ""


def _account_memory_dir_from_store(account_store: AccountStore, account_id: str) -> Path | None:
    try:
        account_dir = account_store.account_dir(account_id)
    except (AccountStoreError, OSError):
        LOGGER.exception("Failed to resolve account memory directory from store.")
        return None
    return account_dir if account_dir.is_dir() else None


def _proactive_agent_status_lines(
    *,
    account_store: AccountStore | None,
    account_id: str,
    instance_name: str,
    proactive_model_planner: str,
    env: Mapping[str, str] | None,
) -> list[str]:
    scheduler_enabled = proactive_agent_instance_enabled(instance_name, env=env or os.environ)
    planner = _proactive_model_planner_status(proactive_model_planner)
    if account_store is None or not account_id:
        return [
            "Proactive Agent",
            "- Agent enabled: unbekannt",
            "- Outbox queued: unbekannt",
            "- Review pending: unbekannt",
            f"- Scheduler enabled: {'ja' if scheduler_enabled else 'nein'}",
            f"- Model planner: {planner}",
        ]
    try:
        state = account_store.read_agent_state(account_id)
        outbox = account_store.read_proactive_outbox(account_id)
    except (AccountStoreError, OSError):
        LOGGER.exception("Failed to read proactive agent status.")
        return [
            "Proactive Agent",
            "- Agent enabled: Fehler beim Lesen",
            "- Outbox queued: Fehler beim Lesen",
            "- Review pending: Fehler beim Lesen",
            f"- Scheduler enabled: {'ja' if scheduler_enabled else 'nein'}",
            f"- Model planner: {planner}",
        ]
    proactive = state.get("proactive") if isinstance(state, dict) else {}
    if not isinstance(proactive, dict):
        proactive = {}
    enabled = bool(proactive.get("enabled"))
    paused = bool(proactive.get("paused"))
    queued = sum(1 for item in outbox if isinstance(item, dict) and str(item.get("status") or "queued").strip().casefold() == "queued")
    review_pending = sum(1 for item in outbox if isinstance(item, dict) and str(item.get("status") or "").strip().casefold() == "review_pending")
    return [
        "Proactive Agent",
        f"- Agent enabled: {'ja' if enabled else 'nein'}",
        f"- Agent paused: {'ja' if paused else 'nein'}",
        f"- Outbox queued: {queued}",
        f"- Review pending: {review_pending}",
        f"- Scheduler enabled: {'ja' if scheduler_enabled else 'nein'}",
        f"- Model planner: {planner}",
    ]


def _proactive_model_planner_status(value: str) -> str:
    planner = str(value or "").strip().casefold()
    if planner in {"tool", "llm", "none"}:
        return planner
    return "unbekannt"


def github_commit_history_url(project_root: Path) -> str:
    repo_url = github_repo_url(project_root)
    if not repo_url:
        repo_url = DEFAULT_REPO_URL
    return f"{repo_url.rstrip('/')}/commits/main"


def account_memory_dir_for_account(account_id: str, *, instance_name: str, project_root: Path) -> Path | None:
    if not account_id or not instance_name:
        return None
    account_dir = project_root / "instances" / instance_name / "data" / "accounts" / "accounts" / account_id
    return account_dir if account_dir.is_dir() else None


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


def account_memory_payload_size(*, account_store: AccountStore | None, account_id: str, fallback_directory: Path | None) -> int:
    if account_store is not None and account_id:
        try:
            entries = account_store.read_memory_entries(account_id)
            index = account_store.read_memory_index(account_id)
        except (AccountStoreError, OSError):
            LOGGER.exception("Failed to read account memory payload size from store.")
        else:
            payload: dict[str, Any] = {"entries": entries}
            if index:
                payload["index"] = index
            raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            return len(raw)
    return memory_files_size(fallback_directory)


def memory_encryption_status(directory: Path | None, *, account_store: AccountStore | None = None, account_id: str = "") -> str:
    if account_store is not None and account_id and account_store.account_memory_backend is not None:
        return "Datenbank-Backend, Payloads verschluesselt"
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


def account_memory_index_health_lines(*, instance_name: str, project_root: Path) -> list[str]:
    if not instance_name:
        return []
    root = project_root / "instances" / instance_name / "data" / "accounts"
    account_dirs = _account_memory_account_dirs(root / ACCOUNTS_DIRNAME)
    if not account_dirs:
        return [f"account_memory={instance_name} status=none"]
    try:
        store = AccountStore(
            root,
            instance_name,
            secret_provider=SecretToolInstanceSecretProvider(),
            create_dirs=False,
        )
    except Exception as exc:
        return [f"account_memory={instance_name} status=broken error={type(exc).__name__}: {exc}"]
    lines: list[str] = []
    for account_dir in account_dirs:
        account_id = account_dir.name
        try:
            health = store.check_structured_memory_index(account_id)
        except AccountStoreError as exc:
            lines.append(f"account_memory={instance_name}/{account_id} status=broken error={exc}")
            continue
        except OSError as exc:
            lines.append(f"account_memory={instance_name}/{account_id} status=broken error={exc}")
            continue
        if health.ok:
            lines.append(f"account_memory={instance_name}/{account_id} status=ok")
        else:
            lines.append(f"account_memory={instance_name}/{account_id} status=broken error={'; '.join(health.errors)}")
    return lines


def _account_memory_account_dirs(accounts_dir: Path) -> list[Path]:
    if not accounts_dir.exists():
        return []
    try:
        children = list(accounts_dir.iterdir())
    except OSError:
        LOGGER.exception("Failed to list account memory directories.")
        return []
    return sorted(
        path
        for path in children
        if path.is_dir() and TOKEN_HEX_RE.fullmatch(path.name) and not (path / "Account_Tombstone.json").exists()
    )


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
