from __future__ import annotations

import math
import re
from copy import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from TeeBotus.instructions import BotInstructions
from TeeBotus.runtime.accounts import AccountStore, AccountStoreError

TTS_DIALECT_STATE_KEY = "tts_dialect"
TTS_VOICE_STATE_KEY = "tts_voice"
TTS_MIMIC_VOICE_STATE_KEY = "tts_mimic_voice"
TTS_MIMIC_POSITION_BEFORE_DIALECT = "before_dialect"
TTS_MIMIC_POSITION_AFTER_DIALECT = "after_dialect"
OPENAI_TTS_VOICE_DOCS_URL = "https://platform.openai.com/docs/guides/text-to-speech#voice-options"
OPENAI_TTS_VOICES = (
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "fable",
    "nova",
    "onyx",
    "sage",
    "shimmer",
    "verse",
    "marin",
    "cedar",
)
OPENAI_LEGACY_TTS_VOICES = ("alloy", "ash", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer")
OPENAI_TTS_VOICE_ALIASES = {
    "onys": "onyx",
    "ony": "onyx",
    "onyx": "onyx",
    "marlin": "marin",
    "standard": "",
    "default": "",
    "reset": "",
    "off": "",
    "aus": "",
}

_CITY_PATTERN = r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})"
_BIRTH_CITY_PATTERNS = (
    re.compile(rf"\b(?:ich\s+bin|bin)\s+in\s+{_CITY_PATTERN}\s+geboren\b", re.IGNORECASE),
    re.compile(rf"\b(?:ich\s+wurde|wurde\s+ich)\s+in\s+{_CITY_PATTERN}\s+geboren\b", re.IGNORECASE),
    re.compile(rf"\bgeboren\s+wurde\s+ich\s+(?:in|bei)\s+{_CITY_PATTERN}", re.IGNORECASE),
    re.compile(rf"\b(?:geboren|geb\.)\s+(?:in|bei)\s+{_CITY_PATTERN}", re.IGNORECASE),
    re.compile(rf"\b(?:meine\s+geburtsstadt|mein\s+geburtsort)\s+(?:ist|heisst|heißt|war)\s+{_CITY_PATTERN}", re.IGNORECASE),
)
_LIFETIME_CITY_PATTERNS = (
    re.compile(rf"\b(?:die\s+)?(?:meiste|laengste|längste)\s+zeit\s+(?:meines\s+lebens\s+)?(?:habe\s+ich\s+)?(?:in|bei)\s+{_CITY_PATTERN}\s+(?:gelebt|verbracht|gewohnt)\b", re.IGNORECASE),
    re.compile(rf"\b(?:ich\s+)?(?:habe\s+)?(?:den\s+)?(?:groessten|größten|grossen|großen)\s+teil\s+meines\s+lebens\s+(?:in|bei)\s+{_CITY_PATTERN}\s+(?:gelebt|verbracht|gewohnt)\b", re.IGNORECASE),
    re.compile(rf"\b(?:ich\s+)?(?:habe\s+)?(?:fast\s+)?mein\s+ganzes\s+leben\s+(?:in|bei)\s+{_CITY_PATTERN}\s+(?:gelebt|verbracht|gewohnt)\b", re.IGNORECASE),
)
_POSITIVE_RE = re.compile(r"\b(mochte|mag|liebte|liebe|gern|gerne|schoen|schön|gut|heimat|zuhause|wohlgefuehlt|wohlgefühlt)\b", re.IGNORECASE)
_NEGATIVE_RE = re.compile(
    r"\b(?:hasste|hass|schlimm|furchtbar|ungern|nie\s+gemocht)\b|"
    r"\b(?:nicht|nie)\b.{0,40}\b(?:mochte|mag|liebte|liebe|gern|gerne|schoen|schön|gut|heimat|zuhause|wohlgefuehlt|wohlgefühlt)\b|"
    r"\b(?:mochte|mag|liebte|liebe|gern|gerne|schoen|schön|gut|heimat|zuhause|wohlgefuehlt|wohlgefühlt)\b.{0,40}\b(?:nicht|nie)\b",
    re.IGNORECASE,
)
_YES_RE = re.compile(r"^\s*(ja|jep|jo|yes|y|klar|stimmt|genau|mochte ich|habe ich gemocht|war gut|war schoen|war schön)\b", re.IGNORECASE)
_NO_RE = re.compile(r"^\s*(nein|nee|no|n|nicht|gar nicht|abbrechen|cancel|mochte ich nicht|eher nicht)\b", re.IGNORECASE)


