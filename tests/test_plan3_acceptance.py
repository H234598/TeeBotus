from __future__ import annotations

import subprocess
from pathlib import Path

from scripts import check_plan3_acceptance


def test_plan3_acceptance_builds_non_live_default_commands(tmp_path: Path) -> None:
    commands = check_plan3_acceptance.build_acceptance_commands(
        python="python-test",
        benchmark_output=tmp_path / "bench.md",
        benchmark_json_output=tmp_path / "bench.json",
    )
    by_label = {command.label: command for command in commands}

    assert by_label["version"].argv == ("python-test", "-m", "TeeBotus", "--version")
    assert by_label["hf-pool-doctor"].argv == ("python-test", "-m", "TeeBotus.llm.hf_pool.doctor")
    assert by_label["embedding-cli-help"].argv == ("python-test", "-m", "TeeBotus.embedding", "--help")
    assert by_label["plan3-safe-rollout-config"].argv == (
        "python-test",
        "scripts/check_plan3_acceptance.py",
        "--check-safe-rollout",
    )
    assert by_label["runtime-status"].validate_runtime_status is True
    assert by_label["plan3-pytest"].argv[:4] == ("python-test", "-m", "pytest", "-q")
    assert "tests/test_hf_pool_config.py" in by_label["plan3-pytest"].argv
    assert "tests/test_qdrant_memory_index.py" in by_label["plan3-pytest"].argv
    assert "tests/test_pydantic_decision_fake_model.py" in by_label["plan3-pytest"].argv
    assert "hf-pool-doctor-live" not in by_label
    assert by_label["plan3-quick-benchmarks"].validate_benchmark_artifacts is True


def test_plan3_acceptance_live_hf_is_explicit() -> None:
    commands = check_plan3_acceptance.build_acceptance_commands(python="python-test", include_live_hf=True)

    live = next(command for command in commands if command.label == "hf-pool-doctor-live")
    assert live.argv == ("python-test", "-m", "TeeBotus.llm.hf_pool.doctor", "--live")
    assert live.nonfatal is False


def test_plan3_acceptance_can_skip_runtime_and_benchmarks() -> None:
    commands = check_plan3_acceptance.build_acceptance_commands(
        python="python-test",
        skip_runtime_status=True,
        skip_benchmarks=True,
    )
    labels = {command.label for command in commands}

    assert "runtime-status" not in labels
    assert "plan3-quick-benchmarks" not in labels
    assert "plan3-pytest" in labels


def test_plan3_acceptance_dry_run_does_not_execute(monkeypatch, capsys) -> None:
    def fail_if_executed(_commands):
        raise AssertionError("dry-run must not execute commands")

    monkeypatch.setattr(check_plan3_acceptance, "run_acceptance_commands", fail_if_executed)

    result = check_plan3_acceptance.main(["--dry-run", "--skip-runtime-status", "--skip-benchmarks"])

    output = capsys.readouterr().out
    assert result == 0
    assert "hf-pool-doctor:" in output
    assert "embedding-cli-help:" in output
    assert "plan3-safe-rollout-config:" in output
    assert "runtime-status" not in output
    assert "plan3-quick-benchmarks" not in output


def test_plan3_safe_rollout_accepts_hf_pool_structured_but_not_default(tmp_path: Path) -> None:
    profiles = tmp_path / "profiles.yaml"
    routing = tmp_path / "routing.yaml"
    profiles.write_text(
        """
profiles:
  local_ollama:
    provider: litellm
    model: ollama_chat/llama3.1:8b
  hf_pool_structured:
    provider: hf_pool
    model: pool:default#structured_decision
""",
        encoding="utf-8",
    )
    routing.write_text(
        """
default_profile: local_ollama
purposes:
  normal_chat:
    profile: local_ollama
    fallback: null
  structured_decision:
    profile: hf_pool_structured
    fallback: local_ollama
""",
        encoding="utf-8",
    )

    assert check_plan3_acceptance.plan3_safe_rollout_errors(profiles_path=profiles, routing_path=routing) == []


def test_plan3_safe_rollout_rejects_hf_pool_default_and_normal_chat(tmp_path: Path) -> None:
    profiles = tmp_path / "profiles.yaml"
    routing = tmp_path / "routing.yaml"
    profiles.write_text(
        """
profiles:
  local_ollama:
    provider: litellm
    model: ollama_chat/llama3.1:8b
  hf_pool_default:
    provider: hf_pool
    model: pool:default#normal_chat
""",
        encoding="utf-8",
    )
    routing.write_text(
        """
default_profile: hf_pool_default
purposes:
  normal_chat:
    profile: hf_pool_default
    fallback: hf_pool_default
""",
        encoding="utf-8",
    )

    errors = check_plan3_acceptance.plan3_safe_rollout_errors(profiles_path=profiles, routing_path=routing)

    assert "Plan3 safe-rollout: default_profile must not use provider=hf_pool" in errors
    assert "Plan3 safe-rollout: normal_chat profile must not use provider=hf_pool" in errors
    assert "Plan3 safe-rollout: normal_chat fallback must not use provider=hf_pool" in errors


def test_plan3_acceptance_runtime_status_validation_fails_on_broken_line(monkeypatch, capsys) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(argv, **_kwargs):
        calls.append(tuple(argv))
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=(
                "account_crypto=Demo status=broken mapping=present memory=missing_required "
                "pepper=not_required keyring=broken error=memory:missing\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(check_plan3_acceptance.subprocess, "run", fake_run)

    result = check_plan3_acceptance.run_acceptance_commands(
        [
            check_plan3_acceptance.Plan3Command(
                "runtime-status",
                ("python-test", "-m", "TeeBotus", "--runtime-status"),
                validate_runtime_status=True,
            ),
            check_plan3_acceptance.Plan3Command("later", ("python-test", "-m", "pytest")),
        ]
    )

    assert result == 1
    assert calls == [("python-test", "-m", "TeeBotus", "--runtime-status")]
    assert "runtime-status reports broken state" in capsys.readouterr().err
