from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from TeeBotus import __version__


DEFAULT_REPO_ROOT = Path.home() / "TeeBotus"
DEFAULT_CHANNELS = "telegram,signal"
DEFAULT_UNIT_NAME = "teebotus.service"
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
    status_parser.add_argument("--python", default=sys.executable)
    status_parser.add_argument("--timeout", type=int, default=DEFAULT_STATUS_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)
    if args.command == "status":
        payload = build_status_payload(
            repo_root=Path(args.repo_root),
            channels=str(args.channels),
            unit_name=str(args.unit),
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
) -> dict[str, Any]:
    root = repo_root.expanduser().resolve()
    runtime = _runtime_status(root, channels=channels, python_executable=python_executable, timeout_seconds=timeout_seconds)
    parsed_runtime = parse_runtime_status(runtime["stdout"])
    unit = _systemd_unit_status(unit_name)
    repo = _repo_status(root)
    ok = runtime["returncode"] == 0 and unit.get("active_state") in {"active", "unknown"}
    return {
        "ok": ok,
        "version": __version__,
        "repo": repo,
        "unit": unit,
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
        "gemini_free_tier": "",
        "qdrant": "",
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
        elif line.startswith("gemini_free_tier_limits "):
            summary["gemini_free_tier"] = line
        elif line.startswith("qdrant="):
            summary["qdrant"] = line
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
