from __future__ import annotations

from TeeBotus.ai_structures.schemas import IntentDecision, MemoryCandidate, ReminderDecision

__all__ = [
    "IntentDecision",
    "MemoryCandidate",
    "ReminderDecision",
    "decide_intent",
    "parse_memory_candidate",
    "parse_reminder_decision",
]


def __getattr__(name: str):
    if name in {"decide_intent", "parse_memory_candidate", "parse_reminder_decision"}:
        from TeeBotus.ai_structures import decisions

        return getattr(decisions, name)
    raise AttributeError(name)
