from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import shlex
import sqlite3
import tempfile
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from TeeBotus.admin.accounts_report import DEFAULT_INSTANCES_DIR, ReadOnlySecretToolInstanceSecretProvider, discover_instances, parse_csv
from TeeBotus.artifact_outputs import legacy_import_preflight_path
from TeeBotus.runtime.accounts import (
    ACCOUNTS_DIRNAME,
    ACCOUNT_MEMORY_KEY_PURPOSE,
    ACCOUNT_PROFILE_FILENAME,
    AGENT_STATE_FILENAME,
    CODEX_HISTORY_DISPATCH_RESULTS_FILENAME,
    CODEX_HISTORY_OUTBOX_FILENAME,
    CODEX_HISTORY_PROJECTS_FILENAME,
    INSTANCE_STATE_ACCOUNT_ID,
    INSTANCE_MAPPING_KEY_PURPOSE,
    INSTANCE_PEPPER_PURPOSE,
    LLM_STATE_FILENAME,
    OPENAI_STATE_FILENAME,
    PROACTIVE_AUDIT_FILENAME,
    PROACTIVE_DISPATCH_RESULTS_FILENAME,
    PROACTIVE_OUTBOX_FILENAME,
    STATUS_AUTH_STATE_FILENAME,
    STATUS_DISPATCH_RESULTS_FILENAME,
    STATUS_OUTBOX_FILENAME,
    AccountStore,
    AccountStoreError,
    InstanceSecretProvider,
    TOKEN_HEX_RE,
    USER_MEMORY_ENTRIES_FILENAME,
    USER_MEMORY_INDEX_FILENAME,
    telegram_identity_key,
)
from TeeBotus.runtime.artifacts import safe_artifact_name
from TeeBotus.runtime.dotenv import load_project_dotenv_for_instances
from TeeBotus.runtime.sqlite_memory import SQLiteAccountMemoryBackend, SQLiteMemoryConfig

RECOVERY_SCHEMA_VERSION = 2
SQLITE_MEMORY_TABLES = ("memory_entries", "memory_indexes", "account_jsonl_collections")
JSON_ACCOUNT_MEMORY_FILES = (
    USER_MEMORY_ENTRIES_FILENAME,
    USER_MEMORY_INDEX_FILENAME,
    LLM_STATE_FILENAME,
    OPENAI_STATE_FILENAME,
    AGENT_STATE_FILENAME,
    PROACTIVE_OUTBOX_FILENAME,
    PROACTIVE_AUDIT_FILENAME,
    PROACTIVE_DISPATCH_RESULTS_FILENAME,
    STATUS_AUTH_STATE_FILENAME,
    STATUS_OUTBOX_FILENAME,
    STATUS_DISPATCH_RESULTS_FILENAME,
    CODEX_HISTORY_OUTBOX_FILENAME,
    CODEX_HISTORY_DISPATCH_RESULTS_FILENAME,
    CODEX_HISTORY_PROJECTS_FILENAME,
)
JSON_ACCOUNT_STATE_FILES = (
    LLM_STATE_FILENAME,
    OPENAI_STATE_FILENAME,
    AGENT_STATE_FILENAME,
    PROACTIVE_OUTBOX_FILENAME,
    PROACTIVE_AUDIT_FILENAME,
    PROACTIVE_DISPATCH_RESULTS_FILENAME,
    STATUS_AUTH_STATE_FILENAME,
    STATUS_OUTBOX_FILENAME,
    STATUS_DISPATCH_RESULTS_FILENAME,
    CODEX_HISTORY_OUTBOX_FILENAME,
    CODEX_HISTORY_DISPATCH_RESULTS_FILENAME,
    CODEX_HISTORY_PROJECTS_FILENAME,
)
LEGACY_USER_MEMORY_DIRNAME = "users"
ACCOUNT_METADATA_SECRET_GUARD_PURPOSES = (INSTANCE_MAPPING_KEY_PURPOSE, INSTANCE_PEPPER_PURPOSE)


@dataclass(frozen=True)
class RecoverySource:
    name: str
    kind: str
    path: Path
    active: bool = True


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_account_memory_recovery_report(
    *,
    instances_dir: str | Path = DEFAULT_INSTANCES_DIR,
    instances: Sequence[str] = (),
    legacy_instances_dir: str | Path | None = None,
    provider: InstanceSecretProvider | None = None,
) -> dict[str, Any]:
    resolved_instances_dir = Path(instances_dir)
    resolved_legacy_instances_dir = Path(legacy_instances_dir).expanduser() if legacy_instances_dir else None
    provider = provider or ReadOnlySecretToolInstanceSecretProvider()
    selected_instances = discover_instances(resolved_instances_dir, instances)
    report: dict[str, Any] = {
        "schema_version": RECOVERY_SCHEMA_VERSION,
        "scope": "account_memory",
        "generated_at": utc_now(),
        "instances_dir": str(resolved_instances_dir),
        "instance_count": len(selected_instances),
        "instances": [],
        "totals": {
            "accounts": 0,
            "recoverable_accounts": 0,
            "unrecoverable_accounts": 0,
            "empty_accounts": 0,
            "no_source_accounts": 0,
            "sources": 0,
            "readable_sources": 0,
            "unreadable_sources": 0,
            "metadata_broken_instances": 0,
            "metadata_unreadable_items": 0,
            "metadata_unreadable_accounts": 0,
            "legacy_plaintext_sources": 0,
            "legacy_plaintext_entries": 0,
        },
    }
    if resolved_legacy_instances_dir is not None:
        report["legacy_instances_dir"] = str(resolved_legacy_instances_dir)
    for instance_name in selected_instances:
        instance_report = build_instance_recovery_report(
            instances_dir=resolved_instances_dir,
            instance_name=instance_name,
            legacy_instances_dir=resolved_legacy_instances_dir,
            provider=provider,
        )
        report["instances"].append(instance_report)
        _add_totals(report["totals"], instance_report)
    return report


def build_instance_recovery_report(
    *,
    instances_dir: Path,
    instance_name: str,
    legacy_instances_dir: Path | None = None,
    provider: InstanceSecretProvider,
) -> dict[str, Any]:
    normalized_name = str(instance_name or "").strip()
    if not normalized_name or discover_instances(instances_dir, (normalized_name,)) != (normalized_name,):
        raise ValueError(f"invalid instance name: {instance_name}")
    instance_name = normalized_name
    accounts_root = instances_dir / instance_name / "data" / "accounts"
    account_ids = _discover_account_ids(accounts_root)
    sources = _discover_recovery_sources(accounts_root)
    legacy_import = (
        _legacy_plaintext_import_report(
            legacy_instances_dir=legacy_instances_dir,
            target_instances_dir=instances_dir,
            instance_name=instance_name,
        )
        if legacy_instances_dir is not None
        else None
    )
    legacy_sources_by_account = _legacy_plaintext_sources_by_account(
        accounts_root=accounts_root,
        instance_name=instance_name,
        legacy_import=legacy_import,
        provider=provider,
    )
    legacy_instance_source_names = {
        str(source.get("name") or "")
        for sources_for_account in legacy_sources_by_account.values()
        for source in sources_for_account
        if str(source.get("name") or "")
    }
    account_reports = []
    for account_id in account_ids:
        source_reports = [_inspect_source(source, instance_name=instance_name, account_id=account_id, provider=provider) for source in sources]
        source_reports.extend(legacy_sources_by_account.get(account_id, []))
        recovery_status, recommendation = _account_recovery_status(source_reports)
        account_reports.append(
            {
                "account_id": account_id,
                "recoverable": recovery_status == "recoverable",
                "recovery_status": recovery_status,
                "recommendation": recommendation,
                "sources": source_reports,
            }
        )
    result = {
        "instance": instance_name,
        "accounts_root": str(accounts_root),
        "metadata_health": _metadata_health_report(accounts_root, instance_name, provider),
        "accounts": account_reports,
        "source_count": len(sources) + len(legacy_instance_source_names),
        "sources": [
            {"name": source.name, "kind": source.kind, "path": str(source.path), "active": source.active}
            for source in sources
        ]
        + [
            {
                "name": source_name,
                "kind": "legacy_plaintext",
                "path": _legacy_source_path_by_name(legacy_sources_by_account, source_name),
                "active": False,
            }
            for source_name in sorted(legacy_instance_source_names)
        ],
    }
    if legacy_import is not None:
        result["legacy_plaintext_import"] = legacy_import
    return result


