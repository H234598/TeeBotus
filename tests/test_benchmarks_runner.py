from __future__ import annotations

import importlib
import json
from pathlib import Path

from TeeBotus import __version__ as TEEBOTUS_VERSION
from TeeBotus.benchmarks import llm_routing
from TeeBotus.benchmarks import suite as benchmark_suite
from TeeBotus.runtime.qdrant_memory import QDRANT_MEMORY_PAYLOAD_SCHEMA_VERSION
from scripts import run_benchmarks as benchmark_module
from scripts.run_benchmarks import main, render_markdown, run_benchmarks


def test_plan3_benchmark_core_lives_in_package() -> None:
    adapters = importlib.import_module("TeeBotus.benchmarks.adapters")
    bibliothekar = importlib.import_module("TeeBotus.benchmarks.bibliothekar")
    codex_history = importlib.import_module("TeeBotus.benchmarks.codex_history")
    core = importlib.import_module("TeeBotus.benchmarks.core")
    hf_pool = importlib.import_module("TeeBotus.benchmarks.hf_pool")
    langgraph_flows = importlib.import_module("TeeBotus.benchmarks.langgraph_flows")
    llm_routing = importlib.import_module("TeeBotus.benchmarks.llm_routing")
    mcp = importlib.import_module("TeeBotus.benchmarks.mcp")
    memory = importlib.import_module("TeeBotus.benchmarks.memory")
    pydantic_ai = importlib.import_module("TeeBotus.benchmarks.pydantic_ai")
    proactive = importlib.import_module("TeeBotus.benchmarks.proactive")
    qdrant = importlib.import_module("TeeBotus.benchmarks.qdrant")
    reporting = importlib.import_module("TeeBotus.benchmarks.reporting")
    runtime_health = importlib.import_module("TeeBotus.benchmarks.runtime_health")
    source_quality = importlib.import_module("TeeBotus.benchmarks.source_quality")
    suite = importlib.import_module("TeeBotus.benchmarks.suite")
    youtube = importlib.import_module("TeeBotus.benchmarks.youtube")
    package_dir = Path(core.__file__).resolve().parent

    assert (package_dir / "__init__.py").exists()
    assert (package_dir / "adapters.py").exists()
    assert (package_dir / "bibliothekar.py").exists()
    assert (package_dir / "codex_history.py").exists()
    assert (package_dir / "core.py").exists()
    assert (package_dir / "hf_pool.py").exists()
    assert (package_dir / "langgraph_flows.py").exists()
    assert (package_dir / "llm_routing.py").exists()
    assert (package_dir / "mcp.py").exists()
    assert (package_dir / "memory.py").exists()
    assert (package_dir / "pydantic_ai.py").exists()
    assert (package_dir / "proactive.py").exists()
    assert (package_dir / "qdrant.py").exists()
    assert (package_dir / "reporting.py").exists()
    assert (package_dir / "runtime_health.py").exists()
    assert (package_dir / "source_quality.py").exists()
    assert (package_dir / "suite.py").exists()
    assert (package_dir / "youtube.py").exists()
    assert benchmark_module._build_quality_gate is core.build_quality_gate
    assert benchmark_module._build_comparisons is core.build_comparisons
    assert benchmark_module._result is core.result
    assert benchmark_module.BENCHMARK_CONTEXT_DEPENDENCIES is core.BENCHMARK_CONTEXT_DEPENDENCIES
    assert benchmark_module.BENCHMARK_RANKING_NAME_SETS is core.BENCHMARK_RANKING_NAME_SETS
    assert benchmark_module.REQUIRED_BENCHMARK_NAMES is core.REQUIRED_BENCHMARK_NAMES
    assert benchmark_module.REQUIRED_BENCHMARK_NAME_CATEGORIES is core.REQUIRED_BENCHMARK_NAME_CATEGORIES
    assert benchmark_module._benchmark_adapter_contracts is adapters.benchmark_adapter_contracts
    assert benchmark_module._benchmark_bibliothekar is bibliothekar.benchmark_bibliothekar_local_query
    assert benchmark_module._benchmark_bibliothekar_llamaindex_fake is bibliothekar.benchmark_bibliothekar_llamaindex_fake_query
    assert benchmark_module._benchmark_bibliothekar_haystack_fake is bibliothekar.benchmark_bibliothekar_haystack_fake_query
    assert benchmark_module._benchmark_retrieval_embedding_reranker_matrix is bibliothekar.benchmark_retrieval_embedding_reranker_matrix
    assert benchmark_module._benchmark_hf_pool_quick is hf_pool.benchmark_hf_pool_quick
    assert benchmark_module._benchmark_hf_pool_eval_matrix is hf_pool.benchmark_hf_pool_eval_matrix
    assert benchmark_module._benchmark_hf_pool_live is hf_pool.benchmark_hf_pool_live
    assert benchmark_module._benchmark_langgraph_flow is langgraph_flows.benchmark_langgraph_bibliothekar_deep_query
    assert benchmark_module._benchmark_langgraph_linear_flow is langgraph_flows.benchmark_langgraph_bibliothekar_linear
    assert benchmark_module._benchmark_langgraph_fake_installed_flow is langgraph_flows.benchmark_langgraph_bibliothekar_fake_installed
    assert benchmark_module._benchmark_langgraph_source_harvester_workflow is langgraph_flows.benchmark_langgraph_source_harvester_workflow
    assert benchmark_module.benchmark_llm_router is llm_routing.benchmark_llm_router
    assert benchmark_module.benchmark_llm_message_latency_paths is llm_routing.benchmark_llm_message_latency_paths
    assert benchmark_module.benchmark_llm_decision_qdrant_path_matrix is llm_routing.benchmark_llm_decision_qdrant_path_matrix
    assert benchmark_module.benchmark_live_llm_message_latency_paths is llm_routing.benchmark_live_llm_message_latency_paths
    assert benchmark_module.benchmark_gemini_free_tier_guard is llm_routing.benchmark_gemini_free_tier_guard
    assert benchmark_module._benchmark_mcp_tools is mcp.benchmark_mcp_readonly_bibliothekar_and_memory_search
    assert benchmark_module.benchmark_memory_results is memory.memory_results
    assert benchmark_module._benchmark_memory_jsonl_to_sqlite_migration is memory.benchmark_memory_jsonl_to_sqlite_migration
    assert benchmark_module._benchmark_decision_fake_model is pydantic_ai.benchmark_decision_fake_model
    assert benchmark_module._benchmark_pydantic_structured_decisions is pydantic_ai.benchmark_pydantic_structured_decisions
    assert benchmark_module._benchmark_proactive is proactive.benchmark_proactive_tool_plan_due_dispatch_gates
    assert benchmark_module._benchmark_qdrant_health_quick is qdrant.benchmark_qdrant_health_quick
    assert benchmark_module._benchmark_qdrant_health_live is qdrant.benchmark_qdrant_health_live
    assert benchmark_module._benchmark_qdrant_memory_index_quick is qdrant.benchmark_qdrant_memory_index_quick
    assert (
        benchmark_module._benchmark_qdrant_usermemory_1024d_side_index_quick
        is qdrant.benchmark_qdrant_usermemory_1024d_side_index_quick
    )
    assert (
        benchmark_module._benchmark_qdrant_usermemory_384d_side_index_quick
        is qdrant.benchmark_qdrant_usermemory_384d_side_index_quick
    )
    assert (
        benchmark_module._benchmark_qdrant_vector_dimensions_quantization_quick
        is qdrant.benchmark_qdrant_vector_dimensions_quantization_quick
    )
    assert benchmark_module._context is reporting.benchmark_context
    assert benchmark_module._dependency_context is reporting.dependency_context
    assert benchmark_module._build_regression_report is reporting.build_regression_report
    assert benchmark_module.render_markdown is reporting.render_markdown
    assert benchmark_module.run_benchmarks is suite.run_benchmarks
    assert benchmark_module._benchmark_status_doctor is runtime_health.benchmark_status_doctor
    assert benchmark_module._benchmark_codex_history_collector_timer_render is codex_history.benchmark_codex_history_collector_timer_render
    assert benchmark_module._benchmark_database_fallback_policy is runtime_health.benchmark_database_fallback_policy
    assert benchmark_module._benchmark_source_harvester_quality_gate is source_quality.benchmark_source_harvester_quality_gate
    assert benchmark_module._benchmark_source_harvester_promote_index_flow is source_quality.benchmark_source_harvester_promote_index_flow
    assert benchmark_module._benchmark_youtube_parser is youtube.benchmark_youtube_parser
    assert benchmark_module._benchmark_youtube_local_job_queue is youtube.benchmark_youtube_local_job_queue
    assert benchmark_module._benchmark_youtube_local_pipeline_cache is youtube.benchmark_youtube_local_pipeline_cache


