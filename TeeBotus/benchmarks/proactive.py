from __future__ import annotations

import asyncio
import json
import statistics
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from TeeBotus.benchmarks.core import BenchmarkResult, result
from TeeBotus.decisions import ProactiveToolCallDecision
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, signal_identity_key
from TeeBotus.runtime.proactive_agent import (
    apply_proactive_agent_tool_calls,
    check_proactive_agent_account,
    dispatch_due_proactive_outbox_items,
    due_proactive_outbox_items,
    enable_proactive_agent,
    proactive_policy_decision,
)


def benchmark_proactive_tool_plan_due_dispatch_gates(*, iterations: int) -> BenchmarkResult:
    with tempfile.TemporaryDirectory(prefix="teebotus-bench-proactive-") as tmp:
        store = AccountStore(Path(tmp) / "accounts", "Bench", StaticSecretProvider(b"p" * 32))
        identity = signal_identity_key(source_uuid="bench")
        account_id = store.resolve_or_create_account(identity)
        store.update_identity_route(identity, channel="signal", chat_id="+491", chat_type="private", adapter_slot=1)
        enable_proactive_agent(store, account_id, categories=("reminder", "analysis"))
        store.append_structured_memory_entry(
            account_id,
            {
                "id": "mem_bench_goal",
                "kind": "therapy_goal",
                "user_text": "Der Nutzer moechte morgens kurz an den Spaziergang erinnert werden.",
                "created_at": "2026-06-16T07:30:00+00:00",
                "updated_at": "2026-06-16T07:30:00+00:00",
            },
        )
        now = datetime(2026, 6, 16, 10, 30, tzinfo=timezone.utc)
        safe_tool = {
            "name": "proactive_queue_message",
            "arguments": {
                "category": "reminder",
                "intent": "bench_follow_up",
                "message_text": "Benchmark: Magst du kurz berichten, ob der Spaziergang geklappt hat?",
                "reason_memory_ids": ["mem_bench_goal"],
                "risk_gate": "none",
                "due_at": "2026-06-16T10:00:00+00:00",
            },
        }
        review_tool = {
            "name": "proactive_queue_message",
            "arguments": {
                "category": "analysis",
                "intent": "bench_review_only",
                "message_text": "Benchmark: Analysevorschlag nur nach Review.",
                "reason_memory_ids": ["mem_bench_goal"],
                "risk_gate": "needs_review",
                "due_at": "2026-06-16T10:00:00+00:00",
            },
        }
        validation_timings = [
            _timed_ms(lambda: (ProactiveToolCallDecision.model_validate(safe_tool), ProactiveToolCallDecision.model_validate(review_tool)))
            for _ in range(iterations)
        ]
        planning_results = []
        planning_ms = _timed_ms(
            lambda: planning_results.append(
                apply_proactive_agent_tool_calls(store, account_id, (safe_tool, review_tool), now=now)
            )
        )
        timings = [_timed_ms(lambda: due_proactive_outbox_items(store, account_id, now=now)) for _ in range(iterations)]
        policy_results = []
        policy_ms = _timed_ms(lambda: policy_results.append(proactive_policy_decision(store, account_id, category="reminder", now=now)))
        sent_actions: list[str] = []

        def fake_sender(_route: dict[str, Any], action: Any, _item: dict[str, Any]) -> str:
            sent_actions.append(str(getattr(action, "text", "")))
            return "bench-sent-ref"

        dispatch_results = []
        dispatch_ms = _timed_ms(
            lambda: dispatch_results.extend(
                asyncio.run(
                    dispatch_due_proactive_outbox_items(
                        store,
                        account_id,
                        senders={"signal": fake_sender},
                        now=now,
                        instance_name="Bench",
                    )
                )
            )
        )
        health = check_proactive_agent_account(store, account_id)
        planning_result = planning_results[0] if planning_results else None
        queued_items = store.read_proactive_outbox(account_id)
        sent_count = sum(1 for item in queued_items if str(item.get("status") or "") == "sent")
        review_pending_count = sum(1 for item in queued_items if str(item.get("status") or "") == "review_pending")
        ok = (
            planning_result is not None
            and not planning_result.errors
            and len(planning_result.queued_item_ids) == 2
            and len(dispatch_results) == 1
            and dispatch_results[0].status == "sent"
            and sent_count == 1
            and review_pending_count == 1
            and health.review_pending_count == 1
            and len(sent_actions) == 1
        )
        return result(
            name="proactive_tool_plan_due_dispatch_gates",
            category="proactive_agent",
            iterations=iterations * 2 + 3,
            total_ms=sum(validation_timings) + planning_ms + sum(timings) + policy_ms + dispatch_ms,
            ok=ok,
            errors=0 if ok else 1,
            payload_bytes=sum(len(json.dumps(item, ensure_ascii=False)) for item in queued_items),
            details={
                "tool_schema_validated": True,
                "tool_plan_errors": list(planning_result.errors) if planning_result else ["missing_planning_result"],
                "tool_queued_item_ids": list(planning_result.queued_item_ids) if planning_result else [],
                "queued": len(queued_items),
                "sent": sent_count,
                "review_pending": review_pending_count,
                "due_after_review_gate": len(due_proactive_outbox_items(store, account_id, now=now)),
                "dispatch_simulated": len(dispatch_results),
                "dispatch_statuses": [dispatch_result.status for dispatch_result in dispatch_results],
                "policy_allowed": policy_results[0].allowed if policy_results else False,
                "health_ok_with_review_pending": health.ok,
                "health_review_pending": health.review_pending_count,
                "median_tool_validation_ms": statistics.median(validation_timings),
                "planning_ms": planning_ms,
                "median_due_ms": statistics.median(timings),
                "policy_ms": policy_ms,
                "dispatch_ms": dispatch_ms,
                "network_calls": 0,
            },
        )


def _timed_ms(func: Callable[[], Any]) -> float:
    start = time.perf_counter()
    func()
    return (time.perf_counter() - start) * 1000


__all__ = ["benchmark_proactive_tool_plan_due_dispatch_gates"]
