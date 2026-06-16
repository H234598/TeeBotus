from __future__ import annotations

from TeeBotus.ai_structures.schemas import (
    BibliothekarQueryDecision,
    IntentDecision,
    MemoryCandidate,
    ProactiveToolCallDecision,
    ReminderDecision,
    SourceQualityDecision,
    ToolSafetyDecision,
    YouTubeOptionsDecision,
)

__all__ = [
    "BibliothekarQueryDecision",
    "IntentDecision",
    "MemoryCandidate",
    "ProactiveToolCallDecision",
    "ReminderDecision",
    "SourceQualityDecision",
    "ToolSafetyDecision",
    "YouTubeOptionsDecision",
    "decide_bibliothekar_query",
    "decide_intent",
    "parse_bibliothekar_query_decision",
    "parse_memory_candidate",
    "parse_reminder_decision",
    "PydanticAIUnavailableError",
    "build_pydantic_ai_model_runner",
    "pydantic_ai_available",
]


def __getattr__(name: str):
    if name in {"decide_bibliothekar_query", "decide_intent", "parse_bibliothekar_query_decision", "parse_memory_candidate", "parse_reminder_decision"}:
        from TeeBotus.ai_structures import decisions

        return getattr(decisions, name)
    if name in {"PydanticAIUnavailableError", "build_pydantic_ai_model_runner", "pydantic_ai_available"}:
        from TeeBotus.ai_structures import pydantic_ai_adapter

        return getattr(pydantic_ai_adapter, name)
    raise AttributeError(name)