def test_quick_benchmark_suite_covers_plan_core_categories() -> None:
    suite = run_benchmarks(entries=2, iterations=1, quick=True)

    categories = {result["category"] for result in suite["results"]}

    assert suite["schema_version"] == 1
    assert suite["ok"] is True
    assert suite["include_live"] is False
    assert suite["live_llm"] is False
    assert suite["context"]["cpu_count"] >= 1
    assert suite["context"]["dependencies"]["teebotus"] == {"version": TEEBOTUS_VERSION, "status": "worktree"}
    assert set(benchmark_module.BENCHMARK_CONTEXT_DEPENDENCIES).issubset(suite["context"]["dependencies"])
    assert suite["context"]["dependencies"]["litellm"]["status"] in {"installed", "missing"}
    assert suite["context"]["dependencies"]["llama-index-core"]["status"] in {"installed", "missing"}
    assert suite["context"]["dependencies"]["signalbot"]["version"]
    assert suite["comparisons"]["auto_switching"] is False
    assert suite["quality_gate"] == {
        "status": "ok",
        "ok": True,
        "checked_results": len(suite["results"]),
        "error_count": 0,
        "errors": [],
    }
    assert benchmark_module.REQUIRED_BENCHMARK_NAMES.issubset({result["name"] for result in suite["results"] if result["ok"] and not result["skipped"]})
    assert suite["regression"]["status"] == "not_configured"
    assert suite["regression"]["failed"] is False
    rankings = {ranking["category"]: ranking for ranking in suite["comparisons"]["stable_backend_rankings"]}
    assert benchmark_module.REQUIRED_BENCHMARK_RANKING_CATEGORIES.issubset(rankings)
    assert set(benchmark_module.BENCHMARK_RANKING_NAME_SETS) == benchmark_module.REQUIRED_BENCHMARK_RANKING_CATEGORIES
    for category, names in benchmark_module.BENCHMARK_RANKING_NAME_SETS.items():
        ranking = rankings[category]
        ranked_names = {candidate["name"] for candidate in ranking["candidates"]}
        skipped_names = {skipped["name"] for skipped in ranking["skipped"]}
        assert ranked_names <= names
        assert skipped_names <= names
    assert rankings["account_memory"]["fastest_stable"]
    assert rankings["account_memory"]["candidates"]
    assert [candidate["rank"] for candidate in rankings["account_memory"]["candidates"]] == list(
        range(1, len(rankings["account_memory"]["candidates"]) + 1)
    )
    assert {candidate["name"] for candidate in rankings["retrieval"]["candidates"]} == {
        "retrieval_backend_haystack_fake",
        "retrieval_backend_llamaindex_fake",
        "retrieval_backend_local",
    }
    assert rankings["retrieval"]["fastest_stable"].startswith("retrieval_backend_")
    assert any(skipped["name"] == "memory_postgres" for skipped in rankings["account_memory"]["skipped"])
    assert {
        "account_memory",
        "bibliothekar",
        "gemini_free_tier",
        "hf_pool",
        "llm_router",
        "pydantic_ai",
        "proactive_agent",
        "qdrant",
        "retrieval",
        "source_harvester",
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
    for result in suite["results"]:
        for counter in benchmark_module.STANDARD_BENCHMARK_FORBIDDEN_CALL_COUNTERS:
            assert result["details"][counter] == 0
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
    llamaindex_library = next(result for result in suite["results"] if result["name"] == "bibliothekar_llamaindex_fake_query")
    haystack_library = next(result for result in suite["results"] if result["name"] == "bibliothekar_haystack_fake_query")
    assert local_library["details"]["fixture"] == "tests/fixtures/books"
    assert llamaindex_library["details"]["fixture"] == "tests/fixtures/books"
    assert haystack_library["details"]["fixture"] == "tests/fixtures/books"
    assert local_library["details"]["selected_chunks"] >= 1
    assert llamaindex_library["details"]["selected_chunks"] >= 1
    assert haystack_library["details"]["selected_chunks"] >= 1
    assert local_library["details"]["citation_payload_bytes"] > 0
    assert llamaindex_library["details"]["citation_payload_bytes"] > 0
    assert haystack_library["details"]["citation_payload_bytes"] > 0
    assert local_library["details"]["has_citation_format"] is True
    assert llamaindex_library["details"]["has_citation_format"] is True
    assert haystack_library["details"]["has_citation_format"] is True
    assert local_library["details"]["provenance_fields_complete"] is True
    assert llamaindex_library["details"]["provenance_fields_complete"] is True
    assert haystack_library["details"]["provenance_fields_complete"] is True
    assert local_library["details"]["citation_missing_fields"] == []
    assert llamaindex_library["details"]["citation_missing_fields"] == []
    assert haystack_library["details"]["citation_missing_fields"] == []
    assert {
        "chunk_id",
        "source_id",
        "file",
        "file_path",
        "file_sha256",
        "file_type",
        "language",
        "locator",
        "license",
        "source_quality",
        "citation_quality",
        "ingested_at",
        "chunk_index",
        "embedding_model",
        "citation_format",
    }.issubset(set(local_library["details"]["citation_required_fields"]))
    assert llamaindex_library["details"]["query_engine"] == "fake_llamaindex_chunks"
    assert llamaindex_library["details"]["private_filter_selected_chunks"] >= 1
    assert llamaindex_library["details"]["private_filter_payload_leaked"] is False
    assert haystack_library["details"]["private_filter_selected_chunks"] >= 1
    assert haystack_library["details"]["private_filter_payload_leaked"] is False
    assert {candidate["name"] for candidate in rankings["bibliothekar"]["candidates"]} == {
        "bibliothekar_local_query",
        "bibliothekar_llamaindex_fake_query",
        "bibliothekar_haystack_fake_query",
    }
    assert any(result["name"] == "langgraph_bibliothekar_linear" for result in suite["results"])
    fake_graph = next(result for result in suite["results"] if result["name"] == "langgraph_bibliothekar_fake_installed")
    assert fake_graph["details"]["mode"] == "fake_installed_langgraph"
    assert fake_graph["details"]["node_sequence"] == ["classify", "retrieve", "rerank", "answer", "citation_check", "fallback"]
    llm_router = next(result for result in suite["results"] if result["name"] == "llm_router_structured_decision")
    assert llm_router["details"]["runtime_client"] == "HFPoolProvider"
    assert llm_router["details"]["runtime_provider"] == "hf_pool"
    assert llm_router["details"]["runtime_model"] == "pool:default#structured_decision"
    assert llm_router["details"]["runtime_fallback_client"] == "LiteLLMTextClient"
    assert llm_router["details"]["runtime_fallback_model"] == "ollama_chat/llama3.2:3b"
    assert llm_router["details"]["memory_candidate_kind"] == "therapy_goal"
    assert llm_router["details"]["remote_fallback_default_enabled"] is True
    assert llm_router["details"]["default_fallback_models"] == ["ollama_chat/llama3.2:3b"]
    assert llm_router["details"]["default_fallback_profile"] == "local_ollama"
    assert llm_router["details"]["explicit_remote_fallback_enabled"] is True
    assert llm_router["details"]["explicit_remote_fallback_models"] == ["ollama_chat/llama3.2:3b"]
    assert llm_router["details"]["explicit_remote_fallback_api_key_env"] == ""
    assert llm_router["details"]["explicit_remote_fallback_api_key_mapped"] is False
    assert "benchmark-groq-key" not in json.dumps(suite, ensure_ascii=False)
    assert llm_router["details"]["direct_remote_fallback_default_models"] == ["ollama_chat/qwen2.5:7b"]
    assert llm_router["details"]["direct_remote_fallback_allowed_models"] == [
        "groq/llama-3.1-8b-instant",
        "ollama_chat/qwen2.5:7b",
    ]
    assert llm_router["details"]["network_calls"] == 0
    llm_message_latency = next(result for result in suite["results"] if result["name"] == "llm_message_latency_paths")
    assert llm_message_latency["ok"] is True
    assert llm_message_latency["category"] == "llm_router"
    assert llm_message_latency["details"]["synthetic_clients_only"] is True
    assert llm_message_latency["details"]["openai_account_state_ok"] is True
    assert llm_message_latency["details"]["gemini_account_state_ok"] is True
    assert llm_message_latency["details"]["stateless_paths_ignore_state_ok"] is True
    assert {path["path"] for path in llm_message_latency["details"]["paths"]} == {
        "openai_responses_stateful",
        "litellm_gemini_stateful",
        "litellm_gemini_paid_stateful",
        "litellm_gemini_paid_stateless",
        "litellm_local_stateless",
        "hf_pool_stateless",
    }
    for path in llm_message_latency["details"]["paths"]:
        assert path["local_client_calls"] == llm_message_latency["details"]["message_count_per_path"]
        assert path["mean_ms"] >= 0
        assert path["p95_ms"] >= 0
    assert llm_message_latency["details"]["network_calls"] == 0
    assert llm_message_latency["details"]["provider_calls"] == 0
    llm_matrix = next(result for result in suite["results"] if result["name"] == "llm_decision_qdrant_path_matrix")
    assert llm_matrix["ok"] is True
    assert llm_matrix["category"] == "llm_router"
    assert llm_matrix["details"]["synthetic_clients_only"] is True
    assert llm_matrix["details"]["fake_qdrant_only"] is True
    assert llm_matrix["details"]["path_count"] == 72
    assert llm_matrix["details"]["scenario_count"] == 12
    assert llm_matrix["details"]["qdrant_path_count"] == 24
    assert llm_matrix["details"]["decision_path_count"] == 36
    assert llm_matrix["details"]["bibliothekar_path_count"] == 36
    assert llm_matrix["details"]["qdrant_paths_ok"] is True
    assert llm_matrix["details"]["decision_paths_ok"] is True
    assert llm_matrix["details"]["bibliothekar_paths_ok"] is True
    assert {path["memory_mode"] for path in llm_matrix["details"]["paths"]} == {"none", "keyword", "qdrant"}
    assert {path["decision_layer"] for path in llm_matrix["details"]["paths"]} == {False, True}
    assert {path["bibliothekar"] for path in llm_matrix["details"]["paths"]} == {False, True}
    assert llm_matrix["details"]["network_calls"] == 0
    assert llm_matrix["details"]["provider_calls"] == 0
    assert not any(result["name"] == "live_llm_message_latency_paths" for result in suite["results"])
    gemini_free_tier = next(result for result in suite["results"] if result["name"] == "gemini_free_tier_guard_cache_rotation")
    assert gemini_free_tier["ok"] is True
    assert gemini_free_tier["category"] == "gemini_free_tier"
    assert gemini_free_tier["details"]["refresh_status"] == "ok"
    assert gemini_free_tier["details"]["cached_limits"] == {"rpm": 2, "tpm": 100, "rpd": 3, "reserve_tokens": 10}
    assert gemini_free_tier["details"]["resolved_summary"] == "on(rpm=2,tpm=100,rpd=3,reserve=10)"
    assert gemini_free_tier["details"]["ring_size"] == 6
    assert gemini_free_tier["details"]["ring_order_ok"] is True
    assert gemini_free_tier["details"]["blocked_before_provider"] is True
    assert gemini_free_tier["details"]["rotation_after_limit_ok"] is True
    assert gemini_free_tier["details"]["blocked_reason_contains_tpm"] is True
    assert gemini_free_tier["details"]["network_calls"] == 0
    assert gemini_free_tier["details"]["provider_calls"] == 0
    hf_pool = next(result for result in suite["results"] if result["name"] == "hf_pool_quick_health")
    assert hf_pool["ok"] is True
    assert hf_pool["category"] == "hf_pool"
    assert hf_pool["details"]["network_calls"] == 0
    assert any(line.startswith("hf_pool=") for line in hf_pool["details"]["status_lines"])
    hf_eval = next(result for result in suite["results"] if result["name"] == "hf_pool_eval_matrix")
    assert hf_eval["ok"] is True
    assert hf_eval["category"] == "hf_pool"
    assert hf_eval["details"]["purposes"] == [
        "structured_decision",
        "normal_chat",
        "psychology_explainer",
        "bibliothekar_answer",
        "summarizer",
    ]
    assert hf_eval["details"]["structured_decision_json_valid"] is True
    assert hf_eval["details"]["routed_purposes"] == hf_eval["details"]["purposes"]
    assert 0 < hf_eval["details"]["structured_decision_confidence"] <= 1
    assert hf_eval["details"]["normal_chat_median_latency_ms"] > 0
    assert hf_eval["details"]["psychology_quality_score"] >= 3
    assert all(hf_eval["details"]["psychology_quality_checks"].values())
    assert hf_eval["details"]["psychology_quality_ok"] is True
    assert hf_eval["details"]["bibliothekar_citation_faithful"] is True
    assert all(hf_eval["details"]["bibliothekar_citation_fields"].values())
    assert hf_eval["details"]["summarizer_faithful"] is True
    assert all(hf_eval["details"]["summarizer_terms"].values())
    assert hf_eval["details"]["summarizer_hallucinated"] is False
    assert hf_eval["details"]["provider_failure_fallback"] is True
    assert hf_eval["details"]["cooldown_fallback"] is True
    assert hf_eval["details"]["cooldown_state_key"] == "default/bench_normal_chat"
    assert hf_eval["details"]["cooldown_network_calls"] == 0
    assert hf_eval["details"]["network_calls"] == 0
    qdrant_health = next(result for result in suite["results"] if result["name"] == "qdrant_health_quick")
    assert qdrant_health["ok"] is True
    assert qdrant_health["details"]["latest_status"] == "qdrant=127.0.0.1:6333 status=reachable"
    assert qdrant_health["details"]["network_calls"] == 0
    qdrant_memory = next(result for result in suite["results"] if result["name"] == "qdrant_memory_index_quick")
    assert qdrant_memory["ok"] is True
    assert qdrant_memory["details"]["points"] >= 1
    assert qdrant_memory["details"]["selected"] >= 1
    assert qdrant_memory["details"]["schema_versions"] == [QDRANT_MEMORY_PAYLOAD_SCHEMA_VERSION]
    assert qdrant_memory["details"]["cleartext_in_payload"] is False
    assert qdrant_memory["details"]["messenger_identity_in_payload"] is False
    assert qdrant_memory["details"]["account_id_in_payload"] is False
    assert qdrant_memory["details"]["content_hash_in_payload"] is False
    assert qdrant_memory["details"]["sensitive_metadata_in_payload"] is False
    assert qdrant_memory["details"]["remote_embedding_blocked"] is True
    assert qdrant_memory["details"]["network_calls"] == 0
    qdrant_quant = next(
        result
        for result in suite["results"]
        if result["name"] == "qdrant_vector_dimensions_quantization_quick"
    )
    assert qdrant_quant["ok"] is True
    assert qdrant_quant["category"] == "qdrant"
    assert qdrant_quant["details"]["dimension_candidates"] == [64, 128, 256, 384, 768, 1024]
    assert qdrant_quant["details"]["storage_ratio_1024_vs_64"] == 16.0
    assert qdrant_quant["details"]["scalar_int8_ratio_vs_float32"] == 0.25
    assert qdrant_quant["details"]["binary_ratio_vs_float32"] == 0.03125
    assert qdrant_quant["details"]["dimension_cost_monotonic"] is True
    assert qdrant_quant["details"]["estimated_only"] is True
    assert qdrant_quant["details"]["network_calls"] == 0
    assert qdrant_quant["details"]["provider_calls"] == 0
    assert qdrant_quant["details"]["remote_calls"] == 0
    qdrant_384d = next(
        result
        for result in suite["results"]
        if result["name"] == "qdrant_usermemory_384d_side_index_quick"
    )
    assert qdrant_384d["ok"] is True
    assert qdrant_384d["category"] == "qdrant"
    assert qdrant_384d["details"]["baseline_dimensions"] == 64
    assert qdrant_384d["details"]["side_index_dimensions"] == 384
    assert qdrant_384d["details"]["side_index_optional"] is True
    assert qdrant_384d["details"]["side_index_rebuildable"] is True
    assert qdrant_384d["details"]["storage_ratio_384d_vs_64d"] == 6.0
    assert qdrant_384d["details"]["primary_top3_hits"] == qdrant_384d["details"]["queries"]
    assert qdrant_384d["details"]["side_top3_hits"] == qdrant_384d["details"]["queries"]
    assert qdrant_384d["details"]["embedding_dimensions"] == [64, 384]
    assert qdrant_384d["details"]["cleartext_in_payload"] is False
    assert qdrant_384d["details"]["messenger_identity_in_payload"] is False
    assert qdrant_384d["details"]["account_id_in_payload"] is False
    assert qdrant_384d["details"]["network_calls"] == 0
    assert qdrant_384d["details"]["provider_calls"] == 0
    assert qdrant_384d["details"]["remote_calls"] == 0
    retrieval = next(result for result in suite["results"] if result["name"] == "retrieval_embedding_reranker_matrix")
    assert retrieval["ok"] is True
    assert retrieval["category"] == "retrieval"
    assert retrieval["details"]["usermemory_models"] == ["intfloat/multilingual-e5-small", "intfloat/multilingual-e5-base"]
    assert retrieval["details"]["book_models"] == ["BAAI/bge-m3", "intfloat/multilingual-e5-base"]
    assert retrieval["details"]["reranker"] == "BAAI/bge-reranker-v2-m3"
    assert retrieval["details"]["reranker_backend"] == "keyword_overlap_fake"
    assert retrieval["details"]["reranker_comparison"]["without_reranker_model"] == "BAAI/bge-m3"
    assert retrieval["details"]["reranker_comparison"]["with_reranker_model"] == "BAAI/bge-reranker-v2-m3"
    assert len(retrieval["details"]["reranker_comparison"]["without_reranker_top"]) == 2
    assert len(retrieval["details"]["reranker_comparison"]["with_reranker_top"]) == 2
    assert retrieval["details"]["backend_modes"] == ["local", "llamaindex_fake", "haystack_fake"]
    assert all(count >= 1 for count in retrieval["details"]["backend_selected"].values())
    assert retrieval["details"]["network_calls"] == 0
    source_harvester = next(result for result in suite["results"] if result["name"] == "source_harvester_quality_gate")
    assert source_harvester["ok"] is True
    assert source_harvester["category"] == "source_harvester"
    assert source_harvester["details"]["routes"] == {"accepted": 1}
    assert source_harvester["details"]["accepted_for_ingest"] == 1
    assert source_harvester["details"]["network_calls"] == 0
    source_promote = next(result for result in suite["results"] if result["name"] == "source_harvester_promote_index_flow")
    assert source_promote["ok"] is True
    assert source_promote["category"] == "source_harvester"
    assert source_promote["details"]["promoted"] == 1
    assert source_promote["details"]["pre_promote_chunk_counts"] == [0]
    assert source_promote["details"]["post_promote_final_chunks"] == 1
    assert source_promote["details"]["promoted_dir"] == "books"
    assert source_promote["details"]["network_calls"] == 0
    decision_fake = next(result for result in suite["results"] if result["name"] == "decision_fake_model")
    assert decision_fake["ok"] is True
    assert decision_fake["details"]["fake_model_calls"] == 1
    assert decision_fake["details"]["latest_intent"] == "bibliothekar_query"
    assert decision_fake["details"]["network_calls"] == 0
    pydantic_ai = next(result for result in suite["results"] if result["name"] == "pydantic_structured_decisions")
    assert pydantic_ai["ok"] is True
    assert pydantic_ai["category"] == "pydantic_ai"
    assert pydantic_ai["details"]["schemas"] == [
        "AgentTaskDecision",
        "BibliothekarQueryDecision",
        "MemoryCandidate",
        "ReminderDecision",
        "SourceQualityDecision",
        "ToolSafetyDecision",
        "ProactiveToolCallDecision",
        "YouTubeOptionsDecision",
    ]
    assert pydantic_ai["details"]["fake_agent_calls"] == 1
    assert pydantic_ai["details"]["fake_agent_model"] == "pool:default#structured_decision"
    assert pydantic_ai["details"]["router_purpose"] == "structured_decision"
    assert pydantic_ai["details"]["router_provider"] == "hf_pool"
    assert pydantic_ai["details"]["latest_runner_query"] == "Therapie Schlaf"
    assert pydantic_ai["details"]["network_calls"] == 0
    source_harvester_flow = next(result for result in suite["results"] if result["name"] == "langgraph_source_harvester_workflow")
    assert source_harvester_flow["ok"] is True
    assert source_harvester_flow["details"]["ready_for_ingest"] == 1
    assert source_harvester_flow["details"]["statuses"] == {"ready_for_ingest": 1}
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
    assert rankings["transcription_youtube"]["fastest_stable"]
    assert {candidate["name"] for candidate in rankings["transcription_youtube"]["candidates"]} == {
        "youtube_parser_local",
        "youtube_local_job_queue_no_llm",
        "youtube_local_pipeline_cache_no_openai",
    }
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
    assert status_doctor["details"]["decision_provider"] == "hf_pool"
    assert status_doctor["details"]["decision_model"] == "pool:default#structured_decision"
    assert status_doctor["details"]["decision_profile"] == "hf_pool_structured"
    assert status_doctor["details"]["crew_pilot_lines"] >= 3
    assert status_doctor["details"]["dependency_ok"] is True
    assert status_doctor["details"]["account_crypto_ok"] is True
    assert status_doctor["details"]["account_memory_ok"] is True
    assert status_doctor["details"]["account_identity_ok"] is True
    assert status_doctor["details"]["account_crypto_status"].startswith("account_crypto=Bench status=ok")
    assert "mapping=present" in status_doctor["details"]["account_crypto_status"]
    assert "memory=present" in status_doctor["details"]["account_crypto_status"]
    assert status_doctor["details"]["account_memory_status"].startswith("account_memory=Bench/")
    assert "status=ok" in status_doctor["details"]["account_memory_status"]
    assert status_doctor["details"]["account_identity_status"] == (
        "account_identity=Bench status=ok identity_warnings=0 "
        "runtime_slots=matrix:1,signal:1,telegram:1 identities=matrix:1,signal:1,telegram:1"
    )
    assert "telegram-token" not in json.dumps(status_doctor, ensure_ascii=False)
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
    mcp_tools = next(result for result in suite["results"] if result["name"] == "mcp_readonly_bibliothekar_and_memory_search")
    assert mcp_tools["ok"] is True
    assert mcp_tools["details"]["tool_names"] == ("bibliothekar.search", "memory.search")
    assert mcp_tools["details"]["group_tool_names"] == ("bibliothekar.search",)
    assert mcp_tools["details"]["library_selected"] >= 1
    assert mcp_tools["details"]["memory_selected"] == 1
    assert mcp_tools["details"]["group_blocks_memory"] is True
    assert mcp_tools["details"]["unknown_tool_blocked"] is True
    assert mcp_tools["details"]["network_calls"] == 0


def test_gemini_free_tier_benchmark_is_repeatable() -> None:
    first = llm_routing.benchmark_gemini_free_tier_guard(iterations=1)
    second = llm_routing.benchmark_gemini_free_tier_guard(iterations=1)

    assert first["ok"] is True
    assert second["ok"] is True
    assert first["details"]["rotation_after_limit_ok"] is True
    assert second["details"]["rotation_after_limit_ok"] is True


def test_benchmark_markdown_contains_comparison_table() -> None:
    suite = run_benchmarks(entries=1, iterations=1, quick=True)

    markdown = render_markdown(suite)

    assert "# TeeBotus Benchmarks" in markdown
    assert "## Dependencies" in markdown
    assert "| litellm |" in markdown
    assert "| name | category | status | mode | iterations | total_ms | throughput_ops_s | errors | payload_bytes | index_bytes | note | details |" in markdown
    assert "## Stable Backend Rankings" in markdown
    assert "## Quality Gate" in markdown
    assert "status: ok" in markdown
    assert "## Regression Check" in markdown
    assert "status: not_configured" in markdown
    assert "include_live: False" in markdown
    assert "live_llm: False" in markdown
    assert "| category | rank | name | mode | throughput_ops_s | total_ms | errors | note |" in markdown
    assert "Die Rangliste dokumentiert Messwerte nur" in markdown
    assert "memory_jsonl" in markdown
    assert "memory_migration_jsonl_to_sqlite" in markdown
    assert "bibliothekar_llamaindex_fake_query" in markdown
    assert "bibliothekar_haystack_fake_query" in markdown
    assert "pydantic_structured_decisions" in markdown
    assert "gemini_free_tier_guard_cache_rotation" in markdown
    assert "llm_message_latency_paths" in markdown
    assert "llm_decision_qdrant_path_matrix" in markdown
    assert "langgraph_bibliothekar_deep_query" in markdown
    assert "langgraph_bibliothekar_fake_installed" in markdown
    assert "langgraph_source_harvester_workflow" in markdown
    assert "hf_pool_quick_health" in markdown
    assert "qdrant_health_quick" in markdown
    assert "qdrant_memory_index_quick" in markdown
    assert "qdrant_vector_dimensions_quantization_quick" in markdown
    assert "qdrant_usermemory_384d_side_index_quick" in markdown
    assert "retrieval_embedding_reranker_matrix" in markdown
    assert "retrieval_backend_local" in markdown
    assert "retrieval_backend_haystack_fake" in markdown
    assert "source_harvester_quality_gate" in markdown
    assert "source_harvester_promote_index_flow" in markdown
    assert "decision_fake_model" in markdown
    assert "youtube_parser_local" in markdown
    assert "proactive_tool_plan_due_dispatch_gates" in markdown
    assert "messenger_adapter_runtime_contracts" in markdown
    assert "status_doctor_runtime_dependency_health" in markdown
    assert "youtube_local_job_queue_no_llm" in markdown
    assert "youtube_local_pipeline_cache_no_openai" in markdown
    assert "primary_failure_secondary_sync_recovery_warning" in markdown
    assert "mcp_readonly_bibliothekar_and_memory_search" in markdown
    assert "keine echten Provider-Calls" in markdown


def test_emergency_live_llm_benchmark_is_double_gated_without_provider_calls() -> None:
    result = benchmark_module.benchmark_live_llm_message_latency_paths(iterations=1, env={})

    assert result["name"] == "live_llm_message_latency_paths"
    assert result["skipped"] is True
    assert result["ok"] is False
    assert result["mode"] == "live_emergency_llm"
    assert "TEEBOTUS_EMERGENCY_LIVE_LLM_BENCHMARK" in result["reason"]
    assert result["details"]["required_confirmation"] == "NOTFALL_KOSTEN_AKZEPTIERT"
    for counter in benchmark_module.STANDARD_BENCHMARK_FORBIDDEN_CALL_COUNTERS:
        assert result["details"][counter] == 0


def test_live_llm_candidate_runnable_uses_central_gemini_api_scope() -> None:
    runnable, reason = llm_routing._live_llm_candidate_runnable(
        provider="gemini_paid_interactions",
        model="custom-gemini-model",
        api_key_env="",
        source={"GEMINI_API_KEYS_ACCOUNT_1": "gemini-key"},
    )

    assert runnable is True
    assert reason == ""

    runnable, reason = llm_routing._live_llm_candidate_runnable(
        provider="google_vertex",
        model="custom-vertex-model",
        api_key_env="",
        source={"GEMINI_API_KEYS_ACCOUNT_1": "gemini-key"},
    )

    assert runnable is False
    assert reason == "missing GOOGLE_APPLICATION_CREDENTIALS"


def test_benchmark_quality_gate_flags_incomplete_standard_results() -> None:
    results = [
        {
            "name": "memory_jsonl",
            "category": "account_memory",
            "ok": True,
            "skipped": False,
            "iterations": 0,
            "total_ms": 1.0,
            "throughput_ops_s": 1.0,
            "errors": 1,
            "payload_bytes": 0,
            "index_bytes": 0,
            "mode": "live",
            "details": {"network_calls": 1},
        }
    ]

    quality_gate = benchmark_module._build_quality_gate(
        results,
        comparisons={"stable_backend_rankings": []},
        quick=True,
        include_live=False,
    )

    assert quality_gate["ok"] is False
    assert quality_gate["status"] == "failed"
    assert any("missing required benchmark categories" in error for error in quality_gate["errors"])
    assert any("missing required benchmark results" in error for error in quality_gate["errors"])
    assert any("missing required benchmark rankings" in error for error in quality_gate["errors"])
    assert "memory_jsonl iterations must be a positive integer" in quality_gate["errors"]
    assert "memory_jsonl errors must be 0 for ok standard benchmark results" in quality_gate["errors"]
    assert "memory_jsonl must report payload_bytes or index_bytes" in quality_gate["errors"]
    assert any("memory_jsonl details missing standard no-live counters" in error for error in quality_gate["errors"])
    assert "memory_jsonl details.network_calls must be 0 in standard quick benchmarks, got 1" in quality_gate["errors"]
    assert "memory_jsonl must not use live mode in standard quick benchmarks" in quality_gate["errors"]


def test_benchmark_quality_gate_rejects_non_skipped_live_optional_mode() -> None:
    quality_gate = benchmark_module._build_quality_gate(
        [
            {
                "name": "memory_jsonl",
                "category": "account_memory",
                "ok": True,
                "skipped": False,
                "iterations": 1,
                "total_ms": 1.0,
                "throughput_ops_s": 1.0,
                "errors": 0,
                "payload_bytes": 1,
                "index_bytes": 0,
                "mode": "live_optional",
                "details": {
                    "network_calls": 0,
                    "openai_calls": 0,
                    "provider_calls": 0,
                    "remote_calls": 0,
                    "llm_calls": 0,
                },
            }
        ],
        comparisons={"stable_backend_rankings": []},
        quick=True,
        include_live=False,
    )

    assert "memory_jsonl must not use live mode in standard quick benchmarks" in quality_gate["errors"]


def test_benchmark_quality_gate_rejects_malformed_skipped_results() -> None:
    quality_gate = benchmark_module._build_quality_gate(
        [
            {
                "name": "memory_postgres",
                "category": "account_memory",
                "ok": True,
                "skipped": True,
                "iterations": 1,
                "total_ms": 1.0,
                "throughput_ops_s": 1.0,
                "errors": 1,
                "payload_bytes": 0,
                "index_bytes": 0,
                "mode": "",
                "reason": "",
                "details": {"network_calls": 1},
            }
        ],
        comparisons={"stable_backend_rankings": []},
        quick=True,
        include_live=False,
    )

    assert quality_gate["ok"] is False
    assert "memory_postgres skipped result must not be ok" in quality_gate["errors"]
    assert "memory_postgres skipped result iterations must be 0" in quality_gate["errors"]
    assert "memory_postgres skipped result errors must be 0" in quality_gate["errors"]
    assert "memory_postgres skipped result reason must be non-empty" in quality_gate["errors"]
    assert "memory_postgres skipped result mode must be non-empty" in quality_gate["errors"]
    assert any("memory_postgres details missing standard no-live counters" in error for error in quality_gate["errors"])
    assert "memory_postgres details.network_calls must be 0 in standard quick benchmarks, got 1" in quality_gate["errors"]


def test_benchmark_quality_gate_rejects_single_candidate_required_rankings() -> None:
    quality_gate = benchmark_module._build_quality_gate(
        [],
        comparisons={
            "stable_backend_rankings": [
                {
                    "category": "bibliothekar",
                    "fastest_stable": "bibliothekar_local_query",
                    "candidates": [{"name": "bibliothekar_local_query"}],
                    "skipped": [],
                }
            ]
        },
        quick=True,
        include_live=False,
    )

    assert quality_gate["ok"] is False
    assert "ranking bibliothekar must compare at least 2 successful candidates" in quality_gate["errors"]


def test_benchmark_quality_gate_rejects_malformed_ranking_structure() -> None:
    no_comparisons = benchmark_module._build_quality_gate(
        [],
        comparisons=[],
        quick=True,
        include_live=False,
    )
    wrong_rankings = benchmark_module._build_quality_gate(
        [],
        comparisons={"stable_backend_rankings": {}},
        quick=True,
        include_live=False,
    )
    malformed_rankings = benchmark_module._build_quality_gate(
        [],
        comparisons={
            "stable_backend_rankings": [
                None,
                {"category": "", "candidates": [], "skipped": []},
                {"category": "account_memory", "candidates": "memory_jsonl", "skipped": "memory_postgres"},
                {"category": "account_memory", "candidates": [{"name": "memory_jsonl"}], "skipped": []},
            ]
        },
        quick=True,
        include_live=False,
    )

    assert "comparisons must be an object" in no_comparisons["errors"]
    assert "comparisons.stable_backend_rankings must be a non-empty list" in wrong_rankings["errors"]
    assert "rankings[0] must be an object" in malformed_rankings["errors"]
    assert "rankings[1] category must be non-empty" in malformed_rankings["errors"]
    assert "rankings[1] candidates must be a non-empty list" in malformed_rankings["errors"]
    assert "ranking account_memory candidates must be a non-empty list" in malformed_rankings["errors"]
    assert "ranking account_memory skipped must be a list" in malformed_rankings["errors"]
    assert "duplicate ranking category: account_memory" in malformed_rankings["errors"]


def test_benchmark_quality_gate_rejects_automatic_backend_switching() -> None:
    quality_gate = benchmark_module._build_quality_gate(
        [],
        comparisons={
            "auto_switching": True,
            "selection_policy": "switch_to_fastest",
            "stable_backend_rankings": [],
        },
        quick=True,
        include_live=False,
    )

    assert quality_gate["ok"] is False
    assert "comparisons.auto_switching must be false" in quality_gate["errors"]
    assert "comparisons.selection_policy must be document_fastest_stable_backend_only" in quality_gate["errors"]


def test_benchmark_quality_gate_rejects_unknown_ranking_categories() -> None:
    quality_gate = benchmark_module._build_quality_gate(
        [],
        comparisons={
            "stable_backend_rankings": [
                {
                    "category": "custom_backend",
                    "fastest_stable": "custom_b",
                    "candidates": [
                        {
                            "rank": 1,
                            "name": "custom_b",
                            "mode": "local",
                            "throughput_ops_s": 100.0,
                            "total_ms": 1.0,
                            "errors": 0,
                            "payload_bytes": 1,
                            "index_bytes": 1,
                        }
                    ],
                    "skipped": [],
                }
            ]
        },
        quick=True,
        include_live=False,
    )

    assert quality_gate["ok"] is False
    assert "unexpected benchmark ranking category: custom_backend" in quality_gate["errors"]


def test_benchmark_quality_gate_rejects_duplicate_or_empty_ranking_names() -> None:
    memory_jsonl = benchmark_module._result(
        name="memory_jsonl",
        category="account_memory",
        iterations=1,
        total_ms=1.0,
        ok=True,
        errors=0,
        payload_bytes=1,
        index_bytes=0,
        mode="local",
    )
    memory_sqlite = benchmark_module._result(
        name="memory_sqlite_projection",
        category="account_memory",
        iterations=1,
        total_ms=2.0,
        ok=True,
        errors=0,
        payload_bytes=1,
        index_bytes=0,
        mode="local",
    )

    quality_gate = benchmark_module._build_quality_gate(
        [memory_jsonl, memory_sqlite],
        comparisons={
            "stable_backend_rankings": [
                {
                    "category": "account_memory",
                    "fastest_stable": "",
                    "candidates": [
                        {"rank": 1, "name": "", "mode": "local"},
                        {
                            "rank": 2,
                            "name": "memory_jsonl",
                            "mode": memory_jsonl["mode"],
                            "throughput_ops_s": memory_jsonl["throughput_ops_s"],
                            "total_ms": memory_jsonl["total_ms"],
                            "errors": memory_jsonl["errors"],
                            "payload_bytes": memory_jsonl["payload_bytes"],
                            "index_bytes": memory_jsonl["index_bytes"],
                        },
                        {
                            "rank": 3,
                            "name": "memory_jsonl",
                            "mode": memory_jsonl["mode"],
                            "throughput_ops_s": memory_jsonl["throughput_ops_s"],
                            "total_ms": memory_jsonl["total_ms"],
                            "errors": memory_jsonl["errors"],
                            "payload_bytes": memory_jsonl["payload_bytes"],
                            "index_bytes": memory_jsonl["index_bytes"],
                        },
                    ],
                    "skipped": [
                        {"name": "", "mode": "", "reason": ""},
                        {"name": "memory_jsonl", "mode": "live_optional", "reason": "missing dsn"},
                        {"name": "memory_postgres", "mode": "live_optional", "reason": "missing dsn"},
                        {"name": "memory_postgres", "mode": "live_optional", "reason": "still missing dsn"},
                    ],
                }
            ]
        },
        quick=True,
        include_live=False,
    )
    fastest_skipped = benchmark_module._build_quality_gate(
        [memory_jsonl, memory_sqlite],
        comparisons={
            "stable_backend_rankings": [
                {
                    "category": "account_memory",
                    "fastest_stable": "memory_jsonl",
                    "candidates": [
                        {
                            "rank": 1,
                            "name": "memory_jsonl",
                            "mode": memory_jsonl["mode"],
                            "throughput_ops_s": memory_jsonl["throughput_ops_s"],
                            "total_ms": memory_jsonl["total_ms"],
                            "errors": memory_jsonl["errors"],
                            "payload_bytes": memory_jsonl["payload_bytes"],
                            "index_bytes": memory_jsonl["index_bytes"],
                        },
                        {
                            "rank": 2,
                            "name": "memory_sqlite_projection",
                            "mode": memory_sqlite["mode"],
                            "throughput_ops_s": memory_sqlite["throughput_ops_s"],
                            "total_ms": memory_sqlite["total_ms"],
                            "errors": memory_sqlite["errors"],
                            "payload_bytes": memory_sqlite["payload_bytes"],
                            "index_bytes": memory_sqlite["index_bytes"],
                        },
                    ],
                    "skipped": [{"name": "memory_jsonl", "mode": "live_optional", "reason": "missing dsn"}],
                }
            ]
        },
        quick=True,
        include_live=False,
    )

    assert quality_gate["ok"] is False
    assert "ranking account_memory fastest_stable must be non-empty" in quality_gate["errors"]
    assert "ranking account_memory candidate name must be non-empty" in quality_gate["errors"]
    assert "ranking account_memory duplicate candidate name: memory_jsonl" in quality_gate["errors"]
    assert "ranking account_memory skipped item name must be non-empty" in quality_gate["errors"]
    assert "ranking account_memory duplicate skipped name: memory_postgres" in quality_gate["errors"]
    assert "ranking account_memory skipped item must not also be a candidate: memory_jsonl" in quality_gate["errors"]
    assert "ranking account_memory fastest_stable must not be skipped" in fastest_skipped["errors"]


def test_benchmark_quality_gate_rejects_ranking_names_outside_configured_sets() -> None:
    quality_gate = benchmark_module._build_quality_gate(
        [],
        comparisons={
            "stable_backend_rankings": [
                {
                    "category": "account_memory",
                    "fastest_stable": "custom_memory_backend",
                    "candidates": [
                        {"name": "memory_jsonl"},
                        {"name": "custom_memory_backend"},
                    ],
                    "skipped": [
                        {"name": "custom_memory_backup", "mode": "live_optional", "reason": "missing dsn"},
                    ],
                }
            ]
        },
        quick=True,
        include_live=False,
    )

    assert quality_gate["ok"] is False
    assert "ranking account_memory candidate custom_memory_backend is not in configured benchmark name set" in quality_gate["errors"]
    assert "ranking account_memory skipped item custom_memory_backup is not in configured benchmark name set" in quality_gate["errors"]


def test_benchmark_quality_gate_rejects_rankings_that_do_not_match_results() -> None:
    result = benchmark_module._result(
        name="memory_jsonl",
        category="account_memory",
        iterations=1,
        total_ms=10.0,
        ok=True,
        errors=0,
        payload_bytes=100,
        index_bytes=0,
        mode="local",
    )
    skipped = benchmark_module._result(
        name="memory_postgres",
        category="account_memory",
        iterations=0,
        total_ms=0.0,
        ok=False,
        skipped=True,
        errors=0,
        payload_bytes=0,
        index_bytes=0,
        mode="live_optional",
        reason="missing dsn",
    )

    quality_gate = benchmark_module._build_quality_gate(
        [result, skipped],
        comparisons={
            "stable_backend_rankings": [
                {
                    "category": "account_memory",
                    "fastest_stable": "memory_sqlite_projection",
                    "candidates": [
                        {
                            "rank": 2,
                            "name": "memory_jsonl",
                            "mode": "mutated",
                            "throughput_ops_s": 999.0,
                            "total_ms": result["total_ms"],
                            "errors": result["errors"],
                            "payload_bytes": result["payload_bytes"],
                            "index_bytes": result["index_bytes"],
                        },
                        {
                            "rank": 2,
                            "name": "memory_sqlite_projection",
                            "mode": "local",
                            "throughput_ops_s": 1.0,
                            "total_ms": 1.0,
                            "errors": 0,
                            "payload_bytes": 1,
                            "index_bytes": 0,
                        },
                    ],
                    "skipped": [{"name": "memory_postgres", "mode": "live_optional", "reason": "different"}],
                }
            ]
        },
        quick=True,
        include_live=False,
    )

    assert quality_gate["ok"] is False
    assert "ranking account_memory candidate memory_jsonl mode must match result" in quality_gate["errors"]
    assert "ranking account_memory candidate memory_jsonl throughput_ops_s must match result" in quality_gate["errors"]
    assert "ranking account_memory candidate memory_jsonl rank must be 1" in quality_gate["errors"]
    assert "ranking account_memory candidate memory_sqlite_projection must reference a successful result" in quality_gate["errors"]
    assert "ranking account_memory skipped item memory_postgres reason must match skipped result" in quality_gate["errors"]
    assert "ranking account_memory fastest_stable must match rank 1 candidate" in quality_gate["errors"]


def test_benchmark_quality_gate_requires_specific_plan2_benchmark_names() -> None:
    base_result = {
        "category": "account_memory",
        "ok": True,
        "skipped": False,
        "iterations": 1,
        "total_ms": 1.0,
        "throughput_ops_s": 1.0,
        "errors": 0,
        "payload_bytes": 1,
        "index_bytes": 0,
        "mode": "local",
        "details": {
            "network_calls": 0,
            "openai_calls": 0,
            "provider_calls": 0,
            "remote_calls": 0,
            "llm_calls": 0,
        },
    }
    results = [
        {
            **base_result,
            "name": required_name,
            "category": "account_memory" if required_name == "memory_jsonl" else "custom",
        }
        for required_name in sorted(benchmark_module.REQUIRED_BENCHMARK_NAMES - {"youtube_local_pipeline_cache_no_openai"})
    ]

    quality_gate = benchmark_module._build_quality_gate(
        results,
        comparisons={"stable_backend_rankings": []},
        quick=True,
        include_live=False,
    )

    assert quality_gate["ok"] is False
    assert any("missing required benchmark results: youtube_local_pipeline_cache_no_openai" == error for error in quality_gate["errors"])


def test_benchmark_quality_gate_rejects_required_name_category_mismatch() -> None:
    base_result = {
        "ok": True,
        "skipped": False,
        "iterations": 1,
        "total_ms": 1.0,
        "throughput_ops_s": 1.0,
        "errors": 0,
        "payload_bytes": 1,
        "index_bytes": 0,
        "mode": "local",
        "details": {
            "network_calls": 0,
            "openai_calls": 0,
            "provider_calls": 0,
            "remote_calls": 0,
            "llm_calls": 0,
        },
    }
    results = [
        {
            **base_result,
            "name": name,
            "category": "qdrant" if name == "memory_jsonl" else category,
        }
        for name, category in sorted(benchmark_module.REQUIRED_BENCHMARK_NAME_CATEGORIES.items())
    ]

    quality_gate = benchmark_module._build_quality_gate(
        results,
        comparisons={"stable_backend_rankings": []},
        quick=True,
        include_live=False,
    )

    assert quality_gate["ok"] is False
    assert "memory_jsonl category must be account_memory" in quality_gate["errors"]


def test_benchmark_quality_gate_rejects_duplicate_result_names() -> None:
    base_result = {
        "name": "memory_jsonl",
        "category": "account_memory",
        "ok": True,
        "skipped": False,
        "iterations": 1,
        "total_ms": 1.0,
        "throughput_ops_s": 1.0,
        "errors": 0,
        "payload_bytes": 1,
        "index_bytes": 0,
        "mode": "local",
        "details": {
            "network_calls": 0,
            "openai_calls": 0,
            "provider_calls": 0,
            "remote_calls": 0,
            "llm_calls": 0,
        },
    }

    quality_gate = benchmark_module._build_quality_gate(
        [
            base_result,
            {
                **base_result,
                "category": "qdrant",
            },
        ],
        comparisons={"stable_backend_rankings": []},
        quick=True,
        include_live=False,
    )

    assert quality_gate["ok"] is False
    assert "duplicate benchmark result name: memory_jsonl" in quality_gate["errors"]


def test_stable_backend_ranking_excludes_erroring_candidates() -> None:
    ranking = benchmark_module._stable_backend_ranking(
        category="account_memory",
        names={"memory_jsonl", "memory_sqlite_projection"},
        results=[
            {
                "name": "memory_jsonl",
                "category": "account_memory",
                "ok": True,
                "skipped": False,
                "mode": "local",
                "iterations": 1,
                "throughput_ops_s": 100000.0,
                "total_ms": 0.01,
                "errors": 1,
                "payload_bytes": 100,
                "index_bytes": 100,
                "note": "fast but invalid",
            },
            {
                "name": "memory_sqlite_projection",
                "category": "account_memory",
                "ok": True,
                "skipped": False,
                "mode": "local",
                "iterations": 1,
                "throughput_ops_s": 10.0,
                "total_ms": 10.0,
                "errors": 0,
                "payload_bytes": 100,
                "index_bytes": 100,
                "note": "stable",
            },
        ],
    )

    assert ranking is not None
    assert ranking["fastest_stable"] == "memory_sqlite_projection"
    assert [candidate["name"] for candidate in ranking["candidates"]] == ["memory_sqlite_projection"]


def test_stable_backend_ranking_excludes_incomplete_measurement_candidates() -> None:
    ranking = benchmark_module._stable_backend_ranking(
        category="account_memory",
        names={"memory_jsonl", "memory_sqlite_projection"},
        results=[
            {
                "name": "memory_jsonl",
                "category": "account_memory",
                "ok": True,
                "skipped": False,
                "mode": "local",
                "iterations": 0,
                "throughput_ops_s": 100000.0,
                "total_ms": 0.01,
                "errors": 0,
                "payload_bytes": 0,
                "index_bytes": 0,
                "note": "fast but incomplete",
            },
            {
                "name": "memory_sqlite_projection",
                "category": "account_memory",
                "ok": True,
                "skipped": False,
                "mode": "local",
                "iterations": 1,
                "throughput_ops_s": 10.0,
                "total_ms": 10.0,
                "errors": 0,
                "payload_bytes": 100,
                "index_bytes": 0,
                "note": "stable",
            },
        ],
    )

    assert ranking is not None
    assert ranking["fastest_stable"] == "memory_sqlite_projection"
    assert [candidate["name"] for candidate in ranking["candidates"]] == ["memory_sqlite_projection"]


def test_stable_backend_ranking_excludes_wrong_category_skips() -> None:
    ranking = benchmark_module._stable_backend_ranking(
        category="account_memory",
        names={"memory_jsonl", "memory_postgres"},
        results=[
            {
                "name": "memory_jsonl",
                "category": "account_memory",
                "ok": True,
                "skipped": False,
                "mode": "local",
                "iterations": 1,
                "throughput_ops_s": 10.0,
                "total_ms": 10.0,
                "errors": 0,
                "payload_bytes": 100,
                "index_bytes": 0,
                "note": "stable",
            },
            {
                "name": "memory_postgres",
                "category": "qdrant",
                "ok": False,
                "skipped": True,
                "mode": "live_optional",
                "reason": "missing dsn",
                "iterations": 0,
                "throughput_ops_s": 0.0,
                "total_ms": 0.0,
                "errors": 0,
                "payload_bytes": 0,
                "index_bytes": 0,
            },
        ],
    )

    assert ranking is not None
    assert ranking["skipped"] == []


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
            "--no-obsidian",
            "--no-admin-notify",
        ]
    )

    assert result == 0
    assert markdown_path.exists()
    assert json_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["include_live"] is False
    assert payload["live_hf"] is False
    assert payload["live_qdrant"] is False
    assert payload["profile"] == ""
    assert payload["results"]
    assert payload["comparisons"]["stable_backend_rankings"]
    assert payload["regression"]["status"] == "not_configured"
    assert "TeeBotus Benchmarks" in markdown_path.read_text(encoding="utf-8")


