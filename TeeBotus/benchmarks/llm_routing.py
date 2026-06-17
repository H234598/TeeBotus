from __future__ import annotations

import json
import statistics
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from TeeBotus.benchmarks.core import BenchmarkResult, result
from TeeBotus.decisions import parse_bibliothekar_query_decision, parse_memory_candidate
from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.free_tier import GeminiFreeTierGuard, reset_gemini_free_tier_budget_state, resolve_gemini_free_tier_limits
from TeeBotus.llm.gemini_limits_refresh import cached_gemini_free_tier_limit_values, refresh_gemini_free_tier_limits_if_due
from TeeBotus.llm.keyring import RotatingAPIKeyRing, resolve_gemini_api_key_ring
from TeeBotus.llm.profiles import load_llm_profiles, load_llm_routing, select_llm_route
from TeeBotus.runtime.llm_factory import build_runtime_text_llm_client


def benchmark_llm_router(*, iterations: int) -> BenchmarkResult:
    profiles = load_llm_profiles()
    _default_profile, routing = load_llm_routing()
    route_timings = [_timed_ms(lambda: select_llm_route("structured_decision", profiles=profiles, routing=routing)) for _ in range(iterations)]
    runtime_timings = [
        _timed_ms(
            lambda: build_runtime_text_llm_client(
                instructions=BotInstructions(),
                openai_client=None,
                purpose="structured_decision",
                allow_remote_fallback=True,
            )
        )
        for _ in range(iterations)
    ]
    decision_payload = {
        "should_search": True,
        "query": "Therapie Schlaf Tagesstruktur",
        "confidence": 0.91,
        "reason_short": "benchmark fake structured decision",
        "source": "model",
    }
    memory_payload = {
        "should_store": True,
        "memory_type": "therapy_goal",
        "text": "Morgens kurzen Spaziergang als Therapieaufgabe testen.",
        "sensitivity": "medium",
        "confidence": 0.88,
    }
    decision_timings = [_timed_ms(lambda: parse_bibliothekar_query_decision(decision_payload)) for _ in range(iterations)]
    memory_timings = [_timed_ms(lambda: parse_memory_candidate(memory_payload)) for _ in range(iterations)]
    client = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        purpose="structured_decision",
        allow_remote_fallback=True,
        env={"GROQ_API_KEY": "benchmark-groq-key"},
    )
    direct_blocked_client = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        provider="ollama",
        model="broken",
        fallback_models="groq/llama-3.1-8b-instant,ollama_chat/qwen2.5:7b",
    )
    direct_allowed_client = build_runtime_text_llm_client(
        instructions=BotInstructions(),
        openai_client=None,
        provider="ollama",
        model="broken",
        fallback_models="groq/llama-3.1-8b-instant,ollama_chat/qwen2.5:7b",
        allow_remote_fallback=True,
    )
    default_route = select_llm_route("structured_decision", profiles=profiles, routing=routing)
    explicit_fallback_route = select_llm_route("structured_decision", profiles=profiles, routing=routing, allow_remote_fallback=True)
    fallback_client = getattr(client, "fallback_client", None)
    return result(
        name="llm_router_structured_decision",
        category="llm_router",
        iterations=iterations * 4,
        total_ms=sum(route_timings) + sum(runtime_timings) + sum(decision_timings) + sum(memory_timings),
        payload_bytes=len(json.dumps({"bibliothekar": decision_payload, "memory": memory_payload}, ensure_ascii=False).encode("utf-8")),
        index_bytes=len(json.dumps({"profiles": list(profiles), "routing": list(routing)}, ensure_ascii=False).encode("utf-8")),
        details={
            "median_route_ms": statistics.median(route_timings),
            "median_runtime_client_ms": statistics.median(runtime_timings),
            "median_structured_decision_ms": statistics.median(decision_timings),
            "median_memory_candidate_ms": statistics.median(memory_timings),
            "memory_candidate_kind": parse_memory_candidate(memory_payload).memory_type,
            "profile_count": len(profiles),
            "route_count": len(routing),
            "runtime_client": type(client).__name__,
            "runtime_provider": _benchmark_client_provider(client),
            "runtime_model": _benchmark_client_model(client),
            "runtime_fallback_client": type(fallback_client).__name__ if fallback_client is not None else "",
            "runtime_fallback_model": getattr(fallback_client, "model", ""),
            "remote_fallback_default_enabled": bool(default_route.fallback_models),
            "default_fallback_models": list(default_route.fallback_models),
            "default_fallback_profile": default_route.fallback_profile_name,
            "explicit_remote_fallback_enabled": bool(explicit_fallback_route.fallback_models),
            "explicit_remote_fallback_models": list(explicit_fallback_route.fallback_models),
            "explicit_remote_fallback_api_key_env": explicit_fallback_route.fallback_api_key_env,
            "explicit_remote_fallback_api_key_mapped": bool(
                getattr(fallback_client, "api_key", "") or getattr(fallback_client, "fallback_api_keys", {})
            ),
            "direct_remote_fallback_default_models": list(getattr(direct_blocked_client, "fallback_models", ())),
            "direct_remote_fallback_allowed_models": list(getattr(direct_allowed_client, "fallback_models", ())),
            "network_calls": 0,
        },
    )