def render_text_report(report: Mapping[str, Any]) -> str:
    lines = [
        "# TeeBotus Account-Memory Recovery Report",
        "",
        f"- generated_at: `{report.get('generated_at', '')}`",
        f"- instances_dir: `{report.get('instances_dir', '')}`",
        "",
        "## Totals",
        "",
    ]
    totals = report.get("totals", {})
    if isinstance(totals, Mapping):
        for key in sorted(totals):
            lines.append(f"- {key}: `{totals[key]}`")
    for instance in report.get("instances", []):
        if not isinstance(instance, Mapping):
            continue
        lines.extend(["", f"## Instance: {instance.get('instance', '')}", "", f"- source_count: `{instance.get('source_count', 0)}`"])
        metadata_health = instance.get("metadata_health")
        if isinstance(metadata_health, Mapping):
            lines.append(
                f"- metadata_health: readable=`{metadata_health.get('readable', False)}` "
                f"unreadable_items=`{metadata_health.get('unreadable_items', 0)}`"
            )
            for item in metadata_health.get("items", []):
                if not isinstance(item, Mapping):
                    continue
                account_ids = item.get("account_ids")
                account_text = f" accounts={', '.join(str(value)[:12] for value in account_ids)}" if isinstance(account_ids, list) and account_ids else ""
                lines.append(f"  - {item.get('kind', '')}: `{item.get('path', '')}`{account_text} error={item.get('error', '')}")
        legacy = instance.get("legacy_plaintext_import")
        if isinstance(legacy, Mapping):
            lines.append(
                f"- legacy_plaintext_import: status=`{legacy.get('status', '')}` "
                f"sources=`{legacy.get('sources', 0)}` entries=`{legacy.get('entries', 0)}` "
                f"requested_path_exists=`{legacy.get('requested_legacy_instances_dir_exists', False)}` "
                f"legacy_path_exists=`{legacy.get('legacy_instances_dir_exists', False)}` "
                f"users_path_exists=`{legacy.get('path_exists', False)}` "
                f"path=`{legacy.get('path', '')}`"
            )
            users = legacy.get("users")
            if isinstance(users, list) and users:
                user_text = ", ".join(f"{user.get('user_id')}({user.get('entries', 0)})" for user in users if isinstance(user, Mapping))
                if user_text:
                    lines.append(f"  - users: `{user_text}`")
            command = str(legacy.get("dry_run_command") or "").strip()
            if command:
                lines.append(f"  - dry_run_command: `{command}`")
            apply_command = str(legacy.get("apply_command") or "").strip()
            if apply_command:
                lines.append(f"  - apply_command: `{apply_command}`")
        for account in instance.get("accounts", []):
            if not isinstance(account, Mapping):
                continue
            lines.append("")
            lines.append(f"### Account: {account.get('account_id', '')}")
            lines.append(f"- recovery_status: `{account.get('recovery_status', 'unknown')}`")
            lines.append(f"- recoverable: `{account.get('recoverable', False)}`")
            recommendation = str(account.get("recommendation") or "").strip()
            if recommendation:
                lines.append(f"- recommendation: {recommendation}")
            for source in account.get("sources", []):
                if not isinstance(source, Mapping):
                    continue
                status = "readable" if source.get("readable") else "unreadable"
                role = "active" if source.get("active", True) is not False else "inactive"
                flags: list[str] = []
                if source.get("partial") is True:
                    flags.append("partial")
                elif source.get("fully_readable") is True:
                    flags.append("fully_readable")
                flag_text = f" ({', '.join(flags)})" if flags else ""
                detail = (
                    f"entries={source.get('entries', 0)} raw_entries={source.get('raw_entries', 0)} "
                    f"index_present={source.get('index_present', False)} "
                    f"raw_index_present={source.get('raw_index_present', False)} "
                    f"collections={source.get('collections', 0)} raw_collections={source.get('raw_collections', 0)}"
                )
                error = f" error={source.get('error')}" if source.get("error") else ""
                lines.append(f"  - {source.get('name', '')}: {role} {status}{flag_text} {detail}{error}")
    quarantine = report.get("quarantine")
    if isinstance(quarantine, Mapping):
        lines.extend(["", "## Quarantine", ""])
        lines.append(f"- status: `{quarantine.get('status', '')}`")
        lines.append(f"- mode: `{quarantine.get('mode', '')}`")
        lines.append(f"- base_dir: `{quarantine.get('base_dir', '')}`")
        safety = quarantine.get("apply_safety")
        if isinstance(safety, Mapping):
            lines.append(f"- running_bot_process_count: `{safety.get('running_bot_process_count', 0)}`")
            message = str(safety.get("message") or "").strip()
            if message:
                lines.append(f"- safety: {message}")
        totals = quarantine.get("totals")
        if isinstance(totals, Mapping):
            for key in sorted(totals):
                lines.append(f"- {key}: `{totals[key]}`")
    metadata_quarantine = report.get("metadata_quarantine")
    if isinstance(metadata_quarantine, Mapping):
        lines.extend(["", "## Metadata Quarantine", ""])
        lines.append(f"- status: `{metadata_quarantine.get('status', '')}`")
        lines.append(f"- mode: `{metadata_quarantine.get('mode', '')}`")
        lines.append(f"- base_dir: `{metadata_quarantine.get('base_dir', '')}`")
        safety = metadata_quarantine.get("apply_safety")
        if isinstance(safety, Mapping):
            lines.append(f"- running_bot_process_count: `{safety.get('running_bot_process_count', 0)}`")
            message = str(safety.get("message") or "").strip()
            if message:
                lines.append(f"- safety: {message}")
        totals = metadata_quarantine.get("totals")
        if isinstance(totals, Mapping):
            for key in sorted(totals):
                lines.append(f"- {key}: `{totals[key]}`")
    return "\n".join(lines) + "\n"