def test_run_benchmarks_cli_quick_writes_obsidian_and_notifies_admins(tmp_path, monkeypatch, capsys) -> None:
    suite = {"ok": True, "quick": True, "results": [{"name": "memory_jsonl"}]}
    notified: list[dict[str, object]] = []

    async def fake_notify(**kwargs):  # noqa: ANN003
        notified.append(kwargs)
        return ()

    monkeypatch.setattr(benchmark_module, "run_benchmarks", lambda **_kwargs: suite)
    monkeypatch.setattr(benchmark_module, "render_markdown", lambda _suite: "# TeeBotus Benchmarks\n\nok\n")
    monkeypatch.setattr(benchmark_module, "notify_benchmark_admin_accounts", fake_notify)

    result = benchmark_module.main(["--quick", "--entries", "1", "--iterations", "1", "--obsidian-dir", str(tmp_path)])

    assert result == 0
    markdown_path = tmp_path / benchmark_module.DEFAULT_OBSIDIAN_BENCHMARK_MD
    json_path = tmp_path / benchmark_module.DEFAULT_OBSIDIAN_BENCHMARK_JSON
    assert markdown_path.read_text(encoding="utf-8") == "# TeeBotus Benchmarks\n\nok\n"
    assert json.loads(json_path.read_text(encoding="utf-8")) == suite
    assert len(notified) == 1
    assert notified[0]["markdown_document"] == "# TeeBotus Benchmarks\n\nok\n"
    assert notified[0]["markdown_filename"] == benchmark_module.DEFAULT_OBSIDIAN_BENCHMARK_MD
    assert notified[0]["json_artifact_path"] == json_path
    assert notified[0]["benchmark_suite"] == suite
    captured = capsys.readouterr()
    assert "benchmark_obsidian=written" in captured.err


