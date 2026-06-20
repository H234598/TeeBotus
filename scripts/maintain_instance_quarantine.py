#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
DEFAULT_QUARANTINE_DIRNAME = ".quarantine"
DEFAULT_RETENTION_DAYS = 7
DEFAULT_SERVICE_NAME = "teebotus-instance-quarantine-retention.service"
DEFAULT_TIMER_NAME = "teebotus-instance-quarantine-retention.timer"
DEFAULT_SQL_CONFIRMATION_NAME = "sql-backup-confirmed.json"
MANIFEST_NAME = "manifest.json"
PSEUDO_INSTANCE_NAMES = frozenset({"Bench", "Demo", "all"})
ACCOUNT_QUARANTINE_DIR_NAMES = frozenset({"Account_Memory_Quarantine", "Account_Metadata_Quarantine", "quarantine"})
ACTIVE_ACCOUNT_STORE_NAMES = frozenset(
    {
        "accounts",
        "Account_Memory.sqlite3",
        "Account_Memory.sqlite3-wal",
        "Account_Memory.sqlite3-shm",
        "Account_Memory.backup.sqlite3",
        "Account_Memory.backup.sqlite3-wal",
        "Account_Memory.backup.sqlite3-shm",
        "Account_Index.json",
        "Account_Identities.json",
        "Account_Keyring.json",
        "Account_Secrets.json",
    }
)


@dataclass(frozen=True)
class QuarantineCandidate:
    path: Path
    reason: str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Quarantine and retain stale TeeBotus instance backup artifacts.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    quarantine = subparsers.add_parser("quarantine", help="Move stale backup artifacts into a central dated quarantine bundle.")
    _add_common_paths(quarantine)
    quarantine.add_argument("--apply", action="store_true", help="Actually move artifacts. Without this, only prints the plan.")
    quarantine.add_argument("--timestamp", default="", help="Override UTC timestamp for deterministic tests.")

    retention = subparsers.add_parser("retention", help="Archive old central quarantine bundles and optionally remove raw bundles.")
    _add_common_paths(retention)
    retention.add_argument("--apply", action="store_true", help="Actually archive/remove eligible bundles. Without this, only prints the plan.")
    retention.add_argument("--min-age-days", type=int, default=DEFAULT_RETENTION_DAYS)
    retention.add_argument(
        "--delete-raw-after-archive",
        action="store_true",
        help="Remove the raw cleanup-* directory after a successful tar.gz archive.",
    )
    retention.add_argument(
        "--sql-confirmation",
        default="",
        help="Path to SQL backup confirmation JSON. Defaults to instances/.quarantine/sql-backup-confirmed.json.",
    )

    confirm = subparsers.add_parser("confirm-sql-backup", help="Write a local SQL backup confirmation gate for retention.")
    _add_common_paths(confirm)
    confirm.add_argument("--apply", action="store_true", help="Write the confirmation file.")
    confirm.add_argument("--backup-label", default="", help="Human label/path/id for the confirmed SQL backup.")
    confirm.add_argument("--sql-confirmation", default="", help="Override confirmation JSON path.")

    install = subparsers.add_parser("install-systemd", help="Install a user-systemd retention timer.")
    _add_common_paths(install)
    install.add_argument("--enable", action="store_true", help="Enable and start the timer after writing unit files.")
    install.add_argument("--print", dest="print_only", action="store_true", help="Print units instead of writing them.")
    install.add_argument("--python", default="", help="Python executable. Defaults to repo .venv-py313/bin/python if present.")
    install.add_argument("--service-name", default=DEFAULT_SERVICE_NAME)
    install.add_argument("--timer-name", default=DEFAULT_TIMER_NAME)
    install.add_argument("--interval", default="daily", help="systemd OnCalendar value.")
    install.add_argument("--randomized-delay", default="30min")
    install.add_argument("--min-age-days", type=int, default=DEFAULT_RETENTION_DAYS)
    install.add_argument(
        "--keep-raw-after-archive",
        action="store_true",
        help="Install the timer without deleting raw cleanup-* bundles after successful archival.",
    )

    args = parser.parse_args(argv)
    if args.command == "quarantine":
        summary = quarantine_stale_instance_artifacts(
            instances_dir=Path(args.instances_dir),
            quarantine_root=_quarantine_root(args.instances_dir, args.quarantine_root),
            apply=bool(args.apply),
            timestamp_override=args.timestamp,
        )
    elif args.command == "retention":
        summary = apply_retention(
            instances_dir=Path(args.instances_dir),
            quarantine_root=_quarantine_root(args.instances_dir, args.quarantine_root),
            apply=bool(args.apply),
            min_age_days=max(0, int(args.min_age_days)),
            delete_raw_after_archive=bool(args.delete_raw_after_archive),
            sql_confirmation_path=_sql_confirmation_path(args.instances_dir, args.quarantine_root, args.sql_confirmation),
        )
    elif args.command == "confirm-sql-backup":
        summary = confirm_sql_backup(
            instances_dir=Path(args.instances_dir),
            quarantine_root=_quarantine_root(args.instances_dir, args.quarantine_root),
            confirmation_path=_sql_confirmation_path(args.instances_dir, args.quarantine_root, args.sql_confirmation),
            backup_label=args.backup_label,
            apply=bool(args.apply),
        )
    elif args.command == "install-systemd":
        summary = install_systemd_timer(
            repo_root=Path.cwd(),
            instances_dir=Path(args.instances_dir),
            quarantine_root=_quarantine_root(args.instances_dir, args.quarantine_root),
            python_executable=args.python,
            service_name=args.service_name,
            timer_name=args.timer_name,
            interval=args.interval,
            randomized_delay=args.randomized_delay,
            min_age_days=max(0, int(args.min_age_days)),
            delete_raw_after_archive=not bool(args.keep_raw_after_archive),
            enable=bool(args.enable),
            print_only=bool(args.print_only),
        )
    else:  # pragma: no cover - argparse enforces this.
        parser.error("missing command")
    if summary is not None:
        print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _add_common_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--instances-dir", default="instances", help="TeeBotus instances directory.")
    parser.add_argument(
        "--quarantine-root",
        default="",
        help="Central quarantine root. Defaults to <instances-dir>/.quarantine.",
    )


