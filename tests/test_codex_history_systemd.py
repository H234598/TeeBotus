from __future__ import annotations

import subprocess
from pathlib import Path

from TeeBotus.codex_history_systemd import main, render_codex_history_index_systemd_units, render_codex_history_systemd_unit


def test_render_codex_history_systemd_unit_matches_plan_shape(tmp_path: Path) -> None:
    unit = render_codex_history_systemd_unit(repo_root=tmp_path)

    assert unit.service_name == "teebotus-codex-history.service"
    assert "Description=TeeBotus Codex history watcher" in unit.service_text
    assert f"WorkingDirectory={tmp_path.resolve()}" in unit.service_text
    assert f"EnvironmentFile=-{tmp_path.resolve() / '.env'}" in unit.service_text
    assert "ExecStart=python3 -m TeeBotus.admin codex-history watch" in unit.service_text
    assert f"--instances-dir {tmp_path.resolve() / 'instances'}" in unit.service_text
    assert "--follow" in unit.service_text
    assert "--event-mode auto" in unit.service_text
    assert "--poll-interval 5" in unit.service_text
    assert "--max-iterations" not in unit.service_text
    assert "--limit 1000" in unit.service_text
    assert "--post-index" in unit.service_text
    assert "--post-index-qdrant" not in unit.service_text
    assert "--once" not in unit.service_text
    assert "Restart=on-failure" in unit.service_text
    assert "RestartSec=5s" in unit.service_text
    assert "NoNewPrivileges=true" in unit.service_text
    assert "PrivateTmp=true" in unit.service_text
    assert "WantedBy=default.target" in unit.service_text


def test_render_codex_history_systemd_unit_can_target_instance_and_session_roots(tmp_path: Path) -> None:
    unit = render_codex_history_systemd_unit(
        repo_root=tmp_path,
        instances_dir="instances",
        instance="Depressionsbot",
        sessions_roots=(tmp_path / "sessions", tmp_path / "agents" / "a1" / ".codex" / "sessions"),
        restart_sec="30s",
        python_executable="/usr/bin/python3",
        limit=250,
        event_mode="snapshot",
        poll_interval_seconds=2.5,
    )

    assert "ExecStart=/usr/bin/python3 -m TeeBotus.admin codex-history watch" in unit.service_text
    assert "--instance=Depressionsbot" in unit.service_text
    assert f"--sessions-root {tmp_path / 'sessions'}" in unit.service_text
    assert f"--sessions-root {tmp_path / 'agents' / 'a1' / '.codex' / 'sessions'}" in unit.service_text
    assert "--event-mode snapshot" in unit.service_text
    assert "--poll-interval 2.5" in unit.service_text
    assert "--limit 250" in unit.service_text
    assert "RestartSec=30s" in unit.service_text


def test_render_codex_history_systemd_unit_can_disable_post_index(tmp_path: Path) -> None:
    unit = render_codex_history_systemd_unit(repo_root=tmp_path, post_index=False)

    assert "--post-index" not in unit.service_text
    assert "--post-index-qdrant" not in unit.service_text


def test_render_codex_history_systemd_unit_can_enable_qdrant_post_index(tmp_path: Path) -> None:
    unit = render_codex_history_systemd_unit(
        repo_root=tmp_path,
        post_index_qdrant=True,
        post_index_qdrant_url="http://127.0.0.1:6333",
        post_index_qdrant_dry_run=True,
        post_index_qdrant_ensure=True,
    )

    assert "--post-index" in unit.service_text
    assert "--post-index-qdrant" in unit.service_text
    assert "--post-index-qdrant-url http://127.0.0.1:6333" in unit.service_text
    assert "--post-index-qdrant-dry-run" in unit.service_text
    assert "--post-index-qdrant-ensure" in unit.service_text


