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


DEFAULT_SERVICE_NAME = "teebotus-codex-history-collector.service"
DEFAULT_COLLECTOR_TIMER_NAME = "teebotus-codex-history-collector.timer"
DEFAULT_INDEX_SERVICE_NAME = "teebotus-codex-history-index.service"
DEFAULT_INDEX_TIMER_NAME = "teebotus-codex-history-index.timer"
DEFAULT_INSTANCES_DIR = "instances"
DEFAULT_SYSTEMD_SYSTEM_DIR = "/etc/systemd/system"
DEFAULT_RUN_USER = "root"
DEFAULT_RESTART_SEC = "5s"
DEFAULT_POLL_INTERVAL_SECONDS = 300.0
DEFAULT_LIMIT = 1000
DEFAULT_MAX_ITERATIONS = 1
DEFAULT_COLLECTOR_INTERVAL = "5min"
DEFAULT_COLLECTOR_RANDOMIZED_DELAY = "0"
DEFAULT_INDEX_INTERVAL = "24h"
DEFAULT_INDEX_RANDOMIZED_DELAY = "15min"


@dataclass(frozen=True)
class CodexHistorySystemdUnit:
    service_name: str
    service_text: str


@dataclass(frozen=True)
class CodexHistoryCollectorTimerUnits:
    service_name: str
    service_text: str
    timer_name: str
    timer_text: str


