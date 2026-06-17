from __future__ import annotations

from TeeBotus.ai_structures.schemas import SourceQualityDecision
from TeeBotus.decisions.parsing import coerce_decision_payload


def parse_source_quality_decision(payload: object) -> SourceQualityDecision:
    return coerce_decision_payload(payload, SourceQualityDecision)


__all__ = ["SourceQualityDecision", "parse_source_quality_decision"]