def test_run_benchmarks_cli_quick_side_effects_can_be_disabled(tmp_path, monkeypatch) -> None:
    suite = {"ok": True, "quick": True, "results": []}
    notified = False

    async def fake_notify(**_kwargs):  # noqa: ANN003
        nonlocal notified
        notified = True
        return ()

    monkeypatch.setattr(benchmark_module, "run_benchmarks", lambda **_kwargs: suite)
    monkeypatch.setattr(benchmark_module, "render_markdown", lambda _suite: "# TeeBotus Benchmarks\n")
    monkeypatch.setattr(benchmark_module, "notify_benchmark_admin_accounts", fake_notify)

    result = benchmark_module.main(
        [
            "--quick",
            "--entries",
            "1",
            "--iterations",
            "1",
            "--obsidian-dir",
            str(tmp_path),
            "--no-obsidian",
            "--no-admin-notify",
        ]
    )

    assert result == 0
    assert notified is False
    assert not (tmp_path / benchmark_module.DEFAULT_OBSIDIAN_BENCHMARK_MD).exists()
    assert not (tmp_path / benchmark_module.DEFAULT_OBSIDIAN_BENCHMARK_JSON).exists()


def test_run_benchmarks_cli_admin_notify_uses_local_dotenv_defaults(tmp_path, monkeypatch) -> None:
    suite = {"ok": True, "quick": True, "results": []}
    notified: list[dict[str, object]] = []
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".env").write_text(
        "TEEBOTUS_INSTANCES_DIR=dotenv-instances\n"
        "TEEBOTUS_LOGGER_TELEGRAM_TOKEN='dotenv-token'\n",
        encoding="utf-8",
    )

    async def fake_notify(**kwargs):  # noqa: ANN003
        notified.append(kwargs)
        return ()

    monkeypatch.delenv("TEEBOTUS_INSTANCES_DIR", raising=False)
    monkeypatch.delenv("TEEBOTUS_LOGGER_TELEGRAM_TOKEN", raising=False)
    monkeypatch.setattr(benchmark_module, "REPO_ROOT", repo_root)
    monkeypatch.setattr(benchmark_module, "run_benchmarks", lambda **_kwargs: suite)
    monkeypatch.setattr(benchmark_module, "render_markdown", lambda _suite: "# TeeBotus Benchmarks\n")
    monkeypatch.setattr(benchmark_module, "notify_benchmark_admin_accounts", fake_notify)

    result = benchmark_module.main(["--quick", "--no-obsidian"])

    assert result == 0
    assert len(notified) == 1
    assert notified[0]["instances_dir"] == repo_root / "dotenv-instances"
    assert notified[0]["env"]["TEEBOTUS_LOGGER_TELEGRAM_TOKEN"] == "dotenv-token"


