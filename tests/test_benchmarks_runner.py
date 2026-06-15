from __future__ import annotations

import json

from scripts.run_benchmarks import main, render_markdown, run_benchmarks


def test_quick_benchmark_suite_covers_plan_core_categories() -> None:
    suite = run_benchmarks(entries=2, iterations=1, quick=True)

    categories = {result["category"] for result in suite["results"]}

    assert suite["schema_version"] == 1
    assert suite["ok"] is True
    assert {
        "account_memory",
        "bibliothekar",
        "llm_router",
        "proactive_agent",
        "messenger_adapters",
        "transcription_youtube",
        "status_doctor",
        "database_fallback",
        "langgraph_flows",
    }.issubset(categories)
    assert all("total_ms" in result for result in suite["results"])
    assert all("throughput_ops_s" in result for result in suite["results"])
    assert any(result["name"] == "memory_postgres" and result["skipped"] is True for result in suite["results"])


def test_benchmark_markdown_contains_comparison_table() -> None:
    suite = run_benchmarks(entries=1, iterations=1, quick=True)

    markdown = render_markdown(suite)

    assert "# TeeBotus Benchmarks" in markdown
    assert "| name | category | status | iterations |" in markdown
    assert "memory_jsonl" in markdown
    assert "langgraph_bibliothekar_deep_query" in markdown
    assert "keine echten Provider-Calls" in markdown


def test_run_benchmarks_cli_writes_markdown_and_json(tmp_path) -> None:
    markdown_path = tmp_path / "benchmarks.md"
    json_path = tmp_path / "benchmarks.json"

    result = main(
        [
            "--quick",
            "--entries",
            "1",
            "--iterations",
            "1",
            "--output",
            str(markdown_path),
            "--json-output",
            str(json_path),
        ]
    )

    assert result == 0
    assert markdown_path.exists()
    assert json_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["results"]
    assert "TeeBotus Benchmarks" in markdown_path.read_text(encoding="utf-8")
