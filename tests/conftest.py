"""Pytest collection rules for the Plan-3 runtime scaffold.

The Plan-3 branch replaces the legacy monolithic TeeBotus modules with the
channel-neutral runtime scaffold. Legacy tests that import removed modules stay in
the tree for reference, but full pytest collection must not fail on modules that
are intentionally absent in this branch.
"""

collect_ignore = [
    "test_bot.py",
    "test_handlers.py",
    "test_instructions.py",
    "test_openai_client.py",
    "test_youtube_parser_misses_report.py",
    "test_youtube_parser_stats.py",
]
