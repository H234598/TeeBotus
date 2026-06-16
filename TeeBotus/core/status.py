from __future__ import annotations

import contextlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Mapping

from TeeBotus import __version__
from TeeBotus.core.version_notifications import DEFAULT_REPO_URL, github_repo_url
from TeeBotus.mcp_tools import DEFAULT_MCP_TOOL_POLICIES, MCPToolPolicy, resolve_mcp_tool_policies
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
STATUS_SECRET_REDACTIONS = (
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"), "sk-<redacted>"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9_-]{8,}\b"), "xox-<redacted>"),
    (re.compile(r"\bsyt_[A-Za-z0-9_=-]{8,}\b"), "syt_<redacted>"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{8,}\b"), "gh_<redacted>"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{12,}\b"), "github_pat_<redacted>"),
    (re.compile(r"\bglpat-[A-Za-z0-9_-]{8,}\b"), "glpat-<redacted>"),
    (re.compile(r"\bhf_[A-Za-z0-9]{8,}\b"), "hf_<redacted>"),
    (re.compile(r"\bgsk_[A-Za-z0-9]{8,}\b"), "gsk_<redacted>"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{16,}\b"), "AIza<redacted>"),
    (
        re.compile(r"\b([A-Za-z0-9_]*(?:api[_-]?key|access[_-]?token|token|secret|password)[A-Za-z0-9_]*)=([^,\s)]+)", re.IGNORECASE),
        r"\1=<redacted>",
    ),
)
STATUS_URL_CREDENTIAL_RE = re.compile(r"(?<!\S)(?:[A-Za-z][A-Za-z0-9+.-]*://)?[^/\s:@]+:[^/\s@]+@(?=[^\s]+)")


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
    mcp_tools: Mapping[str, Mapping[str, Any]] | None = None,
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
            *mcp_tool_status_lines(mcp_tools or {}),
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
    return redact_status_text(text) if text else default


def _fallback_model_count(value: tuple[str, ...] | list[str] | str) -> str:
    if isinstance(value, str):
        count = len([part for part in value.split(",") if part.strip()])
    else:
        count = len([part for part in value if str(part or "").strip()])
    return str(count)


def mcp_tool_status_lines(mcp_tools: Mapping[str, Mapping[str, Any]] | None = None) -> list[str]:
    configured = {str(name or "").strip().casefold(): config for name, config in (mcp_tools or {}).items() if str(name or "").strip()}
    allowed: list[str] = []
    guarded: list[str] = []
    disabled: list[str] = []
    resolved = resolve_mcp_tool_policies(configured)
    for name, policy in sorted(resolved.items()):
        if _mcp_policy_directly_callable(policy):
            allowed.append(_mcp_tool_status_label(name, policy))
        elif policy.enabled and policy.read_only:
            guarded.append(_mcp_tool_status_label(name, policy))
        elif not policy.enabled:
            disabled.append(name)
        else:
            disabled.append(f"{name} (nicht read-only)")
    ignored = sorted(redact_status_text(name) for name in configured if name not in DEFAULT_MCP_TOOL_POLICIES)
    lines = [
        "MCP Tools",
        f"- Read-only allowlist: {', '.join(allowed) if allowed else 'keine'}",
    ]
    if guarded:
        lines.append(f"- Nur mit Schutz: {', '.join(guarded)}")
    if disabled:
        lines.append(f"- Deaktiviert: {', '.join(disabled)}")
    if ignored:
        lines.append(f"- Ignoriert: {', '.join(ignored)}")
    return lines


def mcp_tool_runtime_status_line(instance_name: str, mcp_tools: Mapping[str, Mapping[str, Any]] | None = None) -> str:
    lines = mcp_tool_status_lines(mcp_tools)
    details = " ".join(line.removeprefix("- ") for line in lines[1:])
    return f"mcp_tools={instance_name} {details}"


