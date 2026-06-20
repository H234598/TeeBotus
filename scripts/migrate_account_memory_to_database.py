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
    AGENT_STATE_COLLECTION,
    AGENT_STATE_FILENAME,
    CODEX_HISTORY_DISPATCH_RESULTS_COLLECTION,
    CODEX_HISTORY_DISPATCH_RESULTS_FILENAME,
    CODEX_HISTORY_OUTBOX_COLLECTION,
    CODEX_HISTORY_OUTBOX_FILENAME,
    CODEX_HISTORY_PROJECTS_COLLECTION,
    CODEX_HISTORY_PROJECTS_FILENAME,
    LLM_STATE_COLLECTION,
    LLM_STATE_FILENAME,
    OPENAI_STATE_FILENAME,
    PROACTIVE_AUDIT_COLLECTION,
    PROACTIVE_AUDIT_FILENAME,
    PROACTIVE_DISPATCH_RESULTS_COLLECTION,
    PROACTIVE_DISPATCH_RESULTS_FILENAME,
    PROACTIVE_OUTBOX_COLLECTION,
    PROACTIVE_OUTBOX_FILENAME,
    STATUS_AUTH_STATE_COLLECTION,
    STATUS_AUTH_STATE_FILENAME,
    STATUS_DISPATCH_RESULTS_COLLECTION,
    STATUS_DISPATCH_RESULTS_FILENAME,
    STATUS_OUTBOX_COLLECTION,
    STATUS_OUTBOX_FILENAME,
    USER_MEMORY_ENTRIES_FILENAME,
    USER_MEMORY_INDEX_FILENAME,
    AccountStore,
    SecretToolInstanceSecretProvider,
    TOKEN_HEX_RE,
    _choose_newer_state,
    _merge_account_jsonl_rows,
    _merge_json_document_rows,
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
            if not _account_source_artifacts(account_dir):
                skipped += 1
                continue
            artifact_result = _migrate_account_artifacts(
                source_store=source_store,
                target_store=target_store,
                instance_name=instance_dir.name,
                account_id=account_id,
                account_dir=account_dir,
                dry_run=dry_run,
                delete_json_files=delete_json_files,
            )
            print(
                f"instance={instance_dir.name} account={account_id} entries={artifact_result['entries']} "
                f"artifacts={artifact_result['artifacts']} dry_run={dry_run} delete_json_files={delete_json_files}"
            )
            if dry_run:
                skipped += 1
                continue
            migrated += 1
            deleted += artifact_result["deleted"]
    return {"migrated": migrated, "skipped": skipped, "deleted": deleted}


ACCOUNT_JSON_DOCUMENT_ARTIFACTS = (
    (LLM_STATE_COLLECTION, (LLM_STATE_FILENAME, OPENAI_STATE_FILENAME)),
    (AGENT_STATE_COLLECTION, (AGENT_STATE_FILENAME,)),
    (STATUS_AUTH_STATE_COLLECTION, (STATUS_AUTH_STATE_FILENAME,)),
)


ACCOUNT_JSONL_COLLECTION_ARTIFACTS = (
    (PROACTIVE_OUTBOX_COLLECTION, PROACTIVE_OUTBOX_FILENAME),
    (PROACTIVE_AUDIT_COLLECTION, PROACTIVE_AUDIT_FILENAME),
    (PROACTIVE_DISPATCH_RESULTS_COLLECTION, PROACTIVE_DISPATCH_RESULTS_FILENAME),
    (STATUS_OUTBOX_COLLECTION, STATUS_OUTBOX_FILENAME),
    (STATUS_DISPATCH_RESULTS_COLLECTION, STATUS_DISPATCH_RESULTS_FILENAME),
    (CODEX_HISTORY_OUTBOX_COLLECTION, CODEX_HISTORY_OUTBOX_FILENAME),
    (CODEX_HISTORY_DISPATCH_RESULTS_COLLECTION, CODEX_HISTORY_DISPATCH_RESULTS_FILENAME),
    (CODEX_HISTORY_PROJECTS_COLLECTION, CODEX_HISTORY_PROJECTS_FILENAME),
)


