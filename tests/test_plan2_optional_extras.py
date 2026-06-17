from __future__ import annotations

import importlib.metadata

from scripts.check_plan2_optional_extras import build_optional_extras_report


def test_plan2_optional_extras_inventory_reports_declared_groups() -> None:
    report = build_optional_extras_report()

    assert report["schema_version"] == 1
    assert report["ok"] is True
    assert set(report["extras"]) == {"llm", "rag", "agents", "tools"}
    assert "litellm==1.83.7" in report["extras"]["llm"]["declared"]
    assert "python-dotenv==1.0.1" in report["extras"]["llm"]["declared"]
    assert "openai==2.30.0" in report["extras"]["llm"]["declared"]
    assert "ollama==0.6.2" in report["extras"]["llm"]["declared"]
    assert report["extras"]["llm"]["version_mismatches"] == []
    assert "haystack-ai==2.30.1" in report["extras"]["rag"]["declared"]
    assert "qdrant-haystack==10.3.0" in report["extras"]["rag"]["declared"]
    assert "beautifulsoup4==4.14.3" in report["extras"]["rag"]["declared"]
    assert "llama-index-core==0.14.22" in report["extras"]["rag"]["declared"]
    assert "pydantic-ai-slim==1.107.0" in report["extras"]["agents"]["declared"]
    assert "langgraph==1.2.5" in report["extras"]["agents"]["declared"]
    assert "fastmcp==2.0.0" in report["extras"]["tools"]["declared"]


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
    def version(package: str) -> str:
        if package == "litellm":
            return "1.82.7"
        return "999.0"

    monkeypatch.setattr("scripts.check_plan2_optional_extras.importlib.metadata.version", version)

    report = build_optional_extras_report(require_installed=True)

    assert report["ok"] is False
    assert {"name": "litellm", "expected": "1.83.7", "installed": "1.82.7"} in report["extras"]["llm"]["version_mismatches"]
    assert any("llm version mismatches" in error for error in report["errors"])


def test_plan2_optional_extras_blocks_compromised_litellm_even_when_versions_match(monkeypatch, tmp_path) -> None:
    payload = {
        "project": {
            "optional-dependencies": {
                "llm": ["litellm==1.82.7", "python-dotenv==1.0.1", "openai", "ollama"],
                "rag": ["haystack-ai==2.30.1", "beautifulsoup4==4.14.3"],
                "agents": ["pydantic-ai-slim==1.107.0"],
                "tools": ["fastmcp==2.0.0"],
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


def test_plan2_optional_extras_requires_exact_plan2_pins(monkeypatch, tmp_path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        _toml_for_optional_dependencies(
            {
                "llm": ["litellm==1.83.7", "python-dotenv==1.0.1", "openai", "ollama==0.6.2"],
                "rag": ["haystack-ai==2.30.1", "beautifulsoup4"],
                "agents": ["pydantic-ai-slim==1.107.0"],
                "tools": ["fastmcp==2.0.0"],
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
