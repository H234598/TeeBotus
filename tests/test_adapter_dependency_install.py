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
                "litellm==1.89.2",
                "openai==2.30.0",
                "python-dotenv==1.2.2",
                "fastmcp==3.4.2",
                "watchdog==6.0.0",
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
    assert "litellm==1.89.2" not in commands[0]
    assert "nio-bot==1.0.2.post1" not in commands[0]
    assert commands[1][-3:] == ["h11==0.16.0", "litellm==1.89.2", "openai==2.30.0"]
    assert commands[2][-3:] == ["python-dotenv==1.2.2", "fastmcp==3.4.2", "watchdog==6.0.0"]
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
    assert f"openai=={_active_openai_version()}" in output
    assert "python-dotenv==1.2.2" in output
    assert "fastmcp==3.4.2" in output
    assert "watchdog==6.0.0" in output
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


def test_adapter_dependency_installer_can_skip_post_check(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, check=False, **_kwargs):
        calls.append(list(command))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("scripts.install_adapter_deps.subprocess.run", fake_run)

    result = main(["--python-only", "--python", "python3", "--no-user", "--skip-post-check"])

    assert result == 0
    assert not any(
        len(command) > 1 and str(Path(command[1]).name) == "check_adapter_deps.py" for command in calls
    )
    assert any("signalbot==1.2.2" in command for command in calls)


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
    monkeypatch.setattr(check_adapter_deps, "_check_adapter_lock_pyproject_contract", ok("lock_pyproject_contract"))
    monkeypatch.setattr(check_adapter_deps, "_check_requirements_runtime_contract", ok("requirements_contract"))
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
    assert "package:watchdog" in called
    assert "package:openai" in called
    assert "package:psycopg" in called
    assert "package:psycopg-binary" in called
    assert "python_runtime_choice" in called
    assert "litellm_dotenv" in called
    assert "pyproject_contract" in called
    assert "lock_pyproject_contract" in called
    assert "requirements_contract" in called
    assert "llm_profiles_contract" in called
    assert "secret_permissions" in called


def test_pyproject_plan2_contract_accepts_current_project_metadata() -> None:
    ok, message = check_adapter_deps._check_pyproject_plan2_contract()

    assert ok
    assert "extras=dev,llm,rag,agents,tools" in message


def test_adapter_lock_pyproject_contract_accepts_current_pins() -> None:
    ok, message = check_adapter_deps._check_adapter_lock_pyproject_contract()

    assert ok
    assert "packages=fastmcp,litellm,openai,python-dotenv,watchdog" in message


