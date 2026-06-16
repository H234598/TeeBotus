from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import shutil
import shlex
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
from TeeBotus.runtime.artifacts import safe_artifact_name
from TeeBotus.runtime.sqlite_memory import SQLiteAccountMemoryBackend, SQLiteMemoryConfig

LOGGER = logging.getLogger("TeeBotus")
RECOVERY_SCHEMA_VERSION = 2
SQLITE_MEMORY_TABLES = ("memory_entries", "memory_indexes")
LEGACY_USER_MEMORY_DIRNAME = "users"


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
    legacy_instances_dir: str | Path | None = None,
    provider: InstanceSecretProvider | None = None,
) -> dict[str, Any]:
    resolved_instances_dir = Path(instances_dir)
    resolved_legacy_instances_dir = Path(legacy_instances_dir).expanduser() if legacy_instances_dir else None
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
            "unrecoverable_accounts": 0,
            "empty_accounts": 0,
            "no_source_accounts": 0,
            "sources": 0,
            "readable_sources": 0,
            "unreadable_sources": 0,
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
    accounts_root = instances_dir / instance_name / "data" / "accounts"
    account_ids = _discover_account_ids(accounts_root)
    sources = _discover_recovery_sources(accounts_root)
    account_reports = []
    for account_id in account_ids:
        source_reports = [_inspect_source(source, instance_name=instance_name, account_id=account_id, provider=provider) for source in sources]
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
        "accounts": account_reports,
        "source_count": len(sources),
        "sources": [{"name": source.name, "kind": source.kind, "path": str(source.path)} for source in sources],
    }
    if legacy_instances_dir is not None:
        result["legacy_plaintext_import"] = _legacy_plaintext_import_report(
            legacy_instances_dir=legacy_instances_dir,
            target_instances_dir=instances_dir,
            instance_name=instance_name,
        )
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
        legacy = instance.get("legacy_plaintext_import")
        if isinstance(legacy, Mapping):
            lines.append(f"- legacy_plaintext_import: sources=`{legacy.get('sources', 0)}` entries=`{legacy.get('entries', 0)}` path=`{legacy.get('path', '')}`")
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
                detail = f"entries={source.get('entries', 0)} index_present={source.get('index_present', False)}"
                error = f" error={source.get('error')}" if source.get("error") else ""
                lines.append(f"  - {source.get('name', '')}: {status} {detail}{error}")
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
    blocked = bool(apply and running and not allow_running_bot)
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
            "apply_allowed_now": bool(not blocked),
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
        result["instances"].append(instance_result)
        totals = result["totals"]
        for key in totals:
            totals[key] += int(instance_result.get("totals", {}).get(key, 0) or 0)
    if not result["totals"]["unrecoverable_accounts"]:
        result["status"] = "no-op"
    return result


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
    sqlite_sources = _sqlite_sources_for_unrecoverable_accounts(unrecoverable_accounts)
    json_files = _json_memory_files_for_accounts(accounts_root, account_ids)
    result["totals"]["sqlite_sources"] = len(sqlite_sources)
    result["totals"]["json_files_quarantined"] = len(json_files)
    if not apply:
        result["totals"]["accounts_quarantined"] = len(account_ids)
        result["sqlite_sources"] = [{"path": str(path), "would_snapshot": True, "would_delete_rows": True} for path in sqlite_sources]
        result["json_files"] = [{"path": str(path), "would_move": True} for path in json_files]
        return result

    _prepare_private_dir(instance_quarantine_dir)
    snapshots_dir = instance_quarantine_dir / "sqlite_snapshots"
    for sqlite_path in sqlite_sources:
        snapshot_path = snapshots_dir / sqlite_path.name
        _snapshot_sqlite_database(sqlite_path, snapshot_path)
        result["totals"]["snapshots_created"] += 1
        deleted_rows = _delete_sqlite_account_rows(sqlite_path, instance_name, account_ids)
        result["totals"]["sqlite_rows_quarantined"] += deleted_rows
        result["sqlite_sources"].append({"path": str(sqlite_path), "snapshot": str(snapshot_path), "rows_deleted": deleted_rows})
    moved_files = []
    for path in json_files:
        target = instance_quarantine_dir / "json_files" / path.parent.name / path.name
        _prepare_private_dir(target.parent)
        shutil.move(str(path), str(target))
        moved_files.append({"path": str(path), "quarantine_path": str(target)})
    result["json_files"] = moved_files
    result["totals"]["json_files_quarantined"] = len(moved_files)
    result["totals"]["accounts_quarantined"] = len(account_ids)
    manifest_path = instance_quarantine_dir / "manifest.json"
    manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TeeBotus account-memory recovery report and unrecoverable-data quarantine.")
    parser.add_argument("--instances-dir", default=DEFAULT_INSTANCES_DIR)
    parser.add_argument("--instances", default="", help="Comma-separated instance list. Defaults to all folders with Bot_Verhalten.md.")
    parser.add_argument("--legacy-instances-dir", default="", help="Optional plaintext legacy instances directory to inspect for importable data/users memory.")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--output", default="")
    parser.add_argument("--quarantine-unrecoverable", action="store_true", help="Move unrecoverable encrypted memory payloads out of active stores.")
    parser.add_argument("--apply", action="store_true", help="Apply --quarantine-unrecoverable. Without this, only report what would move.")
    parser.add_argument("--quarantine-dir", default="", help="Optional base directory for quarantine artifacts. Defaults below each accounts root.")
    parser.add_argument("--allow-running-bot", action="store_true", help="Allow quarantine apply while TeeBotus runtime processes are running.")
    args = parser.parse_args(list(argv) if argv is not None else None)
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
    output = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n" if args.format == "json" else render_text_report(report)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return exit_code


