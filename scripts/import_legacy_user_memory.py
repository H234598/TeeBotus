#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from TeeBotus.runtime.accounts import (  # noqa: E402
    AccountStore,
    AccountStoreError,
    SecretToolInstanceSecretProvider,
    USER_MEMORY_ENTRIES_FILENAME,
    USER_MEMORY_INDEX_FILENAME,
    telegram_identity_key,
)
from TeeBotus.runtime.postgres_memory import POSTGRES_BACKEND_ENV  # noqa: E402
from TeeBotus.runtime.sqlite_memory import SQLITE_BACKEND_ENV, SQLITE_DEFAULT_FALLBACK_FILENAME, SQLITE_DEFAULT_FILENAME  # noqa: E402


USER_MEMORY_LEGACY_ROOT = "users"
TEEBOTUS_MODULE_RUNTIME_RE = re.compile(r"(?:^|\s)-m\s+teebotus(?:\s|$)")


class LegacyPlaintextReadError(ValueError):
    def __init__(self, message: str, *, source_kind: str) -> None:
        super().__init__(message)
        self.source_kind = source_kind


@dataclass
class ImportStats:
    sources: int = 0
    imported_sources: int = 0
    skipped_sources: int = 0
    malformed_sources: int = 0
    encrypted_sources: int = 0
    entries_seen: int = 0
    entries_imported: int = 0
    accounts_created: int = 0
    accounts_existing: int = 0
    unreadable_targets: int = 0
    unreadable_metadata: int = 0
    backups_created: int = 0
    metadata_backups_created: int = 0
    account_store_resets: int = 0
    requested_legacy_instances_dir: str = ""
    effective_legacy_instances_dir: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import plaintext legacy data/users/* user memories into encrypted account memory.")
    parser.add_argument(
        "--legacy-instances-dir",
        required=True,
        help="Legacy instances directory or backup root, e.g. /home/teladi/TeeBotus.bak2 or /home/teladi/TeeBotus.bak2/instances.bak.",
    )
    parser.add_argument("--target-instances-dir", default="instances", help="Current TeeBotus instances directory.")
    parser.add_argument("--instance", action="append", default=[], help="Instance to import. Can be repeated.")
    parser.add_argument("--backend", choices=("sqlite", "json", "env"), default="sqlite", help="Target account-memory backend override.")
    parser.add_argument("--apply", action="store_true", help="Write imported memories. Without this, only dry-run.")
    parser.add_argument(
        "--replace-unreadable",
        action="store_true",
        help="Allow replacing unreadable target account-memory rows after backing up current SQLite files.",
    )
    parser.add_argument(
        "--replace-unreadable-account-metadata",
        action="store_true",
        help="Move the unreadable active account store aside before importing legacy users: Account_* metadata, accounts/, SQLite DBs, WAL and SHM.",
    )
    parser.add_argument("--no-backup-current", action="store_true", help="Do not copy current SQLite files before --apply.")
    parser.add_argument("--json-output", default="", help="Write a machine-readable import/preflight report.")
    parser.add_argument("--markdown-output", default="", help="Write a human-readable import/preflight report.")
    parser.add_argument(
        "--rehearsal-copy-dir",
        default="",
        help="Copy --target-instances-dir to this new directory and run --apply against the copy only.",
    )
    parser.add_argument(
        "--allow-running-bot",
        action="store_true",
        help="Allow --apply while TeeBotus/proactive processes are running. Dangerous; default is to refuse.",
    )
    args = parser.parse_args(argv)

    requested_target_instances_dir = Path(args.target_instances_dir)
    rehearsal_copy_dir = Path(args.rehearsal_copy_dir).expanduser() if args.rehearsal_copy_dir else None
    target_instances_dir = requested_target_instances_dir
    if rehearsal_copy_dir is not None:
        if not args.apply:
            print("--rehearsal-copy-dir requires --apply", file=sys.stderr)
            return 2
        target_instances_dir = _prepare_rehearsal_target_copy(requested_target_instances_dir, rehearsal_copy_dir)

    running_processes = _detect_running_teebotus_processes()
    if args.apply and not args.allow_running_bot and rehearsal_copy_dir is None:
        if running_processes:
            print("Refusing legacy memory import --apply because TeeBotus-related processes are running:", file=sys.stderr)
            for process in running_processes:
                print(f"  pid={process['pid']} cmd={process['cmdline']}", file=sys.stderr)
            print("Stop the bot/proactive jobs first, or pass --allow-running-bot if you intentionally accept the race.", file=sys.stderr)
            return 2

    previous_env = _apply_backend(args.backend)
    try:
        requested_legacy_instances_dir = Path(args.legacy_instances_dir)
        stats = import_legacy_user_memory(
            legacy_instances_dir=requested_legacy_instances_dir,
            target_instances_dir=target_instances_dir,
            instances=tuple(args.instance),
            apply=args.apply,
            replace_unreadable=args.replace_unreadable,
            replace_unreadable_account_metadata=args.replace_unreadable_account_metadata,
            backup_current=not args.no_backup_current,
        )
    finally:
        _restore_env(previous_env)
    mode = "rehearsal-apply" if rehearsal_copy_dir is not None and args.apply else ("apply" if args.apply else "dry-run")
    report = _build_import_report(
        stats,
        mode=mode,
        legacy_instances_dir=Path(stats.effective_legacy_instances_dir or args.legacy_instances_dir),
        requested_legacy_instances_dir=Path(stats.requested_legacy_instances_dir or args.legacy_instances_dir),
        target_instances_dir=target_instances_dir,
        requested_target_instances_dir=requested_target_instances_dir,
        instances=tuple(args.instance),
        backend=args.backend,
        replace_unreadable=args.replace_unreadable,
        replace_unreadable_account_metadata=args.replace_unreadable_account_metadata,
        backup_current=not args.no_backup_current,
        allow_running_bot=args.allow_running_bot,
        rehearsal_copy_dir=rehearsal_copy_dir,
        running_processes=running_processes,
    )
    if args.json_output:
        Path(args.json_output).write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.markdown_output:
        Path(args.markdown_output).write_text(_render_markdown_report(report), encoding="utf-8")
    print(
        f"legacy-user-memory-import {mode}: sources={stats.sources} imported_sources={stats.imported_sources} "
        f"skipped_sources={stats.skipped_sources} malformed_sources={stats.malformed_sources} "
        f"encrypted_sources={stats.encrypted_sources} entries_seen={stats.entries_seen} entries_imported={stats.entries_imported} "
        f"accounts_existing={stats.accounts_existing} accounts_created={stats.accounts_created} "
        f"unreadable_targets={stats.unreadable_targets} unreadable_metadata={stats.unreadable_metadata} "
        f"backups_created={stats.backups_created} metadata_backups_created={stats.metadata_backups_created} "
        f"account_store_resets={stats.account_store_resets}"
    )
    return 0


def import_legacy_user_memory(
    *,
    legacy_instances_dir: Path,
    target_instances_dir: Path,
    instances: tuple[str, ...] = (),
    apply: bool = False,
    replace_unreadable: bool = False,
    replace_unreadable_account_metadata: bool = False,
    backup_current: bool = True,
    provider: Any | None = None,
) -> ImportStats:
    provider = provider or SecretToolInstanceSecretProvider(create_if_missing=apply)
    stats = ImportStats()
    requested_legacy_instances_dir = Path(legacy_instances_dir)
    if not requested_legacy_instances_dir.exists():
        raise SystemExit(f"legacy instances directory does not exist: {requested_legacy_instances_dir}")
    legacy_instances_dir = _resolve_legacy_instances_dir(requested_legacy_instances_dir, set(instances))
    stats.requested_legacy_instances_dir = str(requested_legacy_instances_dir)
    stats.effective_legacy_instances_dir = str(legacy_instances_dir)
    selected = set(instances)
    reset_account_stores: set[Path] = set()
    user_dirs = _legacy_user_dirs(legacy_instances_dir, selected)
    entries_by_user_dir: dict[Path, list[dict[str, Any]]] = {}
    read_errors_by_user_dir: dict[Path, LegacyPlaintextReadError] = {}
    for user_dir in user_dirs:
        try:
            entries_by_user_dir[user_dir] = _read_plaintext_entries(user_dir / USER_MEMORY_ENTRIES_FILENAME)
        except LegacyPlaintextReadError as exc:
            entries_by_user_dir[user_dir] = []
            read_errors_by_user_dir[user_dir] = exc
    importable_user_dirs = [
        user_dir
        for user_dir, entries in entries_by_user_dir.items()
        if entries and user_dir not in read_errors_by_user_dir
    ]
    if apply and replace_unreadable_account_metadata:
        for instance_name in _instances_with_legacy_user_dirs(importable_user_dirs):
            target_root = target_instances_dir / instance_name / "data" / "accounts"
            try:
                target_store = AccountStore(target_root, instance_name, secret_provider=provider)
            except AccountStoreError:
                target_store = None
            if target_store is not None and not _account_store_metadata_unreadable(target_store):
                continue
            moved = _reset_unreadable_account_store(target_root)
            stats.metadata_backups_created += moved
            stats.account_store_resets += 1
            reset_account_stores.add(target_root)
    for user_dir in user_dirs:
        stats.sources += 1
        instance_name = user_dir.parents[2].name
        read_error = read_errors_by_user_dir.get(user_dir)
        if read_error is not None:
            stats.skipped_sources += 1
            if read_error.source_kind == "encrypted":
                stats.encrypted_sources += 1
                action = "skip-encrypted-source"
            else:
                stats.malformed_sources += 1
                action = "skip-malformed-source"
            stats.events.append(
                _event(
                    instance_name=instance_name,
                    legacy_user_id=user_dir.name,
                    account_id="<not-created>",
                    entries=0,
                    imported=0,
                    action=action,
                    error=str(read_error),
                )
            )
            print(
                f"instance={instance_name} legacy_user={user_dir.name} account=<not-created> "
                f"entries=0 action={action} error={read_error}"
            )
            continue
        entries = entries_by_user_dir[user_dir]
        stats.entries_seen += len(entries)
        if not entries:
            stats.skipped_sources += 1
            stats.events.append(
                _event(
                    instance_name=instance_name,
                    legacy_user_id=user_dir.name,
                    account_id="<not-created>",
                    entries=0,
                    imported=0,
                    action="skip-empty",
                )
            )
            print(f"instance={instance_name} legacy_user={user_dir.name} account=<not-created> entries=0 action=skip-empty")
            continue

        target_root = target_instances_dir / instance_name / "data" / "accounts"
        identity = telegram_identity_key(user_dir.name)
        metadata_unreadable_for_source = target_root in reset_account_stores
        if metadata_unreadable_for_source:
            stats.unreadable_metadata += 1
        target_store: AccountStore | None = None
        existing_account_id: str | None = None
        try:
            target_store = AccountStore(target_root, instance_name, secret_provider=provider)
            existing_account_id = target_store.get_account_for_identity(identity)
        except AccountStoreError as exc:
            if not metadata_unreadable_for_source:
                stats.unreadable_metadata += 1
                metadata_unreadable_for_source = True
            if not replace_unreadable_account_metadata:
                stats.skipped_sources += 1
                stats.events.append(
                    _event(
                        instance_name=instance_name,
                        legacy_user_id=user_dir.name,
                        account_id="<metadata-unreadable>",
                        entries=len(entries),
                        imported=0,
                        action="skip-unreadable-account-metadata",
                        metadata_unreadable=True,
                        error=str(exc),
                    )
                )
                print(
                    f"instance={instance_name} legacy_user={user_dir.name} account=<metadata-unreadable> "
                    f"entries={len(entries)} action=skip-unreadable-account-metadata error={exc}"
                )
                continue
            if apply:
                if target_root not in reset_account_stores:
                    moved = _reset_unreadable_account_store(target_root)
                    stats.metadata_backups_created += moved
                    stats.account_store_resets += 1
                    reset_account_stores.add(target_root)
                target_store = AccountStore(target_root, instance_name, secret_provider=provider)
                existing_account_id = target_store.get_account_for_identity(identity)
            else:
                existing_account_id = None
        if existing_account_id:
            account_id = existing_account_id
            stats.accounts_existing += 1
        elif apply:
            if target_store is None:
                target_store = AccountStore(target_root, instance_name, secret_provider=provider)
            account_id = target_store.resolve_or_create_account(identity, display_label=f"legacy telegram {user_dir.name}")
            stats.accounts_created += 1
        else:
            account_id = "<new>"
            stats.accounts_created += 1

        target_entries: list[dict[str, Any]] = []
        target_unreadable = False
        if existing_account_id:
            if target_store is None:
                raise AccountStoreError(f"account store unavailable for existing account {instance_name}/{existing_account_id}")
            try:
                target_entries = target_store.read_memory_entries(existing_account_id)
            except AccountStoreError:
                target_unreadable = True
            backend = target_store.account_memory_backend
            if str(getattr(backend, "last_entry_read_error", "") or ""):
                target_unreadable = True
        if target_unreadable:
            stats.unreadable_targets += 1
            if not replace_unreadable:
                stats.skipped_sources += 1
                stats.events.append(
                    _event(
                        instance_name=instance_name,
                        legacy_user_id=user_dir.name,
                        account_id=account_id,
                        entries=len(entries),
                        imported=0,
                        action="skip-unreadable-target",
                        target_unreadable=True,
                    )
                )
                print(
                    f"instance={instance_name} legacy_user={user_dir.name} account={account_id} "
                    f"entries={len(entries)} action=skip-unreadable-target"
                )
                continue
            target_entries = []

        merged_entries = _merge_entries(target_entries, entries, instance_name=instance_name, legacy_user_id=user_dir.name)
        imported_count = max(0, len(merged_entries) - len(target_entries))
        action = "would-import" if not apply else "import"
        if metadata_unreadable_for_source and replace_unreadable_account_metadata:
            action = "would-import-after-metadata-reset" if not apply else "import-after-metadata-reset"
        stats.events.append(
            _event(
                instance_name=instance_name,
                legacy_user_id=user_dir.name,
                account_id=account_id,
                entries=len(entries),
                imported=imported_count,
                action=action,
                target_unreadable=target_unreadable,
                metadata_unreadable=metadata_unreadable_for_source,
                account_created=not bool(existing_account_id),
            )
        )
        print(
            f"instance={instance_name} legacy_user={user_dir.name} account={account_id} "
            f"entries={len(entries)} imported={imported_count} action={action}"
        )
        if not apply:
            stats.imported_sources += 1
            stats.entries_imported += imported_count
            continue
        if target_store is None:
            target_store = AccountStore(target_root, instance_name, secret_provider=provider)
        if backup_current:
            stats.backups_created += _backup_sqlite_files(target_root)
        if target_unreadable and replace_unreadable:
            _clear_unreadable_account_memory(target_store, account_id)
        target_store.write_memory_entries(account_id, merged_entries)
        target_store.rebuild_structured_memory_index(account_id)
        health = target_store.check_structured_memory_index(account_id)
        if not health.ok:
            raise SystemExit(f"import verification failed for {instance_name}/{account_id}: {'; '.join(health.errors)}")
        _verify_imported_account_identity(
            target_store,
            identity,
            account_id,
            instance_name=instance_name,
            legacy_user_id=user_dir.name,
        )
        stats.imported_sources += 1
        stats.entries_imported += imported_count
    return stats


def _event(
    *,
    instance_name: str,
    legacy_user_id: str,
    account_id: str,
    entries: int,
    imported: int,
    action: str,
    target_unreadable: bool = False,
    metadata_unreadable: bool = False,
    account_created: bool = False,
    error: str = "",
) -> dict[str, Any]:
    return {
        "instance": instance_name,
        "legacy_user_id": legacy_user_id,
        "identity": telegram_identity_key(legacy_user_id),
        "account_id": account_id,
        "entries": int(entries),
        "imported": int(imported),
        "action": action,
        "target_unreadable": bool(target_unreadable),
        "metadata_unreadable": bool(metadata_unreadable),
        "account_created": bool(account_created),
        "error": error,
    }


def _verify_imported_account_identity(
    store: AccountStore,
    identity: str,
    account_id: str,
    *,
    instance_name: str,
    legacy_user_id: str,
) -> None:
    try:
        resolved_account_id = store.get_account_for_identity(identity)
    except AccountStoreError as exc:
        raise SystemExit(f"import identity verification failed for {instance_name}/{legacy_user_id}: {exc}") from exc
    if resolved_account_id != account_id:
        raise SystemExit(
            f"import identity verification failed for {instance_name}/{legacy_user_id}: "
            f"{identity} resolves to {resolved_account_id or '<none>'}, expected {account_id}"
        )
    try:
        profile = store._read_account_profile(account_id)
    except AccountStoreError as exc:
        raise SystemExit(f"import profile verification failed for {instance_name}/{legacy_user_id}: {exc}") from exc
    linked = {str(value) for value in profile.get("linked_identities", [])}
    if identity not in linked:
        raise SystemExit(
            f"import profile verification failed for {instance_name}/{legacy_user_id}: "
            f"{identity} is missing from account profile {account_id}"
        )


def _build_import_report(
    stats: ImportStats,
    *,
    mode: str,
    legacy_instances_dir: Path,
    requested_legacy_instances_dir: Path,
    target_instances_dir: Path,
    requested_target_instances_dir: Path | None = None,
    instances: tuple[str, ...],
    backend: str,
    replace_unreadable: bool,
    replace_unreadable_account_metadata: bool,
    backup_current: bool,
    allow_running_bot: bool = False,
    rehearsal_copy_dir: Path | None = None,
    running_processes: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    running_processes = list(running_processes or [])
    rehearsal_active = rehearsal_copy_dir is not None
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": mode,
        "requested_legacy_instances_dir": str(requested_legacy_instances_dir),
        "legacy_instances_dir": str(legacy_instances_dir),
        "requested_target_instances_dir": str(requested_target_instances_dir or target_instances_dir),
        "target_instances_dir": str(target_instances_dir),
        "instances": list(instances),
        "options": {
            "backend": backend,
            "replace_unreadable": bool(replace_unreadable),
            "replace_unreadable_account_metadata": bool(replace_unreadable_account_metadata),
            "backup_current": bool(backup_current),
            "allow_running_bot": bool(allow_running_bot),
            "rehearsal_copy_dir": str(rehearsal_copy_dir or ""),
            "rehearsal_active": rehearsal_active,
        },
        "apply_safety": {
            "running_bot_processes": running_processes,
            "running_bot_process_count": len(running_processes),
            "apply_allowed_now": bool(rehearsal_active or not running_processes or allow_running_bot),
            "apply_requires_stopped_bot": bool(running_processes and not allow_running_bot and not rehearsal_active),
            "message": _apply_safety_message(running_processes, allow_running_bot=allow_running_bot, rehearsal_active=rehearsal_active),
        },
        "totals": {
            "sources": stats.sources,
            "imported_sources": stats.imported_sources,
            "skipped_sources": stats.skipped_sources,
            "malformed_sources": stats.malformed_sources,
            "encrypted_sources": stats.encrypted_sources,
            "entries_seen": stats.entries_seen,
            "entries_imported": stats.entries_imported,
            "accounts_created": stats.accounts_created,
            "accounts_existing": stats.accounts_existing,
            "unreadable_targets": stats.unreadable_targets,
            "unreadable_metadata": stats.unreadable_metadata,
            "backups_created": stats.backups_created,
            "metadata_backups_created": stats.metadata_backups_created,
            "account_store_resets": stats.account_store_resets,
        },
        "events": list(stats.events),
    }


def _apply_safety_message(running_processes: list[dict[str, str]], *, allow_running_bot: bool, rehearsal_active: bool = False) -> str:
    if rehearsal_active:
        return "Rehearsal mode writes only to the copied target directory; live TeeBotus data is not modified."
    if not running_processes:
        return "No TeeBotus runtime process detected; --apply may run after reviewing the preflight report."
    if allow_running_bot:
        return "--allow-running-bot was set; apply is intentionally allowed despite detected runtime processes."
    return "TeeBotus runtime processes are running; stop bot/proactive jobs before using --apply."


def _render_markdown_report(report: dict[str, Any]) -> str:
    totals = report.get("totals") if isinstance(report.get("totals"), dict) else {}
    options = report.get("options") if isinstance(report.get("options"), dict) else {}
    apply_safety = report.get("apply_safety") if isinstance(report.get("apply_safety"), dict) else {}
    lines = [
        "# TeeBotus Legacy User Memory Import",
        "",
        f"- generated_at: `{report.get('generated_at', '')}`",
        f"- mode: `{report.get('mode', '')}`",
        f"- requested_legacy_instances_dir: `{report.get('requested_legacy_instances_dir', '')}`",
        f"- legacy_instances_dir: `{report.get('legacy_instances_dir', '')}`",
        f"- target_instances_dir: `{report.get('target_instances_dir', '')}`",
        f"- requested_target_instances_dir: `{report.get('requested_target_instances_dir', '')}`",
        f"- backend: `{options.get('backend', '')}`",
        f"- replace_unreadable: `{options.get('replace_unreadable', False)}`",
        f"- replace_unreadable_account_metadata: `{options.get('replace_unreadable_account_metadata', False)}`",
        f"- allow_running_bot: `{options.get('allow_running_bot', False)}`",
        f"- rehearsal_active: `{options.get('rehearsal_active', False)}`",
        f"- rehearsal_copy_dir: `{options.get('rehearsal_copy_dir', '')}`",
        "",
        "## Apply Safety",
        "",
        f"- apply_allowed_now: `{apply_safety.get('apply_allowed_now', False)}`",
        f"- apply_requires_stopped_bot: `{apply_safety.get('apply_requires_stopped_bot', False)}`",
        f"- running_bot_process_count: `{apply_safety.get('running_bot_process_count', 0)}`",
        f"- message: `{apply_safety.get('message', '')}`",
        "",
        "## Totals",
        "",
    ]
    for key in sorted(totals):
        lines.append(f"- {key}: `{totals[key]}`")
    running_processes = apply_safety.get("running_bot_processes")
    if isinstance(running_processes, list) and running_processes:
        lines.extend(["", "### Running Bot Processes", ""])
        for process in running_processes:
            if not isinstance(process, dict):
                continue
            lines.append(f"- pid=`{process.get('pid', '')}` cmd=`{process.get('cmdline', '')}`")
    lines.extend(["", "## Events", ""])
    for event in report.get("events", []) if isinstance(report.get("events"), list) else []:
        if not isinstance(event, dict):
            continue
        flags = []
        if event.get("metadata_unreadable"):
            flags.append("metadata_unreadable")
        if event.get("target_unreadable"):
            flags.append("target_unreadable")
        if event.get("account_created"):
            flags.append("account_created")
        flags_text = f" flags=`{','.join(flags)}`" if flags else ""
        lines.append(
            "- "
            f"instance=`{event.get('instance', '')}` "
            f"legacy_user=`{event.get('legacy_user_id', '')}` "
            f"account=`{event.get('account_id', '')}` "
            f"entries=`{event.get('entries', 0)}` "
            f"imported=`{event.get('imported', 0)}` "
            f"action=`{event.get('action', '')}`"
            f"{flags_text}"
        )
    return "\n".join(lines) + "\n"


def _prepare_rehearsal_target_copy(source_instances_dir: Path, rehearsal_copy_dir: Path) -> Path:
    source = source_instances_dir.expanduser()
    destination = rehearsal_copy_dir.expanduser()
    if not source.exists():
        raise SystemExit(f"rehearsal source target instances directory does not exist: {source}")
    if not source.is_dir():
        raise SystemExit(f"rehearsal source target instances path is not a directory: {source}")
    if destination.exists():
        raise SystemExit(f"rehearsal copy directory already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, symlinks=True)
    return destination


def _detect_running_teebotus_processes() -> list[dict[str, str]]:
    proc_root = Path("/proc")
    current_pid = os.getpid()
    if not proc_root.exists():
        return []
    running: list[dict[str, str]] = []
    for path in proc_root.iterdir():
        if not path.name.isdigit():
            continue
        pid = int(path.name)
        if pid == current_pid:
            continue
        try:
            raw = (path / "cmdline").read_bytes()
        except OSError:
            continue
        if not raw:
            continue
        parts = [part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part]
        cmdline = " ".join(parts).strip()
        lower = cmdline.lower()
        if not _looks_like_running_teebotus_runtime(lower):
            continue
        if "scripts/import_legacy_user_memory.py" in lower:
            continue
        running.append({"pid": str(pid), "cmdline": cmdline[:500]})
    return running


def _looks_like_running_teebotus_runtime(cmdline_lower: str) -> bool:
    return (
        TEEBOTUS_MODULE_RUNTIME_RE.search(cmdline_lower) is not None
        or "teebotus-proactive" in cmdline_lower
        or "/teebotus-proactive" in cmdline_lower
    )


def _legacy_user_dirs(legacy_instances_dir: Path, selected_instances: set[str]) -> list[Path]:
    if not legacy_instances_dir.exists():
        return []
    result: list[Path] = []
    for users_dir in sorted(legacy_instances_dir.glob(f"*/data/{USER_MEMORY_LEGACY_ROOT}")):
        instance_name = users_dir.parents[1].name
        if selected_instances and instance_name not in selected_instances:
            continue
        for user_dir in sorted(users_dir.iterdir()):
            if user_dir.is_dir() and (user_dir / USER_MEMORY_ENTRIES_FILENAME).exists():
                result.append(user_dir)
    return result