def test_adapter_lock_pyproject_contract_rejects_drift(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
        [project]
        name = "test"

        [project.optional-dependencies]
        llm = [
            "litellm==1.89.2",
            "openai==2.43.0; python_version < '3.14'",
            "openai==2.30.0; python_version >= '3.14'",
            "ollama==0.6.2",
        ]
        tools = [
            "fastmcp==3.4.2",
            "python-dotenv==1.2.2",
            "watchdog==6.0.0",
        ]
        """,
        encoding="utf-8",
    )
    lockfile = tmp_path / "adapter-dependencies.lock"
    lockfile.write_text(
        "\n".join(
            [
                "litellm==1.89.2",
                "openai==2.41.0; python_version < '3.14'",
                "openai==2.30.0; python_version >= '3.14'",
                "python-dotenv==1.2.2",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    ok, message = check_adapter_deps._check_adapter_lock_pyproject_contract(lockfile, pyproject)

    assert not ok
    assert "missing_from_lock" in message
    assert "openai==2.43.0" in message
    assert "fastmcp==3.4.2" in message
    assert "watchdog==6.0.0" in message
    assert "unexpected_in_lock" in message
    assert "openai==2.41.0" in message


def test_requirements_runtime_contract_accepts_current_requirements() -> None:
    ok, message = check_adapter_deps._check_requirements_runtime_contract()

    assert ok
    assert "psycopg[binary]==3.3.4" in message
    assert "sequenced_deps=deferred" in message


def test_requirements_runtime_contract_rejects_resolver_unsafe_dependencies(tmp_path: Path) -> None:
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        "\n".join(
            [
                "psycopg[binary]==3.3.4",
                "litellm==1.89.2",
                "openai==2.30.0",
                "python-dotenv==1.2.2",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    ok, message = check_adapter_deps._check_requirements_runtime_contract(requirements)

    assert not ok
    assert "sequenced dependencies must stay out of requirements.txt" in message
    assert "litellm==1.89.2" in message
    assert "openai==2.30.0" in message


def test_requirements_runtime_contract_requires_postgres_driver_pin(tmp_path: Path) -> None:
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("# intentionally empty\n", encoding="utf-8")

    ok, message = check_adapter_deps._check_requirements_runtime_contract(requirements)

    assert not ok
    assert "missing psycopg[binary]==3.3.4" in message


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
    assert "active_litellm=1.89.2" in message
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
        dev = ["pytest==9.1.1", "pytest-cov", "ruff", "mypy", "pip-audit"]
        llm = ["litellm==1.89.2", "openai==2.43.0", "ollama==0.6.2", "surprise-llm"]
        rag = ["haystack-ai==2.30.2", "qdrant-haystack==10.3.0", "sentence-transformers==5.6.0", "pypdf==6.13.3", "pymupdf==1.27.2.3", "ebooklib==0.20", "beautifulsoup4==4.15.0", "llama-index-core==0.14.22"]
        agents = ["pydantic-ai-slim==1.107.0", "langgraph==1.2.6"]
        tools = ["fastmcp==3.4.2", "python-dotenv==1.2.2", "watchdog==6.0.0"]

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
        "profiles=local_ollama,hf_mistral,hf_qwen,hf_pool_default,hf_pool_structured,"
        "hf_pool_quality,hf_pool_bibliothekar,groq_fast,"
        "gemini_flash_stateless,gemini_flash_stateful,gemini_flash_paid_stateless,"
        "gemini_flash_paid_stateful,gemini_2_5_flash_stateless,gemini_2_5_flash_stateful,"
        "gemini_2_5_flash_paid_stateless,gemini_2_5_flash_paid_stateful,"
        "vertex_gemini_flash,vertex_gemini_2_5_flash,openai_premium"
    ) in message
    assert (
        "routes=normal_chat,hard_reasoning,cheap_fast,private,bibliothekar_answer,"
        "structured_decision,codex_history_categorization,codex_history_strategic_analysis"
    ) in message


def test_llm_profiles_plan2_contract_rejects_wrong_api_key_env(monkeypatch) -> None:
    from dataclasses import replace

    from TeeBotus.llm import profiles as llm_profiles

    profiles = dict(llm_profiles.load_llm_profiles())
    default_profile, routing = llm_profiles.load_llm_routing()
    profiles["gemini_flash_stateful"] = replace(profiles["gemini_flash_stateful"], api_key_env="OPENAI_API_KEY")
    profiles["vertex_gemini_flash"] = replace(profiles["vertex_gemini_flash"], api_key_env="GEMINI_API_KEY")
    profiles["openai_premium"] = replace(profiles["openai_premium"], api_key_env="GEMINI_API_KEY")
    monkeypatch.setattr(llm_profiles, "load_llm_profiles", lambda: profiles)
    monkeypatch.setattr(llm_profiles, "load_llm_routing", lambda: (default_profile, routing))

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "profile gemini_flash_stateful api_key_env=OPENAI_API_KEY expected=GEMINI_API_KEY" in message
    assert "profile vertex_gemini_flash api_key_env=GEMINI_API_KEY expected=GOOGLE_APPLICATION_CREDENTIALS" in message
    assert "profile openai_premium api_key_env=GEMINI_API_KEY expected=OPENAI_API_KEY" in message


def test_llm_profiles_plan2_contract_rejects_unexpected_profile_service_tier(monkeypatch) -> None:
    from dataclasses import replace

    from TeeBotus.llm import profiles as llm_profiles

    profiles = dict(llm_profiles.load_llm_profiles())
    default_profile, routing = llm_profiles.load_llm_routing()
    profiles["gemini_flash_stateful"] = replace(profiles["gemini_flash_stateful"], service_tier="flex")
    monkeypatch.setattr(llm_profiles, "load_llm_profiles", lambda: profiles)
    monkeypatch.setattr(llm_profiles, "load_llm_routing", lambda: (default_profile, routing))

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "profile gemini_flash_stateful service_tier=flex expected=<empty>" in message


def test_llm_profiles_plan2_contract_rejects_wrong_profile_base_url(monkeypatch) -> None:
    from dataclasses import replace

    from TeeBotus.llm import profiles as llm_profiles

    profiles = dict(llm_profiles.load_llm_profiles())
    default_profile, routing = llm_profiles.load_llm_routing()
    profiles["local_ollama"] = replace(profiles["local_ollama"], base_url="http://localhost:11435")
    monkeypatch.setattr(llm_profiles, "load_llm_profiles", lambda: profiles)
    monkeypatch.setattr(llm_profiles, "load_llm_routing", lambda: (default_profile, routing))

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "profile local_ollama base_url=http://localhost:11435 expected=http://127.0.0.1:11434" in message


def test_llm_profiles_plan2_contract_rejects_wrong_purpose_routes(monkeypatch) -> None:
    from dataclasses import replace

    from TeeBotus.llm import profiles as llm_profiles

    profiles = llm_profiles.load_llm_profiles()
    default_profile, routing = llm_profiles.load_llm_routing()
    broken_routing = dict(routing)
    broken_routing["bibliothekar_answer"] = replace(
        broken_routing["bibliothekar_answer"],
        profile="local_ollama",
        fallback="",
    )
    broken_routing.pop("codex_history_strategic_analysis")
    monkeypatch.setattr(llm_profiles, "load_llm_profiles", lambda: profiles)
    monkeypatch.setattr(llm_profiles, "load_llm_routing", lambda: (default_profile, broken_routing))

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert (
        "routing bibliothekar_answer profile=local_ollama fallback=<empty> "
        "expected=gemini_flash_stateful/local_ollama"
    ) in message
    assert "routing missing codex_history_strategic_analysis" in message


def test_llm_profiles_plan2_contract_rejects_selector_route_drift(monkeypatch) -> None:
    from dataclasses import replace

    from TeeBotus.llm import profiles as llm_profiles

    original_selector = llm_profiles.select_llm_route

    def drifting_selector(purpose: str, **kwargs):
        route = original_selector(purpose, **kwargs)
        if route.purpose == "hard_reasoning":
            return replace(route, fallback_profile_name="", fallback_model="", fallback_api_key_env="")
        return route

    monkeypatch.setattr(llm_profiles, "select_llm_route", drifting_selector)

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "routing hard_reasoning selector fallback=<empty> expected=gemini_flash_stateful" in message


def test_llm_profiles_plan2_contract_rejects_selector_field_drift(monkeypatch) -> None:
    from dataclasses import replace

    from TeeBotus.llm import profiles as llm_profiles

    original_selector = llm_profiles.select_llm_route

    def drifting_selector(purpose: str, **kwargs):
        route = original_selector(purpose, **kwargs)
        if route.purpose == "hard_reasoning":
            return replace(route, api_key_env="", fallback_api_key_env="OPENAI_API_KEY", service_tier="flex")
        return route

    monkeypatch.setattr(llm_profiles, "select_llm_route", drifting_selector)

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "routing hard_reasoning selector api_key_env=<empty> expected=OPENAI_API_KEY" in message
    assert "routing hard_reasoning selector service_tier=flex expected=<empty>" in message
    assert "routing hard_reasoning selector fallback_api_key_env=OPENAI_API_KEY expected=GEMINI_API_KEY" in message


def test_llm_profiles_plan2_contract_rejects_unexpected_profiles_and_routes(monkeypatch) -> None:
    from dataclasses import replace

    from TeeBotus.llm import profiles as llm_profiles

    profiles = dict(llm_profiles.load_llm_profiles())
    default_profile, routing = llm_profiles.load_llm_routing()
    broken_routing = dict(routing)
    profiles["gemini_flash"] = replace(profiles["gemini_flash_stateful"], name="gemini_flash")
    broken_routing["legacy_bibliothekar"] = replace(
        broken_routing["bibliothekar_answer"],
        purpose="legacy_bibliothekar",
    )
    monkeypatch.setattr(llm_profiles, "load_llm_profiles", lambda: profiles)
    monkeypatch.setattr(llm_profiles, "load_llm_routing", lambda: (default_profile, broken_routing))

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "unexpected profile(s): gemini_flash" in message
    assert "unexpected routing purpose(s): legacy_bibliothekar" in message


def test_llm_profiles_plan2_contract_rejects_raw_profile_hidden_from_loader(monkeypatch) -> None:
    from copy import deepcopy

    from TeeBotus.llm import profiles as llm_profiles

    original_loader = llm_profiles._load_yaml_mapping

    def fake_loader(path):
        payload = deepcopy(original_loader(path))
        if Path(path) == llm_profiles.DEFAULT_PROFILE_PATH:
            payload.setdefault("profiles", {})["gemini_flash"] = {"provider": "", "model": ""}
        return payload

    monkeypatch.setattr(llm_profiles, "_load_yaml_mapping", fake_loader)

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "unexpected raw profile(s): gemini_flash" in message


def test_normalize_raw_llm_config_key_collapses_case_whitespace_and_hyphens() -> None:
    assert check_adapter_deps._normalize_raw_llm_config_key(" API  Key-Env ") == "api_key_env"
    assert check_adapter_deps._normalize_raw_llm_config_key("default---profile") == "default_profile"
    assert check_adapter_deps._normalize_raw_llm_config_key("__local ollama__") == "local_ollama"


def test_llm_profiles_plan2_contract_rejects_raw_profile_non_string_name(monkeypatch) -> None:
    from copy import deepcopy

    from TeeBotus.llm import profiles as llm_profiles

    original_loader = llm_profiles._load_yaml_mapping

    def fake_loader(path):
        payload = deepcopy(original_loader(path))
        if Path(path) == llm_profiles.DEFAULT_PROFILE_PATH:
            payload["profiles"][123] = {"provider": "litellm", "model": "ollama_chat/llama3.2:3b"}
        return payload

    monkeypatch.setattr(llm_profiles, "_load_yaml_mapping", fake_loader)

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "raw profile name(s) must be string: 123" in message


def test_llm_profiles_plan2_contract_rejects_raw_profile_alias_key(monkeypatch) -> None:
    from copy import deepcopy

    from TeeBotus.llm import profiles as llm_profiles

    original_loader = llm_profiles._load_yaml_mapping

    def fake_loader(path):
        payload = deepcopy(original_loader(path))
        if Path(path) == llm_profiles.DEFAULT_PROFILE_PATH:
            profiles = payload["profiles"]
            profiles["local ollama"] = profiles.pop("local_ollama")
        return payload

    monkeypatch.setattr(llm_profiles, "_load_yaml_mapping", fake_loader)

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "raw profile local ollama must use canonical key local_ollama" in message


def test_llm_profiles_plan2_contract_rejects_duplicate_raw_profile_aliases(monkeypatch) -> None:
    from copy import deepcopy

    from TeeBotus.llm import profiles as llm_profiles

    original_loader = llm_profiles._load_yaml_mapping

    def fake_loader(path):
        payload = deepcopy(original_loader(path))
        if Path(path) == llm_profiles.DEFAULT_PROFILE_PATH:
            payload["profiles"]["local-ollama"] = deepcopy(payload["profiles"]["local_ollama"])
        return payload

    monkeypatch.setattr(llm_profiles, "_load_yaml_mapping", fake_loader)

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "duplicate raw profile local_ollama: local-ollama,local_ollama" in message


def test_llm_profiles_plan2_contract_rejects_raw_config_non_string_top_level_keys(monkeypatch) -> None:
    from copy import deepcopy

    from TeeBotus.llm import profiles as llm_profiles

    original_loader = llm_profiles._load_yaml_mapping

    def fake_loader(path):
        payload = deepcopy(original_loader(path))
        if Path(path) == llm_profiles.DEFAULT_PROFILE_PATH:
            payload[123] = {}
        if Path(path) == llm_profiles.DEFAULT_ROUTING_PATH:
            payload[456] = {}
        return payload

    monkeypatch.setattr(llm_profiles, "_load_yaml_mapping", fake_loader)

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "raw profile config key(s) must be string: 123" in message
    assert "raw routing config key(s) must be string: 456" in message


def test_llm_profiles_plan2_contract_rejects_raw_config_top_level_alias_keys(monkeypatch) -> None:
    from copy import deepcopy

    from TeeBotus.llm import profiles as llm_profiles

    original_loader = llm_profiles._load_yaml_mapping

    def fake_loader(path):
        payload = deepcopy(original_loader(path))
        if Path(path) == llm_profiles.DEFAULT_PROFILE_PATH:
            payload["Profiles"] = payload.pop("profiles")
        if Path(path) == llm_profiles.DEFAULT_ROUTING_PATH:
            payload["default profile"] = payload.pop("default_profile")
        return payload

    monkeypatch.setattr(llm_profiles, "_load_yaml_mapping", fake_loader)

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "raw profile config key Profiles must use canonical key profiles" in message
    assert "raw routing config key default profile must use canonical key default_profile" in message


def test_llm_profiles_plan2_contract_rejects_duplicate_raw_config_top_level_aliases(monkeypatch) -> None:
    from copy import deepcopy

    from TeeBotus.llm import profiles as llm_profiles

    original_loader = llm_profiles._load_yaml_mapping

    def fake_loader(path):
        payload = deepcopy(original_loader(path))
        if Path(path) == llm_profiles.DEFAULT_PROFILE_PATH:
            payload["Profiles"] = payload["profiles"]
        if Path(path) == llm_profiles.DEFAULT_ROUTING_PATH:
            payload["default-profile"] = payload["default_profile"]
        return payload

    monkeypatch.setattr(llm_profiles, "_load_yaml_mapping", fake_loader)

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "duplicate raw profile config key profiles: Profiles,profiles" in message
    assert "duplicate raw routing config key default_profile: default-profile,default_profile" in message


def test_llm_profiles_plan2_contract_rejects_raw_config_non_mapping_without_unreadable(monkeypatch) -> None:
    from copy import deepcopy

    from TeeBotus.llm import profiles as llm_profiles

    original_loader = llm_profiles._load_yaml_mapping
    profiles = llm_profiles.load_llm_profiles()
    default_profile, routing = llm_profiles.load_llm_routing()

    def fake_loader(path):
        if Path(path) == llm_profiles.DEFAULT_PROFILE_PATH:
            return ["profiles"]
        if Path(path) == llm_profiles.DEFAULT_ROUTING_PATH:
            return ["routing"]
        return deepcopy(original_loader(path))

    monkeypatch.setattr(llm_profiles, "_load_yaml_mapping", fake_loader)
    monkeypatch.setattr(llm_profiles, "load_llm_profiles", lambda: profiles)
    monkeypatch.setattr(llm_profiles, "load_llm_routing", lambda: (default_profile, routing))

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "unreadable" not in message
    assert "raw profile config must be mapping" in message
    assert "raw routing config must be mapping" in message


def test_llm_profiles_plan2_contract_rejects_raw_profile_unknown_keys(monkeypatch) -> None:
    from copy import deepcopy

    from TeeBotus.llm import profiles as llm_profiles

    original_loader = llm_profiles._load_yaml_mapping

    def fake_loader(path):
        payload = deepcopy(original_loader(path))
        if Path(path) == llm_profiles.DEFAULT_PROFILE_PATH:
            payload["profiles"]["local_ollama"]["api_base"] = "http://127.0.0.1:11434"
        return payload

    monkeypatch.setattr(llm_profiles, "_load_yaml_mapping", fake_loader)

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "raw profile local_ollama unexpected key(s): api_base" in message


def test_llm_profiles_plan2_contract_rejects_raw_profile_field_alias_key(monkeypatch) -> None:
    from copy import deepcopy

    from TeeBotus.llm import profiles as llm_profiles

    original_loader = llm_profiles._load_yaml_mapping

    def fake_loader(path):
        payload = deepcopy(original_loader(path))
        if Path(path) == llm_profiles.DEFAULT_PROFILE_PATH:
            payload["profiles"]["openai_premium"]["api key env"] = "OPENAI_API_KEY"
        return payload

    monkeypatch.setattr(llm_profiles, "_load_yaml_mapping", fake_loader)

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "raw profile openai_premium key api key env must use canonical key api_key_env" in message


def test_llm_profiles_plan2_contract_rejects_duplicate_raw_profile_field_aliases(monkeypatch) -> None:
    from copy import deepcopy

    from TeeBotus.llm import profiles as llm_profiles

    original_loader = llm_profiles._load_yaml_mapping

    def fake_loader(path):
        payload = deepcopy(original_loader(path))
        if Path(path) == llm_profiles.DEFAULT_PROFILE_PATH:
            payload["profiles"]["openai_premium"]["api-key-env"] = "OPENAI_API_KEY"
        return payload

    monkeypatch.setattr(llm_profiles, "_load_yaml_mapping", fake_loader)

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "duplicate raw profile openai_premium key api_key_env: api-key-env,api_key_env" in message


def test_llm_profiles_plan2_contract_rejects_raw_profile_missing_required_keys(monkeypatch) -> None:
    from copy import deepcopy

    from TeeBotus.llm import profiles as llm_profiles

    original_loader = llm_profiles._load_yaml_mapping

    def fake_loader(path):
        payload = deepcopy(original_loader(path))
        if Path(path) == llm_profiles.DEFAULT_PROFILE_PATH:
            del payload["profiles"]["local_ollama"]["api_key_env"]
        return payload

    monkeypatch.setattr(llm_profiles, "_load_yaml_mapping", fake_loader)

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "raw profile local_ollama missing key(s): api_key_env" in message


def test_llm_profiles_plan2_contract_rejects_raw_profile_non_string_values(monkeypatch) -> None:
    from copy import deepcopy

    from TeeBotus.llm import profiles as llm_profiles

    original_loader = llm_profiles._load_yaml_mapping

    def fake_loader(path):
        payload = deepcopy(original_loader(path))
        if Path(path) == llm_profiles.DEFAULT_PROFILE_PATH:
            payload["profiles"]["local_ollama"]["provider"] = ["litellm"]
        return payload

    monkeypatch.setattr(llm_profiles, "_load_yaml_mapping", fake_loader)

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "raw profile local_ollama provider must be string" in message


def test_llm_profiles_plan2_contract_rejects_raw_profile_wrong_provider_value(monkeypatch) -> None:
    from copy import deepcopy

    from TeeBotus.llm import profiles as llm_profiles

    original_loader = llm_profiles._load_yaml_mapping

    def fake_loader(path):
        payload = deepcopy(original_loader(path))
        if Path(path) == llm_profiles.DEFAULT_PROFILE_PATH:
            payload["profiles"]["openai_premium"]["provider"] = " openai"
        return payload

    monkeypatch.setattr(llm_profiles, "_load_yaml_mapping", fake_loader)

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "raw profile openai_premium provider= openai expected=litellm" in message


def test_llm_profiles_plan2_contract_rejects_raw_profile_trimmed_api_key_env(monkeypatch) -> None:
    from copy import deepcopy

    from TeeBotus.llm import profiles as llm_profiles

    original_loader = llm_profiles._load_yaml_mapping

    def fake_loader(path):
        payload = deepcopy(original_loader(path))
        if Path(path) == llm_profiles.DEFAULT_PROFILE_PATH:
            payload["profiles"]["openai_premium"]["api_key_env"] = "OPENAI_API_KEY "
        return payload

    monkeypatch.setattr(llm_profiles, "_load_yaml_mapping", fake_loader)

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "raw profile openai_premium api_key_env=OPENAI_API_KEY  expected=OPENAI_API_KEY" in message


def test_llm_profiles_plan2_contract_rejects_raw_profile_wrong_static_model_value(monkeypatch) -> None:
    from copy import deepcopy

    from TeeBotus.llm import profiles as llm_profiles

    original_loader = llm_profiles._load_yaml_mapping

    def fake_loader(path):
        payload = deepcopy(original_loader(path))
        if Path(path) == llm_profiles.DEFAULT_PROFILE_PATH:
            payload["profiles"]["hf_mistral"]["model"] = "huggingface/mistralai/Other-Instruct"
        return payload

    monkeypatch.setattr(llm_profiles, "_load_yaml_mapping", fake_loader)

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert (
        "raw profile hf_mistral model=huggingface/mistralai/Other-Instruct "
        "expected=huggingface/mistralai/Mistral-7B-Instruct-v0.3"
    ) in message


def test_llm_profiles_plan2_contract_rejects_raw_profile_and_route_non_string_field_keys(monkeypatch) -> None:
    from copy import deepcopy

    from TeeBotus.llm import profiles as llm_profiles

    original_loader = llm_profiles._load_yaml_mapping

    def fake_loader(path):
        payload = deepcopy(original_loader(path))
        if Path(path) == llm_profiles.DEFAULT_PROFILE_PATH:
            payload["profiles"]["local_ollama"][123] = "ignored"
        if Path(path) == llm_profiles.DEFAULT_ROUTING_PATH:
            payload["purposes"]["normal_chat"][456] = "ignored"
        return payload

    monkeypatch.setattr(llm_profiles, "_load_yaml_mapping", fake_loader)

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "raw profile local_ollama key(s) must be string: 123" in message
    assert "raw routing purpose normal_chat key(s) must be string: 456" in message


def test_llm_profiles_plan2_contract_rejects_raw_routing_alias_key(monkeypatch) -> None:
    from copy import deepcopy

    from TeeBotus.llm import profiles as llm_profiles

    original_loader = llm_profiles._load_yaml_mapping

    def fake_loader(path):
        payload = deepcopy(original_loader(path))
        if Path(path) == llm_profiles.DEFAULT_ROUTING_PATH:
            purposes = payload["purposes"]
            purposes["structured-decision"] = purposes.pop("structured_decision")
        return payload

    monkeypatch.setattr(llm_profiles, "_load_yaml_mapping", fake_loader)

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "raw routing purpose structured-decision must use canonical key structured_decision" in message


def test_llm_profiles_plan2_contract_rejects_duplicate_raw_routing_aliases(monkeypatch) -> None:
    from copy import deepcopy

    from TeeBotus.llm import profiles as llm_profiles

    original_loader = llm_profiles._load_yaml_mapping

    def fake_loader(path):
        payload = deepcopy(original_loader(path))
        if Path(path) == llm_profiles.DEFAULT_ROUTING_PATH:
            payload["purposes"]["structured-decision"] = deepcopy(payload["purposes"]["structured_decision"])
        return payload

    monkeypatch.setattr(llm_profiles, "_load_yaml_mapping", fake_loader)

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "duplicate raw routing purpose structured_decision: structured-decision,structured_decision" in message


def test_llm_profiles_plan2_contract_rejects_raw_routing_unknown_keys(monkeypatch) -> None:
    from copy import deepcopy

    from TeeBotus.llm import profiles as llm_profiles

    original_loader = llm_profiles._load_yaml_mapping

    def fake_loader(path):
        payload = deepcopy(original_loader(path))
        if Path(path) == llm_profiles.DEFAULT_ROUTING_PATH:
            payload["purposes"]["hard_reasoning"]["fallback_profile"] = "gemini_flash_stateful"
        return payload

    monkeypatch.setattr(llm_profiles, "_load_yaml_mapping", fake_loader)

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "raw routing purpose hard_reasoning key fallback_profile must use canonical key fallback" in message
    assert "raw routing purpose hard_reasoning unexpected key(s): fallback_profile" in message


def test_llm_profiles_plan2_contract_rejects_duplicate_raw_routing_field_aliases(monkeypatch) -> None:
    from copy import deepcopy

    from TeeBotus.llm import profiles as llm_profiles

    original_loader = llm_profiles._load_yaml_mapping

    def fake_loader(path):
        payload = deepcopy(original_loader(path))
        if Path(path) == llm_profiles.DEFAULT_ROUTING_PATH:
            payload["purposes"]["hard_reasoning"]["fallback_profile"] = "gemini_flash_stateful"
        return payload

    monkeypatch.setattr(llm_profiles, "_load_yaml_mapping", fake_loader)

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "duplicate raw routing purpose hard_reasoning key fallback: fallback,fallback_profile" in message


def test_llm_profiles_plan2_contract_rejects_raw_routing_missing_required_keys(monkeypatch) -> None:
    from copy import deepcopy

    from TeeBotus.llm import profiles as llm_profiles

    original_loader = llm_profiles._load_yaml_mapping

    def fake_loader(path):
        payload = deepcopy(original_loader(path))
        if Path(path) == llm_profiles.DEFAULT_ROUTING_PATH:
            del payload["purposes"]["normal_chat"]["fallback"]
        return payload

    monkeypatch.setattr(llm_profiles, "_load_yaml_mapping", fake_loader)

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "raw routing purpose normal_chat missing key(s): fallback" in message


def test_llm_profiles_plan2_contract_rejects_raw_routing_non_scalar_fallback(monkeypatch) -> None:
    from copy import deepcopy

    from TeeBotus.llm import profiles as llm_profiles

    original_loader = llm_profiles._load_yaml_mapping

    def fake_loader(path):
        payload = deepcopy(original_loader(path))
        if Path(path) == llm_profiles.DEFAULT_ROUTING_PATH:
            payload["purposes"]["hard_reasoning"]["fallback"] = ["gemini_flash_stateful"]
        return payload

    monkeypatch.setattr(llm_profiles, "_load_yaml_mapping", fake_loader)

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "raw routing purpose hard_reasoning fallback must be string or null" in message


def test_llm_profiles_plan2_contract_rejects_raw_routing_wrong_profile_value(monkeypatch) -> None:
    from copy import deepcopy

    from TeeBotus.llm import profiles as llm_profiles

    original_loader = llm_profiles._load_yaml_mapping

    def fake_loader(path):
        payload = deepcopy(original_loader(path))
        if Path(path) == llm_profiles.DEFAULT_ROUTING_PATH:
            payload["purposes"]["hard_reasoning"]["profile"] = "local_ollama"
        return payload

    monkeypatch.setattr(llm_profiles, "_load_yaml_mapping", fake_loader)

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "raw routing purpose hard_reasoning profile=local_ollama expected=openai_premium" in message


def test_llm_profiles_plan2_contract_rejects_raw_routing_empty_string_fallback(monkeypatch) -> None:
    from copy import deepcopy

    from TeeBotus.llm import profiles as llm_profiles

    original_loader = llm_profiles._load_yaml_mapping

    def fake_loader(path):
        payload = deepcopy(original_loader(path))
        if Path(path) == llm_profiles.DEFAULT_ROUTING_PATH:
            payload["purposes"]["normal_chat"]["fallback"] = ""
        return payload

    monkeypatch.setattr(llm_profiles, "_load_yaml_mapping", fake_loader)

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "raw routing purpose normal_chat fallback=<empty> expected=<null>" in message


def test_llm_profiles_plan2_contract_rejects_raw_routing_trimmed_default_profile(monkeypatch) -> None:
    from copy import deepcopy

    from TeeBotus.llm import profiles as llm_profiles

    original_loader = llm_profiles._load_yaml_mapping

    def fake_loader(path):
        payload = deepcopy(original_loader(path))
        if Path(path) == llm_profiles.DEFAULT_ROUTING_PATH:
            payload["default_profile"] = " local_ollama"
        return payload

    monkeypatch.setattr(llm_profiles, "_load_yaml_mapping", fake_loader)

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "raw routing default_profile= local_ollama expected=local_ollama" in message


def test_llm_profiles_plan2_contract_rejects_raw_routing_top_level_drift(monkeypatch) -> None:
    from copy import deepcopy

    from TeeBotus.llm import profiles as llm_profiles

    original_loader = llm_profiles._load_yaml_mapping

    def fake_loader(path):
        payload = deepcopy(original_loader(path))
        if Path(path) == llm_profiles.DEFAULT_ROUTING_PATH:
            payload["default"] = "local_ollama"
        return payload

    monkeypatch.setattr(llm_profiles, "_load_yaml_mapping", fake_loader)

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "raw routing config unexpected key(s): default" in message


def test_llm_profiles_plan2_contract_rejects_raw_routing_non_string_purpose_name(monkeypatch) -> None:
    from copy import deepcopy

    from TeeBotus.llm import profiles as llm_profiles

    original_loader = llm_profiles._load_yaml_mapping

    def fake_loader(path):
        payload = deepcopy(original_loader(path))
        if Path(path) == llm_profiles.DEFAULT_ROUTING_PATH:
            payload["purposes"][123] = {"profile": "local_ollama", "fallback": None}
        return payload

    monkeypatch.setattr(llm_profiles, "_load_yaml_mapping", fake_loader)

    ok, message = check_adapter_deps._check_llm_profiles_plan2_contract()

    assert not ok
    assert "raw routing purpose name(s) must be string: 123" in message


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
    active_litellm_version = _active_litellm_version()
    monkeypatch.setattr(check_adapter_deps.importlib.metadata, "version", lambda _name: active_litellm_version)
    monkeypatch.setattr(check_adapter_deps.sys, "path", [str(tmp_path)])

    ok, message = check_adapter_deps._check_litellm_supply_chain_guard(active_litellm_version)

    assert not ok
    assert "suspicious_pth_files" in message


def test_litellm_dotenv_contract_accepts_current_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    versions = {"litellm": "1.89.2", "python-dotenv": "1.2.2"}
    monkeypatch.setattr(check_adapter_deps.importlib.metadata, "version", lambda name: versions[name])
    monkeypatch.setattr(
        check_adapter_deps.importlib,
        "import_module",
        lambda name: types.SimpleNamespace(load_dotenv=lambda: None) if name == "dotenv" else types.SimpleNamespace(),
    )

    ok, message = check_adapter_deps._check_litellm_dotenv_contract("1.89.2")

    assert ok
    assert "python-dotenv=1.2.2" in message


def test_litellm_dotenv_contract_rejects_old_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    versions = {"litellm": "1.89.2", "python-dotenv": "1.0.1"}
    monkeypatch.setattr(check_adapter_deps.importlib.metadata, "version", lambda name: versions[name])
    monkeypatch.setattr(
        check_adapter_deps.importlib,
        "import_module",
        lambda name: types.SimpleNamespace(load_dotenv=lambda: None) if name == "dotenv" else types.SimpleNamespace(),
    )

    ok, message = check_adapter_deps._check_litellm_dotenv_contract("1.89.2")

    assert not ok
    assert "expected=1.2.2" in message


def _active_litellm_version() -> str:
    if sys.version_info >= (3, 14):
        return "1.89.2"
    return "1.89.2"


def _active_openai_version() -> str:
    if sys.version_info >= (3, 14):
        return "2.30.0"
    return "2.43.0"


def _below_active_litellm_minimum() -> str:
    if sys.version_info >= (3, 14):
        return "1.89.1"
    return "1.83.7"