def quarantine_stale_instance_artifacts(
    *,
    instances_dir: Path,
    quarantine_root: Path,
    apply: bool,
    timestamp_override: str = "",
) -> dict[str, Any]:
    instances = instances_dir.expanduser().resolve()
    quarantine = _safe_quarantine_root(instances, quarantine_root)
    candidates = collect_quarantine_candidates(instances, quarantine)
    timestamp = _timestamp(timestamp_override)
    bundle = _unique_path(quarantine / f"cleanup-{timestamp}") if apply and candidates else quarantine / f"cleanup-{timestamp}"
    items = [_candidate_manifest_item(candidate, instances, bundle) for candidate in candidates]
    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "operation": "quarantine",
        "apply": bool(apply),
        "created_at": _utc_now(),
        "instances_dir": str(instances),
        "quarantine_root": str(quarantine),
        "bundle_dir": str(bundle),
        "candidate_count": len(candidates),
        "items": items,
    }
    if not apply or not candidates:
        return summary
    bundle.mkdir(parents=True, exist_ok=False)
    moved: list[dict[str, Any]] = []
    try:
        for candidate, item in zip(candidates, items):
            destination = Path(str(item["quarantine_path"]))
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(candidate.path), str(destination))
            moved.append(item)
        summary["moved_count"] = len(moved)
        summary["manifest_path"] = str(bundle / MANIFEST_NAME)
        (bundle / MANIFEST_NAME).write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        summary["moved_count"] = len(moved)
        summary["failed"] = True
        (bundle / "manifest.partial.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        raise
    return summary


def collect_quarantine_candidates(instances_dir: Path, quarantine_root: Path) -> list[QuarantineCandidate]:
    instances = instances_dir.expanduser().resolve()
    quarantine = quarantine_root.expanduser().resolve()
    candidates: list[QuarantineCandidate] = []
    if not instances.exists():
        return []
    for child in sorted(instances.iterdir(), key=lambda path: path.name):
        if _is_inside(child, quarantine):
            continue
        if child.is_dir() and child.name in PSEUDO_INSTANCE_NAMES and not (child / "Bot_Verhalten.md").exists():
            candidates.append(QuarantineCandidate(child, "pseudo_instance"))
    for instance_dir in sorted((path for path in instances.iterdir() if path.is_dir()), key=lambda path: path.name):
        if _is_inside(instance_dir, quarantine):
            continue
        data_dir = instance_dir / "data"
        if not data_dir.is_dir():
            continue
        for snapshot in sorted(data_dir.glob("accounts.pre-*"), key=lambda path: path.name):
            if snapshot.is_dir() and not snapshot.is_symlink():
                candidates.append(QuarantineCandidate(snapshot, "pre_secret_repair_account_store_snapshot"))
        accounts_root = data_dir / "accounts"
        if not accounts_root.is_dir():
            continue
        for child in sorted(accounts_root.iterdir(), key=lambda path: path.name):
            if _is_inside(child, quarantine) or child.name in ACTIVE_ACCOUNT_STORE_NAMES or child.is_symlink():
                continue
            reason = _account_root_candidate_reason(child)
            if reason:
                candidates.append(QuarantineCandidate(child, reason))
        for nested in sorted(accounts_root.rglob("*"), key=lambda path: str(path)):
            if nested.parent == accounts_root or _is_inside(nested, quarantine) or nested.is_symlink():
                continue
            reason = _account_tree_candidate_reason(nested)
            if reason:
                candidates.append(QuarantineCandidate(nested, reason))
    return _drop_nested_candidates(candidates)


def apply_retention(
    *,
    instances_dir: Path,
    quarantine_root: Path,
    apply: bool,
    min_age_days: int,
    delete_raw_after_archive: bool,
    sql_confirmation_path: Path,
) -> dict[str, Any]:
    instances = instances_dir.expanduser().resolve()
    quarantine = _safe_quarantine_root(instances, quarantine_root)
    archive_root = quarantine / "archives"
    sql_confirmed = _sql_backup_confirmed(sql_confirmation_path)
    now = datetime.now(timezone.utc)
    bundles = [path for path in sorted(quarantine.glob("cleanup-*")) if path.is_dir()]
    items: list[dict[str, Any]] = []
    for bundle in bundles:
        age_days = _age_days(bundle, now)
        eligible = age_days >= min_age_days or sql_confirmed
        archive_path = archive_root / f"{bundle.name}.tar.gz"
        item = {
            "bundle": str(bundle),
            "age_days": age_days,
            "eligible": eligible,
            "archive_path": str(archive_path),
            "archive_exists": archive_path.exists(),
            "action": "archive_raw" if eligible and not archive_path.exists() else "none",
        }
        if eligible and archive_path.exists() and delete_raw_after_archive:
            item["action"] = "delete_raw"
        items.append(item)
    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "operation": "retention",
        "apply": bool(apply),
        "created_at": _utc_now(),
        "instances_dir": str(instances),
        "quarantine_root": str(quarantine),
        "min_age_days": min_age_days,
        "sql_confirmation_path": str(sql_confirmation_path),
        "sql_backup_confirmed": sql_confirmed,
        "delete_raw_after_archive": delete_raw_after_archive,
        "items": items,
    }
    if not apply:
        return summary
    archive_root.mkdir(parents=True, exist_ok=True)
    archived = 0
    removed = 0
    for item in items:
        bundle = Path(str(item["bundle"]))
        archive_path = Path(str(item["archive_path"]))
        if not item["eligible"]:
            continue
        if not archive_path.exists():
            _write_archive(bundle, archive_path)
            archived += 1
            item["archived"] = True
        if delete_raw_after_archive and archive_path.exists() and bundle.exists():
            shutil.rmtree(bundle)
            removed += 1
            item["raw_removed"] = True
    summary["archived_count"] = archived
    summary["raw_removed_count"] = removed
    retention_log = quarantine / "retention-log.jsonl"
    with retention_log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(summary, sort_keys=True) + "\n")
    summary["retention_log"] = str(retention_log)
    return summary


