from __future__ import annotations

from collections.abc import Callable
from typing import Any

from TeeBotus.ai_structures.decisions import decide_residence as _decide_residence
from TeeBotus.ai_structures.schemas import ResidenceDecision
from TeeBotus.decisions.parsing import coerce_decision_payload

ModelRunner = Callable[[str, type[Any]], Any]


def decide_residence(text: str, *, model_runner: ModelRunner | None = None) -> ResidenceDecision:
    return _decide_residence(text, model_runner=model_runner)


def parse_residence_decision(payload: object) -> ResidenceDecision:
    return coerce_decision_payload(payload, ResidenceDecision)


__all__ = ["ResidenceDecision", "decide_residence", "parse_residence_decision"]
