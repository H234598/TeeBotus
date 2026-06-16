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
    assert "openai" in report["extras"]["llm"]["declared"]
    assert "ollama" in report["extras"]["llm"]["declared"]
    assert report["extras"]["llm"]["version_mismatches"] == []
    assert "haystack-ai==2.30.1" in report["extras"]["rag"]["declared"]
    assert "qdrant-haystack==10.3.0" in report["extras"]["rag"]["declared"]
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
