from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any
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
CODEX_USAGE_STALE_WARNING_HOURS = 24
MAX_CAPTURE_CHARS = 80_000
MAX_ERROR_CHARS = 2_000
SECRET_TOKEN_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{8,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{12,}\b"),
    re.compile(r"\bhf_[A-Za-z0-9]{8,}\b"),
    re.compile(r"\bsyt_[A-Za-z0-9_=-]{8,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bgsk_[A-Za-z0-9]{8,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{16,}\b"),
)
URL_CREDENTIAL_RE = re.compile(
    r"(?:(?:[a-z][a-z0-9+.-]*://)|(?:(?:target|base_url|url)=)(?:[a-z][a-z0-9+.-]*://)?)[^\s/@:]*:[^\s/@]*@",
    re.IGNORECASE,
)
BEARER_TOKEN_RE = re.compile(r"\b(Bearer)\s+([A-Za-z0-9._~+/=-]{8,})\b", re.IGNORECASE)
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?<!\S)([A-Za-z0-9_-]*(?:api[_-]?key|access[_-]?token|auth[_-]?token|bearer[_-]?token|token|secret|password)"
    r"[A-Za-z0-9_-]*)\s*([:=])\s*([^,\s)]+)",
    re.IGNORECASE,
)
SECRET_ASSIGNMENT_FRAGMENT_RE = re.compile(
    r"([\s=;,&?])([A-Za-z0-9_-]*(?:api[_-]?key|access[_-]?token|auth[_-]?token|bearer[_-]?token|token|secret|password)"
    r"[A-Za-z0-9_-]*)\s*([:=])\s*([^,\s)&]+)",
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
        "error",
        "failed",
        "fallback_defaults",
        "invalid",
        "missing",
        "missing_key",
        "never",
        "needed",
        "no_limits_found",
        "schema_mismatch",
        "stale",
        "unknown",
        "unavailable",
        "unreachable",
        "warning",
    }
)
SECONDARY_PROBLEM_STATUS_FIELDS = frozenset({"route_status"})


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
    command_ok = runtime["returncode"] == 0 and unit.get("active_state") in {"active", "unknown"}
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
    qdrant_unit_problem_count = _unit_problem_count(qdrant_unit)
    qdrant_runtime_problem_count = _safe_int(runtime_summary.get("qdrant_problem_status_count", 0))
    qdrant_probe_problem_count = 0 if qdrant_runtime_problem_count > 0 else _qdrant_problem_count(qdrant)
    qdrant_problem_count = qdrant_probe_problem_count + qdrant_unit_problem_count
    severe_count = sum(_safe_int(status_counts.get(status, 0)) for status in ("broken", "config_conflict", "error", "failed", "invalid", "schema_mismatch"))
    total_problem_count = command_problem_count + problem_count + qdrant_problem_count
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
        "problem_statuses": str(runtime_summary.get("problem_statuses", "") or ""),
        "qdrant_problem_count": qdrant_problem_count,
        "qdrant_probe_problem_count": qdrant_probe_problem_count,
        "qdrant_runtime_problem_count": qdrant_runtime_problem_count,
        "qdrant_unit_problem_count": qdrant_unit_problem_count,
        "total_problem_count": total_problem_count,
        "severe_status_count": severe_count,
    }


def _unit_problem_count(unit: dict[str, Any]) -> int:
    active_state = str(unit.get("active_state", "") or "").strip()
    if not active_state or active_state in {"active", "unknown"}:
        return 0
    return 1


