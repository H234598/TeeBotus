from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


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
    memory_type: Literal["preference", "profile", "habit", "project", "relationship", "none"]
    text: str = Field(default="", max_length=1200)
    sensitivity: Literal["low", "medium", "high"]
    confidence: float = Field(ge=0.0, le=1.0)

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
