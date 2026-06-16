#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from TeeBotus.runtime.accounts import (  # noqa: E402
    ACCOUNT_MEMORY_KEY_PURPOSE,
    AccountStoreError,
    InstanceSecretProvider,
    SecretToolInstanceSecretProvider,
)
from TeeBotus.runtime.sqlite_memory import (  # noqa: E402
    SQLITE_DEFAULT_FALLBACK_FILENAME,
    SQLITE_DEFAULT_FILENAME,
    SQLITE_FALLBACK_PATH_ENV,
    SQLITE_PATH_ENV,
    SQLiteAccountMemoryBackend,
    SQLiteMemoryConfig,
)


@dataclass(frozen=True)
class SyncResult:
    primary: str
    secondary: str
    dry_run: bool
    copied: bool
    decrypt_checked: bool
    account_payloads_checked: int
    existing_secondary_files: int
    secondary_backups_created: int
    secondary_backup_dir: str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync TeeBotus primary SQLite account-memory DB to the secondary fallback DB.")
    parser.add_argument("--accounts-root", default="", help="Account store root, e.g. instances/Depressionsbot/data/accounts.")
    parser.add_argument("--primary", default="", help=f"Override primary DB path. Defaults to {SQLITE_PATH_ENV} or Account_Memory.sqlite3.")
    parser.add_argument("--secondary", default="", help=f"Override secondary DB path. Defaults to {SQLITE_FALLBACK_PATH_ENV} or Account_Memory.backup.sqlite3.")
    parser.add_argument("--instance-name", default="", help="Optional instance-name filter for decrypt validation.")
    parser.add_argument("--skip-decrypt-check", action="store_true", help="Skip payload decryption validation. Not recommended.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and report what would be copied without writing the secondary DB.")
    parser.add_argument("--json-output", default="", help="Write a machine-readable sync report.")
    args = parser.parse_args(argv)

    try:
        result = sync_account_memory_sqlite_backup(
            accounts_root=Path(args.accounts_root or "."),
            primary=Path(args.primary).expanduser() if args.primary else None,
            secondary=Path(args.secondary).expanduser() if args.secondary else None,
            instance_name=args.instance_name,
            decrypt_check=not args.skip_decrypt_check,
            dry_run=args.dry_run,
            provider=SecretToolInstanceSecretProvider(create_if_missing=False),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"sync_failed={exc}", file=sys.stderr)
        return 2
    if args.json_output:
        Path(args.json_output).write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    action = "would-sync" if result.dry_run else "synced"
    print(
        f"{action} primary={result.primary} secondary={result.secondary} "
        f"decrypt_checked={result.decrypt_checked} account_payloads_checked={result.account_payloads_checked} "
        f"secondary_backups_created={result.secondary_backups_created}"
    )
    return 0


def sync_account_memory_sqlite_backup(
    *,
    accounts_root: Path,
    primary: Path | None = None,
    secondary: Path | None = None,
    instance_name: str = "",
    decrypt_check: bool = True,
    dry_run: bool = False,
    provider: InstanceSecretProvider | None = None,
) -> SyncResult:
    root = Path(accounts_root or ".").expanduser()
    primary_path = Path(primary or os.environ.get(SQLITE_PATH_ENV) or root / SQLITE_DEFAULT_FILENAME).expanduser()
    secondary_path = Path(secondary or os.environ.get(SQLITE_FALLBACK_PATH_ENV) or root / SQLITE_DEFAULT_FALLBACK_FILENAME).expanduser()
    if not primary_path.exists():
        raise FileNotFoundError(f"primary_missing={primary_path}")
    if primary_path.is_dir():
        raise IsADirectoryError(f"primary_is_directory={primary_path}")
    if secondary_path.exists() and secondary_path.is_dir():
        raise IsADirectoryError(f"secondary_is_directory={secondary_path}")

    _quick_check(primary_path, label="primary")
    payloads_checked = 0
    if decrypt_check:
        payloads_checked = _verify_payloads_decryptable(
            primary_path,
            provider=provider or SecretToolInstanceSecretProvider(create_if_missing=False),
            instance_name_filter=instance_name,
        )

    existing_secondary_files = _existing_sqlite_file_count(secondary_path)
    backup_dir = ""
    backups_created = 0
    if not dry_run:
        backup_dir, backups_created = _backup_existing_secondary(secondary_path)
        secondary_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(primary_path) as source:
            with sqlite3.connect(secondary_path) as target:
                source.backup(target)
        _quick_check(secondary_path, label="secondary")
        if decrypt_check:
            _verify_payloads_decryptable(
                secondary_path,
                provider=provider or SecretToolInstanceSecretProvider(create_if_missing=False),
                instance_name_filter=instance_name,
            )

    return SyncResult(
        primary=str(primary_path),
        secondary=str(secondary_path),
        dry_run=dry_run,
        copied=not dry_run,
        decrypt_checked=decrypt_check,
        account_payloads_checked=payloads_checked,
        existing_secondary_files=existing_secondary_files,
        secondary_backups_created=backups_created,
        secondary_backup_dir=backup_dir,
    )


