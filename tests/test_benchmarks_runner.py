from __future__ import annotations

import json

from TeeBotus import __version__ as TEEBOTUS_VERSION
from scripts.run_benchmarks import main, render_markdown, run_benchmarks


def test_quick_benchmark_suite_covers_plan_core_categories() -> None:
    suite = run_benchmarks(entries=2, iterations=1, quick=True)

    categories = {result["category"] for result in suite["results"]}

    assert suite["schema_version"] == 1
    assert suite["ok"] is True
    assert suite["context"]["cpu_count"] >= 1
    assert suite["context"]["dependencies"]["teebotus"] == {"version": TEEBOTUS_VERSION, "status": "worktree"}
    assert suite["context"]["dependencies"]["litellm"]["status"] in {"installed", "missing"}
    assert suite["context"]["dependencies"]["signalbot"]["version"]
    assert suite["comparisons"]["auto_switching"] is False
    assert suite["regression"]["status"] == "not_configured"
    assert suite["regression"]["failed"] is False
    rankings = {ranking["category"]: ranking for ranking in suite["comparisons"]["stable_backend_rankings"]}
    assert {"account_memory", "bibliothekar", "langgraph_flows"}.issubset(rankings)
    assert rankings["account_memory"]["fastest_stable"]
    assert rankings["account_memory"]["candidates"]
    assert [candidate["rank"] for candidate in rankings["account_memory"]["candidates"]] == list(
        range(1, len(rankings["account_memory"]["candidates"]) + 1)
    )
    assert any(skipped["name"] == "memory_postgres" for skipped in rankings["account_memory"]["skipped"])
    assert {
        "account_memory",
        "bibliothekar",
        "llm_router",
        "pydantic_ai",
        "proactive_agent",
        "messenger_adapters",
        "transcription_youtube",
        "status_doctor",
        "database_fallback",
        "langgraph_flows",
        "mcp_tools",
    }.issubset(categories)
    assert all("total_ms" in result for result in suite["results"])
    assert all("throughput_ops_s" in result for result in suite["results"])
    assert all("mode" in result and "live" in result for result in suite["results"])
    missing_sizes = [
        result["name"]
        for result in suite["results"]
        if not result["skipped"] and result["payload_bytes"] <= 0 and result["index_bytes"] <= 0
    ]
    assert missing_sizes == []
    assert any(result["name"] == "memory_postgres" and result["skipped"] is True and result["mode"] == "live_optional" for result in suite["results"])
    migration = next(result for result in suite["results"] if result["name"] == "memory_migration_jsonl_to_sqlite")
    assert migration["ok"] is True
    assert migration["details"]["verified"] is True
    assert any(result["name"] == "bibliothekar_local_query" for result in suite["results"])
    local_library = next(result for result in suite["results"] if result["name"] == "bibliothekar_local_query")
    haystack_library = next(result for result in suite["results"] if result["name"] == "bibliothekar_haystack_fake_query")
    assert local_library["details"]["fixture"] == "tests/fixtures/books"
    assert haystack_library["details"]["fixture"] == "tests/fixtures/books"
    assert local_library["details"]["selected_chunks"] >= 1
    assert haystack_library["details"]["selected_chunks"] >= 1
    assert local_library["details"]["citation_payload_bytes"] > 0
    assert haystack_library["details"]["citation_payload_bytes"] > 0
    assert local_library["details"]["has_citation_format"] is True
    assert haystack_library["details"]["has_citation_format"] is True
    assert haystack_library["details"]["private_filter_selected_chunks"] >= 1
    assert haystack_library["details"]["private_filter_payload_leaked"] is False
    assert any(result["name"] == "langgraph_bibliothekar_linear" for result in suite["results"])
    fake_graph = next(result for result in suite["results"] if result["name"] == "langgraph_bibliothekar_fake_installed")
    assert fake_graph["details"]["mode"] == "fake_installed_langgraph"
    assert fake_graph["details"]["node_sequence"] == ["classify", "retrieve", "rerank", "answer", "citation_check", "fallback"]
    llm_router = next(result for result in suite["results"] if result["name"] == "llm_router_structured_decision")
    assert llm_router["details"]["runtime_provider"] == "litellm"
    assert llm_router["details"]["runtime_model"] == "ollama_chat/llama3.1:8b"
    assert llm_router["details"]["memory_candidate_kind"] == "therapy_goal"
    assert llm_router["details"]["remote_fallback_default_enabled"] is False
    assert llm_router["details"]["default_fallback_models"] == []
    assert llm_router["details"]["explicit_remote_fallback_enabled"] is True
    assert llm_router["details"]["explicit_remote_fallback_models"] == ["groq/llama-3.1-8b-instant"]
    assert llm_router["details"]["explicit_remote_fallback_api_key_env"] == "GROQ_API_KEY"
    assert llm_router["details"]["explicit_remote_fallback_api_key_mapped"] is True
    assert "benchmark-groq-key" not in json.dumps(suite, ensure_ascii=False)
    assert llm_router["details"]["direct_remote_fallback_default_models"] == ["ollama_chat/qwen2.5:7b"]
    assert llm_router["details"]["direct_remote_fallback_allowed_models"] == [
        "groq/llama-3.1-8b-instant",
        "ollama_chat/qwen2.5:7b",
    ]
    assert llm_router["details"]["network_calls"] == 0
    pydantic_ai = next(result for result in suite["results"] if result["name"] == "pydantic_structured_decisions")
    assert pydantic_ai["ok"] is True
    assert pydantic_ai["category"] == "pydantic_ai"
    assert pydantic_ai["details"]["schemas"] == [
        "BibliothekarQueryDecision",
        "MemoryCandidate",
        "ReminderDecision",
        "ProactiveToolCallDecision",
    ]
    assert pydantic_ai["details"]["fake_agent_calls"] == 1
    assert pydantic_ai["details"]["latest_runner_query"] == "Therapie Schlaf"
    assert pydantic_ai["details"]["network_calls"] == 0
    proactive = next(result for result in suite["results"] if result["name"] == "proactive_tool_plan_due_dispatch_gates")
    assert proactive["ok"] is True
    assert proactive["details"]["tool_schema_validated"] is True
    assert proactive["details"]["tool_plan_errors"] == []
    assert len(proactive["details"]["tool_queued_item_ids"]) == 2
    assert proactive["details"]["sent"] == 1
    assert proactive["details"]["review_pending"] == 1
    assert proactive["details"]["dispatch_simulated"] == 1
    assert proactive["details"]["dispatch_statuses"] == ["sent"]
    assert proactive["details"]["policy_allowed"] is True
    assert proactive["details"]["network_calls"] == 0
    youtube_job = next(result for result in suite["results"] if result["name"] == "youtube_local_job_queue_no_llm")
    assert youtube_job["ok"] is True
    assert youtube_job["details"]["started_jobs"] == 1
    assert youtube_job["details"]["background_dispatches"] == 1
    assert youtube_job["details"]["llm_calls"] == 0
    assert youtube_job["details"]["network_calls"] == 0
    youtube_pipeline = next(result for result in suite["results"] if result["name"] == "youtube_local_pipeline_cache_no_openai")
    assert youtube_pipeline["ok"] is True
    assert youtube_pipeline["details"]["subtitle_attempts"] == 1
    assert youtube_pipeline["details"]["whisper_calls"] == 1
    assert youtube_pipeline["details"]["cache_reads"] == 1
    assert youtube_pipeline["details"]["cache_files"] == 1
    assert youtube_pipeline["details"]["live_chunks"] == 1
    assert youtube_pipeline["details"]["openai_calls"] == 0
    assert youtube_pipeline["details"]["network_calls"] == 0
    messenger = next(result for result in suite["results"] if result["name"] == "messenger_adapter_runtime_contracts")
    assert messenger["ok"] is True
    assert messenger["details"]["channels"] == ["telegram", "signal", "matrix"]
    assert messenger["details"]["event_contracts"] == {"telegram": True, "signal": True, "matrix": True}
    assert messenger["details"]["send_contracts"] == {"telegram": True, "signal": True, "matrix": True}
    assert messenger["details"]["fake_network_sends"] == 3
    assert messenger["details"]["network_calls"] == 0
    status_doctor = next(result for result in suite["results"] if result["name"] == "status_doctor_runtime_dependency_health")
    assert status_doctor["ok"] is True
    assert status_doctor["details"]["runtime_instances"] == ["Bench"]
    assert status_doctor["details"]["runtime_channels"] == ["telegram", "signal", "matrix"]
    assert status_doctor["details"]["runtime_accounts"] == 3
    assert status_doctor["details"]["bibliothekar_status"] == "ready"
    assert status_doctor["details"]["bibliothekar_backend"] == "local"
    assert status_doctor["details"]["dependency_ok"] is True
    assert any("pyproject plan2 contract=ok" in message for message in status_doctor["details"]["dependency_checks"])
    assert any("litellm supply_chain_guard=ok" in message for message in status_doctor["details"]["dependency_checks"])
    database_fallback = next(result for result in suite["results"] if result["name"] == "database_fallback_policy")
    assert database_fallback["ok"] is True
    assert database_fallback["details"]["primary"] == "sqlite-primary"
    assert database_fallback["details"]["secondary"] == "sqlite-fallback"
    assert database_fallback["details"]["synced_entries"] is True
    assert database_fallback["details"]["synced_index"] is True
    assert database_fallback["details"]["fallback_warnings"] >= 1
    assert database_fallback["details"]["recovery_warnings"] >= 1


