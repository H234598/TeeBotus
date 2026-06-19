#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VENV = ".venv-py313"
FEDORA_INSTALL_HINT = "sudo dnf install -y python3.13 python3.13-devel"
Runner = Callable[..., subprocess.CompletedProcess[str]]


def main(argv: list[str] | None = None, *, runner: Runner = subprocess.run) -> int:
    parser = argparse.ArgumentParser(description="Create a TeeBotus Python 3.13 runtime venv.")
    parser.add_argument("--python", default="python3.13", help="Python 3.13 executable to use.")
    parser.add_argument("--venv", default=DEFAULT_VENV, help="Target venv path, relative to repo root unless absolute.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without creating the venv.")
    parser.add_argument("--skip-requirements", action="store_true", help="Do not install requirements.txt into the venv.")
    parser.add_argument("--skip-editable", action="store_true", help="Do not install TeeBotus itself into the venv.")
    parser.add_argument("--skip-adapter-deps", action="store_true", help="Do not install pinned Python adapter dependencies.")
    parser.add_argument("--install-systemd", action="store_true", help="Render and write teebotus.service for the new venv.")
    parser.add_argument("--enable-systemd", action="store_true", help="Also enable --now teebotus.service after writing it.")
    parser.add_argument("--service-name", default="teebotus.service", help="User systemd service filename.")
    parser.add_argument("--channels", default="telegram,signal,matrix", help="Comma-separated channels for the systemd unit.")
    args = parser.parse_args(argv)

    python = _resolve_python(args.python)
    if python is None:
        print(
            f"{args.python} not found. Install it side-by-side with: {FEDORA_INSTALL_HINT}",
            file=sys.stderr,
        )
        return 2
    try:
        version = _python_version(python, runner=runner)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if version[:2] != (3, 13):
        found = ".".join(str(part) for part in version)
        print(f"{python} must be Python 3.13, found {found}.", file=sys.stderr)
        return 2

    venv = _resolve_venv(args.venv)
    commands = _setup_commands(
        python=python,
        venv=venv,
        install_requirements=not args.skip_requirements,
        install_editable=not args.skip_editable,
        install_adapter_deps=not args.skip_adapter_deps,
        dry_run=args.dry_run,
    )
    if args.enable_systemd and not args.install_systemd:
        print("--enable-systemd requires --install-systemd.", file=sys.stderr)
        return 2
    for command in commands:
        print(shlex.join(command), flush=True)
        if not args.dry_run:
            runner(command, check=True, cwd=REPO_ROOT, text=True)
    if args.install_systemd:
        systemd_command = _systemd_command(
            venv=venv,
            service_name=args.service_name,
            channels=args.channels,
            enable=args.enable_systemd,
        )
        print(shlex.join(systemd_command), flush=True)
        if not args.dry_run:
            runner(systemd_command, check=True, cwd=REPO_ROOT, text=True)
    print(f"python313_runtime=ready venv={venv} python={venv / 'bin' / 'python'}", flush=True)
    return 0


def _resolve_python(value: str) -> str | None:
    raw = str(value or "").strip() or "python3.13"
    path = Path(raw).expanduser()
    if path.name == raw:
        return shutil.which(raw)
    return str(path if path.is_absolute() else (REPO_ROOT / path).resolve()) if path.exists() else None


def _resolve_venv(value: str) -> Path:
    path = Path(str(value or DEFAULT_VENV)).expanduser()
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def _python_version(python: str, *, runner: Runner = subprocess.run) -> tuple[int, int, int]:
    command = [
        python,
        "-c",
        "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')",
    ]
    result = runner(command, check=True, capture_output=True, text=True)
    raw = str(result.stdout).strip()
    parts = raw.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise RuntimeError(f"Could not parse Python version from {python!r}: {raw!r}")
    return int(parts[0]), int(parts[1]), int(parts[2])


def _setup_commands(
    *,
    python: str,
    venv: Path,
    install_requirements: bool,
    install_editable: bool,
    install_adapter_deps: bool,
    dry_run: bool,
) -> list[list[str]]:
    venv_python = str(venv / "bin" / "python")
    commands: list[list[str]] = [
        [python, "-m", "venv", str(venv)],
        [venv_python, "-m", "pip", "install", "--upgrade", "pip"],
        [venv_python, "-m", "pip", "install", "--upgrade", "packaging"],
    ]
    if install_requirements:
        commands.append([venv_python, "-m", "pip", "install", "-r", str(REPO_ROOT / "requirements.txt")])
    if install_editable:
        commands.append([venv_python, "-m", "pip", "install", "--no-deps", "-e", str(REPO_ROOT)])
    if install_adapter_deps:
        adapter_command = [
            venv_python,
            str(REPO_ROOT / "scripts" / "install_adapter_deps.py"),
            "--python",
            venv_python,
            "--python-only",
            "--no-user",
        ]
        adapter_command.append("--skip-post-check")
        if dry_run:
            adapter_command.append("--dry-run")
        commands.append(adapter_command)
    if install_adapter_deps:
        commands.append([venv_python, str(REPO_ROOT / "scripts" / "check_adapter_deps.py"), "--python-only"])
    return commands


def _systemd_command(*, venv: Path, service_name: str, channels: str, enable: bool) -> list[str]:
    command = [
        str(venv / "bin" / "python"),
        "-m",
        "TeeBotus.systemd",
        "--repo-root",
        str(REPO_ROOT),
        "--python",
        str(venv / "bin" / "python"),
        "--service-name",
        str(service_name or "teebotus.service"),
        "--channels",
        str(channels or "telegram,signal,matrix"),
    ]
    if enable:
        command.append("--enable")
    return command


if __name__ == "__main__":
    raise SystemExit(main())