def test_render_codex_history_index_systemd_units_builds_low_priority_timer(tmp_path: Path) -> None:
    units = render_codex_history_index_systemd_units(
        repo_root=tmp_path,
        python_executable="/usr/bin/python3",
        instances_dir="instances",
        instance="Depressionsbot",
        interval="4h",
        randomized_delay="20min",
        repo="TeeBotus",
        limit=25,
        qdrant_url="http://127.0.0.1:6333",
    )

    assert units.service_name == "teebotus-codex-history-index.service"
    assert units.timer_name == "teebotus-codex-history-index.timer"
    assert "Type=oneshot" in units.service_text
    assert "Nice=10" in units.service_text
    assert "IOSchedulingClass=best-effort" in units.service_text
    assert "IOSchedulingPriority=7" in units.service_text
    assert "CPUWeight=10" in units.service_text
    assert "IOWeight=10" in units.service_text
    assert "ExecStart=/usr/bin/python3 -m TeeBotus.admin codex-history index" in units.service_text
    assert f"--instances-dir {tmp_path.resolve() / 'instances'}" in units.service_text
    assert "--instance=Depressionsbot" in units.service_text
    assert "--qdrant" in units.service_text
    assert "--qdrant-ensure" in units.service_text
    assert "--repo TeeBotus" in units.service_text
    assert "--limit 25" in units.service_text
    assert "--qdrant-url http://127.0.0.1:6333" in units.service_text
    assert "--categorize" not in units.service_text
    assert "OnBootSec=5min" in units.timer_text
    assert "OnUnitActiveSec=4h" in units.timer_text
    assert "RandomizedDelaySec=20min" in units.timer_text
    assert "Persistent=true" in units.timer_text
    assert "Unit=teebotus-codex-history-index.service" in units.timer_text
    assert "WantedBy=timers.target" in units.timer_text


def test_render_codex_history_index_systemd_units_can_enable_local_categorization(tmp_path: Path) -> None:
    units = render_codex_history_index_systemd_units(
        repo_root=tmp_path,
        graph=True,
        graph_svg=True,
        categorize=True,
        categorize_profile="local_ollama",
        categorize_dry_run=True,
        strategic_analysis=True,
        strategic_analysis_profile="local_ollama",
        strategic_analysis_allow_remote=True,
        strategic_analysis_dry_run=True,
    )

    assert "--graph" in units.service_text
    assert "--graph-svg" in units.service_text
    assert "--categorize" in units.service_text
    assert "--categorize-profile local_ollama" in units.service_text
    assert "--categorize-dry-run" in units.service_text
    assert "--strategic-analysis" in units.service_text
    assert "--strategic-analysis-profile local_ollama" in units.service_text
    assert "--strategic-analysis-allow-remote" in units.service_text
    assert "--strategic-analysis-dry-run" in units.service_text


def test_render_codex_history_index_systemd_units_rejects_unsafe_timer_name(tmp_path: Path) -> None:
    try:
        render_codex_history_index_systemd_units(repo_root=tmp_path, timer_name="../bad.timer")
    except ValueError as exc:
        assert "timer name" in str(exc)
    else:
        raise AssertionError("expected unsafe timer name rejection")


def test_render_codex_history_systemd_unit_can_use_legacy_bounded_restart_loop(tmp_path: Path) -> None:
    unit = render_codex_history_systemd_unit(repo_root=tmp_path, follow=False, max_iterations=3)

    assert "--follow" not in unit.service_text
    assert "--max-iterations 3" in unit.service_text
    assert "Restart=always" in unit.service_text


def test_render_codex_history_systemd_unit_prefers_python313_venv_when_present(tmp_path: Path) -> None:
    legacy_python = tmp_path / ".venv" / "bin" / "python"
    legacy_python.parent.mkdir(parents=True)
    legacy_python.write_text("#!/bin/sh\n", encoding="utf-8")
    py313_python = tmp_path / ".venv-py313" / "bin" / "python"
    py313_python.parent.mkdir(parents=True)
    py313_python.write_text("#!/bin/sh\n", encoding="utf-8")

    unit = render_codex_history_systemd_unit(repo_root=tmp_path)

    assert f"ExecStart={py313_python.resolve()} -m TeeBotus.admin codex-history watch" in unit.service_text
    assert str(legacy_python.resolve()) not in unit.service_text


def test_render_codex_history_systemd_unit_uses_assignment_for_dash_prefixed_instance(tmp_path: Path) -> None:
    unit = render_codex_history_systemd_unit(repo_root=tmp_path, instance="-Depressionsbot")

    assert "--instance=-Depressionsbot" in unit.service_text
    assert "--instance -Depressionsbot" not in unit.service_text


