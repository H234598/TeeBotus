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
from TeeBotus.llm.base import LLMResponse
from TeeBotus.llm.capabilities import (
    GEMINI_INTERACTIONS_CAPABILITIES,
    HF_POOL_TEXT_CAPABILITIES,
    LITELLM_TEXT_CAPABILITIES,
    OPENAI_CAPABILITIES,
    LLMCapabilities,
)
from TeeBotus.llm.free_tier import GeminiFreeTierGuard, reset_gemini_free_tier_budget_state, resolve_gemini_free_tier_limits
from TeeBotus.llm.gemini_limits_refresh import cached_gemini_free_tier_limit_values, refresh_gemini_free_tier_limits_if_due
from TeeBotus.llm.keyring import RotatingAPIKeyRing, resolve_gemini_api_key_ring
from TeeBotus.llm.profiles import load_llm_profiles, load_llm_routing, select_llm_route
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, telegram_identity_key
from TeeBotus.runtime.engine import TeeBotusEngine
from TeeBotus.runtime.events import IncomingEvent
from TeeBotus.runtime.llm_factory import build_runtime_text_llm_client
from TeeBotus.runtime.state import RuntimeStateStore


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


def benchmark_llm_message_latency_paths(*, iterations: int) -> BenchmarkResult:
    message_count = max(4, int(iterations or 1))
    path_specs = (
        _LLMMessagePathSpec(
            name="openai_responses_stateful",
            provider="openai",
            model="gpt-4.1-mini",
            capabilities=OPENAI_CAPABILITIES,
            stateful=True,
        ),
        _LLMMessagePathSpec(
            name="gemini_interactions_stateful",
            provider="gemini_interactions",
            model="gemini/gemini-3.5-flash",
            capabilities=GEMINI_INTERACTIONS_CAPABILITIES,
            stateful=True,
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
            "gemini_account_state_ok": _path_ok(paths, "gemini_interactions_stateful"),
            "stateless_paths_ignore_state_ok": all(
                _path_ok(paths, name) for name in ("litellm_local_stateless", "hf_pool_stateless")
            ),
            "synthetic_clients_only": True,
            "network_calls": 0,
            "provider_calls": 0,
            "remote_calls": 0,
            "llm_calls": 0,
            "openai_calls": 0,
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


class _LLMMessagePathSpec:
    def __init__(
        self,
        *,
        name: str,
        provider: str,
        model: str,
        capabilities: LLMCapabilities,
        stateful: bool,
    ) -> None:
        self.name = name
        self.provider = provider
        self.model = model
        self.capabilities = capabilities
        self.stateful = stateful


class _SyntheticLLMClient:
    def __init__(self, spec: _LLMMessagePathSpec) -> None:
        self.spec = spec
        self.provider = spec.provider
        self.provider_name = spec.provider
        self.model = spec.model
        self.capabilities = spec.capabilities
        self.previous_ids: list[str | None] = []
        self.response_ids: list[str] = []

    def create_reply(
        self,
        _user_text: str,
        _instructions: BotInstructions,
        previous_response_id: str | None = None,
    ) -> LLMResponse:
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


__all__ = [
    "benchmark_gemini_free_tier_guard",
    "benchmark_llm_message_latency_paths",
    "benchmark_llm_router",
]
