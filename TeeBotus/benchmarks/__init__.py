from __future__ import annotations

from TeeBotus.benchmarks.adapters import benchmark_adapter_contracts
from TeeBotus.benchmarks.bibliothekar import (
    benchmark_bibliothekar_haystack_fake_query,
    benchmark_bibliothekar_llamaindex_fake_query,
    benchmark_bibliothekar_local_query,
    benchmark_retrieval_embedding_reranker_matrix,
)
from TeeBotus.benchmarks.core import (
    BenchmarkResult,
    REQUIRED_BENCHMARK_CATEGORIES,
    REQUIRED_BENCHMARK_MIN_RANKING_CANDIDATES,
    REQUIRED_BENCHMARK_NAMES,
    REQUIRED_BENCHMARK_RANKING_CATEGORIES,
    STANDARD_BENCHMARK_FORBIDDEN_CALL_COUNTERS,
    build_comparisons,
    build_quality_gate,
    result,
    stable_backend_ranking,
)
from TeeBotus.benchmarks.hf_pool import benchmark_hf_pool_eval_matrix, benchmark_hf_pool_live, benchmark_hf_pool_quick
from TeeBotus.benchmarks.llm_routing import benchmark_gemini_free_tier_guard, benchmark_llm_router
from TeeBotus.benchmarks.memory import benchmark_memory_jsonl_to_sqlite_migration, memory_results
from TeeBotus.benchmarks.pydantic_ai import benchmark_decision_fake_model, benchmark_pydantic_structured_decisions
from TeeBotus.benchmarks.proactive import benchmark_proactive_tool_plan_due_dispatch_gates
from TeeBotus.benchmarks.qdrant import (
    benchmark_qdrant_health_live,
    benchmark_qdrant_health_quick,
    benchmark_qdrant_memory_index_quick,
)
from TeeBotus.benchmarks.source_quality import (
    benchmark_source_harvester_promote_index_flow,
    benchmark_source_harvester_quality_gate,
)

__all__ = [
    "BenchmarkResult",
    "REQUIRED_BENCHMARK_CATEGORIES",
    "REQUIRED_BENCHMARK_MIN_RANKING_CANDIDATES",
    "REQUIRED_BENCHMARK_NAMES",
    "REQUIRED_BENCHMARK_RANKING_CATEGORIES",
    "STANDARD_BENCHMARK_FORBIDDEN_CALL_COUNTERS",
    "build_comparisons",
    "build_quality_gate",
    "benchmark_adapter_contracts",
    "benchmark_bibliothekar_haystack_fake_query",
    "benchmark_bibliothekar_llamaindex_fake_query",
    "benchmark_bibliothekar_local_query",
    "benchmark_decision_fake_model",
    "benchmark_gemini_free_tier_guard",
    "benchmark_hf_pool_eval_matrix",
    "benchmark_hf_pool_live",
    "benchmark_hf_pool_quick",
    "benchmark_llm_router",
    "benchmark_memory_jsonl_to_sqlite_migration",
    "benchmark_pydantic_structured_decisions",
    "benchmark_proactive_tool_plan_due_dispatch_gates",
    "benchmark_qdrant_health_live",
    "benchmark_qdrant_health_quick",
    "benchmark_qdrant_memory_index_quick",
    "benchmark_retrieval_embedding_reranker_matrix",
    "benchmark_source_harvester_promote_index_flow",
    "benchmark_source_harvester_quality_gate",
    "memory_results",
    "result",
    "stable_backend_ranking",
]
