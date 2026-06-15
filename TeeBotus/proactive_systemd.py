from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from TeeBotus.instructions import load_instructions


@dataclass(frozen=True)
class ProactiveSystemdUnit:
    service_name: str
    timer_name: str
    service_text: str
    timer_text: str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install or print TeeBotus proactive-agent user systemd units.")
    parser.add_argument("--repo-root", default=str(Path.cwd()), help="TeeBotus repository root used as WorkingDirectory.")
    parser.add_argument("--instances-dir", default="instances", help="Instances directory passed to teebotus-proactive.")
    parser.add_argument("--instance", default="Depressionsbot", help="Instance name for the proactive scheduler.")
    parser.add_argument("--interval", default="5min", help="systemd OnUnitActiveSec interval.")
    planner_group = parser.add_mutually_exclusive_group()
    planner_group.add_argument(
        "--llm-plan",
        action="store_const",
        dest="planner",
        const="llm",
        help="Include --llm-plan instead of the default --tool-plan.",
    )
    planner_group.add_argument(
        "--tool-plan",
        action="store_const",
        dest="planner",
        const="tool",
        help="Include --tool-plan. This is the default for the Depressionsbot proactive scheduler.",
    )
    planner_group.add_argument("--no-model-plan", action="store_const", dest="planner", const="none", help="Disable model planning and keep only the local reflection planner.")
    parser.set_defaults(planner="auto")
    parser.add_argument("--print", action="store_true", dest="print_only", help="Print unit files instead of writing them.")
    parser.add_argument("--enable", action="store_true", help="Run systemctl --user daemon-reload and enable --now the timer after writing.")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root)
    planner = args.planner
    if planner == "auto":
        planner = _planner_from_instance_instructions(
            repo_root=repo_root,
            instances_dir=args.instances_dir,
            instance_name=args.instance,
        )
    unit = render_proactive_systemd_unit(
        repo_root=repo_root,
        instances_dir=args.instances_dir,
        instance_name=args.instance,
        interval=args.interval,
        llm_plan=planner == "llm",
        tool_plan=planner == "tool",
    )
    if args.print_only:
        print(f"# {unit.service_name}")
        print(unit.service_text, end="")
        print(f"\n# {unit.timer_name}")
        print(unit.timer_text, end="")
        return 0
    user_dir = Path.home() / ".config" / "systemd" / "user"
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / unit.service_name).write_text(unit.service_text, encoding="utf-8")
    (user_dir / unit.timer_name).write_text(unit.timer_text, encoding="utf-8")
    print(f"wrote {user_dir / unit.service_name}")
    print(f"wrote {user_dir / unit.timer_name}")
    if args.enable:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", unit.timer_name], check=True)
        print(f"enabled {unit.timer_name}")
    return 0


def render_proactive_systemd_unit(
    *,
    repo_root: Path,
    instances_dir: str,
    instance_name: str,
    interval: str,
    llm_plan: bool = False,
    tool_plan: bool = True,
) -> ProactiveSystemdUnit:
    if llm_plan and tool_plan:
        raise ValueError("llm_plan and tool_plan are mutually exclusive")
    safe_instance = _systemd_instance_token(instance_name)
    service_name = f"teebotus-proactive-{safe_instance}.service"
    timer_name = f"teebotus-proactive-{safe_instance}.timer"
    repo = repo_root.expanduser().resolve()
    instances_arg = str((repo / instances_dir).resolve()) if not Path(instances_dir).is_absolute() else str(Path(instances_dir).resolve())
    command = [
        _shell_quote(str(Path.home() / ".local" / "bin" / "teebotus-proactive")),
        "--instances-dir",
        _shell_quote(instances_arg),
        "--instance",
        _shell_quote(instance_name),
        "--dispatch",
        "--plan",
    ]
    if llm_plan:
        command.append("--llm-plan")
    if tool_plan:
        command.append("--tool-plan")
    service_text = "\n".join(
        [
            "[Unit]",
            f"Description=TeeBotus proactive agent cycle for {instance_name}",
            "Documentation=https://github.com/H234598/TeeBotus",
            "",
            "[Service]",
            "Type=oneshot",
            f"WorkingDirectory={repo}",
            f"EnvironmentFile=-{repo / '.env'}",
            "ExecStart=" + " ".join(command),
            "",
        ]
    )
    timer_text = "\n".join(
        [
            "[Unit]",
            f"Description=Run TeeBotus proactive agent cycle for {instance_name}",
            "",
            "[Timer]",
            "OnBootSec=5min",
            f"OnUnitActiveSec={_systemd_interval(interval)}",
            "Persistent=true",
            f"Unit={service_name}",
            "",
            "[Install]",
            "WantedBy=timers.target",
            "",
        ]
    )
    return ProactiveSystemdUnit(service_name, timer_name, service_text, timer_text)


def _systemd_instance_token(instance_name: str) -> str:
    token = "".join(char.casefold() if char.isalnum() else "-" for char in str(instance_name or "").strip())
    token = "-".join(part for part in token.split("-") if part)
    return token or "default"


def _systemd_interval(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "5min"
    if any(char.isspace() for char in text):
        raise ValueError("systemd interval must not contain whitespace")
    return text


def _shell_quote(value: str) -> str:
    if not value:
        return "''"
    if all(char.isalnum() or char in "@%_+=:,./-" for char in value):
        return value
    return "'" + value.replace("'", "'\\''") + "'"


def _planner_from_instance_instructions(*, repo_root: Path, instances_dir: str, instance_name: str) -> str:
    repo = repo_root.expanduser().resolve()
    instances_path = Path(instances_dir)
    if not instances_path.is_absolute():
        instances_path = repo / instances_path
    instruction_path = instances_path / instance_name / "Bot_Verhalten.md"
    instructions = load_instructions(instruction_path)
    planner = str(instructions.proactive_model_planner or "").strip().casefold()
    if planner in {"llm", "tool", "none"}:
        return planner
    return "tool"


if __name__ == "__main__":
    raise SystemExit(main())