def _qdrant_problem_count(qdrant: dict[str, Any]) -> int:
    count = 0
    collections = qdrant.get("collections", {})
    if isinstance(collections, dict):
        for result in collections.values():
            if isinstance(result, dict) and str(result.get("status", "") or "") != "ready":
                count += 1
    if count == 0 and str(qdrant.get("error", "") or "").strip():
        count = 1
    return count


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_runtime_status(output: str) -> dict[str, Any]:
    sections: dict[str, list[str]] = {"Start": []}
    current = "Start"
    status_counts: dict[str, int] = {}
    summary: dict[str, Any] = {
        "instances": "",
        "channels": "",
        "telegram_slots": 0,
        "signal_accounts": 0,
        "matrix_homeservers": 0,
        "memory_accounts": 0,
        "llm_routes": 0,
        "api_budgets": 0,
        "codex_usage": "",
        "codex_usage_accounts": 0,
        "gemini_free_tier": "",
        "qdrant": "",
        "qdrant_collections": 0,
        "qdrant_problem_status_count": 0,
        "qdrant_ready_collections": 0,
        "memory_semantic_ready": 0,
        "hf_pool": "",
        "problem_status_count": 0,
        "problem_statuses": "",
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
        fields = _parse_status_fields(line)
        for status in _line_status_values(fields):
            status_counts[status] = status_counts.get(status, 0) + 1
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
            if _codex_usage_is_stale(fields):
                status_counts["stale"] = status_counts.get("stale", 0) + 1
        elif line.startswith("codex_usage_account="):
            summary["codex_usage_accounts"] += 1
        elif line.startswith("gemini_free_tier_limits "):
            summary["gemini_free_tier"] = line
        elif line.startswith("qdrant="):
            summary["qdrant"] = line
            if fields.get("status") in PROBLEM_STATUSES:
                summary["qdrant_problem_status_count"] += 1
        elif line.startswith("qdrant_collection="):
            summary["qdrant_collections"] += 1
            if fields.get("status") in PROBLEM_STATUSES:
                summary["qdrant_problem_status_count"] += 1
            if fields.get("status") == "ready":
                summary["qdrant_ready_collections"] += 1
        elif line.startswith("memory_index=") and fields.get("semantic") == "ready":
            summary["memory_semantic_ready"] += 1
        elif line.startswith("hf_pool="):
            summary["hf_pool"] = line
    problem_counts = {status: count for status, count in sorted(status_counts.items()) if status in PROBLEM_STATUSES}
    summary["problem_status_count"] = sum(problem_counts.values())
    summary["problem_statuses"] = ",".join(f"{status}:{count}" for status, count in problem_counts.items())
    sections = {key: value for key, value in sections.items() if value}
    return {"sections": sections, "summary": summary, "status_counts": status_counts}


def _line_status_values(fields: dict[str, str]) -> tuple[str, ...]:
    values: list[str] = []
    primary = fields.get("status", "")
    if primary:
        values.append(primary)
    for key in sorted(SECONDARY_PROBLEM_STATUS_FIELDS):
        secondary = fields.get(key, "")
        if secondary and secondary in PROBLEM_STATUSES and secondary != primary:
            values.append(secondary)
    return tuple(values)


def _codex_usage_is_stale(fields: dict[str, str]) -> bool:
    return _safe_int(fields.get("stale_hours"), -1) >= CODEX_USAGE_STALE_WARNING_HOURS


def _runtime_status(repo_root: Path, *, channels: str, python_executable: str, timeout_seconds: int) -> dict[str, Any]:
    argv = [python_executable, "-m", "TeeBotus", "--runtime-status", "--channels", channels]
    return _run(argv, cwd=repo_root, timeout_seconds=timeout_seconds)


def _systemd_unit_status(unit_name: str) -> dict[str, Any]:
    name = str(unit_name or "").strip()
    if not name:
        return {"name": "", "active_state": "unknown", "sub_state": "unknown", "main_pid": ""}
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
        return {"url": str(url or ""), "collections": {}, "error": "invalid local qdrant url"}
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
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
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
    try:
        response = urlopen(request, timeout=2)
        status_code = int(getattr(response, "status", getattr(response, "code", 200)) or 200)
        raw = response.read()
        close = getattr(response, "close", None)
        if callable(close):
            close()
    except HTTPError as exc:
        return {"status": "unreachable", "count": 0, "error": f"HTTP {exc.code}"}
    except (URLError, TimeoutError, OSError) as exc:
        return {"status": "unreachable", "count": 0, "error": _redact(str(getattr(exc, "reason", exc)))}
    except Exception as exc:  # noqa: BLE001 - applet status should stay JSON even if Qdrant is broken.
        return {"status": "unreachable", "count": 0, "error": _redact(f"{type(exc).__name__}: {exc}")}
    if not 200 <= status_code < 300:
        return {"status": "unreachable", "count": 0, "error": f"HTTP {status_code}"}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {"status": "broken", "count": 0, "error": f"invalid JSON: {type(exc).__name__}"}
    result = payload.get("result") if isinstance(payload, dict) else {}
    count = result.get("count") if isinstance(result, dict) else 0
    try:
        parsed_count = max(0, int(count))
    except (TypeError, ValueError):
        parsed_count = 0
    return {"status": "ready", "count": parsed_count, "error": ""}


def _repo_status(repo_root: Path) -> dict[str, Any]:
    status = {
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
    status["dirty"] = any(line and not line.startswith("## ") for line in porcelain["stdout"].splitlines())
    first = next((line for line in porcelain["stdout"].splitlines() if line.startswith("## ")), "")
    status["ahead_behind"] = first[3:].strip()
    return status


def _run(argv: list[str], *, cwd: Path | None = None, timeout_seconds: int = 10) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            text=True,
            capture_output=True,
            timeout=max(1, int(timeout_seconds)),
            check=False,
        )
        return {
            "argv": [shlex.quote(str(part)) for part in argv],
            "returncode": completed.returncode,
            "stdout": _limit_text(completed.stdout, MAX_CAPTURE_CHARS),
            "stderr": _limit_text(_redact(completed.stderr), MAX_ERROR_CHARS),
        }
    except Exception as exc:  # noqa: BLE001 - applet status should degrade to JSON, not crash.
        return {
            "argv": [shlex.quote(str(part)) for part in argv],
            "returncode": 124,
            "stdout": "",
            "stderr": _limit_text(_redact(f"{type(exc).__name__}: {exc}"), MAX_ERROR_CHARS),
        }


def _parse_status_fields(line: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in str(line or "").split():
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        fields[key.strip()] = value.strip()
    return fields


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
    for pattern in SECRET_TOKEN_PATTERNS:
        text = pattern.sub("<redacted-secret>", text)
    text = URL_CREDENTIAL_RE.sub(_redact_url_credentials, text)
    text = BEARER_TOKEN_RE.sub(r"\1 <redacted-secret>", text)
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


def _redact_secret_assignment_text(key: str, separator: str, value: str, *, original: str) -> str:
    key_token = key.strip().casefold().replace("-", "_").replace(" ", "_")
    normalized_value = value.strip().strip("\"'`").casefold()
    raw_value = value.strip()
    if normalized_value in SAFE_SECRET_VALUES:
        return original
    if key_token.endswith("_env") and re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", raw_value):
        return original
    if key_token in SAFE_SECRET_NUMERIC_METADATA and (raw_value.isdigit() or re.fullmatch(r"\d+/\d+", raw_value)):
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
