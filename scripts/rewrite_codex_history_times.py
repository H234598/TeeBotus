#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from TeeBotus.admin.codex_history import main as codex_history_main  # noqa: E402
from TeeBotus.runtime.dotenv import load_dotenv_defaults  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    _load_dotenv(REPO_ROOT / ".env")
    args = list(sys.argv[1:] if argv is None else argv)
    return codex_history_main(["rewrite-times", *args])


def _load_dotenv(path: Path) -> None:
    load_dotenv_defaults(path)


if __name__ == "__main__":
    raise SystemExit(main())
