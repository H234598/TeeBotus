from __future__ import annotations

import argparse
import json
import os
import re
import selectors
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping, NamedTuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from TeeBotus import __version__
from TeeBotus.runtime.qdrant import QDRANT_BIBLIOTHEKAR_COLLECTION, QDRANT_USER_MEMORY_COLLECTION


DEFAULT_REPO_ROOT = Path.home() / "TeeBotus"
DEFAULT_CHANNELS = "telegram,signal"
DEFAULT_UNIT_NAME = "teebotus.service"
DEFAULT_QDRANT_UNIT_NAME = "teebotus-qdrant.service"
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
DEFAULT_STATUS_TIMEOUT_SECONDS = 30
MAX_STATUS_TIMEOUT_SECONDS = 300
CODEX_USAGE_STALE_WARNING_HOURS = 24
CONFIRMED_ACTIVE_SUBSTATES = frozenset({"active", "elapsed", "exited", "listening", "mounted", "plugged", "running", "waiting"})
MAX_CAPTURE_CHARS = 80_000
MAX_ERROR_CHARS = 2_000
MAX_REDACTION_GUARD_BYTES = 4_096
MAX_QDRANT_COUNT_RESPONSE_BYTES = 64_000
MAX_QDRANT_COUNT = 9_007_199_254_740_991
SECRET_TOKEN_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{8,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{12,}\b"),
    re.compile(r"\bhf_[A-Za-z0-9]{8,}\b"),
    re.compile(r"\bsyt_[A-Za-z0-9_=-]{8,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bgsk_[A-Za-z0-9]{8,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{16,}\b"),
    re.compile(r"\bya29\.[A-Za-z0-9._-]{16,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\b[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{20,}\b"),
)
URL_CREDENTIAL_RE = re.compile(
    r"(?:(?:[a-z][a-z0-9+.-]*://)|(?:(?:target|base_url|url)=)(?:[a-z][a-z0-9+.-]*://)?)(?:[^\s/@:]+(?::[^\s/@]*)?|:[^\s/@]+)@",
    re.IGNORECASE,
)
AUTHORIZATION_TOKEN_RE = re.compile(
    r"\b((?:proxy-)?authorization\s*[:=]\s*)(Bearer|Basic|ApiKey|Token)\s+([A-Za-z0-9._~+/=-]+)(?=$|[\s,;&)\]}>])",
    re.IGNORECASE,
)
BARE_AUTHORIZATION_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_-])((?i:Bearer|Basic|ApiKey)|Token)"
    r"\s+([A-Za-z0-9._~+/=-]{8,})(?=$|[\s,;&)\]}>])"
)
QUOTED_AUTHORIZATION_TOKEN_RE = re.compile(
    r"(^|[\s=;,&?(\[<{])([\"'])((?:proxy-)?authorization)\2(\s*[=:]\s*)([\"'])"
    r"(Bearer|Basic|ApiKey|Token)\s+([A-Za-z0-9._~+/=-]+)(\5)",
    re.IGNORECASE,
)
SECRET_OPTION_VALUE_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(--?(?:api[_-]?key|private[_-]?key|signing[_-]?key|access[_-]?token|auth[_-]?token|bearer[_-]?token|cookie|token|secret|password))"
    r"(\s+)((?:\"(?:\\.|[^\"\\\r\n])*\"|'(?:\\.|[^'\\\r\n])*'|`(?:\\.|[^`\\\r\n])*`|(?!-)[^\s,;&)\]}}>]+))",
    re.IGNORECASE,
)
COOKIE_HEADER_RE = re.compile(r"(?i)(?<![A-Za-z0-9_-])((?:set-cookie|cookie)\s*:\s*)[^\r\n]+")
SECRET_TOKEN_HINTS = frozenset(
    {
        "sk-",
        "ghp_",
        "gho_",
        "ghu_",
        "ghs_",
        "ghr_",
        "github_pat_",
        "hf_",
        "syt_",
        "glpat-",
        "gsk_",
        "aiza",
        "ya29.",
        "xox",
    }
)
URL_REDACTION_HINTS = frozenset({"://", "target=", "base_url=", "url="})
AUTHORIZATION_REDACTION_HINTS = frozenset({"authorization", "bearer", "basic", "apikey", "api_key", "api-key", "token "})
SECRET_OPTION_REDACTION_HINTS = frozenset(
    {
        "-api",
        "-private",
        "-signing",
        "-access",
        "-auth",
        "-bearer",
        "-cookie",
        "-token",
        "-secret",
        "-password",
    }
)
SECRET_ASSIGNMENT_REDACTION_HINTS = frozenset(
    {
        "api_key",
        "api-key",
        "apikey",
        "private_key",
        "private-key",
        "signing_key",
        "signing-key",
        "access_token",
        "access-token",
        "auth_token",
        "auth-token",
        "bearer_token",
        "bearer-token",
        "cookie",
        "token",
        "secret",
        "password",
    }
)
STATUS_FIELD_RE = re.compile(r"(?<!\S)([A-Za-z_][A-Za-z0-9_-]*)=")
FREE_TEXT_STATUS_FIELDS = frozenset({"action", "command", "error", "message", "route_error"})
FREE_TEXT_STATUS_FIELD_BOUNDARIES = {
    "action": frozenset({"warning"}),
    "command": frozenset({"apply_command"}),
    "error": frozenset({"warning"}),
    "message": frozenset({"action", "warning"}),
    "route_error": frozenset(
        {
            "fallback",
            "fallback_api_key",
            "fallback_base_url",
            "fallback_model",
            "fallback_models",
            "fallback_profile",
            "remote_fallback",
            "warning",
        }
    ),
}
FLAG_PROBLEM_STATUS_FIELDS = frozenset({"warning"})
NEUTRAL_FLAG_VALUES = frozenset({"0", "false", "no", "none", "off"})
FORCED_PROBLEM_STATUS_FIELDS = {"account_identity_warning": "warning"}
SENSITIVE_ASSIGNMENT_KEY_PATTERN = (
    r"(?:api[_-]?key|private[_-]?key|signing[_-]?key|access[_-]?token|auth[_-]?token|bearer[_-]?token|cookie|token|secret|password)"
)
SECRET_ASSIGNMENT_VALUE_PATTERN = (
    r"<redacted(?:-secret)?>|\"(?:\\.|[^\"\\\r\n])*\"|'(?:\\.|[^'\\\r\n])*'|`(?:\\.|[^`\\\r\n])*`|"
    r"(?:(?!\s+[A-Za-z_][A-Za-z0-9_-]*\s*[=:])[^,;\r\n)\]}>])+"
)
SECRET_ASSIGNMENT_FRAGMENT_VALUE_PATTERN = (
    r"<redacted(?:-secret)?>|\"(?:\\.|[^\"\\\r\n])*\"|'(?:\\.|[^'\\\r\n])*'|`(?:\\.|[^`\\\r\n])*`|"
    r"(?:(?!\s+[A-Za-z_][A-Za-z0-9_-]*\s*[=:])[^,;\r\n)&\]}>])+"
)
SECRET_ASSIGNMENT_RE = re.compile(
    rf"(?<!\S)([A-Za-z0-9_-]*{SENSITIVE_ASSIGNMENT_KEY_PATTERN}[A-Za-z0-9_-]*)\s*([:=])\s*"
    rf"({SECRET_ASSIGNMENT_VALUE_PATTERN})",
    re.IGNORECASE,
)
SECRET_ASSIGNMENT_FRAGMENT_RE = re.compile(
    rf"(^|[^A-Za-z0-9_-])([A-Za-z0-9_-]*{SENSITIVE_ASSIGNMENT_KEY_PATTERN}[A-Za-z0-9_-]*)\s*([:=])\s*"
    rf"({SECRET_ASSIGNMENT_FRAGMENT_VALUE_PATTERN})",
    re.IGNORECASE,
)
QUOTED_SECRET_ASSIGNMENT_RE = re.compile(
    rf"(^|[^A-Za-z0-9_-])([\"'])([A-Za-z0-9_-]*{SENSITIVE_ASSIGNMENT_KEY_PATTERN}[A-Za-z0-9_-]*)\2(\s*[=:]\s*)"
    rf"({SECRET_ASSIGNMENT_FRAGMENT_VALUE_PATTERN})",
    re.IGNORECASE,
)
SAFE_SECRET_VALUES = frozenset({"configured", "none", "missing", "redacted", "<redacted>", "<redacted-secret>"})
SAFE_SECRET_NUMERIC_METADATA = frozenset({"api_key_ring", "gemini_api_key_ring", "api_key_instances", "max_output_tokens"})
SAFE_SECRET_TEXT_METADATA = frozenset({"tokens", "token_usage", "costs", "limits", "free_tier_guard"})
PROBLEM_STATUSES = frozenset(
    {
        "broken",
        "config_conflict",
        "cooldown",
        "degraded",
        "empty",
        "error",
        "failed",
        "fallback_defaults",
        "invalid",
        "missing",
        "missing_key",
        "never",
        "needed",
        "no_limits_found",
        "partial",
        "schema_mismatch",
        "stale",
        "unknown",
        "unavailable",
        "unreachable",
        "unsupported",
        "warning",
    }
)
SECONDARY_PROBLEM_STATUS_FIELDS = frozenset({"models_feed", "route_status", "semantic"})
STATUS_FIELD_BOUNDARY_KEYS = frozenset({"status"}) | SECONDARY_PROBLEM_STATUS_FIELDS
STATUS_FIELD_BOUNDARY_VALUES = PROBLEM_STATUSES | frozenset(
    {
        "accepted",
        "available",
        "configured",
        "disabled",
        "enabled",
        "healthy",
        "installed",
        "not_applicable",
        "not_configured",
        "none",
        "ok",
        "planned",
        "queued",
        "reachable",
        "ready",
        "rebuilt",
        "registered",
        "routable",
        "skipped",
    }
)
SECTION_PROBLEM_SUMMARY_KEYS = {
    "Messenger": "messenger_problem_status_count",
    "Accounts und Entscheidungen": "llm_problem_status_count",
    "LLM-Routen und Backends": "llm_problem_status_count",
    "Lokale Dienste": "llm_problem_status_count",
    "API Keys, Limits und Kosten": "api_problem_status_count",
    "Projekt-History": "codex_history_problem_status_count",
    "Memory und semantische Suche": "memory_problem_status_count",
    "Tools und Account-Memory": "memory_problem_status_count",
}