@dataclass(frozen=True)
class CodexHistoryIndexSystemdUnits:
    service_name: str
    service_text: str
    timer_name: str
    timer_text: str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install or print the TeeBotus Codex history collector systemd service.")
    parser.add_argument("--repo-root", default=str(Path.cwd()), help="TeeBotus repository root used as WorkingDirectory.")
    parser.add_argument(
        "--python",
        default="",
        help="Python executable. Defaults to .venv-py313/bin/python if present, then .venv/bin/python, else python3.",
    )
    parser.add_argument("--service-name", default=DEFAULT_SERVICE_NAME, help="systemd service filename.")
    parser.add_argument("--run-user", default=DEFAULT_RUN_USER, help="System service User value. Empty omits User=.")
    parser.add_argument("--system-dir", default=DEFAULT_SYSTEMD_SYSTEM_DIR, help="Systemd system unit directory used outside --user-unit.")
    parser.add_argument("--user-unit", action="store_true", help="Install as the invoking user's user-systemd unit instead of a system/root unit.")
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
    parser.add_argument("--post-index", dest="post_index", action="store_true", default=True, help="Export admin-only Codex-History index after scans.")
    parser.add_argument("--no-post-index", dest="post_index", action="store_false", help="Disable post-scan Codex-History index export.")
    parser.add_argument("--post-index-qdrant", action="store_true", help="Also rebuild the admin-only Codex-History Qdrant collection after scans.")
    parser.add_argument("--post-index-qdrant-url", default="", help="Override Qdrant URL for post-index rebuild.")
    parser.add_argument("--post-index-qdrant-dry-run", action="store_true", help="Count post-index Qdrant chunks without writing Qdrant.")
    parser.add_argument("--post-index-qdrant-ensure", action="store_true", help="Ensure Qdrant collections before post-index rebuild.")
    parser.add_argument("--collector-timer", action="store_true", help="Render/install the collector as a bounded oneshot service plus timer.")
    parser.add_argument("--collector-timer-name", default=DEFAULT_COLLECTOR_TIMER_NAME, help="systemd timer filename for the collector timer.")
    parser.add_argument("--collector-interval", default=DEFAULT_COLLECTOR_INTERVAL, help="Timer OnUnitActiveSec interval for the collector timer.")
    parser.add_argument(
        "--collector-randomized-delay",
        default=DEFAULT_COLLECTOR_RANDOMIZED_DELAY,
        help="Timer RandomizedDelaySec for the collector timer.",
    )
    parser.add_argument("--index-timer", action="store_true", help="Also render/install a low-priority periodic Codex-History admin index timer.")
    parser.add_argument("--index-service-name", default=DEFAULT_INDEX_SERVICE_NAME, help="systemd service filename for periodic Codex-History indexing.")
    parser.add_argument("--index-timer-name", default=DEFAULT_INDEX_TIMER_NAME, help="systemd timer filename for periodic Codex-History indexing.")
    parser.add_argument("--index-interval", default=DEFAULT_INDEX_INTERVAL, help="Timer OnUnitActiveSec interval for periodic Codex-History indexing.")
    parser.add_argument(
        "--index-randomized-delay",
        default=DEFAULT_INDEX_RANDOMIZED_DELAY,
        help="Timer RandomizedDelaySec for periodic Codex-History indexing.",
    )
    parser.add_argument("--index-repo", default="", help="Repo filter passed to codex-history index.")
    parser.add_argument("--index-limit", type=int, default=0, help="Limit codex-history index to latest N summaries after filtering; 0 means all.")
    parser.add_argument("--index-qdrant-url", default="", help="Override Qdrant URL for periodic index rebuild.")
    parser.add_argument("--index-qdrant-dry-run", action="store_true", help="Count periodic Qdrant chunks without writing Qdrant.")
    parser.add_argument("--index-graph", action="store_true", help="Export an admin-only Mermaid graph during the periodic Codex-History index job.")
    parser.add_argument("--index-graph-svg", action="store_true", help="Also export a dependency-free SVG Codex-History graph image.")
    parser.add_argument(
        "--index-graph-svg-engine",
        choices=("builtin", "auto", "mmdc"),
        default="builtin",
        help="SVG renderer for periodic graph export; auto uses Mermaid CLI mmdc when installed.",
    )
    parser.add_argument("--index-graph-queue-svg", action="store_true", help="Queue the SVG Codex-History graph for admin dispatch.")
    parser.add_argument("--index-categorize", action="store_true", help="Run optional local Codex-History categorization in the periodic index job.")
    parser.add_argument("--index-categorize-profile", default="local_ollama", help="Local-only LLM profile used by periodic Codex-History categorization.")
    parser.add_argument("--index-categorize-dry-run", action="store_true", help="Run periodic categorization without persisting category updates.")
    parser.add_argument("--index-strategic-analysis", action="store_true", help="Queue an admin-only strategic Codex-History analysis in the periodic index job.")
    parser.add_argument("--index-strategic-analysis-profile", default="local_ollama", help="LLM profile used by periodic Codex-History strategic analysis.")
    parser.add_argument("--index-strategic-analysis-allow-remote", action="store_true", help="Allow a remote strategic-analysis profile explicitly.")
    parser.add_argument("--index-strategic-analysis-force", action="store_true", help="Bypass strategic-analysis source cache.")
    parser.add_argument("--index-strategic-analysis-dry-run", action="store_true", help="Run periodic strategic analysis without writing the outbox item.")
    parser.add_argument("--index-dispatch", action="store_true", help="Dispatch queued Codex-History items after the periodic index job.")
    parser.add_argument("--index-dispatch-limit", type=int, default=100, help="Max queued Codex-History items to dispatch after periodic indexing; 0 means all.")
    parser.add_argument("--index-dispatch-dry-run", action="store_true", help="Dry-run the post-index dispatch step.")
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=DEFAULT_MAX_ITERATIONS,
        help="Bounded watch iterations per service start when --no-follow is used.",
    )
    parser.add_argument("--restart-sec", default=DEFAULT_RESTART_SEC, help="systemd RestartSec interval.")
    parser.add_argument("--print", action="store_true", dest="print_only", help="Print unit file instead of writing it.")
    parser.add_argument("--enable", action="store_true", help="Run systemctl daemon-reload and enable --now the service after writing.")
    args = parser.parse_args(argv)

    try:
        run_user = "" if args.user_unit else args.run_user
        collector_timer_units = (
            render_codex_history_collector_timer_units(
                repo_root=Path(args.repo_root),
                python_executable=args.python,
                service_name=args.service_name,
                timer_name=args.collector_timer_name,
                run_user=run_user,
                env_file=args.env_file,
                instances_dir=args.instances_dir,
                instances=args.instances,
                instance=args.instance,
                sessions_roots=tuple(args.sessions_root or ()),
                limit=int(args.limit),
                event_mode=args.event_mode,
                poll_interval_seconds=float(args.poll_interval),
                post_index=bool(args.post_index),
                post_index_qdrant=bool(args.post_index_qdrant),
                post_index_qdrant_url=args.post_index_qdrant_url,
                post_index_qdrant_dry_run=bool(args.post_index_qdrant_dry_run),
                post_index_qdrant_ensure=bool(args.post_index_qdrant_ensure),
                interval=args.collector_interval,
                randomized_delay=args.collector_randomized_delay,
            )
            if args.collector_timer
            else None
        )
        unit = None if collector_timer_units is not None else render_codex_history_systemd_unit(
            repo_root=Path(args.repo_root),
            python_executable=args.python,
            service_name=args.service_name,
            run_user=run_user,
            env_file=args.env_file,
            instances_dir=args.instances_dir,
            instances=args.instances,
            instance=args.instance,
            sessions_roots=tuple(args.sessions_root or ()),
            limit=int(args.limit),
            event_mode=args.event_mode,
            poll_interval_seconds=float(args.poll_interval),
            follow=bool(args.follow),
            post_index=bool(args.post_index),
            post_index_qdrant=bool(args.post_index_qdrant),
            post_index_qdrant_url=args.post_index_qdrant_url,
            post_index_qdrant_dry_run=bool(args.post_index_qdrant_dry_run),
            post_index_qdrant_ensure=bool(args.post_index_qdrant_ensure),
            max_iterations=int(args.max_iterations),
            restart_sec=args.restart_sec,
        )
        index_units = (
            render_codex_history_index_systemd_units(
                repo_root=Path(args.repo_root),
                python_executable=args.python,
                service_name=args.index_service_name,
                timer_name=args.index_timer_name,
                run_user=run_user,
                env_file=args.env_file,
                instances_dir=args.instances_dir,
                instances=args.instances,
                instance=args.instance,
                interval=args.index_interval,
                randomized_delay=args.index_randomized_delay,
                repo=args.index_repo,
                limit=int(args.index_limit),
                qdrant_url=args.index_qdrant_url,
                qdrant_dry_run=bool(args.index_qdrant_dry_run),
                graph=bool(args.index_graph),
                graph_svg=bool(args.index_graph_svg),
                graph_svg_engine=args.index_graph_svg_engine,
                graph_queue_svg=bool(args.index_graph_queue_svg),
                categorize=bool(args.index_categorize),
                categorize_profile=args.index_categorize_profile,
                categorize_dry_run=bool(args.index_categorize_dry_run),
                strategic_analysis=bool(args.index_strategic_analysis),
                strategic_analysis_profile=args.index_strategic_analysis_profile,
                strategic_analysis_allow_remote=bool(args.index_strategic_analysis_allow_remote),
                strategic_analysis_force=bool(args.index_strategic_analysis_force),
                strategic_analysis_dry_run=bool(args.index_strategic_analysis_dry_run),
                dispatch=bool(args.index_dispatch),
                dispatch_limit=int(args.index_dispatch_limit),
                dispatch_dry_run=bool(args.index_dispatch_dry_run),
            )
            if args.index_timer
            else None
        )
    except ValueError as exc:
        parser.error(str(exc))
    if args.print_only:
        if unit is not None:
            print(f"# {unit.service_name}")
            print(unit.service_text, end="")
        if collector_timer_units is not None:
            print(f"# {collector_timer_units.service_name}")
            print(collector_timer_units.service_text, end="")
            print(f"# {collector_timer_units.timer_name}")
            print(collector_timer_units.timer_text, end="")
        if index_units is not None:
            print(f"# {index_units.service_name}")
            print(index_units.service_text, end="")
            print(f"# {index_units.timer_name}")
            print(index_units.timer_text, end="")
        return 0
    unit_dir = Path.home() / ".config" / "systemd" / "user" if args.user_unit else Path(args.system_dir).expanduser()
    unit_dir.mkdir(parents=True, exist_ok=True)
    targets: list[tuple[str, str]] = []
    if unit is not None:
        targets.append((unit.service_name, unit.service_text))
    if collector_timer_units is not None:
        targets.extend(
            [
                (collector_timer_units.service_name, collector_timer_units.service_text),
                (collector_timer_units.timer_name, collector_timer_units.timer_text),
            ]
        )
    if index_units is not None:
        targets.extend(
            [
                (index_units.service_name, index_units.service_text),
                (index_units.timer_name, index_units.timer_text),
            ]
        )
    for name, text in targets:
        target = unit_dir / name
        target.write_text(text, encoding="utf-8")
        print(f"wrote {target}")
    if args.enable:
        systemctl = ["systemctl", "--user"] if args.user_unit else ["systemctl"]
        subprocess.run([*systemctl, "daemon-reload"], check=True)
        if collector_timer_units is not None:
            subprocess.run([*systemctl, "enable", "--now", collector_timer_units.timer_name], check=True)
        elif unit is not None:
            subprocess.run([*systemctl, "enable", "--now", unit.service_name], check=True)
        if index_units is not None:
            subprocess.run([*systemctl, "enable", "--now", index_units.timer_name], check=True)
        if collector_timer_units is not None:
            print(f"enabled {collector_timer_units.timer_name}")
        elif unit is not None:
            print(f"enabled {unit.service_name}")
        if index_units is not None:
            print(f"enabled {index_units.timer_name}")
    return 0


