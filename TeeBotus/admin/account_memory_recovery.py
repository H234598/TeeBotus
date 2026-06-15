from __future__ import annotations

import argparse
import contextlib
import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from TeeBotus.admin.accounts_report import DEFAULT_INSTANCES_DIR, ReadOnlySecretToolInstanceSecretProvider, discover_instances, parse_csv
from TeeBotus.runtime.accounts import (
    ACCOUNTS_DIRNAME,
    ACCOUNT_MEMORY_KEY_PURPOSE,
    AccountStoreError,
    InstanceSecretProvider,
    TOKEN_HEX_RE,
    USER_MEMORY_ENTRIES_FILENAME,
    USER_MEMORY_INDEX_FILENAME,
)
from TeeBotus.runtime.sqlite_memory import SQLiteAccountMemoryBackend, SQLiteMemoryConfig

LOGGER = logging.getLogger("TeeBotus")
RECOVERY_SCHEMA_VERSION = 1
SQLITE_MEMORY_TABLES = ("memory_entries", "memory_indexes")


@dataclass(frozen=True)
class RecoverySource:
    name: str
    kind: str
    path: Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_account_memory_recovery_report(
    *,
    instances_dir: str | Path = DEFAULT_INSTANCES_DIR,
    instances: Sequence[str] = (),
    provider: InstanceSecretProvider | None = None,
) -> dict[str, Any]:
    resolved_instances_dir = Path(instances_dir)
    provider = provider or ReadOnlySecretToolInstanceSecretProvider()
    selected_instances = discover_instances(resolved_instances_dir, instances)
    report: dict[str, Any] = {
        "schema_version": RECOVERY_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "instances_dir": str(resolved_instances_dir),
        "instance_count": len(selected_instances),
        "instances": [],
        "totals": {
            "accounts": 0,
            "recoverable_accounts": 0,
            "sources": 0,
            "readable_sources": 0,
            "unreadable_sources": 0,
        },
    }
    for instance_name in selected_instances:
        instance_report = build_instance_recovery_report(
            instances_dir=resolved_instances_dir,
            instance_name=instance_name,
            provider=provider,
        )
        report["instances"].append(instance_report)
        _add_totals(report["totals"], instance_report)
    return report


def build_instance_recovery_report(
    *,
    instances_dir: Path,
    instance_name: str,
    provider: InstanceSecretProvider,
) -> dict[str, Any]:
    accounts_root = instances_dir / instance_name / "data" / "accounts"
    account_ids = _discover_account_ids(accounts_root)
    sources = _discover_recovery_sources(accounts_root)
    account_reports = []
    for account_id in account_ids:
        source_reports = [_inspect_source(source, instance_name=instance_name, account_id=account_id, provider=provider) for source in sources]
        account_reports.append(
            {
                "account_id": account_id,
                "recoverable": any(source.get("readable") and (source.get("entries", 0) or source.get("index_present")) for source in source_reports),
                "sources": source_reports,
            }
        )
    return {
        "instance": instance_name,
        "accounts_root": str(accounts_root),
        "accounts": account_reports,
        "source_count": len(sources),
        "sources": [{"name": source.name, "kind": source.kind, "path": str(source.path)} for source in sources],
    }


def render_text_report(report: Mapping[str, Any]) -> str:
    lines = [
        "TeeBotus Account-Memory Recovery Report",
        f"Generated: {report.get('generated_at', '')}",
        f"Instances dir: {report.get('instances_dir', '')}",
        "",
        "Totals:",
    ]
    totals = report.get("totals", {})
    if isinstance(totals, Mapping):
        for key in sorted(totals):
            lines.append(f"  {key}: {totals[key]}")
    for instance in report.get("instances", []):
        if not isinstance(instance, Mapping):
            continue
        lines.extend(["", f"Instance: {instance.get('instance', '')}", f"  source_count: {instance.get('source_count', 0)}"])
        for account in instance.get("accounts", []):
            if not isinstance(account, Mapping):
                continue
            lines.append(f"  account: {account.get('account_id', '')} recoverable={account.get('recoverable', False)}")
            for source in account.get("sources", []):
                if not isinstance(source, Mapping):
                    continue
                status = "readable" if source.get("readable") else "unreadable"
                detail = f"entries={source.get('entries', 0)} index_present={source.get('index_present', False)}"
                error = f" error={source.get('error')}" if source.get("error") else ""
                lines.append(f"    {source.get('name', '')}: {status} {detail}{error}")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only TeeBotus account-memory recovery report.")
    parser.add_argument("--instances-dir", default=DEFAULT_INSTANCES_DIR)
    parser.add_argument("--instances", default="", help="Comma-separated instance list. Defaults to all folders with Bot_Verhalten.md.")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--output", default="")
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = build_account_memory_recovery_report(instances_dir=args.instances_dir, instances=parse_csv(args.instances))
    output = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n" if args.format == "json" else render_text_report(report)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


def _discover_account_ids(accounts_root: Path) -> list[str]:
    account_ids: set[str] = set()
    accounts_dir = accounts_root / ACCOUNTS_DIRNAME
    if accounts_dir.exists():
        account_ids.update(path.name for path in accounts_dir.iterdir() if path.is_dir() and TOKEN_HEX_RE.fullmatch(path.name))
    for db_path in (accounts_root / "Account_Memory.sqlite3", accounts_root / "Account_Memory.backup.sqlite3"):
        account_ids.update(_sqlite_account_ids(db_path))
    return sorted(account_ids)


