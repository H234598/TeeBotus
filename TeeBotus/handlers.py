from __future__ import annotations

from pathlib import Path
from typing import Any

from .core.program_history import build_program_history_reply
from .instructions import BotInstructions, render_template

DEFAULT_INSTRUCTIONS = BotInstructions()
HELP_TEXT = DEFAULT_INSTRUCTIONS.help_text()


def build_reply(
    message: dict[str, Any],
    instructions: BotInstructions | None = None,
    include_fallback: bool = True,
    project_root: Path | None = None,
) -> str | None:
    instructions = instructions or DEFAULT_INSTRUCTIONS
    text = str(message.get("text") or "").strip()
    if not text:
        return None

    command = _normalize_command(text)
    if command == "/start":
        return render_template(instructions.start, message, text)
    if command == "/help":
        return instructions.help_text()
    if command == "/chatid":
        chat_id = message.get("chat", {}).get("id")
        template = instructions.chatid if chat_id is not None else instructions.chatid_missing
        return render_template(template, message, text)
    if is_program_history_request(text):
        return build_program_history_reply(project_root)
    if command in instructions.commands:
        return render_template(instructions.commands[command], message, text)
    if text.startswith("/"):
        return render_template(instructions.unknown_command, message, text)

    text_key = text.casefold()
    if text_key in instructions.text_replies:
        return render_template(instructions.text_replies[text_key], message, text)

    for needle, reply in instructions.contains_replies.items():
        if needle in text_key:
            return render_template(reply, message, text)

    if include_fallback and instructions.echo_enabled:
        return f"{instructions.echo_prefix}{text}"
    return None


def should_use_openai(message: dict[str, Any], instructions: BotInstructions | None = None) -> bool:
    instructions = instructions or DEFAULT_INSTRUCTIONS
    text = str(message.get("text") or "").strip()
    if not text or text.startswith("/"):
        return False
    return instructions.openai_enabled and build_reply(message, instructions, include_fallback=False) is None


def is_program_history_request(text: str) -> bool:
    command = _normalize_command(text)
    if command in {"/history", "/programmhistorie", "/commits", "/changelog", "/neuigkeiten"}:
        return True
    normalized = _normalize_history_text(text)
    needles = (
        "programmhistorie",
        "programm historie",
        "programmaenderungen",
        "programmanderungen",
        "programm anderungen",
        "programm aenderungen",
        "neue features",
        "neues feature",
        "neue funktionen",
        "was ist neu",
        "was wurde geaendert",
        "was wurde geandert",
        "aenderungen am bot",
        "anderungen am bot",
        "github commits",
        "commit historie",
        "commithistorie",
        "release notes",
        "releases",
        "changelog",
    )
    return any(needle in normalized for needle in needles)


def _normalize_command(text: str) -> str:
    command = text.split(maxsplit=1)[0].lower()
    if "@" in command:
        command = command.split("@", maxsplit=1)[0]
    return command


def _normalize_history_text(text: str) -> str:
    return (
        text.casefold()
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