def _instances_with_legacy_user_dirs(user_dirs: Iterable[Path]) -> tuple[str, ...]:
    names: list[str] = []
    for user_dir in user_dirs:
        instance_name = user_dir.parents[2].name
        if instance_name not in names:
            names.append(instance_name)
    return tuple(names)


def _account_store_metadata_unreadable(store: AccountStore) -> bool:
    try:
        store._load_identities()
        store._load_index()
        store._load_secrets()
        if store.accounts_dir.exists():
            for account_dir in sorted(path for path in store.accounts_dir.iterdir() if path.is_dir()):
                store._read_account_profile(account_dir.name)
    except AccountStoreError:
        return True
    return False


def _resolve_legacy_instances_dir(path: Path, selected_instances: set[str]) -> Path:
    if _legacy_user_dirs(path, selected_instances):
        return path
    candidates: list[tuple[int, int, str, Path]] = []
    for child in sorted(path.iterdir()) if path.exists() and path.is_dir() else []:
        if not child.is_dir() or not child.name.startswith("instances"):
            continue
        source_count = 0
        entry_count = 0
        for user_dir in _legacy_user_dirs(child, selected_instances):
            entries_path = user_dir / USER_MEMORY_ENTRIES_FILENAME
            try:
                entries = _read_plaintext_entries(entries_path)
            except LegacyPlaintextReadError:
                continue
            if entries:
                source_count += 1
                entry_count += len(entries)
        if source_count:
            candidates.append((entry_count, source_count, child.name, child))
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


