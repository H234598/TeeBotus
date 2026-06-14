"""Command line entry point for TeeBotus.

This module must stay tiny and must keep delegating to ``TeeBotus.bot.main`` so
existing starts such as ``python3 -m TeeBotus`` and ``python3 -m TeeBotus --all``
continue to work while the Plan-3 runtime is integrated additively.
"""

from __future__ import annotations

from .bot import main


if __name__ == "__main__":
    raise SystemExit(main())