def benchmark_gemini_free_tier_guard(*, iterations: int) -> BenchmarkResult:
    with tempfile.TemporaryDirectory(prefix="teebotus-gemini-bench-") as tmp:
        cache_path = Path(tmp) / "gemini_free_tier_limits.json"
        env = {
            "TEEBOTUS_GEMINI_FREE_TIER_CACHE": str(cache_path),
            "TEEBOTUS_GEMINI_FREE_TIER_LIMITS_URL": "https://bench.local/gemini-free-tier.json",
            "TEEBOTUS_GEMINI_API_KEYS_ACCOUNT_1": "bench-a1,bench-a2",
            "TEEBOTUS_GEMINI_API_KEYS_ACCOUNT_2": "bench-b1,bench-b2",
            "TEEBOTUS_GEMINI_API_KEYS_ACCOUNT_3": "bench-c1,bench-c2",
        }
        refresh = refresh_gemini_free_tier_limits_if_due(
            env,
            force=True,
            now=lambda: datetime(2026, 6, 17, tzinfo=timezone.utc),
            fetcher=lambda _url, _timeout: json.dumps(
                {
                    "models": {
                        "gemini-2.5-flash": {
                            "rpm": 2,
                            "tpm": 100,
                            "rpd": 3,
                            "reserve_tokens": 10,
                        }
                    }
                }
            ),
        )
        cached_limits = cached_gemini_free_tier_limit_values(env, model="gemini/gemini-2.5-flash")
        limits = resolve_gemini_free_tier_limits(env, provider="litellm", model="gemini/gemini-2.5-flash")
        ring_keys = resolve_gemini_api_key_ring(env)
        ring = RotatingAPIKeyRing(ring_keys, name="benchmark-gemini-free-tier")
        if ring_keys:
            ring.mark_success(ring_keys[0])
        reset_gemini_free_tier_budget_state()
        guard = GeminiFreeTierGuard(
            limits,
            now=lambda: datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc),
        )

        blocked_reasons: list[str] = []
        rotated_to: list[str] = []
        allowed = 0
        blocked = 0

        def exercise_once(index: int) -> None:
            nonlocal allowed, blocked
            active_key = ring.ordered_keys()[0]
            quota_owner = f"{active_key}:{index}"
            first = guard.reserve(
                quota_owner=quota_owner,
                model="gemini/gemini-2.5-flash",
                estimated_input_tokens=85,
            )
            second = guard.reserve(
                quota_owner=quota_owner,
                model="gemini/gemini-2.5-flash",
                estimated_input_tokens=6,
            )
            allowed += 1 if first.allowed else 0
            blocked += 0 if second.allowed else 1
            if not second.allowed:
                blocked_reasons.append(second.reason)
                ring.mark_limited(active_key)
            rotated_key = ring.ordered_keys()[0]
            rotated_to.append(rotated_key)
            third = guard.reserve(
                quota_owner=f"{rotated_key}:{index}",
                model="gemini/gemini-2.5-flash",
                estimated_input_tokens=6,
            )
            allowed += 1 if third.allowed else 0
            if ring_keys:
                ring.mark_success(ring_keys[0])

        total_ms = _timed_ms(lambda: [exercise_once(index) for index in range(iterations)])
        expected_order = ("bench-a1", "bench-b1", "bench-c1", "bench-a2", "bench-b2", "bench-c2")
        payload = {
            "cached_limits": cached_limits,
            "refresh_status": refresh.status,
            "ring_size": len(ring_keys),
            "allowed": allowed,
            "blocked": blocked,
            "blocked_reasons": blocked_reasons[:3],
            "rotated_to": rotated_to[:3],
        }
        details = {
            "refresh_status": refresh.status,
            "cached_limits": cached_limits,
            "resolved_summary": limits.status_summary(),
            "ring_size": len(ring_keys),
            "ring_order_ok": ring_keys == expected_order,
            "blocked_before_provider": blocked == iterations,
            "rotation_after_limit_ok": all(key == "bench-b1" for key in rotated_to),
            "allowed_reservations": allowed,
            "blocked_reservations": blocked,
            "blocked_reason_contains_tpm": any("TPM free-tier budget" in reason for reason in blocked_reasons),
            "cache_file_written": cache_path.exists(),
            "network_calls": 0,
            "provider_calls": 0,
            "remote_calls": 0,
            "llm_calls": 0,
            "openai_calls": 0,
        }
        return result(
            name="gemini_free_tier_guard_cache_rotation",
            category="gemini_free_tier",
            iterations=iterations * 3,
            total_ms=total_ms,
            ok=refresh.status == "ok"
            and cached_limits == {"rpm": 2, "tpm": 100, "rpd": 3, "reserve_tokens": 10}
            and details["ring_order_ok"]
            and details["blocked_before_provider"]
            and details["rotation_after_limit_ok"],
            errors=0,
            payload_bytes=len(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
            index_bytes=cache_path.stat().st_size if cache_path.exists() else 0,
            note="gemini free-tier guard and key rotation",
            details=details,
        )


def _benchmark_client_provider(client: object | None) -> str:
    if client is None:
        return ""
    return str(getattr(client, "provider_name", "") or getattr(client, "provider", "") or "")


def _benchmark_client_model(client: object | None) -> str:
    if client is None:
        return ""
    selector = str(getattr(client, "model_selector", "") or "").strip()
    if selector:
        return selector
    model = str(getattr(client, "model", "") or "").strip()
    if model:
        return model
    pool_name = str(getattr(client, "pool_name", "") or "").strip()
    return f"pool:{pool_name}" if pool_name else ""


def _timed_ms(func: Callable[[], Any]) -> float:
    start = time.perf_counter()
    func()
    return (time.perf_counter() - start) * 1000


__all__ = [
    "benchmark_gemini_free_tier_guard",
    "benchmark_llm_router",
]
