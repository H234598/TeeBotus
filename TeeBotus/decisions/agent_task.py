from __future__ import annotations

from TeeBotus.ai_structures.schemas import AgentTaskDecision
from TeeBotus.decisions.parsing import coerce_decision_payload


def parse_agent_task_decision(payload: object) -> AgentTaskDecision:
    return coerce_decision_payload(payload, AgentTaskDecision)


__all__ = ["AgentTaskDecision", "parse_agent_task_decision"]
