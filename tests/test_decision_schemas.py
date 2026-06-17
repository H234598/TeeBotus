from __future__ import annotations

import pytest
from pydantic import ValidationError

from TeeBotus.decisions import (
    AgentTaskDecision,
    BibliothekarQueryDecision,
    IntentDecision,
    MemoryCandidate,
    ProactiveToolCallDecision,
    ReminderDecision,
    ToolSafetyDecision,
)
from TeeBotus.decisions.agent_task import parse_agent_task_decision
from TeeBotus.decisions.bibliothekar import decide_bibliothekar_query
from TeeBotus.decisions.intent import parse_intent_decision
from TeeBotus.decisions.proactive import parse_proactive_tool_call_decision
from TeeBotus.decisions.pydantic_agent import pydantic_ai_available
from TeeBotus.decisions.source_quality import parse_source_quality_decision
from TeeBotus.decisions.tool_safety import parse_tool_safety_decision
from TeeBotus.decisions.youtube import parse_youtube_options_decision


def test_decision_package_exports_core_pydantic_schemas() -> None:
    assert IntentDecision(intent="chat", confidence=1.0).intent == "chat"
    assert BibliothekarQueryDecision(should_search=True, query="Schlaf", confidence=0.8).should_search is True
    assert ReminderDecision(should_create=False, confidence=0.9).should_create is False
    assert ToolSafetyDecision(allowed=True, requires_confirmation=False, risk_level="low").risk_level == "low"
    assert AgentTaskDecision(should_run=False, confidence=0.9).task == "none"
    assert isinstance(pydantic_ai_available(), bool)


def test_bibliothekar_query_decision_accepts_plan3_alias_fields() -> None:
    decision = BibliothekarQueryDecision.model_validate(
        {
            "should_query_bibliothekar": True,
            "query": " Schlaf ",
            "filters": {"topic": " Depression "},
            "requires_sources": True,
            "confidence": 0.82,
        }
    )

    assert decision.should_search is True
    assert decision.should_query_bibliothekar is True
    assert decision.query == "Schlaf"
    assert decision.filters == {"topic": "Depression"}


def test_memory_candidate_schema_keeps_existing_safety_rules() -> None:
    candidate = MemoryCandidate(
        should_store=True,
        memory_type="therapy-goal",
        text="Morgens Spaziergang testen.",
        sensitivity="medium",
        confidence=0.9,
    )

    assert candidate.memory_type == "therapy_goal"

    with pytest.raises(ValidationError, match="text must be non-empty"):
        MemoryCandidate(should_store=True, memory_type="preference", text="", sensitivity="low", confidence=0.9)


def test_proactive_tool_call_schema_validates_known_tool_arguments() -> None:
    call = ProactiveToolCallDecision(
        name="proactive_create_memory",
        arguments={"kind": "reflection", "text": "Schlafrhythmus beobachten"},
        call_id="call_1",
    )

    assert call.name == "proactive_create_memory"

    with pytest.raises(ValidationError, match="missing required arguments"):
        ProactiveToolCallDecision(name="proactive_create_memory", arguments={"kind": "reflection"})


def test_tool_safety_schema_blocks_inconsistent_blocked_allow() -> None:
    decision = ToolSafetyDecision(
        allowed=False,
        requires_confirmation=False,
        reason="Zu riskant fuer automatische Ausfuehrung.",
        risk_level="blocked",
    )

    assert decision.reason == "Zu riskant fuer automatische Ausfuehrung."

    with pytest.raises(ValidationError, match="blocked tools must not be allowed"):
        ToolSafetyDecision(allowed=True, requires_confirmation=True, reason="no", risk_level="blocked")


def test_decision_facade_modules_parse_structured_payloads() -> None:
    intent = parse_intent_decision('{"intent":"chat","confidence":0.82,"reason_short":"ok","source":"model"}')
    agent_task = parse_agent_task_decision(
        {
            "should_run": True,
            "task": "source-harvest",
            "objective": "Quelle pruefen",
            "confidence": 0.86,
            "reason_short": "ok",
            "risk_level": "low",
        }
    )
    source_quality = parse_source_quality_decision(
        {"status": "usable", "reason": "metadata ok", "requires_human_review": False, "confidence": 0.72}
    )
    tool_safety = parse_tool_safety_decision(
        {"allowed": True, "requires_confirmation": False, "reason": "read-only", "risk_level": "low"}
    )
    youtube_options = parse_youtube_options_decision({"live_output": False, "send_to_llm": True, "confidence": 0.91})
    proactive_call = parse_proactive_tool_call_decision(
        {"name": "proactive_noop", "arguments": {"reason": "test"}, "call_id": "call_1"}
    )
    bibliothekar = decide_bibliothekar_query("Was sagt die Bibliothek zu Schlaf?")

    assert intent.intent == "chat"
    assert agent_task.task == "source_harvest"
    assert source_quality.status == "usable"
    assert tool_safety.risk_level == "low"
    assert youtube_options.send_to_llm is True
    assert proactive_call.name == "proactive_noop"
    assert bibliothekar.should_search is True


def test_agent_task_decision_blocks_unsafe_or_empty_run_requests() -> None:
    with pytest.raises(ValidationError, match="task must not be none"):
        AgentTaskDecision(should_run=True, task="none", objective="Aufgabe", confidence=0.8)

    with pytest.raises(ValidationError, match="objective must be non-empty"):
        AgentTaskDecision(should_run=True, task="source_harvest", objective="", confidence=0.8)

    with pytest.raises(ValidationError, match="blocked agent tasks must not run"):
        AgentTaskDecision(
            should_run=True,
            task="workflow",
            objective="Riskante Aktion",
            confidence=0.8,
            risk_level="blocked",
        )
