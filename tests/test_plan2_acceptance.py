from __future__ import annotations

import subprocess
from pathlib import Path

from scripts import check_plan2_acceptance


def test_plan2_acceptance_commands_cover_non_invasive_plan2_paths(tmp_path: Path) -> None:
    commands = check_plan2_acceptance.build_acceptance_commands(
        python="python-test",
        benchmark_output=tmp_path / "bench.md",
        benchmark_json_output=tmp_path / "bench.json",
        entries=3,
        iterations=2,
        include_audit=True,
    )

    by_label = {command.label: command for command in commands}

    assert by_label["version"].argv == ("python-test", "-m", "TeeBotus", "--version")
    assert by_label["runtime-status"].argv == (
        "python-test",
        "-m",
        "TeeBotus",
        "--runtime-status",
        "--channels",
        "telegram,signal,matrix",
    )
    for channel in ("telegram", "signal", "matrix"):
        assert by_label[f"runtime-status-{channel}"].argv == (
            "python-test",
            "-m",
            "TeeBotus",
            "--runtime-status",
            "--channels",
            channel,
        )
    assert "--all" not in " ".join(" ".join(command.argv) for command in commands)
    assert "tests/test_account_store.py" in by_label["plan2-pytest"].argv
    assert "tests/test_engine_identity_flows.py" in by_label["plan2-pytest"].argv
    assert "tests/test_instructions.py" in by_label["plan2-pytest"].argv
    assert "tests/test_matrix_runner.py" in by_label["plan2-pytest"].argv
    assert "tests/test_program_history.py" in by_label["plan2-pytest"].argv
    assert "tests/test_proactive_agent.py" in by_label["plan2-pytest"].argv
    assert "tests/test_proactive_systemd.py" in by_label["plan2-pytest"].argv
    assert "tests/test_runtime_config.py" in by_label["plan2-pytest"].argv
    assert "tests/test_runtime_maintenance.py" in by_label["plan2-pytest"].argv
    assert "tests/test_runtime_state.py" in by_label["plan2-pytest"].argv
    assert "tests/test_signal_runner.py" in by_label["plan2-pytest"].argv
    assert "tests/test_tts_dialect.py" in by_label["plan2-pytest"].argv
    assert "tests/test_weather_context.py" in by_label["plan2-pytest"].argv
    assert "tests/test_working_memory.py" in by_label["plan2-pytest"].argv
    assert "tests/test_openai_client.py" in by_label["plan2-pytest"].argv
    assert "tests/test_bibliothekar.py" in by_label["plan2-pytest"].argv
    assert "tests/test_bibliothekar_plan2.py" in by_label["plan2-pytest"].argv
    assert "tests/test_pyproject_metadata.py" in by_label["plan2-pytest"].argv
    assert "tests/test_reminder_intent.py" in by_label["plan2-pytest"].argv
    assert "tests/test_graphs_bibliothekar.py" in by_label["plan2-pytest"].argv
    assert "tests/test_youtube_parser_stats.py" in by_label["plan2-pytest"].argv
    assert "tests/test_youtube_parser_misses_report.py" in by_label["plan2-pytest"].argv
    assert "tests/test_memory_store_benchmark.py" in by_label["plan2-pytest"].argv
    assert "tests/test_plan2_acceptance.py" in by_label["plan2-pytest"].argv
    assert by_label["bibliothekar-dry-run"].argv[-4:] == ("index", "--source", "tests/fixtures/books", "--dry-run")
    assert by_label["bibliothekar-fixture-query"].argv[-4:] == ("tests/fixtures/books", "Therapie Schlaf", "--top-k", "2")
    assert by_label["plan2-quick-benchmarks"].argv[-9:] == (
        "--quick",
        "--entries",
        "3",
        "--iterations",
        "2",
        "--output",
        str(tmp_path / "bench.md"),
        "--json-output",
        str(tmp_path / "bench.json"),
    )
    assert by_label["adapter-deps"].argv == ("python-test", "scripts/check_adapter_deps.py")
    assert any(command.label.startswith("pip-audit") and command.nonfatal for command in commands)


def test_plan2_acceptance_can_skip_live_optional_checks(tmp_path: Path) -> None:
    commands = check_plan2_acceptance.build_acceptance_commands(
        python="python-test",
        benchmark_output=tmp_path / "bench.md",
        benchmark_json_output=tmp_path / "bench.json",
        skip_runtime_status=True,
        skip_adapter_deps=True,
    )

    labels = {command.label for command in commands}

    assert "runtime-status" not in labels
    assert "runtime-status-telegram" not in labels
    assert "runtime-status-signal" not in labels
    assert "runtime-status-matrix" not in labels
    assert "adapter-deps" not in labels
    assert "plan2-pytest" in labels


def test_plan2_acceptance_runner_stops_on_fatal_failure(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(argv, cwd, check):  # noqa: ANN001
        calls.append(tuple(argv))
        return subprocess.CompletedProcess(argv, 7)

    monkeypatch.setattr(check_plan2_acceptance.subprocess, "run", fake_run)

    result = check_plan2_acceptance.run_acceptance_commands(
        [
            check_plan2_acceptance.AcceptanceCommand("fatal", ("python-test", "-m", "pytest")),
            check_plan2_acceptance.AcceptanceCommand("later", ("python-test", "-m", "TeeBotus")),
        ]
    )

    assert result == 7
    assert calls == [("python-test", "-m", "pytest")]


def test_plan2_acceptance_runner_continues_after_nonfatal_failure(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(argv, cwd, check):  # noqa: ANN001
        calls.append(tuple(argv))
        code = 3 if tuple(argv) == ("pip-audit",) else 0
        return subprocess.CompletedProcess(argv, code)

    monkeypatch.setattr(check_plan2_acceptance.subprocess, "run", fake_run)

    result = check_plan2_acceptance.run_acceptance_commands(
        [
            check_plan2_acceptance.AcceptanceCommand("audit", ("pip-audit",), nonfatal=True),
            check_plan2_acceptance.AcceptanceCommand("later", ("python-test", "-m", "TeeBotus")),
        ]
    )

    assert result == 0
    assert calls == [("pip-audit",), ("python-test", "-m", "TeeBotus")]
