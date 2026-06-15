from __future__ import annotations

import pytest
from pydantic import ValidationError

from TeeBotus.ai_structures import (
    IntentDecision,
    MemoryCandidate,
    ReminderDecision,
    decide_intent,
    parse_memory_candidate,
    parse_reminder_decision,
)


def test_intent_decision_validates_confidence_range() -> None:
    with pytest.raises(ValidationError):
        IntentDecision(intent="chat", confidence=1.5, reason_short="bad")


def test_classic_slash_commands_are_not_sent_to_model_runner() -> None:
    def fail_model_runner(_prompt, _schema):
        raise AssertionError("model runner must not be called for slash commands")

    decision = decide_intent("/youtube_transcript https://youtu.be/abc123", model_runner=fail_model_runner)

    assert decision.intent == "youtube_transcript"
    assert decision.confidence == 1.0
    assert decision.source == "classic"


def test_classic_registration_and_reminder_intents_are_detected_before_model() -> None:
    assert decide_intent("/login").intent == "login"
    reminder = decide_intent("Erinnere mich morgen um 9 an den Zahnarzt")

    assert reminder.intent == "reminder"
    assert reminder.source == "classic"


def test_unclear_natural_language_can_use_fake_model_runner() -> None:
    calls = []

    def fake_model_runner(prompt, schema):
        calls.append((prompt, schema))
        return {"intent": "bibliothekar_query", "confidence": 0.82, "reason_short": "asks about library", "source": "model"}

    decision = decide_intent("Was sagt mein Buch dazu?", model_runner=fake_model_runner)

    assert decision == IntentDecision(
        intent="bibliothekar_query",
        confidence=0.82,
        reason_short="asks about library",
        source="model",
    )
    assert calls and calls[0][1] is IntentDecision


def test_invalid_model_payload_falls_back_to_unknown() -> None:
    decision = decide_intent("irgendwas diffuses", model_runner=lambda _prompt, _schema: {"intent": "bad", "confidence": 2})

    assert decision.intent == "unknown"
    assert decision.source == "fallback"


def test_memory_candidate_schema_supports_safe_structured_storage_decisions() -> None:
    candidate = parse_memory_candidate(
        {
            "should_store": True,
            "memory_type": "preference",
            "text": " Mag abends kurze Antworten. ",
            "sensitivity": "low",
            "confidence": 0.91,
        }
    )

    assert candidate == MemoryCandidate(
        should_store=True,
        memory_type="preference",
        text="Mag abends kurze Antworten.",
        sensitivity="low",
        confidence=0.91,
    )


def test_reminder_decision_schema_accepts_json_payloads() -> None:
    reminder = parse_reminder_decision(
        '{"should_create": true, "text": "Termin", "datetime_iso": "2026-06-16T09:00:00+00:00", "recurrence": null, "confidence": 0.88}'
    )

    assert reminder == ReminderDecision(
        should_create=True,
        text="Termin",
        datetime_iso="2026-06-16T09:00:00+00:00",
        recurrence=None,
        confidence=0.88,
    )