def _account_source_artifacts(account_dir: Path) -> list[Path]:
    paths = [
        account_dir / USER_MEMORY_ENTRIES_FILENAME,
        account_dir / USER_MEMORY_INDEX_FILENAME,
    ]
    for _collection, filenames in ACCOUNT_JSON_DOCUMENT_ARTIFACTS:
        paths.extend(account_dir / filename for filename in filenames)
    for _collection, filename in ACCOUNT_JSONL_COLLECTION_ARTIFACTS:
        paths.append(account_dir / filename)
    return [path for path in paths if path.exists()]


def _migrate_account_artifacts(
    *,
    source_store: AccountStore,
    target_store: AccountStore,
    instance_name: str,
    account_id: str,
    account_dir: Path,
    dry_run: bool,
    delete_json_files: bool,
) -> dict[str, int]:
    artifacts = _account_source_artifacts(account_dir)
    result = {"entries": 0, "artifacts": len(artifacts), "deleted": 0}
    if not artifacts:
        return result
    if dry_run:
        entries_path = account_dir / USER_MEMORY_ENTRIES_FILENAME
        if entries_path.exists():
            result["entries"] = len(source_store._read_jsonl_with_fallback(entries_path, vault=source_store.account_memory_vault))
        return result
    result["deleted"] += _migrate_memory_entry_artifacts(
        source_store=source_store,
        target_store=target_store,
        instance_name=instance_name,
        account_id=account_id,
        account_dir=account_dir,
        delete_json_files=delete_json_files,
        result=result,
    )
    result["deleted"] += _migrate_json_document_artifacts(
        source_store=source_store,
        target_store=target_store,
        instance_name=instance_name,
        account_id=account_id,
        account_dir=account_dir,
        delete_json_files=delete_json_files,
    )
    result["deleted"] += _migrate_jsonl_collection_artifacts(
        source_store=source_store,
        target_store=target_store,
        instance_name=instance_name,
        account_id=account_id,
        account_dir=account_dir,
        delete_json_files=delete_json_files,
    )
    return result


def _migrate_memory_entry_artifacts(
    *,
    source_store: AccountStore,
    target_store: AccountStore,
    instance_name: str,
    account_id: str,
    account_dir: Path,
    delete_json_files: bool,
    result: dict[str, int],
) -> int:
    entries_path = account_dir / USER_MEMORY_ENTRIES_FILENAME
    index_path = account_dir / USER_MEMORY_INDEX_FILENAME
    if not entries_path.exists() and not index_path.exists():
        return 0
    source_entries = source_store._read_jsonl_with_fallback(entries_path, vault=source_store.account_memory_vault) if entries_path.exists() else []
    source_index = source_store._read_json_with_fallback(index_path, {}, vault=source_store.account_memory_vault) if index_path.exists() else {}
    target_entries = target_store.read_memory_entries(account_id)
    target_index = target_store.read_memory_index(account_id)
    merged_entries = _merge_account_jsonl_rows(target_entries, source_entries)
    selected_index = _choose_newer_state(source_index, target_index) if source_index else target_index
    result["entries"] = len(source_entries)
    if merged_entries != target_entries:
        target_store.write_memory_entries(account_id, merged_entries)
    if source_index:
        target_store.write_memory_index(account_id, selected_index)
    elif merged_entries != target_entries:
        target_store.rebuild_structured_memory_index(account_id)
    if target_store.read_memory_entries(account_id) != merged_entries:
        raise SystemExit(f"verification failed for entries: {instance_name}/{account_id}")
    if source_index and target_store.read_memory_index(account_id) != selected_index:
        raise SystemExit(f"verification failed for index: {instance_name}/{account_id}")
    if merged_entries != target_entries:
        health = target_store.check_structured_memory_index(account_id)
        if not health.ok:
            raise SystemExit(f"index health check failed for {instance_name}/{account_id}: {'; '.join(health.errors)}")
    return _delete_verified_files((entries_path, index_path), enabled=delete_json_files)


