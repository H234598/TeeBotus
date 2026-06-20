#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from TeeBotus.runtime.accounts import USER_MEMORY_ENTRIES_FILENAME  # noqa: E402
from scripts.import_legacy_user_memory import import_legacy_user_memory  # noqa: E402
from scripts.migrate_account_memory_to_database import (  # noqa: E402
    _apply_backend_overrides,
    _migrate as migrate_account_memory_to_database,
    _resolve_backend,
    _restore_env,
)

SCHEMA_VERSION = 1
DEFAULT_SERVICE_NAME = "teebotus-memory-artifact-import.service"
DEFAULT_TIMER_NAME = "teebotus-memory-artifact-import.timer"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv and argv[0] in {"run", "install-systemd"} else "run"
    command_argv = argv[1:] if argv and argv[0] in {"run", "install-systemd"} else argv
    if command == "install-systemd":
        return _install_systemd_main(command_argv)
    return _run_main(command_argv)


def _run_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Import TeeBotus memory JSON/artifacts and verified legacy user-memory sources.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT), help="TeeBotus repository root.")
    parser.add_argument("--instances-dir", default="instances", help="Current TeeBotus instances directory.")
    parser.add_argument("--instance", action="append", default=[], help="Instance to import. Can be repeated.")
    parser.add_argument("--backend", choices=("", "env", "sqlite", "postgres"), default="env", help="Database backend override.")
    parser.add_argument("--sqlite-path", default="", help="Override SQLite account-memory path during migration.")
    parser.add_argument("--postgres-dsn", default="", help="Override PostgreSQL DSN during migration.")
    parser.add_argument("--legacy-search-root", action="append", default=[], help="Root to scan for legacy */data/users sources. Defaults to repo root.")
    parser.add_argument("--dry-run", action="store_true", help="Report importable sources without writing or deleting.")
    parser.add_argument("--keep-imported-sources", action="store_true", help="Do not delete verified imported JSON/user-memory artifacts.")
    parser.add_argument("--skip-active-json", action="store_true", help="Skip active account JSON-to-database migration.")
    parser.add_argument("--skip-legacy", action="store_true", help="Skip legacy */data/users import.")
    parser.add_argument("--replace-unreadable", action="store_true", help="Allow legacy import to replace unreadable target memory rows.")
    parser.add_argument(
        "--replace-unreadable-account-metadata",
        action="store_true",
        help="Allow legacy import to move unreadable account metadata aside before import.",
    )
    parser.add_argument("--json-output", default="", help="Write machine-readable report.")
    parser.add_argument("--markdown-output", default="", help="Write Markdown report.")
    args = parser.parse_args(argv)

    repo = Path(args.repo_root).expanduser().resolve()
    _load_dotenv(repo / ".env")
    instances_dir = _path_relative_to_repo(args.instances_dir, repo)
    selected = _normalize_instance_selection(args.instance)
    backend = _resolve_backend("" if args.backend == "env" else args.backend)
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "mode": "dry-run" if args.dry_run else "apply",
        "repo_root": str(repo),
        "instances_dir": str(instances_dir),
        "instances": list(selected),
        "delete_imported_sources": not bool(args.keep_imported_sources),
        "backend": backend or "",
        "active_json": {},
        "legacy_import": {"roots": [], "totals": _empty_legacy_totals()},
        "ok": True,
        "errors": [],
    }

    if backend not in {"sqlite", "postgres"}:
        report["ok"] = False
        report["errors"].append("No account-memory database backend configured. Set TEEBOTUS_ACCOUNT_MEMORY_BACKEND or pass --backend.")
        _write_reports(report, json_output=args.json_output, markdown_output=args.markdown_output)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 2

    previous_env = _apply_backend_overrides(backend=backend, sqlite_path=args.sqlite_path, postgres_dsn=args.postgres_dsn)
    try:
        if args.skip_active_json:
            report["active_json"] = {"status": "skipped"}
        else:
            active_result = migrate_account_memory_to_database(
                instances_dir=instances_dir,
                selected=selected,
                dry_run=bool(args.dry_run),
                delete_json_files=not bool(args.keep_imported_sources),
            )
            report["active_json"] = {"status": "ok", **active_result}
        if args.skip_legacy:
            report["legacy_import"] = {"status": "skipped", "roots": [], "totals": _empty_legacy_totals()}
        else:
            legacy_roots = discover_legacy_instance_roots(
                search_roots=[Path(path) for path in args.legacy_search_root] or [repo],
                repo_root=repo,
            )
            report["legacy_import"] = _import_legacy_roots(
                legacy_roots=legacy_roots,
                target_instances_dir=instances_dir,
                selected=selected,
                apply=not bool(args.dry_run),
                delete_imported_sources=not bool(args.keep_imported_sources),
                replace_unreadable=bool(args.replace_unreadable),
                replace_unreadable_account_metadata=bool(args.replace_unreadable_account_metadata),
            )
    except BaseException as exc:  # noqa: BLE001 - this job must write a report before failing.
        report["ok"] = False
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        _write_reports(report, json_output=args.json_output, markdown_output=args.markdown_output)
        print(json.dumps(report, indent=2, sort_keys=True))
        raise
    finally:
        _restore_env(previous_env)
    _write_reports(report, json_output=args.json_output, markdown_output=args.markdown_output)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("ok") else 1


