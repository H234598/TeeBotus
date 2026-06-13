from __future__ import annotations

import json
import logging
import re
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("telegram_bot.instructions")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALL_BOTS_DEFAULT_FILENAME = "ALL_BOTS_DEFAULT.md"
EASTER_EGGS_FILENAME = "EASTER_EGGS.json"

DEFAULT_COMMANDS = {
    "/ping": "pong",
}

DEFAULT_HELP_LINES = (
    "/start - Bot starten",
    "/help - Hilfe anzeigen",
    "/ping - Verbindung testen",
    "/status - Status anzeigen",
    "/codex Prompt - fuehrt Codex CLI lokal aus",
    "/voice Text - Text als Sprachnachricht senden. Ohne Text nutzt /voice den Text der beantworteten Nachricht.",
    "/youtube_transcript URL - YouTube-Untertitel laden oder per lokalem Whisper transkribieren",
    "/chatid - aktuelle Chat-ID anzeigen",
    "/reset - setzt nur den OpenAI-Verlauf dieses Chats zurueck. Memory und Telegram-Nachrichten bleiben erhalten.",
    "/reset_memorys - fragt nach und loescht danach nur deine eigenen User-Memory-Eintraege.",
    "/Call_a_Teladi - Send Teladi a emergency message",
    "/cleanup N - loescht die letzten N seit Bot-Start gemerkten Nachrichten in diesem Chat.",
    "/cleanup all - loescht alle seit Bot-Start gemerkten Nachrichten in diesem Chat.",
)