def confirm_sql_backup(
    *,
    instances_dir: Path,
    quarantine_root: Path,
    confirmation_path: Path,
    backup_label: str,
    apply: bool,
) -> dict[str, Any]:
    instances = instances_dir.expanduser().resolve()
    quarantine = _safe_quarantine_root(instances, quarantine_root)
    confirmation = confirmation_path.expanduser().resolve()
    _require_inside(confirmation, quarantine)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "confirmed": True,
        "confirmed_at": _utc_now(),
        "backup_label": str(backup_label or "").strip(),
        "instances_dir": str(instances),
    }
    summary = {
        "schema_version": SCHEMA_VERSION,
        "operation": "confirm_sql_backup",
        "apply": bool(apply),
        "confirmation_path": str(confirmation),
        "payload": payload,
    }
    if apply:
        confirmation.parent.mkdir(parents=True, exist_ok=True)
        confirmation.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def install_systemd_timer(
    *,
    repo_root: Path,
    instances_dir: Path,
    quarantine_root: Path,
    python_executable: str,
    service_name: str,
    timer_name: str,
    interval: str,
    randomized_delay: str,
    min_age_days: int,
    delete_raw_after_archive: bool,
    enable: bool,
    print_only: bool,
) -> dict[str, Any] | None:
    repo = repo_root.expanduser().resolve()
    script = repo / "scripts" / "maintain_instance_quarantine.py"
    python_path = _python_path(repo, python_executable)
    instances = _path_for_unit(instances_dir, repo)
    quarantine = _path_for_unit(quarantine_root, repo)
    service_name = _unit_name(service_name, suffix=".service")
    timer_name = _unit_name(timer_name, suffix=".timer")
    command = [
        str(python_path),
        str(script),
        "retention",
        "--instances-dir",
        str(instances),
        "--quarantine-root",
        str(quarantine),
        "--apply",
        "--min-age-days",
        str(max(0, int(min_age_days))),
    ]
    if delete_raw_after_archive:
        command.append("--delete-raw-after-archive")
    service_text = "\n".join(
        [
            "[Unit]",
            "Description=TeeBotus instance quarantine retention",
            "",
            "[Service]",
            "Type=oneshot",
            f"WorkingDirectory={_systemd_value(str(repo))}",
            f"ExecStart={_systemd_value(_shell_command(command))}",
            "NoNewPrivileges=true",
            "PrivateTmp=true",
            "",
        ]
    )
    timer_text = "\n".join(
        [
            "[Unit]",
            "Description=Run TeeBotus instance quarantine retention",
            "",
            "[Timer]",
            "OnBootSec=10min",
            f"OnCalendar={_systemd_value(interval)}",
            f"RandomizedDelaySec={_systemd_value(randomized_delay)}",
            "Persistent=true",
            f"Unit={_systemd_value(service_name)}",
            "",
            "[Install]",
            "WantedBy=timers.target",
            "",
        ]
    )
    if print_only:
        print(f"# {service_name}")
        print(service_text)
        print(f"# {timer_name}")
        print(timer_text)
        return None
    user_dir = Path.home() / ".config" / "systemd" / "user"
    user_dir.mkdir(parents=True, exist_ok=True)
    service_path = user_dir / service_name
    timer_path = user_dir / timer_name
    service_path.write_text(service_text, encoding="utf-8")
    timer_path.write_text(timer_text, encoding="utf-8")
    if enable:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", timer_name], check=True)
    return {
        "schema_version": SCHEMA_VERSION,
        "operation": "install_systemd",
        "service_path": str(service_path),
        "timer_path": str(timer_path),
        "enabled": bool(enable),
        "service_name": service_name,
        "timer_name": timer_name,
    }