def _discover_recovery_sources(accounts_root: Path) -> list[RecoverySource]:
    sources: list[RecoverySource] = []
    for name, path in (
        ("sqlite_primary", accounts_root / "Account_Memory.sqlite3"),
        ("sqlite_fallback", accounts_root / "Account_Memory.backup.sqlite3"),
    ):
        if path.exists():
            sources.append(RecoverySource(name, "sqlite", path))
    accounts_dir = accounts_root / ACCOUNTS_DIRNAME
    if accounts_dir.exists():
        sources.append(RecoverySource("json_files", "json", accounts_dir))
    return sources


def _inspect_source(source: RecoverySource, *, instance_name: str, account_id: str, provider: InstanceSecretProvider) -> dict[str, Any]:
    if source.kind == "sqlite":
        return _inspect_sqlite_source(source, instance_name=instance_name, account_id=account_id, provider=provider)
    return _inspect_json_source(source, instance_name=instance_name, account_id=account_id, provider=provider)


def _inspect_sqlite_source(source: RecoverySource, *, instance_name: str, account_id: str, provider: InstanceSecretProvider) -> dict[str, Any]:
    raw_entries, raw_index_present = _sqlite_raw_counts(source.path, instance_name, account_id)
    backend = SQLiteAccountMemoryBackend(
        instance_name=instance_name,
        provider=provider,
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=source.path, fallback_path=None),
    )
    with _suppress_expected_backend_logs():
        entries = backend.read_entries(account_id)
        index = backend.read_index(account_id)
    errors = []
    if backend.last_entry_read_error:
        errors.append(f"entries: {backend.last_entry_read_error}")
    if backend.last_index_read_error:
        errors.append(f"index: {backend.last_index_read_error}")
    return {
        "name": source.name,
        "kind": source.kind,
        "path": str(source.path),
        "readable": not errors,
        "entries": len(entries),
        "raw_entries": raw_entries,
        "index_present": bool(index),
        "raw_index_present": raw_index_present,
        "error": "; ".join(errors),
    }


def _inspect_json_source(source: RecoverySource, *, instance_name: str, account_id: str, provider: InstanceSecretProvider) -> dict[str, Any]:
    store = _JsonProbeStore(source.path.parent, instance_name, secret_provider=provider, create_dirs=False)
    entries_path = source.path / account_id / USER_MEMORY_ENTRIES_FILENAME
    index_path = source.path / account_id / USER_MEMORY_INDEX_FILENAME
    errors = []
    entries: list[dict[str, Any]] = []
    index: dict[str, Any] = {}
    if entries_path.exists():
        try:
            entries = store.account_memory_vault.read_jsonl(entries_path)
        except AccountStoreError as exc:
            errors.append(f"entries: {exc}")
    if index_path.exists():
        try:
            index = store.account_memory_vault.read_json(index_path, {})
        except AccountStoreError as exc:
            errors.append(f"index: {exc}")
    return {
        "name": source.name,
        "kind": source.kind,
        "path": str(source.path),
        "readable": not errors,
        "entries": len(entries),
        "raw_entries": _count_lines(entries_path),
        "index_present": bool(index),
        "raw_index_present": index_path.exists(),
        "error": "; ".join(errors),
    }


class _JsonProbeStore:
    def __init__(self, root: Path, instance_name: str, *, secret_provider: InstanceSecretProvider, create_dirs: bool = False) -> None:
        from TeeBotus.runtime.accounts import AccountStore

        self._store = AccountStore(root, instance_name, secret_provider=secret_provider, create_dirs=create_dirs)

    @property
    def account_memory_vault(self):
        return self._store.account_memory_vault


def _sqlite_account_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        with sqlite3.connect(path) as connection:
            ids = set()
            for table in SQLITE_MEMORY_TABLES:
                if not _sqlite_table_exists(connection, table):
                    continue
                ids.update(str(row[0]) for row in connection.execute(f"SELECT DISTINCT account_id FROM {table}"))
            return {account_id for account_id in ids if TOKEN_HEX_RE.fullmatch(account_id)}
    except sqlite3.Error:
        return set()


def _sqlite_raw_counts(path: Path, instance_name: str, account_id: str) -> tuple[int, bool]:
    try:
        with sqlite3.connect(path) as connection:
            entries = 0
            index_present = False
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
            return entries, index_present
    except sqlite3.Error:
        return 0, False


def _sqlite_table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table,)).fetchone() is not None


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return sum(1 for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())
    except OSError:
        return 0


@contextlib.contextmanager
def _suppress_expected_backend_logs():
    previous_disabled = LOGGER.disabled
    LOGGER.disabled = True
    try:
        yield
    finally:
        LOGGER.disabled = previous_disabled


def _add_totals(totals: dict[str, int], instance_report: Mapping[str, Any]) -> None:
    for account in instance_report.get("accounts", []) if isinstance(instance_report.get("accounts"), list) else []:
        if not isinstance(account, Mapping):
            continue
        totals["accounts"] += 1
        if account.get("recoverable"):
            totals["recoverable_accounts"] += 1
        for source in account.get("sources", []) if isinstance(account.get("sources"), list) else []:
            if not isinstance(source, Mapping):
                continue
            totals["sources"] += 1
            if source.get("readable"):
                totals["readable_sources"] += 1
            else:
                totals["unreadable_sources"] += 1


__all__ = [
    "build_account_memory_recovery_report",
    "build_instance_recovery_report",
    "main",
    "render_text_report",
]
