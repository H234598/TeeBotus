from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "tests.yml"


def test_github_actions_runs_plan2_acceptance_with_all_extras() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "plan2-acceptance:" in workflow
    assert 'python -m pip install -e ".[dev,llm,rag,agents,tools]"' in workflow
    assert "python scripts/check_plan2_acceptance.py" in workflow
    assert "--skip-runtime-status" in workflow
    assert "--skip-adapter-deps" in workflow
    assert "--benchmark-output reports/teebotus-plan2-benchmarks.md" in workflow
    assert "--benchmark-json-output reports/teebotus-plan2-benchmarks.json" in workflow