@dataclass
class BotInstructions:
    start: str = "Hallo{name_suffix}. Ich bin bereit. Sende /help fuer die Befehle."
    help_title: str = "Befehle:"
    chatid: str = "Chat-ID: {chat_id}"
    chatid_missing: str = "Keine Chat-ID gefunden."
    unknown_command: str = "Diesen Befehl kenne ich nicht. Sende /help fuer die verfuegbaren Befehle."
    echo_enabled: bool = True
    echo_prefix: str = "Echo: "
    openai_enabled: bool = False
    openai_model: str = "gpt-5.5"
    openai_service_tier: str = ""
    openai_rule_file: str = "Bot_Rüstzeug.md"
    openai_rule_text: str = ""
    openai_web_search: bool = False
    openai_web_search_context_size: str = "medium"
    openai_web_search_required: bool = False
    openai_max_output_tokens: int | None = 700
    openai_timeout_seconds: int = 900
    openai_reasoning_effort: str = "low"
    openai_verbosity: str = "low"
    openai_voice_enabled: bool = True
    openai_voice_model: str = "gpt-4o-mini-tts"
    openai_voice: str = "alloy"
    openai_voice_format: str = "opus"
    openai_voice_speed: float = 1.0
    openai_voice_max_input_chars: int = 4096
    openai_voice_instructions: str = "Sprich natuerlich, ruhig und gut verstaendlich auf Deutsch."
    openai_auto_voice_enabled: bool = True
    openai_auto_voice_every: int = 3
    openai_auto_voice_max_words: int = 50
    openai_auto_voice_skip_sources: bool = True
    openai_voice_usage: str = "Nutzung: /voice Text fuer die Sprachnachricht"
    openai_voice_too_long: str = "Der Text ist zu lang fuer eine Sprachnachricht. Maximum: {max_chars} Zeichen."
    openai_voice_error: str = "Ich konnte die Sprachnachricht gerade nicht erzeugen. Bitte versuche es gleich nochmal."
    codex_enabled: bool = True
    codex_allowed_sender_ids: tuple[str, ...] = ("395935293",)
    codex_timeout_seconds: int = 300
    codex_usage: str = "Nutzung: /codex Prompt"
    codex_unauthorized: str = "Nein."
    codex_not_found: str = "Codex CLI wurde nicht gefunden."
    codex_error: str = "Codex konnte gerade nicht ausgefuehrt werden: {error}"
    codex_empty: str = "Codex hat keine Ausgabe erzeugt."
    openai_transcription_enabled: bool = True
    openai_transcription_model: str = "gpt-4o-mini-transcribe"
    openai_transcription_fallback_model: str = "whisper-1"
    openai_transcription_language: str = "de"
    openai_transcription_prompt: str = "Transkribiere deutschsprachige Telegram-Sprachnachrichten wortgetreu."
    openai_transcription_error: str = "Ich konnte die Sprachnachricht gerade nicht transkribieren. Bitte versuche es gleich nochmal."
    openai_transcription_empty: str = "Ich konnte in der Sprachnachricht keinen Text erkennen."
    openai_error: str = "Ich kann die OpenAI API gerade nicht erreichen. Bitte versuche es gleich nochmal."
    openai_missing_key: str = "OpenAI ist aktiviert, aber OPENAI_API_KEY ist nicht gesetzt."
    openai_reset: str = (
        "Der OpenAI-Verlauf fuer diesen Chat wurde geloescht. "
        "Das betrifft nur den Antwortkontext fuer OpenAI in diesem Chat; Telegram-Nachrichten und User-Memory bleiben erhalten."
    )
    delete_empty: str = (
        "Ich habe fuer diesen Chat keine gespeicherte Nachricht, die ich loeschen kann. "
        "/cleanup N und /cleanup all arbeiten mit den seit dem letzten Bot-Start gemerkten Nachrichten in diesem Chat."
    )
    delete_error: str = (
        "Ich konnte die Bot-Nachricht nicht loeschen. "
        "In Gruppen brauche ich dafuer passende Adminrechte; OpenAI-Verlauf und User-Memory bleiben dabei erhalten."
    )
    cleanup_success: str = (
        "{count} gespeicherte Nachrichten geloescht. "
        "Das entfernt die gemerkten Telegram-Nachrichten aus diesem Chat; OpenAI-Verlauf und User-Memory bleiben erhalten."
    )
    cleanup_usage: str = (
        "Nutzung: /cleanup all. "
        "Damit loesche ich alle seit dem letzten Bot-Start gemerkten Nachrichten aus diesem Chat."
    )
    user_memory_reset_confirm: str = (
        "Soll ich deine gespeicherten User-Memory-Eintraege wirklich loeschen? "
        "Das betrifft nur deine eigenen Memory-Eintraege; OpenAI-Verlauf, Telegram-Nachrichten und admingepflegte interne Hinweise bleiben erhalten. "
        "Antworte mit Ja zum Loeschen oder Nein zum Abbrechen."
    )
    user_memory_reset_success: str = (
        "Deine gespeicherten User-Memory-Eintraege wurden geloescht. "
        "OpenAI-Verlauf, Telegram-Nachrichten und admingepflegte interne Hinweise bleiben erhalten."
    )
    user_memory_reset_cancelled: str = "Okay, ich loesche nichts. Deine User-Memory-Eintraege bleiben erhalten."
    user_memory_reset_unavailable: str = (
        "Fuer dich ist kein User-Memory aktiv. Es wurden keine Telegram-Nachrichten und kein OpenAI-Verlauf geloescht."
    )
    user_memory_reset_error: str = "Ich konnte deine User-Memory-Eintraege gerade nicht loeschen. Bitte versuche es spaeter erneut."
    user_memory_reset_only_own: str = (
        "Ich kann nur deine eigenen Erinnerungen loeschen, nicht fremde Erinnerungen oder das Instanz-Arbeitsgedaechtnis. "
        "Das Instanz-/Arbeitsgedaechtnis enthaelt keine userbezogenen Daten."
    )
    teladi_call_prompt: str = "Welche Emergency Message soll ich an Teladi schicken? Deine naechste Antwort wird 1:1 weitergeleitet."
    teladi_call_sent: str = "Emergency Message wurde an Teladi gesendet."
    teladi_call_cooldown: str = "Du kannst /Call_a_Teladi erst in {remaining} wieder nutzen."
    teladi_call_error: str = "Ich konnte die Emergency Message gerade nicht senden. Bitte versuche es spaeter erneut."
    user_memory_enabled: bool = False
    user_memory_dir: str = "instances/{instance}/data/users"
    user_memory_max_prompt_chars: int = 12000
    user_memory_max_entry_chars: int = 2000
    openai_shared_prompt: str = ""
    openai_system_prompt: str = (
        "Du bist ein hilfreicher Telegram-Bot.\n"
        "Antworte auf Deutsch, klar und eher kurz.\n"
        "Wenn du etwas nicht sicher weisst, sage das offen."
    )
    security_answer_short: str = ""
    security_answer_full: str = ""
    security_answer_easter_egg: str = ""
    commands: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_COMMANDS))
    text_replies: dict[str, str] = field(default_factory=dict)
    contains_replies: dict[str, str] = field(default_factory=dict)
    help_lines: tuple[str, ...] = DEFAULT_HELP_LINES

    def help_text(self) -> str:
        return "\n".join([self.help_title, *self.help_lines])

    def openai_instructions_text(self) -> str:
        parts = [self.openai_shared_prompt.strip(), self.openai_system_prompt.strip()]
        if self.openai_rule_text.strip():
            parts.extend(
                [
                    f"Zusaetzliches Grundregelwerk aus {self.openai_rule_file}:",
                    self.openai_rule_text.strip(),
                ]
            )
        security_templates = _security_templates_text(self)
        if security_templates:
            parts.append(security_templates)
        return "\n\n".join(part for part in parts if part)


class InstructionStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._signature: tuple[int | None, int | None, str, int | None, int | None] | None = None
        self._instructions = BotInstructions()

    def get(self) -> BotInstructions:
        if not self.path.exists():
            if self._signature is not None:
                LOGGER.warning("Instruction file %s disappeared; using defaults.", self.path)
            self._signature = None
            self._instructions = load_instructions(self.path)
            return self._instructions

        signature = _instruction_signature(self.path, self._instructions)
        if signature != self._signature:
            self._instructions = load_instructions(self.path)
            self._signature = _instruction_signature(self.path, self._instructions)
            LOGGER.info("Loaded bot instructions from %s", self.path)

        return self._instructions


def load_instructions(path: str | Path) -> BotInstructions:
    path = Path(path)
    default_instructions = _load_default_instructions()
    if not path.exists():
        return default_instructions
    instructions = parse_instructions(path.read_text(encoding="utf-8"), base=default_instructions)
    instructions.openai_rule_text = _load_rule_text(path, instructions.openai_rule_file)
    return instructions


def _instruction_signature(path: Path, instructions: BotInstructions) -> tuple[int | None, int | None, str, int | None, int | None]:
    rule_path = _resolve_rule_path(path, instructions.openai_rule_file)
    default_path = _default_instruction_path()
    easter_eggs_path = _easter_eggs_path()
    return (
        _mtime_ns(path),
        _mtime_ns(rule_path),
        str(rule_path) if rule_path else "",
        _mtime_ns(default_path),
        _mtime_ns(easter_eggs_path),
    )


def _default_instruction_path() -> Path:
    return PROJECT_ROOT / ALL_BOTS_DEFAULT_FILENAME


def _easter_eggs_path() -> Path:
    return PROJECT_ROOT / EASTER_EGGS_FILENAME


def _load_default_instructions() -> BotInstructions:
    path = _default_instruction_path()
    if not path.exists():
        instructions = BotInstructions()
    else:
        instructions = parse_instructions(path.read_text(encoding="utf-8"))
    _apply_easter_eggs(instructions, _easter_eggs_path())
    return instructions


def _apply_easter_eggs(instructions: BotInstructions, path: Path) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except json.JSONDecodeError as exc:
        LOGGER.warning("Could not parse Easter egg file %s: %s", path, exc)
        return
    if not isinstance(payload, dict):
        LOGGER.warning("Ignoring Easter egg file %s because the root value is not an object.", path)
        return
    security = payload.get("security")
    if isinstance(security, dict):
        value = security.get("easter_egg")
        if isinstance(value, str) and value.strip():
            instructions.security_answer_easter_egg = value