@dataclass(frozen=True)
class TtsDialectUpdate:
    city: str = ""
    source: str = ""
    reply_text: str = ""
    changed: bool = False
    pending: bool = False


@dataclass(frozen=True)
class TtsVoiceCommandResult:
    reply_text: str
    changed: bool = False
    voice: str = ""


@dataclass(frozen=True)
class TtsMimicVoiceCommandResult:
    reply_text: str
    changed: bool = False
    enabled: bool = False
    position: str = TTS_MIMIC_POSITION_AFTER_DIALECT


def maybe_update_tts_dialect_preference(account_store: AccountStore, account_id: str, text: str) -> TtsDialectUpdate:
    if not account_id:
        return TtsDialectUpdate()
    with account_store.account_memory_lock(account_id):
        return _maybe_update_tts_dialect_preference_unlocked(account_store, account_id, text)


def _maybe_update_tts_dialect_preference_unlocked(account_store: AccountStore, account_id: str, text: str) -> TtsDialectUpdate:
    normalized_text = str(text or "").strip()
    if not normalized_text:
        return TtsDialectUpdate()
    try:
        state = account_store.read_agent_state(account_id)
    except (AccountStoreError, OSError, ValueError):
        return TtsDialectUpdate()

    pending = _pending_lifetime_city(state)
    if pending is not None:
        city = str(pending.get("city") or "").strip()
        if _NO_RE.search(normalized_text) or _NEGATIVE_RE.search(normalized_text):
            _clear_pending_lifetime_city(state)
            _write_state(account_store, account_id, state)
            return TtsDialectUpdate(reply_text="Okay, dann aendere ich den TTS-Dialekt nicht.")
        if city and _YES_RE.search(normalized_text):
            _set_dialect_city(state, city, "lifetime_city_confirmed")
            _write_state(account_store, account_id, state)
            return TtsDialectUpdate(city=city, source="lifetime_city_confirmed", changed=True, reply_text=f"Okay, fuer Sprachnachrichten nutze ich ab jetzt eine leichte regionale Faerbung aus {city}.")

    birth_city = extract_birth_city(normalized_text)
    if birth_city:
        _set_dialect_city(state, birth_city, "birth_city")
        _write_state(account_store, account_id, state)
        return TtsDialectUpdate(city=birth_city, source="birth_city", changed=True)

    lifetime_city = extract_lifetime_city(normalized_text)
    if not lifetime_city:
        return TtsDialectUpdate()
    if _NEGATIVE_RE.search(normalized_text):
        return TtsDialectUpdate()
    if _POSITIVE_RE.search(normalized_text):
        _set_dialect_city(state, lifetime_city, "liked_lifetime_city")
        _write_state(account_store, account_id, state)
        return TtsDialectUpdate(city=lifetime_city, source="liked_lifetime_city", changed=True)
    _set_pending_lifetime_city(state, lifetime_city, normalized_text)
    _write_state(account_store, account_id, state)
    return TtsDialectUpdate(
        city=lifetime_city,
        source="lifetime_city_pending",
        pending=True,
        reply_text=f"Du hast {lifetime_city} als Ort genannt, an dem du viel Lebenszeit verbracht hast. Mochtest du es dort? Dann nutze ich fuer Sprachnachrichten eine leichte regionale Faerbung von dort.",
    )


def voice_instructions_for_account(instructions: BotInstructions, account_store: AccountStore | None, account_id: str) -> BotInstructions:
    city = tts_dialect_city(account_store, account_id)
    voice = tts_voice_for_account(account_store, account_id, instructions)
    mimic_profile, mimic_position = tts_mimic_voice_profile(account_store, account_id)
    if not city and not voice and not mimic_profile:
        return instructions
    adjusted = copy(instructions)
    if city or mimic_profile:
        adjusted.openai_voice_instructions = _compose_voice_instructions(
            instructions.openai_voice_instructions,
            city=city,
            mimic_profile=mimic_profile,
            mimic_position=mimic_position,
        )
    if voice:
        adjusted.openai_voice = voice
    return adjusted