def _read_plaintext_entries(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not path.exists():
        return entries
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise LegacyPlaintextReadError(f"{path}: legacy memory entries could not be read: {exc}", source_kind="malformed") from exc
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LegacyPlaintextReadError(
                f"{path}:{line_number}: legacy memory entry is malformed JSON: {exc.msg}",
                source_kind="malformed",
            ) from exc
        if not isinstance(data, dict):
            raise LegacyPlaintextReadError(f"{path}:{line_number}: legacy memory entry is not an object", source_kind="malformed")
        if {"version", "nonce", "ciphertext"}.issubset(data):
            raise LegacyPlaintextReadError(
                f"{path}:{line_number}: legacy memory entry is encrypted; use a plaintext backup",
                source_kind="encrypted",
            )
        entries.append(data)
    return entries


def _merge_entries(
    target_entries: Iterable[dict[str, Any]],
    legacy_entries: Iterable[dict[str, Any]],
    *,
    instance_name: str,
    legacy_user_id: str,
) -> list[dict[str, Any]]:
    merged = [dict(entry) for entry in target_entries if isinstance(entry, dict)]
    existing_ids = {str(entry.get("id") or "").strip() for entry in merged if str(entry.get("id") or "").strip()}
    existing_legacy_keys = _existing_legacy_import_keys(merged)
    new_entries: list[dict[str, Any]] = []
    remapped_ids: dict[str, str] = {}
    for entry in legacy_entries:
        normalized = dict(entry)
        memory_id = str(normalized.get("id") or "").strip()
        legacy_import_key = _legacy_memory_import_key(normalized, memory_id)
        legacy_key = (instance_name, legacy_user_id, legacy_import_key)
        if legacy_key in existing_legacy_keys:
            continue
        target_id = memory_id
        if not target_id or target_id in existing_ids:
            target_id = _scoped_legacy_memory_id(instance_name=instance_name, legacy_user_id=legacy_user_id, memory_id=legacy_import_key)
            if target_id in existing_ids:
                continue
            normalized["id"] = target_id
        if memory_id and target_id != memory_id:
            remapped_ids[memory_id] = target_id
        normalized.setdefault("source", {})
        if isinstance(normalized["source"], dict):
            normalized["source"] = {
                **normalized["source"],
                "legacy_import": True,
                "legacy_instance": instance_name,
                "legacy_user_id": legacy_user_id,
                "legacy_original_id": memory_id,
                "legacy_import_key": legacy_import_key,
            }
        else:
            normalized["source"] = {
                "legacy_import": True,
                "legacy_instance": instance_name,
                "legacy_user_id": legacy_user_id,
                "legacy_original_id": memory_id,
                "legacy_import_key": legacy_import_key,
            }
        new_entries.append(normalized)
        existing_ids.add(target_id)
        existing_legacy_keys.add(legacy_key)
    for entry in new_entries:
        _remap_legacy_memory_links(entry, remapped_ids)
    merged.extend(new_entries)
    return merged


def _remap_legacy_memory_links(entry: dict[str, Any], remapped_ids: dict[str, str]) -> None:
    if not remapped_ids:
        return
    for key in ("related_ids", "supports", "contradicts", "supersedes"):
        entry[key] = _remap_legacy_memory_link_list(entry.get(key), remapped_ids)
    relations = entry.get("relations")
    if not isinstance(relations, list):
        return
    remapped_relations: list[Any] = []
    for relation in relations:
        if not isinstance(relation, dict):
            remapped_relations.append(relation)
            continue
        remapped = dict(relation)
        for key in ("target_id", "id"):
            target_id = str(remapped.get(key) or "").strip()
            if target_id in remapped_ids:
                remapped[key] = remapped_ids[target_id]
        remapped_relations.append(remapped)
    entry["relations"] = remapped_relations


def _remap_legacy_memory_link_list(value: Any, remapped_ids: dict[str, str]) -> list[Any]:
    if not isinstance(value, list):
        return []
    remapped_values: list[Any] = []
    for item in value:
        if isinstance(item, dict):
            remapped = dict(item)
            for key in ("target_id", "id"):
                target_id = str(remapped.get(key) or "").strip()
                if target_id in remapped_ids:
                    remapped[key] = remapped_ids[target_id]
            remapped_values.append(remapped)
            continue
        target_id = str(item or "").strip()
        remapped_values.append(remapped_ids.get(target_id, item))
    return remapped_values


def _existing_legacy_import_keys(entries: Iterable[dict[str, Any]]) -> set[tuple[str, str, str]]:
    keys: set[tuple[str, str, str]] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        source = entry.get("source")
        if not isinstance(source, dict) or source.get("legacy_import") is not True:
            continue
        instance_name = str(source.get("legacy_instance") or "").strip()
        legacy_user_id = str(source.get("legacy_user_id") or "").strip()
        import_key = str(source.get("legacy_import_key") or source.get("legacy_original_id") or entry.get("id") or "").strip()
        if instance_name and legacy_user_id and import_key:
            keys.add((instance_name, legacy_user_id, import_key))
    return keys


def _legacy_memory_import_key(entry: dict[str, Any], memory_id: str) -> str:
    if memory_id:
        return memory_id
    payload = json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"missing_id_{digest[:32]}"


def _scoped_legacy_memory_id(*, instance_name: str, legacy_user_id: str, memory_id: str) -> str:
    digest = hashlib.sha256(f"{instance_name}\0{legacy_user_id}\0{memory_id}".encode("utf-8")).hexdigest()
    return f"legacy_{digest[:32]}"


def _backup_sqlite_files(accounts_root: Path) -> int:
    backup_dir = _unique_backup_dir(accounts_root, ".pre-legacy-user-memory-import")
    copied = 0
    for filename in (SQLITE_DEFAULT_FILENAME, SQLITE_DEFAULT_FALLBACK_FILENAME):
        for path in [accounts_root / filename, accounts_root / f"{filename}-wal", accounts_root / f"{filename}-shm"]:
            if not path.exists():
                continue
            backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup_dir / path.name)
            copied += 1
    return copied


