from __future__ import annotations

import json
import statistics
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from TeeBotus.benchmarks.core import BenchmarkResult, result
from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.base import LLMResponse
from TeeBotus.llm.hf_pool.executor import OpenAICompatibleHFPoolExecutor
from TeeBotus.llm.hf_pool.health import check_hf_pool, format_hf_pool_status_lines
from TeeBotus.llm.hf_pool.provider import HFPoolProvider
from TeeBotus.llm.hf_pool.state import HFPoolRuntimeState
from TeeBotus.llm.profiles import load_llm_profiles


def benchmark_hf_pool_quick(*, iterations: int) -> BenchmarkResult:
    timings: list[float] = []
    lines: list[str] = []
    for _ in range(iterations):
        timings.append(_timed_ms(lambda: lines.extend(format_hf_pool_status_lines(check_hf_pool()))))
    ok = bool(lines) and any(line.startswith("hf_pool=") for line in lines)
    return result(
        name="hf_pool_quick_health",
        category="hf_pool",
        iterations=iterations,
        total_ms=sum(timings),
        ok=ok,
        errors=0 if ok else 1,
        payload_bytes=len("\n".join(lines).encode("utf-8")),
        index_bytes=len(json.dumps({"status_lines": len(lines)}, ensure_ascii=False).encode("utf-8")),
        note="local_hf_pool_status_no_live_calls",
        details={
            "status_lines": lines[-3:],
            "network_calls": 0,
            "provider_calls": 0,
            "remote_calls": 0,
        },
    )


