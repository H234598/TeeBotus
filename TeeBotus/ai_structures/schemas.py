from __future__ import annotations

from datetime import datetime
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
    "source_harvest",
    "tool_request",
    "unknown",
]

AgentTaskName = Literal[
    "none",
    "source_harvest",
    "bibliothekar_query",
    "memory_reflection",
    "reminder_planning",
    "tool_safety",
    "proactive_planning",
    "workflow",
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

    @model_validator(mode="after")
    def _require_text_for_auto_store(self) -> "MemoryCandidate":
        if self.should_store and self.memory_type != "none" and not self.text:
            raise ValueError("text must be non-empty when should_store is true")
        return self


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

    @field_validator("datetime_iso")
    @classmethod
    def _validate_datetime_iso(cls, value: str | None) -> str | None:
        if not value:
            return value
        try:
            datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("datetime_iso must be ISO-8601 parseable") from exc
        return value

    @model_validator(mode="after")
    def _require_actionable_reminder_fields(self) -> "ReminderDecision":
        if self.should_create and not self.text:
            raise ValueError("text must be non-empty when should_create is true")
        if self.should_create and not (self.datetime_iso or self.recurrence):
            raise ValueError("datetime_iso or recurrence is required when should_create is true")
        return self


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
    filters: dict[str, str | list[str]] = Field(default_factory=dict)
    requires_sources: bool = True
    confidence: float = Field(ge=0.0, le=1.0)
    reason_short: str = Field(default="", max_length=240)
    source: Literal["classic", "model", "fallback"] = "model"

    @model_validator(mode="before")
    @classmethod
    def _accept_plan3_field_names(cls, value: Any) -> Any:
        if isinstance(value, dict) and "should_search" not in value and "should_query_bibliothekar" in value:
            value = dict(value)
            value["should_search"] = value.pop("should_query_bibliothekar")
        return value

    @field_validator("query", "reason_short")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        return str(value or "").strip()

    @field_validator("filters", mode="before")
    @classmethod
    def _coerce_filters(cls, value: Any) -> dict[str, str | list[str]]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("filters must be an object")
        filters: dict[str, str | list[str]] = {}
        for key, item in value.items():
            normalized_key = str(key).strip()
            if not normalized_key:
                continue
            if isinstance(item, (list, tuple, set, frozenset)):
                normalized_values = [str(entry).strip() for entry in item if str(entry).strip()]
                if normalized_values:
                    filters[normalized_key] = normalized_values
                continue
            normalized_value = str(item).strip()
            if normalized_value:
                filters[normalized_key] = normalized_value
        return filters

    @property
    def should_query_bibliothekar(self) -> bool:
        return self.should_search


class SourceQualityDecision(BaseModel):
    status: Literal["trusted", "usable", "weak", "reject", "needs_review"]
    reason: str = Field(default="", max_length=500)
    requires_human_review: bool
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("reason")
    @classmethod
    def _strip_reason(cls, value: str) -> str:
        return str(value or "").strip()


class ToolSafetyDecision(BaseModel):
    allowed: bool
    requires_confirmation: bool
    reason: str = Field(default="", max_length=500)
    risk_level: Literal["low", "medium", "high", "blocked"]

    @field_validator("reason")
    @classmethod
    def _strip_reason(cls, value: str) -> str:
        return str(value or "").strip()

    @model_validator(mode="after")
    def _keep_blocked_tools_denied(self) -> "ToolSafetyDecision":
        if self.risk_level == "blocked" and self.allowed:
            raise ValueError("blocked tools must not be allowed")
        return self


class AgentTaskDecision(BaseModel):
    should_run: bool
    task: AgentTaskName = "none"
    objective: str = Field(default="", max_length=800)
    confidence: float = Field(ge=0.0, le=1.0)
    reason_short: str = Field(default="", max_length=240)
    risk_level: Literal["low", "medium", "high", "blocked"] = "low"
    source: Literal["classic", "model", "fallback"] = "model"

    @field_validator("task", mode="before")
    @classmethod
    def _normalize_task(cls, value: str) -> str:
        return str(value or "none").strip().casefold().replace("-", "_") or "none"

    @field_validator("objective", "reason_short")
    @classmethod
    def _strip_agent_text(cls, value: str) -> str:
        return str(value or "").strip()

    @model_validator(mode="after")
    def _require_task_for_run(self) -> "AgentTaskDecision":
        if self.risk_level == "blocked" and self.should_run:
            raise ValueError("blocked agent tasks must not run")
        if self.should_run and self.task == "none":
            raise ValueError("task must not be none when should_run is true")
        if self.should_run and not self.objective:
            raise ValueError("objective must be non-empty when should_run is true")
        return self


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
        empty = sorted(key for key in rule["required"] if _empty_required_argument(self.arguments.get(key)))
        if empty:
            raise ValueError(f"empty required arguments for {self.name}: {', '.join(empty)}")
        unknown = sorted(keys - rule["allowed"])
        if unknown:
            raise ValueError(f"unsupported arguments for {self.name}: {', '.join(unknown)}")
        return self


def _empty_required_argument(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, frozenset)):
        return not any(not _empty_required_argument(item) for item in value)
    if isinstance(value, dict):
        return not any(not _empty_required_argument(item) for item in value.values())
    return False
