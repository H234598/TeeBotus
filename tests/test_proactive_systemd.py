from __future__ import annotations

from pathlib import Path

from TeeBotus.proactive_systemd import main, render_proactive_systemd_unit


def test_render_proactive_systemd_unit_defaults_to_tool_planner(tmp_path) -> None:
    unit = render_proactive_systemd_unit(
        repo_root=tmp_path,
        instances_dir="instances",
        instance_name="Depressionsbot",
        interval="5min",
    )

    assert unit.service_name == "teebotus-proactive-depressionsbot.service"
    assert unit.timer_name == "teebotus-proactive-depressionsbot.timer"
    assert f"WorkingDirectory={tmp_path.resolve()}" in unit.service_text
    assert "EnvironmentFile=-" in unit.service_text
    assert "teebotus-proactive" in unit.service_text
    assert "--dispatch --plan --tool-plan" in unit.service_text
    assert "--llm-plan" not in unit.service_text
    assert "OnUnitActiveSec=5min" in unit.timer_text
    assert "Persistent=true" in unit.timer_text


def test_render_proactive_systemd_unit_can_disable_tool_plan(tmp_path) -> None:
    unit = render_proactive_systemd_unit(
        repo_root=tmp_path,
        instances_dir=str(tmp_path / "instances"),
        instance_name="Depressionsbot",
        interval="1h",
        tool_plan=False,
    )

    assert "--dispatch --plan" in unit.service_text
    assert "--tool-plan" not in unit.service_text
    assert f"--instances-dir {tmp_path / 'instances'}" in unit.service_text
    assert "OnUnitActiveSec=1h" in unit.timer_text


def test_render_proactive_systemd_unit_can_enable_llm_plan(tmp_path) -> None:
    unit = render_proactive_systemd_unit(
        repo_root=tmp_path,
        instances_dir=str(tmp_path / "instances"),
        instance_name="Depressionsbot",
        interval="30min",
        llm_plan=True,
        tool_plan=False,
    )

    assert "--dispatch --plan --llm-plan" in unit.service_text
    assert "--tool-plan" not in unit.service_text
    assert "OnUnitActiveSec=30min" in unit.timer_text


def test_render_proactive_systemd_unit_rejects_multiple_planners(tmp_path) -> None:
    try:
        render_proactive_systemd_unit(
            repo_root=tmp_path,
            instances_dir="instances",
            instance_name="Depressionsbot",
            interval="5min",
            tool_plan=True,
            llm_plan=True,
        )
    except ValueError as exc:
        assert "mutually exclusive" in str(exc)
    else:
        raise AssertionError("expected mutually exclusive planner options to fail")


def test_proactive_systemd_print_mode_outputs_both_units(tmp_path, capsys) -> None:
    instance_dir = tmp_path / "instances" / "Depressionsbot"
    instance_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text("## Proactive\n- model_planner: tool\n", encoding="utf-8")

    result = main(["--repo-root", str(tmp_path), "--instance", "Depressionsbot", "--print"])

    captured = capsys.readouterr()
    assert result == 0
    assert "# teebotus-proactive-depressionsbot.service" in captured.out
    assert "# teebotus-proactive-depressionsbot.timer" in captured.out
    assert "--dispatch --plan --tool-plan" in captured.out


def test_proactive_systemd_print_mode_reads_llm_planner_from_bot_verhalten(tmp_path, capsys) -> None:
    instance_dir = tmp_path / "instances" / "Depressionsbot"
    instance_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text("## Proactive\n- model_planner: llm\n", encoding="utf-8")

    result = main(["--repo-root", str(tmp_path), "--instance", "Depressionsbot", "--print"])

    captured = capsys.readouterr()
    assert result == 0
    assert "--dispatch --plan --llm-plan" in captured.out
    assert "--tool-plan" not in captured.out


def test_proactive_systemd_print_mode_can_disable_model_plan(tmp_path, capsys) -> None:
    result = main(["--repo-root", str(tmp_path), "--instance", "Depressionsbot", "--no-model-plan", "--print"])

    captured = capsys.readouterr()
    assert result == 0
    assert "--dispatch --plan" in captured.out
    assert "--tool-plan" not in captured.out
    assert "--llm-plan" not in captured.out


def test_proactive_systemd_print_mode_can_enable_llm_plan(tmp_path, capsys) -> None:
    instance_dir = tmp_path / "instances" / "Depressionsbot"
    instance_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text("## Proactive\n- model_planner: tool\n", encoding="utf-8")

    result = main(["--repo-root", str(tmp_path), "--instance", "Depressionsbot", "--llm-plan", "--print"])

    captured = capsys.readouterr()
    assert result == 0
    assert "--dispatch --plan --llm-plan" in captured.out
    assert "--tool-plan" not in captured.out