def redact_status_text(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for pattern, replacement in STATUS_SECRET_REDACTIONS:
        text = pattern.sub(replacement, text)
    text = STATUS_URL_CREDENTIAL_RE.sub(_redacted_status_url_credentials, text)
    return text.replace("\r", " ").replace("\n", " ")


def _redacted_status_url_credentials(match: re.Match[str]) -> str:
    value = match.group(0)
    if "://" not in value:
        return ""
    return value.split("://", maxsplit=1)[0] + "://"


def _mcp_tool_status_label(name: str, policy: MCPToolPolicy) -> str:
    suffixes: list[str] = []
    if policy.private_chat_only:
        suffixes.append("private")
    if policy.requires_confirmation:
        suffixes.append("confirm")
    if policy.requires_admin:
        suffixes.append("admin")
    if policy.sandbox_required:
        suffixes.append("sandbox")
    return f"{name} ({', '.join(suffixes)})" if suffixes else name


def _mcp_policy_directly_callable(policy: MCPToolPolicy) -> bool:
    return policy.enabled and policy.read_only and not policy.requires_confirmation and not policy.requires_admin and not policy.sandbox_required


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
    project_root = project_root.resolve()
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
    has_broken_memory = False
    for account_dir in account_dirs:
        account_id = account_dir.name
        profile_warning = ""
        try:
            store._read_account_profile(account_id)
        except AccountStoreError as exc:
            if store.account_memory_backend is None:
                lines.append(f"account_memory={instance_name}/{account_id} status=broken error={exc}")
                has_broken_memory = True
                continue
            profile_warning = f" warning=profile_unreadable:{exc}"
        except OSError as exc:
            if store.account_memory_backend is None:
                lines.append(f"account_memory={instance_name}/{account_id} status=broken error={exc}")
                has_broken_memory = True
                continue
            profile_warning = f" warning=profile_unreadable:{exc}"
        try:
            with _suppress_expected_account_memory_health_logs():
                health = store.check_structured_memory_index(account_id, require_resolvable=not profile_warning)
        except AccountStoreError as exc:
            lines.append(f"account_memory={instance_name}/{account_id} status=broken error={exc}")
            has_broken_memory = True
            continue
        except OSError as exc:
            lines.append(f"account_memory={instance_name}/{account_id} status=broken error={exc}")
            has_broken_memory = True
            continue
        fallback_warning = _account_memory_fallback_warning(store, account_id)
        if health.ok:
            lines.append(f"account_memory={instance_name}/{account_id} status=ok{profile_warning}{fallback_warning}")
        else:
            lines.append(
                f"account_memory={instance_name}/{account_id} status=broken error={'; '.join(health.errors)}{profile_warning}{fallback_warning}"
            )
            has_broken_memory = True
    if has_broken_memory:
        instances_dir = project_root / "instances"
        lines.append(
            f'account_memory_recovery={instance_name} status=needed command="python3 -m TeeBotus.admin memory-recovery --instances-dir {instances_dir} --instances {instance_name}"'
        )
        legacy = _find_legacy_plaintext_backup(project_root=project_root, instance_name=instance_name)
        if legacy:
            lines.append(
                f'account_memory_recovery_legacy={instance_name} status=available '
                f'sources={legacy["sources"]} entries={legacy["entries"]} path={legacy["effective_path"]} '
                f'command="python3 scripts/import_legacy_user_memory.py --legacy-instances-dir {legacy["requested_path"]} '
                f'--target-instances-dir {instances_dir} --instance {instance_name} --replace-unreadable-account-metadata"'
            )
    return lines


def _account_memory_fallback_warning(store: AccountStore, account_id: str) -> str:
    backend = store.account_memory_backend
    if backend is None:
        return ""
    stale_entries = set(getattr(backend, "stale_fallback_entry_account_ids", ()) or ())
    stale_indexes = set(getattr(backend, "stale_fallback_index_account_ids", ()) or ())
    stale_parts: list[str] = []
    if account_id in stale_entries:
        stale_parts.append("entries")
    if account_id in stale_indexes:
        stale_parts.append("index")
    if not stale_parts:
        return ""
    error = redact_status_text(getattr(backend, "last_fallback_sync_error", "") or "")
    suffix = f":{error}" if error else ""
    return f" warning=fallback_sync_stale:{'+'.join(stale_parts)}{suffix}"


@contextlib.contextmanager
def _suppress_expected_account_memory_health_logs():
    previous_disabled = LOGGER.disabled
    LOGGER.disabled = True
    try:
        yield
    finally:
        LOGGER.disabled = previous_disabled


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


def _find_legacy_plaintext_backup(*, project_root: Path, instance_name: str) -> dict[str, str | int] | None:
    candidates: list[dict[str, str | int]] = []
    env_path = os.environ.get("TEEBOTUS_LEGACY_INSTANCES_DIR", "").strip()
    if env_path:
        candidate = _legacy_plaintext_backup_candidate(Path(env_path).expanduser(), instance_name)
        if candidate:
            candidates.append(candidate)
    try:
        sibling_candidates = sorted(project_root.parent.glob(f"{project_root.name}.bak*"))
    except OSError:
        sibling_candidates = []
    for path in sibling_candidates:
        candidate = _legacy_plaintext_backup_candidate(path, instance_name)
        if candidate:
            candidates.append(candidate)
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            int(item["entries"]),
            int(item["sources"]),
            _legacy_backup_priority(str(item["effective_path"])),
            _requested_backup_priority(str(item["requested_path"])),
        ),
    )