def render_codex_history_systemd_unit(
    *,
    repo_root: Path,
    python_executable: str = "",
    service_name: str = DEFAULT_SERVICE_NAME,
    run_user: str = DEFAULT_RUN_USER,
    env_file: str = ".env",
    instances_dir: str = DEFAULT_INSTANCES_DIR,
    instances: str = "",
    instance: str = "",
    sessions_roots: tuple[str | Path, ...] = (),
    limit: int = DEFAULT_LIMIT,
    event_mode: str = "auto",
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    follow: bool = True,
    post_index: bool = True,
    post_index_qdrant: bool = False,
    post_index_qdrant_url: str = "",
    post_index_qdrant_dry_run: bool = False,
    post_index_qdrant_ensure: bool = False,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    restart_sec: str = DEFAULT_RESTART_SEC,
) -> CodexHistorySystemdUnit:
    service_name = _service_name(service_name)
    repo = repo_root.expanduser().resolve()
    python_path = _python_path(repo, python_executable)
    run_user = _run_user(run_user)
    env_path = _env_path(repo, env_file)
    instances_arg = _instances_path(repo, instances_dir)
    instance = _optional_instance_name(instance)
    instances = _csv_argument(instances, label="instances")
    effective_sessions_roots = sessions_roots or _default_collector_session_roots(repo, run_user=run_user)
    session_args = _session_root_args(repo, effective_sessions_roots)
    limit = _positive_int(limit, label="limit")
    max_iterations = _positive_int(max_iterations, label="max iterations")
    event_mode = _event_mode(event_mode)
    poll_interval_seconds = _non_negative_float(poll_interval_seconds, label="poll interval")
    post_index_qdrant_url = _optional_systemd_argument(post_index_qdrant_url, label="post-index qdrant url")
    restart_sec = _systemd_interval(restart_sec)

    command = _collector_watch_command(
        python_path=python_path,
        instances_arg=instances_arg,
        event_mode=event_mode,
        poll_interval_seconds=poll_interval_seconds,
        limit=limit,
        follow=follow,
        once=False,
        max_iterations=max_iterations,
        instances=instances,
        instance=instance,
        session_args=session_args,
        post_index=post_index,
        post_index_qdrant=post_index_qdrant,
        post_index_qdrant_url=post_index_qdrant_url,
        post_index_qdrant_dry_run=post_index_qdrant_dry_run,
        post_index_qdrant_ensure=post_index_qdrant_ensure,
    )

    service_text = "\n".join(
        [
            "[Unit]",
            "Description=TeeBotus Codex history collector",
            "Documentation=https://github.com/H234598/TeeBotus",
            "Wants=network-online.target",
            "After=network-online.target",
            "",
            "[Service]",
            "Type=simple",
            *( [f"User={_systemd_unit_value(run_user, label='run user')}"] if run_user else [] ),
            f"WorkingDirectory={_systemd_unit_value(str(repo), label='repo root')}",
            f"EnvironmentFile=-{_systemd_unit_value(str(env_path), label='env file')}",
            "ExecStart=" + _systemd_unit_value(" ".join(command), label="command line"),
            "Restart=on-failure" if follow else "Restart=always",
            f"RestartSec={_systemd_unit_value(restart_sec, label='restart interval')}",
            "UMask=0077",
            "NoNewPrivileges=true",
            "PrivateTmp=true",
            "",
            "[Install]",
            "WantedBy=multi-user.target" if run_user else "WantedBy=default.target",
            "",
        ]
    )
    return CodexHistorySystemdUnit(service_name=service_name, service_text=service_text)


