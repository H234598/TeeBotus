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
    assert by_label["runtime-status"].validate_runtime_status is True
    for channel in ("telegram", "signal", "matrix"):
        assert by_label[f"runtime-status-{channel}"].argv == (
            "python-test",
            "-m",
            "TeeBotus",
            "--runtime-status",
            "--channels",
            channel,
        )
        assert by_label[f"runtime-status-{channel}"].validate_runtime_status is True
    assert "--all" not in " ".join(" ".join(command.argv) for command in commands)
    pytest_args = by_label["plan2-pytest"].argv
    expected_plan2_tests = check_plan2_acceptance._expand_test_patterns(check_plan2_acceptance.PLAN2_TEST_PATTERNS)
    assert pytest_args[:3] == ("python-test", "-m", "pytest")
    assert pytest_args[3] == "-q"
    assert set(pytest_args[4:]) == set(expected_plan2_tests)
    assert "tests/test_proactive_backends.py" in pytest_args
    assert "tests/test_proactive_cli.py" in pytest_args
    assert "tests/test_readme_plan2_docs.py" in pytest_args
    assert "tests/test_secret_hygiene.py" in pytest_args
    assert by_label["bibliothekar-status"].argv == ("python-test", "-m", "TeeBotus.bibliothekar", "status")
    assert by_label["bibliothekar-dry-run"].argv[-4:] == ("index", "--source", "tests/fixtures/books", "--dry-run")
    assert by_label["bibliothekar-fixture-query"].argv[-4:] == ("tests/fixtures/books", "Testfrage", "--top-k", "3")
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
    assert by_label["plan2-optional-extras"].argv == ("python-test", "scripts/check_plan2_optional_extras.py", "--require-installed")
    assert by_label["qdrant-systemd-print"].argv == ("python-test", "-m", "TeeBotus.qdrant_systemd", "--print")
    assert by_label["teebotus-systemd-print"].argv == ("python-test", "-m", "TeeBotus.systemd", "--print")
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
    assert not any(label.startswith("qdrant-live") for label in labels)


def test_plan2_acceptance_can_include_nonfatal_qdrant_live_probe(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(check_plan2_acceptance.shutil, "which", lambda name: "/usr/bin/curl" if name == "curl" else None)

    commands = check_plan2_acceptance.build_acceptance_commands(
        python="python-test",
        benchmark_output=tmp_path / "bench.md",
        benchmark_json_output=tmp_path / "bench.json",
        include_qdrant_live=True,
    )
    by_label = {command.label: command for command in commands}

    assert by_label["qdrant-live-collections"].argv == ("/usr/bin/curl", "-fsS", "http://127.0.0.1:6333/collections")
    assert by_label["qdrant-live-collections"].nonfatal is True


def test_plan2_acceptance_runner_stops_on_fatal_failure(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(argv, cwd, check, **kwargs):  # noqa: ANN001, ARG001
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

    def fake_run(argv, cwd, check, **kwargs):  # noqa: ANN001, ARG001
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


def test_plan2_acceptance_runner_fails_on_broken_runtime_status(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(argv, cwd, check, **kwargs):  # noqa: ANN001, ARG001
        calls.append(tuple(argv))
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=(
                "TeeBotus runtime configuration resolves.\n"
                "account_memory=Demo/abc status=broken error=recent_ids missing entries: mem_missing\n"
                "account_memory_recovery=Demo status=needed command=\"python3 -m TeeBotus.admin memory-recovery\"\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(check_plan2_acceptance.subprocess, "run", fake_run)

    result = check_plan2_acceptance.run_acceptance_commands(
        [
            check_plan2_acceptance.AcceptanceCommand(
                "runtime-status",
                ("python-test", "-m", "TeeBotus", "--runtime-status"),
                validate_runtime_status=True,
            ),
            check_plan2_acceptance.AcceptanceCommand("later", ("python-test", "-m", "pytest")),
        ]
    )

    assert result == 1
    assert calls == [("python-test", "-m", "TeeBotus", "--runtime-status")]


def test_runtime_status_broken_lines_ignores_non_broken_statuses() -> None:
    output = "\n".join(
        [
            "llm=Demo/telegram:1 provider=openai model=gpt status=configured",
            "signal_service=Demo/signal:1 target=127.0.0.1:8080 status=reachable",
            "account_memory=Demo/abc status=ok",
        ]
    )

    assert check_plan2_acceptance._runtime_status_broken_lines(output) == []