class _StatusFieldMatch(NamedTuple):
    key: str
    key_start: int
    value_start: int


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="teebotus-cinnamon-applet")
    subparsers = parser.add_subparsers(dest="command", required=True)
    status_parser = subparsers.add_parser("status", help="Print Cinnamon applet status JSON.")
    status_parser.add_argument("--repo-root", default=str(DEFAULT_REPO_ROOT))
    status_parser.add_argument("--channels", default=DEFAULT_CHANNELS)
    status_parser.add_argument("--unit", default=DEFAULT_UNIT_NAME)
    status_parser.add_argument("--qdrant-unit", default=DEFAULT_QDRANT_UNIT_NAME)
    status_parser.add_argument("--qdrant-url", default=DEFAULT_QDRANT_URL)
    status_parser.add_argument("--python", default=sys.executable)
    status_parser.add_argument("--timeout", type=int, default=DEFAULT_STATUS_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)
    if args.command == "status":
        payload = build_status_payload(
            repo_root=Path(args.repo_root),
            channels=str(args.channels),
            unit_name=str(args.unit),
            qdrant_unit_name=str(args.qdrant_unit),
            qdrant_url=str(args.qdrant_url),
            python_executable=str(args.python),
            timeout_seconds=max(1, int(args.timeout)),
        )
        print(json.dumps(payload, ensure_ascii=True, sort_keys=True))
        return 0
    parser.error(f"unsupported command: {args.command}")
    return 2


