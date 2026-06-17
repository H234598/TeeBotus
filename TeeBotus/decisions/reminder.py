from __future__ import annotations

from TeeBotus.ai_structures.schemas import ReminderDecision
from TeeBotus.decisions.parsing import coerce_decision_payload


def parse_reminder_decision(payload: object) -> ReminderDecision:
    return coerce_decision_payload(payload, ReminderDecision)

__all__ = ["ReminderDecision", "parse_reminder_decision"]
