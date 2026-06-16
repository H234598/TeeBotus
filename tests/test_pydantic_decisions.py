from __future__ import annotations

import sys
import types

import pytest
from pydantic import ValidationError

from TeeBotus.ai_structures import (
    BibliothekarQueryDecision,
    IntentDecision,
    MemoryCandidate,
    ProactiveToolCallDecision,
    ReminderDecision,
    YouTubeOptionsDecision,
    build_pydantic_ai_model_runner,
    decide_bibliothekar_query,
    decide_intent,
    parse_bibliothekar_query_decision,
    parse_memory_candidate,
    parse_reminder_decision,
    pydantic_ai_available,
)
from TeeBotus.ai_structures.pydantic_ai_adapter import PydanticAIUnavailableError


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


def test_low_confidence_model_intent_falls_back_to_unknown() -> None:
    decision = decide_intent(
        "vielleicht soll das irgendwas ausloesen",
        model_runner=lambda _prompt, _schema: {
            "intent": "reminder",
            "confidence": 0.42,
            "reason_short": "too uncertain",
            "source": "model",
        },
    )

    assert decision.intent == "unknown"
    assert decision.confidence == 0.42
    assert decision.source == "fallback"


def test_bibliothekar_query_decision_classic_and_model_runner_paths() -> None:
    classic = decide_bibliothekar_query("Was sagt das Buch dazu?")
    assert classic.should_search is True
    assert classic.source == "classic"

    calls = []

    def fake_model_runner(prompt, schema):
        calls.append((prompt, schema))
        return {"should_search": False, "query": "", "confidence": 0.91, "reason_short": "smalltalk", "source": "model"}

    decision = decide_bibliothekar_query("Wie geht es dir?", model_runner=fake_model_runner)

    assert decision == BibliothekarQueryDecision(should_search=False, query="", confidence=0.91, reason_short="smalltalk", source="model")
    assert calls and calls[0][1] is BibliothekarQueryDecision


def test_bibliothekar_query_decision_ignores_low_confidence_model_search() -> None:
    decision = decide_bibliothekar_query(
        "Vielleicht gibt es irgendwo etwas dazu?",
        model_runner=lambda _prompt, _schema: {
            "should_search": True,
            "query": "unsichere Quelle",
            "confidence": 0.42,
            "reason_short": "too uncertain",
            "source": "model",
        },
    )

    assert decision == BibliothekarQueryDecision(
        should_search=False,
        query="",
        confidence=0.42,
        reason_short="Model bibliothekar decision below confidence threshold",
        source="model",
    )


def test_bibliothekar_query_decision_schema_accepts_json_payloads() -> None:
    decision = parse_bibliothekar_query_decision(
        '{"should_search": true, "query": "Schlafhygiene Depression", "confidence": 0.88, "reason_short": "library query", "source": "model"}'
    )

    assert decision == BibliothekarQueryDecision(
        should_search=True,
        query="Schlafhygiene Depression",
        confidence=0.88,
        reason_short="library query",
        source="model",
    )


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


def test_memory_candidate_schema_requires_text_for_auto_store() -> None:
    with pytest.raises(ValidationError, match="text must be non-empty"):
        parse_memory_candidate(
            {
                "should_store": True,
                "memory_type": "preference",
                "text": "   ",
                "sensitivity": "low",
                "confidence": 0.91,
            }
        )

    skipped = parse_memory_candidate(
        {
            "should_store": False,
            "memory_type": "none",
            "text": "",
            "sensitivity": "low",
            "confidence": 0.91,
        }
    )

    assert skipped.should_store is False
    assert skipped.memory_type == "none"