def _mtime_ns(path: Path | None) -> int | None:
    if path is None:
        return None
    try:
        return path.stat().st_mtime_ns
    except FileNotFoundError:
        return None


def _load_rule_text(instruction_path: Path, rule_file: str) -> str:
    rule_path = _resolve_rule_path(instruction_path, rule_file)
    if rule_path is None:
        return ""
    try:
        return rule_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        LOGGER.debug("Configured OpenAI rule file %s does not exist.", rule_path)
        return ""


def _resolve_rule_path(instruction_path: Path, rule_file: str) -> Path | None:
    value = rule_file.strip()
    if not value or value.casefold() in {"none", "null", "off", "aus"}:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    return instruction_path.parent / path


def parse_instructions(markdown: str, *, base: BotInstructions | None = None) -> BotInstructions:
    instructions = deepcopy(base) if base is not None else BotInstructions()
    commands = dict(instructions.commands)
    text_replies: dict[str, str] = dict(instructions.text_replies)
    contains_replies: dict[str, str] = dict(instructions.contains_replies)
    help_lines: list[str] | None = None
    shared_prompt_lines: list[str] | None = None
    system_prompt_lines: list[str] | None = None
    section = ""

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line and section != "system_prompt":
            continue
        if line.startswith("#"):
            next_section = _section_name(line)
            if next_section:
                section = next_section
                continue
            if section not in {"shared_prompt", "system_prompt"}:
                section = ""
                continue
        if section == "shared_prompt":
            if shared_prompt_lines is None:
                shared_prompt_lines = []
            shared_prompt_lines.append(line)
            continue
        if section == "system_prompt":
            if system_prompt_lines is None:
                system_prompt_lines = []
            system_prompt_lines.append(line)
            continue

        item = _strip_bullet(line)
        if not item:
            continue

        if section == "help":
            if help_lines is None:
                help_lines = []
            help_lines.append(item)
            continue

        pair = _parse_pair(item)
        if pair is None:
            continue

        key, value = pair
        if section == "settings":
            _apply_setting(instructions, key, value)
        elif section == "replies":
            _apply_reply(instructions, key, value)
        elif section == "openai":
            _apply_openai_setting(instructions, key, value)
        elif section == "codex":
            _apply_codex_setting(instructions, key, value)
        elif section == "memory":
            _apply_memory_setting(instructions, key, value)
        elif section == "security_answers":
            _apply_security_answer(instructions, key, value)
        elif section == "commands":
            commands[_normalize_command_name(key)] = value
        elif section == "text_replies":
            text_replies[key.casefold()] = value
        elif section == "contains_replies":
            contains_replies[key.casefold()] = value

    instructions.commands = commands
    instructions.text_replies = text_replies
    instructions.contains_replies = contains_replies
    if help_lines is not None:
        instructions.help_lines = tuple(help_lines)
    if shared_prompt_lines is not None:
        instructions.openai_shared_prompt = "\n".join(shared_prompt_lines).strip()
    if system_prompt_lines is not None:
        system_prompt = "\n".join(system_prompt_lines).strip()
        if base is not None and base.openai_system_prompt.strip():
            instructions.openai_system_prompt = "\n\n".join(
                part for part in (system_prompt, base.openai_system_prompt.strip()) if part
            )
        else:
            instructions.openai_system_prompt = system_prompt
    return instructions


def render_template(template: str, message: dict[str, Any], text: str = "", extra: dict[str, Any] | None = None) -> str:
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    sender = message.get("from") if isinstance(message.get("from"), dict) else {}
    first_name = str(sender.get("first_name") or "").strip()
    last_name = str(sender.get("last_name") or "").strip()
    username = str(sender.get("username") or "").strip()
    context = _SafeContext(
        {
            "text": text,
            "chat_id": chat.get("id", ""),
            "first_name": first_name,
            "last_name": last_name,
            "username": username,
            "name_suffix": f", {first_name}" if first_name else "",
        }
    )
    if extra:
        context.update(extra)
    try:
        return template.format_map(context)
    except ValueError:
        return template