def _sqlite_sources_for_unrecoverable_accounts(accounts: Sequence[Mapping[str, Any]]) -> list[Path]:
    paths: list[Path] = []
    for account in accounts:
        for source in account.get("sources", []) if isinstance(account.get("sources"), list) else []:
            if not isinstance(source, Mapping) or source.get("kind") != "sqlite":
                continue
            if int(source.get("raw_entries", 0) or 0) <= 0 and not bool(source.get("raw_index_present")):
                continue
            raw_path = str(source.get("path") or "").strip()
            if not raw_path:
                continue
            path = Path(raw_path)
            if path not in paths:
                paths.append(path)
    return paths


def _json_memory_files_for_accounts(accounts_root: Path, account_ids: Sequence[str]) -> list[Path]:
    files: list[Path] = []
    for account_id in account_ids:
        account_dir = accounts_root / ACCOUNTS_DIRNAME / account_id
        for filename in (USER_MEMORY_ENTRIES_FILENAME, USER_MEMORY_INDEX_FILENAME):
            path = account_dir / filename
            if path.exists():
                files.append(path)
    return files


def _snapshot_sqlite_database(source: Path, target: Path) -> None:
    _prepare_private_dir(target.parent)
    with sqlite3.connect(source) as source_connection, sqlite3.connect(target) as target_connection:
        source_connection.backup(target_connection)
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass


def _delete_sqlite_account_rows(path: Path, instance_name: str, account_ids: Sequence[str]) -> int:
    deleted = 0
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
    return deleted


def _delete_row_count(cursor: sqlite3.Cursor) -> int:
    return max(0, int(cursor.rowcount if cursor.rowcount is not None else 0))


def _prepare_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


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
        if "teebotus-proactive" in lowered or "-m teebotus " in f"{lowered} ":
            processes.append({"pid": pid_dir.name, "cmdline": cmdline[:500]})
    return processes


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


def _legacy_plaintext_import_report(*, legacy_instances_dir: Path, target_instances_dir: Path, instance_name: str) -> dict[str, Any]:
    effective_legacy_instances_dir = _resolve_legacy_instances_dir(legacy_instances_dir, instance_name)
    instance_users_dir = effective_legacy_instances_dir / instance_name / "data" / LEGACY_USER_MEMORY_DIRNAME
    sources = 0
    entries = 0
    encrypted_sources = 0
    malformed_sources = 0
    if instance_users_dir.exists():
        for user_dir in sorted(path for path in instance_users_dir.iterdir() if path.is_dir()):
            entries_path = user_dir / USER_MEMORY_ENTRIES_FILENAME
            if not entries_path.exists():
                continue
            source_kind, source_entries = _legacy_entries_file_shape(entries_path)
            if source_kind == "plaintext":
                sources += 1
                entries += source_entries
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
            "--replace-unreadable-account-metadata",
            "--json-output",
            str(Path.home() / "Downloads" / f"teebotus-legacy-import-preflight-{artifact_name}.json"),
            "--markdown-output",
            str(Path.home() / "Downloads" / f"teebotus-legacy-import-preflight-{artifact_name}.md"),
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
        "legacy_instances_dir": str(effective_legacy_instances_dir),
        "path": str(instance_users_dir),
        "sources": sources,
        "entries": entries,
        "encrypted_sources": encrypted_sources,
        "malformed_sources": malformed_sources,
        "dry_run_command": command,
        "apply_command": apply_command,
        "apply_requires": "--apply plus explicit review of metadata/account-memory replacement flags",
    }


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
        if source.get("readable") and (int(source.get("entries", 0) or 0) > 0 or bool(source.get("index_present")))
    ]
    if readable_payload_sources:
        names = ", ".join(str(source.get("name") or "<unknown>") for source in readable_payload_sources)
        return "recoverable", f"Recover from readable source(s): {names}."
    raw_payload_sources = [
        source
        for source in source_reports
        if int(source.get("raw_entries", 0) or 0) > 0 or bool(source.get("raw_index_present"))
    ]
    if raw_payload_sources:
        return (
            "unrecoverable",
            "Raw encrypted payloads exist, but no source is readable with the current instance secret; keep backups and restore the matching old secret if available.",
        )
    readable_empty_sources = [source for source in source_reports if source.get("readable")]
    if readable_empty_sources:
        return "empty", "Sources are readable but contain no memory payloads for this account."
    return "unrecoverable", "No source is readable with the current instance secret; keep backups before changing account-memory files."


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
        totals["legacy_plaintext_sources"] += int(legacy.get("sources", 0) or 0)
        totals["legacy_plaintext_entries"] += int(legacy.get("entries", 0) or 0)


__all__ = [
    "build_account_memory_recovery_report",
    "build_instance_recovery_report",
    "main",
    "render_text_report",
]
