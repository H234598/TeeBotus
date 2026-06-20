from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


DEFAULT_CHANNELS = "telegram,signal,matrix"
SYSTEMD_EXEC_PREFIX_CHARS = frozenset("@-:+!|")


@dataclass(frozen=True)
class TeeBotusSystemdUnit:
    service_name: str
    service_text: str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install or print TeeBotus user systemd service.")
    parser.add_argument("--check-env-file", default="", help=argparse.SUPPRESS)
    parser.add_argument("--repo-root", default=str(Path.cwd()), help="TeeBotus repository root used as WorkingDirectory.")
    parser.add_argument(
        "--python",
        default="",
        help="Python executable. Defaults to .venv-py313/bin/python if present, then .venv/bin/python, else python3.",
    )
    parser.add_argument("--service-name", default="teebotus.service", help="User systemd service filename.")
    parser.add_argument("--env-file", default=".env", help="EnvironmentFile path, relative to repo root unless absolute.")
    parser.add_argument("--channels", default=DEFAULT_CHANNELS, help="Comma-separated channels for python -m TeeBotus.")
    parser.add_argument("--no-all", action="store_true", help="Omit --all from ExecStart.")
    parser.add_argument("--print", action="store_true", dest="print_only", help="Print unit file instead of writing it.")
    parser.add_argument("--enable", action="store_true", help="Run systemctl --user daemon-reload and enable --now the service after writing.")
    args = parser.parse_args(argv)
    if args.check_env_file:
        return _check_env_file_permissions(Path(args.check_env_file))

    try:
        unit = render_teebotus_systemd_unit(
            repo_root=Path(args.repo_root),
            python_executable=args.python,
            service_name=args.service_name,
            env_file=args.env_file,
            channels=args.channels,
            all_instances=not args.no_all,
        )
    except ValueError as exc:
        parser.error(str(exc))
    if args.print_only:
        print(f"# {unit.service_name}")
        print(unit.service_text, end="")
        return 0
    user_dir = Path.home() / ".config" / "systemd" / "user"
    user_dir.mkdir(parents=True, exist_ok=True)
    target = user_dir / unit.service_name
    target.write_text(unit.service_text, encoding="utf-8")
    print(f"wrote {target}")
    if args.enable:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", unit.service_name], check=True)
        print(f"enabled {unit.service_name}")
    return 0


def render_teebotus_systemd_unit(
    *,
    repo_root: Path,
    python_executable: str = "",
    service_name: str = "teebotus.service",
    env_file: str = ".env",
    channels: str = DEFAULT_CHANNELS,
    all_instances: bool = True,
) -> TeeBotusSystemdUnit:
    service_name = _service_name(service_name)
    repo = repo_root.expanduser().resolve()
    python_path = _python_path(repo, python_executable)
    env_path = _env_path(repo, env_file)
    repo_value = _systemd_unit_value(str(repo), label="repo root")
    env_value = _systemd_unit_value(str(env_path), label="env file")
    channel_arg = _channels(channels)
    command = [_shell_quote(str(python_path)), "-m", "TeeBotus"]
    if all_instances:
        command.append("--all")
    command.extend(["--channels", _shell_quote(channel_arg)])
    service_text = "\n".join(
        [
            "[Unit]",
            "Description=TeeBotus multi-channel bot",
            "Documentation=https://github.com/H234598/TeeBotus",
            "Wants=network-online.target",
            "After=network-online.target",
            "",
            "[Service]",
            "Type=simple",
            f"WorkingDirectory={repo_value}",
            f"EnvironmentFile=-{env_value}",
            "ExecStartPre="
            + _systemd_unit_value(
                " ".join(
                    [
                        _shell_quote(str(python_path)),
                        "-m",
                        "TeeBotus.systemd",
                        "--check-env-file",
                        _shell_quote(str(env_path)),
                    ]
                ),
                label="command line",
            ),
            "ExecStart=" + _systemd_unit_value(" ".join(command), label="command line"),
            "Restart=on-failure",
            "RestartSec=10",
            "NoNewPrivileges=true",
            "PrivateTmp=true",
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        ]
    )
    return TeeBotusSystemdUnit(service_name=service_name, service_text=service_text)


def _python_path(repo_root: Path, value: str) -> Path | str:
    raw = str(value or "").strip()
    if raw:
        path = Path(raw).expanduser()
        if path.name == raw:
            if raw[0] in SYSTEMD_EXEC_PREFIX_CHARS:
                raise ValueError("systemd python executable must not start with a special ExecStart prefix")
            return raw
        return _absolute_without_symlink_resolution(path if path.is_absolute() else repo_root / path)
    for venv_name in (".venv-py313", ".venv"):
        venv_python = repo_root / venv_name / "bin" / "python"
        if venv_python.exists():
            return _absolute_without_symlink_resolution(venv_python)
    return Path("python3")


def _absolute_without_symlink_resolution(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _env_path(repo_root: Path, value: str) -> Path:
    raw = str(value or "").strip() or ".env"
    path = Path(raw).expanduser()
    return path if path.is_absolute() else (repo_root / path).resolve()


def _check_env_file_permissions(path: Path) -> int:
    try:
        if not path.exists():
            return 0
        mode = path.stat().st_mode & 0o777
    except OSError as exc:
        print(f"EnvironmentFile permission check failed for {path}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if mode & 0o077:
        print(f"EnvironmentFile permission check failed for {path}: mode={mode:03o} expected=600-or-stricter", file=sys.stderr)
        return 1
    return 0


def _service_name(value: str) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError("systemd service name must not be empty")
    if not name.endswith(".service"):
        name = f"{name}.service"
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.@-")
    if any(char not in allowed for char in name):
        raise ValueError("systemd service name contains unsupported characters")
    if not name[0].isalnum():
        raise ValueError("systemd service name must start with an ASCII letter or digit")
    return name


def _systemd_unit_value(value: str, *, label: str) -> str:
    return _validate_systemd_unit_value(value, label=label).replace("%", "%%")


def _validate_systemd_unit_value(value: str, *, label: str) -> str:
    text = str(value)
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ValueError(f"systemd {label} contains invalid control characters")
    return text


def _channels(value: str) -> str:
    channels = ",".join(part.strip().casefold() for part in str(value or "").split(",") if part.strip())
    if not channels:
        raise ValueError("systemd TeeBotus channels must not be empty")
    allowed = {"telegram", "signal", "matrix"}
    unknown = sorted(set(channels.split(",")) - allowed)
    if unknown:
        raise ValueError(f"unsupported TeeBotus channels: {', '.join(unknown)}")
    return channels


def _shell_quote(value: str) -> str:
    _validate_systemd_unit_value(value, label="command argument")
    if not value:
        return "''"
    if all(char.isalnum() or char in "@%_+=:,./-" for char in value):
        return value
    return "'" + value.replace("'", "'\\''") + "'"


if __name__ == "__main__":
    raise SystemExit(main())