def render_codex_history_collector_timer_units(
    *,
    repo_root: Path,
    python_executable: str = "",
    service_name: str = DEFAULT_SERVICE_NAME,
    timer_name: str = DEFAULT_COLLECTOR_TIMER_NAME,
    run_user: str = DEFAULT_RUN_USER,
    env_file: str = ".env",
    instances_dir: str = DEFAULT_INSTANCES_DIR,
    instances: str = "",
    instance: str = "",
    sessions_roots: tuple[str | Path, ...] = (),
    limit: int = DEFAULT_LIMIT,
    event_mode: str = "snapshot",
    poll_interval_seconds: float = 0,
    post_index: bool = True,
    post_index_qdrant: bool = False,
    post_index_qdrant_url: str = "",
    post_index_qdrant_dry_run: bool = False,
    post_index_qdrant_ensure: bool = False,
    interval: str = DEFAULT_COLLECTOR_INTERVAL,
    randomized_delay: str = DEFAULT_COLLECTOR_RANDOMIZED_DELAY,
) -> CodexHistoryCollectorTimerUnits:
    service_name = _service_name(service_name)
    timer_name = _timer_name(timer_name)
    repo = repo_root.expanduser().resolve()
    python_path = _python_path(repo, python_executable)
    run_user = _run_user(run_user)
    env_path = _env_path(repo, env_file)
    instances_arg = _instances_path(repo, instances_dir)
    instance = _optional_instance_name(instance)
    instances = _csv_argument(instances, label="instances")
    effective_sessions_roots = sessions_roots or _default_collector_session_roots(repo, run_user=run_user)
    session_args = _session_root_args(repo, effective_sessions_roots)
    limit = _positive_int(limit, label="limit")
    event_mode = _event_mode(event_mode)
    poll_interval_seconds = _non_negative_float(poll_interval_seconds, label="poll interval")
    post_index_qdrant_url = _optional_systemd_argument(post_index_qdrant_url, label="post-index qdrant url")
    interval = _systemd_interval(interval)
    randomized_delay = _systemd_interval(randomized_delay)

    command = _collector_watch_command(
        python_path=python_path,
        instances_arg=instances_arg,
        event_mode=event_mode,
        poll_interval_seconds=poll_interval_seconds,
        limit=limit,
        follow=False,
        once=True,
        max_iterations=1,
        instances=instances,
        instance=instance,
        session_args=session_args,
        post_index=post_index,
        post_index_qdrant=post_index_qdrant,
        post_index_qdrant_url=post_index_qdrant_url,
        post_index_qdrant_dry_run=post_index_qdrant_dry_run,
        post_index_qdrant_ensure=post_index_qdrant_ensure,
    )
    service_text = "\n".join(
        [
            "[Unit]",
            "Description=TeeBotus Codex history collector scan",
            "Documentation=https://github.com/H234598/TeeBotus",
            "Wants=network-online.target",
            "After=network-online.target",
            "",
            "[Service]",
            "Type=oneshot",
            *( [f"User={_systemd_unit_value(run_user, label='run user')}"] if run_user else [] ),
            f"WorkingDirectory={_systemd_unit_value(str(repo), label='repo root')}",
            f"EnvironmentFile=-{_systemd_unit_value(str(env_path), label='env file')}",
            "Nice=10",
            "IOSchedulingClass=best-effort",
            "IOSchedulingPriority=7",
            "CPUWeight=10",
            "IOWeight=10",
            "ExecStart=" + _systemd_unit_value(" ".join(command), label="command line"),
            "UMask=0077",
            "NoNewPrivileges=true",
            "PrivateTmp=true",
            "",
        ]
    )
    timer_text = "\n".join(
        [
            "[Unit]",
            "Description=Run TeeBotus Codex history collector scan",
            "",
            "[Timer]",
            "OnBootSec=1min",
            f"OnUnitActiveSec={_systemd_unit_value(interval, label='collector interval')}",
            f"RandomizedDelaySec={_systemd_unit_value(randomized_delay, label='collector randomized delay')}",
            "Persistent=true",
            f"Unit={_systemd_unit_value(service_name, label='collector service name')}",
            "",
            "[Install]",
            "WantedBy=timers.target",
            "",
        ]
    )
    return CodexHistoryCollectorTimerUnits(
        service_name=service_name,
        service_text=service_text,
        timer_name=timer_name,
        timer_text=timer_text,
    )


