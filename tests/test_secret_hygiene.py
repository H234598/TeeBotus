from __future__ import annotations

import re
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bsyt_[A-Za-z0-9_=-]{12,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{12,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bhf_[A-Za-z0-9]{12,}\b"),
    re.compile(r"\bgsk_[A-Za-z0-9]{12,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
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
FORBIDDEN_TRACKED_PATH_PATTERNS = (
    re.compile(r"(^|/)\.env($|\.)"),
    re.compile(r"(^|/)instances/"),
    re.compile(r"(^|/)data/"),
    re.compile(r"(^|/)Account_(Index|Identities|Keyring|Secrets|Memory)\.(json|sqlite3?)$"),
    re.compile(r"(^|/)User_Memory_(Entries|Index)\.jsonl?$"),
    re.compile(r"\.(sqlite3?|db)$"),
    re.compile(r"\.(pem|key)$"),
)
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


def test_git_index_does_not_track_runtime_secret_or_memory_paths() -> None:
    tracked = subprocess.check_output(["git", "ls-files"], cwd=PROJECT_ROOT, text=True).splitlines()
    findings = []
    for path in tracked:
        if path == ".env.example":
            continue
        if any(pattern.search(path) for pattern in FORBIDDEN_TRACKED_PATH_PATTERNS):
            findings.append(path)

    assert findings == []


def test_runtime_code_does_not_autocreate_account_store_secrets() -> None:
    runtime_paths = (
        PROJECT_ROOT / "TeeBotus" / "runtime" / "telegram_runner.py",
        PROJECT_ROOT / "TeeBotus" / "runtime" / "signal_runner.py",
        PROJECT_ROOT / "TeeBotus" / "runtime" / "matrix_runner.py",
        PROJECT_ROOT / "TeeBotus" / "adapters" / "telegram_runtime.py",
    )
    findings: list[str] = []
    direct_provider_call = re.compile(r"\bSecretToolInstanceSecretProvider\s*\(")
    for path in runtime_paths:
        text = path.read_text(encoding="utf-8")
        for match in direct_provider_call.finditer(text):
            findings.append(f"{path.relative_to(PROJECT_ROOT)}:{_line_number(text, match.start())}")

    assert findings == []


def test_operator_scripts_do_not_autocreate_account_store_secrets() -> None:
    script_paths = (
        PROJECT_ROOT / "scripts" / "import_legacy_user_memory.py",
        PROJECT_ROOT / "scripts" / "migrate_account_memory_to_database.py",
        PROJECT_ROOT / "scripts" / "check_proactive_agent.py",
    )
    findings: list[str] = []
    direct_provider_call = re.compile(r"\bSecretToolInstanceSecretProvider\s*\((?!create_if_missing=False\))")
    for path in script_paths:
        text = path.read_text(encoding="utf-8")
        for match in direct_provider_call.finditer(text):
            findings.append(f"{path.relative_to(PROJECT_ROOT)}:{_line_number(text, match.start())}")

    assert findings == []


def test_product_code_never_requests_account_secret_autocreate() -> None:
    findings: list[str] = []
    pattern = re.compile(r"\bcreate_if_missing\s*=\s*True\b")
    for path in (PROJECT_ROOT / "TeeBotus").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            findings.append(f"{path.relative_to(PROJECT_ROOT)}:{_line_number(text, match.start())}")

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