def build_status_payload(
    *,
    repo_root: Path,
    channels: str,
    unit_name: str,
    python_executable: str,
    timeout_seconds: int,
    qdrant_unit_name: str = DEFAULT_QDRANT_UNIT_NAME,
    qdrant_url: str = DEFAULT_QDRANT_URL,
) -> dict[str, Any]:
    root = repo_root.expanduser().resolve()
    runtime = _runtime_status(root, channels=channels, python_executable=python_executable, timeout_seconds=timeout_seconds)
    parsed_runtime = parse_runtime_status(runtime["stdout"])
    unit = _systemd_unit_status(unit_name)
    qdrant_unit = _systemd_unit_status(qdrant_unit_name)
    qdrant = _qdrant_status(qdrant_url)
    repo = _repo_status(root)
    runtime_output_ok = bool(str(runtime.get("stdout", "") or "").strip())
    command_ok = (
        _status_query_ok(runtime)
        and runtime_output_ok
        and _status_query_ok(unit)
        and _unit_state_ok(unit)
    )
    health = _health_summary(command_ok=command_ok, parsed_runtime=parsed_runtime, qdrant=qdrant, qdrant_unit=qdrant_unit)
    return {
        "ok": health["status"] == "ok",
        "command_ok": command_ok,
        "health": health,
        "version": __version__,
        "repo": repo,
        "unit": unit,
        "qdrant": {
            "unit": qdrant_unit,
            "url": qdrant.get("url", qdrant_url),
            "collections": qdrant.get("collections", {}),
            "error": qdrant.get("error", ""),
        },
        "runtime": {
            "returncode": runtime["returncode"],
            "stderr": runtime["stderr"],
            "sections": parsed_runtime["sections"],
            "summary": parsed_runtime["summary"],
            "status_counts": parsed_runtime["status_counts"],
        },
    }


def _health_summary(*, command_ok: bool, parsed_runtime: dict[str, Any], qdrant: dict[str, Any], qdrant_unit: dict[str, Any]) -> dict[str, Any]:
    runtime_summary = parsed_runtime.get("summary", {}) if isinstance(parsed_runtime, dict) else {}
    status_counts = parsed_runtime.get("status_counts", {}) if isinstance(parsed_runtime, dict) else {}
    command_problem_count = 0 if command_ok else 1
    problem_count = _safe_int(runtime_summary.get("problem_status_count", 0))
    status_problem_count = sum(_safe_int(status_counts.get(status, 0)) for status in PROBLEM_STATUSES)
    qdrant_unit_problem_count = _unit_problem_count(qdrant_unit)
    qdrant_runtime_problem_count = _safe_int(runtime_summary.get("qdrant_problem_status_count", 0))
    qdrant_probe_problem_count = _qdrant_problem_count(qdrant)
    # A failed service query and failed collection probes are overlapping signals
    # for the same Qdrant outage; keep their detail fields, but count the worst
    # signal once in the top-level health total.
    qdrant_problem_count = max(qdrant_runtime_problem_count, qdrant_probe_problem_count, qdrant_unit_problem_count)
    severe_count = sum(_safe_int(status_counts.get(status, 0)) for status in ("broken", "config_conflict", "error", "failed", "invalid", "schema_mismatch"))
    runtime_problem_count = max(0, max(problem_count, status_problem_count) - qdrant_runtime_problem_count)
    total_problem_count = command_problem_count + runtime_problem_count + qdrant_problem_count
    status = "ok"
    if not command_ok or severe_count > 0:
        status = "broken"
    elif total_problem_count > 0:
        status = "warning"
    return {
        "status": status,
        "command_ok": bool(command_ok),
        "command_problem_count": command_problem_count,
        "problem_status_count": problem_count,
        "problem_statuses": str(runtime_summary.get("problem_statuses", "") or _problem_statuses_from_counts(status_counts)),
        "runtime_problem_count": runtime_problem_count,
        "qdrant_problem_count": qdrant_problem_count,
        "qdrant_probe_problem_count": qdrant_probe_problem_count,
        "qdrant_runtime_problem_count": qdrant_runtime_problem_count,
        "qdrant_unit_problem_count": qdrant_unit_problem_count,
        "total_problem_count": total_problem_count,
        "severe_status_count": severe_count,
    }


def _unit_problem_count(unit: dict[str, Any]) -> int:
    if not _status_query_ok(unit):
        return 1
    return 0 if _unit_state_ok(unit) else 1


def _status_query_ok(unit: dict[str, Any]) -> bool:
    """Treat a failed systemd query as unhealthy even if output looks active."""
    if not isinstance(unit, dict) or "returncode" not in unit:
        return False
    value = unit["returncode"]
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value == 0
    return isinstance(value, str) and value.strip() == "0"


def _unit_state_ok(unit: dict[str, Any]) -> bool:
    active_state = str(unit.get("active_state", "") or "").strip().casefold()
    sub_state = str(unit.get("sub_state", "") or "").strip().casefold()
    return active_state == "active" and sub_state in CONFIRMED_ACTIVE_SUBSTATES


