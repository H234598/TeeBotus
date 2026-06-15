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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate encrypted TeeBotus account memories from JSONL files to PostgreSQL.")
    parser.add_argument("--instances-dir", default="instances", help="TeeBotus instances directory.")
    parser.add_argument("--instance", action="append", default=[], help="Instance to migrate. Can be repeated.")
    parser.add_argument("--dry-run", action="store_true", help="Read and report, but do not write PostgreSQL.")
    args = parser.parse_args(argv)
    if not os.environ.get(POSTGRES_DSN_ENV):
        print(f"{POSTGRES_DSN_ENV} is required.", file=sys.stderr)
        return 2
    if os.environ.get(POSTGRES_BACKEND_ENV, "").strip().casefold() not in {"postgres", "postgresql", "pg"}:
        print(f"{POSTGRES_BACKEND_ENV}=postgres is required.", file=sys.stderr)
        return 2

    instances_dir = Path(args.instances_dir)
    provider = SecretToolInstanceSecretProvider()
    migrated = 0
    for instance_dir in _instance_dirs(instances_dir, tuple(args.instance)):
        store = AccountStore(instance_dir / "data" / "accounts", instance_dir.name, provider)
        for account_dir in _account_dirs(store.accounts_dir):
            account_id = account_dir.name
            entries = store.account_memory_vault.read_jsonl(account_dir / USER_MEMORY_ENTRIES_FILENAME)
            index = store.account_memory_vault.read_json(account_dir / USER_MEMORY_INDEX_FILENAME, {})
            print(f"instance={instance_dir.name} account={account_id} entries={len(entries)} dry_run={args.dry_run}")
            if args.dry_run:
                continue
            store.write_memory_entries(account_id, entries)
            store.write_memory_index(account_id, index)
            migrated += 1
    print(f"migrated_accounts={migrated}")
    return 0


def _instance_dirs(instances_dir: Path, selected: tuple[str, ...]) -> list[Path]:
    if selected:
        return [instances_dir / name for name in selected]
    if not instances_dir.exists():
        return []
    return sorted(path for path in instances_dir.iterdir() if path.is_dir() and (path / "data" / "accounts").exists())


def _account_dirs(accounts_dir: Path) -> list[Path]:
    if not accounts_dir.exists():
        return []
    return sorted(path for path in accounts_dir.iterdir() if path.is_dir() and TOKEN_HEX_RE.fullmatch(path.name))


if __name__ == "__main__":
    raise SystemExit(main())
