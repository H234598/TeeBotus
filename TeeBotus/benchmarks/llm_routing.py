from __future__ import annotations

import json
import os
import statistics
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from TeeBotus.benchmarks.core import BenchmarkResult, result
from TeeBotus.decisions import parse_bibliothekar_query_decision, parse_memory_candidate
from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.base import LLMResponse
from TeeBotus.llm.capabilities import (
    GEMINI_INTERACTIONS_CAPABILITIES,
    HF_POOL_TEXT_CAPABILITIES,
    LITELLM_TEXT_CAPABILITIES,
    OPENAI_CAPABILITIES,
    LLMCapabilities,
)
from TeeBotus.llm.free_tier import (
    GeminiFreeTierGuard,
    reset_gemini_free_tier_budget_state,
    resolve_gemini_free_tier_limits,
    route_uses_gemini_api,
    route_uses_google_gemini,
)
from TeeBotus.llm.gemini_limits_refresh import cached_gemini_free_tier_limit_values, refresh_gemini_free_tier_limits_if_due
from TeeBotus.llm.keyring import RotatingAPIKeyRing, resolve_gemini_api_key_ring
from TeeBotus.llm_client import normalize_llm_provider
from TeeBotus.llm.profiles import load_llm_profiles, load_llm_routing, select_llm_route
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, telegram_identity_key
import TeeBotus.runtime.engine as runtime_engine
from TeeBotus.runtime.engine import TeeBotusEngine
from TeeBotus.runtime.events import IncomingEvent
from TeeBotus.runtime.llm_factory import build_runtime_text_llm_client
from TeeBotus.runtime.qdrant_memory import QdrantMemoryResult
from TeeBotus.runtime.state import RuntimeStateStore

EMERGENCY_LIVE_LLM_ENV = "TEEBOTUS_EMERGENCY_LIVE_LLM_BENCHMARK"
EMERGENCY_LIVE_LLM_CONFIRMATION = "NOTFALL_KOSTEN_AKZEPTIERT"
EMERGENCY_LIVE_LLM_MAX_CALLS_ENV = "TEEBOTUS_EMERGENCY_LIVE_LLM_MAX_CALLS"
EMERGENCY_LIVE_LLM_PATHS_ENV = "TEEBOTUS_EMERGENCY_LIVE_LLM_PATHS"


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
        ring = RotatingAPIKeyRing(ring_keys, name=f"benchmark-gemini-free-tier:{cache_path}")
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


