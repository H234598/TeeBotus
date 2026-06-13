from __future__ import annotations

from typing import Any

from .instructions import BotInstructions, render_template

DEFAULT_INSTRUCTIONS = BotInstructions()
HELP_TEXT = DEFAULT_INSTRUCTIONS.help_text()


def build_reply(
    message: dict[str, Any],
    instructions: BotInstructions | None = None,
    include_fallback: bool = True,
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


def _normalize_command(text: str) -> str:
    command = text.split(maxsplit=1)[0].lower()
    if "@" in command:
        command = command.split("@", maxsplit=1)[0]
    return command
