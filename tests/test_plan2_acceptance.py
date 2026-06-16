from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts import check_plan2_acceptance


RANKING_RESULT_NAMES = {
    "account_memory": "account_memory_benchmark",
    "bibliothekar": "bibliothekar_benchmark",
    "langgraph_flows": "langgraph_flows_benchmark",
    "transcription_youtube": "transcription_youtube_benchmark",
}


def _valid_ranking(category: str) -> dict:
    name = RANKING_RESULT_NAMES.get(category, f"{category}_benchmark")
    return {
        "category": category,
        "fastest_stable": name,
        "candidates": [
            {
                "rank": 1,
                "name": name,
                "mode": "local",
                "throughput_ops_s": 100.0,
                "total_ms": 1.0,
                "errors": 0,
                "payload_bytes": 1,
                "index_bytes": 1,
                "note": "",
            }
        ],
        "skipped": [],
    }


def _valid_benchmark_payload() -> dict:
    return {
        "schema_version": 1,
        "quick": True,
        "include_live": False,
        "ok": True,
        "context": {
            "python": "3.14.0",
            "platform": "Linux-test",
            "machine": "x86_64",
            "cpu_count": 4,
            "dependencies": {"teebotus": {"version": "1.5.0", "status": "worktree"}},
        },
        "results": [
            {
                "name": f"{category}_benchmark",
                "category": category,
                "ok": True,
                "mode": "local",
                "iterations": 1,
                "total_ms": 1.0,
                "throughput_ops_s": 100.0,
                "errors": 0,
                "payload_bytes": 1,
                "index_bytes": 1,
                "details": {
                    "network_calls": 0,
                    "openai_calls": 0,
                    "provider_calls": 0,
                    "remote_calls": 0,
                    "llm_calls": 0,
                },
            }
            for category in sorted(check_plan2_acceptance.REQUIRED_BENCHMARK_CATEGORIES)
        ],
        "comparisons": {
            "stable_backend_rankings": [
                _valid_ranking(category)
                for category in sorted(check_plan2_acceptance.REQUIRED_BENCHMARK_RANKING_CATEGORIES)
            ]
        },
        "quality_gate": {
            "status": "ok",
            "ok": True,
            "checked_results": len(check_plan2_acceptance.REQUIRED_BENCHMARK_CATEGORIES),
            "error_count": 0,
            "errors": [],
        },
        "regression": {"status": "not_configured", "failed": False},
    }


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
    assert "tests/test_account_memory_migration.py" in pytest_args
    assert "tests/test_proactive_backends.py" in pytest_args
    assert "tests/test_proactive_cli.py" in pytest_args
    assert "tests/test_readme_plan2_docs.py" in pytest_args
    assert "tests/test_secret_hygiene.py" in pytest_args
    assert "tests/test_ci_workflow.py" in pytest_args
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
    assert by_label["plan2-quick-benchmarks"].validate_benchmark_artifacts is True
    assert by_label["adapter-deps"].argv == ("python-test", "scripts/check_adapter_deps.py")
    assert by_label["plan2-optional-extras"].argv == ("python-test", "scripts/check_plan2_optional_extras.py", "--require-installed")
    assert by_label["qdrant-systemd-print"].argv == ("python-test", "-m", "TeeBotus.qdrant_systemd", "--print")
    assert by_label["qdrant-systemd-print"].validate_systemd_unit is True
    assert by_label["teebotus-systemd-print"].argv == ("python-test", "-m", "TeeBotus.systemd", "--print")
    assert by_label["teebotus-systemd-print"].validate_systemd_unit is True
    assert "memory-recovery-legacy-json" not in by_label
    assert "legacy-import-preflight" not in by_label
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