def benchmark_llm_message_latency_paths(*, iterations: int) -> BenchmarkResult:
    message_count = max(4, int(iterations or 1))
    path_specs = _llm_message_path_specs()
    paths = [_measure_engine_message_path(spec, message_count=message_count) for spec in path_specs]
    total_ms = sum(float(path["total_ms"]) for path in paths)
    all_ok = all(bool(path["ok"]) for path in paths)
    payload = {"paths": paths, "message_count_per_path": message_count}
    return result(
        name="llm_message_latency_paths",
        category="llm_router",
        iterations=message_count * len(path_specs),
        total_ms=total_ms,
        ok=all_ok,
        errors=0 if all_ok else 1,
        payload_bytes=len(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
        note="engine message latency by llm path, synthetic clients only",
        details={
            "paths": paths,
            "path_count": len(path_specs),
            "message_count_per_path": message_count,
            "openai_account_state_ok": _path_ok(paths, "openai_responses_stateful"),
            "gemini_account_state_ok": _path_ok(paths, "litellm_gemini_stateful"),
            "stateless_paths_ignore_state_ok": all(
                _path_ok(paths, name)
                for name in ("litellm_gemini_paid_stateless", "litellm_local_stateless", "hf_pool_stateless")
            ),
            "synthetic_clients_only": True,
            "network_calls": 0,
            "provider_calls": 0,
            "remote_calls": 0,
            "llm_calls": 0,
            "openai_calls": 0,
        },
    )


def benchmark_llm_decision_qdrant_path_matrix(*, iterations: int) -> BenchmarkResult:
    repetitions = max(1, min(3, int(iterations or 1)))
    scenarios = _llm_decision_qdrant_scenarios()
    paths = [
        _measure_engine_decision_qdrant_path(spec, scenario, repetitions=repetitions)
        for spec in _llm_message_path_specs()
        for scenario in scenarios
    ]
    total_ms = sum(float(path["total_ms"]) for path in paths)
    all_ok = all(bool(path["ok"]) for path in paths)
    qdrant_paths = [path for path in paths if path["memory_mode"] == "qdrant"]
    decision_paths = [path for path in paths if path["decision_layer"]]
    bibliothekar_paths = [path for path in paths if path["bibliothekar"]]
    payload = {"paths": paths, "repetitions_per_path": repetitions}
    return result(
        name="llm_decision_qdrant_path_matrix",
        category="llm_router",
        iterations=repetitions * len(paths),
        total_ms=total_ms,
        ok=all_ok,
        errors=0 if all_ok else 1,
        payload_bytes=len(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
        note="engine llm path matrix with decision layer and qdrant fake index",
        details={
            "paths": paths,
            "path_count": len(paths),
            "repetitions_per_path": repetitions,
            "llm_path_classes": [spec.name for spec in _llm_message_path_specs()],
            "scenario_count": len(scenarios),
            "qdrant_path_count": len(qdrant_paths),
            "decision_path_count": len(decision_paths),
            "bibliothekar_path_count": len(bibliothekar_paths),
            "qdrant_paths_ok": bool(qdrant_paths) and all(path["qdrant_ok"] for path in qdrant_paths),
            "decision_paths_ok": bool(decision_paths) and all(path["decision_ok"] for path in decision_paths),
            "bibliothekar_paths_ok": bool(bibliothekar_paths) and all(path["bibliothekar_ok"] for path in bibliothekar_paths),
            "synthetic_clients_only": True,
            "fake_qdrant_only": True,
            "network_calls": 0,
            "provider_calls": 0,
            "remote_calls": 0,
            "llm_calls": 0,
            "openai_calls": 0,
        },
    )


def benchmark_live_llm_message_latency_paths(
    *,
    iterations: int,
    env: Mapping[str, str] | None = None,
    max_calls: int = 3,
) -> BenchmarkResult:
    source = os.environ if env is None else env
    if str(source.get(EMERGENCY_LIVE_LLM_ENV, "")).strip() != EMERGENCY_LIVE_LLM_CONFIRMATION:
        return _skipped_live_llm_result(
            reason=(
                f"emergency live LLM benchmark disabled; set {EMERGENCY_LIVE_LLM_ENV}="
                f"{EMERGENCY_LIVE_LLM_CONFIRMATION} and pass --emergency-live-llm"
            ),
            details={"configured_candidates": _live_llm_candidate_names(source)},
        )
    call_limit = _positive_int(source.get(EMERGENCY_LIVE_LLM_MAX_CALLS_ENV), default=max_calls)
    call_limit = max(1, min(12, call_limit))
    allowlist = _csv_set(source.get(EMERGENCY_LIVE_LLM_PATHS_ENV, ""))
    candidates = _live_llm_candidates(source)
    if allowlist:
        candidates = [candidate for candidate in candidates if candidate["name"] in allowlist]
    runnable = [candidate for candidate in candidates if candidate["runnable"]]
    selected = runnable[:call_limit]
    if not selected:
        return _skipped_live_llm_result(
            reason="emergency live LLM benchmark enabled, but no runnable configured LLM paths were found",
            details={
                "configured_candidates": [candidate["name"] for candidate in candidates],
                "skipped_candidates": [candidate for candidate in candidates if not candidate["runnable"]],
                "allowlist": sorted(allowlist),
            },
        )

    path_results = [_measure_live_llm_candidate(candidate, source=source, iterations=max(1, min(2, int(iterations or 1)))) for candidate in selected]
    total_ms = sum(float(path["total_ms"]) for path in path_results)
    provider_calls = sum(int(path["calls"]) for path in path_results)
    openai_calls = sum(int(path["calls"]) for path in path_results if path.get("provider") == "openai")
    ok = all(bool(path["ok"]) for path in path_results)
    payload = {"paths": path_results, "selected": [candidate["name"] for candidate in selected]}
    return result(
        name="live_llm_message_latency_paths",
        category="llm_router",
        iterations=provider_calls,
        total_ms=total_ms,
        ok=ok,
        errors=sum(0 if path["ok"] else 1 for path in path_results),
        payload_bytes=len(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
        note="EMERGENCY ONLY real provider/API LLM latency benchmark",
        mode="live_emergency_llm",
        details={
            "paths": path_results,
            "selected_paths": [candidate["name"] for candidate in selected],
            "configured_candidates": [candidate["name"] for candidate in candidates],
            "call_limit": call_limit,
            "confirmation_env": EMERGENCY_LIVE_LLM_ENV,
            "network_calls": provider_calls,
            "provider_calls": provider_calls,
            "remote_calls": provider_calls,
            "llm_calls": provider_calls,
            "openai_calls": openai_calls,
        },
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


def _timed_value_ms(func: Callable[[], Any]) -> tuple[float, Any]:
    start = time.perf_counter()
    value = func()
    return (time.perf_counter() - start) * 1000, value


@dataclass(frozen=True)
class _LLMMessagePathSpec:
    name: str
    provider: str
    model: str
    capabilities: LLMCapabilities
    stateful: bool


@dataclass(frozen=True)
class _LLMPathScenario:
    name: str
    memory_mode: str
    decision_layer: bool
    bibliothekar: bool


def _llm_message_path_specs() -> tuple[_LLMMessagePathSpec, ...]:
    return (
        _LLMMessagePathSpec(
            name="openai_responses_stateful",
            provider="openai",
            model="gpt-4.1-mini",
            capabilities=OPENAI_CAPABILITIES,
            stateful=True,
        ),
        _LLMMessagePathSpec(
            name="litellm_gemini_stateful",
            provider="litellm_gemini_stateful",
            model="gemini/gemini-3.5-flash",
            capabilities=GEMINI_INTERACTIONS_CAPABILITIES,
            stateful=True,
        ),
        _LLMMessagePathSpec(
            name="litellm_gemini_paid_stateful",
            provider="litellm_gemini_paid_stateful",
            model="gemini/gemini-3.5-flash",
            capabilities=GEMINI_INTERACTIONS_CAPABILITIES,
            stateful=True,
        ),
        _LLMMessagePathSpec(
            name="litellm_gemini_paid_stateless",
            provider="litellm_gemini_paid_stateless",
            model="gemini/gemini-3.5-flash",
            capabilities=LITELLM_TEXT_CAPABILITIES,
            stateful=False,
        ),
        _LLMMessagePathSpec(
            name="litellm_local_stateless",
            provider="litellm",
            model="ollama_chat/qwen2.5:7b",
            capabilities=LITELLM_TEXT_CAPABILITIES,
            stateful=False,
        ),
        _LLMMessagePathSpec(
            name="hf_pool_stateless",
            provider="hf_pool",
            model="pool:default#normal_chat",
            capabilities=HF_POOL_TEXT_CAPABILITIES,
            stateful=False,
        ),
    )


def _llm_decision_qdrant_scenarios() -> tuple[_LLMPathScenario, ...]:
    return tuple(
        _LLMPathScenario(
            name=f"memory_{memory_mode}__decision_{'on' if decision_layer else 'off'}__bibliothekar_{'on' if bibliothekar else 'off'}",
            memory_mode=memory_mode,
            decision_layer=decision_layer,
            bibliothekar=bibliothekar,
        )
        for memory_mode in ("none", "keyword", "qdrant")
        for decision_layer in (False, True)
        for bibliothekar in (False, True)
    )


class _SyntheticLLMClient:
    def __init__(self, spec: _LLMMessagePathSpec) -> None:
        self.spec = spec
        self.provider = spec.provider
        self.provider_name = spec.provider
        self.model = spec.model
        self.capabilities = spec.capabilities
        self.previous_ids: list[str | None] = []
        self.response_ids: list[str] = []
        self.user_texts: list[str] = []

    def create_reply(
        self,
        _user_text: str,
        _instructions: BotInstructions,
        previous_response_id: str | None = None,
    ) -> LLMResponse:
        self.user_texts.append(_user_text)
        self.previous_ids.append(previous_response_id)
        response_id = f"{self.spec.name}-resp-{len(self.previous_ids)}"
        self.response_ids.append(response_id)
        return LLMResponse(
            text=f"{self.spec.name} synthetic reply {len(self.previous_ids)}",
            response_id=response_id,
            provider=self.spec.provider,
            model=self.spec.model,
        )


def _measure_engine_message_path(spec: _LLMMessagePathSpec, *, message_count: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"teebotus-llm-message-{spec.name}-") as tmp:
        provider = StaticSecretProvider(b"b" * 32)
        data_dir = Path(tmp) / "Bench" / "data"
        account_store = AccountStore(data_dir / "accounts", "Bench", provider)
        state = RuntimeStateStore(data_dir, instance_name="Bench", secret_provider=provider)
        client = _SyntheticLLMClient(spec)
        instructions = BotInstructions(
            openai_enabled=True,
            llm_provider=spec.provider,
            llm_model=spec.model,
            user_memory_enabled=False,
        )
        engine = TeeBotusEngine(
            account_store=account_store,
            state=state,
            instructions=instructions,
            llm_client=client,
        )
        identity_a = telegram_identity_key(91001)
        identity_b = telegram_identity_key(91002)
        pattern = (identity_a, identity_a, identity_b, identity_a)
        identities = [pattern[index % len(pattern)] for index in range(message_count)]
        latencies = [
            _timed_ms(lambda index=index, identity=identity: engine.process(_benchmark_message_event(identity, index)))
            for index, identity in enumerate(identities)
        ]
        account_a = account_store.get_account_for_identity(identity_a)
        account_b = account_store.get_account_for_identity(identity_b)
        first_a_prev = client.previous_ids[0] if len(client.previous_ids) > 0 else "__missing__"
        second_a_prev = client.previous_ids[1] if len(client.previous_ids) > 1 else "__missing__"
        first_b_prev = client.previous_ids[2] if len(client.previous_ids) > 2 else "__missing__"
        third_a_prev = client.previous_ids[3] if len(client.previous_ids) > 3 else "__missing__"
        response_0 = client.response_ids[0] if len(client.response_ids) > 0 else "__missing__"
        response_1 = client.response_ids[1] if len(client.response_ids) > 1 else "__missing__"
        state_a = state.get_previous_response_id("Bench", account_a) if account_a else None
        state_b = state.get_previous_response_id("Bench", account_b) if account_b else None
        latest_a_response = _latest_response_for_identity(client.response_ids, identities, identity_a)
        latest_b_response = _latest_response_for_identity(client.response_ids, identities, identity_b)
        expected_stateful_ok = (
            first_a_prev is None
            and second_a_prev == response_0
            and first_b_prev is None
            and third_a_prev == response_1
            and state_a == latest_a_response
            and state_b == latest_b_response
        )
        expected_stateless_ok = all(previous_id is None for previous_id in client.previous_ids) and state_a is None and state_b is None
        ok = expected_stateful_ok if spec.stateful else expected_stateless_ok
        return {
            "path": spec.name,
            "provider": spec.provider,
            "model": spec.model,
            "stateful": spec.stateful,
            "ok": bool(ok),
            "message_count": message_count,
            "total_ms": sum(latencies),
            "mean_ms": statistics.fmean(latencies) if latencies else 0.0,
            "median_ms": statistics.median(latencies) if latencies else 0.0,
            "p95_ms": _percentile(latencies, 95),
            "min_ms": min(latencies) if latencies else 0.0,
            "max_ms": max(latencies) if latencies else 0.0,
            "local_client_calls": len(client.previous_ids),
            "first_a_previous_id": first_a_prev,
            "second_a_previous_id": second_a_prev,
            "first_b_previous_id": first_b_prev,
            "third_a_previous_id": third_a_prev,
            "account_a_stateful": bool(state_a),
            "account_b_stateful": bool(state_b),
        }


def _measure_engine_decision_qdrant_path(
    spec: _LLMMessagePathSpec,
    scenario: _LLMPathScenario,
    *,
    repetitions: int,
) -> dict[str, Any]:
    original_qdrant_index = runtime_engine.QdrantMemoryIndex
    _BenchmarkEngineQdrantIndex.reset()
    if scenario.memory_mode == "qdrant":
        runtime_engine.QdrantMemoryIndex = _BenchmarkEngineQdrantIndex  # type: ignore[assignment]
    try:
        return _measure_engine_decision_qdrant_path_inner(spec, scenario, repetitions=repetitions)
    finally:
        runtime_engine.QdrantMemoryIndex = original_qdrant_index  # type: ignore[assignment]


def _measure_engine_decision_qdrant_path_inner(
    spec: _LLMMessagePathSpec,
    scenario: _LLMPathScenario,
    *,
    repetitions: int,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"teebotus-llm-matrix-{spec.name}-") as tmp:
        provider = StaticSecretProvider(b"m" * 32)
        data_dir = Path(tmp) / "Bench" / "data"
        account_store = AccountStore(data_dir / "accounts", "Bench", provider)
        state = RuntimeStateStore(data_dir, instance_name="Bench", secret_provider=provider)
        identity = telegram_identity_key(92001)
        account_id = account_store.resolve_or_create_account(identity)
        if scenario.memory_mode in {"keyword", "qdrant"}:
            _seed_benchmark_account_memory(account_store, account_id)
        client = _SyntheticLLMClient(spec)
        decision_runner = _BenchmarkStructuredDecisionRunner() if scenario.decision_layer else None
        bibliothekar_store = _BenchmarkBibliothekarStore() if scenario.bibliothekar else None
        instructions = BotInstructions(
            openai_enabled=True,
            llm_provider=spec.provider,
            llm_model=spec.model,
            user_memory_enabled=scenario.memory_mode != "none",
            memory_search_semantic_enabled=scenario.memory_mode == "qdrant",
            memory_search_semantic_backend="qdrant" if scenario.memory_mode == "qdrant" else "",
            memory_search_local_limit=1,
            memory_search_semantic_limit=1,
            memory_search_qdrant_url="http://127.0.0.1:6333",
            bibliothekar_enabled=scenario.bibliothekar,
            bibliothekar_max_chunks=1,
            bibliothekar_max_prompt_chars=1200,
        )
        engine = TeeBotusEngine(
            account_store=account_store,
            state=state,
            instructions=instructions,
            llm_client=client,
            bibliothekar_store=bibliothekar_store,
            structured_decision_runner=decision_runner,
        )
        latencies = [
            _timed_ms(lambda index=index: engine.process(_benchmark_matrix_event(identity, index)))
            for index in range(repetitions)
        ]
        prompts = "\n".join(client.user_texts)
        decision_counts = decision_runner.schema_counts() if decision_runner is not None else {}
        bibliothekar_calls = len(bibliothekar_store.calls) if bibliothekar_store is not None else 0
        qdrant_search_calls = len(_BenchmarkEngineQdrantIndex.search_calls)
        qdrant_index_calls = len(_BenchmarkEngineQdrantIndex.index_calls)
        memory_context_present = "Persistentes Account-Memory:" in prompts
        keyword_selected = '"id": "mem_keyword"' in prompts
        qdrant_selected = '"id": "mem_semantic"' in prompts
        library_context_present = "Bibliothekar-Quellenkontext:" in prompts
        memory_ok = _memory_scenario_ok(
            scenario.memory_mode,
            memory_context_present=memory_context_present,
            keyword_selected=keyword_selected,
            qdrant_selected=qdrant_selected,
            qdrant_search_calls=qdrant_search_calls,
            repetitions=repetitions,
        )
        decision_ok = _decision_scenario_ok(scenario, decision_counts=decision_counts, repetitions=repetitions)
        bibliothekar_ok = (bibliothekar_calls >= repetitions and library_context_present) if scenario.bibliothekar else bibliothekar_calls == 0
        qdrant_ok = (
            qdrant_search_calls >= repetitions and qdrant_index_calls >= repetitions and qdrant_selected
            if scenario.memory_mode == "qdrant"
            else qdrant_search_calls == 0 and qdrant_index_calls == 0
        )
        ok = (
            len(client.previous_ids) == repetitions
            and memory_ok
            and decision_ok
            and bibliothekar_ok
            and qdrant_ok
        )
        return {
            "path": f"{spec.name}::{scenario.name}",
            "llm_path": spec.name,
            "provider": spec.provider,
            "model": spec.model,
            "memory_mode": scenario.memory_mode,
            "decision_layer": scenario.decision_layer,
            "bibliothekar": scenario.bibliothekar,
            "ok": bool(ok),
            "message_count": repetitions,
            "total_ms": sum(latencies),
            "mean_ms": statistics.fmean(latencies) if latencies else 0.0,
            "median_ms": statistics.median(latencies) if latencies else 0.0,
            "p95_ms": _percentile(latencies, 95),
            "local_client_calls": len(client.previous_ids),
            "memory_ok": memory_ok,
            "decision_ok": decision_ok,
            "bibliothekar_ok": bibliothekar_ok,
            "qdrant_ok": qdrant_ok,
            "decision_schema_counts": decision_counts,
            "bibliothekar_calls": bibliothekar_calls,
            "qdrant_search_calls": qdrant_search_calls,
            "qdrant_index_calls": qdrant_index_calls,
            "memory_context_present": memory_context_present,
            "keyword_selected": keyword_selected,
            "qdrant_selected": qdrant_selected,
            "library_context_present": library_context_present,
        }


def _benchmark_message_event(identity_key: str, index: int) -> IncomingEvent:
    return IncomingEvent(
        event_id=f"telegram:bench:{index}",
        instance="Bench",
        channel="telegram",
        adapter_slot=1,
        account_id="",
        identity_key=identity_key,
        chat_id=f"bench-chat-{identity_key}",
        chat_type="private",
        sender_id=identity_key,
        sender_name=identity_key,
        text=f"Benchmark message {index}",
        message_ref=str(index),
    )


def _benchmark_matrix_event(identity_key: str, index: int) -> IncomingEvent:
    return IncomingEvent(
        event_id=f"telegram:matrix-bench:{index}",
        instance="Bench",
        channel="telegram",
        adapter_slot=1,
        account_id="",
        identity_key=identity_key,
        chat_id="bench-matrix-chat",
        chat_type="private",
        sender_id=identity_key,
        sender_name="Benchmark User",
        text=f"Bitte behalte Schlaf und Tagesstruktur auf dem Schirm. Runde {index}",
        message_ref=f"matrix-{index}",
    )


def _seed_benchmark_account_memory(account_store: AccountStore, account_id: str) -> None:
    account_store.append_structured_memory_entry(
        account_id,
        {
            "id": "mem_keyword",
            "kind": "sleep_pattern",
            "memory_type": "semantic",
            "importance": 4,
            "keywords": ["schlaf", "tagesstruktur"],
            "user_text": "Schlaf profitiert von klarer Tagesstruktur.",
            "bot_text": "Gemerkt.",
        },
    )
    account_store.append_structured_memory_entry(
        account_id,
        {
            "id": "mem_semantic",
            "kind": "therapy_goal",
            "memory_type": "semantic",
            "importance": 5,
            "keywords": ["morgenroutine", "struktur"],
            "user_text": "Eine kleine Morgenroutine hilft bei depressiven Tagen.",
            "bot_text": "Gemerkt.",
        },
    )


def _memory_scenario_ok(
    memory_mode: str,
    *,
    memory_context_present: bool,
    keyword_selected: bool,
    qdrant_selected: bool,
    qdrant_search_calls: int,
    repetitions: int,
) -> bool:
    if memory_mode == "none":
        return not memory_context_present and qdrant_search_calls == 0
    if memory_mode == "keyword":
        return memory_context_present and keyword_selected and qdrant_search_calls == 0
    if memory_mode == "qdrant":
        return memory_context_present and qdrant_selected and qdrant_search_calls >= repetitions
    return False


def _decision_scenario_ok(
    scenario: _LLMPathScenario,
    *,
    decision_counts: dict[str, int],
    repetitions: int,
) -> bool:
    if not scenario.decision_layer:
        return not decision_counts
    if decision_counts.get("ReminderDecision", 0) < repetitions:
        return False
    if scenario.memory_mode != "none" and decision_counts.get("MemoryCandidate", 0) < repetitions:
        return False
    if scenario.bibliothekar and decision_counts.get("BibliothekarQueryDecision", 0) < repetitions:
        return False
    return True


class _BenchmarkStructuredDecisionRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, prompt: str, schema: type[Any]) -> dict[str, Any]:
        schema_name = getattr(schema, "__name__", str(schema))
        self.calls.append((str(prompt or ""), schema_name))
        if schema_name == "ReminderDecision":
            return {"should_create": False, "text": "", "datetime_iso": None, "recurrence": None, "confidence": 0.0}
        if schema_name == "MemoryCandidate":
            return {
                "should_store": True,
                "memory_type": "therapy_goal",
                "text": "User arbeitet an Schlaf und Tagesstruktur.",
                "sensitivity": "low",
                "confidence": 0.9,
            }
        if schema_name == "BibliothekarQueryDecision":
            return {
                "should_search": True,
                "query": "Schlaf Tagesstruktur Depression",
                "filters": {},
                "requires_sources": True,
                "confidence": 0.92,
                "reason_short": "benchmark decision",
                "source": "model",
            }
        raise KeyError(f"unexpected benchmark decision schema: {schema_name}")

    def schema_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for _prompt, schema_name in self.calls:
            counts[schema_name] = counts.get(schema_name, 0) + 1
        return counts


class _BenchmarkPromptText:
    def __init__(self, prompt_text: str) -> None:
        self.prompt_text = prompt_text


class _BenchmarkBibliothekarStore:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def search(self, query: str, **_kwargs: Any) -> _BenchmarkPromptText:
        self.calls.append(str(query or ""))
        return _BenchmarkPromptText(
            "Quelle: Schlafhandbuch, Datei: sleep.md, Locator: Abschnitt 1, chunk_id: bench_sleep_1\n"
            "Kurzer Auszug: Schlaf und Tagesstruktur stabilisieren Alltagsrhythmus."
        )


class _BenchmarkEngineQdrantIndex:
    search_calls: list[tuple[str, str, str, int]] = []
    index_calls: list[tuple[str, str, str]] = []

    def __init__(self, *, url: str | None = None, **_kwargs: Any) -> None:
        self.url = url

    @classmethod
    def reset(cls) -> None:
        cls.search_calls = []
        cls.index_calls = []

    def search(self, *, instance_name: str, account_id: str, query: str, limit: int = 5) -> tuple[QdrantMemoryResult, ...]:
        self.search_calls.append((instance_name, account_id, query, int(limit)))
        return (
            QdrantMemoryResult(
                memory_id="mem_semantic",
                account_id=account_id,
                instance_name=instance_name,
                score=2.5,
                payload={"memory_id": "mem_semantic", "schema_version": 3},
            ),
        )

    def index_memory(self, *, instance_name: str, account_id: str, entry: dict[str, Any]) -> str:
        self.index_calls.append((instance_name, account_id, str(entry.get("id") or "")))
        return "bench-qdrant-point"


def _latest_response_for_identity(response_ids: list[str], identities: list[str], identity: str) -> str | None:
    for index in range(min(len(response_ids), len(identities)) - 1, -1, -1):
        if identities[index] == identity:
            return response_ids[index]
    return None


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = round((max(0, min(100, percentile)) / 100) * (len(ordered) - 1))
    return ordered[int(rank)]


def _path_ok(paths: list[dict[str, Any]], name: str) -> bool:
    for path in paths:
        if path.get("path") == name:
            return bool(path.get("ok"))
    return False


def _skipped_live_llm_result(*, reason: str, details: dict[str, Any] | None = None) -> BenchmarkResult:
    merged_details = {
        "network_calls": 0,
        "provider_calls": 0,
        "remote_calls": 0,
        "llm_calls": 0,
        "openai_calls": 0,
        "confirmation_env": EMERGENCY_LIVE_LLM_ENV,
        "required_confirmation": EMERGENCY_LIVE_LLM_CONFIRMATION,
    }
    merged_details.update(details or {})
    return result(
        name="live_llm_message_latency_paths",
        category="llm_router",
        iterations=0,
        total_ms=0.0,
        ok=False,
        skipped=True,
        errors=0,
        payload_bytes=len(json.dumps(merged_details, ensure_ascii=False).encode("utf-8")),
        note="EMERGENCY ONLY real provider/API LLM latency benchmark",
        reason=reason,
        mode="live_emergency_llm",
        details=merged_details,
    )


def _live_llm_candidate_names(source: Mapping[str, str]) -> list[str]:
    return [candidate["name"] for candidate in _live_llm_candidates(source)]


def _live_llm_candidates(source: Mapping[str, str]) -> list[dict[str, Any]]:
    profiles = load_llm_profiles()
    default_profile, routing = load_llm_routing()
    candidates: list[dict[str, Any]] = []
    for purpose in sorted(routing):
        route = select_llm_route(
            purpose,
            profiles=profiles,
            default_profile=default_profile,
            routing=routing,
            allow_remote_fallback=False,
        )
        candidates.append(
            _live_llm_candidate(
                name=f"purpose:{purpose}",
                kind="purpose",
                purpose=purpose,
                profile="",
                provider=route.provider,
                model=route.model,
                api_key_env=route.api_key_env,
                source=source,
            )
        )
    for profile_name, profile in sorted(profiles.items()):
        candidates.append(
            _live_llm_candidate(
                name=f"profile:{profile_name}",
                kind="profile",
                purpose="",
                profile=profile_name,
                provider=profile.provider,
                model=profile.model,
                api_key_env=profile.api_key_env,
                source=source,
            )
        )
    return candidates


def _live_llm_candidate(
    *,
    name: str,
    kind: str,
    purpose: str,
    profile: str,
    provider: str,
    model: str,
    api_key_env: str,
    source: Mapping[str, str],
) -> dict[str, Any]:
    runnable, reason = _live_llm_candidate_runnable(provider=provider, model=model, api_key_env=api_key_env, source=source)
    return {
        "name": name,
        "kind": kind,
        "purpose": purpose,
        "profile": profile,
        "provider": provider,
        "model": model,
        "api_key_env": api_key_env,
        "runnable": runnable,
        "skip_reason": reason,
    }


def _live_llm_candidate_runnable(
    *,
    provider: str,
    model: str,
    api_key_env: str,
    source: Mapping[str, str],
) -> tuple[bool, str]:
    normalized_provider = normalize_llm_provider(provider)
    normalized_model = str(model or "").strip().casefold()
    if normalized_provider == "hf_pool":
        return True, ""
    if normalized_model.startswith(("ollama/", "ollama_chat/")):
        return True, ""
    if route_uses_gemini_api(provider=provider, model=model):
        if (api_key_env and source.get(api_key_env, "").strip()) or resolve_gemini_api_key_ring(source):
            return True, ""
        return False, "missing Gemini API key or key ring"
    if api_key_env and source.get(api_key_env, "").strip():
        return True, ""
    if route_uses_google_gemini(provider=provider, model=model):
        return False, f"missing {api_key_env or 'GOOGLE_APPLICATION_CREDENTIALS'}"
    if normalized_provider == "openai" or normalized_model.startswith("openai/"):
        return False, f"missing {api_key_env or 'OPENAI_API_KEY'}"
    if normalized_model.startswith("groq/"):
        return False, f"missing {api_key_env or 'GROQ_API_KEY'}"
    if normalized_model.startswith("huggingface/"):
        return False, f"missing {api_key_env or 'HUGGINGFACE_API_KEY'}"
    if normalized_model.startswith("vertex_ai/"):
        return False, f"missing {api_key_env or 'GOOGLE_APPLICATION_CREDENTIALS'}"
    return bool(api_key_env and source.get(api_key_env, "").strip()), f"missing {api_key_env or 'provider API key'}"


def _measure_live_llm_candidate(candidate: dict[str, Any], *, source: Mapping[str, str], iterations: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="teebotus-live-llm-bench-") as tmp:
        provider = StaticSecretProvider(b"l" * 32)
        data_dir = Path(tmp) / "Bench" / "data"
        account_store = AccountStore(data_dir / "accounts", "Bench", provider)
        state = RuntimeStateStore(data_dir, instance_name="Bench", secret_provider=provider)
        instructions = BotInstructions(
            openai_enabled=True,
            llm_provider=str(candidate.get("provider") or ""),
            llm_model=str(candidate.get("model") or ""),
            user_memory_enabled=False,
            llm_timeout_seconds=30,
            llm_max_output_tokens=64,
            llm_temperature=0.0,
            openai_timeout_seconds=30,
            openai_max_output_tokens=64,
        )
        client = build_runtime_text_llm_client(
            instructions=instructions,
            openai_client=None,
            profile=str(candidate.get("profile") or ""),
            purpose=str(candidate.get("purpose") or ""),
            allow_remote_fallback=False,
            timeout=30,
            max_tokens=16,
            temperature=0.0,
            env=source,
        )
        if client is None:
            return {
                **candidate,
                "ok": False,
                "calls": 0,
                "total_ms": 0.0,
                "mean_ms": 0.0,
                "error": "client unavailable",
            }
        engine = TeeBotusEngine(account_store=account_store, state=state, instructions=instructions, llm_client=client)
        identity = telegram_identity_key(93001)
        latencies: list[float] = []
        errors: list[str] = []
        calls = 0
        for index in range(iterations):
            calls += 1
            try:
                latency_ms, actions = _timed_value_ms(lambda index=index: engine.process(_live_llm_event(identity, index)))
                latencies.append(latency_ms)
                if fallback_reply := _live_llm_fallback_reply(actions, instructions):
                    errors.append(f"fallback reply: {fallback_reply}")
                    break
            except Exception as exc:  # noqa: BLE001 - benchmark report must contain provider boundary failures.
                errors.append(_redact_live_llm_error(exc, source))
                break
        ok = bool(latencies) and not errors
        return {
            **candidate,
            "ok": ok,
            "calls": calls,
            "total_ms": sum(latencies),
            "mean_ms": statistics.fmean(latencies) if latencies else 0.0,
            "median_ms": statistics.median(latencies) if latencies else 0.0,
            "p95_ms": _percentile(latencies, 95),
            "errors": errors,
            "fallbacks_disabled_for_cost_control": True,
        }


def _live_llm_event(identity_key: str, index: int) -> IncomingEvent:
    return IncomingEvent(
        event_id=f"telegram:live-llm-bench:{index}",
        instance="Bench",
        channel="telegram",
        adapter_slot=1,
        account_id="",
        identity_key=identity_key,
        chat_id="bench-live-llm-chat",
        chat_type="private",
        sender_id=identity_key,
        sender_name="Benchmark User",
        text="Antworte exakt mit: OK",
        message_ref=f"live-llm-{index}",
    )


def _live_llm_fallback_reply(actions: object, instructions: BotInstructions) -> str:
    fallback_texts = {
        str(instructions.llm_error or "").strip(),
        str(instructions.llm_missing_key or "").strip(),
        str(instructions.openai_error or "").strip(),
        str(instructions.openai_missing_key or "").strip(),
    }
    for action in actions if isinstance(actions, (list, tuple)) else ():
        text = str(getattr(action, "text", "") or "").strip()
        if not text:
            continue
        lowered = text.casefold()
        if text in fallback_texts or "gerade nicht erreichen" in lowered or "api gerade nicht" in lowered:
            return text[:240]
    return ""


def _redact_live_llm_error(exc: BaseException, source: Mapping[str, str]) -> str:
    text = f"{type(exc).__name__}: {exc}".replace("\n", " ").replace("\r", " ")
    for key, value in source.items():
        key_text = str(key or "").casefold()
        if not any(marker in key_text for marker in ("key", "token", "secret", "password", "credential")):
            continue
        value_text = str(value or "").strip()
        if len(value_text) >= 6:
            text = text.replace(value_text, "<redacted>")
    return text[:1000]


def _positive_int(value: object, *, default: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        parsed = int(default)
    return parsed if parsed > 0 else int(default)


def _csv_set(value: object) -> set[str]:
    return {part.strip() for part in str(value or "").split(",") if part.strip()}


__all__ = [
    "benchmark_gemini_free_tier_guard",
    "benchmark_live_llm_message_latency_paths",
    "benchmark_llm_decision_qdrant_path_matrix",
    "benchmark_llm_message_latency_paths",
    "benchmark_llm_router",
]