def _qdrant_problem_count(qdrant: dict[str, Any]) -> int:
    count = 0
    collections = qdrant.get("collections", {})
    if isinstance(collections, dict):
        for result in collections.values():
            if (
                not isinstance(result, dict)
                or _normalized_status_value(result.get("status")) != "ready"
                or str(result.get("error", "") or "").strip()
            ):
                count += 1
    if count == 0 and str(qdrant.get("error", "") or "").strip():
        count = 1
    return count


def _safe_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (OverflowError, TypeError, ValueError):
        return default


def _problem_statuses_from_counts(status_counts: Mapping[str, Any]) -> str:
    items: list[str] = []
    for status, value in sorted(status_counts.items(), key=lambda item: str(item[0])):
        if status not in PROBLEM_STATUSES:
            continue
        count = _safe_int(value)
        if count > 0:
            items.append(f"{status}:{count}")
    return ",".join(items)


def parse_runtime_status(output: str) -> dict[str, Any]:
    sections: dict[str, list[str]] = {"Start": []}
    current = "Start"
    status_counts: dict[str, int] = {}
    codex_history_has_problem = False
    summary: dict[str, Any] = {
        "instances": "",
        "channels": "",
        "telegram_slots": 0,
        "signal_accounts": 0,
        "matrix_homeservers": 0,
        "messenger_problem_status_count": 0,
        "memory_accounts": 0,
        "memory_problem_status_count": 0,
        "llm_routes": 0,
        "llm_problem_status_count": 0,
        "api_budgets": 0,
        "api_problem_status_count": 0,
        "codex_usage": "",
        "codex_usage_accounts": 0,
        "codex_history": "",
        "codex_history_instances": 0,
        "codex_history_repos": 0,
        "codex_history_run_summaries": 0,
        "codex_history_strategies": 0,
        "codex_history_graphs": 0,
        "codex_history_other": 0,
        "codex_history_problem_status_count": 0,
        "gemini_free_tier": "",
        "qdrant": "",
        "qdrant_collections": 0,
        "qdrant_problem_status_count": 0,
        "qdrant_ready_collections": 0,
        "memory_semantic_ready": 0,
        "hf_pool": "",
        "problem_status_count": 0,
        "problem_statuses": "",
        "output_truncated": False,
    }
    for raw_line in str(output or "").splitlines():
        line = _redact(raw_line.strip())
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip() or "Unbenannt"
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
        if line == "<truncated>":
            summary["output_truncated"] = True
            continue
        fields = _parse_status_fields(line)
        line_statuses = list(_line_status_values(fields))
        if _line_has_ready_error(line, fields) and not any(status in PROBLEM_STATUSES for status in line_statuses):
            _append_status_value(line_statuses, "warning")
        if line.startswith("codex_usage=") and _codex_usage_is_stale(fields):
            _append_status_value(line_statuses, "stale")
        for status in line_statuses:
            status_counts[status] = status_counts.get(status, 0) + 1
        section_problem_key = SECTION_PROBLEM_SUMMARY_KEYS.get(current)
        if section_problem_key:
            summary[section_problem_key] += sum(1 for status in line_statuses if status in PROBLEM_STATUSES)
        if line.startswith("instances="):
            summary["instances"] = line.split("=", 1)[1]
        elif line.startswith("channels="):
            summary["channels"] = line.split("=", 1)[1]
        elif line.startswith("telegram_slot="):
            summary["telegram_slots"] += 1
        elif line.startswith("signal_account="):
            summary["signal_accounts"] += 1
        elif line.startswith("matrix_homeserver="):
            summary["matrix_homeservers"] += 1
        elif line.startswith("account_memory="):
            summary["memory_accounts"] += 1
        elif line.startswith("llm_route="):
            summary["llm_routes"] += 1
        elif line.startswith("api_budget="):
            summary["api_budgets"] += 1
        elif line.startswith("codex_usage="):
            summary["codex_usage"] = line
        elif line.startswith("codex_usage_account="):
            summary["codex_usage_accounts"] += 1
        elif line.startswith("codex_history="):
            summary["codex_history_instances"] += 1
            summary["codex_history_run_summaries"] += _safe_int(fields.get("run_summaries", 0))
            summary["codex_history_strategies"] += _safe_int(fields.get("strategies", 0))
            summary["codex_history_graphs"] += _safe_int(fields.get("graphs", 0))
            summary["codex_history_other"] += _safe_int(fields.get("other", 0))
            line_has_problem = any(status in PROBLEM_STATUSES for status in line_statuses)
            if not summary["codex_history"] or (line_has_problem and not codex_history_has_problem):
                summary["codex_history"] = line
                codex_history_has_problem = line_has_problem
        elif line.startswith("codex_history_repo="):
            summary["codex_history_repos"] += 1
        elif line.startswith("gemini_free_tier_limits "):
            summary["gemini_free_tier"] = line
        elif line.startswith("qdrant="):
            summary["qdrant"] = line
            summary["qdrant_problem_status_count"] += sum(status in PROBLEM_STATUSES for status in line_statuses)
        elif line.startswith("qdrant_collection="):
            summary["qdrant_collections"] += 1
            summary["qdrant_problem_status_count"] += sum(status in PROBLEM_STATUSES for status in line_statuses)
            if _status_is_ready_without_error(fields, "status"):
                summary["qdrant_ready_collections"] += 1
        elif (
            line.startswith("memory_index=")
            and _status_is_ready_without_error(fields, "status")
            and _status_is_ready_without_error(fields, "semantic")
        ):
            summary["memory_semantic_ready"] += 1
        elif line.startswith("hf_pool=") and not fields.get("target"):
            summary["hf_pool"] = line
    if summary["output_truncated"]:
        status_counts["warning"] = status_counts.get("warning", 0) + 1
    problem_counts = {status: count for status, count in sorted(status_counts.items()) if status in PROBLEM_STATUSES}
    summary["problem_status_count"] = sum(problem_counts.values())
    summary["problem_statuses"] = ",".join(f"{status}:{count}" for status, count in problem_counts.items())
    sections = {key: value for key, value in sections.items() if value}
    return {"sections": sections, "summary": summary, "status_counts": status_counts}