def discover_legacy_instance_roots(*, search_roots: Iterable[Path], repo_root: Path) -> list[Path]:
    repo = repo_root.expanduser().resolve(strict=False)
    roots: list[Path] = []
    seen: set[Path] = set()
    for raw_root in search_roots:
        search_root = _path_relative_to_repo(raw_root, repo)
        if not search_root.exists() or not search_root.is_dir():
            continue
        for users_dir in _iter_legacy_users_dirs(search_root):
            try:
                resolved_users = users_dir.resolve(strict=False)
            except OSError:
                continue
            if repo not in (resolved_users, *resolved_users.parents):
                continue
            if not _users_dir_has_importable_source(users_dir):
                continue
            legacy_root = users_dir.parents[2].resolve(strict=False)
            if legacy_root in seen:
                continue
            roots.append(legacy_root)
            seen.add(legacy_root)
    return roots


def _iter_legacy_users_dirs(search_root: Path) -> Iterable[Path]:
    skip_names = {".git", ".hg", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv", ".venv-py313", "__pycache__", "node_modules"}
    for current, dirnames, _filenames in os.walk(search_root):
        dirnames[:] = [name for name in dirnames if name not in skip_names]
        current_path = Path(current)
        if current_path.name == "data" and "users" in dirnames:
            yield current_path / "users"


def _users_dir_has_importable_source(users_dir: Path) -> bool:
    try:
        user_dirs = [path for path in users_dir.iterdir() if path.is_dir()]
    except OSError:
        return False
    return any((user_dir / USER_MEMORY_ENTRIES_FILENAME).exists() for user_dir in user_dirs)


def _import_legacy_roots(
    *,
    legacy_roots: list[Path],
    target_instances_dir: Path,
    selected: tuple[str, ...],
    apply: bool,
    delete_imported_sources: bool,
    replace_unreadable: bool,
    replace_unreadable_account_metadata: bool,
) -> dict[str, Any]:
    root_reports: list[dict[str, Any]] = []
    totals = _empty_legacy_totals()
    for legacy_root in legacy_roots:
        stats = import_legacy_user_memory(
            legacy_instances_dir=legacy_root,
            target_instances_dir=target_instances_dir,
            instances=selected,
            apply=apply,
            replace_unreadable=replace_unreadable,
            replace_unreadable_account_metadata=replace_unreadable_account_metadata,
            backup_current=True,
            delete_imported_sources=delete_imported_sources,
        )
        root_report = {
            "legacy_instances_dir": str(legacy_root),
            "requested_legacy_instances_dir": stats.requested_legacy_instances_dir,
            "effective_legacy_instances_dir": stats.effective_legacy_instances_dir,
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
                "memory_keyring_repairs": stats.memory_keyring_repairs,
                "account_store_resets": stats.account_store_resets,
                "imported_source_artifacts_deleted": stats.imported_source_artifacts_deleted,
                "imported_source_artifacts_kept_external": stats.imported_source_artifacts_kept_external,
                "imported_source_artifact_delete_failures": stats.imported_source_artifact_delete_failures,
            },
            "events": list(stats.events),
        }
        root_reports.append(root_report)
        for key, value in root_report["totals"].items():
            totals[key] = int(totals.get(key, 0)) + int(value or 0)
    return {"status": "ok", "roots": root_reports, "totals": totals}


