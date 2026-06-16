#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
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


@dataclass
class ImportStats:
    sources: int = 0
    imported_sources: int = 0
    skipped_sources: int = 0
    entries_seen: int = 0
    entries_imported: int = 0
    accounts_created: int = 0
    accounts_existing: int = 0
    unreadable_targets: int = 0
    unreadable_metadata: int = 0
    backups_created: int = 0
    metadata_backups_created: int = 0
    account_store_resets: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import plaintext legacy data/users/* user memories into encrypted account memory.")
    parser.add_argument("--legacy-instances-dir", required=True, help="Legacy instances directory, e.g. /home/teladi/TeeBotus.bak2/instances.bak.")
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
    args = parser.parse_args(argv)

    previous_env = _apply_backend(args.backend)
    try:
        stats = import_legacy_user_memory(
            legacy_instances_dir=Path(args.legacy_instances_dir),
            target_instances_dir=Path(args.target_instances_dir),
            instances=tuple(args.instance),
            apply=args.apply,
            replace_unreadable=args.replace_unreadable,
            replace_unreadable_account_metadata=args.replace_unreadable_account_metadata,
            backup_current=not args.no_backup_current,
        )
    finally:
        _restore_env(previous_env)
    mode = "apply" if args.apply else "dry-run"
    report = _build_import_report(
        stats,
        mode=mode,
        legacy_instances_dir=Path(args.legacy_instances_dir),
        target_instances_dir=Path(args.target_instances_dir),
        instances=tuple(args.instance),
        backend=args.backend,
        replace_unreadable=args.replace_unreadable,
        replace_unreadable_account_metadata=args.replace_unreadable_account_metadata,
        backup_current=not args.no_backup_current,
    )
    if args.json_output:
        Path(args.json_output).write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.markdown_output:
        Path(args.markdown_output).write_text(_render_markdown_report(report), encoding="utf-8")
    print(
        f"legacy-user-memory-import {mode}: sources={stats.sources} imported_sources={stats.imported_sources} "
        f"skipped_sources={stats.skipped_sources} entries_seen={stats.entries_seen} entries_imported={stats.entries_imported} "
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
    provider = provider or SecretToolInstanceSecretProvider()
    stats = ImportStats()
    selected = set(instances)
    reset_account_stores: set[Path] = set()
    for user_dir in _legacy_user_dirs(legacy_instances_dir, selected):
        stats.sources += 1
        instance_name = user_dir.parents[2].name
        target_root = target_instances_dir / instance_name / "data" / "accounts"
        target_store = AccountStore(target_root, instance_name, secret_provider=provider)
        identity = telegram_identity_key(user_dir.name)
        try:
            existing_account_id = target_store.get_account_for_identity(identity)
        except AccountStoreError as exc:
            stats.unreadable_metadata += 1
            if not replace_unreadable_account_metadata:
                stats.skipped_sources += 1
                stats.events.append(
                    _event(
                        instance_name=instance_name,
                        legacy_user_id=user_dir.name,
                        account_id="<metadata-unreadable>",
                        entries=0,
                        imported=0,
                        action="skip-unreadable-account-metadata",
                        metadata_unreadable=True,
                        error=str(exc),
                    )
                )
                print(
                    f"instance={instance_name} legacy_user={user_dir.name} account=<metadata-unreadable> "
                    f"entries=unknown action=skip-unreadable-account-metadata error={exc}"
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
            account_id = target_store.resolve_or_create_account(identity, display_label=f"legacy telegram {user_dir.name}")
            stats.accounts_created += 1
        else:
            account_id = "<new>"
            stats.accounts_created += 1

        entries = _read_plaintext_entries(user_dir / USER_MEMORY_ENTRIES_FILENAME)
        stats.entries_seen += len(entries)
        if not entries:
            stats.skipped_sources += 1
            stats.events.append(
                _event(
                    instance_name=instance_name,
                    legacy_user_id=user_dir.name,
                    account_id=account_id,
                    entries=0,
                    imported=0,
                    action="skip-empty",
                )
            )
            print(f"instance={instance_name} legacy_user={user_dir.name} account={account_id} entries=0 action=skip-empty")
            continue

        target_entries: list[dict[str, Any]] = []
        target_unreadable = False
        if existing_account_id:
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
        stats.events.append(
            _event(
                instance_name=instance_name,
                legacy_user_id=user_dir.name,
                account_id=account_id,
                entries=len(entries),
                imported=imported_count,
                action=action,
                target_unreadable=target_unreadable,
                metadata_unreadable=False,
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
        if backup_current:
            stats.backups_created += _backup_sqlite_files(target_root)
        target_store.write_memory_entries(account_id, merged_entries)
        target_store.rebuild_structured_memory_index(account_id)
        health = target_store.check_structured_memory_index(account_id)
        if not health.ok:
            raise SystemExit(f"import verification failed for {instance_name}/{account_id}: {'; '.join(health.errors)}")
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


def _build_import_report(
    stats: ImportStats,
    *,
    mode: str,
    legacy_instances_dir: Path,
    target_instances_dir: Path,
    instances: tuple[str, ...],
    backend: str,
    replace_unreadable: bool,
    replace_unreadable_account_metadata: bool,
    backup_current: bool,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": mode,
        "legacy_instances_dir": str(legacy_instances_dir),
        "target_instances_dir": str(target_instances_dir),
        "instances": list(instances),
        "options": {
            "backend": backend,
            "replace_unreadable": bool(replace_unreadable),
            "replace_unreadable_account_metadata": bool(replace_unreadable_account_metadata),
            "backup_current": bool(backup_current),
        },
        "totals": {
            "sources": stats.sources,
            "imported_sources": stats.imported_sources,
            "skipped_sources": stats.skipped_sources,
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


def _render_markdown_report(report: dict[str, Any]) -> str:
    totals = report.get("totals") if isinstance(report.get("totals"), dict) else {}
    options = report.get("options") if isinstance(report.get("options"), dict) else {}
    lines = [
        "# TeeBotus Legacy User Memory Import",
        "",
        f"- generated_at: `{report.get('generated_at', '')}`",
        f"- mode: `{report.get('mode', '')}`",
        f"- legacy_instances_dir: `{report.get('legacy_instances_dir', '')}`",
        f"- target_instances_dir: `{report.get('target_instances_dir', '')}`",
        f"- backend: `{options.get('backend', '')}`",
        f"- replace_unreadable: `{options.get('replace_unreadable', False)}`",
        f"- replace_unreadable_account_metadata: `{options.get('replace_unreadable_account_metadata', False)}`",
        "",
        "## Totals",
        "",
    ]
    for key in sorted(totals):
        lines.append(f"- {key}: `{totals[key]}`")
    lines.extend(["", "## Events", ""])
    for event in report.get("events", []) if isinstance(report.get("events"), list) else []:
        if not isinstance(event, dict):
            continue
        lines.append(
            "- "
            f"instance=`{event.get('instance', '')}` "
            f"legacy_user=`{event.get('legacy_user_id', '')}` "
            f"account=`{event.get('account_id', '')}` "
            f"entries=`{event.get('entries', 0)}` "
            f"imported=`{event.get('imported', 0)}` "
            f"action=`{event.get('action', '')}`"
        )
    return "\n".join(lines) + "\n"


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


def _read_plaintext_entries(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not path.exists():
        return entries
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        data = json.loads(line)
        if not isinstance(data, dict):
            raise SystemExit(f"{path}:{line_number}: legacy memory entry is not an object")
        if {"version", "nonce", "ciphertext"}.issubset(data):
            raise SystemExit(f"{path}:{line_number}: legacy memory entry is encrypted; use a plaintext backup")
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
    existing_ids = {str(entry.get("id") or "") for entry in merged}
    for entry in legacy_entries:
        normalized = dict(entry)
        memory_id = str(normalized.get("id") or "").strip()
        if memory_id in existing_ids:
            continue
        normalized.setdefault("source", {})
        if isinstance(normalized["source"], dict):
            normalized["source"] = {
                **normalized["source"],
                "legacy_import": True,
                "legacy_instance": instance_name,
                "legacy_user_id": legacy_user_id,
            }
        else:
            normalized["source"] = {"legacy_import": True, "legacy_instance": instance_name, "legacy_user_id": legacy_user_id}
        merged.append(normalized)
        existing_ids.add(memory_id)
    return merged


def _backup_sqlite_files(accounts_root: Path) -> int:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = accounts_root / f".pre-legacy-user-memory-import-{timestamp}"
    copied = 0
    for filename in (SQLITE_DEFAULT_FILENAME, SQLITE_DEFAULT_FALLBACK_FILENAME):
        for path in [accounts_root / filename, accounts_root / f"{filename}-wal", accounts_root / f"{filename}-shm"]:
            if not path.exists():
                continue
            backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup_dir / path.name)
            copied += 1
    return copied


def _reset_unreadable_account_store(accounts_root: Path) -> int:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = accounts_root / f".pre-legacy-user-memory-account-store-reset-{timestamp}"
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
