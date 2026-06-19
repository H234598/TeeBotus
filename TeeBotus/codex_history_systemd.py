from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path

from TeeBotus.systemd import (
    _python_path,
    _service_name,
    _shell_quote,
    _systemd_unit_value,
    _validate_systemd_unit_value,
)


DEFAULT_SERVICE_NAME = "teebotus-codex-history.service"
DEFAULT_INSTANCES_DIR = "instances"
DEFAULT_RESTART_SEC = "5s"
DEFAULT_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_LIMIT = 1000
DEFAULT_MAX_ITERATIONS = 1


@dataclass(frozen=True)
class CodexHistorySystemdUnit:
    service_name: str
    service_text: str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install or print TeeBotus Codex history watcher user systemd service.")
    parser.add_argument("--repo-root", default=str(Path.cwd()), help="TeeBotus repository root used as WorkingDirectory.")
    parser.add_argument(
        "--python",
        default="",
        help="Python executable. Defaults to .venv-py313/bin/python if present, then .venv/bin/python, else python3.",
    )
    parser.add_argument("--service-name", default=DEFAULT_SERVICE_NAME, help="User systemd service filename.")
    parser.add_argument("--env-file", default=".env", help="EnvironmentFile path, relative to repo root unless absolute.")
    parser.add_argument("--instances-dir", default=DEFAULT_INSTANCES_DIR, help="Instances directory passed to codex-history watch.")
    parser.add_argument("--instances", default="", help="Comma-separated instance filter passed to codex-history watch.")
    parser.add_argument("--instance", default="", help="Single instance passed to codex-history watch.")
    parser.add_argument("--sessions-root", action="append", default=[], help="Codex session root passed to codex-history watch; repeatable.")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Max session JSONL files per scan.")
    parser.add_argument("--event-mode", choices=("auto", "watchdog", "snapshot", "poll"), default="auto", help="Codex history watch backend.")
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL_SECONDS, help="Fallback wait interval for watch mode.")
    parser.add_argument("--follow", dest="follow", action="store_true", default=True, help="Run the watcher persistently in the systemd service.")
    parser.add_argument("--no-follow", dest="follow", action="store_false", help="Use the legacy bounded scan plus systemd restart loop.")
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=DEFAULT_MAX_ITERATIONS,
        help="Bounded watch iterations per service start when --no-follow is used.",
    )
    parser.add_argument("--restart-sec", default=DEFAULT_RESTART_SEC, help="systemd RestartSec interval.")
    parser.add_argument("--print", action="store_true", dest="print_only", help="Print unit file instead of writing it.")
    parser.add_argument("--enable", action="store_true", help="Run systemctl --user daemon-reload and enable --now the service after writing.")
    args = parser.parse_args(argv)

    try:
        unit = render_codex_history_systemd_unit(
            repo_root=Path(args.repo_root),
            python_executable=args.python,
            service_name=args.service_name,
            env_file=args.env_file,
            instances_dir=args.instances_dir,
            instances=args.instances,
            instance=args.instance,
            sessions_roots=tuple(args.sessions_root or ()),
            limit=int(args.limit),
            event_mode=args.event_mode,
            poll_interval_seconds=float(args.poll_interval),
            follow=bool(args.follow),
            max_iterations=int(args.max_iterations),
            restart_sec=args.restart_sec,
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


def render_codex_history_systemd_unit(
    *,
    repo_root: Path,
    python_executable: str = "",
    service_name: str = DEFAULT_SERVICE_NAME,
    env_file: str = ".env",
    instances_dir: str = DEFAULT_INSTANCES_DIR,
    instances: str = "",
    instance: str = "",
    sessions_roots: tuple[str | Path, ...] = (),
    limit: int = DEFAULT_LIMIT,
    event_mode: str = "auto",
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    follow: bool = True,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    restart_sec: str = DEFAULT_RESTART_SEC,
) -> CodexHistorySystemdUnit:
    service_name = _service_name(service_name)
    repo = repo_root.expanduser().resolve()
    python_path = _python_path(repo, python_executable)
    env_path = _env_path(repo, env_file)
    instances_arg = _instances_path(repo, instances_dir)
    instance = _optional_instance_name(instance)
    instances = _csv_argument(instances, label="instances")
    session_args = _session_root_args(repo, sessions_roots)
    limit = _positive_int(limit, label="limit")
    max_iterations = _positive_int(max_iterations, label="max iterations")
    event_mode = _event_mode(event_mode)
    poll_interval_seconds = _non_negative_float(poll_interval_seconds, label="poll interval")
    restart_sec = _systemd_interval(restart_sec)

    command = [
        _shell_quote(str(python_path)),
        "-m",
        "TeeBotus.admin",
        "codex-history",
        "watch",
        "--instances-dir",
        _shell_quote(instances_arg),
        "--event-mode",
        event_mode,
        "--poll-interval",
        _format_seconds(poll_interval_seconds),
        "--limit",
        str(limit),
    ]
    if follow:
        command.append("--follow")
    else:
        command.extend(["--max-iterations", str(max_iterations)])
    if instances:
        command.append(_shell_quote(f"--instances={instances}"))
    if instance:
        command.append(_shell_quote(f"--instance={instance}"))
    command.extend(session_args)

    service_text = "\n".join(
        [
            "[Unit]",
            "Description=TeeBotus Codex history watcher",
            "Documentation=https://github.com/H234598/TeeBotus",
            "Wants=network-online.target",
            "After=network-online.target",
            "",
            "[Service]",
            "Type=simple",
            f"WorkingDirectory={_systemd_unit_value(str(repo), label='repo root')}",
            f"EnvironmentFile=-{_systemd_unit_value(str(env_path), label='env file')}",
            "ExecStart=" + _systemd_unit_value(" ".join(command), label="command line"),
            "Restart=on-failure" if follow else "Restart=always",
            f"RestartSec={_systemd_unit_value(restart_sec, label='restart interval')}",
            "NoNewPrivileges=true",
            "PrivateTmp=true",
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        ]
    )
    return CodexHistorySystemdUnit(service_name=service_name, service_text=service_text)


def _env_path(repo_root: Path, value: str) -> Path:
    raw = str(value or "").strip() or ".env"
    path = Path(raw).expanduser()
    return path if path.is_absolute() else (repo_root / path).resolve()


def _instances_path(repo_root: Path, value: str) -> str:
    raw = _validate_systemd_unit_value(str(value or "").strip() or DEFAULT_INSTANCES_DIR, label="instances dir")
    path = Path(raw).expanduser()
    return str(path.resolve() if path.is_absolute() else (repo_root / path).resolve())


def _session_root_args(repo_root: Path, roots: tuple[str | Path, ...]) -> list[str]:
    args: list[str] = []
    for root_value in roots:
        raw = _validate_systemd_unit_value(str(root_value or "").strip(), label="sessions root")
        if not raw:
            continue
        path = Path(raw).expanduser()
        resolved = path.resolve() if path.is_absolute() else (repo_root / path).resolve()
        args.extend(["--sessions-root", _shell_quote(str(resolved))])
    return args


def _optional_instance_name(value: str) -> str:
    text = _validate_systemd_unit_value(str(value or "").strip(), label="instance name")
    if not text:
        return ""
    if text in {".", ".."} or "/" in text or "\\" in text:
        raise ValueError("Codex history instance name must be a single path segment")
    return text


def _csv_argument(value: str, *, label: str) -> str:
    text = _validate_systemd_unit_value(str(value or "").strip(), label=label)
    if any(part.strip() in {".", ".."} or "/" in part or "\\" in part for part in text.split(",") if part.strip()):
        raise ValueError(f"Codex history {label} must contain instance names, not paths")
    return text


def _positive_int(value: int, *, label: str) -> int:
    number = int(value)
    if number < 1:
        raise ValueError(f"Codex history {label} must be >= 1 for the restart-driven watcher service")
    return number


def _non_negative_float(value: float, *, label: str) -> float:
    number = float(value)
    if number < 0:
        raise ValueError(f"Codex history {label} must be >= 0")
    return number


def _format_seconds(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _event_mode(value: str) -> str:
    text = _validate_systemd_unit_value(str(value or "auto").strip().casefold(), label="event mode")
    if text not in {"auto", "watchdog", "snapshot", "poll"}:
        raise ValueError("Codex history event mode must be one of auto, watchdog, snapshot or poll")
    return text


def _systemd_interval(value: str) -> str:
    text = _validate_systemd_unit_value(str(value or "").strip() or DEFAULT_RESTART_SEC, label="restart interval")
    if any(char.isspace() for char in text):
        raise ValueError("Codex history restart interval must not contain whitespace")
    return text


if __name__ == "__main__":
    raise SystemExit(main())
