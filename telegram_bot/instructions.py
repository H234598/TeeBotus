from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("telegram_bot.instructions")

DEFAULT_COMMANDS = {
    "/ping": "pong",
}

DEFAULT_HELP_LINES = (
    "/start - Bot starten",
    "/help - Hilfe anzeigen",
    "/ping - Verbindung testen",
    "/chatid - aktuelle Chat-ID anzeigen",
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
    openai_transcription_enabled: bool = True
    openai_transcription_model: str = "gpt-4o-mini-transcribe"
    openai_transcription_fallback_model: str = "whisper-1"
    openai_transcription_language: str = "de"
    openai_transcription_prompt: str = "Transkribiere deutschsprachige Telegram-Sprachnachrichten wortgetreu."
    openai_transcription_error: str = "Ich konnte die Sprachnachricht gerade nicht transkribieren. Bitte versuche es gleich nochmal."
    openai_transcription_empty: str = "Ich konnte in der Sprachnachricht keinen Text erkennen."
    openai_error: str = "Ich kann die OpenAI API gerade nicht erreichen. Bitte versuche es gleich nochmal."
    openai_missing_key: str = "OpenAI ist aktiviert, aber OPENAI_API_KEY ist nicht gesetzt."
    openai_reset: str = "Der OpenAI-Verlauf fuer diesen Chat wurde geloescht."
    delete_last_success: str = "Letzte Bot-Nachricht geloescht."
    delete_empty: str = "Ich habe fuer diesen Chat keine Bot-Nachricht gespeichert, die ich loeschen kann."
    delete_error: str = "Ich konnte die Bot-Nachricht nicht loeschen. In Gruppen brauche ich dafuer passende Adminrechte."
    cleanup_success: str = "{count} Bot-Nachrichten geloescht."
    cleanup_usage: str = "Nutzung: /cleanup 10"
    user_memory_enabled: bool = False
    user_memory_dir: str = "instances/{instance}/data/users"
    user_memory_max_prompt_chars: int = 12000
    user_memory_max_entry_chars: int = 2000
    openai_system_prompt: str = (
        "Du bist ein hilfreicher Telegram-Bot.\n"
        "Antworte auf Deutsch, klar und eher kurz.\n"
        "Wenn du etwas nicht sicher weisst, sage das offen."
    )
    commands: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_COMMANDS))
    text_replies: dict[str, str] = field(default_factory=dict)
    contains_replies: dict[str, str] = field(default_factory=dict)
    help_lines: tuple[str, ...] = DEFAULT_HELP_LINES

    def help_text(self) -> str:
        return "\n".join([self.help_title, *self.help_lines])

    def openai_instructions_text(self) -> str:
        parts = [self.openai_system_prompt.strip()]
        if self.openai_rule_text.strip():
            parts.extend(
                [
                    f"Zusaetzliches Grundregelwerk aus {self.openai_rule_file}:",
                    self.openai_rule_text.strip(),
                ]
            )
        return "\n\n".join(part for part in parts if part)


class InstructionStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._signature: tuple[int | None, int | None, str] | None = None
        self._instructions = BotInstructions()

    def get(self) -> BotInstructions:
        if not self.path.exists():
            if self._signature is not None:
                LOGGER.warning("Instruction file %s disappeared; using defaults.", self.path)
            self._signature = None
            self._instructions = BotInstructions()
            return self._instructions

        signature = _instruction_signature(self.path, self._instructions)
        if signature != self._signature:
            self._instructions = load_instructions(self.path)
            self._signature = _instruction_signature(self.path, self._instructions)
            LOGGER.info("Loaded bot instructions from %s", self.path)

        return self._instructions


def load_instructions(path: str | Path) -> BotInstructions:
    path = Path(path)
    if not path.exists():
        return BotInstructions()
    instructions = parse_instructions(path.read_text(encoding="utf-8"))
    instructions.openai_rule_text = _load_rule_text(path, instructions.openai_rule_file)
    return instructions


def _instruction_signature(path: Path, instructions: BotInstructions) -> tuple[int | None, int | None, str]:
    rule_path = _resolve_rule_path(path, instructions.openai_rule_file)
    return (_mtime_ns(path), _mtime_ns(rule_path), str(rule_path) if rule_path else "")


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


def parse_instructions(markdown: str) -> BotInstructions:
    instructions = BotInstructions()
    commands = dict(DEFAULT_COMMANDS)
    text_replies: dict[str, str] = {}
    contains_replies: dict[str, str] = {}
    help_lines: list[str] | None = None
    system_prompt_lines: list[str] | None = None
    section = ""

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line and section != "system_prompt":
            continue
        if line.startswith("#"):
            section = _section_name(line)
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
        elif section == "memory":
            _apply_memory_setting(instructions, key, value)
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
    if system_prompt_lines is not None:
        instructions.openai_system_prompt = "\n".join(system_prompt_lines).strip()
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
    elif normalized == "delete_last_success":
        instructions.delete_last_success = value
    elif normalized == "delete_empty":
        instructions.delete_empty = value
    elif normalized == "delete_error":
        instructions.delete_error = value
    elif normalized == "cleanup_success":
        instructions.cleanup_success = value
    elif normalized == "cleanup_usage":
        instructions.cleanup_usage = value


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
