from __future__ import annotations

import re
from copy import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from TeeBotus.instructions import BotInstructions
from TeeBotus.runtime.accounts import AccountStore, AccountStoreError

TTS_DIALECT_STATE_KEY = "tts_dialect"
TTS_VOICE_STATE_KEY = "tts_voice"
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
    re.compile(rf"\b(?:geboren|geb\.)\s+(?:in|bei)\s+{_CITY_PATTERN}", re.IGNORECASE),
    re.compile(rf"\b(?:meine\s+geburtsstadt|mein\s+geburtsort)\s+(?:ist|heisst|heißt|war)\s+{_CITY_PATTERN}", re.IGNORECASE),
)
_LIFETIME_CITY_PATTERNS = (
    re.compile(rf"\b(?:die\s+)?(?:meiste|laengste|längste)\s+zeit\s+(?:meines\s+lebens\s+)?(?:habe\s+ich\s+)?(?:in|bei)\s+{_CITY_PATTERN}\s+(?:gelebt|verbracht|gewohnt)\b", re.IGNORECASE),
    re.compile(rf"\b(?:ich\s+)?(?:habe\s+)?(?:den\s+)?(?:groessten|größten|grossen|großen)\s+teil\s+meines\s+lebens\s+(?:in|bei)\s+{_CITY_PATTERN}\s+(?:gelebt|verbracht|gewohnt)\b", re.IGNORECASE),
    re.compile(rf"\b(?:ich\s+)?(?:habe\s+)?(?:fast\s+)?mein\s+ganzes\s+leben\s+(?:in|bei)\s+{_CITY_PATTERN}\s+(?:gelebt|verbracht|gewohnt)\b", re.IGNORECASE),
)
_POSITIVE_RE = re.compile(r"\b(mochte|mag|liebte|liebe|gern|gerne|schoen|schön|gut|heimat|zuhause|wohlgefuehlt|wohlgefühlt)\b", re.IGNORECASE)
_NEGATIVE_RE = re.compile(r"\b(nicht\s+mochte|mochte\s+.{0,40}\s+nicht|nicht\s+mag|mag\s+.{0,40}\s+nicht|hasste|hass|schlimm|furchtbar|ungern|nie\s+gemocht)\b", re.IGNORECASE)
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


def maybe_update_tts_dialect_preference(account_store: AccountStore, account_id: str, text: str) -> TtsDialectUpdate:
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
        if city and _YES_RE.search(normalized_text):
            _set_dialect_city(state, city, "lifetime_city_confirmed")
            _write_state(account_store, account_id, state)
            return TtsDialectUpdate(city=city, source="lifetime_city_confirmed", changed=True, reply_text=f"Okay, fuer Sprachnachrichten nutze ich ab jetzt eine leichte regionale Faerbung aus {city}.")
        if _NO_RE.search(normalized_text):
            _clear_pending_lifetime_city(state)
            _write_state(account_store, account_id, state)
            return TtsDialectUpdate(reply_text="Okay, dann aendere ich den TTS-Dialekt nicht.")

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
    if not city and not voice:
        return instructions
    adjusted = copy(instructions)
    if city:
        adjusted.openai_voice_instructions = _dialect_voice_instructions(instructions.openai_voice_instructions, city)
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


def _dialect_voice_instructions(base: str, city: str) -> str:
    prefix = str(base or "").strip()
    dialect = (
        f"Nutze fuer diesen Account statt der globalen Dialektvorgabe eine leichte bis mittelleichte regionale "
        f"Faerbung aus der Gegend von {city}. Sprich weiterhin natuerlich, gut verstaendlich und nicht karikierend."
    )
    return "\n".join(part for part in (prefix, dialect) if part)


def _extract_city(text: str, patterns: tuple[re.Pattern[str], ...]) -> str:
    for pattern in patterns:
        match = pattern.search(text)
        if not match:
            continue
        return _clean_city(match.group("city"))
    return ""


def _clean_city(value: str) -> str:
    city = re.split(r"\s+(?:und|aber|weil|denn|wo|als|seit|dort|da)\b", str(value or "").strip(), maxsplit=1, flags=re.IGNORECASE)[0]
    city = re.sub(r"[.,;:!?]+$", "", city.strip())
    return re.sub(r"\s+", " ", city)[:80]


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