def quarantine_unrecoverable_account_memory(
    report: Mapping[str, Any],
    *,
    apply: bool = False,
    quarantine_dir: Path | None = None,
    allow_running_bot: bool = False,
    running_processes: Sequence[Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    running = [dict(process) for process in (running_processes if running_processes is not None else _running_teebotus_processes())]
    apply_allowed_now = _quarantine_apply_allowed_now(running, allow_running_bot=allow_running_bot)
    blocked = bool(apply and not apply_allowed_now)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    result: dict[str, Any] = {
        "schema_version": 1,
        "scope": "account_memory",
        "payload_kind": "encrypted_account_memory",
        "generated_at": utc_now(),
        "mode": "apply" if apply else "dry-run",
        "status": "blocked" if blocked else ("applied" if apply else "dry-run"),
        "base_dir": str(quarantine_dir or ""),
        "apply_safety": {
            "running_bot_processes": running,
            "running_bot_process_count": len(running),
            "apply_allowed_now": apply_allowed_now,
            "apply_requires_stopped_bot": bool(running and not allow_running_bot),
            "message": _quarantine_safety_message(running, allow_running_bot=allow_running_bot),
        },
        "totals": {
            "unrecoverable_accounts": 0,
            "accounts_quarantined": 0,
            "sqlite_sources": 0,
            "sqlite_rows_quarantined": 0,
            "json_files_quarantined": 0,
            "snapshots_created": 0,
        },
        "instances": [],
    }
    if blocked:
        return result
    for instance in report.get("instances", []) if isinstance(report.get("instances"), list) else []:
        if not isinstance(instance, Mapping):
            continue
        instance_result = _quarantine_instance_unrecoverable(
            instance,
            apply=apply,
            quarantine_dir=quarantine_dir,
            timestamp=timestamp,
        )
        if instance_result.get("status") == "blocked":
            result["status"] = "blocked"
            result["instances"].append(instance_result)
            continue
        result["instances"].append(instance_result)
        totals = result["totals"]
        for key in totals:
            totals[key] += int(instance_result.get("totals", {}).get(key, 0) or 0)
    if result["status"] != "blocked" and not result["totals"]["unrecoverable_accounts"]:
        result["status"] = "no-op"
    return result


def quarantine_unreadable_account_metadata(
    *,
    instances_dir: str | Path = DEFAULT_INSTANCES_DIR,
    instances: Sequence[str] = (),
    provider: InstanceSecretProvider | None = None,
    apply: bool = False,
    quarantine_dir: Path | None = None,
    allow_running_bot: bool = False,
    running_processes: Sequence[Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    resolved_instances_dir = Path(instances_dir)
    provider = provider or ReadOnlySecretToolInstanceSecretProvider()
    running = [dict(process) for process in (running_processes if running_processes is not None else _running_teebotus_processes())]
    apply_allowed_now = _quarantine_apply_allowed_now(running, allow_running_bot=allow_running_bot)
    blocked = bool(apply and not apply_allowed_now)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    result: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "mode": "apply" if apply else "dry-run",
        "status": "blocked" if blocked else ("applied" if apply else "dry-run"),
        "base_dir": str(quarantine_dir or ""),
        "apply_safety": {
            "running_bot_processes": running,
            "running_bot_process_count": len(running),
            "apply_allowed_now": apply_allowed_now,
            "apply_requires_stopped_bot": bool(running and not allow_running_bot),
            "message": _quarantine_safety_message(running, allow_running_bot=allow_running_bot),
        },
        "totals": {
            "instances_with_unreadable_metadata": 0,
            "items_quarantined": 0,
            "account_dirs_quarantined": 0,
        },
        "instances": [],
    }
    if blocked:
        return result
    for instance_name in discover_instances(resolved_instances_dir, instances):
        instance_result = _quarantine_instance_unreadable_metadata(
            instances_dir=resolved_instances_dir,
            instance_name=instance_name,
            provider=provider,
            apply=apply,
            quarantine_dir=quarantine_dir,
            timestamp=timestamp,
        )
        if instance_result.get("status") == "blocked":
            result["status"] = "blocked"
            result["instances"].append(instance_result)
            continue
        if instance_result["totals"]["items_quarantined"]:
            result["instances"].append(instance_result)
            result["totals"]["instances_with_unreadable_metadata"] += 1
            result["totals"]["items_quarantined"] += int(instance_result["totals"]["items_quarantined"])
            result["totals"]["account_dirs_quarantined"] += int(instance_result["totals"]["account_dirs_quarantined"])
    if result["status"] != "blocked" and not result["totals"]["items_quarantined"]:
        result["status"] = "no-op"
    return result


def _quarantine_instance_unreadable_metadata(
    *,
    instances_dir: Path,
    instance_name: str,
    provider: InstanceSecretProvider,
    apply: bool,
    quarantine_dir: Path | None,
    timestamp: str,
) -> dict[str, Any]:
    accounts_root = instances_dir / instance_name / "data" / "accounts"
    artifact_name = safe_artifact_name(instance_name, default="instance")
    instance_quarantine_dir = (
        quarantine_dir / artifact_name / "metadata" / timestamp
        if quarantine_dir is not None
        else accounts_root / "Account_Metadata_Quarantine" / timestamp
    )
    try:
        items = _unreadable_metadata_items(accounts_root, instance_name, provider)
    except (AccountStoreError, OSError, ValueError) as exc:
        items = [{"kind": "account_store", "path": accounts_root, "error": str(exc)}]
    result: dict[str, Any] = {
        "instance": instance_name,
        "accounts_root": str(accounts_root),
        "quarantine_dir": str(instance_quarantine_dir),
        "items": [
            {
                "kind": item["kind"],
                "path": str(item["path"]),
                "error": item["error"],
                "would_move": not apply,
            }
            for item in items
        ],
        "totals": {
            "items_quarantined": len(items),
            "account_dirs_quarantined": sum(1 for item in items if item["kind"] == "accounts_dir"),
        },
    }
    if apply:
        unsafe_items = [
            item
            for item in items
            if item.get("quarantine_safe") is False
            or not _metadata_error_is_safe_to_quarantine(str(item.get("error") or ""))
        ]
        if unsafe_items:
            result["status"] = "blocked"
            result["error"] = (
                "Refusing metadata quarantine because at least one read failure may be caused by an unavailable, "
                "missing, or changed secret rather than corrupted payload."
            )
            result["totals"]["items_quarantined"] = 0
            result["totals"]["account_dirs_quarantined"] = 0
            result["items"] = [
                {
                    "kind": item["kind"],
                    "path": str(item["path"]),
                    "error": item["error"],
                    "would_move": False,
                }
                for item in unsafe_items
            ]
            return result
    if not items or not apply:
        return result
    _prepare_private_dir(instance_quarantine_dir)
    moved_items = []
    for item in items:
        path = item["path"]
        if item["kind"] == "accounts_dir":
            account_ids = [
                str(account_id)
                for account_id in item.get("account_ids", [])
                if TOKEN_HEX_RE.fullmatch(str(account_id))
            ]
            moved_account_dirs = []
            for account_id in account_ids:
                account_dir = path / account_id
                if not account_dir.is_dir() or account_dir.is_symlink():
                    continue
                target = instance_quarantine_dir / "accounts" / account_id
                if target.exists():
                    target = instance_quarantine_dir / "accounts" / f"{account_id}.account_dir"
                _prepare_private_dir(target.parent)
                shutil.move(str(account_dir), str(target))
                moved_account_dirs.append(
                    {
                        "path": str(account_dir),
                        "quarantine_path": str(target),
                    }
                )
            moved_items.append(
                {
                    "kind": item["kind"],
                    "path": str(path),
                    "account_ids": account_ids,
                    "quarantine_paths": [entry["quarantine_path"] for entry in moved_account_dirs],
                    "error": item["error"],
                }
            )
            continue
        target = instance_quarantine_dir / path.name
        if target.exists():
            target = instance_quarantine_dir / f"{path.name}.{safe_artifact_name(item['kind'], default='item')}"
        _prepare_private_dir(target.parent)
        shutil.move(str(path), str(target))
        moved_items.append(
            {
                "kind": item["kind"],
                "path": str(path),
                "quarantine_path": str(target),
                "error": item["error"],
            }
        )
    result["items"] = moved_items
    manifest_path = instance_quarantine_dir / "manifest.json"
    _write_quarantine_manifest(manifest_path, result)
    return result


def _metadata_error_is_safe_to_quarantine(error: str) -> bool:
    lowered = str(error or "").casefold()
    if not lowered:
        return False
    unsafe_markers = (
        "secret-tool",
        "secret service",
        "instance secret is missing",
        "instance secret verifier mismatch",
        "encrypted envelope authentication failed",
        "keyring",
        "provider",
    )
    if any(marker in lowered for marker in unsafe_markers):
        return False
    corruption_markers = (
        "encrypted envelope is malformed",
        "encrypted envelope must be an object",
        "encrypted envelope fields are invalid",
        "encrypted envelope nonce has invalid length",
        "encrypted envelope ciphertext is empty",
        "encrypted json file is invalid",
        "encrypted json file must contain an object",
    )
    return any(marker in lowered for marker in corruption_markers)


def _unreadable_metadata_items(accounts_root: Path, instance_name: str, provider: InstanceSecretProvider) -> list[dict[str, Any]]:
    symlink_component = _first_symlinked_path_component(accounts_root)
    if symlink_component is not None:
        return [
            {
                "kind": "account_store",
                "path": accounts_root,
                "error": f"refusing symlinked metadata path component: {symlink_component}",
            }
        ]
    store = AccountStore(
        accounts_root,
        instance_name,
        secret_provider=provider,
        create_dirs=False,
        memory_backend_enabled=False,
        secret_guard_purposes=ACCOUNT_METADATA_SECRET_GUARD_PURPOSES,
    )
    items: list[dict[str, Any]] = []
    for kind, path, default in (
        ("account_index", store.account_index_path, {"schema_version": 1, "accounts": {}}),
        ("identity_mapping", store.identities_path, {}),
        ("account_secrets", store.secrets_path, {}),
    ):
        if path.is_symlink():
            items.append(
                {
                    "kind": kind,
                    "path": path,
                    "error": f"refusing symlinked metadata file: {path}",
                }
            )
            continue
        if not path.exists():
            continue
        try:
            store.vault.read_json(path, default)
        except AccountStoreError as exc:
            items.append({"kind": kind, "path": path, "error": str(exc)})
    accounts_dir = store.accounts_dir
    if accounts_dir.is_symlink():
        items.append(
            {
                "kind": "accounts_dir",
                "path": accounts_dir,
                "account_ids": [],
                "error": f"refusing symlinked accounts directory: {accounts_dir}",
                "quarantine_safe": False,
            }
        )
    elif accounts_dir.exists():
        unreadable_profiles: list[str] = []
        unreadable_profile_accounts: list[str] = []
        try:
            account_dirs = sorted(path for path in accounts_dir.iterdir() if TOKEN_HEX_RE.fullmatch(path.name))
        except OSError as exc:
            items.append(
                {
                    "kind": "accounts_dir",
                    "path": accounts_dir,
                    "account_ids": [],
                    "error": f"unable to inspect accounts directory: {exc}",
                    "quarantine_safe": False,
                }
            )
            account_dirs = []
        for account_dir in account_dirs:
            if account_dir.is_symlink():
                unreadable_profiles.append(f"{account_dir.name}:refusing symlinked account directory: {account_dir}")
                unreadable_profile_accounts.append(account_dir.name)
                continue
            if not account_dir.is_dir():
                continue
            profile_path = account_dir / ACCOUNT_PROFILE_FILENAME
            if profile_path.is_symlink():
                unreadable_profiles.append(f"{account_dir.name}:refusing symlinked metadata file: {profile_path}")
                unreadable_profile_accounts.append(account_dir.name)
                continue
            if not profile_path.exists():
                continue
            try:
                store.vault.read_json(profile_path, {})
            except AccountStoreError as exc:
                unreadable_profiles.append(f"{account_dir.name}:{exc}")
                unreadable_profile_accounts.append(account_dir.name)
        if unreadable_profiles:
            items.append(
                {
                    "kind": "accounts_dir",
                    "path": accounts_dir,
                    "account_ids": unreadable_profile_accounts,
                    "error": "; ".join(unreadable_profiles[:5]),
                    "quarantine_safe": all(
                        _metadata_error_is_safe_to_quarantine(error)
                        for error in unreadable_profiles
                    ),
                }
            )
    return items


def _metadata_health_report(accounts_root: Path, instance_name: str, provider: InstanceSecretProvider) -> dict[str, Any]:
    try:
        items = _unreadable_metadata_items(accounts_root, instance_name, provider)
    except (AccountStoreError, OSError, ValueError) as exc:
        items = [{"kind": "account_store", "path": accounts_root, "error": str(exc)}]
    normalized_items = []
    for item in items:
        account_ids = item.get("account_ids") if isinstance(item.get("account_ids"), list) else []
        normalized_items.append(
            {
                "kind": str(item.get("kind") or ""),
                "path": str(item.get("path") or ""),
                "account_ids": [str(account_id) for account_id in account_ids if TOKEN_HEX_RE.fullmatch(str(account_id))],
                "error": str(item.get("error") or ""),
            }
        )
    return {
        "readable": not normalized_items,
        "unreadable_items": len(normalized_items),
        "items": normalized_items,
    }


def _quarantine_instance_unrecoverable(
    instance_report: Mapping[str, Any],
    *,
    apply: bool,
    quarantine_dir: Path | None,
    timestamp: str,
) -> dict[str, Any]:
    instance_name = str(instance_report.get("instance") or "instance")
    accounts_root = Path(str(instance_report.get("accounts_root") or ""))
    artifact_name = safe_artifact_name(instance_name, default="instance")
    instance_quarantine_dir = (
        quarantine_dir / artifact_name / timestamp
        if quarantine_dir is not None
        else accounts_root / "Account_Memory_Quarantine" / timestamp
    )
    unrecoverable_accounts = [
        account
        for account in instance_report.get("accounts", [])
        if isinstance(account, Mapping) and str(account.get("recovery_status") or "") == "unrecoverable"
    ]
    account_ids = [str(account.get("account_id") or "") for account in unrecoverable_accounts if TOKEN_HEX_RE.fullmatch(str(account.get("account_id") or ""))]
    result: dict[str, Any] = {
        "instance": instance_name,
        "accounts_root": str(accounts_root),
        "quarantine_dir": str(instance_quarantine_dir),
        "account_ids": account_ids,
        "totals": {
            "unrecoverable_accounts": len(account_ids),
            "accounts_quarantined": 0,
            "sqlite_sources": 0,
            "sqlite_rows_quarantined": 0,
            "json_files_quarantined": 0,
            "snapshots_created": 0,
        },
        "sqlite_sources": [],
        "json_files": [],
    }
    if not account_ids:
        return result
    if (
        not str(instance_report.get("accounts_root") or "").strip()
        or _first_symlinked_path_component(accounts_root) is not None
        or not accounts_root.is_dir()
    ):
        result["status"] = "blocked"
        result["error"] = "Refusing quarantine because report accounts_root is missing, unsafe, or unavailable."
        result["totals"]["unrecoverable_accounts"] = 0
        result["account_ids"] = []
        return result
    sqlite_sources = _sqlite_sources_for_unrecoverable_accounts(unrecoverable_accounts, accounts_root=accounts_root)
    json_files = _json_memory_files_for_accounts(accounts_root, account_ids)
    result["totals"]["sqlite_sources"] = len(sqlite_sources)
    result["totals"]["json_files_quarantined"] = len(json_files)
    if not apply:
        result["totals"]["accounts_quarantined"] = len(account_ids)
        result["sqlite_sources"] = [
            {
                "path": str(path),
                "payload_kind": "encrypted_account_memory",
                "would_snapshot": True,
                "would_delete_rows": True,
            }
            for path in sqlite_sources
        ]
        result["json_files"] = [{"path": str(path), "would_move": True} for path in json_files]
        return result

    _prepare_private_dir(instance_quarantine_dir)
    snapshots_dir = instance_quarantine_dir / "sqlite_snapshots"
    snapshot_records = []
    for sqlite_path in sqlite_sources:
        snapshot_path = snapshots_dir / sqlite_path.name
        _snapshot_sqlite_database(sqlite_path, snapshot_path)
        result["totals"]["snapshots_created"] += 1
        snapshot_record = {
            "path": str(sqlite_path),
            "payload_kind": "encrypted_account_memory",
            "snapshot": str(snapshot_path),
            "rows_deleted": 0,
        }
        snapshot_records.append((sqlite_path, snapshot_record))
        result["sqlite_sources"].append(snapshot_record)
    moved_files = []
    for path in json_files:
        target = instance_quarantine_dir / "json_files" / path.parent.name / path.name
        _prepare_private_dir(target.parent)
        shutil.move(str(path), str(target))
        moved_files.append({"path": str(path), "quarantine_path": str(target)})
    result["json_files"] = moved_files
    result["totals"]["json_files_quarantined"] = len(moved_files)
    for sqlite_path, snapshot_record in snapshot_records:
        deleted_rows = _delete_sqlite_account_rows(sqlite_path, instance_name, account_ids)
        result["totals"]["sqlite_rows_quarantined"] += deleted_rows
        snapshot_record["rows_deleted"] = deleted_rows
    result["totals"]["accounts_quarantined"] = len(account_ids)
    manifest_path = instance_quarantine_dir / "manifest.json"
    _write_quarantine_manifest(manifest_path, result)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TeeBotus account-memory recovery report and unrecoverable-data quarantine.")
    parser.add_argument("--instances-dir", default=DEFAULT_INSTANCES_DIR)
    parser.add_argument("--instances", default="", help="Comma-separated instance list. Defaults to all folders with Bot_Verhalten.md.")
    parser.add_argument("--legacy-instances-dir", default="", help="Optional plaintext legacy instances directory to inspect for importable data/users memory.")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--output", default="")
    parser.add_argument("--quarantine-unrecoverable", action="store_true", help="Move unrecoverable encrypted account-memory payloads out of active stores.")
    parser.add_argument("--quarantine-unreadable-metadata", action="store_true", help="Move unreadable encrypted account metadata out of active stores.")
    parser.add_argument("--apply", action="store_true", help="Apply --quarantine-unrecoverable. Without this, only report what would move.")
    parser.add_argument("--quarantine-dir", default="", help="Optional base directory for quarantine artifacts. Defaults below each accounts root.")
    parser.add_argument("--allow-running-bot", action="store_true", help="Allow quarantine apply while TeeBotus runtime processes are running.")
    args = parser.parse_args(list(argv) if argv is not None else None)
    load_project_dotenv_for_instances(args.instances_dir)
    report = build_account_memory_recovery_report(
        instances_dir=args.instances_dir,
        instances=parse_csv(args.instances),
        legacy_instances_dir=args.legacy_instances_dir or None,
    )
    exit_code = 0
    if args.quarantine_unrecoverable:
        quarantine = quarantine_unrecoverable_account_memory(
            report,
            apply=args.apply,
            quarantine_dir=Path(args.quarantine_dir).expanduser() if args.quarantine_dir else None,
            allow_running_bot=args.allow_running_bot,
        )
        report["quarantine"] = quarantine
        if quarantine.get("status") == "blocked":
            exit_code = 3
    if args.quarantine_unreadable_metadata:
        metadata_quarantine = quarantine_unreadable_account_metadata(
            instances_dir=args.instances_dir,
            instances=parse_csv(args.instances),
            apply=args.apply,
            quarantine_dir=Path(args.quarantine_dir).expanduser() if args.quarantine_dir else None,
            allow_running_bot=args.allow_running_bot,
        )
        report["metadata_quarantine"] = metadata_quarantine
        if metadata_quarantine.get("status") == "blocked":
            exit_code = 3
    output = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n" if args.format == "json" else render_text_report(report)
    if args.output:
        try:
            Path(args.output).write_text(output, encoding="utf-8")
        except OSError as exc:
            print(f"account-memory-recovery: unable to write output: {exc}", file=sys.stderr)
            return 2
    else:
        print(output, end="")
    return exit_code


def _sqlite_sources_for_unrecoverable_accounts(
    accounts: Sequence[Mapping[str, Any]],
    *,
    accounts_root: Path | None = None,
) -> list[Path]:
    if accounts_root is None or _first_symlinked_path_component(accounts_root) is not None:
        return []
    try:
        resolved_root = accounts_root.resolve()
    except OSError:
        return []
    paths: list[Path] = []
    for account in accounts:
        for source in account.get("sources", []) if isinstance(account.get("sources"), list) else []:
            if not isinstance(source, Mapping) or source.get("kind") != "sqlite":
                continue
            if source.get("active", True) is False:
                continue
            if (
                _source_count(source, "raw_entries") <= 0
                and not bool(source.get("raw_index_present"))
                and _source_count(source, "raw_collections") <= 0
            ):
                continue
            raw_path = str(source.get("path") or "").strip()
            if not raw_path:
                continue
            path = Path(raw_path)
            try:
                path.resolve().relative_to(resolved_root)
            except (OSError, ValueError):
                continue
            if path not in paths:
                paths.append(path)
    return paths


def _json_memory_files_for_accounts(accounts_root: Path, account_ids: Sequence[str]) -> list[Path]:
    files: list[Path] = []
    accounts_dir = _safe_json_accounts_dir(accounts_root)
    if accounts_dir is None:
        return files
    for account_id in account_ids:
        account_dir = accounts_dir / account_id
        if account_dir.is_symlink() or not account_dir.is_dir():
            continue
        for filename in JSON_ACCOUNT_MEMORY_FILES:
            path = account_dir / filename
            if not path.is_symlink() and path.is_file():
                files.append(path)
    return files


def _safe_json_accounts_dir(accounts_root: Path) -> Path | None:
    accounts_dir = accounts_root / ACCOUNTS_DIRNAME
    if _first_symlinked_path_component(accounts_root) is not None or accounts_dir.is_symlink() or not accounts_dir.is_dir():
        return None
    return accounts_dir


def _snapshot_sqlite_database(source: Path, target: Path) -> None:
    _prepare_private_dir(target.parent)
    try:
        descriptor = os.open(os.fspath(target), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise AccountStoreError(f"refusing existing SQLite snapshot destination: {target}") from exc
    else:
        os.close(descriptor)
    with _connect_sqlite_readonly(source) as source_connection, sqlite3.connect(target) as target_connection:
        source_connection.backup(target_connection)
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass


def _delete_sqlite_account_rows(path: Path, instance_name: str, account_ids: Sequence[str]) -> int:
    deleted = 0
    _reject_unsafe_sqlite_link(path, label="source")
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists() or sidecar.is_symlink():
            _reject_unsafe_sqlite_link(sidecar, label="sidecar")
    with sqlite3.connect(path) as connection:
        with connection:
            for account_id in account_ids:
                if _sqlite_table_exists(connection, "memory_keywords"):
                    deleted += _delete_row_count(
                        connection.execute(
                            "DELETE FROM memory_keywords WHERE instance_name = ? AND account_id = ?",
                            (instance_name, account_id),
                        )
                    )
                if _sqlite_table_exists(connection, "memory_entries"):
                    deleted += _delete_row_count(
                        connection.execute(
                            "DELETE FROM memory_entries WHERE instance_name = ? AND account_id = ?",
                            (instance_name, account_id),
                        )
                    )
                if _sqlite_table_exists(connection, "memory_indexes"):
                    deleted += _delete_row_count(
                        connection.execute(
                            "DELETE FROM memory_indexes WHERE instance_name = ? AND account_id = ?",
                            (instance_name, account_id),
                        )
                    )
                if _sqlite_table_exists(connection, "account_jsonl_collections"):
                    deleted += _delete_row_count(
                        connection.execute(
                            "DELETE FROM account_jsonl_collections WHERE instance_name = ? AND account_id = ?",
                            (instance_name, account_id),
                        )
                    )
    return deleted


def _delete_row_count(cursor: sqlite3.Cursor) -> int:
    return max(0, int(cursor.rowcount if cursor.rowcount is not None else 0))


def _prepare_private_dir(path: Path) -> None:
    absolute = Path(os.path.abspath(os.fspath(path)))
    symlink_component = _first_symlinked_path_component(absolute)
    if symlink_component is not None:
        raise AccountStoreError(f"refusing symlinked quarantine directory: {symlink_component}")
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise AccountStoreError(f"refusing unsafe quarantine directory: {path}")
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


def _write_quarantine_manifest(path: Path, payload: Mapping[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        descriptor = os.open(os.fspath(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise AccountStoreError(f"refusing existing quarantine manifest: {path}") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(serialized)


def _first_symlinked_path_component(path: Path) -> Path | None:
    absolute = Path(os.path.abspath(os.fspath(path)))
    for candidate in (absolute, *absolute.parents):
        try:
            if candidate.is_symlink():
                return candidate
        except OSError:
            return candidate
    return None


def _quarantine_apply_allowed_now(running_processes: Sequence[Mapping[str, str]], *, allow_running_bot: bool) -> bool:
    return bool(allow_running_bot or not running_processes)


def _quarantine_safety_message(running_processes: Sequence[Mapping[str, str]], *, allow_running_bot: bool) -> str:
    if not running_processes:
        return "No TeeBotus runtime process detected; quarantine apply may run after reviewing the report."
    if allow_running_bot:
        return "--allow-running-bot was set; quarantine apply is intentionally allowed despite detected runtime processes."
    return "TeeBotus runtime processes are running; stop bot/proactive jobs before applying quarantine."


def _running_teebotus_processes() -> list[dict[str, str]]:
    current_pid = os.getpid()
    processes: list[dict[str, str]] = []
    proc_root = Path("/proc")
    if not proc_root.exists():
        return processes
    for pid_dir in proc_root.iterdir():
        if not pid_dir.name.isdigit() or int(pid_dir.name) == current_pid:
            continue
        try:
            raw = (pid_dir / "cmdline").read_bytes()
        except OSError:
            continue
        if not raw:
            continue
        parts = [part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part]
        cmdline = " ".join(parts)
        lowered = cmdline.casefold()
        if "teebotus.admin" in lowered or "memory-recovery" in lowered or "--runtime-status" in lowered:
            continue
        if _looks_like_running_teebotus_runtime(lowered):
            processes.append({"pid": pid_dir.name, "cmdline": cmdline[:500]})
    return processes


def _looks_like_running_teebotus_runtime(cmdline_lower: str) -> bool:
    padded = f"{cmdline_lower} "
    return (
        "teebotus-proactive" in cmdline_lower
        or "-m teebotus " in padded
        or "-m teebotus.proactive " in padded
    )


def _discover_account_ids(accounts_root: Path) -> list[str]:
    account_ids: set[str] = set()
    accounts_dir = _safe_json_accounts_dir(accounts_root)
    if accounts_dir is not None:
        try:
            account_dirs = list(accounts_dir.iterdir())
        except OSError:
            account_dirs = ()
        account_ids.update(
            path.name
            for path in account_dirs
            if not path.is_symlink()
            and path.is_dir()
            and TOKEN_HEX_RE.fullmatch(path.name)
            and path.name != INSTANCE_STATE_ACCOUNT_ID
        )
    for source in _discover_recovery_sources(accounts_root):
        if source.active and source.kind == "sqlite":
            account_ids.update(_sqlite_account_ids(source.path))
    return sorted(account_ids)


def _discover_recovery_sources(accounts_root: Path) -> list[RecoverySource]:
    sources: list[RecoverySource] = []
    for name, path in (
        ("sqlite_primary", accounts_root / "Account_Memory.sqlite3"),
        ("sqlite_fallback", accounts_root / "Account_Memory.backup.sqlite3"),
    ):
        if path.exists():
            sources.append(RecoverySource(name, "sqlite", path))
    accounts_dir = _safe_json_accounts_dir(accounts_root)
    if accounts_dir is not None:
        sources.append(RecoverySource("json_files", "json", accounts_dir))
    sources.extend(_discover_snapshot_sqlite_sources(accounts_root, existing_paths={source.path.resolve() for source in sources}))
    return sources


def _discover_snapshot_sqlite_sources(accounts_root: Path, *, existing_paths: set[Path]) -> list[RecoverySource]:
    candidates = [
        *accounts_root.glob(".pre-*/Account_Memory*.sqlite3"),
        *accounts_root.glob("Account_Memory_Quarantine/*/sqlite_snapshots/Account_Memory*.sqlite3"),
    ]
    sources: list[RecoverySource] = []
    seen_names: set[str] = set()
    for path in sorted(candidates):
        resolved = path.resolve()
        if resolved in existing_paths or path.is_symlink() or not path.is_file():
            continue
        name = _snapshot_source_name(accounts_root, path, seen_names=seen_names)
        sources.append(RecoverySource(name, "sqlite", path, active=False))
    return sources


def _snapshot_source_name(accounts_root: Path, path: Path, *, seen_names: set[str]) -> str:
    try:
        relative = path.relative_to(accounts_root)
    except ValueError:
        relative = path.name
    base = f"sqlite_snapshot_{safe_artifact_name(relative, default='snapshot')}"
    name = base
    suffix = 2
    while name in seen_names:
        name = f"{base}_{suffix}"
        suffix += 1
    seen_names.add(name)
    return name


def _inspect_source(source: RecoverySource, *, instance_name: str, account_id: str, provider: InstanceSecretProvider) -> dict[str, Any]:
    if source.kind == "sqlite":
        return _inspect_sqlite_source(source, instance_name=instance_name, account_id=account_id, provider=provider)
    return _inspect_json_source(source, instance_name=instance_name, account_id=account_id, provider=provider)


def _inspect_sqlite_source(source: RecoverySource, *, instance_name: str, account_id: str, provider: InstanceSecretProvider) -> dict[str, Any]:
    raw_entries, raw_index_present, raw_collections = _sqlite_raw_counts(source.path, instance_name, account_id)
    return _inspect_sqlite_snapshot_source(
        source,
        instance_name=instance_name,
        account_id=account_id,
        provider=provider,
        raw_entries=raw_entries,
        raw_index_present=raw_index_present,
        raw_collections=raw_collections,
    )


def _inspect_sqlite_snapshot_source(
    source: RecoverySource,
    *,
    instance_name: str,
    account_id: str,
    provider: InstanceSecretProvider,
    raw_entries: int,
    raw_index_present: bool,
    raw_collections: int,
) -> dict[str, Any]:
    entries, index, collections, errors = _read_sqlite_snapshot_payloads(
        source.path,
        instance_name=instance_name,
        account_id=account_id,
        provider=provider,
    )
    return {
        "name": source.name,
        "kind": source.kind,
        "payload_kind": "encrypted_account_memory",
        "path": str(source.path),
        "active": source.active,
        "readable": bool(not errors or entries or index or collections),
        "fully_readable": not errors,
        "partial": bool(errors and (entries or index or collections)),
        "entries": len(entries),
        "raw_entries": raw_entries,
        "index_present": bool(index),
        "raw_index_present": raw_index_present,
        "collections": len(collections),
        "raw_collections": raw_collections,
        "error": "; ".join(errors),
    }


def _read_sqlite_snapshot_payloads(
    path: Path,
    *,
    instance_name: str,
    account_id: str,
    provider: InstanceSecretProvider,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]], list[str]]:
    backend = SQLiteAccountMemoryBackend(
        instance_name=instance_name,
        provider=provider,
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=path, fallback_path=None),
    )
    entries: list[dict[str, Any]] = []
    index: dict[str, Any] = {}
    collections: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        with _connect_sqlite_readonly(path) as connection:
            if _sqlite_table_exists(connection, "memory_entries"):
                rows = connection.execute(
                    """
                    SELECT memory_id, payload_nonce, payload_ciphertext
                    FROM memory_entries
                    WHERE instance_name = ? AND account_id = ?
                    ORDER BY ordinal ASC, created_at ASC, memory_id ASC
                    """,
                    (instance_name, account_id),
                ).fetchall()
                skipped_error = ""
                for row in rows:
                    memory_id = str(row[0])
                    try:
                        entries.append(backend._decrypt_json(account_id, memory_id, bytes(row[1]), bytes(row[2])))
                    except AccountStoreError as exc:
                        skipped_error = skipped_error or str(exc)
                if skipped_error:
                    errors.append(f"entries: {skipped_error}")
            if _sqlite_table_exists(connection, "memory_indexes"):
                row = connection.execute(
                    """
                    SELECT payload_nonce, payload_ciphertext
                    FROM memory_indexes
                    WHERE instance_name = ? AND account_id = ?
                    """,
                    (instance_name, account_id),
                ).fetchone()
                if row is not None:
                    try:
                        index = backend._decrypt_json(account_id, "index", bytes(row[0]), bytes(row[1]))
                    except AccountStoreError as exc:
                        errors.append(f"index: {exc}")
            if _sqlite_table_exists(connection, "account_jsonl_collections"):
                rows = connection.execute(
                    """
                    SELECT collection, item_key, payload_nonce, payload_ciphertext
                    FROM account_jsonl_collections
                    WHERE instance_name = ? AND account_id = ?
                    ORDER BY collection ASC, ordinal ASC
                    """,
                    (instance_name, account_id),
                ).fetchall()
                skipped_error = ""
                for row in rows:
                    collection = str(row[0])
                    item_key = str(row[1])
                    try:
                        collections.append(
                            backend._decrypt_json(account_id, f"jsonl:{collection}:{item_key}", bytes(row[2]), bytes(row[3]))
                        )
                    except AccountStoreError as exc:
                        skipped_error = skipped_error or str(exc)
                if skipped_error:
                    errors.append(f"collections: {skipped_error}")
    except (sqlite3.Error, OSError) as exc:
        errors.append(f"sqlite: {exc}")
    return entries, index, collections, errors


def _inspect_json_source(source: RecoverySource, *, instance_name: str, account_id: str, provider: InstanceSecretProvider) -> dict[str, Any]:
    try:
        store = _JsonProbeStore(source.path.parent, instance_name, secret_provider=provider, create_dirs=False)
    except (AccountStoreError, OSError, ValueError) as exc:
        return {
            "name": source.name,
            "kind": source.kind,
            "payload_kind": "encrypted_account_memory",
            "path": str(source.path),
            "active": source.active,
            "readable": False,
            "entries": 0,
            "raw_entries": 0,
            "index_present": False,
            "raw_index_present": False,
            "collections": 0,
            "raw_collections": 0,
            "error": f"store: {exc}",
        }
    entries_path = source.path / account_id / USER_MEMORY_ENTRIES_FILENAME
    index_path = source.path / account_id / USER_MEMORY_INDEX_FILENAME
    errors = []
    entries: list[dict[str, Any]] = []
    index: dict[str, Any] = {}
    collections = 0
    raw_collections = 0
    symlink_component = _first_symlinked_path_component(source.path / account_id)
    if symlink_component is not None:
        return {
            "name": source.name,
            "kind": source.kind,
            "payload_kind": "encrypted_account_memory",
            "path": str(source.path),
            "active": source.active,
            "readable": False,
            "entries": 0,
            "raw_entries": 0,
            "index_present": False,
            "raw_index_present": False,
            "collections": 0,
            "raw_collections": 0,
            "error": f"refusing symlinked JSON recovery path: {symlink_component}",
        }
    if entries_path.exists():
        if entries_path.is_symlink():
            errors.append(f"entries: refusing symlinked JSON recovery file: {entries_path}")
        else:
            try:
                entries = store.account_memory_vault.read_jsonl(entries_path)
            except (AccountStoreError, OSError, ValueError) as exc:
                errors.append(f"entries: {exc}")
    if index_path.exists():
        if index_path.is_symlink():
            errors.append(f"index: refusing symlinked JSON recovery file: {index_path}")
        else:
            try:
                index = store.account_memory_vault.read_json(index_path, {})
            except (AccountStoreError, OSError, ValueError) as exc:
                errors.append(f"index: {exc}")
    for filename in JSON_ACCOUNT_STATE_FILES:
        path = source.path / account_id / filename
        if path.is_symlink():
            errors.append(f"{filename}: refusing symlinked JSON recovery file: {path}")
            continue
        if not path.exists():
            continue
        if filename.endswith(".jsonl"):
            raw_collections += _count_lines(path)
            try:
                collections += len(store.account_memory_vault.read_jsonl(path))
            except (AccountStoreError, OSError, ValueError) as exc:
                errors.append(f"{filename}: {exc}")
        else:
            raw_collections += 1
            try:
                data = store.account_memory_vault.read_json(path, {})
            except (AccountStoreError, OSError, ValueError) as exc:
                errors.append(f"{filename}: {exc}")
            else:
                if data:
                    collections += 1
    return {
        "name": source.name,
        "kind": source.kind,
        "payload_kind": "encrypted_account_memory",
        "path": str(source.path),
        "active": source.active,
        "readable": not errors,
        "entries": len(entries),
        "raw_entries": _count_lines(entries_path) if entries_path.is_file() and not entries_path.is_symlink() else 0,
        "index_present": bool(index),
        "raw_index_present": index_path.is_file() and not index_path.is_symlink(),
        "collections": collections,
        "raw_collections": raw_collections,
        "error": "; ".join(errors),
    }


class _JsonProbeStore:
    def __init__(self, root: Path, instance_name: str, *, secret_provider: InstanceSecretProvider, create_dirs: bool = False) -> None:
        from TeeBotus.runtime.accounts import AccountStore

        self._store = AccountStore(
            root,
            instance_name,
            secret_provider=secret_provider,
            create_dirs=create_dirs,
            memory_backend_enabled=False,
        )

    @property
    def account_memory_vault(self):
        return self._store.account_memory_vault


def _sqlite_account_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        with _connect_sqlite_readonly(path) as connection:
            ids = set()
            for table in SQLITE_MEMORY_TABLES:
                if not _sqlite_table_exists(connection, table):
                    continue
                ids.update(str(row[0]) for row in connection.execute(f"SELECT DISTINCT account_id FROM {table}"))
            return {
                account_id
                for account_id in ids
                if TOKEN_HEX_RE.fullmatch(account_id) and account_id != INSTANCE_STATE_ACCOUNT_ID
            }
    except (sqlite3.Error, OSError):
        return set()


def _sqlite_raw_counts(path: Path, instance_name: str, account_id: str) -> tuple[int, bool, int]:
    try:
        with _connect_sqlite_readonly(path) as connection:
            entries = 0
            index_present = False
            collections = 0
            if _sqlite_table_exists(connection, "memory_entries"):
                entries = int(
                    connection.execute(
                        "SELECT count(*) FROM memory_entries WHERE instance_name = ? AND account_id = ?",
                        (instance_name, account_id),
                    ).fetchone()[0]
                )
            if _sqlite_table_exists(connection, "memory_indexes"):
                index_present = (
                    connection.execute(
                        "SELECT 1 FROM memory_indexes WHERE instance_name = ? AND account_id = ? LIMIT 1",
                        (instance_name, account_id),
                    ).fetchone()
                    is not None
                )
            if _sqlite_table_exists(connection, "account_jsonl_collections"):
                collections = int(
                    connection.execute(
                        "SELECT count(*) FROM account_jsonl_collections WHERE instance_name = ? AND account_id = ?",
                        (instance_name, account_id),
                    ).fetchone()[0]
                )
            return entries, index_present, collections
    except (sqlite3.Error, OSError):
        return 0, False, 0


@contextlib.contextmanager
def _connect_sqlite_readonly(path: Path):
    _reject_unsafe_sqlite_link(path, label="source")
    if not path.exists():
        raise sqlite3.OperationalError(f"database does not exist: {path}")
    with tempfile.TemporaryDirectory(prefix="teebotus-sqlite-readonly-") as temp_dir:
        copied_path = Path(temp_dir) / path.name
        shutil.copy2(path, copied_path)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(path) + suffix)
            if sidecar.exists() or sidecar.is_symlink():
                _reject_unsafe_sqlite_link(sidecar, label="sidecar")
                shutil.copy2(sidecar, Path(str(copied_path) + suffix))
        connection = sqlite3.connect(f"{copied_path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            yield connection
        finally:
            connection.close()


def _reject_unsafe_sqlite_link(path: Path, *, label: str) -> None:
    if path.is_symlink():
        raise OSError(f"refusing symlinked SQLite recovery {label}: {path}")
    symlink_component = _first_symlinked_path_component(path)
    if symlink_component is not None:
        raise OSError(f"refusing symlinked SQLite recovery path component: {symlink_component}")
    if path.exists() and path.stat().st_nlink > 1:
        raise OSError(f"refusing hardlinked SQLite recovery {label}: {path}")


def _sqlite_table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table,)).fetchone() is not None


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return sum(1 for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())
    except OSError:
        return 0


def _legacy_plaintext_import_report(*, legacy_instances_dir: Path, target_instances_dir: Path, instance_name: str) -> dict[str, Any]:
    requested_path_exists = legacy_instances_dir.exists()
    effective_legacy_instances_dir = _resolve_legacy_instances_dir(legacy_instances_dir, instance_name)
    instance_users_dir = effective_legacy_instances_dir / instance_name / "data" / LEGACY_USER_MEMORY_DIRNAME
    legacy_path_exists = effective_legacy_instances_dir.exists()
    users_path_exists = instance_users_dir.exists()
    sources = 0
    entries = 0
    encrypted_sources = 0
    malformed_sources = 0
    users: list[dict[str, Any]] = []
    if instance_users_dir.exists():
        for user_dir in sorted(path for path in instance_users_dir.iterdir() if path.is_dir()):
            entries_path = user_dir / USER_MEMORY_ENTRIES_FILENAME
            if not entries_path.exists():
                continue
            source_kind, source_entries = _legacy_entries_file_shape(entries_path)
            if source_kind == "plaintext":
                sources += 1
                entries += source_entries
                users.append({"user_id": user_dir.name, "entries": source_entries, "path": str(user_dir)})
            elif source_kind == "encrypted":
                encrypted_sources += 1
            else:
                malformed_sources += 1
    artifact_name = safe_artifact_name(instance_name, default="instance")
    command = shlex.join(
        [
            "python3",
            "scripts/import_legacy_user_memory.py",
            "--legacy-instances-dir",
            str(legacy_instances_dir),
            "--target-instances-dir",
            str(target_instances_dir),
            "--instance",
            instance_name,
            "--replace-unreadable",
            "--replace-unreadable-account-metadata",
            "--json-output",
            str(legacy_import_preflight_path(artifact_name, ext=".json")),
            "--markdown-output",
            str(legacy_import_preflight_path(artifact_name, ext=".md")),
        ]
    )
    apply_command = shlex.join(
        [
            "python3",
            "scripts/import_legacy_user_memory.py",
            "--legacy-instances-dir",
            str(legacy_instances_dir),
            "--target-instances-dir",
            str(target_instances_dir),
            "--instance",
            instance_name,
            "--replace-unreadable",
            "--replace-unreadable-account-metadata",
            "--apply",
        ]
    )
    return {
        "requested_legacy_instances_dir": str(legacy_instances_dir),
        "requested_legacy_instances_dir_exists": requested_path_exists,
        "legacy_instances_dir": str(effective_legacy_instances_dir),
        "legacy_instances_dir_exists": legacy_path_exists,
        "path": str(instance_users_dir),
        "path_exists": users_path_exists,
        "status": _legacy_plaintext_import_status(
            requested_path_exists=requested_path_exists,
            users_path_exists=users_path_exists,
            sources=sources,
            encrypted_sources=encrypted_sources,
            malformed_sources=malformed_sources,
        ),
        "sources": sources,
        "entries": entries,
        "users": users,
        "encrypted_sources": encrypted_sources,
        "malformed_sources": malformed_sources,
        "dry_run_command": command,
        "apply_command": apply_command,
        "apply_requires": "--apply plus explicit review of metadata/account-memory replacement flags",
    }


def _legacy_plaintext_import_status(
    *,
    requested_path_exists: bool,
    users_path_exists: bool,
    sources: int,
    encrypted_sources: int,
    malformed_sources: int,
) -> str:
    if not requested_path_exists:
        return "missing"
    if sources:
        return "available"
    if encrypted_sources:
        return "encrypted-only"
    if malformed_sources:
        return "malformed-only"
    if not users_path_exists:
        return "no-users-path"
    return "empty"


def _legacy_plaintext_sources_by_account(
    *,
    accounts_root: Path,
    instance_name: str,
    legacy_import: Mapping[str, Any] | None,
    provider: InstanceSecretProvider,
) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(legacy_import, Mapping) or legacy_import.get("status") != "available":
        return {}
    users = legacy_import.get("users")
    if not isinstance(users, list) or not users:
        return {}
    try:
        store = AccountStore(
            accounts_root,
            instance_name,
            secret_provider=provider,
            create_dirs=False,
            memory_backend_enabled=False,
        )
    except AccountStoreError:
        return {}
    sources_by_account: dict[str, list[dict[str, Any]]] = {}
    for user in users:
        if not isinstance(user, Mapping):
            continue
        user_id = str(user.get("user_id") or "").strip()
        if not user_id:
            continue
        try:
            identity = telegram_identity_key(user_id)
            account_id = store.get_account_for_identity(identity)
        except AccountStoreError:
            continue
        if not account_id:
            continue
        entries = _source_count(user, "entries")
        source = {
            "name": f"legacy_plaintext_import_{user_id}",
            "kind": "legacy_plaintext",
            "payload_kind": "legacy_plaintext_user_memory",
            "path": str(user.get("path") or ""),
            "active": False,
            "readable": True,
            "entries": entries,
            "raw_entries": entries,
            "index_present": False,
            "raw_index_present": False,
            "error": "",
            "identity": identity,
            "legacy_user_id": user_id,
            "import_action": "import_legacy_user_memory",
        }
        sources_by_account.setdefault(account_id, []).append(source)
    return sources_by_account


def _legacy_source_path_by_name(sources_by_account: Mapping[str, Sequence[Mapping[str, Any]]], source_name: str) -> str:
    for sources in sources_by_account.values():
        for source in sources:
            if str(source.get("name") or "") == source_name:
                return str(source.get("path") or "")
    return ""


def _resolve_legacy_instances_dir(path: Path, instance_name: str) -> Path:
    if (path / instance_name / "data" / LEGACY_USER_MEMORY_DIRNAME).exists():
        return path
    candidates: list[tuple[int, int, str, Path]] = []
    for child in sorted(path.iterdir()) if path.exists() and path.is_dir() else []:
        if not child.is_dir() or not child.name.startswith("instances"):
            continue
        users_dir = child / instance_name / "data" / LEGACY_USER_MEMORY_DIRNAME
        if not users_dir.exists():
            continue
        sources = 0
        entries = 0
        for user_dir in sorted(user_dir for user_dir in users_dir.iterdir() if user_dir.is_dir()):
            source_kind, source_entries = _legacy_entries_file_shape(user_dir / USER_MEMORY_ENTRIES_FILENAME)
            if source_kind != "plaintext":
                continue
            sources += 1
            entries += source_entries
        if sources:
            candidates.append((entries, sources, child.name, child))
    if not candidates:
        return path
    candidates.sort(key=lambda item: (item[0], item[1], _legacy_candidate_priority(item[2])), reverse=True)
    return candidates[0][3]


def _legacy_candidate_priority(name: str) -> int:
    if name == "instances.bak":
        return 3
    if name.startswith("instances.bak"):
        return 2
    if name == "instances":
        return 1
    return 0


def _legacy_entries_file_shape(path: Path) -> tuple[str, int]:
    entries = 0
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "malformed", 0
    for line in lines:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return "malformed", entries
        if not isinstance(data, dict):
            return "malformed", entries
        if {"version", "nonce", "ciphertext"}.issubset(data):
            return "encrypted", entries
        entries += 1
    return "plaintext", entries


def _account_recovery_status(source_reports: Sequence[Mapping[str, Any]]) -> tuple[str, str]:
    if not source_reports:
        return "no_sources", "No account-memory source exists for this account."
    readable_payload_sources = [
        source
        for source in source_reports
        if source.get("readable")
        and (
            _source_count(source, "entries") > 0
            or bool(source.get("index_present"))
            or _source_count(source, "collections") > 0
        )
    ]
    if readable_payload_sources:
        names = ", ".join(str(source.get("name") or "<unknown>") for source in readable_payload_sources)
        return "recoverable", f"Recover from readable source(s): {names}."
    raw_payload_sources = [
        source
        for source in source_reports
        if source.get("active", True) is not False
        and not source.get("readable")
        and (
            _source_count(source, "raw_entries") > 0
            or bool(source.get("raw_index_present"))
            or _source_count(source, "raw_collections") > 0
        )
    ]
    inactive_raw_payload_sources = [
        source
        for source in source_reports
        if source.get("active", True) is False
        and not source.get("readable")
        and (
            _source_count(source, "raw_entries") > 0
            or bool(source.get("raw_index_present"))
            or _source_count(source, "raw_collections") > 0
        )
    ]
    if raw_payload_sources:
        return (
            "unrecoverable",
            "Raw encrypted payloads exist, but no source is readable with the current instance secret; keep backups and restore the matching old secret if available.",
        )
    readable_empty_sources = [source for source in source_reports if source.get("active", True) is not False and source.get("readable")]
    if readable_empty_sources:
        if inactive_raw_payload_sources:
            names = ", ".join(str(source.get("name") or "<unknown>") for source in inactive_raw_payload_sources)
            return (
                "empty",
                f"Active sources are readable but empty; inactive snapshots contain encrypted payloads that are not readable with the current instance key. Snapshot sources: {names}.",
            )
        return "empty", "Sources are readable but contain no memory payloads for this account."
    if source_reports:
        if inactive_raw_payload_sources:
            names = ", ".join(str(source.get("name") or "<unknown>") for source in inactive_raw_payload_sources)
            return (
                "no_sources",
                f"Only inactive snapshots exist for this account, and encrypted payloads are not readable with the current instance key. Snapshot sources: {names}.",
            )
        return "no_sources", "Only inactive snapshots exist for this account and none is readable with the current instance secret."
    return "unrecoverable", "No source is readable with the current instance secret; keep backups before changing account-memory files."


def _source_count(source: Mapping[str, Any], key: str) -> int:
    value = source.get(key, 0)
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _add_totals(totals: dict[str, int], instance_report: Mapping[str, Any]) -> None:
    metadata = instance_report.get("metadata_health")
    if isinstance(metadata, Mapping):
        items = metadata.get("items") if isinstance(metadata.get("items"), list) else []
        if metadata.get("readable") is False or items:
            totals["metadata_broken_instances"] += 1
        totals["metadata_unreadable_items"] += len(items)
        unreadable_accounts: set[str] = set()
        for item in items:
            if not isinstance(item, Mapping):
                continue
            account_ids = item.get("account_ids") if isinstance(item.get("account_ids"), list) else []
            unreadable_accounts.update(str(account_id) for account_id in account_ids if TOKEN_HEX_RE.fullmatch(str(account_id)))
        totals["metadata_unreadable_accounts"] += len(unreadable_accounts)
    for account in instance_report.get("accounts", []) if isinstance(instance_report.get("accounts"), list) else []:
        if not isinstance(account, Mapping):
            continue
        totals["accounts"] += 1
        recovery_status = str(account.get("recovery_status") or "")
        if account.get("recoverable"):
            totals["recoverable_accounts"] += 1
        if recovery_status == "unrecoverable":
            totals["unrecoverable_accounts"] += 1
        elif recovery_status == "empty":
            totals["empty_accounts"] += 1
        elif recovery_status == "no_sources":
            totals["no_source_accounts"] += 1
        for source in account.get("sources", []) if isinstance(account.get("sources"), list) else []:
            if not isinstance(source, Mapping):
                continue
            totals["sources"] += 1
            if source.get("readable"):
                totals["readable_sources"] += 1
            else:
                totals["unreadable_sources"] += 1
    legacy = instance_report.get("legacy_plaintext_import")
    if isinstance(legacy, Mapping):
        totals["legacy_plaintext_sources"] += _source_count(legacy, "sources")
        totals["legacy_plaintext_entries"] += _source_count(legacy, "entries")


__all__ = [
    "build_account_memory_recovery_report",
    "build_instance_recovery_report",
    "main",
    "render_text_report",
]


if __name__ == "__main__":
    raise SystemExit(main())
