from __future__ import annotations

import subprocess
from pathlib import Path

from TeeBotus.systemd import main, render_teebotus_systemd_unit


def test_render_teebotus_systemd_unit_matches_plan2_shape(tmp_path: Path) -> None:
    unit = render_teebotus_systemd_unit(repo_root=tmp_path)

    assert unit.service_name == "teebotus.service"
    assert "Description=TeeBotus multi-channel bot" in unit.service_text
    assert f"WorkingDirectory={tmp_path.resolve()}" in unit.service_text
    assert f"EnvironmentFile=-{tmp_path.resolve() / '.env'}" in unit.service_text
    assert f"ExecStartPre=python3 -m TeeBotus.systemd --check-env-file {tmp_path.resolve() / '.env'}" in unit.service_text
    assert "ExecStart=python3 -m TeeBotus --all --channels telegram,signal,matrix" in unit.service_text
    assert "Restart=on-failure" in unit.service_text
    assert "RestartSec=10" in unit.service_text
    assert "NoNewPrivileges=true" in unit.service_text
    assert "PrivateTmp=true" in unit.service_text
    assert "WantedBy=default.target" in unit.service_text


def test_render_teebotus_systemd_unit_uses_venv_python_when_present(tmp_path: Path) -> None:
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!/bin/sh\n", encoding="utf-8")

    unit = render_teebotus_systemd_unit(repo_root=tmp_path)

    assert f"ExecStart={venv_python.resolve()} -m TeeBotus --all --channels telegram,signal,matrix" in unit.service_text
    assert f"ExecStartPre={venv_python.resolve()} -m TeeBotus.systemd --check-env-file {tmp_path.resolve() / '.env'}" in unit.service_text


def test_render_teebotus_systemd_unit_keeps_bare_python_executable_on_path(tmp_path: Path) -> None:
    unit = render_teebotus_systemd_unit(repo_root=tmp_path, python_executable="python3")

    assert "ExecStart=python3 -m TeeBotus --all --channels telegram,signal,matrix" in unit.service_text
    assert f"ExecStart={tmp_path.resolve() / 'python3'}" not in unit.service_text
    assert "ExecStartPre=python3 -m TeeBotus.systemd" in unit.service_text


def test_render_teebotus_systemd_unit_resolves_relative_python_paths(tmp_path: Path) -> None:
    unit = render_teebotus_systemd_unit(repo_root=tmp_path, python_executable="bin/python")

    assert f"ExecStart={tmp_path.resolve() / 'bin' / 'python'} -m TeeBotus" in unit.service_text
    assert f"ExecStartPre={tmp_path.resolve() / 'bin' / 'python'} -m TeeBotus.systemd" in unit.service_text


def test_render_teebotus_systemd_unit_can_limit_channels_and_no_all(tmp_path: Path) -> None:
    unit = render_teebotus_systemd_unit(
        repo_root=tmp_path,
        python_executable="/usr/bin/python3",
        service_name="teebotus-demo",
        channels="telegram, signal",
        all_instances=False,
    )

    assert unit.service_name == "teebotus-demo.service"
    assert "ExecStart=/usr/bin/python3 -m TeeBotus --channels telegram,signal" in unit.service_text
    assert "--all" not in unit.service_text


def test_render_teebotus_systemd_unit_rejects_unknown_channel(tmp_path: Path) -> None:
    try:
        render_teebotus_systemd_unit(repo_root=tmp_path, channels="telegram,irc")
    except ValueError as exc:
        assert "unsupported TeeBotus channels" in str(exc)
    else:
        raise AssertionError("expected unknown channel to fail")


def test_render_teebotus_systemd_unit_rejects_control_characters(tmp_path: Path) -> None:
    cases = [
        {"repo_root": Path("/tmp/TeeBotus\nExecStart=/bin/false")},
        {"repo_root": tmp_path, "env_file": ".env\nExecStart=/bin/false"},
        {"repo_root": tmp_path, "python_executable": "python3\nExecStart=/bin/false"},
    ]
    for kwargs in cases:
        try:
            render_teebotus_systemd_unit(**kwargs)
        except ValueError as exc:
            assert "invalid control characters" in str(exc)
        else:
            raise AssertionError(f"expected control character rejection for {kwargs}")


def test_render_teebotus_systemd_unit_escapes_systemd_percent_specifiers(tmp_path: Path) -> None:
    repo_root = tmp_path / "TeeBotus%x%h"
    unit = render_teebotus_systemd_unit(
        repo_root=repo_root,
        python_executable="/usr/bin/python3%x",
        env_file=".env%h",
    )

    assert f"WorkingDirectory={repo_root.resolve()}".replace("%", "%%") in unit.service_text
    assert f"EnvironmentFile=-{repo_root.resolve() / '.env%h'}".replace("%", "%%") in unit.service_text
    assert "ExecStartPre=/usr/bin/python3%%x -m TeeBotus.systemd" in unit.service_text
    assert "ExecStart=/usr/bin/python3%%x -m TeeBotus --all --channels telegram,signal,matrix" in unit.service_text


def test_teebotus_systemd_print_mode_outputs_service(tmp_path: Path, capsys) -> None:
    result = main(["--repo-root", str(tmp_path), "--print"])

    captured = capsys.readouterr()
    assert result == 0
    assert "# teebotus.service" in captured.out
    assert "ExecStart=python3 -m TeeBotus --all --channels telegram,signal,matrix" in captured.out


def test_teebotus_systemd_cli_reports_invalid_render_options_without_traceback(tmp_path: Path, capsys) -> None:
    try:
        main(["--repo-root", str(tmp_path), "--channels", "telegram,irc", "--print"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected invalid channels to exit with argparse error")

    captured = capsys.readouterr()
    assert "unsupported TeeBotus channels" in captured.err
    assert "Traceback" not in captured.err


def test_teebotus_systemd_env_file_permission_check(tmp_path: Path, capsys) -> None:
    env_file = tmp_path / ".env"

    assert main(["--check-env-file", str(env_file)]) == 0

    env_file.write_text("OPENAI_API_KEY=test\n", encoding="utf-8")
    env_file.chmod(0o600)
    assert main(["--check-env-file", str(env_file)]) == 0

    env_file.chmod(0o644)
    assert main(["--check-env-file", str(env_file)]) == 1
    captured = capsys.readouterr()
    assert "mode=644 expected=600-or-stricter" in captured.err


def test_teebotus_systemd_enable_runs_user_systemctl(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(command, check=False, **_kwargs):
        calls.append(list(command))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("TeeBotus.systemd.Path.home", lambda: tmp_path)
    monkeypatch.setattr("TeeBotus.systemd.subprocess.run", fake_run)

    result = main(["--repo-root", str(tmp_path), "--enable"])

    assert result == 0
    assert (tmp_path / ".config" / "systemd" / "user" / "teebotus.service").exists()
    assert calls == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", "teebotus.service"],
    ]
