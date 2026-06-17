from __future__ import annotations

from collections.abc import Callable
from typing import Any

from TeeBotus.ai_structures.schemas import IntentDecision
from TeeBotus.decisions.parsing import coerce_decision_payload

ModelRunner = Callable[[str, type[Any]], Any]


def decide_intent(text: str, *, model_runner: ModelRunner | None = None) -> IntentDecision:
    from TeeBotus.ai_structures.decisions import decide_intent as _decide_intent

    return _decide_intent(text, model_runner=model_runner)


def parse_intent_decision(payload: object) -> IntentDecision:
    return coerce_decision_payload(payload, IntentDecision)


__all__ = ["IntentDecision", "ModelRunner", "decide_intent", "parse_intent_decision"]
