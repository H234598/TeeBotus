#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from TeeBotus.user_memory_crypto import (  # noqa: E402
    USER_MEMORY_KEY_FILENAME,
    UserMemoryCryptoError,
    ensure_user_memory_key,
    is_encrypted_payload,
    read_json,
    read_jsonl,
    read_text,
    write_json,
    write_jsonl,
    write_text,
)


USER_MEMORY_INDEX_FILENAME = "User_Memory_Index.json"
USER_MEMORY_ENTRIES_FILENAME = "User_Memory_Entries.jsonl"
USER_HABITS_FILENAME = "User_Habbits_and_behave.md"


@dataclass
class MigrationResult:
    encrypted: int = 0
    already_encrypted: int = 0
    missing: int = 0
    users: int = 0
    errors: int = 0

    def add(self, other: "MigrationResult") -> None:
        self.encrypted += other.encrypted
        self.already_encrypted += other.already_encrypted
        self.missing += other.missing
        self.users += other.users
        self.errors += other.errors


def known_user_memory_files(user_dir: Path) -> tuple[tuple[Path, str], ...]:
    return (
        (user_dir / USER_MEMORY_INDEX_FILENAME, "user-memory-index"),
        (user_dir / USER_MEMORY_ENTRIES_FILENAME, "user-memory-entries"),
        (user_dir / USER_HABITS_FILENAME, "user-memory-habits"),
    )


def iter_user_dirs(instances_dir: Path) -> list[Path]:
    if not instances_dir.exists():
        return []
    user_dirs: list[Path] = []
    for users_dir in sorted(instances_dir.glob("*/data/users")):
        if not users_dir.is_dir():
            continue
        for user_dir in sorted(users_dir.iterdir()):
            if user_dir.is_dir():
                user_dirs.append(user_dir)
    return user_dirs


def instance_name_for_user_dir(user_dir: Path) -> str:
    try:
        return user_dir.parents[2].name
    except IndexError as exc:
        raise UserMemoryCryptoError(f"cannot infer instance name from {user_dir}") from exc


def migrate_user_dir(user_dir: Path, *, dry_run: bool = False, verify_only: bool = False) -> MigrationResult:
    result = MigrationResult(users=1)
    key: bytes | None = None

    def user_key() -> bytes:
        nonlocal key
        if key is None:
            key = ensure_user_memory_key(
                user_dir / USER_MEMORY_KEY_FILENAME,
                instance_name=instance_name_for_user_dir(user_dir),
                sender_id=user_dir.name,
            )
        return key

    for path, kind in known_user_memory_files(user_dir):
        if not path.exists():
            result.missing += 1
            continue
        raw = path.read_bytes()
        if is_encrypted_payload(raw):
            result.already_encrypted += 1
            continue
        if verify_only:
            result.errors += 1
            continue
        if dry_run:
            result.encrypted += 1
            continue
        key_bytes = user_key()
        if kind == "user-memory-index":
            payload, _ = read_json(path, key_bytes, kind=kind, default={})
            write_json(path, key_bytes, kind=kind, data=payload)
        elif kind == "user-memory-entries":
            entries, _ = read_jsonl(path, key_bytes, kind=kind)
            write_jsonl(path, key_bytes, kind=kind, entries=entries)
        else:
            text, _ = read_text(path, key_bytes, kind=kind)
            write_text(path, key_bytes, kind=kind, text=text)
        result.encrypted += 1
    return result


def migrate_instances(instances_dir: Path, *, dry_run: bool = False, verify_only: bool = False, verbose: bool = False) -> MigrationResult:
    result = MigrationResult()
    for user_dir in iter_user_dirs(instances_dir):
        try:
            user_result = migrate_user_dir(user_dir, dry_run=dry_run, verify_only=verify_only)
        except (OSError, UserMemoryCryptoError) as exc:
            result.users += 1
            result.errors += 1
            if verbose:
                print(f"ERROR {user_dir}: {exc}", file=sys.stderr)
            continue
        result.add(user_result)
        if verbose and user_result.encrypted:
            action = "would encrypt" if dry_run else "encrypted"
            print(f"{action} {user_result.encrypted} known memory files in {user_dir}")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Encrypt or verify known TeeBotus user-memory files.")
    parser.add_argument("--instances-dir", type=Path, default=ROOT / "instances")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = migrate_instances(
        args.instances_dir,
        dry_run=args.dry_run,
        verify_only=args.verify_only,
        verbose=args.verbose,
    )
    if not args.quiet or result.errors:
        mode = "verify" if args.verify_only else "dry-run" if args.dry_run else "migrate"
        print(
            f"user-memory-encryption {mode}: users={result.users} encrypted={result.encrypted} "
            f"already_encrypted={result.already_encrypted} missing={result.missing} errors={result.errors}"
        )
    return 1 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
