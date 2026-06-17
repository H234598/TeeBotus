from __future__ import annotations

import json
import statistics
import time
from typing import Any, Callable

from TeeBotus.benchmarks.core import BenchmarkResult, result
from TeeBotus.decisions import (
    BibliothekarQueryDecision,
    FakeDecisionModel,
    IntentDecision,
    ProactiveToolCallDecision,
    ToolSafetyDecision,
    build_router_pydantic_ai_model_runner,
    decide_intent,
    parse_agent_task_decision,
    parse_bibliothekar_query_decision,
    parse_memory_candidate,
    parse_reminder_decision,
    parse_source_quality_decision,
    parse_youtube_options_decision,
)


def benchmark_decision_fake_model(*, iterations: int) -> BenchmarkResult:
    fake_model = FakeDecisionModel(
        {
            "IntentDecision": {
                "intent": "bibliothekar_query",
                "confidence": 0.84,
                "reason_short": "benchmark fake model",
                "source": "model",
            }
        }
    )
    outputs: list[IntentDecision] = []
    timings = [_timed_ms(lambda: outputs.append(decide_intent("Bitte einordnen", model_runner=fake_model.runner()))) for _ in range(iterations)]
    ok = bool(outputs) and all(output.intent == "bibliothekar_query" for output in outputs) and len(fake_model.calls) == iterations
    payload = [output.model_dump() for output in outputs]
    return result(
        name="decision_fake_model",
        category="pydantic_ai",
        iterations=iterations,
        total_ms=sum(timings),
        ok=ok,
        errors=0 if ok else 1,
        payload_bytes=len(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
        index_bytes=len(json.dumps({"fake_model_calls": len(fake_model.calls)}, ensure_ascii=False).encode("utf-8")),
        note="provider_free_decision_runner",
        details={
            "fake_model_calls": len(fake_model.calls),
            "latest_intent": outputs[-1].intent if outputs else "",
            "network_calls": 0,
            "provider_calls": 0,
        },
    )


def benchmark_pydantic_structured_decisions(*, iterations: int) -> BenchmarkResult:
    bibliothekar_payload = {
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
    reminder_payload = {
        "should_create": True,
        "text": "Zahnarzttermin",
        "datetime_iso": "2026-06-16T09:00:00+00:00",
        "recurrence": None,
        "confidence": 0.89,
    }
    proactive_tool_payload = {
        "name": "proactive_queue_message",
        "call_id": "bench_call_1",
        "arguments": {
            "category": "reminder",
            "intent": "follow_up",
            "message_text": "Magst du kurz berichten?",
            "reason_memory_ids": ["mem_goal"],
        },
    }
    tool_safety_payload = {
        "allowed": False,
        "requires_confirmation": False,
        "reason": "benchmark blocks risky tool",
        "risk_level": "blocked",
    }
    source_quality_payload = {
        "status": "usable",
        "reason": "benchmark source metadata ok",
        "requires_human_review": False,
        "confidence": 0.73,
    }
    youtube_options_payload = {
        "live_output": False,
        "send_to_llm": True,
        "confidence": 0.9,
        "reason_short": "benchmark local transcript routing",
    }
    agent_task_payload = {
        "should_run": True,
        "task": "source_harvest",
        "objective": "Quelle pruefen und in die Bibliothek routen",
        "confidence": 0.86,
        "reason_short": "benchmark agent task",
        "risk_level": "low",
        "source": "model",
    }
    parse_timings = [
        _timed_ms(
            lambda: (
                parse_bibliothekar_query_decision(bibliothekar_payload),
                parse_memory_candidate(memory_payload),
                parse_reminder_decision(reminder_payload),
                parse_source_quality_decision(source_quality_payload),
                parse_youtube_options_decision(youtube_options_payload),
                parse_agent_task_decision(agent_task_payload),
                ProactiveToolCallDecision.model_validate(proactive_tool_payload),
                ToolSafetyDecision.model_validate(tool_safety_payload),
            )
        )
        for _ in range(iterations)
    ]
    fake_calls: list[dict[str, Any]] = []

    class FakeRunResult:
        def __init__(self, output: Any) -> None:
            self.output = output

    class FakeAgent:
        def __init__(self, model: str, **kwargs: Any) -> None:
            fake_calls.append({"model": model, **kwargs})
            self.schema = kwargs.get("output_type") or kwargs.get("result_type")

        def run_sync(self, prompt: str) -> FakeRunResult:
            if self.schema is None:
                raise RuntimeError("missing schema")
            return FakeRunResult(self.schema.model_validate({**bibliothekar_payload, "query": str(prompt or "").strip()}))

    runner = build_router_pydantic_ai_model_runner(
        "structured_decision",
        system_prompt="Return only the requested structured output.",
        agent_factory=FakeAgent,
    )
    runner_outputs: list[Any] = []
    runner_timings = [
        _timed_ms(lambda: runner_outputs.append(runner("Therapie Schlaf", BibliothekarQueryDecision)))
        for _ in range(iterations)
    ]
    latest_output = runner_outputs[-1] if runner_outputs else None
    ok = (
        parse_bibliothekar_query_decision(bibliothekar_payload).should_search
        and parse_memory_candidate(memory_payload).memory_type == "therapy_goal"
        and parse_reminder_decision(reminder_payload).should_create
        and parse_source_quality_decision(source_quality_payload).status == "usable"
        and parse_youtube_options_decision(youtube_options_payload).send_to_llm is True
        and parse_agent_task_decision(agent_task_payload).task == "source_harvest"
        and ProactiveToolCallDecision.model_validate(proactive_tool_payload).name == "proactive_queue_message"
        and ToolSafetyDecision.model_validate(tool_safety_payload).risk_level == "blocked"
        and getattr(latest_output, "query", "") == "Therapie Schlaf"
        and len(fake_calls) == iterations
    )
    payload = {
        "bibliothekar": bibliothekar_payload,
        "memory": memory_payload,
        "reminder": reminder_payload,
        "source_quality": source_quality_payload,
        "youtube_options": youtube_options_payload,
        "agent_task": agent_task_payload,
        "proactive_tool": proactive_tool_payload,
        "tool_safety": tool_safety_payload,
    }
    return result(
        name="pydantic_structured_decisions",
        category="pydantic_ai",
        iterations=iterations * 9,
        total_ms=sum(parse_timings) + sum(runner_timings),
        ok=ok,
        errors=0 if ok else 1,
        payload_bytes=len(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
        index_bytes=len(json.dumps({"schemas": 8, "fake_agent_calls": len(fake_calls)}, ensure_ascii=False).encode("utf-8")),
        note="schema_validation_and_fake_agent",
        details={
            "schemas": [
                "AgentTaskDecision",
                "BibliothekarQueryDecision",
                "MemoryCandidate",
                "ReminderDecision",
                "SourceQualityDecision",
                "ToolSafetyDecision",
                "ProactiveToolCallDecision",
                "YouTubeOptionsDecision",
            ],
            "fake_agent_calls": len(fake_calls),
            "fake_agent_model": getattr(runner, "model_name", ""),
            "router_purpose": getattr(runner, "llm_purpose", ""),
            "router_provider": getattr(runner, "llm_provider", ""),
            "network_calls": 0,
            "median_parse_batch_ms": statistics.median(parse_timings),
            "median_fake_agent_ms": statistics.median(runner_timings),
            "latest_runner_query": getattr(latest_output, "query", ""),
        },
    )


def _timed_ms(func: Callable[[], Any]) -> float:
    start = time.perf_counter()
    func()
    return (time.perf_counter() - start) * 1000


__all__ = [
    "benchmark_decision_fake_model",
    "benchmark_pydantic_structured_decisions",
]