def _empty_legacy_totals() -> dict[str, int]:
    return {
        "sources": 0,
        "imported_sources": 0,
        "skipped_sources": 0,
        "malformed_sources": 0,
        "encrypted_sources": 0,
        "entries_seen": 0,
        "entries_imported": 0,
        "accounts_created": 0,
        "accounts_existing": 0,
        "unreadable_targets": 0,
        "unreadable_metadata": 0,
        "backups_created": 0,
        "metadata_backups_created": 0,
        "memory_keyring_repairs": 0,
        "account_store_resets": 0,
        "imported_source_artifacts_deleted": 0,
        "imported_source_artifacts_kept_external": 0,
        "imported_source_artifact_delete_failures": 0,
    }


def _install_systemd_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Install TeeBotus daily memory/artifact import user-systemd timer.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--instances-dir", default="instances")
    parser.add_argument("--backend", choices=("env", "sqlite", "postgres"), default="env")
    parser.add_argument("--python", default="")
    parser.add_argument("--service-name", default=DEFAULT_SERVICE_NAME)
    parser.add_argument("--timer-name", default=DEFAULT_TIMER_NAME)
    parser.add_argument("--interval", default="daily", help="systemd OnCalendar value.")
    parser.add_argument("--randomized-delay", default="30min")
    parser.add_argument("--print", dest="print_only", action="store_true")
    parser.add_argument("--enable", action="store_true")
    args = parser.parse_args(argv)
    repo = Path(args.repo_root).expanduser().resolve()
    script = repo / "scripts" / "import_memory_artifacts_daily.py"
    python_path = Path(args.python).expanduser() if args.python else _default_python(repo)
    service_name = _unit_name(args.service_name, ".service")
    timer_name = _unit_name(args.timer_name, ".timer")
    command = [
        str(python_path),
        str(script),
        "run",
        "--repo-root",
        str(repo),
        "--instances-dir",
        str(_path_relative_to_repo(args.instances_dir, repo)),
    ]
    if args.backend != "env":
        command.extend(["--backend", args.backend])
    service_text = "\n".join(
        [
            "[Unit]",
            "Description=TeeBotus daily memory and artifact import",
            "Documentation=https://github.com/H234598/TeeBotus",
            "",
            "[Service]",
            "Type=oneshot",
            f"WorkingDirectory={_systemd_value(str(repo))}",
            f"EnvironmentFile=-{_systemd_value(str(repo / '.env'))}",
            f"ExecStart={_systemd_value(_shell_command(command))}",
            "NoNewPrivileges=true",
            "PrivateTmp=true",
            "",
        ]
    )
    timer_text = "\n".join(
        [
            "[Unit]",
            "Description=Run TeeBotus daily memory and artifact import",
            "",
            "[Timer]",
            "OnBootSec=10min",
            f"OnCalendar={_systemd_value(str(args.interval))}",
            f"RandomizedDelaySec={_systemd_value(str(args.randomized_delay))}",
            "Persistent=true",
            f"Unit={_systemd_value(service_name)}",
            "",
            "[Install]",
            "WantedBy=timers.target",
            "",
        ]
    )
    if args.print_only:
        print(f"# {service_name}")
        print(service_text)
        print(f"# {timer_name}")
        print(timer_text)
        return 0
    user_dir = Path.home() / ".config" / "systemd" / "user"
    user_dir.mkdir(parents=True, exist_ok=True)
    service_path = user_dir / service_name
    timer_path = user_dir / timer_name
    service_path.write_text(service_text, encoding="utf-8")
    timer_path.write_text(timer_text, encoding="utf-8")
    print(f"wrote {service_path}")
    print(f"wrote {timer_path}")
    if args.enable:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", timer_name], check=True)
        print(f"enabled {timer_name}")
    return 0


