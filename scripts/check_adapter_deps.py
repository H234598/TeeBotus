#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.metadata
import importlib
import inspect
import json
import os
import shutil
import subprocess
import sys
import tomllib
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement


LOCKFILE = Path(__file__).resolve().parents[1] / "adapter-dependencies.lock"
REPO_ROOT = Path(__file__).resolve().parents[1]
BAD_LITELLM_VERSIONS = frozenset({"1.82.7", "1.82.8"})
MIN_SAFE_LITELLM_VERSION = "1.84.0"
PY313_LITELLM_VERSION = "1.89.2"
PY314_COMPATIBLE_LITELLM_VERSION = "1.89.2"
PSYCOPG_VERSION = "3.3.4"
PYTEST_VERSION = "9.1.1"
WATCHDOG_VERSION = "6.0.0"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check pinned TeeBotus adapter dependencies.")
    parser.add_argument("--python-only", action="store_true", help="Check only Python adapter dependencies and contracts.")
    parser.add_argument("--native-only", action="store_true", help="Check only native signal-cli binaries and optional service.")
    args = parser.parse_args(argv)
    if args.python_only and args.native_only:
        parser.error("--python-only and --native-only cannot be combined")

    pins = _read_pins(LOCKFILE)
    checks: list[tuple[bool, str]] = []
    if not args.native_only:
        checks.extend(
            [
                _check_python_runtime_choice(),
                _check_python_package("signalbot", pins["signalbot"]),
                _check_python_package("nio-bot", pins["nio-bot"]),
                _check_python_package("matrix-nio", pins["matrix-nio"]),
                _check_python_package("blurhash-python", pins["blurhash-python"]),
                _check_python_package("h11", pins["h11"]),
                _check_python_package("faster-whisper", pins["faster-whisper"]),
                _check_python_package("litellm", pins["litellm"]),
                _check_python_package("openai", pins["openai"]),
                _check_python_package("python-dotenv", "1.2.2"),
                _check_python_package("fastmcp", "3.4.2"),
                _check_python_package("watchdog", WATCHDOG_VERSION),
                _check_python_package("psycopg", PSYCOPG_VERSION),
                _check_python_package("psycopg-binary", PSYCOPG_VERSION),
                _check_litellm_supply_chain_guard(pins["litellm"]),
                _check_litellm_dotenv_contract(pins["litellm"]),
                _check_local_transcription_contract(),
                _check_niobot_matrix_contract(),
                _check_matrix_file_contract(),
                _check_signalbot_context_contract(),
                _check_pyproject_plan2_contract(),
                _check_adapter_lock_pyproject_contract(),
                _check_requirements_runtime_contract(),
                _check_llm_profiles_plan2_contract(),
                _check_local_secret_file_permissions(),
            ]
        )
    if not args.python_only:
        checks.extend(
            [
                _check_executable_version("signal-cli", pins["signal-cli"], ["--version"]),
                _check_signal_cli_rest_api_binary(pins["signal-cli-rest-api"]),
            ]
        )
        service_url = os.environ.get("SIGNAL_CLI_REST_API_CHECK_URL", "").strip()
        if service_url:
            checks.append(_check_signal_cli_rest_api_service(service_url, pins["signal-cli-rest-api"]))
    for ok, message in checks:
        print(("OK " if ok else "FAIL ") + message)
    return 0 if all(ok for ok, _message in checks) else 1


def _read_pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            requirement = Requirement(stripped)
        except InvalidRequirement:
            name, sep, version = stripped.partition("==")
            if not sep:
                raise SystemExit(f"Invalid lock line: {line}") from None
            pins[name.strip()] = version.strip()
            continue
        if requirement.marker is not None and not requirement.marker.evaluate(environment=default_environment()):
            continue
        specifiers = list(requirement.specifier)
        if len(specifiers) != 1 or specifiers[0].operator != "==":
            raise SystemExit(f"Invalid lock line: {line}")
        pins[requirement.name.replace("_", "-")] = specifiers[0].version
    return pins


def _check_python_package(name: str, expected: str) -> tuple[bool, str]:
    try:
        installed = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return False, f"{name} missing, expected {expected}"
    import_name = {"nio-bot": "niobot", "matrix-nio": "nio", "blurhash-python": "blurhash", "python-dotenv": "dotenv"}.get(
        name, name.replace("-", "_")
    )
    try:
        module = importlib.import_module(import_name)
    except Exception as exc:
        module = None
        import_detail = f" import_error={type(exc).__name__}: {exc}"
    else:
        import_detail = f" import={getattr(module, '__file__', '<unknown>')}"
    ok = installed == expected and module is not None
    return ok, f"{name} installed={installed} expected={expected}{import_detail}"


def _check_litellm_supply_chain_guard(expected: str) -> tuple[bool, str]:
    min_safe_litellm = _min_safe_litellm_version()
    if expected in BAD_LITELLM_VERSIONS:
        return False, f"litellm pin={expected} is blocked due to known compromised PyPI releases"
    if _version_tuple(expected) < _version_tuple(min_safe_litellm):
        return False, f"litellm pin={expected} is below security minimum {min_safe_litellm}"
    try:
        installed = importlib.metadata.version("litellm")
    except importlib.metadata.PackageNotFoundError:
        return False, f"litellm missing, expected {expected}"
    if installed in BAD_LITELLM_VERSIONS:
        return False, f"litellm installed={installed} is blocked due to known compromised PyPI releases"
    if _version_tuple(installed) < _version_tuple(min_safe_litellm):
        return False, f"litellm installed={installed} is below security minimum {min_safe_litellm}"
    suspicious_pth = _litellm_pth_files()
    if suspicious_pth:
        return False, "litellm suspicious_pth_files=" + ",".join(str(path) for path in suspicious_pth)
    return True, f"litellm supply_chain_guard=ok blocked={','.join(sorted(BAD_LITELLM_VERSIONS))}"