def render_codex_history_index_systemd_units(
    *,
    repo_root: Path,
    python_executable: str = "",
    service_name: str = DEFAULT_INDEX_SERVICE_NAME,
    timer_name: str = DEFAULT_INDEX_TIMER_NAME,
    run_user: str = DEFAULT_RUN_USER,
    env_file: str = ".env",
    instances_dir: str = DEFAULT_INSTANCES_DIR,
    instances: str = "",
    instance: str = "",
    interval: str = DEFAULT_INDEX_INTERVAL,
    randomized_delay: str = DEFAULT_INDEX_RANDOMIZED_DELAY,
    repo: str = "",
    limit: int = 0,
    qdrant_url: str = "",
    qdrant_dry_run: bool = False,
    graph: bool = False,
    graph_svg: bool = False,
    graph_svg_engine: str = "builtin",
    graph_queue_svg: bool = False,
    categorize: bool = False,
    categorize_profile: str = "local_ollama",
    categorize_dry_run: bool = False,
    strategic_analysis: bool = False,
    strategic_analysis_profile: str = "local_ollama",
    strategic_analysis_allow_remote: bool = False,
    strategic_analysis_force: bool = False,
    strategic_analysis_dry_run: bool = False,
    dispatch: bool = False,
    dispatch_limit: int = 100,
    dispatch_dry_run: bool = False,
) -> CodexHistoryIndexSystemdUnits:
    service_name = _service_name(service_name)
    timer_name = _timer_name(timer_name)
    repo_root = repo_root.expanduser().resolve()
    python_path = _python_path(repo_root, python_executable)
    run_user = _run_user(run_user)
    env_path = _env_path(repo_root, env_file)
    instances_arg = _instances_path(repo_root, instances_dir)
    instances = _csv_argument(instances, label="instances")
    instance = _optional_instance_name(instance)
    interval = _systemd_interval(interval)
    randomized_delay = _systemd_interval(randomized_delay)
    repo_filter = _optional_systemd_argument(repo, label="index repo filter")
    qdrant_url = _optional_systemd_argument(qdrant_url, label="index qdrant url")
    graph_svg_engine = _graph_svg_engine(graph_svg_engine)
    categorize_profile = _optional_systemd_argument(categorize_profile, label="index categorize profile") or "local_ollama"
    strategic_analysis_profile = _optional_systemd_argument(strategic_analysis_profile, label="index strategic analysis profile") or "local_ollama"
    index_limit = _non_negative_int(limit, label="index limit")
    dispatch_limit = _non_negative_int(dispatch_limit, label="index dispatch limit")

    command = [
        _shell_quote(str(python_path)),
        "-m",
        "TeeBotus.admin",
        "codex-history",
        "index",
        "--instances-dir",
        _shell_quote(instances_arg),
        "--qdrant",
        "--qdrant-ensure",
    ]
    if instances:
        command.append(_shell_quote(f"--instances={instances}"))
    if instance:
        command.append(_shell_quote(f"--instance={instance}"))
    if repo_filter:
        command.extend(["--repo", _shell_quote(repo_filter)])
    if index_limit > 0:
        command.extend(["--limit", str(index_limit)])
    if qdrant_url:
        command.extend(["--qdrant-url", _shell_quote(qdrant_url)])
    if qdrant_dry_run:
        command.append("--qdrant-dry-run")
    if graph or graph_svg or graph_queue_svg:
        command.append("--graph")
        if graph_svg or graph_queue_svg:
            command.append("--graph-svg")
            if graph_svg_engine != "builtin":
                command.extend(["--graph-svg-engine", graph_svg_engine])
        if graph_queue_svg:
            command.append("--graph-queue-svg")
    if categorize:
        command.append("--categorize")
        command.extend(["--categorize-profile", _shell_quote(categorize_profile)])
        if categorize_dry_run:
            command.append("--categorize-dry-run")
    if strategic_analysis:
        command.append("--strategic-analysis")
        command.extend(["--strategic-analysis-profile", _shell_quote(strategic_analysis_profile)])
        if strategic_analysis_allow_remote:
            command.append("--strategic-analysis-allow-remote")
        if strategic_analysis_force:
            command.append("--strategic-analysis-force")
        if strategic_analysis_dry_run:
            command.append("--strategic-analysis-dry-run")
    dispatch_command: list[str] = []
    if dispatch:
        dispatch_command = [
            _shell_quote(str(python_path)),
            "-m",
            "TeeBotus.admin",
            "codex-history",
            "dispatch",
            "--instances-dir",
            _shell_quote(instances_arg),
            "--limit",
            str(dispatch_limit),
        ]
        if instances:
            dispatch_command.append(_shell_quote(f"--instances={instances}"))
        if instance:
            dispatch_command.append(_shell_quote(f"--instance={instance}"))
        if dispatch_dry_run:
            dispatch_command.append("--dry-run")

    service_lines = [
        "[Unit]",
        "Description=TeeBotus Codex history admin index refresh",
        "Documentation=https://github.com/H234598/TeeBotus",
        "Wants=network-online.target",
        "After=network-online.target",
        "",
        "[Service]",
        "Type=oneshot",
        *( [f"User={_systemd_unit_value(run_user, label='run user')}"] if run_user else [] ),
        f"WorkingDirectory={_systemd_unit_value(str(repo_root), label='repo root')}",
        f"EnvironmentFile=-{_systemd_unit_value(str(env_path), label='env file')}",
        "Nice=10",
        "IOSchedulingClass=best-effort",
        "IOSchedulingPriority=7",
        "CPUWeight=10",
        "IOWeight=10",
        "ExecStart=" + _systemd_unit_value(" ".join(command), label="command line"),
    ]
    if dispatch_command:
        service_lines.append("ExecStartPost=" + _systemd_unit_value(" ".join(dispatch_command), label="dispatch command line"))
    service_lines.extend(
        [
            "NoNewPrivileges=true",
            "PrivateTmp=true",
            "",
        ]
    )
    service_text = "\n".join(service_lines)
    timer_text = "\n".join(
        [
            "[Unit]",
            "Description=Run TeeBotus Codex history admin index refresh",
            "",
            "[Timer]",
            "OnBootSec=5min",
            f"OnUnitActiveSec={_systemd_unit_value(interval, label='index interval')}",
            f"RandomizedDelaySec={_systemd_unit_value(randomized_delay, label='index randomized delay')}",
            "Persistent=true",
            f"Unit={_systemd_unit_value(service_name, label='index service name')}",
            "",
            "[Install]",
            "WantedBy=timers.target",
            "",
        ]
    )
    return CodexHistoryIndexSystemdUnits(
        service_name=service_name,
        service_text=service_text,
        timer_name=timer_name,
        timer_text=timer_text,
    )


