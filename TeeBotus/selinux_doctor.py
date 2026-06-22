from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


DEFAULT_UNIT = "teebotus-codex-history-collector.service"
SELINUX_MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
PANIC_SYSTEMD_MODULE_RE = re.compile(r"^(?:my|local)[-_].*systemd(?:[-_].*)?$|^mysystemd$", re.IGNORECASE)
BENIGN_SYSTEMD_MODULES = frozenset({"systemd", "systemd_tmpfiles", "systemd_logind", "systemd_userdbd"})


CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class SELinuxCommandResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class SELinuxModule:
    name: str
    version: str = ""
    suspect: bool = False
    reason: str = ""


@dataclass(frozen=True)
class SELinuxDoctorReport:
    ok: bool
    enforcing: str
    modules_readable: bool
    suspect_modules: tuple[SELinuxModule, ...]
    manual_review_modules: tuple[SELinuxModule, ...]
    removed_modules: tuple[str, ...]
    failed_removals: tuple[str, ...]
    unit_present: bool
    unit_active: str
    unit_scope: str
    notes: tuple[str, ...]
    commands: tuple[SELinuxCommandResult, ...]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose and narrowly undo TeeBotus SELinux audit2allow panic modules.")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--unit", default=DEFAULT_UNIT, help="systemd unit to inspect.")
    parser.add_argument("--unit-scope", choices=("auto", "user", "system"), default="auto", help="systemd manager scope to inspect.")
    parser.add_argument("--module", action="append", default=[], help="Exact SELinux module name to remove with --apply; repeatable.")
    parser.add_argument("--remove-suspect", action="store_true", help="With --apply, remove modules matching the narrow panic-systemd pattern.")
    parser.add_argument("--apply", action="store_true", help="Actually run semodule -r for selected modules. Default is dry-run.")
    parser.add_argument("--output", help="Optional file path for writing the rendered report.")
    args = parser.parse_args(argv)

    try:
        report = collect_selinux_report(
            unit=args.unit,
            unit_scope=args.unit_scope,
            explicit_modules=tuple(args.module or ()),
            remove_suspect=bool(args.remove_suspect),
            apply=bool(args.apply),
        )
    except ValueError as exc:
        parser.error(str(exc))
    if args.format == "json":
        output = json.dumps(asdict(report), ensure_ascii=False, indent=2)
    else:
        output = render_selinux_report(report)
    print(output)
    if args.output:
        _write_output(Path(args.output), output)
    return 0 if report.ok else 1


def collect_selinux_report(
    *,
    unit: str = DEFAULT_UNIT,
    unit_scope: str = "auto",
    explicit_modules: Sequence[str] = (),
    remove_suspect: bool = False,
    apply: bool = False,
    runner: CommandRunner | None = None,
) -> SELinuxDoctorReport:
    run = runner or _run_command
    commands: list[SELinuxCommandResult] = []
    notes: list[str] = []

    getenforce = _capture(run, ("getenforce",))
    commands.append(getenforce)
    enforcing = getenforce.stdout.strip() if getenforce.returncode == 0 else "unknown"

    semodule = _capture(run, ("semodule", "-l"))
    commands.append(semodule)
    modules_readable = semodule.returncode == 0
    modules = _parse_semodule_list(semodule.stdout) if modules_readable else ()
    if not modules_readable:
        notes.append("SELinux module store is not readable by this user; rerun via sudo for live module cleanup.")

    suspect_modules = tuple(module for module in modules if module.suspect)
    manual_review_modules = tuple(
        module
        for module in modules
        if "systemd" in module.name.casefold() and not module.suspect and module.name.casefold() not in BENIGN_SYSTEMD_MODULES
    )
    if manual_review_modules:
        notes.append("Additional systemd-looking local modules exist; review them manually before removal.")

    unit_state, unit_commands = _resolve_unit_state(run, unit, scope=unit_scope)
    commands.extend(unit_commands)
    unit_present = unit_state["present"]
    unit_active = unit_state["active"]
    resolved_unit_scope = unit_state["scope"]
    if not unit_present:
        notes.append(f"{unit} is not loaded in the checked systemd manager(s); no active service there needs SELinux allow rules right now.")

    selected_for_removal = _selected_modules(explicit_modules, suspect_modules, remove_suspect=remove_suspect)
    removed: list[str] = []
    failed: list[str] = []
    if selected_for_removal and not apply:
        notes.append("Dry-run only; pass --apply to remove selected modules with semodule -r.")
    for module_name in selected_for_removal if apply else ():
        remove = _capture(run, ("semodule", "-r", module_name))
        commands.append(remove)
        if remove.returncode == 0:
            removed.append(module_name)
        else:
            failed.append(module_name)

    ok = modules_readable and not failed
    return SELinuxDoctorReport(
        ok=ok,
        enforcing=enforcing,
        modules_readable=modules_readable,
        suspect_modules=suspect_modules,
        manual_review_modules=manual_review_modules,
        removed_modules=tuple(removed),
        failed_removals=tuple(failed),
        unit_present=unit_present,
        unit_active=unit_active,
        unit_scope=resolved_unit_scope,
        notes=tuple(notes),
        commands=tuple(commands),
    )