def _clear_unreadable_account_memory(store: AccountStore, account_id: str) -> None:
    backend = store.account_memory_backend
    if backend is not None:
        clear = getattr(backend, "clear_account_unchecked", None)
        if not callable(clear):
            raise AccountStoreError(f"{type(backend).__name__} cannot replace unreadable account memory")
        clear(account_id)
        return
    for filename in (USER_MEMORY_ENTRIES_FILENAME, USER_MEMORY_INDEX_FILENAME):
        (store.account_dir(account_id) / filename).unlink(missing_ok=True)


def _reset_unreadable_account_store(accounts_root: Path) -> int:
    backup_dir = _unique_backup_dir(accounts_root, ".pre-legacy-user-memory-account-store-reset")
    moved = 0
    for filename in (
        "Account_Index.json",
        "Account_Identities.json",
        "Account_Secrets.json",
        "Account_Memory.sqlite3",
        "Account_Memory.sqlite3-wal",
        "Account_Memory.sqlite3-shm",
        "Account_Memory.backup.sqlite3",
        "Account_Memory.backup.sqlite3-wal",
        "Account_Memory.backup.sqlite3-shm",
    ):
        path = accounts_root / filename
        if not path.exists():
            continue
        backup_dir.mkdir(parents=True, exist_ok=True)
        path.rename(backup_dir / path.name)
        moved += 1
    accounts_dir = accounts_root / "accounts"
    if accounts_dir.exists():
        backup_dir.mkdir(parents=True, exist_ok=True)
        accounts_dir.rename(backup_dir / accounts_dir.name)
        moved += 1
    return moved


def _unique_backup_dir(parent: Path, prefix: str) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = parent / f"{prefix}-{timestamp}"
    if not base.exists():
        return base
    for index in range(1, 1000):
        candidate = parent / f"{prefix}-{timestamp}-{index:03d}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not allocate unique backup directory below {parent}")


def _apply_backend(backend: str) -> dict[str, str | None]:
    keys = (SQLITE_BACKEND_ENV, POSTGRES_BACKEND_ENV)
    previous = {key: os.environ.get(key) for key in keys}
    if backend == "sqlite":
        os.environ[SQLITE_BACKEND_ENV] = "sqlite"
        os.environ[POSTGRES_BACKEND_ENV] = "sqlite"
    elif backend == "json":
        os.environ.pop(SQLITE_BACKEND_ENV, None)
        os.environ.pop(POSTGRES_BACKEND_ENV, None)
    return previous


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
