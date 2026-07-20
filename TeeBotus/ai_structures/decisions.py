from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from TeeBotus.ai_structures.schemas import BibliothekarQueryDecision, IntentDecision, MemoryCandidate, ReminderDecision, ResidenceDecision
from TeeBotus.core.registration import RegistrationAction, parse_registration_intent
from TeeBotus.core.youtube import YOUTUBE_TRANSCRIPT_COMMANDS, _has_youtube_transcript_intent
from TeeBotus.decisions.parsing import coerce_decision_payload
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
            model_decision = _coerce_model_payload(decision, IntentDecision)
            if model_decision.confidence < 0.7:
                return IntentDecision(
                    intent="unknown",
                    confidence=model_decision.confidence,
                    reason_short="Model intent below confidence threshold",
                    source="fallback",
                )
            return model_decision
        except (TypeError, ValueError, ValidationError, json.JSONDecodeError):
            pass
    return IntentDecision(intent="unknown", confidence=0.0, reason_short="No deterministic intent matched", source="fallback")


def parse_memory_candidate(payload: object) -> MemoryCandidate:
    return _coerce_model_payload(payload, MemoryCandidate)


def parse_reminder_decision(payload: object) -> ReminderDecision:
    return _coerce_model_payload(payload, ReminderDecision)


def decide_bibliothekar_query(text: str, *, model_runner: ModelRunner | None = None) -> BibliothekarQueryDecision:
    value = str(text or "").strip()
    normalized = _normalize_text(value)
    if not value:
        return BibliothekarQueryDecision(should_search=False, query="", confidence=1.0, reason_short="Empty text or slash command", source="classic")
    if _command_name(value) and "youtube-transkript" not in normalized and "youtube transcript" not in normalized:
        return BibliothekarQueryDecision(should_search=False, query="", confidence=1.0, reason_short="Slash command without generated context", source="classic")
    explicit_needles = (
        "bibliothek",
        "bibliothekar",
        "buch",
        "buecher",
        "bücher",
        "quelle",
        "quellen",
        "zitat",
        "zitier",
        "literatur",
        "dokument",
        "pdf",
        "epub",
        "was sagt",
        "steht dazu",
    )
    if any(needle in normalized for needle in explicit_needles):
        return BibliothekarQueryDecision(should_search=True, query=value, confidence=0.9, reason_short="Explicit library/source wording", source="classic")
    if model_runner is not None:
        try:
            decision = model_runner(_bibliothekar_query_prompt(value), BibliothekarQueryDecision)
            model_decision = _coerce_model_payload(decision, BibliothekarQueryDecision)
            if model_decision.confidence < 0.7:
                return BibliothekarQueryDecision(
                    should_search=False,
                    query="",
                    confidence=model_decision.confidence,
                    reason_short="Model bibliothekar decision below confidence threshold",
                    source="model",
                )
            return model_decision
        except (TypeError, ValueError, ValidationError, json.JSONDecodeError):
            return BibliothekarQueryDecision(
                should_search=False,
                query="",
                confidence=0.0,
                reason_short="Structured Bibliothekar decision unavailable; skipped search",
                source="fallback",
            )
    return BibliothekarQueryDecision(should_search=True, query=value, confidence=0.35, reason_short="Fallback keeps existing Bibliothekar behavior", source="fallback")


def parse_bibliothekar_query_decision(payload: object) -> BibliothekarQueryDecision:
    return _coerce_model_payload(payload, BibliothekarQueryDecision)


def decide_residence(text: str, *, model_runner: ModelRunner | None = None) -> ResidenceDecision:
    value = str(text or "").strip()
    if not value or model_runner is None:
        return ResidenceDecision(
            kind="none",
            city="",
            confidence=0.0,
            reason_short="No residence decision runner available",
            source="fallback",
        )
    try:
        decision = model_runner(_residence_prompt(value), ResidenceDecision)
        model_decision = _coerce_model_payload(decision, ResidenceDecision)
        if model_decision.confidence < 0.75:
            return ResidenceDecision(
                kind="ambiguous",
                city="",
                confidence=model_decision.confidence,
                reason_short="Model residence decision below confidence threshold",
                source="fallback",
            )
        return model_decision
    except (TypeError, ValueError, ValidationError, json.JSONDecodeError):
        return ResidenceDecision(
            kind="ambiguous",
            city="",
            confidence=0.0,
            reason_short="Structured residence decision unavailable",
            source="fallback",
        )


def parse_residence_decision(payload: object) -> ResidenceDecision:
    return _coerce_model_payload(payload, ResidenceDecision)


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
    return coerce_decision_payload(payload, schema)


def _intent_prompt(text: str) -> str:
    return (
        "Klassifiziere die Nutzerabsicht fuer TeeBotus. Antworte nur als JSON fuer IntentDecision. "
        "Slash-Commands werden klassisch verarbeitet; diese Anfrage ist natuerliche Sprache.\n\n"
        f"Nachricht:\n{text.strip()}"
    )


def _bibliothekar_query_prompt(text: str) -> str:
    return (
        "Entscheide, ob TeeBotus fuer diese natuerliche Nutzerfrage den Bibliothekar/RAG-Quellenindex durchsuchen soll. "
        "Antworte nur als JSON fuer BibliothekarQueryDecision. should_search ist true bei Fragen nach Buechern, Dokumenten, Quellen, Zitaten, Literatur oder gespeichertem Bibliothekswissen. "
        "Wenn true, normalisiere query auf eine knappe Suchfrage. Wenn false, lasse query leer.\n\n"
        f"Nachricht:\n{text.strip()}"
    )


def _residence_prompt(text: str) -> str:
    return (
        "Ordne ausschliesslich Orts-/Wohnortangaben dieser Nachricht. Antworte nur als JSON fuer ResidenceDecision. "
        "kind muss genau eines sein: primary (dauerhafter eigener Wohnort), temporary (zeitweiliger Aufenthalt), "
        "secondary (Nebenwohnsitz), historical (frueherer Wohnort), registration (Melde-/Registrierungsadresse), "
        "work (Arbeitsort), travel (Reiseort), none oder ambiguous. "
        "Nur primary darf Wetter-Wohnort aktualisieren. Bei mehreren konkurrierenden Orten oder unklarer Zeit-/Beziehungslage: ambiguous. "
        "city darf nur ein Ort sein, der woertlich in der Nachricht steht; nichts erfinden. Bei none/ambiguous city leer lassen. "
        "confidence zwischen 0 und 1.\n\n"
        f"Nachricht:\n{text}"
    )


def _normalize_text(text: str) -> str:
    return str(text or "").casefold().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")


def _command_name(text: str) -> str:
    stripped = str(text or "").strip()
    if not stripped.startswith("/"):
        return ""
    command = stripped.split(maxsplit=1)[0].casefold()
    if "@" in command:
        command = command.split("@", maxsplit=1)[0]
    return command
