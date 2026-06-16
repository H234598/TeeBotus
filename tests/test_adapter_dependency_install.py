from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import scripts.check_adapter_deps as check_adapter_deps
from scripts.install_adapter_deps import build_python_install_commands, main, read_pins, signal_cli_release_url, signal_cli_rest_api_repo_url


def test_adapter_dependency_installer_keeps_matrix_override_outside_niobot_deps(tmp_path: Path) -> None:
    lockfile = tmp_path / "adapter-dependencies.lock"
    lockfile.write_text(
        "\n".join(
            [
                "signalbot==1.2.2",
                "nio-bot==1.0.2.post1",
                "matrix-nio==0.25.0",
                "blurhash-python==1.2.2",
                "h11==0.16.0",
                "faster-whisper==1.2.1",
                "litellm==1.83.7",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    commands = build_python_install_commands(read_pins(lockfile), python="python3", user=True)

    assert len(commands) == 2
    assert "matrix-nio==0.25.0" in commands[0]
    assert "h11==0.16.0" in commands[0]
    assert "faster-whisper==1.2.1" in commands[0]
    assert "litellm==1.83.7" in commands[0]
    assert "nio-bot==1.0.2.post1" not in commands[0]
    assert commands[1][-2:] == ["--no-deps", "nio-bot==1.0.2.post1"]


def test_signal_cli_release_url_uses_pinned_github_release() -> None:
    assert signal_cli_release_url("0.14.5") == (
        "https://github.com/AsamK/signal-cli/releases/download/v0.14.5/signal-cli-0.14.5.tar.gz"
    )


def test_signal_cli_rest_api_repo_url_uses_bbernhard_upstream() -> None:
    assert signal_cli_rest_api_repo_url() == "https://github.com/bbernhard/signal-cli-rest-api.git"


def test_adapter_dependency_dry_run_includes_native_installs(capsys) -> None:
    result = main(["--dry-run", "--python", "python3"])

    assert result == 0
    output = capsys.readouterr().out
    assert "signalbot==1.2.2" in output
    assert "litellm==1.83.7" in output
    assert "download https://github.com/AsamK/signal-cli/releases/download/v0.14.5/signal-cli-0.14.5.tar.gz" in output
    assert "git clone --depth 1 --branch 0.100 https://github.com/bbernhard/signal-cli-rest-api.git" in output
    assert "go build -o signal-cli-rest-api main.go" in output


def test_adapter_dependency_installer_passes_python_only_to_final_check(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(command, check=False, **_kwargs):
        calls.append(list(command))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("scripts.install_adapter_deps.subprocess.run", fake_run)

    result = main(["--python-only", "--python", "python3", "--no-user"])

    assert result == 0
    assert calls[-1][-1] == "--python-only"
    assert any("signalbot==1.2.2" in command for command in calls)
    assert not any("signal-cli-rest-api" in " ".join(command) for command in calls[:-1])


def test_check_adapter_deps_python_only_skips_native_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []

    def ok(name: str):
        def _inner(*_args, **_kwargs):
            called.append(name)
            return True, name

        return _inner

    monkeypatch.setattr(check_adapter_deps, "_check_python_package", lambda name, _expected: (called.append(f"package:{name}") or (True, name)))
    monkeypatch.setattr(check_adapter_deps, "_check_litellm_supply_chain_guard", ok("litellm_guard"))
    monkeypatch.setattr(check_adapter_deps, "_check_local_transcription_contract", ok("local_transcription"))
    monkeypatch.setattr(check_adapter_deps, "_check_niobot_matrix_contract", ok("niobot_matrix"))
    monkeypatch.setattr(check_adapter_deps, "_check_matrix_file_contract", ok("matrix_file"))
    monkeypatch.setattr(check_adapter_deps, "_check_signalbot_context_contract", ok("signalbot_context"))
    monkeypatch.setattr(check_adapter_deps, "_check_pyproject_plan2_contract", ok("pyproject_contract"))
    monkeypatch.setattr(check_adapter_deps, "_check_llm_profiles_plan2_contract", ok("llm_profiles_contract"))
    monkeypatch.setattr(check_adapter_deps, "_check_local_secret_file_permissions", ok("secret_permissions"))
    monkeypatch.setattr(check_adapter_deps, "_check_executable_version", ok("signal_cli"))
    monkeypatch.setattr(check_adapter_deps, "_check_signal_cli_rest_api_binary", ok("signal_cli_rest_api"))

    assert check_adapter_deps.main(["--python-only"]) == 0

    assert "signal_cli" not in called
    assert "signal_cli_rest_api" not in called
    assert "package:signalbot" in called
    assert "pyproject_contract" in called
    assert "llm_profiles_contract" in called
    assert "secret_permissions" in called


def test_pyproject_plan2_contract_accepts_current_project_metadata() -> None:
    ok, message = check_adapter_deps._check_pyproject_plan2_contract()

    assert ok
    assert "extras=dev,llm,rag,agents,tools" in message


def test_llm_profiles_plan2_contract_accepts_current_profiles() -> None:
    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert ok
    assert "profiles=local_ollama,hf_mistral,groq_fast,gemini_flash,openai_premium" in message


def test_local_secret_file_permission_check_accepts_missing_or_private_env(tmp_path: Path) -> None:
    ok, message = check_adapter_deps._check_local_secret_file_permissions(tmp_path)

    assert ok
    assert ".env=missing" in message

    env_path = tmp_path / ".env"
    env_path.write_text("OPENAI_API_KEY=test-placeholder\n", encoding="utf-8")
    env_path.chmod(0o600)

    ok, message = check_adapter_deps._check_local_secret_file_permissions(tmp_path)

    assert ok
    assert "mode=600" in message


def test_local_secret_file_permission_check_rejects_group_or_world_readable_env(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("OPENAI_API_KEY=test-placeholder\n", encoding="utf-8")
    env_path.chmod(0o644)

    ok, message = check_adapter_deps._check_local_secret_file_permissions(tmp_path)

    assert not ok
    assert "mode=644" in message
    assert "expected=600-or-stricter" in message


def test_litellm_supply_chain_guard_blocks_bad_pin() -> None:
    ok, message = check_adapter_deps._check_litellm_supply_chain_guard("1.82.8")

    assert not ok
    assert "blocked" in message


def test_litellm_supply_chain_guard_blocks_suspicious_pth(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "litellm_init.pth").write_text("bad", encoding="utf-8")
    monkeypatch.setattr(check_adapter_deps.importlib.metadata, "version", lambda _name: "1.83.7")
    monkeypatch.setattr(check_adapter_deps.sys, "path", [str(tmp_path)])

    ok, message = check_adapter_deps._check_litellm_supply_chain_guard("1.83.7")

    assert not ok
    assert "suspicious_pth_files" in message