def _write_reports(report: dict[str, Any], *, json_output: str, markdown_output: str) -> None:
    if json_output:
        json_path = Path(json_output).expanduser()
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if markdown_output:
        markdown_path = Path(markdown_output).expanduser()
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(_render_markdown_report(report), encoding="utf-8")


def _render_markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# TeeBotus Memory Artifact Import",
        "",
        f"- generated_at: `{report.get('generated_at', '')}`",
        f"- mode: `{report.get('mode', '')}`",
        f"- backend: `{report.get('backend', '')}`",
        f"- repo_root: `{report.get('repo_root', '')}`",
        f"- instances_dir: `{report.get('instances_dir', '')}`",
        f"- delete_imported_sources: `{report.get('delete_imported_sources', False)}`",
        f"- ok: `{report.get('ok', False)}`",
        "",
        "## Active Account JSON",
        "",
    ]
    active = report.get("active_json") if isinstance(report.get("active_json"), dict) else {}
    for key in sorted(active):
        lines.append(f"- {key}: `{active[key]}`")
    legacy = report.get("legacy_import") if isinstance(report.get("legacy_import"), dict) else {}
    lines.extend(["", "## Legacy Import", ""])
    totals = legacy.get("totals") if isinstance(legacy.get("totals"), dict) else {}
    for key in sorted(totals):
        lines.append(f"- {key}: `{totals[key]}`")
    roots = legacy.get("roots") if isinstance(legacy.get("roots"), list) else []
    for root in roots:
        if not isinstance(root, dict):
            continue
        lines.extend(["", f"### `{root.get('legacy_instances_dir', '')}`", ""])
        root_totals = root.get("totals") if isinstance(root.get("totals"), dict) else {}
        for key in sorted(root_totals):
            lines.append(f"- {key}: `{root_totals[key]}`")
    errors = report.get("errors") if isinstance(report.get("errors"), list) else []
    if errors:
        lines.extend(["", "## Errors", ""])
        for error in errors:
            lines.append(f"- `{error}`")
    return "\n".join(lines) + "\n"


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = _dotenv_value(value.strip())


def _dotenv_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _normalize_instance_selection(values: Iterable[str]) -> tuple[str, ...]:
    selected: list[str] = []
    seen: set[str] = set()
    for value in values:
        instance = str(value or "").strip()
        if not instance or instance in seen:
            continue
        selected.append(instance)
        seen.add(instance)
    return tuple(selected)


def _path_relative_to_repo(value: str | Path, repo: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (repo / path).resolve(strict=False)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _default_python(repo: Path) -> Path:
    for candidate in (repo / ".venv-py313" / "bin" / "python", repo / ".venv" / "bin" / "python"):
        if candidate.exists():
            return candidate
    return Path(sys.executable)


def _unit_name(value: str, suffix: str) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError("systemd unit name must not be empty")
    return name if name.endswith(suffix) else f"{name}{suffix}"


def _systemd_value(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", " ")


def _shell_command(parts: list[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in parts)


if __name__ == "__main__":
    raise SystemExit(main())