def benchmark_hf_pool_eval_matrix(*, iterations: int) -> BenchmarkResult:
    purposes = (
        "structured_decision",
        "normal_chat",
        "psychology_explainer",
        "bibliothekar_answer",
        "summarizer",
    )
    responses = {
        "structured_decision": '{"intent":"reminder","confidence":0.92,"source":"model"}',
        "normal_chat": "Ich helfe dir kurz und konkret mit einem naechsten Schritt.",
        "psychology_explainer": "Validierend: Das klingt belastend. Keine Diagnose; ein kleiner Schritt und sanfte Aktivierung koennen helfen.",
        "bibliothekar_answer": "Laut [Quelle: Therapie Basis, therapie_basis.md, Zeilen 1-4, chunk_id=lib_abc] werden Aktivierung und Schlafhygiene genannt.",
        "summarizer": "Zusammenfassung: Aktivierung, Schlafhygiene und kleine Aufgaben werden genannt.",
    }

    class EvalExecutor:
        def __init__(self) -> None:
            self.calls: list[dict[str, str]] = []

        def create_reply(self, scheduled: Any, user_text: str, instructions: BotInstructions) -> LLMResponse:  # noqa: ARG002
            purpose = next(iter(getattr(scheduled.target, "purposes", ()) or ("normal_chat",)))
            self.calls.append({"purpose": purpose, "target": scheduled.target.name})
            return LLMResponse(
                text=responses[purpose],
                provider="hf_pool",
                model=scheduled.target.request_model,
                usage={"mock_eval": True, "purpose": purpose},
            )

    class FailingExecutor:
        def create_reply(self, scheduled: Any, user_text: str, instructions: BotInstructions) -> LLMResponse:  # noqa: ARG002
            raise RuntimeError("benchmark provider failure")

    class FallbackClient:
        def __init__(self, text: str) -> None:
            self.text = text
            self.calls = 0

        def create_reply(self, user_text: str, instructions: BotInstructions, previous_response_id: str | None = None) -> LLMResponse:  # noqa: ARG002
            self.calls += 1
            return LLMResponse(text=self.text, provider="fallback", model="local_fallback", usage={"fallback": True})

    with tempfile.TemporaryDirectory(prefix="teebotus-bench-hf-eval-") as tmp:
        config_path = _write_hf_pool_eval_config(Path(tmp), purposes=purposes)
        executor = EvalExecutor()
        timings: list[float] = []
        outputs: dict[str, str] = {}
        for purpose in purposes:
            provider = HFPoolProvider(
                purpose=purpose,
                config_path=config_path,
                env={},
                executor=executor,
            )
            timings.extend(
                _timed_ms(lambda purpose=purpose, provider=provider: outputs.setdefault(purpose, provider.create_reply(_hf_pool_eval_prompt(purpose), BotInstructions()).text))
                for _ in range(iterations)
            )

        failure_fallback = FallbackClient("fallback after provider failure")
        failure_provider = HFPoolProvider(
            purpose="normal_chat",
            config_path=config_path,
            env={},
            executor=FailingExecutor(),
            fallback_client=failure_fallback,
        )
        failure_ms = _timed_ms(lambda: failure_provider.create_reply("Trigger provider failure", BotInstructions()))

        cooldown_network_calls = 0

        def forbidden_opener(*_args: Any, **_kwargs: Any) -> Any:
            nonlocal cooldown_network_calls
            cooldown_network_calls += 1
            raise RuntimeError("cooldown benchmark must not open a network connection")

        cooldown_fallback = FallbackClient("fallback during cooldown")
        cooldown_state_key = "default/bench_normal_chat"
        cooldown_state = HFPoolRuntimeState(
            cooldowns={
                cooldown_state_key: (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
            }
        )
        cooldown_provider = HFPoolProvider(
            purpose="normal_chat",
            config_path=config_path,
            env={},
            executor=OpenAICompatibleHFPoolExecutor(opener=forbidden_opener, state=cooldown_state),
            fallback_client=cooldown_fallback,
        )
        cooldown_ms = _timed_ms(lambda: cooldown_provider.create_reply("Trigger cooldown", BotInstructions()))

        structured = _hf_pool_eval_structured_json(outputs.get("structured_decision", ""))
        psychology = _hf_pool_eval_psychology_quality(outputs.get("psychology_explainer", ""))
        citation = _hf_pool_eval_citation_faithfulness(outputs.get("bibliothekar_answer", ""))
        summary = _hf_pool_eval_summary_faithfulness(outputs.get("summarizer", ""))
        normal_latency_ms = statistics.median(timings) if timings else 0.0
        fallback_ok = failure_fallback.calls == 1
        cooldown_ok = cooldown_fallback.calls == 1 and cooldown_network_calls == 0
        routed_purposes = [call["purpose"] for call in executor.calls]
        ok = (
            structured["valid"]
            and psychology["ok"]
            and citation["ok"]
            and summary["ok"]
            and fallback_ok
            and cooldown_ok
            and set(routed_purposes) == set(purposes)
        )
        details = {
            "purposes": list(purposes),
            "routed_purposes": routed_purposes,
            "structured_decision_json_valid": structured["valid"],
            "structured_decision_confidence": structured["confidence"],
            "normal_chat_median_latency_ms": normal_latency_ms,
            "psychology_quality_score": psychology["score"],
            "psychology_quality_ok": psychology["ok"],
            "bibliothekar_citation_faithful": citation["ok"],
            "bibliothekar_citation_fields": citation["fields"],
            "summarizer_faithful": summary["ok"],
            "summarizer_terms": summary["terms"],
            "provider_failure_fallback": fallback_ok,
            "cooldown_fallback": cooldown_ok,
            "cooldown_state_key": cooldown_state_key,
            "cooldown_network_calls": cooldown_network_calls,
            "mock_executor_calls": len(executor.calls),
            "network_calls": 0,
            "provider_calls": 0,
            "remote_calls": 0,
            "llm_calls": 0,
            "openai_calls": 0,
        }
        return result(
            name="hf_pool_eval_matrix",
            category="hf_pool",
            iterations=max(1, iterations) * len(purposes) + 2,
            total_ms=sum(timings) + failure_ms + cooldown_ms,
            ok=ok,
            errors=0 if ok else 1,
            payload_bytes=len(json.dumps(outputs, ensure_ascii=False).encode("utf-8")),
            index_bytes=config_path.stat().st_size,
            note="provider_free_hf_pool_eval_matrix",
            details=details,
        )


def benchmark_hf_pool_live(*, profile: str = "") -> BenchmarkResult:
    pool_name, route_model = _hf_pool_profile_context(profile)
    lines: list[str] = []
    health_holder: list[Any] = []

    def run_live_check() -> None:
        health = check_hf_pool(pool_name=pool_name, live=True)
        health_holder.append(health)
        lines.extend(format_hf_pool_status_lines(health))

    total_ms = _timed_ms(run_live_check)
    health = health_holder[-1] if health_holder else None
    healthy_targets = [
        target.name
        for target in getattr(health, "targets", ())
        if getattr(target, "status", "") == "healthy"
    ]
    target_statuses = [str(getattr(target, "status", "") or "") for target in getattr(health, "targets", ())]
    live_attempted = any(status in {"healthy", "cooldown", "error", "unavailable"} for status in target_statuses)
    reason = "" if healthy_targets else _hf_pool_live_skip_reason(health)
    skipped = not bool(healthy_targets)
    return result(
        name="hf_pool_live_health",
        category="hf_pool",
        iterations=1 if not skipped else 0,
        total_ms=total_ms,
        ok=not skipped,
        skipped=skipped,
        errors=0,
        payload_bytes=len("\n".join(lines).encode("utf-8")),
        index_bytes=len(json.dumps({"status_lines": len(lines), "healthy_targets": len(healthy_targets)}, ensure_ascii=False).encode("utf-8")),
        note="explicit_live_hf_pool_check",
        reason=reason,
        mode="live_hf",
        details={
            "profile": profile,
            "route_model": route_model,
            "pool": pool_name,
            "status_lines": lines[-5:],
            "healthy_targets": healthy_targets,
            "target_statuses": target_statuses,
            "network_calls": 1 if live_attempted else 0,
            "provider_calls": 1 if live_attempted else 0,
            "remote_calls": 1 if live_attempted else 0,
        },
    )


def _write_hf_pool_eval_config(root: Path, *, purposes: tuple[str, ...]) -> Path:
    targets = [
        {
            "name": f"bench_{purpose}",
            "kind": "hf_router_chat",
            "base_url": "https://router.huggingface.co/v1",
            "api_key_env": "",
            "model": f"Bench/{purpose}",
            "weight": 1,
            "purposes": [purpose],
            "enabled": True,
            "required": {"supports_structured_output": purpose == "structured_decision"},
        }
        for purpose in purposes
    ]
    path = root / "hf_pool_eval.json"
    path.write_text(
        json.dumps(
            {
                "pools": {
                    "default": {
                        "enabled": True,
                        "strategy": "purpose_weighted",
                        "max_retries": 1,
                        "timeout_seconds": 5,
                        "cooldown_seconds_on_429": 900,
                        "targets": targets,
                    }
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _hf_pool_eval_prompt(purpose: str) -> str:
    prompts = {
        "structured_decision": "Gib eine JSON-Intent-Entscheidung fuer eine Erinnerung zurueck.",
        "normal_chat": "Antworte kurz und hilfreich.",
        "psychology_explainer": "Erklaere sanft, ohne Diagnose, mit einem kleinen naechsten Schritt.",
        "bibliothekar_answer": "Nutze nur chunk_id=lib_abc aus therapie_basis.md.",
        "summarizer": "Fasse Aktivierung, Schlafhygiene und kleine Aufgaben zusammen.",
    }
    return prompts.get(purpose, purpose)


def _hf_pool_eval_structured_json(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {"valid": False, "confidence": 0.0}
    confidence = payload.get("confidence") if isinstance(payload, dict) else 0.0
    valid = (
        isinstance(payload, dict)
        and isinstance(payload.get("intent"), str)
        and isinstance(confidence, (int, float))
        and 0 <= float(confidence) <= 1
        and payload.get("source") == "model"
    )
    return {"valid": valid, "confidence": float(confidence) if isinstance(confidence, (int, float)) else 0.0}


def _hf_pool_eval_psychology_quality(text: str) -> dict[str, Any]:
    lower = text.casefold()
    checks = {
        "validierend": "validierend" in lower or "belastend" in lower,
        "keine_diagnose": "keine diagnose" in lower,
        "kleiner_schritt": "kleiner schritt" in lower,
        "sanft": "sanft" in lower or "aktivierung" in lower,
    }
    score = sum(1 for value in checks.values() if value)
    return {"ok": score >= 3, "score": score, "checks": checks}


def _hf_pool_eval_citation_faithfulness(text: str) -> dict[str, Any]:
    fields = {
        "chunk_id": "chunk_id=lib_abc" in text,
        "file": "therapie_basis.md" in text,
        "locator": "Zeilen 1-4" in text,
    }
    return {"ok": all(fields.values()), "fields": fields}


def _hf_pool_eval_summary_faithfulness(text: str) -> dict[str, Any]:
    lower = text.casefold()
    terms = {
        "aktivierung": "aktivierung" in lower,
        "schlafhygiene": "schlafhygiene" in lower,
        "kleine_aufgaben": "kleine aufgaben" in lower,
    }
    hallucinated = any(term in lower for term in ("medikament", "diagnose", "krankschreibung"))
    return {"ok": all(terms.values()) and not hallucinated, "terms": terms, "hallucinated": hallucinated}


def _hf_pool_profile_context(profile: str) -> tuple[str, str]:
    profile_name = str(profile or "").strip()
    if not profile_name:
        return "default", ""
    selected = load_llm_profiles().get(profile_name)
    model = selected.model if selected is not None else ""
    if model.startswith("pool:"):
        selector = model.removeprefix("pool:")
        pool_name = selector.split("#", 1)[0].strip() or "default"
        return pool_name, model
    return "default", model


def _hf_pool_live_skip_reason(health: Any) -> str:
    if health is None:
        return "hf_pool live check did not return health"
    status = str(getattr(health, "status", "") or "unknown")
    error = str(getattr(health, "error", "") or "")
    target_reasons = [
        f"{getattr(target, 'name', '')}:{getattr(target, 'status', '')}"
        for target in getattr(health, "targets", ())
        if getattr(target, "status", "")
    ]
    parts = [f"hf_pool status={status}"]
    if error:
        parts.append(error)
    if target_reasons:
        parts.append(",".join(target_reasons))
    return " ".join(parts)


def _timed_ms(func: Callable[[], Any]) -> float:
    start = time.perf_counter()
    func()
    return (time.perf_counter() - start) * 1000


__all__ = [
    "benchmark_hf_pool_eval_matrix",
    "benchmark_hf_pool_live",
    "benchmark_hf_pool_quick",
]
