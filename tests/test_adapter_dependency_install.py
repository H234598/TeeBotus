from __future__ import annotations

import subprocess
import sys
import types
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
                "matrix-nio==0.25.2",
                "blurhash-python==1.2.2",
                "h11==0.16.0",
                "faster-whisper==1.2.1",
                "litellm==1.83.7",
                "python-dotenv==1.2.2",
                "fastmcp==3.4.2",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    commands = build_python_install_commands(read_pins(lockfile), python="python3", user=True)

    assert len(commands) == 4
    assert "matrix-nio==0.25.2" in commands[0]
    assert "aiosqlite~=0.20" in commands[0]
    assert "orjson~=3.10" in commands[0]
    assert "beautifulsoup4~=4.12" in commands[0]
    assert "Pillow>=9.3.0" in commands[0]
    assert "h11==0.16.0" not in commands[0]
    assert "faster-whisper==1.2.1" in commands[0]
    assert "litellm==1.83.7" not in commands[0]
    assert "nio-bot==1.0.2.post1" not in commands[0]
    assert commands[1][-2:] == ["h11==0.16.0", "litellm==1.83.7"]
    assert commands[2][-2:] == ["python-dotenv==1.2.2", "fastmcp==3.4.2"]
    assert commands[3][-2:] == ["--no-deps", "nio-bot==1.0.2.post1"]


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
    assert "matrix-nio==0.25.2" in output
    assert f"litellm=={_active_litellm_version()}" in output
    assert "python-dotenv==1.2.2" in output
    assert "fastmcp==3.4.2" in output
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
    monkeypatch.setattr(check_adapter_deps, "_check_python_runtime_choice", ok("python_runtime_choice"))
    monkeypatch.setattr(check_adapter_deps, "_check_litellm_supply_chain_guard", ok("litellm_guard"))
    monkeypatch.setattr(check_adapter_deps, "_check_litellm_dotenv_contract", ok("litellm_dotenv"))
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
    assert "package:python-dotenv" in called
    assert "package:fastmcp" in called
    assert "python_runtime_choice" in called
    assert "litellm_dotenv" in called
    assert "pyproject_contract" in called
    assert "llm_profiles_contract" in called
    assert "secret_permissions" in called


def test_pyproject_plan2_contract_accepts_current_project_metadata() -> None:
    ok, message = check_adapter_deps._check_pyproject_plan2_contract()

    assert ok
    assert "extras=dev,llm,rag,agents,tools" in message


def test_python_runtime_choice_prefers_python313_for_clean_llm_resolver() -> None:
    ok, message = check_adapter_deps._check_python_runtime_choice((3, 13, 13))

    assert ok
    assert "choice=ok" in message
    assert "recommended=3.13" in message
    assert "resolver=clean" in message
    assert "litellm=1.89.2" in message


def test_python_runtime_choice_keeps_python314_as_advisory_not_failure() -> None:
    ok, message = check_adapter_deps._check_python_runtime_choice((3, 14, 5))

    assert ok
    assert "choice=advisory" in message
    assert "recommended=3.13" in message
    assert "active_litellm=1.83.7" in message
    assert "py313_litellm=1.89.2" in message
    assert "resolver=override" in message


def test_python_runtime_choice_rejects_unsupported_python() -> None:
    ok, message = check_adapter_deps._check_python_runtime_choice((3, 10, 18))

    assert not ok
    assert "choice=unsupported" in message
    assert "required=>=3.11" in message


def test_pyproject_plan2_contract_rejects_unexpected_plan2_extra_dependency(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
        [project]
        requires-python = ">=3.11"

        [project.optional-dependencies]
        dev = ["pytest", "pytest-cov", "ruff", "mypy", "pip-audit"]
        llm = ["litellm==1.89.2", "openai==2.43.0", "ollama==0.6.2", "surprise-llm"]
        rag = ["haystack-ai==2.30.2", "qdrant-haystack==10.3.0", "sentence-transformers==5.6.0", "pypdf==6.13.3", "pymupdf==1.27.2.3", "ebooklib==0.20", "beautifulsoup4==4.15.0", "llama-index-core==0.14.22"]
        agents = ["pydantic-ai-slim==1.107.0", "langgraph==1.2.6"]
        tools = ["fastmcp==3.4.2", "python-dotenv==1.2.2"]

        [project.scripts]
        teebotus-bibliothekar = "TeeBotus.bibliothekar.cli:main"
        teebotus-systemd = "TeeBotus.systemd:main"
        teebotus-proactive = "TeeBotus.proactive:main"
        teebotus-proactive-review = "TeeBotus.proactive_review:main"
        teebotus-proactive-systemd = "TeeBotus.proactive_systemd:main"
        teebotus-qdrant-systemd = "TeeBotus.qdrant_systemd:main"
        """,
        encoding="utf-8",
    )

    ok, message = check_adapter_deps._check_pyproject_plan2_contract(pyproject)

    assert not ok
    assert "llm unexpected surprise-llm" in message


def test_llm_profiles_plan2_contract_accepts_current_profiles() -> None:
    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert ok
    assert (
        "profiles=local_ollama,hf_pool_structured,hf_mistral,groq_fast,"
        "gemini_flash_stateless,gemini_flash_stateful,gemini_flash_paid_stateless,"
        "gemini_flash_paid_stateful,vertex_gemini_flash,openai_premium"
    ) in message


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


def test_litellm_supply_chain_guard_blocks_below_security_minimum() -> None:
    ok, message = check_adapter_deps._check_litellm_supply_chain_guard(_below_active_litellm_minimum())

    assert not ok
    assert "below security minimum" in message


def test_litellm_supply_chain_guard_blocks_suspicious_pth(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "litellm_init.pth").write_text("bad", encoding="utf-8")
    monkeypatch.setattr(check_adapter_deps.importlib.metadata, "version", lambda _name: "1.84.0")
    monkeypatch.setattr(check_adapter_deps.sys, "path", [str(tmp_path)])

    ok, message = check_adapter_deps._check_litellm_supply_chain_guard("1.84.0")

    assert not ok
    assert "suspicious_pth_files" in message


def test_litellm_dotenv_contract_accepts_current_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    versions = {"litellm": "1.83.7", "python-dotenv": "1.2.2"}
    monkeypatch.setattr(check_adapter_deps.importlib.metadata, "version", lambda name: versions[name])
    monkeypatch.setattr(
        check_adapter_deps.importlib,
        "import_module",
        lambda name: types.SimpleNamespace(load_dotenv=lambda: None) if name == "dotenv" else types.SimpleNamespace(),
    )

    ok, message = check_adapter_deps._check_litellm_dotenv_contract("1.83.7")

    assert ok
    assert "python-dotenv=1.2.2" in message


def test_litellm_dotenv_contract_rejects_old_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    versions = {"litellm": "1.83.7", "python-dotenv": "1.0.1"}
    monkeypatch.setattr(check_adapter_deps.importlib.metadata, "version", lambda name: versions[name])
    monkeypatch.setattr(
        check_adapter_deps.importlib,
        "import_module",
        lambda name: types.SimpleNamespace(load_dotenv=lambda: None) if name == "dotenv" else types.SimpleNamespace(),
    )

    ok, message = check_adapter_deps._check_litellm_dotenv_contract("1.83.7")

    assert not ok
    assert "expected=1.2.2" in message


def _active_litellm_version() -> str:
    if sys.version_info >= (3, 14):
        return "1.83.7"
    return "1.89.2"


def _below_active_litellm_minimum() -> str:
    if sys.version_info >= (3, 14):
        return "1.83.6"
    return "1.83.7"