def _account_root_candidate_reason(path: Path) -> str:
    name = path.name
    if path.is_dir() and name.startswith(".pre-"):
        return "pre_import_or_backup_sync_snapshot"
    if path.is_dir() and name in ACCOUNT_QUARANTINE_DIR_NAMES:
        return "account_quarantine_legacy"
    if path.is_file() and ".unreadable-" in name:
        return "unreadable_metadata_snapshot"
    if path.is_dir() and ".unreadable-" in name:
        return "unreadable_directory_snapshot"
    return ""


def _account_tree_candidate_reason(path: Path) -> str:
    name = path.name
    if name.startswith(".pre-"):
        return "nested_pre_import_or_backup_sync_snapshot"
    if ".unreadable-" in name:
        return "nested_unreadable_snapshot"
    if path.is_dir() and (name in ACCOUNT_QUARANTINE_DIR_NAMES or "Quarantine" in name):
        return "nested_account_quarantine_legacy"
    return ""


def _candidate_manifest_item(candidate: QuarantineCandidate, instances_dir: Path, bundle: Path) -> dict[str, Any]:
    rel = candidate.path.relative_to(instances_dir)
    destination = bundle / rel
    return {
        "original_path": str(candidate.path),
        "original_relative_path": str(rel),
        "quarantine_path": str(destination),
        "reason": candidate.reason,
        "kind": "directory" if candidate.path.is_dir() else "file",
        "size_bytes": _path_size(candidate.path),
        "file_count": _file_count(candidate.path),
        "mtime": _mtime(candidate.path),
        "sha256": _sha256(candidate.path) if candidate.path.is_file() else "",
    }