def test_memory_candidate_schema_accepts_plan2_clinical_memory_kinds() -> None:
    candidate = parse_memory_candidate(
        {
            "should_store": True,
            "memory_type": "therapy-goal",
            "text": "Morgens einen kurzen Spaziergang als Therapieaufgabe testen.",
            "sensitivity": "medium",
            "confidence": 0.89,
        }
    )

    assert candidate.memory_type == "therapy_goal"

    with pytest.raises(ValidationError, match="unsupported memory_type"):
        parse_memory_candidate(
            {
                "should_store": True,
                "memory_type": "random_private_blob",
                "text": "Soll nicht akzeptiert werden.",
                "sensitivity": "low",
                "confidence": 0.9,
            }
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


def test_reminder_decision_schema_rejects_invalid_datetime_iso() -> None:
    with pytest.raises(ValidationError, match="datetime_iso must be ISO-8601 parseable"):
        parse_reminder_decision(
            {
                "should_create": True,
                "text": "Termin",
                "datetime_iso": "morgen um acht",
                "recurrence": None,
                "confidence": 0.91,
            }
        )


def test_youtube_options_decision_schema_accepts_confidence() -> None:
    decision = YouTubeOptionsDecision.model_validate(
        {
            "live_output": False,
            "send_to_llm": True,
            "confidence": 0.88,
            "reason_short": " explicit local transcript options ",
        }
    )

    assert decision.live_output is False
    assert decision.send_to_llm is True
    assert decision.confidence == 0.88
    assert decision.reason_short == "explicit local transcript options"


def test_proactive_tool_call_decision_validates_known_tool_arguments() -> None:
    call = ProactiveToolCallDecision.model_validate(
        {
            "name": " proactive_queue_message ",
            "call_id": " call_1 ",
            "arguments": {
                "category": "reminder",
                "intent": "follow_up",
                "message_text": "Magst du kurz berichten?",
                "reason_memory_ids": ["mem_goal"],
            },
        }
    )

    assert call.name == "proactive_queue_message"
    assert call.call_id == "call_1"
    assert call.arguments["reason_memory_ids"] == ["mem_goal"]


def test_proactive_tool_call_decision_rejects_missing_or_extra_known_tool_arguments() -> None:
    with pytest.raises(ValidationError, match="missing required arguments"):
        ProactiveToolCallDecision.model_validate(
            {
                "name": "proactive_queue_message",
                "arguments": {"category": "reminder", "intent": "follow_up", "message_text": "Hallo"},
            }
        )

    with pytest.raises(ValidationError, match="unsupported arguments"):
        ProactiveToolCallDecision.model_validate(
            {
                "name": "proactive_create_memory",
                "arguments": {"kind": "reflection", "text": "Plan", "send_now": True},
            }
        )


def test_proactive_tool_call_decision_rejects_empty_required_arguments() -> None:
    with pytest.raises(ValidationError, match="empty required arguments"):
        ProactiveToolCallDecision.model_validate(
            {
                "name": "proactive_create_memory",
                "arguments": {"kind": "reflection", "text": "   "},
            }
        )

    with pytest.raises(ValidationError, match="empty required arguments"):
        ProactiveToolCallDecision.model_validate(
            {
                "name": "proactive_queue_message",
                "arguments": {
                    "category": "reminder",
                    "intent": "follow_up",
                    "message_text": "Hallo",
                    "reason_memory_ids": [],
                },
            }
        )

    with pytest.raises(ValidationError, match="empty required arguments"):
        ProactiveToolCallDecision.model_validate(
            {
                "name": "proactive_snooze_item",
                "arguments": {"item_id": "pro_1", "due_at": ""},
            }
        )


def test_pydantic_ai_adapter_reports_missing_optional_extra(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "pydantic_ai", None)

    assert pydantic_ai_available() is False
    with pytest.raises(PydanticAIUnavailableError, match="pydantic-ai is not installed"):
        build_pydantic_ai_model_runner("openai:gpt-test")


def test_pydantic_ai_adapter_builds_model_runner_with_structured_output(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeRunResult:
        def __init__(self, output: object) -> None:
            self.output = output

    class FakeAgent:
        def __init__(self, model: str, **kwargs: object) -> None:
            calls.append({"model": model, **kwargs})
            self.output_type = kwargs["output_type"]

        def run_sync(self, prompt: str) -> FakeRunResult:
            assert "Bibliothekar" in prompt
            return FakeRunResult(
                self.output_type(
                    should_search=True,
                    query="Schlaf und Tagesstruktur",
                    confidence=0.87,
                    reason_short="structured fake",
                    source="model",
                )
            )

    monkeypatch.setitem(sys.modules, "pydantic_ai", types.SimpleNamespace(Agent=FakeAgent))

    runner = build_pydantic_ai_model_runner("openai:gpt-test", system_prompt="Nur JSON.")
    decision = decide_bibliothekar_query("Bibliothekar: Was sagt das Buch?", model_runner=runner)

    assert decision == BibliothekarQueryDecision(
        should_search=True,
        query="Bibliothekar: Was sagt das Buch?",
        confidence=0.9,
        reason_short="Explicit library/source wording",
        source="classic",
    )
    model_decision = runner("Bibliothekar Frage", BibliothekarQueryDecision)
    assert model_decision == BibliothekarQueryDecision(
        should_search=True,
        query="Schlaf und Tagesstruktur",
        confidence=0.87,
        reason_short="structured fake",
        source="model",
    )
    assert calls == [{"model": "openai:gpt-test", "output_type": BibliothekarQueryDecision, "system_prompt": "Nur JSON."}]