def tts_dialect_city(account_store: AccountStore | None, account_id: str) -> str:
    if account_store is None or not account_id:
        return ""
    try:
        state = account_store.read_agent_state(account_id)
    except (AccountStoreError, OSError, ValueError):
        return ""
    dialect_state = state.get(TTS_DIALECT_STATE_KEY)
    if not isinstance(dialect_state, dict):
        return ""
    return str(dialect_state.get("city") or "").strip()


def handle_tts_voice_model_command(
    account_store: AccountStore,
    account_id: str,
    text: str,
    instructions: BotInstructions,
) -> TtsVoiceCommandResult:
    parts = str(text or "").strip().split(maxsplit=1)
    argument = parts[1].strip() if len(parts) > 1 else ""
    if not argument:
        current = tts_voice_for_account(account_store, account_id, instructions) or instructions.openai_voice
        voices = ", ".join(available_openai_tts_voices(instructions))
        return TtsVoiceCommandResult(
            "Aktuelle Stimme: {current}\n"
            "Nutzung: /voicemodel <stimme>, z.B. /voicemodel onyx. Mit /voicemodel reset nutzt du wieder den Instanz-Default.\n"
            "OpenAI-Voices: {voices}\n"
            "Doku: {url}".format(current=current, voices=voices, url=OPENAI_TTS_VOICE_DOCS_URL)
        )
    normalized = normalize_openai_tts_voice(argument)
    if normalized is None:
        voices = ", ".join(available_openai_tts_voices(instructions))
        return TtsVoiceCommandResult(
            "Diese OpenAI-Stimme kenne ich fuer den aktuellen Voice-Provider nicht: {voice}\n"
            "Verfuegbar: {voices}\n"
            "Doku: {url}".format(voice=argument, voices=voices, url=OPENAI_TTS_VOICE_DOCS_URL)
        )
    if not normalized:
        changed = clear_tts_voice_preference(account_store, account_id)
        return TtsVoiceCommandResult(
            "Okay, fuer Sprachnachrichten nutze ich wieder den Instanz-Default: {voice}\nDoku: {url}".format(
                voice=instructions.openai_voice,
                url=OPENAI_TTS_VOICE_DOCS_URL,
            ),
            changed=changed,
        )
    if normalized not in available_openai_tts_voices(instructions):
        voices = ", ".join(available_openai_tts_voices(instructions))
        return TtsVoiceCommandResult(
            "Die Stimme {voice} passt nicht zum aktuell eingestellten OpenAI-Voice-Modell {model}.\n"
            "Verfuegbar: {voices}\n"
            "Doku: {url}".format(
                voice=normalized,
                model=instructions.openai_voice_model,
                voices=voices,
                url=OPENAI_TTS_VOICE_DOCS_URL,
            )
        )
    set_tts_voice_preference(account_store, account_id, normalized, provider="openai")
    return TtsVoiceCommandResult(
        "Okay, fuer deine Sprachnachrichten nutze ich jetzt die OpenAI-Stimme {voice}.\nDoku: {url}".format(
            voice=normalized,
            url=OPENAI_TTS_VOICE_DOCS_URL,
        ),
        changed=True,
        voice=normalized,
    )


