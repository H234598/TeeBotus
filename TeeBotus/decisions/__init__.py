from __future__ import annotations

from TeeBotus.decisions.schemas import (
    AgentTaskDecision,
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
    "AgentTaskDecision",
    "BibliothekarQueryDecision",
    "FakeDecisionModel",
    "IntentDecision",
    "MemoryCandidate",
    "PydanticAIUnavailableError",
    "ProactiveToolCallDecision",
    "ReminderDecision",
    "SourceQualityDecision",
    "ToolSafetyDecision",
    "YouTubeOptionsDecision",
    "build_fake_model_runner",
    "build_pydantic_ai_model_runner",
    "build_router_pydantic_ai_model_runner",
    "decide_bibliothekar_query",
    "decide_intent",
    "parse_agent_task_decision",
    "parse_bibliothekar_query_decision",
    "parse_intent_decision",
    "parse_memory_candidate",
    "parse_proactive_tool_call_decision",
    "parse_reminder_decision",
    "parse_source_quality_decision",
    "parse_tool_safety_decision",
    "parse_youtube_options_decision",
    "pydantic_ai_available",
]


def __getattr__(name: str):
    if name in {"FakeDecisionModel", "build_fake_model_runner"}:
        from TeeBotus.decisions import fake_model

        return getattr(fake_model, name)
    if name in {"PydanticAIUnavailableError", "build_pydantic_ai_model_runner", "build_router_pydantic_ai_model_runner", "pydantic_ai_available"}:
        from TeeBotus.decisions import pydantic_agent

        return getattr(pydantic_agent, name)
    if name in {"decide_intent", "parse_intent_decision"}:
        from TeeBotus.decisions import intent

        return getattr(intent, name)
    if name in {"decide_bibliothekar_query", "parse_bibliothekar_query_decision"}:
        from TeeBotus.decisions import bibliothekar

        return getattr(bibliothekar, name)
    if name == "parse_agent_task_decision":
        from TeeBotus.decisions import agent_task

        return getattr(agent_task, name)
    if name == "parse_memory_candidate":
        from TeeBotus.decisions import memory

        return getattr(memory, name)
    if name == "parse_reminder_decision":
        from TeeBotus.decisions import reminder

        return getattr(reminder, name)
    if name == "parse_proactive_tool_call_decision":
        from TeeBotus.decisions import proactive

        return getattr(proactive, name)
    if name == "parse_source_quality_decision":
        from TeeBotus.decisions import source_quality

        return getattr(source_quality, name)
    if name == "parse_tool_safety_decision":
        from TeeBotus.decisions import tool_safety

        return getattr(tool_safety, name)
    if name == "parse_youtube_options_decision":
        from TeeBotus.decisions import youtube

        return getattr(youtube, name)
    raise AttributeError(name)
