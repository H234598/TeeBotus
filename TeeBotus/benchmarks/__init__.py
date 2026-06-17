from __future__ import annotations

from TeeBotus.benchmarks.adapters import benchmark_adapter_contracts
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
from TeeBotus.benchmarks.pydantic_ai import benchmark_decision_fake_model, benchmark_pydantic_structured_decisions
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
    "benchmark_decision_fake_model",
    "benchmark_gemini_free_tier_guard",
    "benchmark_hf_pool_eval_matrix",
    "benchmark_hf_pool_live",
    "benchmark_hf_pool_quick",
    "benchmark_llm_router",
    "benchmark_pydantic_structured_decisions",
    "benchmark_qdrant_health_live",
    "benchmark_qdrant_health_quick",
    "benchmark_qdrant_memory_index_quick",
    "benchmark_source_harvester_promote_index_flow",
    "benchmark_source_harvester_quality_gate",
    "result",
    "stable_backend_ranking",
]
