from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from TeeBotus.runtime.accounts import ACCOUNT_MEMORY_KINDS, ACCOUNT_MEMORY_TYPES


IntentName = Literal[
    "chat",
    "account",
    "register",
    "login",
    "memory_reset",
    "reminder",
    "youtube_transcript",
    "bibliothekar_query",
    "tool_request",
    "unknown",
]


class IntentDecision(BaseModel):
    intent: IntentName
    confidence: float = Field(ge=0.0, le=1.0)
    reason_short: str = Field(default="", max_length=240)
    source: Literal["classic", "model", "fallback"] = "model"

    @field_validator("reason_short")
    @classmethod
    def _strip_reason(cls, value: str) -> str:
        return str(value or "").strip()


class MemoryCandidate(BaseModel):
    should_store: bool
    memory_type: str = Field(max_length=80)
    text: str = Field(default="", max_length=1200)
    sensitivity: Literal["low", "medium", "high"]
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("memory_type")
    @classmethod
    def _normalize_memory_type(cls, value: str) -> str:
        normalized = str(value or "").strip().casefold().replace("-", "_")
        allowed = ACCOUNT_MEMORY_KINDS | ACCOUNT_MEMORY_TYPES | {"habit", "profile", "project", "relationship", "none"}
        if normalized not in allowed:
            raise ValueError(f"unsupported memory_type: {value}")
        return normalized

    @field_validator("text")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        return str(value or "").strip()


class ReminderDecision(BaseModel):
    should_create: bool
    text: str = Field(default="", max_length=800)
    datetime_iso: str | None = None
    recurrence: str | None = Field(default=None, max_length=240)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("text", "datetime_iso", "recurrence")
    @classmethod
    def _strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return str(value).strip()


class YouTubeOptionsDecision(BaseModel):
    live_output: bool | None = None
    send_to_llm: bool | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reason_short: str = Field(default="", max_length=240)

    @field_validator("reason_short")
    @classmethod
    def _strip_reason(cls, value: str) -> str:
        return str(value or "").strip()


class BibliothekarQueryDecision(BaseModel):
    should_search: bool
    query: str = Field(default="", max_length=800)
    confidence: float = Field(ge=0.0, le=1.0)
    reason_short: str = Field(default="", max_length=240)
    source: Literal["classic", "model", "fallback"] = "model"

    @field_validator("query", "reason_short")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        return str(value or "").strip()


PROACTIVE_TOOL_ARGUMENTS: dict[str, dict[str, set[str]]] = {
    "proactive_create_memory": {
        "required": {"kind", "text"},
        "allowed": {"kind", "text", "source_memory_ids", "importance"},
    },
    "proactive_queue_message": {
        "required": {"category", "intent", "message_text", "reason_memory_ids"},
        "allowed": {
            "category",
            "intent",
            "message_text",
            "reason_memory_ids",
            "risk_gate",
            "due_at",
            "intervention_type",
            "expected_response",
            "review_signal",
            "collaboration_marker",
            "file",
        },
    },
    "proactive_cancel_item": {
        "required": {"item_id"},
        "allowed": {"item_id", "reason"},
    },
    "proactive_snooze_item": {
        "required": {"item_id", "due_at"},
        "allowed": {"item_id", "due_at", "reason"},
    },
    "proactive_noop": {
        "required": set(),
        "allowed": {"reason"},
    },
}


class ProactiveToolCallDecision(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    arguments: dict[str, Any] = Field(default_factory=dict)
    call_id: str = Field(default="", max_length=160)

    @field_validator("name", "call_id")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        return str(value or "").strip()

    @field_validator("arguments", mode="before")
    @classmethod
    def _coerce_arguments(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("tool arguments must be an object")
        return {str(key): item for key, item in value.items()}

    @model_validator(mode="after")
    def _validate_known_tool_arguments(self) -> "ProactiveToolCallDecision":
        rule = PROACTIVE_TOOL_ARGUMENTS.get(self.name)
        if rule is None:
            return self
        keys = set(self.arguments)
        missing = sorted(rule["required"] - keys)
        if missing:
            raise ValueError(f"missing required arguments for {self.name}: {', '.join(missing)}")
        unknown = sorted(keys - rule["allowed"])
        if unknown:
            raise ValueError(f"unsupported arguments for {self.name}: {', '.join(unknown)}")
        return self