def test_render_codex_history_systemd_unit_rejects_control_characters(tmp_path: Path) -> None:
    cases = [
        {"repo_root": Path("/tmp/TeeBotus\nExecStart=/bin/false")},
        {"repo_root": tmp_path, "instances_dir": "instances\nExecStart=/bin/false"},
        {"repo_root": tmp_path, "instance": "Depressionsbot\nExecStart=/bin/false"},
        {"repo_root": tmp_path, "restart_sec": "5s\nExecStart=/bin/false"},
    ]
    for kwargs in cases:
        try:
            render_codex_history_systemd_unit(**kwargs)
        except ValueError as exc:
            assert "invalid control characters" in str(exc)
        else:
            raise AssertionError(f"expected control character rejection for {kwargs}")


def test_render_codex_history_systemd_unit_rejects_invalid_event_mode(tmp_path: Path) -> None:
    try:
        render_codex_history_systemd_unit(repo_root=tmp_path, event_mode="nonsense")
    except ValueError as exc:
        assert "event mode" in str(exc)
    else:
        raise AssertionError("expected invalid event mode rejection")


def test_render_codex_history_systemd_unit_escapes_systemd_percent_specifiers(tmp_path: Path) -> None:
    repo_root = tmp_path / "TeeBotus%x%h"
    unit = render_codex_history_systemd_unit(
        repo_root=repo_root,
        python_executable="/usr/bin/python3%x",
        env_file=".env%h",
        instance="Depressionsbot%h",
    )

    assert f"WorkingDirectory={repo_root.resolve()}".replace("%", "%%") in unit.service_text
    assert f"EnvironmentFile=-{repo_root.resolve() / '.env%h'}".replace("%", "%%") in unit.service_text
    assert "ExecStart=/usr/bin/python3%%x -m TeeBotus.admin codex-history watch" in unit.service_text
    assert "--instance=Depressionsbot%%h" in unit.service_text


def test_codex_history_systemd_print_mode_outputs_service(tmp_path: Path, capsys) -> None:
    result = main(["--repo-root", str(tmp_path), "--print"])

    captured = capsys.readouterr()
    assert result == 0
    assert "# teebotus-codex-history.service" in captured.out
    assert "ExecStart=python3 -m TeeBotus.admin codex-history watch" in captured.out


def test_codex_history_systemd_print_mode_can_output_index_timer(tmp_path: Path, capsys) -> None:
    result = main(["--repo-root", str(tmp_path), "--index-timer", "--print"])

    captured = capsys.readouterr()
    assert result == 0
    assert "# teebotus-codex-history.service" in captured.out
    assert "# teebotus-codex-history-index.service" in captured.out
    assert "# teebotus-codex-history-index.timer" in captured.out
    assert "ExecStart=python3 -m TeeBotus.admin codex-history index" in captured.out
    assert "OnUnitActiveSec=6h" in captured.out


def test_codex_history_systemd_enable_runs_user_systemctl(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(command, check=False, **_kwargs):
        calls.append(list(command))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("TeeBotus.codex_history_systemd.Path.home", lambda: tmp_path)
    monkeypatch.setattr("TeeBotus.codex_history_systemd.subprocess.run", fake_run)

    result = main(["--repo-root", str(tmp_path), "--enable"])

    assert result == 0
    assert (tmp_path / ".config" / "systemd" / "user" / "teebotus-codex-history.service").exists()
    assert calls == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", "teebotus-codex-history.service"],
    ]


def test_codex_history_systemd_enable_with_index_timer_writes_and_enables_timer(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(command, check=False, **_kwargs):
        calls.append(list(command))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("TeeBotus.codex_history_systemd.Path.home", lambda: tmp_path)
    monkeypatch.setattr("TeeBotus.codex_history_systemd.subprocess.run", fake_run)

    result = main(["--repo-root", str(tmp_path), "--index-timer", "--enable"])

    assert result == 0
    user_dir = tmp_path / ".config" / "systemd" / "user"
    assert (user_dir / "teebotus-codex-history.service").exists()
    assert (user_dir / "teebotus-codex-history-index.service").exists()
    assert (user_dir / "teebotus-codex-history-index.timer").exists()
    assert calls == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", "teebotus-codex-history.service"],
        ["systemctl", "--user", "enable", "--now", "teebotus-codex-history-index.timer"],
    ]