def _line_status_values(fields: dict[str, str]) -> tuple[str, ...]:
    values: list[str] = []
    primary = _normalized_status_value(fields.get("status"))
    if primary:
        _append_status_value(values, primary)
    for key in sorted(SECONDARY_PROBLEM_STATUS_FIELDS):
        secondary = _normalized_status_value(fields.get(key))
        if secondary and secondary in PROBLEM_STATUSES:
            _append_status_value(values, secondary)
    for key in sorted(FLAG_PROBLEM_STATUS_FIELDS):
        if _status_flag_is_set(fields.get(key, "")):
            _append_status_value(values, "warning")
    for key, status in sorted(FORCED_PROBLEM_STATUS_FIELDS.items()):
        if _status_flag_is_set(fields.get(key, "")):
            _append_status_value(values, status)
    return tuple(values)


def _normalized_status_value(value: Any) -> str:
    return str(value or "").strip().casefold()


def _status_is_ready_without_error(fields: Mapping[str, Any], key: str) -> bool:
    return _normalized_status_value(fields.get(key)) == "ready" and not str(fields.get("error", "") or "").strip()


def _line_has_ready_error(line: str, fields: Mapping[str, Any]) -> bool:
    if not str(fields.get("error", "") or "").strip():
        return False
    return _normalized_status_value(fields.get("status")) == "ready"


def _append_status_value(values: list[str], status: str) -> None:
    if status and status not in values:
        values.append(status)


def _status_flag_is_set(value: str) -> bool:
    normalized = str(value or "").strip().casefold()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {'"', "'", "`"}:
        normalized = normalized[1:-1].strip()
    return bool(normalized) and normalized not in NEUTRAL_FLAG_VALUES


def _codex_usage_is_stale(fields: dict[str, str]) -> bool:
    return _safe_int(fields.get("stale_hours"), -1) >= CODEX_USAGE_STALE_WARNING_HOURS


def _runtime_status(repo_root: Path, *, channels: str, python_executable: str, timeout_seconds: int) -> dict[str, Any]:
    argv = [*_python_command_argv(python_executable), "-m", "TeeBotus", "--runtime-status", "--channels", channels]
    return _run(argv, cwd=repo_root, timeout_seconds=_bounded_status_timeout(timeout_seconds))


def _bounded_status_timeout(value: Any) -> int:
    try:
        parsed = int(value)
    except (OverflowError, TypeError, ValueError):
        parsed = DEFAULT_STATUS_TIMEOUT_SECONDS
    return min(max(1, parsed), MAX_STATUS_TIMEOUT_SECONDS)


def _python_command_argv(value: str) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return [sys.executable]
    try:
        parsed = shlex.split(raw)
    except ValueError:
        return [raw]
    return parsed or [sys.executable]


def _systemd_unit_status(unit_name: str) -> dict[str, Any]:
    name = str(unit_name or "").strip()
    if not name:
        return {
            "name": "",
            "active_state": "unknown",
            "sub_state": "unknown",
            "main_pid": "",
            "returncode": 2,
            "stderr": "systemd unit name is empty",
        }
    result = _run(
        ["systemctl", "--user", "show", name, "--property=ActiveState,SubState,MainPID,FragmentPath,LoadState"],
        timeout_seconds=5,
    )
    fields = _parse_key_value_lines(result["stdout"])
    active_state = fields.get("ActiveState", "unknown") or "unknown"
    sub_state = fields.get("SubState", "unknown") or "unknown"
    main_pid = fields.get("MainPID", "")
    fragment_path = fields.get("FragmentPath", "")
    load_state = fields.get("LoadState", "")
    if result["returncode"] != 0 and active_state == "unknown":
        active_state = "missing"
    return {
        "name": name,
        "active_state": active_state,
        "sub_state": sub_state,
        "main_pid": main_pid,
        "fragment_path": fragment_path,
        "load_state": load_state,
        "returncode": result["returncode"],
        "stderr": result["stderr"],
    }


def _qdrant_status(url: str) -> dict[str, Any]:
    target = _safe_local_qdrant_url(url)
    if not target:
        return {"url": _redact(str(url or "")), "collections": {}, "error": "invalid local qdrant url"}
    collections: dict[str, Any] = {}
    errors: list[str] = []
    for collection in (QDRANT_USER_MEMORY_COLLECTION, QDRANT_BIBLIOTHEKAR_COLLECTION):
        result = _qdrant_point_count(target, collection)
        collections[collection] = result
        if result.get("error"):
            errors.append(f"{collection}: {result['error']}")
    return {"url": target, "collections": collections, "error": "; ".join(errors)}


def _safe_local_qdrant_url(value: str) -> str:
    raw = str(value or DEFAULT_QDRANT_URL).strip() or DEFAULT_QDRANT_URL
    try:
        parsed = urlparse(raw)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"}:
        return ""
    if (parsed.hostname or "").casefold() not in {"127.0.0.1", "localhost", "::1"}:
        return ""
    try:
        if parsed.port is None:
            return ""
    except ValueError:
        return ""
    if parsed.port <= 0:
        return ""
    if parsed.username is not None or parsed.password is not None or parsed.params or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        return ""
    return raw.rstrip("/")


