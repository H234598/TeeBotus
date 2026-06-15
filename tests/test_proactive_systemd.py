from __future__ import annotations

from pathlib import Path

from TeeBotus.proactive_systemd import main, render_proactive_systemd_unit


def test_render_proactive_systemd_unit_defaults_to_local_planner(tmp_path) -> None:
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
    assert "--dry-run --plan" in unit.service_text
    assert "--llm-plan" not in unit.service_text
    assert "OnUnitActiveSec=15min" in unit.timer_text
    assert "Persistent=true" in unit.timer_text


def test_render_proactive_systemd_unit_can_enable_llm_plan(tmp_path) -> None:
    unit = render_proactive_systemd_unit(
        repo_root=tmp_path,
        instances_dir=str(tmp_path / "instances"),
        instance_name="Depressionsbot",
        interval="1h",
        llm_plan=True,
    )

    assert "--dry-run --plan --llm-plan" in unit.service_text
    assert f"--instances-dir {tmp_path / 'instances'}" in unit.service_text
    assert "OnUnitActiveSec=1h" in unit.timer_text


def test_proactive_systemd_print_mode_outputs_both_units(tmp_path, capsys) -> None:
    result = main(["--repo-root", str(tmp_path), "--instance", "Depressionsbot", "--print"])

    captured = capsys.readouterr()
    assert result == 0
    assert "# teebotus-proactive-depressionsbot.service" in captured.out
    assert "# teebotus-proactive-depressionsbot.timer" in captured.out
    assert "--dry-run --plan" in captured.out