def test_plan2_acceptance_can_include_legacy_memory_preflight(tmp_path: Path) -> None:
    legacy_dir = tmp_path / "instances.bak"
    commands = check_plan2_acceptance.build_acceptance_commands(
        python="python-test",
        benchmark_output=tmp_path / "bench.md",
        benchmark_json_output=tmp_path / "bench.json",
        legacy_instances_dir=legacy_dir,
        memory_recovery_output=tmp_path / "recovery.md",
        memory_recovery_json_output=tmp_path / "recovery.json",
        legacy_import_output=tmp_path / "import.md",
        legacy_import_json_output=tmp_path / "import.json",
    )

    by_label = {command.label: command for command in commands}

    assert by_label["memory-recovery-legacy-json"].argv == (
        "python-test",
        "-m",
        "TeeBotus.admin",
        "memory-recovery",
        "--instances-dir",
        "instances",
        "--legacy-instances-dir",
        str(legacy_dir),
        "--format",
        "json",
        "--output",
        str(tmp_path / "recovery.json"),
    )
    assert by_label["memory-recovery-legacy-text"].argv == (
        "python-test",
        "-m",
        "TeeBotus.admin",
        "memory-recovery",
        "--instances-dir",
        "instances",
        "--legacy-instances-dir",
        str(legacy_dir),
        "--output",
        str(tmp_path / "recovery.md"),
    )
    assert by_label["legacy-import-preflight"].argv == (
        "python-test",
        "scripts/import_legacy_user_memory.py",
        "--legacy-instances-dir",
        str(legacy_dir),
        "--target-instances-dir",
        "instances",
        "--replace-unreadable-account-metadata",
        "--json-output",
        str(tmp_path / "import.json"),
        "--markdown-output",
        str(tmp_path / "import.md"),
    )
    assert by_label["memory-recovery-legacy-json"].validate_secret_artifacts is True
    assert by_label["memory-recovery-legacy-text"].validate_secret_artifacts is True
    assert by_label["legacy-import-preflight"].validate_secret_artifacts is True


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


