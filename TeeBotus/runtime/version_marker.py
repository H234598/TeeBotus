"""Small, local marker for the version of the currently running systemd bot."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


RUNTIME_VERSION_MARKER_SCHEMA_VERSION = 1
RUNTIME_VERSION_MARKER_FILENAME = "teebotus-runtime-version.json"
MAX_RUNTIME_VERSION_MARKER_BYTES = 8 * 1024
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


def runtime_version_marker_path(repo_root: Path | str) -> Path:
    return Path(repo_root).expanduser().resolve() / "data" / "runtime" / RUNTIME_VERSION_MARKER_FILENAME


def write_runtime_version_marker(
    repo_root: Path | str,
    *,
    version: str,
    pid: int,
    invocation_id: str,
    started_at: str | None = None,
) -> Path | None:
    """Write a marker only for a systemd invocation and return its path."""

    normalized_invocation_id = str(invocation_id or "").strip()
    normalized_version = str(version or "").strip()
    if not normalized_invocation_id or not _VERSION_RE.fullmatch(normalized_version):
        return None
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return None
    path = runtime_version_marker_path(repo_root)
    temporary = path.with_name(f".{path.name}.{pid}.tmp")
    payload = {
        "schema_version": RUNTIME_VERSION_MARKER_SCHEMA_VERSION,
        "version": normalized_version,
        "pid": pid,
        "invocation_id": normalized_invocation_id,
        "started_at": str(started_at or datetime.now(timezone.utc).isoformat()),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        return path
    except (OSError, ValueError, TypeError):
        try:
            temporary.unlink()
        except OSError:
            pass
        return None


def remove_runtime_version_marker(path: Path | str, *, pid: int, invocation_id: str) -> None:
    """Remove only the marker owned by this exact systemd invocation."""

    marker = Path(path)
    try:
        if marker.stat().st_size > MAX_RUNTIME_VERSION_MARKER_BYTES:
            return
        payload = json.loads(marker.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return
        if payload.get("pid") != pid or str(payload.get("invocation_id") or "").strip() != str(invocation_id or "").strip():
            return
        marker.unlink()
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return


def read_runtime_version_status(repo_root: Path | str, unit: Mapping[str, Any]) -> dict[str, str]:
    """Return a safe, non-secret status matched to the active systemd unit."""

    result = {
        "status": "missing",
        "version": "",
        "pid": "",
        "invocation_id": "",
        "started_at": "",
        "reason": "marker_missing",
    }
    path = runtime_version_marker_path(repo_root)
    try:
        if path.stat().st_size > MAX_RUNTIME_VERSION_MARKER_BYTES:
            result.update(status="invalid", reason="marker_too_large")
            return result
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return result
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        result.update(status="invalid", reason="marker_unreadable")
        return result
    if not isinstance(payload, dict):
        result.update(status="invalid", reason="marker_not_object")
        return result
    version = str(payload.get("version") or "").strip()
    marker_pid = _positive_int(payload.get("pid"))
    invocation_id = str(payload.get("invocation_id") or "").strip()
    started_at = str(payload.get("started_at") or "").strip()
    if payload.get("schema_version") != RUNTIME_VERSION_MARKER_SCHEMA_VERSION or not _VERSION_RE.fullmatch(version) or marker_pid is None or not invocation_id or not started_at:
        result.update(status="invalid", reason="marker_schema")
        return result
    unit_pid = _positive_int(unit.get("main_pid"))
    unit_invocation_id = str(unit.get("invocation_id") or "").strip()
    if unit_pid is None:
        result.update(status="unavailable", reason="unit_pid_missing")
        return result
    if marker_pid != unit_pid:
        result.update(status="stale", reason="pid_mismatch", version=version, pid=str(marker_pid), invocation_id=invocation_id, started_at=started_at)
        return result
    if unit_invocation_id and invocation_id != unit_invocation_id:
        result.update(status="stale", reason="invocation_mismatch", version=version, pid=str(marker_pid), invocation_id=invocation_id, started_at=started_at)
        return result
    result.update(status="matched", reason="marker_matches_unit", version=version, pid=str(marker_pid), invocation_id=invocation_id, started_at=started_at)
    return result


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