def _legacy_plaintext_backup_candidate(path: Path, instance_name: str) -> dict[str, str | int] | None:
    effective_path = _resolve_legacy_backup_instances_dir(path, instance_name)
    users_dir = effective_path / instance_name / "data" / "users"
    if not users_dir.exists():
        return None
    sources = 0
    entries = 0
    try:
        user_dirs = sorted(user_dir for user_dir in users_dir.iterdir() if user_dir.is_dir())
    except OSError:
        return None
    for user_dir in user_dirs:
        source_entries = _count_plaintext_legacy_entries(user_dir / USER_MEMORY_ENTRIES_FILENAME)
        if source_entries <= 0:
            continue
        sources += 1
        entries += source_entries
    if sources <= 0:
        return None
    return {
        "requested_path": str(path),
        "effective_path": str(effective_path),
        "sources": sources,
        "entries": entries,
    }


def _resolve_legacy_backup_instances_dir(path: Path, instance_name: str) -> Path:
    if (path / instance_name / "data" / "users").exists():
        return path
    candidates: list[tuple[int, int, str, Path]] = []
    try:
        children = sorted(path.iterdir()) if path.exists() and path.is_dir() else []
    except OSError:
        children = []
    for child in children:
        if not child.is_dir() or not child.name.startswith("instances"):
            continue
        users_dir = child / instance_name / "data" / "users"
        if not users_dir.exists():
            continue
        sources = 0
        entries = 0
        try:
            user_dirs = sorted(user_dir for user_dir in users_dir.iterdir() if user_dir.is_dir())
        except OSError:
            continue
        for user_dir in user_dirs:
            source_entries = _count_plaintext_legacy_entries(user_dir / USER_MEMORY_ENTRIES_FILENAME)
            if source_entries <= 0:
                continue
            sources += 1
            entries += source_entries
        if sources:
            candidates.append((entries, sources, child.name, child))
    if not candidates:
        return path
    candidates.sort(key=lambda item: (item[0], item[1], _legacy_backup_priority(item[2])), reverse=True)
    return candidates[0][3]


def _count_plaintext_legacy_entries(path: Path) -> int:
    if not path.exists():
        return 0
    entries = 0
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return 0
    for line in lines:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return 0
        if not isinstance(data, dict):
            return 0
        if {"version", "nonce", "ciphertext"}.issubset(data):
            return 0
        entries += 1
    return entries


def _legacy_backup_priority(name: str) -> int:
    path_name = Path(name).name
    if path_name == "instances.bak":
        return 3
    if path_name.startswith("instances.bak"):
        return 2
    if path_name == "instances":
        return 1
    return 0


def _requested_backup_priority(name: str) -> int:
    path_name = Path(name).name
    marker = ".bak"
    if marker not in path_name:
        return 0
    suffix = path_name.rsplit(marker, 1)[1]
    if not suffix:
        return 1
    try:
        return 1 + int(suffix)
    except ValueError:
        return 1


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
