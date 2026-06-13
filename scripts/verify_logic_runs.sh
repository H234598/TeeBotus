#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

QUIET=1
if [[ "${1:-}" == "--verbose" ]]; then
  QUIET=0
fi

run() {
  local name="$1"
  shift
  if [[ "$QUIET" -eq 1 ]]; then
    local log
    log="$(mktemp)"
    if "$@" >"$log" 2>&1; then
      rm -f "$log"
    else
      printf 'FAILED: %s\n' "$name" >&2
      cat "$log" >&2
      rm -f "$log"
      return 1
    fi
  else
    printf 'RUN: %s\n' "$name"
    "$@"
  fi
}

run "1/20 full pytest" python3 -m pytest
run "2/20 compileall" python3 -m compileall -q TeeBotus tests
run "3/20 diff check" git diff --check
run "4/20 runtime env invariants" python3 - <<'PY'
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
from TeeBotus.bot import _load_dotenv, _load_runtime_config_defaults, _read_runtime_config_defaults

with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    dotenv = root / ".env"
    defaults = root / "ALL_BOTS_DEFAULT.md"
    dotenv.write_text('TELEGRAM_BOT_INSTANCE="FromDotenv"\nTELEGRAM_BOT_TOKEN=dotenv-token\n', encoding="utf-8")
    defaults.write_text(
        "## Laufzeitkonfiguration\n"
        "- TELEGRAM_BOT_INSTANCE: FromMarkdown\n"
        "- LOG_LEVEL: DEBUG\n"
        "- TELEGRAM_BOT_INSTANCES: leer\n",
        encoding="utf-8",
    )
    with patch.dict(os.environ, {"TELEGRAM_BOT_INSTANCE": "FromEnv"}, clear=True):
        _load_dotenv(dotenv)
        _load_runtime_config_defaults(defaults)
        assert os.environ["TELEGRAM_BOT_INSTANCE"] == "FromEnv"
        assert os.environ["TELEGRAM_BOT_TOKEN"] == "dotenv-token"
        assert os.environ["LOG_LEVEL"] == "DEBUG"
        assert "TELEGRAM_BOT_INSTANCES" not in os.environ
    parsed = _read_runtime_config_defaults(defaults)
    assert parsed == {"TELEGRAM_BOT_INSTANCE": "FromMarkdown", "LOG_LEVEL": "DEBUG"}
PY
run "5/20 instruction invariants" python3 - <<'PY'
from TeeBotus.instructions import load_instructions, parse_instructions

wrapped = parse_instructions(
    """
## OpenAI
- voice_instructions: Satz eins.
Satz zwei.
- model: model-x

## Hilfe
- /a - Anfang.
Fortsetzung.
"""
)
assert wrapped.openai_voice_instructions == "Satz eins. Satz zwei."
assert wrapped.openai_model == "model-x"
assert wrapped.help_lines == ("/a - Anfang. Fortsetzung.",)

for path in ["instances/Bote_der_Wahrheit/Bot_Verhalten.md", "instances/Depressionsbot/Bot_Verhalten.md"]:
    ins = load_instructions(path)
    text = ins.openai_instructions_text()
    assert ins.openai_system_prompt.strip()
    assert text.strip()
    assert "Zusaetzliches Grundregelwerk" in text
    assert "Security-Antwort" in text
PY
run "6/20 instance token invariants" python3 - <<'PY'
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
from TeeBotus.bot import (
    _bot_token_config_error,
    _discover_instance_names,
    _resolve_bot_token_configs,
    _resolve_openai_api_keys,
    _resolve_telegram_tokens,
)

with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    for name in ["B", "A"]:
        p = root / name
        p.mkdir()
        (p / "Bot_Verhalten.md").write_text("", encoding="utf-8")
    (root / "Ignored").mkdir()
    with patch.dict(os.environ, {"TELEGRAM_BOT_INSTANCES_DIR": str(root)}, clear=True):
        assert _discover_instance_names() == ["A", "B"]
    env = {
        "TELEGRAM_BOT_TOKENS_DEMO": "ta,tb",
        "TELEGRAM_BOT_TOKEN_DEMO_2": "tb",
        "TELEGRAM_BOT_TOKEN_DEMO_3": "tc",
        "OPENAI_API_KEYS_DEMO": "ka,kb",
        "OPENAI_API_KEY_DEMO_3": "kc",
    }
    with patch.dict(os.environ, env, clear=True):
        assert _resolve_telegram_tokens("Demo") == ["ta", "tb", "tc"]
        assert _resolve_openai_api_keys("Demo", 3) == ["ka", "kb", "kc"]
        configs = _resolve_bot_token_configs("Demo")
        assert [(c.label, c.token, c.openai_api_key) for c in configs] == [
            ("1", "ta", "ka"),
            ("2", "tb", "kb"),
            ("3", "tc", "kc"),
        ]
        assert _bot_token_config_error(configs) == ""