def handle_tts_mimic_voice_command(
    account_store: AccountStore,
    account_id: str,
    text: str,
    instructions: BotInstructions,
) -> TtsMimicVoiceCommandResult:
    del instructions
    parts = str(text or "").strip().split(maxsplit=1)
    argument = re.sub(r"[^a-zA-Z0-9_äöüÄÖÜß-]+", "", parts[1].strip().casefold()) if len(parts) > 1 else ""
    state = account_store.read_agent_state(account_id)
    mimic_state = _mimic_state(state)

    if not argument:
        enabled = bool(mimic_state.get("enabled"))
        position = _normalize_mimic_position(str(mimic_state.get("position") or "")) or TTS_MIMIC_POSITION_AFTER_DIALECT
        profile = _mimic_profile_from_state(mimic_state)
        status = "aktiv" if enabled else "aus"
        position_text = "vor dem Dialekt" if position == TTS_MIMIC_POSITION_BEFORE_DIALECT else "nach dem Dialekt"
        if profile:
            return TtsMimicVoiceCommandResult(
                f"Sprechweisen-Nachahmung: {status}, Einordnung: {position_text}.\n"
                f"Aktuelles Profil: {profile}\n"
                "Nutzung: /mimic_voice on|off|before|after|reset",
                enabled=enabled,
                position=position,
            )
        return TtsMimicVoiceCommandResult(
            f"Sprechweisen-Nachahmung: {status}, Einordnung: {position_text}.\n"
            "Ich verbessere das Profil aus deinen Sprachnachrichten, sobald Transkripte vorliegen.\n"
            "Nutzung: /mimic_voice on|off|before|after|reset",
            enabled=enabled,
            position=position,
        )

    if argument in {"on", "ein", "enable", "aktivieren", "an"}:
        _set_mimic_enabled(mimic_state, True)
        _write_state(account_store, account_id, state)
        return TtsMimicVoiceCommandResult(
            "Okay, ich nutze fuer TTS eine leichte Sprechweisen-Nachahmung aus deinen Sprachnachrichten.",
            changed=True,
            enabled=True,
            position=str(mimic_state.get("position") or TTS_MIMIC_POSITION_AFTER_DIALECT),
        )
    if argument in {"off", "aus", "disable", "deaktivieren"}:
        _set_mimic_enabled(mimic_state, False)
        _write_state(account_store, account_id, state)
        return TtsMimicVoiceCommandResult(
            "Okay, ich nutze die Sprechweisen-Nachahmung fuer TTS nicht mehr.",
            changed=True,
            enabled=False,
            position=str(mimic_state.get("position") or TTS_MIMIC_POSITION_AFTER_DIALECT),
        )
    position = _normalize_mimic_position(argument)
    if position:
        _set_mimic_enabled(mimic_state, True)
        mimic_state["position"] = position
        mimic_state["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _write_state(account_store, account_id, state)
        position_text = "vor dem Dialekt" if position == TTS_MIMIC_POSITION_BEFORE_DIALECT else "nach dem Dialekt"
        return TtsMimicVoiceCommandResult(
            f"Okay, ich setze die Sprechweisen-Nachahmung {position_text}.",
            changed=True,
            enabled=True,
            position=position,
        )
    if argument in {"reset", "clear", "loeschen", "löschen"}:
        changed = TTS_MIMIC_VOICE_STATE_KEY in state
        state.pop(TTS_MIMIC_VOICE_STATE_KEY, None)
        _write_state(account_store, account_id, state)
        return TtsMimicVoiceCommandResult(
            "Okay, ich habe das gespeicherte Sprechweisen-Profil geloescht.",
            changed=changed,
            enabled=False,
        )

    return TtsMimicVoiceCommandResult("Nutzung: /mimic_voice on|off|before|after|reset")


def record_tts_voice_style_observation(
    account_store: AccountStore | None,
    account_id: str,
    transcript: str,
    *,
    duration_seconds: float | int | None = None,
) -> bool:
    if account_store is None or not account_id:
        return False
    with account_store.account_memory_lock(account_id):
        return _record_tts_voice_style_observation_unlocked(
            account_store,
            account_id,
            transcript,
            duration_seconds=duration_seconds,
        )


def _record_tts_voice_style_observation_unlocked(
    account_store: AccountStore,
    account_id: str,
    transcript: str,
    *,
    duration_seconds: float | int | None = None,
) -> bool:
    analysis = _analyze_voice_style(transcript, duration_seconds=duration_seconds)
    if not analysis:
        return False
    state = account_store.read_agent_state(account_id)
    mimic_state = _mimic_state(state)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    mimic_state.setdefault("schema_version", 1)
    mimic_state.setdefault("enabled", False)
    mimic_state.setdefault("position", TTS_MIMIC_POSITION_AFTER_DIALECT)
    mimic_state["observations_count"] = _safe_nonnegative_int(mimic_state.get("observations_count")) + 1
    mimic_state["updated_at"] = now
    mimic_state["last_observed_at"] = now
    label_counts = mimic_state.setdefault("label_counts", {})
    if not isinstance(label_counts, dict):
        label_counts = {}
        mimic_state["label_counts"] = label_counts
    for label in analysis["labels"]:
        label_counts[label] = _safe_nonnegative_int(label_counts.get(label)) + 1
    if analysis.get("words_per_minute") is not None:
        previous = _safe_finite_float(mimic_state.get("avg_words_per_minute"))
        wpm = float(analysis["words_per_minute"])
        mimic_state["avg_words_per_minute"] = round(wpm if previous is None else (previous * 0.7 + wpm * 0.3), 1)
    mimic_state["last_analysis"] = {
        "labels": analysis["labels"],
        "word_count": analysis["word_count"],
        "duration_seconds": analysis.get("duration_seconds"),
        "words_per_minute": analysis.get("words_per_minute"),
    }
    account_store.write_agent_state(account_id, state)
    return True


def tts_mimic_voice_profile(account_store: AccountStore | None, account_id: str) -> tuple[str, str]:
    if account_store is None or not account_id:
        return "", TTS_MIMIC_POSITION_AFTER_DIALECT
    try:
        state = account_store.read_agent_state(account_id)
    except (AccountStoreError, OSError, ValueError):
        return "", TTS_MIMIC_POSITION_AFTER_DIALECT
    mimic_state = state.get(TTS_MIMIC_VOICE_STATE_KEY)
    if not isinstance(mimic_state, dict) or not _coerce_bool(mimic_state.get("enabled")):
        return "", TTS_MIMIC_POSITION_AFTER_DIALECT
    return _mimic_profile_from_state(mimic_state), _normalize_mimic_position(str(mimic_state.get("position") or "")) or TTS_MIMIC_POSITION_AFTER_DIALECT


def tts_voice_for_account(account_store: AccountStore | None, account_id: str, instructions: BotInstructions) -> str:
    if account_store is None or not account_id:
        return ""
    try:
        state = account_store.read_agent_state(account_id)
    except (AccountStoreError, OSError, ValueError):
        return ""
    voice_state = state.get(TTS_VOICE_STATE_KEY)
    if not isinstance(voice_state, dict):
        return ""
    provider = str(voice_state.get("provider") or "openai").strip().casefold()
    if provider != "openai":
        return ""
    voice = normalize_openai_tts_voice(str(voice_state.get("voice") or ""))
    if not voice or voice not in available_openai_tts_voices(instructions):
        return ""
    return voice


def set_tts_voice_preference(account_store: AccountStore, account_id: str, voice: str, *, provider: str = "openai") -> None:
    state = account_store.read_agent_state(account_id)
    state[TTS_VOICE_STATE_KEY] = {
        "schema_version": 1,
        "provider": provider,
        "voice": voice,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "docs_url": OPENAI_TTS_VOICE_DOCS_URL,
    }
    account_store.write_agent_state(account_id, state)


def clear_tts_voice_preference(account_store: AccountStore, account_id: str) -> bool:
    state = account_store.read_agent_state(account_id)
    if TTS_VOICE_STATE_KEY not in state:
        return False
    state.pop(TTS_VOICE_STATE_KEY, None)
    account_store.write_agent_state(account_id, state)
    return True


def normalize_openai_tts_voice(value: str) -> str | None:
    normalized = re.sub(r"[^a-z0-9_-]+", "", str(value or "").strip().casefold())
    normalized = OPENAI_TTS_VOICE_ALIASES.get(normalized, normalized)
    if normalized == "":
        return ""
    if normalized in OPENAI_TTS_VOICES:
        return normalized
    return None


def available_openai_tts_voices(instructions: BotInstructions) -> tuple[str, ...]:
    model = str(instructions.openai_voice_model or "").strip().casefold()
    if model in {"tts-1", "tts-1-hd"}:
        return OPENAI_LEGACY_TTS_VOICES
    return OPENAI_TTS_VOICES


def extract_birth_city(text: str) -> str:
    return _extract_city(text, _BIRTH_CITY_PATTERNS)


def extract_lifetime_city(text: str) -> str:
    return _extract_city(text, _LIFETIME_CITY_PATTERNS)


def _compose_voice_instructions(base: str, *, city: str, mimic_profile: str, mimic_position: str) -> str:
    parts: list[str] = [str(base or "").strip()]
    dialect = _dialect_voice_instruction_text(city) if city else ""
    mimic = _mimic_voice_instruction_text(mimic_profile) if mimic_profile else ""
    if mimic_position == TTS_MIMIC_POSITION_BEFORE_DIALECT:
        parts.extend([mimic, dialect])
    else:
        parts.extend([dialect, mimic])
    return "\n".join(part for part in parts if part)


def _dialect_voice_instructions(base: str, city: str) -> str:
    prefix = str(base or "").strip()
    return "\n".join(part for part in (prefix, _dialect_voice_instruction_text(city)) if part)


def _dialect_voice_instruction_text(city: str) -> str:
    return (
        f"Nutze fuer diesen Account statt der globalen Dialektvorgabe eine leichte bis mittelleichte regionale "
        f"Faerbung aus der Gegend von {city}. Sprich weiterhin natuerlich, gut verstaendlich und nicht karikierend."
    )


def _mimic_voice_instruction_text(profile: str) -> str:
    return (
        "Passe die Sprachausgabe leicht an die beobachtete Sprechweise des Users an: "
        f"{profile}. Bleibe gut verstaendlich, ruhig hilfreich und ueberzeichne die Nachahmung nicht."
    )


def _mimic_state(state: dict[str, Any]) -> dict[str, Any]:
    mimic_state = state.setdefault(TTS_MIMIC_VOICE_STATE_KEY, {})
    if not isinstance(mimic_state, dict):
        mimic_state = {}
        state[TTS_MIMIC_VOICE_STATE_KEY] = mimic_state
    mimic_state.setdefault("schema_version", 1)
    mimic_state["enabled"] = _coerce_bool(mimic_state.get("enabled"))
    mimic_state.setdefault("position", TTS_MIMIC_POSITION_AFTER_DIALECT)
    return mimic_state


def _set_mimic_enabled(mimic_state: dict[str, Any], enabled: bool) -> None:
    mimic_state["schema_version"] = 1
    mimic_state["enabled"] = enabled
    mimic_state.setdefault("position", TTS_MIMIC_POSITION_AFTER_DIALECT)
    mimic_state["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize_mimic_position(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_äöüß-]+", "", str(value or "").strip().casefold())
    if normalized in {"before", "pre", "vor", "before_dialect", "vordialekt", "vor_dialekt"}:
        return TTS_MIMIC_POSITION_BEFORE_DIALECT
    if normalized in {"after", "post", "nach", "after_dialect", "nachdialekt", "nach_dialekt"}:
        return TTS_MIMIC_POSITION_AFTER_DIALECT
    return ""


def _mimic_profile_from_state(mimic_state: dict[str, Any]) -> str:
    label_counts = mimic_state.get("label_counts")
    labels: list[str] = []
    if isinstance(label_counts, dict):
            labels = [
            str(label)
            for label, _count in sorted(
                label_counts.items(),
                key=lambda item: (-_safe_nonnegative_int(item[1]), str(item[0])),
            )
            if str(label).strip() and _safe_nonnegative_int(_count) > 0
        ][:5]
    if not labels:
        last_analysis = mimic_state.get("last_analysis")
        if isinstance(last_analysis, dict):
            raw_labels = last_analysis.get("labels")
            if isinstance(raw_labels, list):
                labels = [str(label) for label in raw_labels if str(label).strip()][:5]
    avg_wpm = _safe_finite_float(mimic_state.get("avg_words_per_minute"))
    if avg_wpm is not None and not any("spricht" in label for label in labels):
        labels.insert(0, _speed_label(avg_wpm))
    return "; ".join(dict.fromkeys(labels))


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on", "ein", "aktiv"}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value == 1
    return False


def _safe_nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _safe_finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _analyze_voice_style(transcript: str, *, duration_seconds: float | int | None = None) -> dict[str, Any]:
    text = str(transcript or "").strip()
    words = re.findall(r"\b[\wÄÖÜäöüß'-]+\b", text, flags=re.UNICODE)
    if len(words) < 2:
        return {}
    labels: list[str] = []
    duration = _clean_duration(duration_seconds)
    wpm: float | None = None
    if duration:
        wpm = round(len(words) / (duration / 60.0), 1)
        labels.append(_speed_label(wpm))
    fillers = re.findall(r"\b(?:aeh|äh|aehm|ähm|hm|hmm|also|halt|irgendwie|quasi)\b", text, flags=re.IGNORECASE)
    if len(fillers) >= 2:
        labels.append("nutzt mehrere Fuelllaute oder Suchwoerter")
    if re.search(r"\b(?:angst|aengstlich|ängstlich|nervoes|nervös|panik|unsicher|sorry|entschuldigung|vielleicht|ich weiss nicht|ich weiß nicht)\b", text, re.IGNORECASE):
        labels.append("wirkt sprachlich leicht unsicher oder aengstlich")
    if re.search(r"(?:\[|\()(?:unverstaendlich|unverständlich|nuschelt|undeutlich)(?:\]|\))", text, re.IGNORECASE) or text.count("...") >= 2:
        labels.append("wirkt stellenweise undeutlich oder nuschelnd")
    dialect_label = _dialect_hint_label(text)
    if dialect_label:
        labels.append(dialect_label)
    if not labels:
        labels.append("spricht in gut verstaendlichem neutralem Deutsch")
    return {
        "labels": list(dict.fromkeys(labels)),
        "word_count": len(words),
        "duration_seconds": duration,
        "words_per_minute": wpm,
    }


def _clean_duration(duration_seconds: float | int | None) -> float | None:
    try:
        duration = float(duration_seconds) if duration_seconds is not None else 0.0
    except (TypeError, ValueError):
        return None
    if duration <= 0:
        return None
    return min(duration, 60.0 * 30.0)


def _speed_label(words_per_minute: float) -> str:
    if words_per_minute >= 210:
        return "spricht sehr schnell und hastig"
    if words_per_minute >= 170:
        return "spricht schnell"
    if words_per_minute <= 90:
        return "spricht langsam und bedaechtig"
    return "spricht in mittlerem Tempo"


def _dialect_hint_label(text: str) -> str:
    if re.search(r"\b(?:isch|nischt|gugg|nu|nue|nü|bidde)\b", text, re.IGNORECASE):
        return "zeigt moeglicherweise einen leichten saechsischen Einschlag"
    if re.search(r"\b(?:servus|fei|gell|ned|net|mei|bissi)\b", text, re.IGNORECASE):
        return "zeigt moeglicherweise einen leichten sueddeutschen Einschlag"
    if re.search(r"\b(?:moin|dat|wat|nich|nech)\b", text, re.IGNORECASE):
        return "zeigt moeglicherweise einen leichten norddeutschen Einschlag"
    return ""


def _extract_city(text: str, patterns: tuple[re.Pattern[str], ...]) -> str:
    for pattern in patterns:
        match = pattern.search(text)
        if not match:
            continue
        city = _clean_city(match.group("city"))
        if city:
            return city
    return ""


def _clean_city(value: str) -> str:
    city = re.split(r"\s+(?:und|aber|weil|denn|wo|als|seit|dort|da)\b", str(value or "").strip(), maxsplit=1, flags=re.IGNORECASE)[0]
    city = re.sub(r"[.,;:!?]+$", "", city.strip())
    city = re.sub(r"\s+", " ", city)[:80]
    if re.search(r"(?i)\b(?:nicht(?:\s+mehr)?|kein(?:e|er|em|en)?|mein(?:e|er|em|en)?|ein(?:e|er|em|en)?)\b", city):
        return ""
    return city


def _pending_lifetime_city(state: dict[str, Any]) -> dict[str, Any] | None:
    dialect_state = state.get(TTS_DIALECT_STATE_KEY)
    if not isinstance(dialect_state, dict):
        return None
    pending = dialect_state.get("pending_lifetime_city")
    return pending if isinstance(pending, dict) else None


def _set_dialect_city(state: dict[str, Any], city: str, source: str) -> None:
    dialect_state = state.setdefault(TTS_DIALECT_STATE_KEY, {})
    if not isinstance(dialect_state, dict):
        dialect_state = {}
        state[TTS_DIALECT_STATE_KEY] = dialect_state
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    dialect_state["schema_version"] = 1
    dialect_state["city"] = city
    dialect_state["source"] = source
    dialect_state["updated_at"] = timestamp
    dialect_state["voice_instructions"] = _dialect_voice_instructions("", city)
    dialect_state.pop("pending_lifetime_city", None)


def _set_pending_lifetime_city(state: dict[str, Any], city: str, original_text: str) -> None:
    dialect_state = state.setdefault(TTS_DIALECT_STATE_KEY, {})
    if not isinstance(dialect_state, dict):
        dialect_state = {}
        state[TTS_DIALECT_STATE_KEY] = dialect_state
    dialect_state["schema_version"] = 1
    dialect_state["pending_lifetime_city"] = {
        "city": city,
        "asked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "original_text": original_text[:400],
    }


def _clear_pending_lifetime_city(state: dict[str, Any]) -> None:
    dialect_state = state.get(TTS_DIALECT_STATE_KEY)
    if isinstance(dialect_state, dict):
        dialect_state.pop("pending_lifetime_city", None)


def _write_state(account_store: AccountStore, account_id: str, state: dict[str, Any]) -> None:
    account_store.write_agent_state(account_id, state)