def _check_litellm_dotenv_contract(expected_litellm: str) -> tuple[bool, str]:
    try:
        litellm_version = importlib.metadata.version("litellm")
        dotenv_version = importlib.metadata.version("python-dotenv")
    except importlib.metadata.PackageNotFoundError as exc:
        return False, f"litellm dotenv contract missing package: {exc.name}"
    if litellm_version != expected_litellm:
        return False, f"litellm dotenv contract litellm={litellm_version} expected={expected_litellm}"
    try:
        importlib.import_module("litellm")
        dotenv_module = importlib.import_module("dotenv")
    except Exception as exc:
        return False, f"litellm dotenv contract import_error={type(exc).__name__}: {exc}"
    if not callable(getattr(dotenv_module, "load_dotenv", None)):
        return False, "litellm dotenv contract dotenv.load_dotenv missing"
    if dotenv_version != "1.2.2":
        return False, f"litellm dotenv contract python-dotenv={dotenv_version} expected=1.2.2"
    return True, f"litellm dotenv contract=ok litellm={litellm_version} python-dotenv={dotenv_version}"


def _check_python_runtime_choice(version_info: tuple[int, int, int] | None = None) -> tuple[bool, str]:
    current = version_info or (sys.version_info.major, sys.version_info.minor, sys.version_info.micro)
    major, minor, micro = current
    current_label = f"{major}.{minor}.{micro}"
    if (major, minor) < (3, 11):
        return False, f"python runtime choice=unsupported current={current_label} required=>=3.11 recommended=3.13"
    if (major, minor) == (3, 13):
        return (
            True,
            "python runtime choice=ok current="
            f"{current_label} recommended=3.13 litellm={PY313_LITELLM_VERSION} openai=2.43.0 "
            "resolver=clean",
        )
    if (major, minor) >= (3, 14):
        return (
            True,
            "python runtime choice=advisory current="
            f"{current_label} recommended=3.13 reason=openai_latest_excludes_python3.14 "
            f"active_litellm={PY314_COMPATIBLE_LITELLM_VERSION} active_openai=2.30.0 "
            f"py313_litellm={PY313_LITELLM_VERSION} py313_openai=2.43.0 resolver=override",
        )
    return (
        True,
        "python runtime choice=compatible current="
        f"{current_label} recommended=3.13 reason=modern_llm_toolchain_pins "
        f"target_litellm={PY313_LITELLM_VERSION} target_openai=2.43.0",
    )


def _check_pyproject_plan2_contract(path: Path = REPO_ROOT / "pyproject.toml") -> tuple[bool, str]:
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return False, f"pyproject plan2 contract unreadable: {type(exc).__name__}: {exc}"
    project = payload.get("project")
    if not isinstance(project, dict):
        return False, "pyproject plan2 contract missing [project]"
    errors: list[str] = []
    if project.get("requires-python") != ">=3.11":
        errors.append("requires-python must stay >=3.11 for Plan2 unless intentionally raised")
    optional = project.get("optional-dependencies")
    if not isinstance(optional, dict):
        errors.append("missing optional-dependencies")
        optional = {}
    litellm_version, openai_version = _active_llm_versions()
    fastmcp_version = _active_fastmcp_version()
    expected_extras = {
        "dev": {"pytest": PYTEST_VERSION, "pytest-cov": "", "ruff": "", "mypy": "", "pip-audit": ""},
        "llm": {
            "litellm": litellm_version,
            "openai": openai_version,
            "ollama": "0.6.2",
        },
        "rag": {
            "haystack-ai": "2.30.2",
            "qdrant-haystack": "10.3.0",
            "sentence-transformers": "5.6.0",
            "pypdf": "6.13.3",
            "pymupdf": "1.27.2.3",
            "ebooklib": "0.20",
            "beautifulsoup4": "4.15.0",
            "llama-index-core": "0.14.22",
        },
        "agents": {"pydantic-ai-slim": "1.107.0", "langgraph": "1.2.6"},
        "tools": {"fastmcp": fastmcp_version, "python-dotenv": "1.2.2", "watchdog": WATCHDOG_VERSION},
    }
    for extra, expected in expected_extras.items():
        found = _active_optional_dependency_versions(optional.get(extra, []))
        missing = sorted(set(expected) - set(found))
        if missing:
            errors.append(f"{extra} missing {','.join(missing)}")
        unexpected = sorted(set(found) - set(expected))
        if extra in {"llm", "rag", "agents", "tools"} and unexpected:
            errors.append(f"{extra} unexpected {','.join(unexpected)}")
        version_mismatches = sorted(
            f"{name}=={found[name]} expected=={expected_version}"
            for name, expected_version in expected.items()
            if expected_version and name in found and found[name] != expected_version
        )
        if version_mismatches:
            errors.append(f"{extra} version_mismatch {','.join(version_mismatches)}")
    llm_deps = set(optional.get("llm", [])) if isinstance(optional.get("llm"), list) else set()
    for dependency in llm_deps:
        name, version = _optional_dependency_name_version(str(dependency))
        if name == "litellm" and version in BAD_LITELLM_VERSIONS:
            errors.append(f"llm pins blocked litellm version {version}")
    scripts = project.get("scripts")
    if not isinstance(scripts, dict):
        errors.append("missing project scripts")
        scripts = {}
    expected_scripts = {
        "teebotus-bibliothekar",
        "teebotus-systemd",
        "teebotus-proactive",
        "teebotus-proactive-review",
        "teebotus-proactive-systemd",
        "teebotus-qdrant-systemd",
        "teebotus-embedding",
    }
    missing_scripts = sorted(expected_scripts - set(scripts))
    if missing_scripts:
        errors.append(f"scripts missing {','.join(missing_scripts)}")
    if errors:
        return False, "pyproject plan2 contract failed: " + "; ".join(errors)
    return True, "pyproject plan2 contract=ok extras=dev,llm,rag,agents,tools requires-python=>=3.11"


def _check_adapter_lock_pyproject_contract(
    lockfile_path: Path = LOCKFILE,
    pyproject_path: Path = REPO_ROOT / "pyproject.toml",
) -> tuple[bool, str]:
    managed_names = {"litellm", "openai", "python-dotenv", "fastmcp", "watchdog"}
    try:
        lock_lines = _dependency_lines(lockfile_path)
        payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return False, f"adapter lock pyproject contract unreadable: {type(exc).__name__}: {exc}"
    project = payload.get("project")
    optional = project.get("optional-dependencies") if isinstance(project, dict) else None
    if not isinstance(optional, dict):
        return False, "adapter lock pyproject contract missing pyproject optional dependencies"
    expected: set[str] = set()
    for extra in ("llm", "tools"):
        raw_deps = optional.get(extra, [])
        if not isinstance(raw_deps, list):
            return False, f"adapter lock pyproject contract {extra} dependencies must be a list"
        expected.update(str(dependency).strip() for dependency in raw_deps if _dependency_name(str(dependency)) in managed_names)
    found = {line for line in lock_lines if _dependency_name(line) in managed_names}
    missing = sorted(expected - found)
    unexpected = sorted(found - expected)
    errors: list[str] = []
    if missing:
        errors.append("missing_from_lock " + ",".join(missing))
    if unexpected:
        errors.append("unexpected_in_lock " + ",".join(unexpected))
    if errors:
        return False, "adapter lock pyproject contract failed: " + "; ".join(errors)
    return True, "adapter lock pyproject contract=ok packages=fastmcp,litellm,openai,python-dotenv,watchdog"