def _collector_watch_command(
    *,
    python_path: Path,
    instances_arg: str,
    event_mode: str,
    poll_interval_seconds: float,
    limit: int,
    follow: bool,
    once: bool,
    max_iterations: int,
    instances: str,
    instance: str,
    session_args: list[str],
    post_index: bool,
    post_index_qdrant: bool,
    post_index_qdrant_url: str,
    post_index_qdrant_dry_run: bool,
    post_index_qdrant_ensure: bool,
) -> list[str]:
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
    if once:
        command.append("--once")
    elif follow:
        command.append("--follow")
    else:
        command.extend(["--max-iterations", str(max_iterations)])
    if instances:
        command.append(_shell_quote(f"--instances={instances}"))
    if instance:
        command.append(_shell_quote(f"--instance={instance}"))
    command.extend(session_args)
    if post_index or post_index_qdrant or post_index_qdrant_ensure:
        command.append("--post-index")
    if post_index_qdrant:
        command.append("--post-index-qdrant")
    if post_index_qdrant_url:
        command.extend(["--post-index-qdrant-url", _shell_quote(post_index_qdrant_url)])
    if post_index_qdrant_dry_run:
        command.append("--post-index-qdrant-dry-run")
    if post_index_qdrant_ensure:
        command.append("--post-index-qdrant-ensure")
    return command


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