def _drop_nested_candidates(candidates: list[QuarantineCandidate]) -> list[QuarantineCandidate]:
    sorted_candidates = sorted(candidates, key=lambda item: (len(item.path.parts), str(item.path)))
    kept: list[QuarantineCandidate] = []
    for candidate in sorted_candidates:
        if any(_is_inside(candidate.path, existing.path) for existing in kept):
            continue
        kept.append(candidate)
    return sorted(kept, key=lambda item: str(item.path))


def _path_size(path: Path) -> int:
    if path.is_file() or path.is_symlink():
        try:
            return path.lstat().st_size
        except OSError:
            return 0
    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_file() or child.is_symlink():
                total += child.lstat().st_size
        except OSError:
            continue
    return total


def _file_count(path: Path) -> int:
    if path.is_file() or path.is_symlink():
        return 1
    count = 0
    for child in path.rglob("*"):
        if child.is_file() or child.is_symlink():
            count += 1
    return count


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
    except OSError:
        return ""


def _timestamp(value: str = "") -> str:
    clean = str(value or "").strip()
    if clean:
        return clean
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _age_days(path: Path, now: datetime) -> int:
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except OSError:
        return 0
    seconds = max(0.0, (now - mtime).total_seconds())
    return int(seconds // 86400)


def _write_archive(source_dir: Path, archive_path: Path) -> None:
    tmp = archive_path.with_suffix(archive_path.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()
    with tarfile.open(tmp, mode="w:gz") as archive:
        archive.add(source_dir, arcname=source_dir.name, recursive=True)
    tmp.replace(archive_path)


def _sql_backup_confirmed(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("confirmed") is True


def _quarantine_root(instances_dir: str | Path, quarantine_root: str | Path) -> Path:
    raw = str(quarantine_root or "").strip()
    if raw:
        return Path(raw)
    return Path(instances_dir) / DEFAULT_QUARANTINE_DIRNAME


def _sql_confirmation_path(instances_dir: str | Path, quarantine_root: str | Path, override: str | Path) -> Path:
    raw = str(override or "").strip()
    if raw:
        return Path(raw)
    return _quarantine_root(instances_dir, quarantine_root) / DEFAULT_SQL_CONFIRMATION_NAME


def _safe_quarantine_root(instances_dir: Path, quarantine_root: Path) -> Path:
    instances = instances_dir.expanduser().resolve()
    quarantine = quarantine_root.expanduser().resolve()
    if quarantine == instances:
        raise ValueError("quarantine root must not be the instances directory")
    _require_inside(quarantine, instances)
    return quarantine


def _require_inside(path: Path, parent: Path) -> None:
    try:
        path.relative_to(parent)
    except ValueError as exc:
        raise ValueError(f"{path} must stay under {parent}") from exc


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except (OSError, ValueError):
        return False
    return True


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.name}-{index:03d}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not allocate unique path for {path}")


def _python_path(repo_root: Path, configured: str) -> Path:
    raw = str(configured or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    for candidate in (repo_root / ".venv-py313" / "bin" / "python", repo_root / ".venv" / "bin" / "python"):
        if candidate.exists():
            return candidate
    return Path(sys.executable).resolve()


def _path_for_unit(path: Path, repo_root: Path) -> Path:
    raw = Path(path)
    if raw.is_absolute():
        return raw.expanduser().resolve()
    return (repo_root / raw).resolve()


def _unit_name(value: str, *, suffix: str) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError("systemd unit name must not be empty")
    if "/" in name or "\\" in name or ".." in name:
        raise ValueError("systemd unit name contains unsupported path characters")
    if not name.endswith(suffix):
        name += suffix
    return name


def _systemd_value(value: str) -> str:
    text = str(value or "")
    if "\n" in text or "\r" in text:
        raise ValueError("systemd value must stay single-line")
    return text


def _shell_command(parts: list[str]) -> str:
    return " ".join(_shell_quote(part) for part in parts)


def _shell_quote(value: str) -> str:
    text = str(value)
    if not text:
        return "''"
    safe = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_+-=.,:/@%"
    if all(char in safe for char in text):
        return text
    return "'" + text.replace("'", "'\\''") + "'"


if __name__ == "__main__":
    raise SystemExit(main())