def test_run_benchmarks_cli_admin_notify_keeps_process_env_over_dotenv(tmp_path, monkeypatch) -> None:
    suite = {"ok": True, "quick": True, "results": []}
    notified: list[dict[str, object]] = []
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".env").write_text("TEEBOTUS_INSTANCES_DIR=dotenv-instances\n", encoding="utf-8")

    async def fake_notify(**kwargs):  # noqa: ANN003
        notified.append(kwargs)
        return ()

    monkeypatch.setenv("TEEBOTUS_INSTANCES_DIR", "process-instances")
    monkeypatch.setattr(benchmark_module, "REPO_ROOT", repo_root)
    monkeypatch.setattr(benchmark_module, "run_benchmarks", lambda **_kwargs: suite)
    monkeypatch.setattr(benchmark_module, "render_markdown", lambda _suite: "# TeeBotus Benchmarks\n")
    monkeypatch.setattr(benchmark_module, "notify_benchmark_admin_accounts", fake_notify)

    result = benchmark_module.main(["--quick", "--no-obsidian"])

    assert result == 0
    assert notified[0]["instances_dir"] == repo_root / "process-instances"


def test_run_benchmarks_requires_explicit_include_live_for_postgres(monkeypatch) -> None:
    seen_dsns: list[str] = []

    def fake_postgres_backend(*, entries: int, select_runs: int, dsn: str):  # noqa: ARG001
        seen_dsns.append(dsn)
        return {
            "backend": "postgres-row-encrypted-memory",
            "skipped": True,
            "reason": "fake",
            "append_total_ms": 0.0,
            "rebuild_ms": 0.0,
            "select_median_ms": 0.0,
        }

    monkeypatch.setattr(benchmark_suite, "benchmark_postgres_backend", fake_postgres_backend)

    quick_suite = run_benchmarks(entries=1, iterations=1, quick=True, postgres_dsn="postgresql://bench")
    live_suite = run_benchmarks(entries=1, iterations=1, quick=False, include_live=True, postgres_dsn="postgresql://bench")

    assert seen_dsns == ["", "postgresql://bench"]
    assert quick_suite["include_live"] is False
    assert live_suite["include_live"] is True