def _qdrant_point_count(url: str, collection: str) -> dict[str, Any]:
    name = str(collection or "").strip()
    if not name:
        return {"status": "invalid", "count": 0, "error": "missing collection name"}
    request = Request(
        f"{url}/collections/{quote(name, safe='')}/points/count",
        data=b'{"exact":true}',
        method="POST",
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    response = None
    try:
        response = urlopen(request, timeout=2)
        status_value = getattr(response, "status", None)
        if status_value is None:
            status_value = getattr(response, "code", 200)
        if isinstance(status_value, bool) or not isinstance(status_value, int):
            raise ValueError("invalid Qdrant HTTP status")
        status_code = status_value
        try:
            raw = response.read(MAX_QDRANT_COUNT_RESPONSE_BYTES + 1)
        except TypeError:
            return {
                "status": "broken",
                "count": 0,
                "error": "Qdrant response reader does not support bounded reads",
            }
    except HTTPError as exc:
        close = getattr(exc, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001 - cleanup must not hide the HTTP status.
                pass
        return {"status": "unreachable", "count": 0, "error": f"HTTP {exc.code}"}
    except (URLError, TimeoutError, OSError) as exc:
        return {"status": "unreachable", "count": 0, "error": _redact(str(getattr(exc, "reason", exc)))}
    except Exception as exc:  # noqa: BLE001 - applet status should stay JSON even if Qdrant is broken.
        return {"status": "unreachable", "count": 0, "error": _redact(f"{type(exc).__name__}: {exc}")}
    finally:
        if response is not None:
            close = getattr(response, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001 - cleanup must not hide the status result.
                    pass
    if not 200 <= status_code < 300:
        return {"status": "unreachable", "count": 0, "error": f"HTTP {status_code}"}
    if not isinstance(raw, (bytes, bytearray)):
        return {"status": "broken", "count": 0, "error": "invalid Qdrant response body"}
    if len(raw) > MAX_QDRANT_COUNT_RESPONSE_BYTES:
        return {"status": "broken", "count": 0, "error": "Qdrant count response too large"}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (RecursionError, UnicodeDecodeError, ValueError) as exc:
        return {"status": "broken", "count": 0, "error": f"invalid JSON: {type(exc).__name__}"}
    if not isinstance(payload, dict):
        return {"status": "broken", "count": 0, "error": "unexpected JSON payload"}
    if "status" in payload and not isinstance(payload["status"], str):
        return {"status": "broken", "count": 0, "error": "invalid Qdrant status"}
    api_status = str(payload.get("status", "")).strip().casefold()
    if "status" in payload and api_status not in {"ok", "green"}:
        return {"status": "broken", "count": 0, "error": f"unexpected Qdrant status: {api_status}"}
    result = payload.get("result")
    if not isinstance(result, dict) or "count" not in result:
        return {"status": "broken", "count": 0, "error": "missing Qdrant count result"}
    count = result.get("count")
    if isinstance(count, bool):
        return {"status": "broken", "count": 0, "error": "invalid Qdrant count result"}
    if isinstance(count, int):
        parsed_count = count
    elif isinstance(count, str) and re.fullmatch(r"[0-9]+", count.strip()):
        normalized_count = count.strip()
        canonical_count = normalized_count.lstrip("0") or "0"
        if len(canonical_count) > len(str(MAX_QDRANT_COUNT)):
            return {"status": "broken", "count": 0, "error": "unsafe Qdrant count result"}
        try:
            parsed_count = int(canonical_count)
        except (ValueError, OverflowError):
            return {"status": "broken", "count": 0, "error": "invalid Qdrant count result"}
    else:
        return {"status": "broken", "count": 0, "error": "invalid Qdrant count result"}
    if parsed_count < 0:
        return {"status": "broken", "count": 0, "error": "negative Qdrant count result"}
    if parsed_count > MAX_QDRANT_COUNT:
        return {"status": "broken", "count": 0, "error": "unsafe Qdrant count result"}
    return {"status": "ready", "count": parsed_count, "error": ""}


def _repo_status(repo_root: Path) -> dict[str, Any]:
    status: dict[str, Any] = {
        "path": str(repo_root),
        "exists": repo_root.exists(),
        "branch": "",
        "commit": "",
        "short_commit": "",
        "dirty": False,
        "ahead_behind": "",
    }
    if not repo_root.exists():
        return status
    branch = _run(["git", "branch", "--show-current"], cwd=repo_root, timeout_seconds=5)
    commit = _run(["git", "rev-parse", "HEAD"], cwd=repo_root, timeout_seconds=5)
    porcelain = _run(["git", "status", "--porcelain=v1", "--branch"], cwd=repo_root, timeout_seconds=5)
    status["branch"] = branch["stdout"].strip()
    status["commit"] = commit["stdout"].strip()
    status["short_commit"] = status["commit"][:7]
    porcelain_lines = porcelain["stdout"].splitlines()
    status["dirty"] = (
        not _status_query_ok(porcelain)
        or "<truncated>" in porcelain_lines
        or any(line and not line.startswith("## ") for line in porcelain_lines)
    )
    first = next((line for line in porcelain_lines if line.startswith("## ")), "")
    status["ahead_behind"] = first[3:].strip()
    return status


def _run(argv: list[str], *, cwd: Path | None = None, timeout_seconds: int = 10) -> dict[str, Any]:
    quoted_argv = [shlex.quote(str(part)) for part in argv]
    try:
        bounded_timeout = max(1, int(timeout_seconds))
        process = subprocess.Popen(
            argv,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr, returncode, timed_out = _collect_process_output(
            process,
            timeout_seconds=bounded_timeout,
        )
        if timed_out:
            return {
                "argv": quoted_argv,
                "returncode": 124,
                "stdout": "",
                "stderr": _limit_text(_redact(f"TimeoutExpired: command timed out after {bounded_timeout} seconds"), MAX_ERROR_CHARS),
            }
        return {
            "argv": quoted_argv,
            "returncode": returncode,
            "stdout": _limit_text(_redact(stdout.decode("utf-8", errors="replace")), MAX_CAPTURE_CHARS),
            "stderr": _limit_text(_redact(stderr.decode("utf-8", errors="replace")), MAX_ERROR_CHARS),
        }
    except Exception as exc:  # noqa: BLE001 - applet status should degrade to JSON, not crash.
        return {
            "argv": quoted_argv,
            "returncode": 124,
            "stdout": "",
            "stderr": _limit_text(_redact(f"{type(exc).__name__}: {exc}"), MAX_ERROR_CHARS),
        }


def _collect_process_output(
    process: subprocess.Popen[bytes],
    *,
    timeout_seconds: int,
) -> tuple[bytes, bytes, int, bool]:
    limits = {
        "stdout": MAX_CAPTURE_CHARS + MAX_REDACTION_GUARD_BYTES,
        "stderr": MAX_ERROR_CHARS + MAX_REDACTION_GUARD_BYTES,
    }
    buffers = {name: bytearray() for name in limits}
    selector = selectors.DefaultSelector()
    streams = {"stdout": process.stdout, "stderr": process.stderr}
    deadline = time.monotonic() + timeout_seconds
    timed_out = False
    try:
        for name, stream in streams.items():
            if stream is not None:
                selector.register(stream, selectors.EVENT_READ, name)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            events = selector.select(remaining)
            if not events:
                if process.poll() is None:
                    timed_out = True
                break
            for key, _ in events:
                stream = key.fileobj
                chunk = os.read(stream.fileno(), 65_536)
                if not chunk:
                    selector.unregister(stream)
                    stream.close()
                    continue
                buffer = buffers[key.data]
                remaining_capacity = limits[key.data] - len(buffer)
                if remaining_capacity > 0:
                    buffer.extend(chunk[:remaining_capacity])
    finally:
        force_stop = timed_out or process.poll() is None
        if force_stop:
            try:
                process.kill()
            except (OSError, ProcessLookupError):
                pass
        try:
            process.wait(timeout=1 if force_stop else max(1, int(timeout_seconds)))
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except (OSError, ProcessLookupError):
                pass
            process.wait(timeout=1)
        for stream in streams.values():
            if stream is not None and not stream.closed:
                stream.close()
        selector.close()

    returncode = process.returncode if process.returncode is not None else 124
    return bytes(buffers["stdout"]), bytes(buffers["stderr"]), int(returncode), timed_out


def _parse_status_fields(line: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    text = str(line or "")
    matches = _status_field_matches(text)
    index = 0
    while index < len(matches):
        match = matches[index]
        key = match.key.strip()
        if not key:
            index += 1
            continue
        value_start = match.value_start
        value_end = _status_field_value_end(text, matches, index, key)
        value = text[value_start:value_end].strip()
        if key in STATUS_FIELD_BOUNDARY_KEYS:
            value = value.casefold()
        fields[key] = value
        index += 1
        while index < len(matches) and matches[index].key_start < value_end:
            index += 1
    return fields


def _status_field_matches(text: str) -> list[_StatusFieldMatch]:
    quoted = _quoted_character_indexes(text)
    matches: list[_StatusFieldMatch] = []
    for match in STATUS_FIELD_RE.finditer(text):
        key_start = match.start(1)
        if key_start in quoted:
            continue
        matches.append(_StatusFieldMatch(key=str(match.group(1) or ""), key_start=key_start, value_start=match.end()))
    return matches


def _quoted_character_indexes(text: str) -> set[int]:
    quoted: set[int] = set()
    index = 0
    while index < len(text):
        char = text[index]
        if char == "=" and index + 1 < len(text) and text[index + 1] in {"'", '"', "`"}:
            quote = text[index + 1]
            quote_index = index + 1
            candidate: set[int] = set()
            closed = False
            while quote_index < len(text):
                candidate.add(quote_index)
                if text[quote_index] == "\\" and quote_index + 1 < len(text):
                    candidate.add(quote_index + 1)
                    quote_index += 2
                    continue
                if quote_index > index + 1 and text[quote_index] == quote:
                    closed = True
                    break
                quote_index += 1
            if closed:
                quoted.update(candidate)
                index = quote_index + 1
                continue
        index += 1
    return quoted


def _status_field_value_end(text: str, matches: list[_StatusFieldMatch], index: int, key: str) -> int:
    if key not in FREE_TEXT_STATUS_FIELDS:
        return matches[index + 1].key_start if index + 1 < len(matches) else len(text)
    allowed_boundaries = FREE_TEXT_STATUS_FIELD_BOUNDARIES.get(key, frozenset())
    for next_index, next_match in enumerate(matches[index + 1 :], start=index + 1):
        next_key = next_match.key
        if next_key in allowed_boundaries or _status_match_is_structured_boundary(text, matches, next_index):
            return next_match.key_start
    return len(text)


def _status_match_is_structured_boundary(text: str, matches: list[_StatusFieldMatch], index: int) -> bool:
    match = matches[index]
    if match.key not in STATUS_FIELD_BOUNDARY_KEYS:
        return False
    value_end = matches[index + 1].key_start if index + 1 < len(matches) else len(text)
    value = _normalized_status_value(text[match.value_start : value_end])
    return value in STATUS_FIELD_BOUNDARY_VALUES


def _parse_key_value_lines(value: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in str(value or "").splitlines():
        if "=" not in line:
            continue
        key, item = line.split("=", 1)
        fields[key.strip()] = item.strip()
    return fields


def _redact(value: str) -> str:
    text = str(value or "")
    if not text:
        return text
    lowered = text.casefold()
    if not (
        any(hint in lowered for hint in SECRET_TOKEN_HINTS)
        or any(hint in lowered for hint in URL_REDACTION_HINTS)
        or any(hint in lowered for hint in AUTHORIZATION_REDACTION_HINTS)
        or any(hint in lowered for hint in SECRET_OPTION_REDACTION_HINTS)
        or any(hint in lowered for hint in SECRET_ASSIGNMENT_REDACTION_HINTS)
        or lowered.count(".") >= 2
    ):
        return text
    if any(hint in lowered for hint in SECRET_TOKEN_HINTS) or lowered.count(".") >= 2:
        for pattern in SECRET_TOKEN_PATTERNS:
            text = pattern.sub("<redacted-secret>", text)
    if "@" in text and any(hint in lowered for hint in URL_REDACTION_HINTS):
        text = URL_CREDENTIAL_RE.sub(_redact_url_credentials, text)
    if any(hint in lowered for hint in AUTHORIZATION_REDACTION_HINTS):
        text = AUTHORIZATION_TOKEN_RE.sub(r"\1\2 <redacted-secret>", text)
        text = BARE_AUTHORIZATION_TOKEN_RE.sub(r"\1 <redacted-secret>", text)
        text = QUOTED_AUTHORIZATION_TOKEN_RE.sub(_redact_quoted_authorization_token, text)
    if any(hint in lowered for hint in SECRET_OPTION_REDACTION_HINTS):
        text = SECRET_OPTION_VALUE_RE.sub(_redact_secret_option_value, text)
    if "cookie" in lowered:
        text = COOKIE_HEADER_RE.sub(r"\1<redacted-secret>", text)
    if any(hint in lowered for hint in SECRET_ASSIGNMENT_REDACTION_HINTS):
        text = QUOTED_SECRET_ASSIGNMENT_RE.sub(_redact_quoted_secret_assignment, text)
        text = SECRET_ASSIGNMENT_RE.sub(_redact_secret_assignment, text)
        text = SECRET_ASSIGNMENT_FRAGMENT_RE.sub(_redact_secret_assignment_fragment, text)
    return text


def _redact_url_credentials(match: re.Match[str]) -> str:
    value = match.group(0)
    if "://" in value:
        return value.split("://", 1)[0] + "://<redacted>@"
    if "=" in value:
        return value.split("=", 1)[0] + "=<redacted>@"
    return "<redacted>@"


def _redact_quoted_authorization_token(match: re.Match[str]) -> str:
    prefix = str(match.group(1) or "")
    key_quote = str(match.group(2) or '"')
    key = str(match.group(3) or "authorization")
    separator = str(match.group(4) or ":")
    value_quote = str(match.group(5) or '"')
    scheme = str(match.group(6) or "Bearer")
    closing_quote = str(match.group(8) or value_quote)
    return f"{prefix}{key_quote}{key}{key_quote}{separator}{value_quote}{scheme} <redacted-secret>{closing_quote}"


def _redact_secret_option_value(match: re.Match[str]) -> str:
    option = str(match.group(1) or "")
    separator = str(match.group(2) or " ")
    return f"{option}{separator}<redacted>"


def _redact_secret_assignment(match: re.Match[str]) -> str:
    key = str(match.group(1) or "")
    separator = str(match.group(2) or "=")
    value = str(match.group(3) or "")
    return _redact_secret_assignment_text(key, separator, value, original=match.group(0))


def _redact_secret_assignment_fragment(match: re.Match[str]) -> str:
    prefix = str(match.group(1) or "")
    key = str(match.group(2) or "")
    separator = str(match.group(3) or "=")
    value = str(match.group(4) or "")
    original = match.group(0)[len(prefix) :]
    return prefix + _redact_secret_assignment_text(key, separator, value, original=original)


def _redact_quoted_secret_assignment(match: re.Match[str]) -> str:
    prefix = str(match.group(1) or "")
    key_quote = str(match.group(2) or '"')
    key = str(match.group(3) or "")
    separator = str(match.group(4) or ":")
    value = str(match.group(5) or "")
    original = match.group(0)[len(prefix) :]
    redacted = _redact_secret_assignment_text(key, separator, value, original=original)
    if redacted == original:
        return match.group(0)
    raw_value = value.strip()
    value_quote = raw_value[:1] if raw_value[:1] in {"'", '"', "`"} and raw_value[-1:] == raw_value[:1] else ""
    rendered_value = f"{value_quote}<redacted>{value_quote}" if value_quote else "<redacted>"
    return f"{prefix}{key_quote}{key}{key_quote}{separator}{rendered_value}"


def _redact_secret_assignment_text(key: str, separator: str, value: str, *, original: str) -> str:
    key_token = key.strip().casefold().replace("-", "_").replace(" ", "_")
    raw_value = value.strip()
    unquoted_value = raw_value.strip("\"'`")
    normalized_value = unquoted_value.casefold()
    if normalized_value in SAFE_SECRET_VALUES:
        return original
    if key_token.endswith("_env") and re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", unquoted_value):
        return original
    if key_token in SAFE_SECRET_NUMERIC_METADATA and (unquoted_value.isdigit() or re.fullmatch(r"\d+/\d+", unquoted_value)):
        return original
    if key_token in SAFE_SECRET_TEXT_METADATA:
        return original
    return f"{key}{separator}<redacted>"


def _limit_text(value: str, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit] + "\n<truncated>"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
