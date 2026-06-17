from __future__ import annotations

import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _pyproject() -> dict:
    return tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_pyproject_declares_plan1_optional_dependency_groups() -> None:
    optional = _pyproject()["project"]["optional-dependencies"]

    assert _pyproject()["project"]["requires-python"] == ">=3.11"
    assert set(optional) >= {"dev", "llm", "agents", "rag", "tools"}
    assert set(optional["dev"]) >= {"pytest", "pytest-cov", "ruff", "mypy", "pip-audit"}
    assert set(optional["llm"]) >= {"litellm==1.83.7", "python-dotenv==1.0.1", "openai==2.30.0", "ollama==0.6.2"}
    assert set(optional["agents"]) >= {"pydantic-ai-slim==1.107.0", "langgraph==1.2.5"}
    assert set(optional["rag"]) >= {
        "haystack-ai==2.30.1",
        "qdrant-haystack==10.3.0",
        "sentence-transformers==5.5.1",
        "pypdf==6.13.2",
        "pymupdf==1.27.2.3",
        "ebooklib==0.20",
        "beautifulsoup4==4.14.3",
        "llama-index-core==0.14.22",
    }
    assert set(optional["tools"]) >= {"fastmcp==2.0.0"}


def test_pyproject_litellm_extra_blocks_known_bad_versions() -> None:
    llm_deps = _pyproject()["project"]["optional-dependencies"]["llm"]

    assert "litellm==1.83.7" in llm_deps
    assert "python-dotenv==1.0.1" in llm_deps
    assert "openai==2.30.0" in llm_deps
    assert "ollama==0.6.2" in llm_deps
    assert "litellm==1.82.7" not in llm_deps
    assert "litellm==1.82.8" not in llm_deps


def test_pytest_config_points_at_local_tests() -> None:
    pytest_config = _pyproject()["tool"]["pytest"]["ini_options"]

    assert pytest_config["testpaths"] == ["tests"]
    assert pytest_config["pythonpath"] == ["."]


def test_pyproject_declares_operator_scripts() -> None:
    scripts = _pyproject()["project"]["scripts"]

    assert scripts["teebotus-bibliothekar"] == "TeeBotus.bibliothekar.cli:main"
    assert scripts["teebotus-qdrant-systemd"] == "TeeBotus.qdrant_systemd:main"
    assert scripts["teebotus-embedding"] == "TeeBotus.embedding.cli:main"