def _quick_check(path: Path, *, label: str) -> None:
    try:
        with sqlite3.connect(path) as connection:
            row = connection.execute("PRAGMA quick_check").fetchone()
    except sqlite3.DatabaseError as exc:
        raise RuntimeError(f"{label}_quick_check_failed:{path}:{exc}") from exc
    if not row or str(row[0]).casefold() != "ok":
        raise RuntimeError(f"{label}_quick_check_failed:{path}:{row[0] if row else 'no result'}")


def _verify_payloads_decryptable(
    path: Path,
    *,
    provider: InstanceSecretProvider,
    instance_name_filter: str = "",
) -> int:
    checked = 0
    for instance_name, account_id in _account_payload_refs(path, instance_name_filter=instance_name_filter):
        backend = SQLiteAccountMemoryBackend(
            instance_name=instance_name,
            provider=provider,
            purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
            config=SQLiteMemoryConfig(path=path, fallback_path=None),
        )
        try:
            backend.read_entries(account_id)
            if backend.last_entry_read_error:
                raise AccountStoreError(backend.last_entry_read_error)
            backend.read_index(account_id)
            if backend.last_index_read_error:
                raise AccountStoreError(backend.last_index_read_error)
        except AccountStoreError as exc:
            raise RuntimeError(f"payload_not_decryptable instance={instance_name} account={account_id}: {exc}") from exc
        checked += 1
    return checked


def _account_payload_refs(path: Path, *, instance_name_filter: str = "") -> list[tuple[str, str]]:
    with sqlite3.connect(path) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('memory_entries', 'memory_indexes')"
            ).fetchall()
        }
        refs: set[tuple[str, str]] = set()
        if "memory_entries" in tables:
            refs.update(
                (str(row[0]), str(row[1]))
                for row in connection.execute("SELECT DISTINCT instance_name, account_id FROM memory_entries").fetchall()
            )
        if "memory_indexes" in tables:
            refs.update(
                (str(row[0]), str(row[1]))
                for row in connection.execute("SELECT DISTINCT instance_name, account_id FROM memory_indexes").fetchall()
            )
    if instance_name_filter:
        refs = {ref for ref in refs if ref[0] == instance_name_filter}
    return sorted(refs)


def _existing_sqlite_file_count(path: Path) -> int:
    return sum(1 for candidate in _sqlite_file_family(path) if candidate.exists())


def _backup_existing_secondary(path: Path) -> tuple[str, int]:
    candidates = [candidate for candidate in _sqlite_file_family(path) if candidate.exists()]
    if not candidates:
        return "", 0
    backup_dir = _unique_backup_dir(path.parent, ".pre-account-memory-backup-sync")
    backup_dir.mkdir(parents=True, exist_ok=True)
    for candidate in candidates:
        shutil.copy2(candidate, backup_dir / candidate.name)
    return str(backup_dir), len(candidates)


def _sqlite_file_family(path: Path) -> tuple[Path, Path, Path]:
    return (path, Path(f"{path}-wal"), Path(f"{path}-shm"))


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


if __name__ == "__main__":
    raise SystemExit(main())