def _migrate_json_document_artifacts(
    *,
    source_store: AccountStore,
    target_store: AccountStore,
    instance_name: str,
    account_id: str,
    account_dir: Path,
    delete_json_files: bool,
) -> int:
    backend = target_store.account_memory_backend
    read_collection = getattr(backend, "read_collection", None) if backend is not None else None
    write_collection = getattr(backend, "write_collection", None) if backend is not None else None
    if not (callable(read_collection) and callable(write_collection)):
        return 0
    deleted = 0
    for collection, filenames in ACCOUNT_JSON_DOCUMENT_ARTIFACTS:
        paths = [account_dir / filename for filename in filenames if (account_dir / filename).exists()]
        if not paths:
            continue
        sql_rows = [row for row in read_collection(account_id, collection) if isinstance(row, dict)]
        sql_document = _merge_json_document_rows(sql_rows, {})
        selected = dict(sql_document)
        for path in paths:
            source_document = source_store._read_json_with_fallback(path, {}, vault=source_store.account_memory_vault)
            selected = _choose_newer_state(source_document, selected)
        if selected != sql_document or len(sql_rows) != 1:
            write_collection(account_id, collection, [selected])
        verified = _merge_json_document_rows([row for row in read_collection(account_id, collection) if isinstance(row, dict)], {})
        if verified != selected:
            raise SystemExit(f"verification failed for {collection}: {instance_name}/{account_id}")
        deleted += _delete_verified_files(paths, enabled=delete_json_files)
    return deleted


def _migrate_jsonl_collection_artifacts(
    *,
    source_store: AccountStore,
    target_store: AccountStore,
    instance_name: str,
    account_id: str,
    account_dir: Path,
    delete_json_files: bool,
) -> int:
    backend = target_store.account_memory_backend
    read_collection = getattr(backend, "read_collection", None) if backend is not None else None
    write_collection = getattr(backend, "write_collection", None) if backend is not None else None
    if not (callable(read_collection) and callable(write_collection)):
        return 0
    deleted = 0
    for collection, filename in ACCOUNT_JSONL_COLLECTION_ARTIFACTS:
        path = account_dir / filename
        if not path.exists():
            continue
        source_rows = source_store._read_jsonl_with_fallback(path, vault=source_store.account_memory_vault)
        sql_rows = [row for row in read_collection(account_id, collection) if isinstance(row, dict)]
        merged_rows = _merge_account_jsonl_rows(sql_rows, source_rows)
        if merged_rows != sql_rows:
            write_collection(account_id, collection, merged_rows)
        verified_rows = [row for row in read_collection(account_id, collection) if isinstance(row, dict)]
        if verified_rows != merged_rows:
            raise SystemExit(f"verification failed for {collection}: {instance_name}/{account_id}")
        deleted += _delete_verified_files((path,), enabled=delete_json_files)
    return deleted


def _delete_verified_files(paths: Iterable[Path], *, enabled: bool) -> int:
    if not enabled:
        return 0
    deleted = 0
    for path in paths:
        if not path.exists():
            continue
        path.unlink()
        deleted += 1
    return deleted


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
        names = tuple(dict.fromkeys(str(name).strip() for name in selected if str(name).strip()))
        return [instances_dir / name for name in names if (instances_dir / name).is_dir()]
    if not instances_dir.exists():
        return []
    return sorted(path for path in instances_dir.iterdir() if path.is_dir() and (path / "data" / "accounts").exists())


def _account_dirs(accounts_dir: Path) -> list[Path]:
    if not accounts_dir.exists():
        return []
    return sorted(path for path in accounts_dir.iterdir() if path.is_dir() and TOKEN_HEX_RE.fullmatch(path.name))


if __name__ == "__main__":
    raise SystemExit(main())
