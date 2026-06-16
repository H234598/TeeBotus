from __future__ import annotations

import pytest

from TeeBotus.decisions import (
    BibliothekarQueryDecision,
    FakeDecisionModel,
    IntentDecision,
    build_fake_model_runner,
    decide_bibliothekar_query,
    decide_intent,
)


def test_fake_decision_model_validates_response_with_requested_schema() -> None:
    model = FakeDecisionModel(
        {
            "IntentDecision": {
                "intent": "bibliothekar_query",
                "confidence": 0.83,
                "reason_short": "asks about sources",
                "source": "model",
            }
        }
    )

    decision = decide_intent("Bitte ordne das ein", model_runner=model.runner())

    assert decision == IntentDecision(
        intent="bibliothekar_query",
        confidence=0.83,
        reason_short="asks about sources",
        source="model",
    )
    assert model.calls and model.calls[0][1] is IntentDecision


def test_fake_decision_model_accepts_json_payloads_for_bibliothekar_decisions() -> None:
    runner = build_fake_model_runner(
        {
            "BibliothekarQueryDecision": (
                '{"should_search": true, "query": "Schlafhygiene Depression", '
                '"confidence": 0.91, "reason_short": "source question", "source": "model"}'
            )
        }
    )

    decision = decide_bibliothekar_query("Kannst du in den Quellen nach Schlaf suchen?", model_runner=runner)

    assert decision == BibliothekarQueryDecision(
        should_search=True,
        query="Kannst du in den Quellen nach Schlaf suchen?",
        confidence=0.9,
        reason_short="Explicit library/source wording",
        source="classic",
    )

    model_decision = decide_bibliothekar_query("Wie würdest du das thematisch einordnen?", model_runner=runner)

    assert model_decision.query == "Schlafhygiene Depression"
    assert model_decision.source == "model"


def test_fake_decision_model_missing_schema_response_is_explicit() -> None:
    model = FakeDecisionModel({})

    with pytest.raises(KeyError, match="IntentDecision"):
        model("prompt", IntentDecision)


def test_slash_commands_stay_classic_even_with_fake_model() -> None:
    def fail_response(_prompt, _schema):
        raise AssertionError("slash commands must not call fake model")

    model = FakeDecisionModel({"IntentDecision": fail_response})

    decision = decide_intent("/status", model_runner=model.runner())

    assert decision.source == "classic"
    assert model.calls == []
