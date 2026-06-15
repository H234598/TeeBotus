from __future__ import annotations

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bsyt_[A-Za-z0-9_=-]{12,}\b"),
)
ALLOWED_PLACEHOLDER_PARTS = (
    "replace",
    "optional",
    "fallback",
    "token",
    "first",
    "second",
    "example",
    "test",
    "signal-channel",
    "instance-slot",
    "proactive",
)
SKIP_DIRS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "reports",
}
TEXT_SUFFIXES = {
    ".cfg",
    ".env",
    ".example",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}


def test_repository_contains_no_real_looking_secrets() -> None:
    findings: list[str] = []
    for path in _iter_text_files(PROJECT_ROOT):
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in SECRET_PATTERNS:
            for match in pattern.finditer(text):
                token = match.group(0)
                if _allowed_placeholder(token):
                    continue
                findings.append(f"{path.relative_to(PROJECT_ROOT)}:{_line_number(text, match.start())}:{token[:10]}...")

    assert findings == []


def _iter_text_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.suffix in TEXT_SUFFIXES or path.name == ".env.example":
            yield path


def _allowed_placeholder(token: str) -> bool:
    lowered = token.casefold()
    return any(part in lowered for part in ALLOWED_PLACEHOLDER_PARTS)


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1