PY
run "7/20 openai client and handlers" python3 -m pytest -q tests/test_openai_client.py tests/test_handlers.py
run "8/20 bot split multipart token instance config" python3 -m pytest -q tests/test_bot.py -k "split or multipart or token or instance or config or dotenv or runtime"
run "9/20 memory crypto paths" bash -c 'python3 -m pytest -q tests/test_bot.py -k "memory or crypto or passphrase or avatar or reset" && python3 scripts/migrate_user_memory_encryption.py --verify-only --quiet'
run "10/20 youtube subprocess paths" python3 -m pytest -q tests/test_bot.py -k "youtube or transcript or subprocess or process or registry or priority"
run "10b/20 youtube parser stats" bash -c 'python3 scripts/youtube_parser_stats.py --json >/tmp/teebotus-youtube-parser-stats.json && python3 scripts/youtube_parser_misses_report.py --instances-dir instances --json >/tmp/teebotus-youtube-parser-misses.json && python3 -m pytest -q tests/test_youtube_parser_stats.py tests/test_youtube_parser_misses_report.py'
run "11/20 voice transcription openai flow" python3 -m pytest -q tests/test_bot.py -k "voice or transcription or openai or source"
run "12/20 commands update handling" python3 -m pytest -q tests/test_bot.py -k "handle or command or cleanup or delete or call or chatid or status"
run "13/20 static config references" python3 - <<'PY'
from pathlib import Path

checks = [
    ("TeeBotus/bot.py", "DOTENV_RUNTIME_KEYS"),
    ("README.md", "DOTENV_RUNTIME_KEYS"),
    ("tests/test_bot.py", "DOTENV_RUNTIME_KEYS"),
]
for file_name, needle in checks:
    text = Path(file_name).read_text(encoding="utf-8")
    assert needle not in text, f"{needle} still referenced in {file_name}"
for file_name in ["ALL_BOTS_DEFAULT.md", "README.md"]:
    text = Path(file_name).read_text(encoding="utf-8")
    assert "Laufzeitkonfiguration" in text or "Runtime" in text
PY
run "14/20 ast parse" python3 - <<'PY'
import ast
from pathlib import Path

for root in [Path("TeeBotus"), Path("tests")]:
    for path in root.rglob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
PY
run "15/20 section continuation matrix" python3 - <<'PY'
from TeeBotus.instructions import parse_instructions

md = """
## Antworten
- start: Hallo.
Weiter.
- unknown_command: Nein.

## Befehle
- /x: X.
Weiter X.

## Textantworten
- hi: Hallo.
Weiter Hallo.

## Enthaelt
- foo: Bar.
Weiter Bar.

## Einstellungen
- echo_prefix: Echo:
Weiter Prefix.
"""
ins = parse_instructions(md)
assert ins.start == "Hallo. Weiter."
assert ins.unknown_command == "Nein."
assert ins.commands["/x"] == "X. Weiter X."
assert ins.text_replies["hi"] == "Hallo. Weiter Hallo."
assert ins.contains_replies["foo"] == "Bar. Weiter Bar."
assert ins.echo_prefix == "Echo: Weiter Prefix."
PY
run "16/20 runtime parser edge matrix" python3 - <<'PY'
import tempfile
from pathlib import Path
from TeeBotus.bot import _read_runtime_config_defaults

with tempfile.TemporaryDirectory() as d:
    path = Path(d) / "ALL_BOTS_DEFAULT.md"
    path.write_text(
        """
## Laufzeitkonfiguration
- LOG_LEVEL: INFO:extra
- TELEGRAM_BOT_TOKEN_<INSTANCE>: nope
- TELEGRAM_BOT_INSTANCE: all
- lower_key: no
- OPENAI_API_KEY: leer

## OpenAI
- model: ignored
""",
        encoding="utf-8",
    )
    parsed = _read_runtime_config_defaults(path)
assert parsed == {"LOG_LEVEL": "INFO:extra", "TELEGRAM_BOT_INSTANCE": "all"}
PY
run "17/20 module imports" python3 - <<'PY'
import importlib

for name in [
    "TeeBotus.bot",
    "TeeBotus.handlers",
    "TeeBotus.instructions",
    "TeeBotus.openai_client",
    "TeeBotus.user_memory_crypto",
]:
    importlib.import_module(name)
PY
run "18/20 full pytest repeat" python3 -m pytest
run "19/20 compile status gate" bash -c 'python3 -m compileall -q TeeBotus tests && git diff --check && test -z "$(git status --short)"'
run "20/20 final smoke and remote parity" bash -c 'python3 - <<'"'"'PY'"'"'
from pathlib import Path
from TeeBotus.bot import _read_runtime_config_defaults
from TeeBotus.instructions import load_instructions

runtime = _read_runtime_config_defaults(Path("ALL_BOTS_DEFAULT.md"))
assert runtime.get("TELEGRAM_BOT_INSTANCE") == "all"
assert runtime.get("LOG_LEVEL") == "INFO"
for path in ["instances/Bote_der_Wahrheit/Bot_Verhalten.md", "instances/Depressionsbot/Bot_Verhalten.md"]:
    ins = load_instructions(path)
    assert ins.openai_model
    assert ins.help_text().startswith("Befehle:")
PY
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)"'

if [[ "$QUIET" -eq 1 ]]; then
  printf 'All 20 verification runs passed.\n'
fi
