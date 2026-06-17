from __future__ import annotations

from TeeBotus.ai_structures.schemas import ProactiveToolCallDecision
from TeeBotus.decisions.parsing import coerce_decision_payload


def parse_proactive_tool_call_decision(payload: object) -> ProactiveToolCallDecision:
    return coerce_decision_payload(payload, ProactiveToolCallDecision)


__all__ = ["ProactiveToolCallDecision", "parse_proactive_tool_call_decision"]
