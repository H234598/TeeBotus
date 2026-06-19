from __future__ import annotations

import subprocess
from pathlib import Path

import scripts.setup_python313_runtime as setup_python313


def test_python313_runtime_setup_reports_missing_python(monkeypatch, capsys) -> None:
    monkeypatch.setattr(setup_python313.shutil, "which", lambda _name: None)

    result = setup_python313.main([])

    captured = capsys.readouterr()
    assert result == 2
    assert "sudo dnf install -y python3.13 python3.13-devel" in captured.err


def test_python313_runtime_setup_rejects_wrong_python(monkeypatch, capsys) -> None:
    monkeypatch.setattr(setup_python313.shutil, "which", lambda _name: "/usr/bin/python3")

    def runner(command, **_kwargs):
        assert command[:2] == ["/usr/bin/python3", "-c"]
        return subprocess.CompletedProcess(command, 0, stdout="3.14.5\n", stderr="")

    result = setup_python313.main([], runner=runner)

    captured = capsys.readouterr()
    assert result == 2
    assert "must be Python 3.13" in captured.err


def test_python313_runtime_setup_dry_run_prints_safe_commands(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(setup_python313.shutil, "which", lambda _name: "/usr/bin/python3.13")

    def runner(command, **_kwargs):
        assert command[:2] == ["/usr/bin/python3.13", "-c"]
        return subprocess.CompletedProcess(command, 0, stdout="3.13.13\n", stderr="")

    result = setup_python313.main(["--dry-run", "--venv", str(tmp_path / "venv")], runner=runner)

    captured = capsys.readouterr()
    assert result == 0
    assert f"/usr/bin/python3.13 -m venv {tmp_path / 'venv'}" in captured.out
    assert f"{tmp_path / 'venv' / 'bin' / 'python'} -m pip install --upgrade pip" in captured.out
    assert f"{tmp_path / 'venv' / 'bin' / 'python'} -m pip install --upgrade packaging" in captured.out
    assert "--python-only --no-user --dry-run" in captured.out
    assert "python313_runtime=ready" in captured.out


def test_python313_runtime_setup_rejects_enable_without_install(monkeypatch, capsys) -> None:
    monkeypatch.setattr(setup_python313.shutil, "which", lambda _name: "/usr/bin/python3.13")

    def runner(command, **_kwargs):
        assert command[:2] == ["/usr/bin/python3.13", "-c"]
        return subprocess.CompletedProcess(command, 0, stdout="3.13.13\n", stderr="")

    result = setup_python313.main(["--enable-systemd"], runner=runner)

    captured = capsys.readouterr()
    assert result == 2
    assert "--enable-systemd requires --install-systemd" in captured.err


def test_python313_runtime_setup_dry_run_can_print_systemd_install(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(setup_python313.shutil, "which", lambda _name: "/usr/bin/python3.13")

    def runner(command, **_kwargs):
        assert command[:2] == ["/usr/bin/python3.13", "-c"]
        return subprocess.CompletedProcess(command, 0, stdout="3.13.13\n", stderr="")

    result = setup_python313.main(
        [
            "--dry-run",
            "--venv",
            str(tmp_path / "venv"),
            "--install-systemd",
            "--enable-systemd",
            "--channels",
            "telegram,signal",
        ],
        runner=runner,
    )

    captured = capsys.readouterr()
    assert result == 0
    assert "-m TeeBotus.systemd" in captured.out
    assert f"--python {tmp_path / 'venv' / 'bin' / 'python'}" in captured.out
    assert "--channels telegram,signal" in captured.out
    assert "--enable" in captured.out


def test_python313_runtime_setup_runs_expected_commands(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(setup_python313.shutil, "which", lambda _name: "/usr/bin/python3.13")
    calls: list[list[str]] = []

    def runner(command, **_kwargs):
        calls.append(list(command))
        if command[:2] == ["/usr/bin/python3.13", "-c"]:
            return subprocess.CompletedProcess(command, 0, stdout="3.13.13\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    result = setup_python313.main(["--venv", str(tmp_path / "venv")], runner=runner)

    assert result == 0
    assert calls[1] == ["/usr/bin/python3.13", "-m", "venv", str(tmp_path / "venv")]
    assert calls[2][:5] == [str(tmp_path / "venv" / "bin" / "python"), "-m", "pip", "install", "--upgrade"]
    assert calls[3] == [str(tmp_path / "venv" / "bin" / "python"), "-m", "pip", "install", "--upgrade", "packaging"]
    assert calls[4][:5] == [str(tmp_path / "venv" / "bin" / "python"), "-m", "pip", "install", "--no-deps"]
    assert calls[5][:2] == [str(tmp_path / "venv" / "bin" / "python"), str(setup_python313.REPO_ROOT / "scripts" / "install_adapter_deps.py")]


def test_python313_runtime_setup_runs_systemd_install_after_dependency_setup(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(setup_python313.shutil, "which", lambda _name: "/usr/bin/python3.13")
    calls: list[list[str]] = []

    def runner(command, **_kwargs):
        calls.append(list(command))
        if command[:2] == ["/usr/bin/python3.13", "-c"]:
            return subprocess.CompletedProcess(command, 0, stdout="3.13.13\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    result = setup_python313.main(
        [
            "--venv",
            str(tmp_path / "venv"),
            "--install-systemd",
            "--service-name",
            "teebotus-test.service",
            "--channels",
            "telegram,signal",
        ],
        runner=runner,
    )

    assert result == 0
    assert calls[-1] == [
        str(tmp_path / "venv" / "bin" / "python"),
        "-m",
        "TeeBotus.systemd",
        "--repo-root",
        str(setup_python313.REPO_ROOT),
        "--python",
        str(tmp_path / "venv" / "bin" / "python"),
        "--service-name",
        "teebotus-test.service",
        "--channels",
        "telegram,signal",
    ]
