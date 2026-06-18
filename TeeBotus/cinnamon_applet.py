from __future__ import annotations

import argparse
import json
import os
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
MAX_CAPTURE_CHARS = 80_000
MAX_ERROR_CHARS = 2_000


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
    ok = runtime["returncode"] == 0 and unit.get("active_state") in {"active", "unknown"}
    return {
        "ok": ok,
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
        "qdrant_ready_collections": 0,
        "memory_semantic_ready": 0,
        "hf_pool": "",
    }
    for raw_line in str(output or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip() or "Unbenannt"
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
        fields = _parse_status_fields(line)
        status = fields.get("status", "")
        if status:
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
        elif line.startswith("codex_usage_account="):
            summary["codex_usage_accounts"] += 1
        elif line.startswith("gemini_free_tier_limits "):
            summary["gemini_free_tier"] = line
        elif line.startswith("qdrant="):
            summary["qdrant"] = line
        elif line.startswith("qdrant_collection="):
            summary["qdrant_collections"] += 1
            if fields.get("status") == "ready":
                summary["qdrant_ready_collections"] += 1
        elif line.startswith("memory_index=") and fields.get("semantic") == "ready":
            summary["memory_semantic_ready"] += 1
        elif line.startswith("hf_pool="):
            summary["hf_pool"] = line
    sections = {key: value for key, value in sections.items() if value}
    return {"sections": sections, "summary": summary, "status_counts": status_counts}


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
    lowered = text.lower()
    if any(marker in lowered for marker in ("api_key=", "token=", "password=", "secret=", "bearer ")):
        return "<redacted>"
    return text


def _limit_text(value: str, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit] + "\n<truncated>"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
