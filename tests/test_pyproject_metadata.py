from __future__ import annotations

import re
import tomllib
from pathlib import Path

from TeeBotus import __version__


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


def _pyproject() -> dict:
    return tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_package_version_is_semver() -> None:
    assert SEMVER_RE.fullmatch(__version__)
    assert _pyproject()["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "TeeBotus.__version__"}


def test_pyproject_declares_plan1_optional_dependency_groups() -> None:
    optional = _pyproject()["project"]["optional-dependencies"]

    assert _pyproject()["project"]["requires-python"] == ">=3.11"
    assert set(optional) >= {"dev", "llm", "agents", "rag", "tools"}
    assert set(optional["dev"]) >= {"pytest", "pytest-cov", "ruff", "mypy", "pip-audit"}
    assert any(dependency.startswith("litellm==1.89.2") for dependency in optional["llm"])
    assert any(dependency.startswith("openai==2.43.0;") for dependency in optional["llm"])
    assert any(dependency.startswith("openai==2.30.0;") for dependency in optional["llm"])
    assert "ollama==0.6.2" in optional["llm"]
    assert set(optional["agents"]) >= {"pydantic-ai-slim==1.107.0", "langgraph==1.2.6"}
    assert set(optional["rag"]) >= {
        "haystack-ai==2.30.2",
        "qdrant-haystack==10.3.0",
        "sentence-transformers==5.6.0",
        "pypdf==6.13.3",
        "pymupdf==1.27.2.3",
        "ebooklib==0.20",
        "beautifulsoup4==4.15.0",
        "llama-index-core==0.14.22",
    }
    assert "fastmcp==3.4.2" in optional["tools"]
    assert "python-dotenv==1.2.2" in optional["tools"]


def test_pyproject_litellm_extra_blocks_known_bad_versions() -> None:
    llm_deps = _pyproject()["project"]["optional-dependencies"]["llm"]

    assert any(dependency.startswith("litellm==1.89.2") for dependency in llm_deps)
    assert any(dependency.startswith("openai==2.43.0;") for dependency in llm_deps)
    assert any(dependency.startswith("openai==2.30.0;") for dependency in llm_deps)
    assert "ollama==0.6.2" in llm_deps
    assert "litellm==1.82.7" not in llm_deps
    assert "litellm==1.82.8" not in llm_deps


def test_requirements_defers_sequenced_llm_and_tool_dependencies() -> None:
    requirements = {
        line.strip()
        for line in (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }

    blocked_prefixes = ("litellm", "openai", "python-dotenv", "fastmcp", "nio-bot", "matrix-nio", "h11")
    assert not any(dependency.startswith(blocked_prefixes) for dependency in requirements)
    assert "psycopg[binary]==3.3.4" in requirements


def test_pytest_config_points_at_local_tests() -> None:
    pytest_config = _pyproject()["tool"]["pytest"]["ini_options"]

    assert pytest_config["testpaths"] == ["tests"]
    assert pytest_config["pythonpath"] == ["."]


def test_pyproject_declares_operator_scripts() -> None:
    scripts = _pyproject()["project"]["scripts"]

    assert scripts["teebotus-bibliothekar"] == "TeeBotus.bibliothekar.cli:main"
    assert scripts["teebotus-qdrant-systemd"] == "TeeBotus.qdrant_systemd:main"
    assert scripts["teebotus-embedding"] == "TeeBotus.embedding.cli:main"
    assert scripts["teebotus-cinnamon-applet"] == "TeeBotus.cinnamon_applet:main"