def _default_collector_session_roots(repo_root: Path, *, run_user: str) -> tuple[Path, ...]:
    if run_user != "root":
        return ()
    owner_home = _home_from_repo_root(repo_root)
    if owner_home is None:
        return ()
    return (owner_home / ".codex" / "sessions", owner_home / ".codex-agents")


def _home_from_repo_root(repo_root: Path) -> Path | None:
    parts = repo_root.parts
    if len(parts) >= 3 and parts[0] == "/" and parts[1] == "home" and parts[2]:
        return Path("/", "home", parts[2])
    return None


def _run_user(value: str) -> str:
    text = _validate_systemd_unit_value(str(value or "").strip(), label="run user")
    if not text:
        return ""
    if any(char.isspace() for char in text):
        raise ValueError("Codex history run user must not contain whitespace")
    return text


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


def _optional_systemd_argument(value: str, *, label: str) -> str:
    return _validate_systemd_unit_value(str(value or "").strip(), label=label)


def _timer_name(value: str) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError("systemd timer name must not be empty")
    if not name.endswith(".timer"):
        name = f"{name}.timer"
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.@-")
    if any(char not in allowed for char in name):
        raise ValueError("systemd timer name contains unsupported characters")
    if not name[0].isalnum():
        raise ValueError("systemd timer name must start with an ASCII letter or digit")
    return name


def _positive_int(value: int, *, label: str) -> int:
    number = int(value)
    if number < 1:
        raise ValueError(f"Codex history {label} must be >= 1 for the restart-driven watcher service")
    return number


def _non_negative_int(value: int, *, label: str) -> int:
    number = int(value)
    if number < 0:
        raise ValueError(f"Codex history {label} must be >= 0")
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


def _graph_svg_engine(value: str) -> str:
    text = _validate_systemd_unit_value(str(value or "builtin").strip().casefold(), label="graph svg engine")
    if text not in {"builtin", "auto", "mmdc"}:
        raise ValueError("Codex history graph svg engine must be builtin, auto, or mmdc")
    return text


def _systemd_interval(value: str) -> str:
    text = _validate_systemd_unit_value(str(value or "").strip() or DEFAULT_RESTART_SEC, label="restart interval")
    if any(char.isspace() for char in text):
        raise ValueError("Codex history restart interval must not contain whitespace")
    return text


if __name__ == "__main__":
    raise SystemExit(main())