class _SafeContext(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return ""


def _section_name(line: str) -> str:
    heading = line.lstrip("#").strip().casefold()
    aliases = {
        "einstellungen": "settings",
        "settings": "settings",
        "antworten": "replies",
        "replies": "replies",
        "openai": "openai",
        "befehle": "commands",
        "commands": "commands",
        "systemprompt": "system_prompt",
        "system prompt": "system_prompt",
        "system_prompt": "system_prompt",
        "prompt": "shared_prompt",
        "defaultprompt": "shared_prompt",
        "default prompt": "shared_prompt",
        "global prompt": "shared_prompt",
        "all bots prompt": "shared_prompt",
        "gemeinsamer prompt": "shared_prompt",
        "securityantworten": "security_answers",
        "security antworten": "security_answers",
        "security answers": "security_answers",
        "datenschutzantworten": "security_answers",
        "privacy answers": "security_answers",
        "codex": "codex",
        "textantworten": "text_replies",
        "text replies": "text_replies",
        "exact text replies": "text_replies",
        "enthaelt": "contains_replies",
        "enthält": "contains_replies",
        "contains": "contains_replies",
        "contains replies": "contains_replies",
        "memory": "memory",
        "gedaechtnis": "memory",
        "gedächtnis": "memory",
        "speicher": "memory",
        "hilfe": "help",
        "help": "help",
    }
    return aliases.get(heading, "")


def _strip_bullet(line: str) -> str:
    for marker in ("- ", "* "):
        if line.startswith(marker):
            return line[len(marker) :].strip()
    return line


def _parse_pair(line: str) -> tuple[str, str] | None:
    for separator in ("=", ":"):
        if separator in line:
            key, value = line.split(separator, maxsplit=1)
            key = key.strip()
            value = _clean_value(value)
            if key:
                return key, value
    return None


def _clean_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return value.replace("\\n", "\n")


def _apply_setting(instructions: BotInstructions, key: str, value: str) -> None:
    normalized = _normalize_key(key)
    if normalized == "echo":
        instructions.echo_enabled = _parse_bool(value, default=instructions.echo_enabled)
    elif normalized == "echo_prefix":
        instructions.echo_prefix = value


def _apply_reply(instructions: BotInstructions, key: str, value: str) -> None:
    normalized = _normalize_key(key)
    if normalized == "start":
        instructions.start = value
    elif normalized == "help_title":
        instructions.help_title = value
    elif normalized == "chatid":
        instructions.chatid = value
    elif normalized == "chatid_missing":
        instructions.chatid_missing = value
    elif normalized == "unknown_command":
        instructions.unknown_command = value
    elif normalized == "echo_prefix":
        instructions.echo_prefix = value
    elif normalized == "delete_empty":
        instructions.delete_empty = value
    elif normalized == "delete_error":
        instructions.delete_error = value
    elif normalized == "cleanup_success":
        instructions.cleanup_success = value
    elif normalized == "cleanup_usage":
        instructions.cleanup_usage = value
    elif normalized == "user_memory_reset_confirm":
        instructions.user_memory_reset_confirm = value
    elif normalized == "user_memory_reset_success":
        instructions.user_memory_reset_success = value
    elif normalized == "user_memory_reset_cancelled":
        instructions.user_memory_reset_cancelled = value
    elif normalized == "user_memory_reset_unavailable":
        instructions.user_memory_reset_unavailable = value
    elif normalized == "user_memory_reset_error":
        instructions.user_memory_reset_error = value
    elif normalized == "user_memory_reset_only_own":
        instructions.user_memory_reset_only_own = value
    elif normalized == "teladi_call_prompt":
        instructions.teladi_call_prompt = value
    elif normalized == "teladi_call_sent":
        instructions.teladi_call_sent = value
    elif normalized == "teladi_call_cooldown":
        instructions.teladi_call_cooldown = value
    elif normalized == "teladi_call_error":
        instructions.teladi_call_error = value
    elif normalized == "codex_usage":
        instructions.codex_usage = value
    elif normalized == "codex_unauthorized":
        instructions.codex_unauthorized = value
    elif normalized == "codex_not_found":
        instructions.codex_not_found = value
    elif normalized == "codex_error":
        instructions.codex_error = value
    elif normalized == "codex_empty":
        instructions.codex_empty = value


def _apply_openai_setting(instructions: BotInstructions, key: str, value: str) -> None:
    normalized = _normalize_key(key)
    if normalized == "enabled":
        instructions.openai_enabled = _parse_bool(value, default=instructions.openai_enabled)
    elif normalized == "model":
        instructions.openai_model = value
    elif normalized == "service_tier":
        instructions.openai_service_tier = value
    elif normalized == "rule_file":
        instructions.openai_rule_file = value
    elif normalized == "web_search":
        instructions.openai_web_search = _parse_bool(value, default=instructions.openai_web_search)
    elif normalized == "web_search_context_size":
        instructions.openai_web_search_context_size = value
    elif normalized == "web_search_required":
        instructions.openai_web_search_required = _parse_bool(value, default=instructions.openai_web_search_required)
    elif normalized == "max_output_tokens":
        instructions.openai_max_output_tokens = _parse_optional_int(value, default=instructions.openai_max_output_tokens)
    elif normalized == "timeout_seconds":
        instructions.openai_timeout_seconds = _parse_required_int(value, default=instructions.openai_timeout_seconds)
    elif normalized == "reasoning_effort":
        instructions.openai_reasoning_effort = value
    elif normalized == "verbosity":
        instructions.openai_verbosity = value
    elif normalized == "voice_enabled":
        instructions.openai_voice_enabled = _parse_bool(value, default=instructions.openai_voice_enabled)
    elif normalized == "voice_model":
        instructions.openai_voice_model = value
    elif normalized == "voice":
        instructions.openai_voice = value
    elif normalized == "voice_format":
        instructions.openai_voice_format = value
    elif normalized == "voice_speed":
        instructions.openai_voice_speed = _parse_float(value, default=instructions.openai_voice_speed)
    elif normalized == "voice_max_input_chars":
        instructions.openai_voice_max_input_chars = _parse_required_int(value, default=instructions.openai_voice_max_input_chars)
    elif normalized == "voice_instructions":
        instructions.openai_voice_instructions = value
    elif normalized == "auto_voice_enabled":
        instructions.openai_auto_voice_enabled = _parse_bool(value, default=instructions.openai_auto_voice_enabled)
    elif normalized == "auto_voice_every":
        instructions.openai_auto_voice_every = _parse_required_int(value, default=instructions.openai_auto_voice_every)
    elif normalized == "auto_voice_max_words":
        instructions.openai_auto_voice_max_words = _parse_required_int(value, default=instructions.openai_auto_voice_max_words)
    elif normalized == "auto_voice_skip_sources":
        instructions.openai_auto_voice_skip_sources = _parse_bool(value, default=instructions.openai_auto_voice_skip_sources)
    elif normalized == "voice_usage":
        instructions.openai_voice_usage = value
    elif normalized == "voice_too_long":
        instructions.openai_voice_too_long = value
    elif normalized == "voice_error":
        instructions.openai_voice_error = value
    elif normalized == "transcription_enabled":
        instructions.openai_transcription_enabled = _parse_bool(value, default=instructions.openai_transcription_enabled)
    elif normalized == "transcription_model":
        instructions.openai_transcription_model = value
    elif normalized == "transcription_fallback_model":
        instructions.openai_transcription_fallback_model = value
    elif normalized == "transcription_language":
        instructions.openai_transcription_language = value
    elif normalized == "transcription_prompt":
        instructions.openai_transcription_prompt = value
    elif normalized == "transcription_error":
        instructions.openai_transcription_error = value
    elif normalized == "transcription_empty":
        instructions.openai_transcription_empty = value
    elif normalized == "error":
        instructions.openai_error = value
    elif normalized == "missing_key":
        instructions.openai_missing_key = value
    elif normalized == "reset":
        instructions.openai_reset = value


def _apply_codex_setting(instructions: BotInstructions, key: str, value: str) -> None:
    normalized = _normalize_key(key)
    if normalized == "enabled":
        instructions.codex_enabled = _parse_bool(value, default=instructions.codex_enabled)
    elif normalized == "allowed_sender_ids":
        instructions.codex_allowed_sender_ids = tuple(_parse_id_list(value))
    elif normalized == "timeout_seconds":
        instructions.codex_timeout_seconds = _parse_required_int(value, default=instructions.codex_timeout_seconds)


def _apply_memory_setting(instructions: BotInstructions, key: str, value: str) -> None:
    normalized = _normalize_key(key)
    if normalized == "enabled":
        instructions.user_memory_enabled = _parse_bool(value, default=instructions.user_memory_enabled)
    elif normalized in {"directory", "dir", "path"}:
        instructions.user_memory_dir = value
    elif normalized == "max_prompt_chars":
        instructions.user_memory_max_prompt_chars = _parse_required_int(value, default=instructions.user_memory_max_prompt_chars)
    elif normalized == "max_entry_chars":
        instructions.user_memory_max_entry_chars = _parse_required_int(value, default=instructions.user_memory_max_entry_chars)


def _apply_security_answer(instructions: BotInstructions, key: str, value: str) -> None:
    normalized = _normalize_key(key)
    if normalized in {"short", "kurz", "security_answer_short"}:
        instructions.security_answer_short = value
    elif normalized in {"full", "voll", "detailed", "ausfuehrlich", "security_answer_full"}:
        instructions.security_answer_full = value
    elif normalized in {"easter_egg", "easteregg", "witz", "security_answer_easter_egg"}:
        instructions.security_answer_easter_egg = value


def _security_templates_text(instructions: BotInstructions) -> str:
    entries = [
        ("Kurze Security-Antwort", instructions.security_answer_short),
        ("Ausfuehrliche Security-Antwort", instructions.security_answer_full),
        ("Klar als erfundener Witz markiertes Security-Easter-Egg", instructions.security_answer_easter_egg),
    ]
    lines: list[str] = []
    for title, value in entries:
        if value.strip():
            lines.extend([f"{title}:", value.strip()])
    if not lines:
        return ""
    return "Editierbare Antwortvorlagen fuer Datenschutz- und Security-Fragen:\n" + "\n\n".join(lines)


def _normalize_key(key: str) -> str:
    return key.strip().casefold().replace("-", "_").replace(" ", "_")


def _normalize_command_name(command: str) -> str:
    command = command.strip().split(maxsplit=1)[0].casefold()
    if "@" in command:
        command = command.split("@", maxsplit=1)[0]
    if not command.startswith("/"):
        command = f"/{command}"
    return command


def _parse_bool(value: str, default: bool) -> bool:
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "ja", "on", "an"}:
        return True
    if normalized in {"0", "false", "no", "nein", "off", "aus"}:
        return False
    return default


def _parse_id_list(value: str) -> list[str]:
    if not value.strip():
        return []
    parts = [part.strip() for part in re.split(r"[,\n]", value) if part.strip()]
    return parts


def _parse_optional_int(value: str, default: int | None) -> int | None:
    normalized = value.strip().casefold()
    if normalized in {"", "none", "null", "aus", "off"}:
        return None
    try:
        parsed = int(normalized)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _parse_required_int(value: str, default: int) -> int:
    try:
        parsed = int(value.strip())
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _parse_float(value: str, default: float) -> float:
    try:
        parsed = float(value.strip())
    except ValueError:
        return default
    return parsed if parsed > 0 else default
