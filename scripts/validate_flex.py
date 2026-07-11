from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from TeeBotus.bot import _resolve_instance_name, _resolve_instruction_path, _resolve_openai_api_key  # noqa: E402
from TeeBotus.instructions import load_instructions  # noqa: E402
from TeeBotus.openai_client import OpenAIClient, OpenAIAPIError  # noqa: E402
from TeeBotus.runtime.dotenv import load_dotenv_defaults  # noqa: E402


def load_dotenv(path: Path) -> None:
    load_dotenv_defaults(path)


def main() -> int:
    load_dotenv(ROOT / ".env")
    instance_name = _resolve_instance_name()
    api_key = _resolve_openai_api_key(instance_name)
    if not api_key:
        print(f"OPENAI_API_KEY for instance {instance_name} is not set.", file=sys.stderr)
        return 2

    instructions = load_instructions(ROOT / _resolve_instruction_path(instance_name))
    if instructions.openai_service_tier != "flex":
        print(f"Bot_Verhalten.md requests service_tier={instructions.openai_service_tier!r}, expected 'flex'.", file=sys.stderr)
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
