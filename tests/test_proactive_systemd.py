from __future__ import annotations

from pathlib import Path

from TeeBotus.proactive_systemd import main, render_proactive_systemd_unit


def test_render_proactive_systemd_unit_defaults_to_llm_planner(tmp_path) -> None:
    unit = render_proactive_systemd_unit(
        repo_root=tmp_path,
        instances_dir="instances",
        instance_name="Depressionsbot",
        interval="15min",
    )

    assert unit.service_name == "teebotus-proactive-depressionsbot.service"
    assert unit.timer_name == "teebotus-proactive-depressionsbot.timer"
    assert f"WorkingDirectory={tmp_path.resolve()}" in unit.service_text
    assert "EnvironmentFile=-" in unit.service_text
    assert "teebotus-proactive" in unit.service_text
    assert "--dispatch --plan --llm-plan" in unit.service_text
    assert "--tool-plan" not in unit.service_text
    assert "OnUnitActiveSec=15min" in unit.timer_text
    assert "Persistent=true" in unit.timer_text


def test_render_proactive_systemd_unit_can_disable_llm_plan(tmp_path) -> None:
    unit = render_proactive_systemd_unit(
        repo_root=tmp_path,
        instances_dir=str(tmp_path / "instances"),
        instance_name="Depressionsbot",
        interval="1h",
        llm_plan=False,
    )

    assert "--dispatch --plan" in unit.service_text
    assert "--llm-plan" not in unit.service_text
    assert f"--instances-dir {tmp_path / 'instances'}" in unit.service_text
    assert "OnUnitActiveSec=1h" in unit.timer_text


def test_render_proactive_systemd_unit_can_enable_tool_plan(tmp_path) -> None:
    unit = render_proactive_systemd_unit(
        repo_root=tmp_path,
        instances_dir=str(tmp_path / "instances"),
        instance_name="Depressionsbot",
        interval="30min",
        llm_plan=False,
        tool_plan=True,
    )

    assert "--dispatch --plan --tool-plan" in unit.service_text
    assert "--llm-plan" not in unit.service_text
    assert "OnUnitActiveSec=30min" in unit.timer_text


def test_render_proactive_systemd_unit_rejects_multiple_planners(tmp_path) -> None:
    try:
        render_proactive_systemd_unit(
            repo_root=tmp_path,
            instances_dir="instances",
            instance_name="Depressionsbot",
            interval="15min",
            llm_plan=True,
            tool_plan=True,
        )
    except ValueError as exc:
        assert "mutually exclusive" in str(exc)
    else:
        raise AssertionError("expected mutually exclusive planner options to fail")


def test_proactive_systemd_print_mode_outputs_both_units(tmp_path, capsys) -> None:
    result = main(["--repo-root", str(tmp_path), "--instance", "Depressionsbot", "--print"])

    captured = capsys.readouterr()
    assert result == 0
    assert "# teebotus-proactive-depressionsbot.service" in captured.out
    assert "# teebotus-proactive-depressionsbot.timer" in captured.out
    assert "--dispatch --plan --llm-plan" in captured.out


def test_proactive_systemd_print_mode_can_disable_llm_plan(tmp_path, capsys) -> None:
    result = main(["--repo-root", str(tmp_path), "--instance", "Depressionsbot", "--no-llm-plan", "--print"])

    captured = capsys.readouterr()
    assert result == 0
    assert "--dispatch --plan" in captured.out
    assert "--llm-plan" not in captured.out


def test_proactive_systemd_print_mode_can_enable_tool_plan(tmp_path, capsys) -> None:
    result = main(["--repo-root", str(tmp_path), "--instance", "Depressionsbot", "--no-llm-plan", "--tool-plan", "--print"])

    captured = capsys.readouterr()
    assert result == 0
    assert "--dispatch --plan --tool-plan" in captured.out