def test_plan2_acceptance_runner_validates_benchmark_artifacts(tmp_path: Path, monkeypatch) -> None:
    markdown_path = tmp_path / "bench.md"
    json_path = tmp_path / "bench.json"
    calls: list[tuple[str, ...]] = []

    def fake_run(argv, cwd, check, **kwargs):  # noqa: ANN001, ARG001
        calls.append(tuple(argv))
        markdown_path.write_text(
            "# TeeBotus Benchmarks\n\n## Results\n\nok\n\n## Regression Check\n\n- status: not_configured\n",
            encoding="utf-8",
        )
        json_path.write_text(
            json.dumps(_valid_benchmark_payload()),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(check_plan2_acceptance.subprocess, "run", fake_run)

    result = check_plan2_acceptance.run_acceptance_commands(
        [
            check_plan2_acceptance.AcceptanceCommand(
                "plan2-quick-benchmarks",
                (
                    "python-test",
                    "scripts/run_benchmarks.py",
                    "--output",
                    str(markdown_path),
                    "--json-output",
                    str(json_path),
                ),
                validate_benchmark_artifacts=True,
            ),
            check_plan2_acceptance.AcceptanceCommand("later", ("python-test", "-m", "pytest")),
        ]
    )

    assert result == 0
    assert calls == [
        (
            "python-test",
            "scripts/run_benchmarks.py",
            "--output",
            str(markdown_path),
            "--json-output",
            str(json_path),
        ),
        ("python-test", "-m", "pytest"),
    ]


def test_plan2_acceptance_runner_fails_on_invalid_benchmark_artifacts(tmp_path: Path, monkeypatch) -> None:
    markdown_path = tmp_path / "bench.md"
    json_path = tmp_path / "bench.json"
    calls: list[tuple[str, ...]] = []

    def fake_run(argv, cwd, check, **kwargs):  # noqa: ANN001, ARG001
        calls.append(tuple(argv))
        markdown_path.write_text("not a benchmark report\n", encoding="utf-8")
        json_path.write_text(json.dumps({"schema_version": 1, "ok": True, "results": []}), encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(check_plan2_acceptance.subprocess, "run", fake_run)

    result = check_plan2_acceptance.run_acceptance_commands(
        [
            check_plan2_acceptance.AcceptanceCommand(
                "plan2-quick-benchmarks",
                (
                    "python-test",
                    "scripts/run_benchmarks.py",
                    "--output",
                    str(markdown_path),
                    "--json-output",
                    str(json_path),
                ),
                validate_benchmark_artifacts=True,
            ),
            check_plan2_acceptance.AcceptanceCommand("later", ("python-test", "-m", "pytest")),
        ]
    )

    assert result == 1
    assert calls == [
        (
            "python-test",
            "scripts/run_benchmarks.py",
            "--output",
            str(markdown_path),
            "--json-output",
            str(json_path),
        )
    ]


def test_plan2_acceptance_runner_validates_secret_artifacts(tmp_path: Path, monkeypatch) -> None:
    output_path = tmp_path / "recovery.md"
    calls: list[tuple[str, ...]] = []

    def fake_run(argv, cwd, check, **kwargs):  # noqa: ANN001, ARG001
        calls.append(tuple(argv))
        output_path.write_text("# Recovery\n\nok\n", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(check_plan2_acceptance.subprocess, "run", fake_run)

    result = check_plan2_acceptance.run_acceptance_commands(
        [
            check_plan2_acceptance.AcceptanceCommand(
                "memory-recovery-legacy-text",
                ("python-test", "-m", "TeeBotus.admin", "memory-recovery", "--output", str(output_path)),
                validate_secret_artifacts=True,
            ),
            check_plan2_acceptance.AcceptanceCommand("later", ("python-test", "-m", "pytest")),
        ]
    )

    assert result == 0
    assert calls == [
        ("python-test", "-m", "TeeBotus.admin", "memory-recovery", "--output", str(output_path)),
        ("python-test", "-m", "pytest"),
    ]


def test_plan2_acceptance_runner_fails_on_secret_artifact_leak(tmp_path: Path, monkeypatch) -> None:
    output_path = tmp_path / "recovery.md"
    calls: list[tuple[str, ...]] = []

    def fake_run(argv, cwd, check, **kwargs):  # noqa: ANN001, ARG001
        calls.append(tuple(argv))
        output_path.write_text("# Recovery\n\napi_key=plain-secret\n", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(check_plan2_acceptance.subprocess, "run", fake_run)

    result = check_plan2_acceptance.run_acceptance_commands(
        [
            check_plan2_acceptance.AcceptanceCommand(
                "memory-recovery-legacy-text",
                ("python-test", "-m", "TeeBotus.admin", "memory-recovery", "--output", str(output_path)),
                validate_secret_artifacts=True,
            ),
            check_plan2_acceptance.AcceptanceCommand("later", ("python-test", "-m", "pytest")),
        ]
    )

    assert result == 1
    assert calls == [("python-test", "-m", "TeeBotus.admin", "memory-recovery", "--output", str(output_path))]


def test_secret_artifact_validation_checks_all_declared_outputs(tmp_path: Path) -> None:
    json_path = tmp_path / "import.json"
    markdown_path = tmp_path / "import.md"
    json_path.write_text(json.dumps({"status": "ok", "api_key_env": "GROQ_API_KEY"}), encoding="utf-8")
    markdown_path.write_text("# Import\n\npassword=plain-secret\n", encoding="utf-8")

    errors = check_plan2_acceptance._secret_artifact_errors(
        (
            "python-test",
            "scripts/import_legacy_user_memory.py",
            "--json-output",
            str(json_path),
            "--markdown-output",
            str(markdown_path),
        )
    )

    assert errors == [f"--markdown-output artifact contains secret-looking content: {markdown_path}"]


def test_secret_artifact_validation_rejects_yaml_style_secret_fields(tmp_path: Path) -> None:
    markdown_path = tmp_path / "import.md"
    markdown_path.write_text("# Import\n\napi_key: plain-secret\npassword: hunter2\n", encoding="utf-8")

    errors = check_plan2_acceptance._secret_artifact_errors(
        ("python-test", "script.py", "--markdown-output", str(markdown_path))
    )

    assert errors == [f"--markdown-output artifact contains secret-looking content: {markdown_path}"]


def test_secret_artifact_validation_allows_yaml_style_placeholders_and_env_names(tmp_path: Path) -> None:
    markdown_path = tmp_path / "import.md"
    markdown_path.write_text(
        "# Import\n\napi_key: configured\napi_key_env: GROQ_API_KEY\npassword: <redacted>\n",
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._secret_artifact_errors(
        ("python-test", "script.py", "--markdown-output", str(markdown_path))
    )

    assert errors == []


def test_benchmark_artifact_validation_rejects_secret_leaks(tmp_path: Path) -> None:
    markdown_path = tmp_path / "bench.md"
    json_path = tmp_path / "bench.json"
    markdown_path.write_text(
        "# TeeBotus Benchmarks\n\n## Results\n\napi_key=plain-secret\n\n## Regression Check\n\nok\n",
        encoding="utf-8",
    )
    payload = _valid_benchmark_payload()
    payload["results"][0]["details"]["api_key"] = "plain-secret"
    json_path.write_text(json.dumps(payload), encoding="utf-8")

    markdown_errors = check_plan2_acceptance._markdown_artifact_errors(markdown_path)
    json_errors = check_plan2_acceptance._json_benchmark_artifact_errors(json_path)

    assert any("benchmark markdown artifact contains secret-looking content" in error for error in markdown_errors)
    assert any("benchmark JSON artifact contains secret-looking content" in error for error in json_errors)


def test_benchmark_artifact_validation_allows_env_var_names_without_values(tmp_path: Path) -> None:
    json_path = tmp_path / "bench.json"
    payload = _valid_benchmark_payload()
    payload["results"][0]["details"]["api_key_env"] = "GROQ_API_KEY"
    json_path.write_text(json.dumps(payload), encoding="utf-8")

    errors = check_plan2_acceptance._json_benchmark_artifact_errors(json_path)

    assert not any("secret-looking content" in error for error in errors)


def test_systemd_unit_validation_flags_public_or_unchecked_units() -> None:
    qdrant_errors = check_plan2_acceptance._systemd_unit_errors(
        "qdrant-systemd-print",
        "\n".join(
            [
                "[Unit]",
                "[Service]",
                "ExecStart=podman run --rm --name teebotus-qdrant -p 0.0.0.0:6333:6333 qdrant/qdrant:latest",
                "[Install]",
            ]
        ),
    )
    teebotus_errors = check_plan2_acceptance._systemd_unit_errors(
        "teebotus-systemd-print",
        "\n".join(
            [
                "[Unit]",
                "[Service]",
                "EnvironmentFile=-/tmp/.env",
                "ExecStart=python3 -m TeeBotus --all",
                "[Install]",
            ]
        ),
    )

    assert any("127.0.0.1" in error for error in qdrant_errors)
    assert any("pinned" in error for error in qdrant_errors)
    assert any("permission check missing" in error for error in teebotus_errors)
    assert any("multi-channel" in error for error in teebotus_errors)


def test_benchmark_artifact_validation_requires_plan2_core_categories() -> None:
    payload = {
        "schema_version": 1,
        "quick": True,
        "include_live": False,
        "ok": True,
        "results": [
            {
                "name": "memory_jsonl",
                "category": "account_memory",
                "ok": True,
                "mode": "local",
                "iterations": 1,
                "total_ms": 1.0,
                "throughput_ops_s": 100.0,
                "errors": 0,
                "payload_bytes": 1,
                "index_bytes": 1,
                "details": {"network_calls": 0},
            }
        ],
        "comparisons": {"stable_backend_rankings": [_valid_ranking("account_memory")]},
        "quality_gate": {"status": "ok", "ok": True, "checked_results": 1, "error_count": 0, "errors": []},
        "regression": {"status": "not_configured", "failed": False},
    }

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert any("benchmark results missing required categories" in error for error in errors)
    assert any("pydantic_ai" in error and "mcp_tools" in error and "transcription_youtube" in error for error in errors)


def test_benchmark_artifact_validation_requires_plan2_ranking_categories() -> None:
    payload = {
        "schema_version": 1,
        "quick": True,
        "include_live": False,
        "ok": True,
        "results": [
            {
                "name": f"{category}_benchmark",
                "category": category,
                "ok": True,
                "mode": "local",
                "iterations": 1,
                "total_ms": 1.0,
                "throughput_ops_s": 100.0,
                "errors": 0,
                "payload_bytes": 1,
                "index_bytes": 1,
                "details": {"network_calls": 0},
            }
            for category in sorted(check_plan2_acceptance.REQUIRED_BENCHMARK_CATEGORIES)
        ],
        "comparisons": {"stable_backend_rankings": [_valid_ranking("account_memory")]},
        "quality_gate": {
            "status": "ok",
            "ok": True,
            "checked_results": len(check_plan2_acceptance.REQUIRED_BENCHMARK_CATEGORIES),
            "error_count": 0,
            "errors": [],
        },
        "regression": {"status": "not_configured", "failed": False},
    }

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert any("benchmark rankings missing required categories" in error for error in errors)
    assert any("bibliothekar" in error and "langgraph_flows" in error and "transcription_youtube" in error for error in errors)


def test_benchmark_artifact_validation_requires_plan2_measurement_fields() -> None:
    payload = {
        "schema_version": 1,
        "quick": True,
        "include_live": False,
        "ok": True,
        "results": [
            {
                "name": "memory_jsonl",
                "category": "account_memory",
                "ok": True,
                "mode": "local",
                "iterations": 0,
                "total_ms": -1.0,
                "throughput_ops_s": 100.0,
                "errors": False,
                "payload_bytes": "unknown",
                "details": {},
            }
        ],
        "comparisons": {"stable_backend_rankings": [{"category": "account_memory", "candidates": [{"name": "memory_jsonl"}]}]},
        "quality_gate": {"status": "ok", "ok": True, "checked_results": 1, "error_count": 0, "errors": []},
        "regression": {"status": "not_configured", "failed": False},
    }

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert any("results[0] missing index_bytes" in error for error in errors)
    assert any("results[0] total_ms must be a non-negative number" in error for error in errors)
    assert any("results[0] payload_bytes must be a non-negative number" in error for error in errors)
    assert any("results[0] errors must be a non-negative integer" in error for error in errors)
    assert any("results[0] iterations must be a positive integer" in error for error in errors)
    assert any("results[0] details must be a non-empty object" in error for error in errors)


def test_benchmark_artifact_validation_requires_no_live_counters() -> None:
    payload = _valid_benchmark_payload()
    payload["results"][0]["details"] = {"network_calls": 0}

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert any("results[0] details missing standard no-live counters" in error for error in errors)
    assert any("openai_calls" in error and "provider_calls" in error and "remote_calls" in error for error in errors)


def test_benchmark_artifact_validation_rejects_live_or_nonquick_standard_artifacts() -> None:
    payload = {
        "schema_version": 1,
        "quick": False,
        "include_live": True,
        "ok": True,
        "results": [
            {
                "name": f"{category}_benchmark",
                "category": category,
                "ok": True,
                "mode": "local",
                "iterations": 1,
                "total_ms": 1.0,
                "throughput_ops_s": 100.0,
                "errors": 0,
                "payload_bytes": 1,
                "index_bytes": 1,
                "details": {"network_calls": 0},
            }
            for category in sorted(check_plan2_acceptance.REQUIRED_BENCHMARK_CATEGORIES)
        ],
        "comparisons": {
            "stable_backend_rankings": [
                _valid_ranking(category)
                for category in sorted(check_plan2_acceptance.REQUIRED_BENCHMARK_RANKING_CATEGORIES)
            ]
        },
        "quality_gate": {
            "status": "ok",
            "ok": True,
            "checked_results": len(check_plan2_acceptance.REQUIRED_BENCHMARK_CATEGORIES),
            "error_count": 0,
            "errors": [],
        },
        "regression": {"status": "not_configured", "failed": False},
    }

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert "quick must be true for standard Plan2 benchmark artifacts" in errors
    assert "include_live must be false for standard Plan2 benchmark artifacts" in errors


def test_benchmark_artifact_validation_rejects_provider_or_network_calls_in_standard_artifacts() -> None:
    payload = _valid_benchmark_payload()
    payload["results"][0]["mode"] = "live"
    payload["results"][1]["details"]["network_calls"] = 1
    payload["results"][2]["details"]["nested"] = {"openai_calls": 2}
    payload["results"][3]["details"]["llm_calls"] = 1

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert "results[0] must not use live mode in standard Plan2 benchmark artifacts" in errors
    assert "results[1] details.network_calls must be 0 in standard Plan2 benchmark artifacts, got 1" in errors
    assert "results[2] details.nested.openai_calls must be 0 in standard Plan2 benchmark artifacts, got 2" in errors
    assert "results[3] details.llm_calls must be 0 in standard Plan2 benchmark artifacts, got 1" in errors


def test_benchmark_artifact_validation_rejects_ok_results_with_errors() -> None:
    payload = _valid_benchmark_payload()
    payload["results"][0]["errors"] = 1

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert "results[0] errors must be 0 for ok standard benchmark results" in errors


def test_benchmark_artifact_validation_rejects_invalid_ranking_candidates() -> None:
    payload = _valid_benchmark_payload()
    ranking = payload["comparisons"]["stable_backend_rankings"][0]
    ranking["fastest_stable"] = "skipped_backend"
    ranking["skipped"] = [{"name": "skipped_backend", "mode": "live_optional", "reason": "missing dsn"}]
    ranking["candidates"][0] = {
        "rank": 2,
        "name": "candidate_with_errors",
        "mode": "live",
        "throughput_ops_s": 1000.0,
        "total_ms": 0.1,
        "errors": 1,
        "payload_bytes": 0,
        "index_bytes": 0,
    }

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert any("rankings[0].candidates[0] rank must be 1" in error for error in errors)
    assert any("rankings[0].candidates[0] errors must be 0" in error for error in errors)
    assert any("rankings[0].candidates[0] must not use live mode" in error for error in errors)
    assert any("rankings[0].candidates[0] must report payload_bytes or index_bytes" in error for error in errors)
    assert any("rankings[0] fastest_stable must match rank 1 candidate" in error for error in errors)
    assert any("rankings[0] fastest_stable must not be skipped" in error for error in errors)


def test_benchmark_artifact_validation_rejects_rankings_without_matching_results() -> None:
    payload = _valid_benchmark_payload()
    ranking = payload["comparisons"]["stable_backend_rankings"][0]
    ranking["fastest_stable"] = "synthetic_fastest"
    ranking["candidates"][0]["name"] = "synthetic_fastest"

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert any("rankings[0].candidates[0] must reference a successful result" in error for error in errors)


def test_benchmark_artifact_validation_requires_runtime_context() -> None:
    payload = _valid_benchmark_payload()
    payload["context"] = {
        "python": "",
        "cpu_count": "unknown",
        "dependencies": {},
    }

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert "context missing required keys: machine, platform" in errors
    assert "context.cpu_count must be a non-negative integer" in errors
    assert "context.dependencies must be a non-empty object" in errors
    assert "context.python must be non-empty" in errors


def test_benchmark_artifact_validation_requires_successful_quality_gate() -> None:
    payload = _valid_benchmark_payload()
    payload["quality_gate"] = {
        "status": "failed",
        "ok": False,
        "checked_results": "unknown",
        "error_count": 2,
        "errors": "benchmark smoke only",
    }

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert "quality_gate.ok must be true" in errors
    assert "quality_gate.status must be ok" in errors
    assert "quality_gate.checked_results must be a non-negative integer" in errors
    assert "quality_gate.error_count must be 0" in errors
    assert "quality_gate.errors must be a list" in errors


def test_benchmark_artifact_validation_requires_quality_gate_to_cover_all_results() -> None:
    payload = _valid_benchmark_payload()
    payload["quality_gate"]["checked_results"] = 1

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert "quality_gate.checked_results must match results length" in errors


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


def test_plan2_acceptance_runner_checks_runtime_status_stderr(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []
    leaked_key = "sk-" + "runtimeStatusStderrLeak123456"

    def fake_run(argv, cwd, check, **kwargs):  # noqa: ANN001, ARG001
        calls.append(tuple(argv))
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout="TeeBotus runtime configuration resolves.\n",
            stderr=f"llm=Demo/telegram:1 provider=openai model=gpt status=configured api_key={leaked_key}\n",
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
            "llm=Demo/signal:1 provider=litellm model=ollama_chat/qwen status=configured api_key=configured",
            "signal_service=Demo/signal:1 target=127.0.0.1:8080 status=reachable",
            "account_memory=Demo/abc status=ok",
            "ollama=127.0.0.1:11434 status=reachable models=llama3.1:8b",
            "local_transcription=Demo backend=local model=tiny status=ready engine=faster-whisper",
            "bibliothekar=Demo backend=local store=json collection=teebotus_books status=ready documents=1 chunks=1",
            "bibliothekar=Demo backend=haystack store=qdrant collection=therapy_books target=http://127.0.0.1:6333 status=reachable documents=1 chunks=1",
            "bibliothekar=Demo backend=haystack store=qdrant collection=therapy_books target=http://localhost:6334 status=reachable documents=1 chunks=1",
        ]
    )

    assert check_plan2_acceptance._runtime_status_broken_lines(output) == []


def test_runtime_status_broken_lines_flags_secret_leaks() -> None:
    openai_key = "sk-" + "liveSecretLeak123456"
    matrix_token = "syt_" + "liveSecretLeak123456"
    output = "\n".join(
        [
            f"llm=Demo/telegram:1 provider=openai model=gpt status=configured api_key={openai_key}",
            f"matrix_homeserver=Demo/matrix:1 target=matrix.example:443 status=reachable token={matrix_token}",
            "account_memory=Demo/abcdef status=ok",
        ]
    )

    assert check_plan2_acceptance._runtime_status_broken_lines(output) == output.splitlines()[:2]


def test_runtime_status_broken_lines_flags_generic_secret_assignments() -> None:
    output = "\n".join(
        [
            "llm=Demo/telegram:1 provider=litellm model=x status=configured api_key=configured",
            "llm=Demo/signal:1 provider=litellm model=x status=broken error=provider refused api_key=plain-secret",
            "signal_service=Demo/signal:1 target=127.0.0.1:8080 status=reachable password=hunter2",
        ]
    )

    assert check_plan2_acceptance._runtime_status_broken_lines(output) == output.splitlines()[1:]


def test_runtime_status_broken_lines_flags_url_credentials() -> None:
    output = "\n".join(
        [
            "signal_service=Demo/signal:1 target=https://user:plain-password@signal.example:8080 status=reachable",
            "llm=Demo/telegram:1 provider=litellm model=x status=configured base_url=http://127.0.0.1:11434 api_key=configured",
            "matrix_homeserver=Demo/matrix:1 target=bot:matrix-password@matrix.example:443 status=reachable",
        ]
    )

    assert check_plan2_acceptance._runtime_status_broken_lines(output) == [output.splitlines()[0], output.splitlines()[2]]


def test_runtime_status_broken_lines_flags_unsafe_qdrant_targets() -> None:
    output = "\n".join(
        [
            "bibliothekar=Demo backend=haystack store=qdrant collection=therapy_books target=http://qdrant.example:6333 status=reachable documents=1 chunks=1",
            "bibliothekar=Demo backend=haystack store=qdrant collection=therapy_books target=http://user:secret@127.0.0.1:6333 status=reachable documents=1 chunks=1",
            "bibliothekar=Demo backend=haystack store=qdrant collection=therapy_books target=http://127.0.0.1:6333?api_key=plain-secret status=reachable documents=1 chunks=1",
            "bibliothekar=Demo backend=haystack store=qdrant collection=therapy_books target=http://127.0.0.1:6333#token status=reachable documents=1 chunks=1",
            "bibliothekar=Demo backend=haystack store=qdrant collection=therapy_books status=reachable documents=1 chunks=1",
        ]
    )

    assert check_plan2_acceptance._runtime_status_broken_lines(output) == output.splitlines()


def test_runtime_status_broken_lines_flags_unhealthy_configured_resources() -> None:
    output = "\n".join(
        [
            "ollama=127.0.0.1:11434 status=unreachable error=connection refused",
            "llm=Demo/telegram:1 provider=openai model=gpt status=missing_key",
            "signal_service=Demo/signal:1 target=127.0.0.1:8080 status=unreachable error=connection refused",
            "signal_account=Demo/signal:1 phone=+491234 target=127.0.0.1:8080 status=missing error=account missing",
            "matrix_homeserver=Demo/matrix:1 target=matrix.example:443 status=unreachable error=connection refused",
            "local_transcription=Demo backend=local model=tiny status=unavailable error=missing backend",
            "bibliothekar=Demo backend=haystack store=qdrant collection=therapy_books status=unavailable error=missing dependency",
            "account_memory_recovery=Demo status=needed command=\"python3 -m TeeBotus.admin memory-recovery\"",
        ]
    )

    assert check_plan2_acceptance._runtime_status_broken_lines(output) == output.splitlines()
