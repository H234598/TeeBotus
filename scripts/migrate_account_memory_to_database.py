#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from TeeBotus.runtime.accounts import (  # noqa: E402
    USER_MEMORY_ENTRIES_FILENAME,
    USER_MEMORY_INDEX_FILENAME,
    AccountStore,
    SecretToolInstanceSecretProvider,
    TOKEN_HEX_RE,
)
from TeeBotus.runtime.postgres_memory import POSTGRES_BACKEND_ENV, POSTGRES_DSN_ENV  # noqa: E402
from TeeBotus.runtime.sqlite_memory import SQLITE_BACKEND_TOKENS, SQLITE_PATH_ENV  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate encrypted TeeBotus account memories from JSON files to the configured database backend.")
    parser.add_argument("--instances-dir", default="instances", help="TeeBotus instances directory.")
    parser.add_argument("--instance", action="append", default=[], help="Instance to migrate. Can be repeated.")
    parser.add_argument("--backend", choices=("sqlite", "postgres"), default="", help="Override TEEBOTUS_ACCOUNT_MEMORY_BACKEND during migration.")
    parser.add_argument("--sqlite-path", default="", help=f"Override {SQLITE_PATH_ENV}.")
    parser.add_argument("--postgres-dsn", default="", help=f"Override {POSTGRES_DSN_ENV}.")
    parser.add_argument("--dry-run", action="store_true", help="Read and report, but do not write the database.")
    parser.add_argument("--delete-json-files", action="store_true", help="Delete User_Memory_Index.json and User_Memory_Entries.jsonl after verified migration.")
    args = parser.parse_args(argv)

    backend = _resolve_backend(args.backend)
    if backend not in {"sqlite", "postgres"}:
        print(f"{POSTGRES_BACKEND_ENV}=sqlite or postgres is required, or pass --backend.", file=sys.stderr)
        return 2
    if backend == "postgres" and not (args.postgres_dsn or os.environ.get(POSTGRES_DSN_ENV)):
        print(f"{POSTGRES_DSN_ENV} is required for PostgreSQL migration.", file=sys.stderr)
        return 2

    previous = _apply_backend_overrides(backend=backend, sqlite_path=args.sqlite_path, postgres_dsn=args.postgres_dsn)
    try:
        result = _migrate(
            instances_dir=Path(args.instances_dir),
            selected=tuple(args.instance),
            dry_run=args.dry_run,
            delete_json_files=args.delete_json_files,
        )
    finally:
        _restore_env(previous)
    print(f"backend={backend} migrated_accounts={result['migrated']} skipped_accounts={result['skipped']} deleted_json_files={result['deleted']}")
    return 0


def _migrate(*, instances_dir: Path, selected: tuple[str, ...], dry_run: bool, delete_json_files: bool) -> dict[str, int]:
    provider = SecretToolInstanceSecretProvider(create_if_missing=False)
    migrated = 0
    skipped = 0
    deleted = 0
    for instance_dir in _instance_dirs(instances_dir, selected):
        source_store = AccountStore(
            instance_dir / "data" / "accounts", instance_dir.name, provider, create_dirs=False
        )
        target_store = AccountStore(
            instance_dir / "data" / "accounts", instance_dir.name, provider, create_dirs=False
        )
        for account_dir in _account_dirs(source_store.accounts_dir):
            account_id = account_dir.name
            entries_path = account_dir / USER_MEMORY_ENTRIES_FILENAME
            index_path = account_dir / USER_MEMORY_INDEX_FILENAME
            if not entries_path.exists() and not index_path.exists():
                skipped += 1
                continue
            entries = source_store.account_memory_vault.read_jsonl(entries_path)
            index = source_store.account_memory_vault.read_json(index_path, {})
            print(f"instance={instance_dir.name} account={account_id} entries={len(entries)} dry_run={dry_run} delete_json_files={delete_json_files}")
            if dry_run:
                skipped += 1
                continue
            target_store.write_memory_entries(account_id, entries)
            target_store.write_memory_index(account_id, index)
            if target_store.read_memory_entries(account_id) != entries:
                raise SystemExit(f"verification failed for entries: {instance_dir.name}/{account_id}")
            if target_store.read_memory_index(account_id) != index:
                raise SystemExit(f"verification failed for index: {instance_dir.name}/{account_id}")
            migrated += 1
            if delete_json_files:
                for path in (entries_path, index_path):
                    if path.exists():
                        path.unlink()
                        deleted += 1
    return {"migrated": migrated, "skipped": skipped, "deleted": deleted}


def _resolve_backend(override: str) -> str:
    if override:
        return override.strip().casefold()
    backend = os.environ.get(POSTGRES_BACKEND_ENV, "").strip().casefold()
    if backend in SQLITE_BACKEND_TOKENS:
        return "sqlite"
    if backend in {"postgres", "postgresql", "pg"}:
        return "postgres"
    return ""


def _apply_backend_overrides(*, backend: str, sqlite_path: str, postgres_dsn: str) -> dict[str, str | None]:
    keys = [POSTGRES_BACKEND_ENV, SQLITE_PATH_ENV, POSTGRES_DSN_ENV]
    previous = {key: os.environ.get(key) for key in keys}
    os.environ[POSTGRES_BACKEND_ENV] = backend
    if sqlite_path:
        os.environ[SQLITE_PATH_ENV] = sqlite_path
    if postgres_dsn:
        os.environ[POSTGRES_DSN_ENV] = postgres_dsn
    return previous


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _instance_dirs(instances_dir: Path, selected: tuple[str, ...]) -> list[Path]:
    if selected:
        return [instances_dir / name for name in selected if (instances_dir / name).is_dir()]
    if not instances_dir.exists():
        return []
    return sorted(path for path in instances_dir.iterdir() if path.is_dir() and (path / "data" / "accounts").exists())


def _account_dirs(accounts_dir: Path) -> list[Path]:
    if not accounts_dir.exists():
        return []
    return sorted(path for path in accounts_dir.iterdir() if path.is_dir() and TOKEN_HEX_RE.fullmatch(path.name))


if __name__ == "__main__":
    raise SystemExit(main())