def _check_requirements_runtime_contract(path: Path = REPO_ROOT / "requirements.txt") -> tuple[bool, str]:
    try:
        requirements = {
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
    except OSError as exc:
        return False, f"requirements runtime contract unreadable: {type(exc).__name__}: {exc}"
    errors: list[str] = []
    required = f"psycopg[binary]=={PSYCOPG_VERSION}"
    if required not in requirements:
        errors.append(f"missing {required}")
    blocked_prefixes = ("litellm", "openai", "python-dotenv", "fastmcp", "watchdog", "nio-bot", "matrix-nio", "h11")
    blocked = sorted(dependency for dependency in requirements if dependency.startswith(blocked_prefixes))
    if blocked:
        errors.append("sequenced dependencies must stay out of requirements.txt: " + ",".join(blocked))
    if errors:
        return False, "requirements runtime contract failed: " + "; ".join(errors)
    return True, f"requirements runtime contract=ok base={required} sequenced_deps=deferred"


def _dependency_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _dependency_name(dependency: str) -> str:
    name, _version = _optional_dependency_name_version(dependency)
    return name


def _version_tuple(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in str(value or "").replace("-", ".").split("."):
        if not chunk.isdigit():
            break
        parts.append(int(chunk))
    return tuple(parts or [0])


def _min_safe_litellm_version() -> str:
    if sys.version_info >= (3, 14):
        return PY314_COMPATIBLE_LITELLM_VERSION
    return MIN_SAFE_LITELLM_VERSION


def _active_llm_versions() -> tuple[str, str]:
    if sys.version_info >= (3, 14):
        return PY314_COMPATIBLE_LITELLM_VERSION, "2.30.0"
    return PY313_LITELLM_VERSION, "2.43.0"


def _active_fastmcp_version() -> str:
    return "3.4.2"


def _active_optional_dependency_versions(raw_deps: object) -> dict[str, str]:
    if not isinstance(raw_deps, list):
        return {}
    versions: dict[str, str] = {}
    for dependency in raw_deps:
        applies = True
        try:
            requirement = Requirement(str(dependency))
        except InvalidRequirement:
            requirement = None
        if requirement is not None and requirement.marker is not None:
            applies = bool(requirement.marker.evaluate(environment=default_environment()))
        if not applies:
            continue
        name, version = _optional_dependency_name_version(str(dependency))
        if name:
            versions[name] = version
    return versions


def _optional_dependency_name_version(dependency: str) -> tuple[str, str]:
    try:
        requirement = Requirement(dependency)
    except InvalidRequirement:
        head = dependency.split(";", 1)[0].strip()
        name, sep, version = head.partition("==")
        return name.strip().replace("_", "-"), version.strip() if sep else ""
    specifiers = list(requirement.specifier)
    version = specifiers[0].version if len(specifiers) == 1 and specifiers[0].operator == "==" else ""
    return requirement.name.replace("_", "-"), version


def _check_llm_profiles_plan2_contract() -> tuple[bool, str]:
    try:
        from TeeBotus.llm.profiles import (
            DEFAULT_PROFILE_PATH,
            DEFAULT_ROUTING_PATH,
            _load_yaml_mapping,
            load_llm_profiles,
            load_llm_routing,
            normalize_llm_purpose,
            select_llm_route,
        )
    except Exception as exc:
        return False, f"llm profiles plan2 contract import_error={type(exc).__name__}: {exc}"
    try:
        raw_profile_payload = _load_yaml_mapping(DEFAULT_PROFILE_PATH).get("profiles")
        raw_routing_payload = _load_yaml_mapping(DEFAULT_ROUTING_PATH).get("purposes")
        profiles = load_llm_profiles()
        default_profile, routing = load_llm_routing()
    except Exception as exc:
        return False, f"llm profiles plan2 contract unreadable: {type(exc).__name__}: {exc}"
    errors: list[str] = []
    expected_profiles = {
        "local_ollama": ("litellm", "ollama_chat/", "", ""),
        "hf_mistral": ("litellm", "huggingface/", "", "HUGGINGFACE_API_KEY"),
        "hf_qwen": ("litellm", "huggingface/", "", "HUGGINGFACE_API_KEY"),
        "hf_pool_default": ("hf_pool", "pool:", "", ""),
        "hf_pool_structured": ("hf_pool", "pool:", "", ""),
        "hf_pool_quality": ("hf_pool", "pool:", "", ""),
        "hf_pool_bibliothekar": ("hf_pool", "pool:", "", ""),
        "groq_fast": ("litellm", "groq/", "", "GROQ_API_KEY"),
        "gemini_flash_stateless": ("litellm_gemini_stateless", "gemini/", "gemini/gemini-3.5-flash", "GEMINI_API_KEY"),
        "gemini_flash_stateful": ("litellm_gemini_stateful", "gemini/", "gemini/gemini-3.5-flash", "GEMINI_API_KEY"),
        "gemini_flash_paid_stateless": ("litellm_gemini_paid_stateless", "gemini/", "gemini/gemini-3.5-flash", "GEMINI_API_KEY"),
        "gemini_flash_paid_stateful": ("litellm_gemini_paid_stateful", "gemini/", "gemini/gemini-3.5-flash", "GEMINI_API_KEY"),
        "gemini_2_5_flash_stateless": ("litellm_gemini_stateless", "gemini/", "gemini/gemini-2.5-flash", "GEMINI_API_KEY"),
        "gemini_2_5_flash_stateful": ("litellm_gemini_stateful", "gemini/", "gemini/gemini-2.5-flash", "GEMINI_API_KEY"),
        "gemini_2_5_flash_paid_stateless": ("litellm_gemini_paid_stateless", "gemini/", "gemini/gemini-2.5-flash", "GEMINI_API_KEY"),
        "gemini_2_5_flash_paid_stateful": ("litellm_gemini_paid_stateful", "gemini/", "gemini/gemini-2.5-flash", "GEMINI_API_KEY"),
        "vertex_gemini_flash": ("litellm", "vertex_ai/", "vertex_ai/gemini-3.5-flash", "GOOGLE_APPLICATION_CREDENTIALS"),
        "vertex_gemini_2_5_flash": ("litellm", "vertex_ai/", "vertex_ai/gemini-2.5-flash", "GOOGLE_APPLICATION_CREDENTIALS"),
        "openai_premium": ("litellm", "openai/", "openai/gpt-5.5", "OPENAI_API_KEY"),
    }
    if not isinstance(raw_profile_payload, dict):
        errors.append("raw profile payload must be mapping")
    else:
        raw_profile_names = {str(name) for name in raw_profile_payload}
        allowed_raw_profile_keys = {"provider", "model", "base_url", "api_key_env", "service_tier"}
        unexpected_raw_profiles = sorted(raw_profile_names - set(expected_profiles))
        missing_raw_profiles = sorted(set(expected_profiles) - raw_profile_names)
        if unexpected_raw_profiles:
            errors.append(f"unexpected raw profile(s): {','.join(unexpected_raw_profiles)}")
        if missing_raw_profiles:
            errors.append(f"missing raw profile(s): {','.join(missing_raw_profiles)}")
        for name in sorted(raw_profile_names & set(expected_profiles)):
            raw_profile = raw_profile_payload.get(name)
            if not isinstance(raw_profile, dict):
                errors.append(f"raw profile {name} must be mapping")
                continue
            unexpected_keys = sorted(str(key) for key in raw_profile if str(key) not in allowed_raw_profile_keys)
            if unexpected_keys:
                errors.append(f"raw profile {name} unexpected key(s): {','.join(unexpected_keys)}")
            required_keys = {"provider", "model", "api_key_env"}
            if name == "local_ollama":
                required_keys.add("base_url")
            missing_keys = sorted(key for key in required_keys if key not in raw_profile)
            if missing_keys:
                errors.append(f"raw profile {name} missing key(s): {','.join(missing_keys)}")
    if default_profile != "local_ollama":
        errors.append("default_profile must be local_ollama")
    if default_profile not in profiles:
        errors.append(f"default_profile missing {default_profile or '<empty>'}")
    unexpected_profiles = sorted(set(profiles) - set(expected_profiles))
    if unexpected_profiles:
        errors.append(f"unexpected profile(s): {','.join(unexpected_profiles)}")
    expected_profile_base_urls = {name: "" for name in expected_profiles}
    expected_profile_base_urls["local_ollama"] = "http://127.0.0.1:11434"
    expected_profile_service_tiers = {name: "" for name in expected_profiles}
    for name, (provider, model_prefix, exact_model, api_key_env) in expected_profiles.items():
        profile = profiles.get(name)
        if profile is None:
            errors.append(f"profile missing {name}")
            continue
        if profile.provider != provider:
            errors.append(f"profile {name} provider={profile.provider or '<empty>'} expected={provider}")
        if model_prefix and not profile.model.startswith(model_prefix):
            errors.append(f"profile {name} model must start with {model_prefix}")
        if exact_model and profile.model != exact_model:
            errors.append(f"profile {name} model={profile.model or '<empty>'} expected={exact_model}")
        if profile.api_key_env != api_key_env:
            errors.append(
                f"profile {name} api_key_env={profile.api_key_env or '<empty>'} expected={api_key_env or '<empty>'}"
            )
        expected_base_url = expected_profile_base_urls[name]
        if profile.base_url != expected_base_url:
            errors.append(
                f"profile {name} base_url={profile.base_url or '<empty>'} expected={expected_base_url or '<empty>'}"
            )
        expected_service_tier = expected_profile_service_tiers[name]
        if profile.service_tier != expected_service_tier:
            errors.append(
                f"profile {name} service_tier={profile.service_tier or '<empty>'} "
                f"expected={expected_service_tier or '<empty>'}"
            )
    expected_hf_pool_selectors = {
        "hf_pool_default": "pool:default#normal_chat",
        "hf_pool_structured": "pool:default#structured_decision",
        "hf_pool_quality": "pool:default#psychology_explainer",
        "hf_pool_bibliothekar": "pool:default#bibliothekar_answer",
    }
    for name, expected_model in expected_hf_pool_selectors.items():
        profile = profiles.get(name)
        if profile is not None and profile.model != expected_model:
            errors.append(f"profile {name} model={profile.model or '<empty>'} expected={expected_model}")
    for purpose, rule in routing.items():
        if rule.profile not in profiles:
            errors.append(f"routing {purpose} unknown profile {rule.profile}")
        if rule.fallback and rule.fallback not in profiles:
            errors.append(f"routing {purpose} unknown fallback {rule.fallback}")
    expected_routes = {
        "normal_chat": ("local_ollama", ""),
        "hard_reasoning": ("openai_premium", "gemini_flash_stateful"),
        "cheap_fast": ("groq_fast", "local_ollama"),
        "private": ("local_ollama", ""),
        "bibliothekar_answer": ("gemini_flash_stateful", "local_ollama"),
        "structured_decision": ("hf_pool_structured", "local_ollama"),
        "codex_history_categorization": ("local_ollama", ""),
        "codex_history_strategic_analysis": ("local_ollama", ""),
    }
    if not isinstance(raw_routing_payload, dict):
        errors.append("raw routing purposes must be mapping")
    else:
        raw_route_names = {str(name) for name in raw_routing_payload}
        normalized_raw_routes: dict[str, str] = {}
        duplicate_normalized_routes: dict[str, list[str]] = {}
        for raw_name in sorted(raw_route_names):
            normalized_name = normalize_llm_purpose(raw_name)
            if normalized_name in normalized_raw_routes:
                duplicate_normalized_routes.setdefault(
                    normalized_name,
                    [normalized_raw_routes[normalized_name]],
                ).append(raw_name)
            normalized_raw_routes[normalized_name] = raw_name
        for normalized_name, raw_names in sorted(duplicate_normalized_routes.items()):
            errors.append(f"duplicate raw routing purpose {normalized_name}: {','.join(raw_names)}")
        unexpected_raw_routes = sorted(set(normalized_raw_routes) - set(expected_routes))
        missing_raw_routes = sorted(set(expected_routes) - set(normalized_raw_routes))
        if unexpected_raw_routes:
            errors.append(f"unexpected raw routing purpose(s): {','.join(unexpected_raw_routes)}")
        if missing_raw_routes:
            errors.append(f"missing raw routing purpose(s): {','.join(missing_raw_routes)}")
        for normalized_name, raw_name in sorted(normalized_raw_routes.items()):
            if normalized_name in expected_routes and raw_name != normalized_name:
                errors.append(f"raw routing purpose {raw_name} must use canonical key {normalized_name}")
            raw_route = raw_routing_payload.get(raw_name)
            if normalized_name in expected_routes and not isinstance(raw_route, dict):
                errors.append(f"raw routing purpose {raw_name} must be mapping")
                continue
            if normalized_name in expected_routes and isinstance(raw_route, dict):
                unexpected_keys = sorted(str(key) for key in raw_route if str(key) not in {"profile", "fallback"})
                if unexpected_keys:
                    errors.append(f"raw routing purpose {raw_name} unexpected key(s): {','.join(unexpected_keys)}")
                missing_keys = sorted(key for key in {"profile", "fallback"} if key not in raw_route)
                if missing_keys:
                    errors.append(f"raw routing purpose {raw_name} missing key(s): {','.join(missing_keys)}")
    unexpected_routes = sorted(set(routing) - set(expected_routes))
    if unexpected_routes:
        errors.append(f"unexpected routing purpose(s): {','.join(unexpected_routes)}")
    for purpose, (profile, fallback) in expected_routes.items():
        rule = routing.get(purpose)
        if rule is None:
            errors.append(f"routing missing {purpose}")
            continue
        if rule.profile != profile or rule.fallback != fallback:
            errors.append(
                f"routing {purpose} profile={rule.profile or '<empty>'} fallback={rule.fallback or '<empty>'} "
                f"expected={profile}/{fallback or '<empty>'}"
            )
        try:
            selected = select_llm_route(
                purpose,
                profiles=profiles,
                default_profile=default_profile,
                routing=routing,
                allow_remote_fallback=True,
            )
        except Exception as exc:
            errors.append(f"routing {purpose} selector failed: {type(exc).__name__}: {exc}")
            continue
        if selected.profile_name != profile:
            errors.append(
                f"routing {purpose} selector profile={selected.profile_name or '<empty>'} expected={profile}"
            )
        expected_profile = profiles.get(profile)
        if expected_profile is not None:
            selected_fields = {
                "provider": selected.provider,
                "model": selected.model,
                "api_key_env": selected.api_key_env,
                "base_url": selected.base_url,
                "service_tier": selected.service_tier,
            }
            for field, selected_value in selected_fields.items():
                expected_value = getattr(expected_profile, field)
                if selected_value != expected_value:
                    errors.append(
                        f"routing {purpose} selector {field}={selected_value or '<empty>'} "
                        f"expected={expected_value or '<empty>'}"
                    )
        if selected.fallback_profile_name != fallback:
            errors.append(
                f"routing {purpose} selector fallback={selected.fallback_profile_name or '<empty>'} "
                f"expected={fallback or '<empty>'}"
            )
        expected_fallback = profiles.get(fallback) if fallback else None
        if expected_fallback is not None:
            fallback_fields = {
                "fallback_model": selected.fallback_model,
                "fallback_api_key_env": selected.fallback_api_key_env,
                "fallback_base_url": selected.fallback_base_url,
            }
            expected_values = {
                "fallback_model": expected_fallback.model,
                "fallback_api_key_env": expected_fallback.api_key_env,
                "fallback_base_url": expected_fallback.base_url,
            }
            for field, selected_value in fallback_fields.items():
                expected_value = expected_values[field]
                if selected_value != expected_value:
                    errors.append(
                        f"routing {purpose} selector {field}={selected_value or '<empty>'} "
                        f"expected={expected_value or '<empty>'}"
                    )
        elif selected.fallback_model or selected.fallback_api_key_env or selected.fallback_base_url:
            errors.append(f"routing {purpose} selector fallback fields must be empty without fallback")
    if errors:
        return False, "llm profiles plan2 contract failed: " + "; ".join(errors)
    return True, (
        "llm profiles plan2 contract=ok "
        f"profiles={','.join(expected_profiles)} "
        f"routes={','.join(expected_routes)}"
    )


def _check_local_secret_file_permissions(root: Path = REPO_ROOT) -> tuple[bool, str]:
    env_path = root / ".env"
    if not env_path.exists():
        return True, "local secret file permissions=ok .env=missing"
    try:
        mode = env_path.stat().st_mode & 0o777
    except OSError as exc:
        return False, f"local secret file permissions failed: .env unreadable: {type(exc).__name__}: {exc}"
    if mode & 0o077:
        return False, f"local secret file permissions failed: .env mode={mode:03o} expected=600-or-stricter"
    return True, f"local secret file permissions=ok .env mode={mode:03o}"


def _litellm_pth_files() -> list[Path]:
    paths: list[Path] = []
    for entry in sys.path:
        try:
            directory = Path(entry)
        except TypeError:
            continue
        if not directory.is_dir():
            continue
        try:
            paths.extend(sorted(directory.glob("litellm*.pth")))
        except OSError:
            continue
    return paths


def _check_niobot_matrix_contract() -> tuple[bool, str]:
    try:
        import nio  # type: ignore[import-not-found]
        import niobot  # type: ignore[import-not-found]
    except Exception as exc:
        return False, f"nio-bot/matrix-nio contract import_error={type(exc).__name__}: {exc}"
    required_nio = (
        "AsyncClient",
        "RoomMessageText",
        "RoomMessageNotice",
        "RoomMessageEmote",
        "RoomMessageFile",
        "RoomMessageImage",
        "RoomMessageAudio",
        "RoomMessageVideo",
        "RoomEncryptedFile",
        "RoomEncryptedImage",
        "RoomEncryptedAudio",
        "RoomEncryptedVideo",
        "RoomMessageUnknown",
        "MatrixRoom",
        "RoomSendResponse",
        "RoomSendError",
        "RoomGetEventResponse",
        "RoomGetEventError",
        "RoomPutStateResponse",
        "RoomPutStateError",
        "SyncResponse",
        "UploadResponse",
        "UploadError",
        "MemoryDownloadResponse",
        "DiskDownloadResponse",
        "DownloadError",
    )
    missing_nio = [name for name in required_nio if not hasattr(nio, name)]
    if missing_nio:
        return False, f"matrix-nio missing required API: {', '.join(missing_nio)}"
    try:
        from nio.crypto.attachments import decrypt_attachment  # type: ignore[import-not-found]
    except Exception as exc:
        return False, f"matrix-nio attachment decrypt import_error={type(exc).__name__}: {exc}"
    if not callable(decrypt_attachment):
        return False, "matrix-nio attachment decrypt is not callable"
    if not hasattr(niobot, "NioBot"):
        return False, "nio-bot missing NioBot"
    start_params = inspect.signature(niobot.NioBot.start).parameters
    send_params = inspect.signature(niobot.NioBot.send_message).parameters
    add_reaction_params = inspect.signature(niobot.NioBot.add_reaction).parameters
    delete_message_params = inspect.signature(niobot.NioBot.delete_message).parameters
    edit_message_params = inspect.signature(niobot.NioBot.edit_message).parameters
    update_room_topic_params = inspect.signature(niobot.NioBot.update_room_topic).parameters
    fetch_message_params = inspect.signature(niobot.NioBot.fetch_message).parameters
    client_params = inspect.signature(niobot.NioBot).parameters
    upload_params = inspect.signature(nio.AsyncClient.upload).parameters
    matrix_room_params = inspect.signature(nio.MatrixRoom).parameters
    download_params = inspect.signature(nio.AsyncClient.download).parameters
    room_get_event_params = inspect.signature(nio.AsyncClient.room_get_event).parameters
    room_send_params = inspect.signature(nio.AsyncClient.room_send).parameters
    room_put_state_params = inspect.signature(nio.AsyncClient.room_put_state).parameters
    room_typing_params = inspect.signature(nio.AsyncClient.room_typing).parameters
    room_redact_params = inspect.signature(nio.AsyncClient.room_redact).parameters
    update_receipt_params = inspect.signature(nio.AsyncClient.update_receipt_marker).parameters
    expectations = {
        "NioBot.command_prefix": "command_prefix" in client_params,
        "NioBot.start.access_token": "access_token" in start_params,
        "NioBot.send_message.file": "file" in send_params,
        "NioBot.send_message.message_type": "message_type" in send_params,
        "NioBot.send_message.reply_to": "reply_to" in send_params,
        "NioBot.add_reaction.emoji": "emoji" in add_reaction_params,
        "NioBot.delete_message.reason": "reason" in delete_message_params,
        "NioBot.edit_message.content": "content" in edit_message_params,
        "NioBot.edit_message.message_type": "message_type" in edit_message_params,
        "NioBot.update_room_topic.room_id": "room_id" in update_room_topic_params,
        "NioBot.update_room_topic.topic": "topic" in update_room_topic_params,
        "NioBot.fetch_message.room_id": "room_id" in fetch_message_params,
        "NioBot.fetch_message.event_id": "event_id" in fetch_message_params,
        "AsyncClient.upload.filesize": "filesize" in upload_params,
        "AsyncClient.upload.encrypt": "encrypt" in upload_params,
        "MatrixRoom.encrypted": "encrypted" in matrix_room_params,
        "AsyncClient.download.mxc": "mxc" in download_params,
        "AsyncClient.room_get_event.event_id": "event_id" in room_get_event_params,
        "AsyncClient.room_send.content": "content" in room_send_params,
        "AsyncClient.room_put_state.content": "content" in room_put_state_params,
        "AsyncClient.room_put_state.state_key": "state_key" in room_put_state_params,
        "AsyncClient.room_typing.timeout": "timeout" in room_typing_params,
        "AsyncClient.room_redact.reason": "reason" in room_redact_params,
        "AsyncClient.update_receipt_marker.receipt_type": "receipt_type" in update_receipt_params,
        "nio.ReceiptType.read": hasattr(getattr(nio, "ReceiptType", object), "read"),
    }
    failures = [name for name, ok in expectations.items() if not ok]
    if failures:
        return False, f"nio-bot/matrix-nio contract missing: {', '.join(failures)}"
    try:
        matrix_room = nio.MatrixRoom("!check:example", "@bot:example", encrypted=True)
    except Exception as exc:
        return False, f"matrix-nio MatrixRoom construction_error={type(exc).__name__}: {exc}"
    if getattr(matrix_room, "encrypted", None) is not True:
        return False, "matrix-nio MatrixRoom did not preserve encrypted=True"
    try:
        requirements = importlib.metadata.metadata("nio-bot").get_all("Requires-Dist") or []
    except importlib.metadata.PackageNotFoundError:
        requirements = []
    declared = next((value for value in requirements if value.startswith("matrix-nio ")), "matrix-nio <unknown>")
    installed = importlib.metadata.version("matrix-nio")
    return True, f"nio-bot/matrix-nio runtime_contract=ok matrix-nio={installed} nio-bot_declares='{declared}'"


def _check_local_transcription_contract() -> tuple[bool, str]:
    try:
        from TeeBotus.core.local_transcription import check_local_transcription_backend
        from TeeBotus.instructions import BotInstructions
    except Exception as exc:
        return False, f"local transcription import_error={type(exc).__name__}: {exc}"
    health = check_local_transcription_backend(
        "check",
        BotInstructions(openai_transcription_backend="local", local_transcription_model="tiny"),
    )
    if health is None:
        return False, "local transcription health missing for local backend"
    if not health.ok:
        return False, f"local transcription unavailable model={health.model} error={health.error or '<missing>'}"
    if health.engine != "faster-whisper" and not health.engine.endswith("/whisper"):
        return False, f"local transcription unexpected engine={health.engine or '<missing>'}"
    return True, f"local transcription contract=ok backend={health.backend} model={health.model} engine={health.engine}"


def _check_matrix_file_contract() -> tuple[bool, str]:
    try:
        from niobot.attachment import AudioAttachment, FileAttachment, ImageAttachment, VideoAttachment  # type: ignore[import-not-found]
    except Exception as exc:
        return False, f"nio-bot attachment import_error={type(exc).__name__}: {exc}"
    try:
        attachment = FileAttachment(
            BytesIO(b"ok"),
            file_name="check.txt",
            mime_type="text/plain",
            size_bytes=2,
        )
    except Exception as exc:
        return False, f"nio-bot FileAttachment construction_error={type(exc).__name__}: {exc}"
    if attachment.file_name != "check.txt" or attachment.mime_type != "text/plain" or attachment.size != 2:
        return False, "nio-bot FileAttachment did not preserve filename/mime/size"
    body = attachment.as_body("Check")
    expected_msgtypes = {
        "file": body,
        "image": ImageAttachment(BytesIO(b"ok"), file_name="check.jpg", mime_type="image/jpeg", size_bytes=2).as_body("Check"),
        "audio": AudioAttachment(BytesIO(b"ok"), file_name="check.ogg", mime_type="audio/ogg", size_bytes=2).as_body("Check"),
        "video": VideoAttachment(BytesIO(b"ok"), file_name="check.mp4", mime_type="video/mp4", size_bytes=2).as_body("Check"),
    }
    failures = [
        f"{name}={payload.get('msgtype')}"
        for name, payload in expected_msgtypes.items()
        if payload.get("msgtype") != f"m.{name}"
    ]
    ok = not failures and body.get("body") == "Check" and body.get("filename") == "check.txt"
    details = "ok" if ok else f"invalid {' '.join(failures)}"
    return ok, f"nio-bot attachment contract={details} body_keys={','.join(sorted(body.keys()))}"


def _check_signalbot_context_contract() -> tuple[bool, str]:
    try:
        import signalbot  # type: ignore[import-not-found]
        from signalbot.context import Context  # type: ignore[import-not-found]
        from signalbot import Command, Config, LinkPreview, SignalBot  # type: ignore[import-not-found]
        from signalbot.message import Message, MessageType  # type: ignore[import-not-found]
        from TeeBotus.runtime.signal_runner import _patch_signalbot_signal_cli_api_about
    except Exception as exc:
        return False, f"signalbot Context import_error={type(exc).__name__}: {exc}"
    _patch_signalbot_signal_cli_api_about(signalbot)
    missing = [
        name
        for name in ("send", "reply", "edit", "start_typing", "stop_typing", "remote_delete", "react", "receipt")
        if not hasattr(Context, name)
    ]
    if missing:
        return False, f"signalbot Context missing required API: {', '.join(missing)}"
    send_params = inspect.signature(Context.send).parameters
    reply_params = inspect.signature(Context.reply).parameters
    edit_params = inspect.signature(Context.edit).parameters
    bot_send_params = inspect.signature(SignalBot.send).parameters
    bot_register_params = inspect.signature(SignalBot.register).parameters
    bot_start_params = inspect.signature(SignalBot.start).parameters
    bot_start_typing_params = inspect.signature(SignalBot.start_typing).parameters
    bot_stop_typing_params = inspect.signature(SignalBot.stop_typing).parameters
    bot_remote_delete_params = inspect.signature(SignalBot.remote_delete).parameters
    bot_react_params = inspect.signature(SignalBot.react).parameters
    bot_receipt_params = inspect.signature(SignalBot.receipt).parameters
    bot_poll_params = inspect.signature(SignalBot.poll).parameters
    bot_get_group_params = inspect.signature(SignalBot.get_group).parameters
    bot_update_contact_params = inspect.signature(SignalBot.update_contact).parameters
    bot_update_group_params = inspect.signature(SignalBot.update_group).parameters
    bot_delete_attachment_params = inspect.signature(SignalBot.delete_attachment).parameters
    config_params = inspect.signature(Config).parameters
    message_params = inspect.signature(Message).parameters
    link_preview_params = inspect.signature(LinkPreview).parameters
    signal_api = getattr(getattr(signalbot, "api", None), "SignalAPI", None)
    connection_mode = getattr(getattr(signalbot, "api", None), "ConnectionMode", None)
    delete_params = inspect.signature(Context.remote_delete).parameters
    react_params = inspect.signature(Context.react).parameters
    receipt_params = inspect.signature(Context.receipt).parameters
    expectations = {
        "Config.signal_service": "signal_service" in config_params,
        "Config.phone_number": "phone_number" in config_params,
        "Config.storage": "storage" in config_params,
        "Config.connection_mode": "connection_mode" in config_params,
        "Config.download_attachments": "download_attachments" in config_params,
        "InMemoryConfig": hasattr(signalbot, "InMemoryConfig"),
        "ConnectionMode.HTTP_ONLY": hasattr(connection_mode, "HTTP_ONLY"),
        "ConnectionMode.HTTPS_ONLY": hasattr(connection_mode, "HTTPS_ONLY"),
        "Context.send.base64_attachments": "base64_attachments" in send_params,
        "Context.send.mentions": "mentions" in send_params,
        "Context.send.text_mode": "text_mode" in send_params,
        "Context.send.view_once": "view_once" in send_params,
        "Context.send.link_preview": "link_preview" in send_params,
        "Context.reply.base64_attachments": "base64_attachments" in reply_params,
        "Context.reply.mentions": "mentions" in reply_params,
        "Context.reply.text_mode": "text_mode" in reply_params,
        "Context.reply.view_once": "view_once" in reply_params,
        "Context.reply.link_preview": "link_preview" in reply_params,
        "Context.edit.edit_timestamp": "edit_timestamp" in edit_params,
        "Context.edit.mentions": "mentions" in edit_params,
        "Context.edit.text_mode": "text_mode" in edit_params,
        "Context.edit.view_once": "view_once" in edit_params,
        "Context.edit.link_preview": "link_preview" in edit_params,
        "Context.react.emoji": "emoji" in react_params,
        "Context.receipt.receipt_type": "receipt_type" in receipt_params,
        "SignalBot.send.receiver": "receiver" in bot_send_params,
        "SignalBot.send.base64_attachments": "base64_attachments" in bot_send_params,
        "SignalBot.send.edit_timestamp": "edit_timestamp" in bot_send_params,
        "SignalBot.send.mentions": "mentions" in bot_send_params,
        "SignalBot.send.text_mode": "text_mode" in bot_send_params,
        "SignalBot.send.view_once": "view_once" in bot_send_params,
        "SignalBot.send.link_preview": "link_preview" in bot_send_params,
        "SignalBot.send.quote_author": "quote_author" in bot_send_params,
        "SignalBot.send.quote_mentions": "quote_mentions" in bot_send_params,
        "SignalBot.send.quote_message": "quote_message" in bot_send_params,
        "SignalBot.send.quote_timestamp": "quote_timestamp" in bot_send_params,
        "SignalBot.register.command": "command" in bot_register_params,
        "SignalBot.start.run_forever": "run_forever" in bot_start_params,
        "SignalBot.signal_cli_rest_api_mode": hasattr(SignalBot, "signal_cli_rest_api_mode"),
        "SignalBot.signal_cli_rest_api_version": hasattr(SignalBot, "signal_cli_rest_api_version"),
        "SignalBot.react.message": "message" in bot_react_params,
        "SignalBot.react.emoji": "emoji" in bot_react_params,
        "SignalBot.receipt.message": "message" in bot_receipt_params,
        "SignalBot.receipt.receipt_type": "receipt_type" in bot_receipt_params,
        "SignalBot.poll.receiver": "receiver" in bot_poll_params,
        "SignalBot.poll.answers": "answers" in bot_poll_params,
        "SignalBot.poll.allow_multiple_selections": "allow_multiple_selections" in bot_poll_params,
        "SignalBot.get_group.internal_id": "internal_id" in bot_get_group_params,
        "SignalBot.update_contact.receiver": "receiver" in bot_update_contact_params,
        "SignalBot.update_contact.expiration_in_seconds": "expiration_in_seconds" in bot_update_contact_params,
        "SignalBot.update_contact.name": "name" in bot_update_contact_params,
        "SignalBot.update_group.group_id": "group_id" in bot_update_group_params,
        "SignalBot.update_group.base64_avatar": "base64_avatar" in bot_update_group_params,
        "SignalBot.update_group.description": "description" in bot_update_group_params,
        "SignalBot.update_group.expiration_in_seconds": "expiration_in_seconds" in bot_update_group_params,
        "SignalBot.update_group.name": "name" in bot_update_group_params,
        "SignalBot.delete_attachment.attachment_filename": "attachment_filename" in bot_delete_attachment_params,
        "SignalBot.start_typing.receiver": "receiver" in bot_start_typing_params,
        "SignalBot.stop_typing.receiver": "receiver" in bot_stop_typing_params,
        "SignalBot.remote_delete.receiver": "receiver" in bot_remote_delete_params,
        "SignalBot.remote_delete.timestamp": "timestamp" in bot_remote_delete_params,
        "Context.remote_delete.timestamp": "timestamp" in delete_params,
        "Message.link_previews": "link_previews" in message_params,
        "Message.mentions": "mentions" in message_params,
        "Message.quote": "quote" in message_params,
        "Message.target_sent_timestamp": "target_sent_timestamp" in message_params,
        "Message.remote_delete_timestamp": "remote_delete_timestamp" in message_params,
        "MessageType.DATA_MESSAGE": hasattr(MessageType, "DATA_MESSAGE"),
        "MessageType.EDIT_MESSAGE": hasattr(MessageType, "EDIT_MESSAGE"),
        "MessageType.DELETE_MESSAGE": hasattr(MessageType, "DELETE_MESSAGE"),
        "MessageType.REACTION_MESSAGE": hasattr(MessageType, "REACTION_MESSAGE"),
        "SignalAPI.get_signal_cli_about": hasattr(signal_api, "get_signal_cli_about"),
        "SignalAPI.get_signal_cli_rest_api_version": hasattr(signal_api, "get_signal_cli_rest_api_version"),
        "SignalAPI.get_signal_cli_rest_api_mode": hasattr(signal_api, "get_signal_cli_rest_api_mode"),
        "LinkPreview.base64_thumbnail": "base64_thumbnail" in link_preview_params,
        "LinkPreview.title": "title" in link_preview_params,
        "LinkPreview.description": "description" in link_preview_params,
        "LinkPreview.url": "url" in link_preview_params,
        "LinkPreview.id": "id" in link_preview_params,
    }
    failures = [name for name, ok in expectations.items() if not ok]
    if failures:
        return False, f"signalbot Context contract missing: {', '.join(failures)}"
    class ContractCommand(Command):
        def __init__(self) -> None:
            super().__init__()
            self.setup_called = False

        def setup(self) -> None:
            self.setup_called = True

        async def handle(self, context: object) -> None:
            return None

    try:
        command = ContractCommand()
        bot = SignalBot(
            signalbot.Config(
                signal_service="127.0.0.1:8080",
                phone_number="+491234",
                storage=signalbot.InMemoryConfig(),
                connection_mode=signalbot.api.ConnectionMode.HTTP_ONLY,
            )
        )
        bot.register(command)
    except Exception as exc:
        return False, f"signalbot register contract_error={type(exc).__name__}: {exc}"
    if command.bot is not bot or not command.setup_called:
        return False, "signalbot register did not attach bot and run setup"
    return True, "signalbot Context contract=ok methods=register,start,send,reply,edit,react,receipt,poll,get_group,update_contact,update_group,start_typing,stop_typing,remote_delete,delete_attachment,about config=in_memory"


def _check_executable_version(binary: str, expected: str, args: list[str]) -> tuple[bool, str]:
    path = _which(binary)
    if path is None:
        return False, f"{binary} missing from PATH, expected {expected}"
    try:
        result = subprocess.run(
            [path, *args],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"{binary} could not be executed: {exc}"
    output = " ".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    ok = result.returncode == 0 and expected in output
    return ok, f"{binary} path={path} version_output={output or '<empty>'} expected={expected}"


def _check_signal_cli_rest_api_binary(expected: str) -> tuple[bool, str]:
    path = _which("signal-cli-rest-api")
    if path is None:
        incompatible = _which("signal-cli-api")
        if incompatible is not None:
            return False, f"signal-cli-rest-api missing, found incompatible Rust signal-cli-api at {incompatible}; expected {expected}"
        return False, f"signal-cli-rest-api missing from PATH, expected {expected}"
    return True, f"signal-cli-rest-api path={path} expected={expected} runtime_version_checked_via_/v1/about"


def _check_signal_cli_rest_api_service(base_url: str, expected: str) -> tuple[bool, str]:
    url = base_url.rstrip("/") + "/v1/about"
    try:
        with urlopen(url, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, json.JSONDecodeError) as exc:
        return False, f"signal-cli-rest-api service unavailable url={url}: {exc}"
    version = str(payload.get("version") or "").strip()
    mode = str(payload.get("mode") or "").strip()
    ok = version == expected and mode == "json-rpc"
    return ok, f"signal-cli-rest-api service version={version or '<missing>'} expected={expected} mode={mode or '<missing>'}"


def _which(binary: str) -> str | None:
    path = shutil.which(binary)
    if path is not None:
        return path
    for directory in (Path.home() / ".local" / "bin", Path.home() / ".cargo" / "bin"):
        candidate = directory / binary
        if os.access(candidate, os.X_OK):
            return str(candidate)
    return None


if __name__ == "__main__":
    raise SystemExit(main())
