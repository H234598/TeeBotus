from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from telegram_bot.bot import _resolve_instance_name, _resolve_instruction_path, _resolve_openai_api_key
from telegram_bot.instructions import load_instructions
from telegram_bot.openai_client import OpenAIClient, OpenAIAPIError


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", maxsplit=1)
        os.environ.setdefault(key.strip(), value.strip())


def main() -> int:
    load_dotenv(ROOT / ".env")
    instance_name = _resolve_instance_name()
    api_key = _resolve_openai_api_key(instance_name)
    if not api_key:
        print(f"OPENAI_API_KEY for instance {instance_name} is not set.", file=sys.stderr)
        return 2

    instructions = load_instructions(ROOT / _resolve_instruction_path(instance_name))
    if instructions.openai_service_tier != "flex":
        print(f"BOT.md requests service_tier={instructions.openai_service_tier!r}, expected 'flex'.", file=sys.stderr)
        return 3

    try:
        response = OpenAIClient(api_key).create_reply("Antworte nur mit: ok", instructions)
    except OpenAIAPIError as exc:
        print(f"OpenAI validation failed: {exc}", file=sys.stderr)
        return 4

    if response.service_tier != "flex":
        print(f"Flex validation failed: API reported service_tier={response.service_tier!r}.", file=sys.stderr)
        return 5

    print(f"Flex processing validated: service_tier={response.service_tier}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
