from __future__ import annotations

import pytest
from pydantic import ValidationError

from TeeBotus.decisions import (
    BibliothekarQueryDecision,
    IntentDecision,
    MemoryCandidate,
    ProactiveToolCallDecision,
    ReminderDecision,
    ToolSafetyDecision,
)


def test_decision_package_exports_core_pydantic_schemas() -> None:
    assert IntentDecision(intent="chat", confidence=1.0).intent == "chat"
    assert BibliothekarQueryDecision(should_search=True, query="Schlaf", confidence=0.8).should_search is True
    assert ReminderDecision(should_create=False, confidence=0.9).should_create is False
    assert ToolSafetyDecision(allowed=True, requires_confirmation=False, risk_level="low").risk_level == "low"


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
