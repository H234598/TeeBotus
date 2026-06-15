from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from TeeBotus.ai_structures.schemas import IntentDecision, MemoryCandidate, ReminderDecision
from TeeBotus.core.registration import RegistrationAction, parse_registration_intent
from TeeBotus.core.youtube import YOUTUBE_TRANSCRIPT_COMMANDS, _has_youtube_transcript_intent
from TeeBotus.runtime.reminder_intent import parse_reminder_intent

ModelRunner = Callable[[str, type[Any]], Any]

COMMAND_INTENTS = {
    "/status": "chat",
    "/info": "chat",
    "/help": "chat",
    "/hilfe": "chat",
    "/reset_memorys": "memory_reset",
    "/memory_reset": "memory_reset",
    "/export": "chat",
}


def decide_intent(text: str, *, model_runner: ModelRunner | None = None) -> IntentDecision:
    """Classify user intent without letting model output override slash commands."""
    value = str(text or "").strip()
    command = _command_name(value)
    if command:
        return _classic_command_intent(command)
    registration = parse_registration_intent(value)
    if registration.action != RegistrationAction.NONE:
        return _classic_registration_intent(registration.action)
    if _has_youtube_transcript_intent(value):
        return IntentDecision(intent="youtube_transcript", confidence=0.93, reason_short="YouTube transcript wording", source="classic")
    reminder = parse_reminder_intent(value)
    if reminder.is_request:
        return IntentDecision(intent="reminder", confidence=0.9, reason_short="Reminder wording", source="classic")
    if model_runner is not None:
        try:
            decision = model_runner(_intent_prompt(value), IntentDecision)
            return _coerce_model_payload(decision, IntentDecision)
        except (TypeError, ValueError, ValidationError, json.JSONDecodeError):
            pass
    return IntentDecision(intent="unknown", confidence=0.0, reason_short="No deterministic intent matched", source="fallback")


def parse_memory_candidate(payload: object) -> MemoryCandidate:
    return _coerce_model_payload(payload, MemoryCandidate)


def parse_reminder_decision(payload: object) -> ReminderDecision:
    return _coerce_model_payload(payload, ReminderDecision)


def _classic_command_intent(command: str) -> IntentDecision:
    if command in YOUTUBE_TRANSCRIPT_COMMANDS:
        return IntentDecision(intent="youtube_transcript", confidence=1.0, reason_short=f"Slash command {command}", source="classic")
    registration = parse_registration_intent(command)
    if registration.action != RegistrationAction.NONE:
        return _classic_registration_intent(registration.action)
    intent = COMMAND_INTENTS.get(command, "unknown")
    confidence = 1.0 if intent != "unknown" else 0.0
    return IntentDecision(intent=intent, confidence=confidence, reason_short=f"Slash command {command}", source="classic")


def _classic_registration_intent(action: RegistrationAction) -> IntentDecision:
    mapping = {
        RegistrationAction.ACCOUNT: "account",
        RegistrationAction.REGISTER: "register",
        RegistrationAction.LOGIN: "login",
        RegistrationAction.ROTATE_SECRET: "account",
        RegistrationAction.UNLINK_THIS_CHANNEL: "account",
        RegistrationAction.ACCOUNT_EDIT: "account",
        RegistrationAction.LINKED_ACCOUNTS: "account",
        RegistrationAction.WTF_UNLINK: "account",
    }
    return IntentDecision(
        intent=mapping.get(action, "unknown"),
        confidence=1.0,
        reason_short=f"Registration parser action {action.value}",
        source="classic",
    )


def _coerce_model_payload(payload: object, schema: type[Any]) -> Any:
    if isinstance(payload, schema):
        return payload
    if isinstance(payload, str):
        payload = json.loads(payload)
    if hasattr(schema, "model_validate"):
        return schema.model_validate(payload)
    raise TypeError(f"Unsupported schema: {schema!r}")


def _intent_prompt(text: str) -> str:
    return (
        "Klassifiziere die Nutzerabsicht fuer TeeBotus. Antworte nur als JSON fuer IntentDecision. "
        "Slash-Commands werden klassisch verarbeitet; diese Anfrage ist natuerliche Sprache.\n\n"
        f"Nachricht:\n{text.strip()}"
    )


def _command_name(text: str) -> str:
    stripped = str(text or "").strip()
    if not stripped.startswith("/"):
        return ""
    command = stripped.split(maxsplit=1)[0].casefold()
    if "@" in command:
        command = command.split("@", maxsplit=1)[0]
    return command
