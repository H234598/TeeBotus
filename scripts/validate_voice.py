from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from TeeBotus.bot import _resolve_instance_name, _resolve_instruction_path, _resolve_openai_api_key
from TeeBotus.instructions import load_instructions
from TeeBotus.openai_client import OpenAIAPIError, OpenAIClient


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
    try:
        voice = OpenAIClient(api_key).create_voice("Test der Sprachausgabe.", instructions)
    except OpenAIAPIError as exc:
        print(f"OpenAI voice validation failed: {exc}", file=sys.stderr)
        return 3

    if not voice.audio:
        print("OpenAI voice validation failed: empty audio.", file=sys.stderr)
        return 4

    print(f"Voice generation validated: {voice.filename}, {voice.content_type}, {len(voice.audio)} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
