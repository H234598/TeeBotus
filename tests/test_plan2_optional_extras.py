from __future__ import annotations

import importlib.metadata
import sys

from scripts.check_plan2_optional_extras import build_optional_extras_report


def _active_llm_versions() -> tuple[str, str]:
    if sys.version_info >= (3, 14):
        return "1.83.7", "1.0.1"
    return "1.84.0", "1.2.2"


def _active_fastmcp_version() -> str:
    if sys.version_info >= (3, 14):
        return "2.2.0"
    return "3.2.0"


def test_plan2_optional_extras_inventory_reports_declared_groups(monkeypatch) -> None:
    litellm_version, dotenv_version = _active_llm_versions()
    fastmcp_version = _active_fastmcp_version()
    safe_versions = {
        "litellm": litellm_version,
        "python-dotenv": dotenv_version,
        "fastmcp": fastmcp_version,
    }
    monkeypatch.setattr(
        "scripts.check_plan2_optional_extras.importlib.metadata.version",
        lambda package: safe_versions.get(package, "999.0"),
    )

    report = build_optional_extras_report()

    assert report["schema_version"] == 1
    assert report["ok"] is True
    assert set(report["extras"]) == {"llm", "rag", "agents", "tools"}
    assert any(dependency.startswith("litellm==1.84.0;") for dependency in report["extras"]["llm"]["declared"])
    assert any(dependency.startswith("python-dotenv==1.2.2;") for dependency in report["extras"]["llm"]["declared"])
    assert any(dependency.startswith("litellm==1.83.7;") for dependency in report["extras"]["llm"]["declared"])
    assert any(dependency.startswith("python-dotenv==1.0.1;") for dependency in report["extras"]["llm"]["declared"])
    assert f"litellm=={litellm_version}; python_version {'>=' if sys.version_info >= (3, 14) else '<'} '3.14'" in report["extras"]["llm"]["active_declared"]
    assert f"python-dotenv=={dotenv_version}; python_version {'>=' if sys.version_info >= (3, 14) else '<'} '3.14'" in report["extras"]["llm"]["active_declared"]
    assert "openai==2.30.0" in report["extras"]["llm"]["declared"]
    assert "ollama==0.6.2" in report["extras"]["llm"]["declared"]
    assert "haystack-ai==2.30.1" in report["extras"]["rag"]["declared"]
    assert "qdrant-haystack==10.3.0" in report["extras"]["rag"]["declared"]
    assert "beautifulsoup4==4.14.3" in report["extras"]["rag"]["declared"]
    assert "llama-index-core==0.14.22" in report["extras"]["rag"]["declared"]
    assert "pydantic-ai-slim==1.107.0" in report["extras"]["agents"]["declared"]
    assert "langgraph==1.2.5" in report["extras"]["agents"]["declared"]
    assert any(dependency.startswith("fastmcp==3.2.0;") for dependency in report["extras"]["tools"]["declared"])
    assert any(dependency.startswith("fastmcp==2.2.0;") for dependency in report["extras"]["tools"]["declared"])
    assert f"fastmcp=={fastmcp_version}; python_version {'>=' if sys.version_info >= (3, 14) else '<'} '3.14'" in report["extras"]["tools"]["active_declared"]


def test_plan2_optional_extras_strict_mode_fails_when_missing(monkeypatch) -> None:
    def missing(_package: str) -> str:
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr("scripts.check_plan2_optional_extras.importlib.metadata.version", missing)

    report = build_optional_extras_report(require_installed=True)

    assert report["ok"] is False
    assert any("llm missing installed packages" in error for error in report["errors"])
    assert any("rag missing installed packages" in error for error in report["errors"])
    assert any("agents missing installed packages" in error for error in report["errors"])
    assert any("tools missing installed packages" in error for error in report["errors"])


def test_plan2_optional_extras_strict_mode_fails_on_pinned_version_mismatch(monkeypatch) -> None:
    expected_litellm, _dotenv_version = _active_llm_versions()

    def version(package: str) -> str:
        if package == "litellm":
            return "1.82.7"
        return "999.0"

    monkeypatch.setattr("scripts.check_plan2_optional_extras.importlib.metadata.version", version)

    report = build_optional_extras_report(require_installed=True)

    assert report["ok"] is False
    assert {"name": "litellm", "expected": expected_litellm, "installed": "1.82.7"} in report["extras"]["llm"]["version_mismatches"]
    assert any("llm version mismatches" in error for error in report["errors"])


def test_plan2_optional_extras_blocks_compromised_litellm_even_when_versions_match(monkeypatch, tmp_path) -> None:
    payload = {
        "project": {
            "optional-dependencies": {
                "llm": ["litellm==1.82.7", "python-dotenv==1.2.2", "openai", "ollama"],
                "rag": ["haystack-ai==2.30.1", "beautifulsoup4==4.14.3"],
                "agents": ["pydantic-ai-slim==1.107.0"],
                "tools": ["fastmcp==3.2.0"],
            }
        }
    }
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_toml_for_optional_dependencies(payload["project"]["optional-dependencies"]), encoding="utf-8")

    def version(package: str) -> str:
        if package == "litellm":
            return "1.82.7"
        return "999.0"

    monkeypatch.setattr("scripts.check_plan2_optional_extras.importlib.metadata.version", version)

    report = build_optional_extras_report(require_installed=True, pyproject_path=pyproject)

    assert report["ok"] is False
    assert any("litellm pin 1.82.7 is blocked" in error for error in report["errors"])
    assert any("litellm installed 1.82.7 is blocked" in error for error in report["errors"])
    assert any("litellm pin 1.82.7 is below security minimum" in error for error in report["errors"])


def test_plan2_optional_extras_requires_exact_plan2_pins(monkeypatch, tmp_path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        _toml_for_optional_dependencies(
            {
                "llm": ["litellm==1.84.0", "python-dotenv==1.2.2", "openai", "ollama==0.6.2"],
                "rag": ["haystack-ai==2.30.1", "beautifulsoup4"],
                "agents": ["pydantic-ai-slim==1.107.0"],
                "tools": ["fastmcp==3.2.0"],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("scripts.check_plan2_optional_extras.importlib.metadata.version", lambda _package: "999.0")

    report = build_optional_extras_report(require_installed=True, pyproject_path=pyproject)

    assert report["ok"] is False
    assert "llm openai must be exactly pinned for Plan2" in report["errors"]
    assert "rag beautifulsoup4 must be exactly pinned for Plan2" in report["errors"]


def _toml_for_optional_dependencies(optional: dict[str, list[str]]) -> str:
    lines = ["[project]", 'name = "test"', 'version = "0.0.0"', "", "[project.optional-dependencies]"]
    for extra, requirements in optional.items():
        lines.append(f"{extra} = [")
        lines.extend(f'  "{requirement}",' for requirement in requirements)
        lines.append("]")
    return "\n".join(lines) + "\n"
