from __future__ import annotations

import subprocess
from pathlib import Path

from TeeBotus.codex_history_systemd import main, render_codex_history_systemd_unit


def test_render_codex_history_systemd_unit_matches_plan_shape(tmp_path: Path) -> None:
    unit = render_codex_history_systemd_unit(repo_root=tmp_path)

    assert unit.service_name == "teebotus-codex-history.service"
    assert "Description=TeeBotus Codex history watcher" in unit.service_text
    assert f"WorkingDirectory={tmp_path.resolve()}" in unit.service_text
    assert f"EnvironmentFile=-{tmp_path.resolve() / '.env'}" in unit.service_text
    assert "ExecStart=python3 -m TeeBotus.admin codex-history watch" in unit.service_text
    assert f"--instances-dir {tmp_path.resolve() / 'instances'}" in unit.service_text
    assert "--max-iterations 1" in unit.service_text
    assert "--limit 1000" in unit.service_text
    assert "--once" not in unit.service_text
    assert "Restart=always" in unit.service_text
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
    )

    assert "ExecStart=/usr/bin/python3 -m TeeBotus.admin codex-history watch" in unit.service_text
    assert "--instance=Depressionsbot" in unit.service_text
    assert f"--sessions-root {tmp_path / 'sessions'}" in unit.service_text
    assert f"--sessions-root {tmp_path / 'agents' / 'a1' / '.codex' / 'sessions'}" in unit.service_text
    assert "--limit 250" in unit.service_text
    assert "RestartSec=30s" in unit.service_text


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