def test_run_benchmarks_live_flags_add_explicit_optional_results(monkeypatch) -> None:
    def fake_hf_live(*, profile: str):
        assert profile == "hf_pool_default"
        return benchmark_module._result(
            name="hf_pool_live_health",
            category="hf_pool",
            iterations=1,
            total_ms=1.0,
            ok=True,
            mode="live_hf",
            details={"profile": profile, "network_calls": 1, "provider_calls": 1, "remote_calls": 1},
        )

    def fake_qdrant_live():
        return benchmark_module._result(
            name="qdrant_health_live",
            category="qdrant",
            iterations=1,
            total_ms=1.0,
            ok=True,
            mode="live_qdrant",
            details={"target": "http://127.0.0.1:6333", "network_calls": 1, "provider_calls": 0, "remote_calls": 0},
        )

    monkeypatch.setattr(benchmark_suite, "_benchmark_hf_pool_live", fake_hf_live)
    monkeypatch.setattr(benchmark_suite, "_benchmark_qdrant_health_live", fake_qdrant_live)

    suite = run_benchmarks(
        entries=1,
        iterations=1,
        quick=True,
        live_hf=True,
        live_qdrant=True,
        profile="hf_pool_default",
    )

    names = {result["name"] for result in suite["results"]}
    assert suite["include_live"] is True
    assert suite["live_hf"] is True
    assert suite["live_qdrant"] is True
    assert suite["profile"] == "hf_pool_default"
    assert "hf_pool_live_health" in names
    assert "qdrant_health_live" in names


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
