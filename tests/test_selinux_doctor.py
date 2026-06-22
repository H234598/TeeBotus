from __future__ import annotations

import subprocess
from collections.abc import Sequence

from TeeBotus.selinux_doctor import collect_selinux_report, main, render_selinux_report


def completed(command: Sequence[str], returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(list(command), returncode, stdout, stderr)


def test_selinux_doctor_detects_panic_systemd_modules_without_removing() -> None:
    calls: list[tuple[str, ...]] = []

    def runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        calls.append(tuple(command))
        if tuple(command) == ("getenforce",):
            return completed(command, stdout="Enforcing\n")
        if tuple(command) == ("semodule", "-l"):
            return completed(command, stdout="systemd 1.0\nmy-systemd 1.0\nlocal_systemd_fix 1.0\nteebotus 1.0\n")
        if tuple(command[:3]) == ("systemctl", "--user", "show"):
            return completed(command, stdout="LoadState=loaded\nActiveState=active\nSubState=running\n")
        raise AssertionError(f"unexpected command {command}")

    report = collect_selinux_report(remove_suspect=True, runner=runner)

    assert report.ok is True
    assert [module.name for module in report.suspect_modules] == ["my-systemd", "local_systemd_fix"]
    assert report.removed_modules == ()
    assert tuple(command for command in calls if command[:2] == ("semodule", "-r")) == ()
    rendered = render_selinux_report(report)
    assert "Verdaechtige Panic-Module" in rendered
    assert "Dry-run only" in rendered


def test_selinux_doctor_apply_removes_only_selected_suspect_modules() -> None:
    calls: list[tuple[str, ...]] = []

    def runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        calls.append(tuple(command))
        if tuple(command) == ("getenforce",):
            return completed(command, stdout="Enforcing\n")
        if tuple(command) == ("semodule", "-l"):
            return completed(command, stdout="systemd 1.0\nmy-systemd 1.0\nother_systemd 1.0\n")
        if tuple(command[:3]) == ("systemctl", "--user", "show"):
            return completed(command, stdout="LoadState=loaded\nActiveState=active\nSubState=running\n")
        if tuple(command) == ("semodule", "-r", "my-systemd"):
            return completed(command, stdout="")
        raise AssertionError(f"unexpected command {command}")

    report = collect_selinux_report(remove_suspect=True, apply=True, runner=runner)

    assert report.removed_modules == ("my-systemd",)
    assert report.failed_removals == ()
    assert ("semodule", "-r", "other_systemd") not in calls


def test_selinux_doctor_explicit_module_removal_requires_apply() -> None:
    calls: list[tuple[str, ...]] = []

    def runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        calls.append(tuple(command))
        if tuple(command) == ("getenforce",):
            return completed(command, stdout="Enforcing\n")
        if tuple(command) == ("semodule", "-l"):
            return completed(command, stdout="custom_policy 1.0\n")
        if tuple(command[:3]) == ("systemctl", "--user", "show"):
            return completed(command, stdout="LoadState=not-found\nActiveState=inactive\nSubState=dead\n")
        if tuple(command[:2]) == ("systemctl", "show"):
            return completed(command, stdout="LoadState=not-found\nActiveState=inactive\nSubState=dead\n")
        return completed(command)

    report = collect_selinux_report(explicit_modules=("custom_policy",), apply=False, runner=runner)

    assert report.removed_modules == ()
    assert ("semodule", "-r", "custom_policy") not in calls
    assert any("Dry-run only" in note for note in report.notes)


def test_selinux_doctor_reports_permission_denied_module_store() -> None:
    def runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        if tuple(command) == ("getenforce",):
            return completed(command, stdout="Enforcing\n")
        if tuple(command) == ("semodule", "-l"):
            return completed(command, returncode=1, stderr="Permission denied\n")
        if tuple(command[:3]) == ("systemctl", "--user", "show"):
            return completed(command, stdout="LoadState=not-found\nActiveState=inactive\nSubState=dead\n")
        if tuple(command[:2]) == ("systemctl", "show"):
            return completed(command, stdout="LoadState=not-found\nActiveState=inactive\nSubState=dead\n")
        raise AssertionError(f"unexpected command {command}")

    report = collect_selinux_report(runner=runner)

    assert report.ok is False
    assert report.modules_readable is False
    assert report.suspect_modules == ()
    assert any("rerun via sudo" in note for note in report.notes)


def test_selinux_doctor_auto_detects_user_unit_before_system_unit() -> None:
    calls: list[tuple[str, ...]] = []

    def runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        calls.append(tuple(command))
        if tuple(command) == ("getenforce",):
            return completed(command, stdout="Enforcing\n")
        if tuple(command) == ("semodule", "-l"):
            return completed(command, stdout="")
        if tuple(command[:3]) == ("systemctl", "--user", "show"):
            return completed(command, stdout="LoadState=loaded\nActiveState=active\nSubState=running\n")
        raise AssertionError(f"unexpected command {command}")

    report = collect_selinux_report(runner=runner)

    assert report.unit_present is True
    assert report.unit_scope == "user"
    assert report.unit_active == "active/running"
    assert not any(command[:2] == ("systemctl", "show") for command in calls)
    assert "Collector-Unit geladen: ja (user)" in render_selinux_report(report)


def test_selinux_doctor_can_check_system_unit_explicitly() -> None:
    calls: list[tuple[str, ...]] = []

    def runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        calls.append(tuple(command))
        if tuple(command) == ("getenforce",):
            return completed(command, stdout="Enforcing\n")
        if tuple(command) == ("semodule", "-l"):
            return completed(command, stdout="")
        if tuple(command[:2]) == ("systemctl", "show"):
            return completed(command, stdout="LoadState=loaded\nActiveState=inactive\nSubState=dead\n")
        raise AssertionError(f"unexpected command {command}")

    report = collect_selinux_report(unit_scope="system", runner=runner)

    assert report.unit_present is True
    assert report.unit_scope == "system"
    assert report.unit_active == "inactive/dead"
    assert not any(command[:3] == ("systemctl", "--user", "show") for command in calls)


def test_selinux_doctor_cli_json_outputs_report(monkeypatch, capsys) -> None:
    def fake_report(**_kwargs):
        return collect_selinux_report(
            runner=lambda command: completed(
                command,
                stdout=(
                    "Enforcing\n"
                    if tuple(command) == ("getenforce",)
                    else "my-systemd 1.0\n"
                    if tuple(command) == ("semodule", "-l")
                    else "LoadState=loaded\nActiveState=active\nSubState=running\n"
                ),
            )
        )

    monkeypatch.setattr("TeeBotus.selinux_doctor.collect_selinux_report", fake_report)

    result = main(["--format", "json"])

    assert result == 0
    assert '"name": "my-systemd"' in capsys.readouterr().out
