from __future__ import annotations

from TeeBotus.ai_structures.schemas import ToolSafetyDecision
from TeeBotus.decisions.parsing import coerce_decision_payload


def parse_tool_safety_decision(payload: object) -> ToolSafetyDecision:
    return coerce_decision_payload(payload, ToolSafetyDecision)


__all__ = ["ToolSafetyDecision", "parse_tool_safety_decision"]
