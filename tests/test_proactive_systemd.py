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
    assert "ExecStart=python3 -m TeeBotus.proactive" in unit.service_text
    assert ".local/bin/teebotus-proactive" not in unit.service_text
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


def test_render_proactive_systemd_unit_rejects_control_characters(tmp_path) -> None:
    base = {
        "repo_root": tmp_path,
        "instances_dir": "instances",
        "instance_name": "Depressionsbot",
        "interval": "5min",
    }
    cases = [
        {**base, "repo_root": Path("/tmp/TeeBotus\nExecStart=/bin/false")},
        {**base, "instances_dir": "instances\nExecStart=/bin/false"},
        {**base, "instance_name": "Depressionsbot\nExecStart=/bin/false"},
    ]
    for kwargs in cases:
        try:
            render_proactive_systemd_unit(**kwargs)
        except ValueError as exc:
            assert "invalid control characters" in str(exc)
        else:
            raise AssertionError(f"expected control character rejection for {kwargs}")


def test_render_proactive_systemd_unit_rejects_instance_path_segments(tmp_path) -> None:
    base = {
        "repo_root": tmp_path,
        "instances_dir": "instances",
        "interval": "5min",
    }
    for instance_name in ("../outside", "nested/Depressionsbot", r"nested\\Depressionsbot", ".", "..", ""):
        try:
            render_proactive_systemd_unit(**base, instance_name=instance_name)
        except ValueError as exc:
            assert "instance name" in str(exc)
        else:
            raise AssertionError(f"expected instance path segment rejection for {instance_name!r}")


def test_render_proactive_systemd_unit_uses_collision_resistant_unit_names(tmp_path) -> None:
    units = [
        render_proactive_systemd_unit(
            repo_root=tmp_path,
            instances_dir="instances",
            instance_name=instance_name,
            interval="5min",
        )
        for instance_name in ("A B", "A-B", "A_B", "A@B")
    ]

    service_names = [unit.service_name for unit in units]
    assert len(set(service_names)) == len(service_names)
    assert "teebotus-proactive-a-b.service" in service_names
    assert all(name.startswith("teebotus-proactive-a-b") for name in service_names)


def test_render_proactive_systemd_unit_rejects_slugless_instance_name(tmp_path) -> None:
    try:
        render_proactive_systemd_unit(
            repo_root=tmp_path,
            instances_dir="instances",
            instance_name="!!!",
            interval="5min",
        )
    except ValueError as exc:
        assert "alphanumeric" in str(exc)
    else:
        raise AssertionError("expected slugless instance name to fail")


def test_proactive_systemd_rejects_instance_traversal_before_bot_verhalten_lookup(tmp_path, capsys) -> None:
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (outside_dir / "Bot_Verhalten.md").write_text("## Proactive\n- model_planner: llm\n", encoding="utf-8")
    (tmp_path / "instances").mkdir()

    try:
        main(["--repo-root", str(tmp_path), "--instances-dir", "instances", "--instance", "../outside", "--print"])
    except ValueError as exc:
        assert "single path segment" in str(exc)
    else:
        raise AssertionError("expected traversal instance to fail before reading Bot_Verhalten.md")
    captured = capsys.readouterr()
    assert "--llm-plan" not in captured.out


def test_render_proactive_systemd_unit_escapes_systemd_percent_specifiers(tmp_path) -> None:
    repo_root = tmp_path / "TeeBotus%x%h"
    unit = render_proactive_systemd_unit(
        repo_root=repo_root,
        instances_dir="instances%h",
        instance_name="Depressionsbot%h",
        interval="5min",
    )

    assert f"WorkingDirectory={repo_root.resolve()}".replace("%", "%%") in unit.service_text
    assert "Description=TeeBotus proactive agent cycle for Depressionsbot%%h" in unit.service_text
    assert f"--instances-dir {repo_root.resolve() / 'instances%h'}".replace("%", "%%") in unit.service_text
    assert "--instance Depressionsbot%%h" in unit.service_text
    assert "Description=Run TeeBotus proactive agent cycle for Depressionsbot%%h" in unit.timer_text


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