def render_selinux_report(report: SELinuxDoctorReport) -> str:
    lines = [
        "TeeBotus SELinux Doctor",
        f"- SELinux: {report.enforcing}",
        f"- Module lesbar: {'ja' if report.modules_readable else 'nein'}",
        f"- Collector-Unit geladen: {'ja' if report.unit_present else 'nein'}"
        + (f" ({report.unit_scope})" if report.unit_scope else ""),
    ]
    if report.unit_active:
        lines.append(f"- Collector-Unit Status: {report.unit_active}")
    if report.suspect_modules:
        lines.append("- Verdaechtige Panic-Module:")
        lines.extend(f"  - {module.name} ({module.reason})" for module in report.suspect_modules)
    else:
        lines.append("- Verdaechtige Panic-Module: keine")
    if report.manual_review_modules:
        lines.append("- Manuell pruefen:")
        lines.extend(f"  - {module.name}" for module in report.manual_review_modules)
    if report.removed_modules:
        lines.append("- Entfernt:")
        lines.extend(f"  - {module}" for module in report.removed_modules)
    if report.failed_removals:
        lines.append("- Entfernen fehlgeschlagen:")
        lines.extend(f"  - {module}" for module in report.failed_removals)
    if report.notes:
        lines.append("- Hinweise:")
        lines.extend(f"  - {note}" for note in report.notes)
    return "\n".join(lines)


def _run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(command), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def _capture(run: CommandRunner, command: Sequence[str]) -> SELinuxCommandResult:
    try:
        completed = run(tuple(command))
    except OSError as exc:
        return SELinuxCommandResult(tuple(command), 127, "", f"{type(exc).__name__}: {exc}")
    return SELinuxCommandResult(
        tuple(command),
        int(completed.returncode),
        str(completed.stdout or ""),
        str(completed.stderr or ""),
    )


def _parse_semodule_list(output: str) -> tuple[SELinuxModule, ...]:
    modules: list[SELinuxModule] = []
    for raw_line in str(output or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        name = parts[0].strip()
        if not name:
            continue
        version = parts[1].strip() if len(parts) > 1 else ""
        suspect = _module_is_panic_systemd(name)
        modules.append(
            SELinuxModule(
                name=name,
                version=version,
                suspect=suspect,
                reason="matches audit2allow -c systemd panic-module pattern" if suspect else "",
            )
        )
    return tuple(modules)


def _module_is_panic_systemd(name: str) -> bool:
    normalized = str(name or "").strip()
    if not normalized:
        return False
    lowered = normalized.casefold()
    if lowered in BENIGN_SYSTEMD_MODULES:
        return False
    return bool(PANIC_SYSTEMD_MODULE_RE.fullmatch(normalized))


def _parse_systemctl_show(output: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for raw_line in str(output or "").splitlines():
        if "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        fields[key.strip()] = value.strip()
    return fields


def _resolve_unit_state(run: CommandRunner, unit: str, *, scope: str) -> tuple[dict[str, Any], tuple[SELinuxCommandResult, ...]]:
    normalized_scope = str(scope or "auto").strip().casefold()
    if normalized_scope not in {"auto", "user", "system"}:
        raise ValueError("unit scope must be auto, user, or system")
    commands: list[SELinuxCommandResult] = []
    attempts: list[tuple[str, tuple[str, ...]]] = []
    if normalized_scope in {"auto", "user"}:
        attempts.append(("user", ("systemctl", "--user", "show", unit, "--property=LoadState,ActiveState,SubState", "--no-pager")))
    if normalized_scope in {"auto", "system"}:
        attempts.append(("system", ("systemctl", "show", unit, "--property=LoadState,ActiveState,SubState", "--no-pager")))
    last_state = {"present": False, "active": "", "scope": normalized_scope if normalized_scope != "auto" else ""}
    for attempt_scope, command in attempts:
        result = _capture(run, command)
        commands.append(result)
        fields = _parse_systemctl_show(result.stdout) if result.returncode == 0 else {}
        active = "/".join(part for part in (fields.get("ActiveState", ""), fields.get("SubState", "")) if part)
        present = fields.get("LoadState") == "loaded"
        state = {"present": present, "active": active, "scope": attempt_scope}
        if present:
            return state, tuple(commands)
        last_state = state
    return last_state, tuple(commands)


def _selected_modules(
    explicit_modules: Sequence[str],
    suspect_modules: Sequence[SELinuxModule],
    *,
    remove_suspect: bool,
) -> tuple[str, ...]:
    selected: list[str] = []
    seen: set[str] = set()
    for module_name in explicit_modules:
        normalized = _validate_selinux_module_name(module_name)
        if normalized in seen:
            continue
        selected.append(normalized)
        seen.add(normalized)
    if remove_suspect:
        for module in suspect_modules:
            if module.name in seen:
                continue
            selected.append(module.name)
            seen.add(module.name)
    return tuple(selected)


def _validate_selinux_module_name(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("SELinux module name must not be empty")
    if not SELINUX_MODULE_NAME_RE.fullmatch(normalized):
        raise ValueError(f"invalid SELinux module name: {normalized!r}")
    return normalized


def _write_output(path: Path, output: str) -> None:
    target = path.expanduser()
    if not target.parent.exists():
        raise FileNotFoundError(f"output parent does not exist: {target.parent}")
    if target.exists() and target.is_dir():
        raise IsADirectoryError(f"output path is a directory: {target}")
    target.write_text(output + "\n", encoding="utf-8")


__all__ = [
    "SELinuxDoctorReport",
    "SELinuxModule",
    "collect_selinux_report",
    "main",
    "render_selinux_report",
]


if __name__ == "__main__":
    raise SystemExit(main())
