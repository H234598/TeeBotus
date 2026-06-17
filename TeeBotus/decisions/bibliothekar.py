from __future__ import annotations

from collections.abc import Callable
from typing import Any

from TeeBotus.ai_structures.schemas import BibliothekarQueryDecision
from TeeBotus.decisions.parsing import coerce_decision_payload

ModelRunner = Callable[[str, type[Any]], Any]


def decide_bibliothekar_query(text: str, *, model_runner: ModelRunner | None = None) -> BibliothekarQueryDecision:
    from TeeBotus.ai_structures.decisions import decide_bibliothekar_query as _decide_bibliothekar_query

    return _decide_bibliothekar_query(text, model_runner=model_runner)


def parse_bibliothekar_query_decision(payload: object) -> BibliothekarQueryDecision:
    return coerce_decision_payload(payload, BibliothekarQueryDecision)

__all__ = [
    "BibliothekarQueryDecision",
    "decide_bibliothekar_query",
    "parse_bibliothekar_query_decision",
]