def test_benchmark_markdown_contains_comparison_table() -> None:
    suite = run_benchmarks(entries=1, iterations=1, quick=True)

    markdown = render_markdown(suite)

    assert "# TeeBotus Benchmarks" in markdown
    assert "## Dependencies" in markdown
    assert "| litellm |" in markdown
    assert "| name | category | status | mode | iterations | total_ms | throughput_ops_s | errors | payload_bytes | index_bytes | note | details |" in markdown
    assert "## Stable Backend Rankings" in markdown
    assert "## Regression Check" in markdown
    assert "status: not_configured" in markdown
    assert "| category | rank | name | mode | throughput_ops_s | total_ms | errors | note |" in markdown
    assert "Die Rangliste dokumentiert Messwerte nur" in markdown
    assert "memory_jsonl" in markdown
    assert "memory_migration_jsonl_to_sqlite" in markdown
    assert "bibliothekar_haystack_fake_query" in markdown
    assert "pydantic_structured_decisions" in markdown
    assert "langgraph_bibliothekar_deep_query" in markdown
    assert "langgraph_bibliothekar_fake_installed" in markdown
    assert "proactive_tool_plan_due_dispatch_gates" in markdown
    assert "messenger_adapter_runtime_contracts" in markdown
    assert "status_doctor_runtime_dependency_health" in markdown
    assert "youtube_local_job_queue_no_llm" in markdown
    assert "youtube_local_pipeline_cache_no_openai" in markdown
    assert "primary_failure_secondary_sync_recovery_warning" in markdown
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
    assert payload["comparisons"]["stable_backend_rankings"]
    assert payload["regression"]["status"] == "not_configured"
    assert "TeeBotus Benchmarks" in markdown_path.read_text(encoding="utf-8")


def test_run_benchmarks_compares_optional_baseline(tmp_path) -> None:
    baseline_path = tmp_path / "baseline.json"
    current = run_benchmarks(entries=1, iterations=1, quick=True)
    baseline = json.loads(json.dumps(current))
    for result in baseline["results"]:
        if result["name"] == "memory_jsonl":
            result["total_ms"] = max(float(result["total_ms"]) / 10.0, 0.001)
            result["throughput_ops_s"] = float(result["throughput_ops_s"]) * 10.0
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")

    suite = run_benchmarks(entries=1, iterations=1, quick=True, baseline_json=baseline_path)
    markdown = render_markdown(suite)

    assert suite["ok"] is False
    assert suite["regression"]["status"] == "failed"
    assert suite["regression"]["failed"] is True
    memory_jsonl = next(entry for entry in suite["regression"]["entries"] if entry["name"] == "memory_jsonl")
    assert memory_jsonl["status"] == "regressed"
    assert "memory_jsonl" in markdown
    assert "## Regression Check" in markdown
