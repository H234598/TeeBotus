from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import subprocess
import threading
import time
import sys
import tomllib
import uuid
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from inspect import isawaitable
from pathlib import Path
from urllib.parse import urlsplit
from typing import Any

from TeeBotus import __version__
from TeeBotus.admin.accounts_report import DEFAULT_INSTANCES_DIR, ReadOnlySecretToolInstanceSecretProvider, discover_instances, parse_csv
from TeeBotus.runtime.actions import SendAttachment
from TeeBotus.runtime.admin_accounts import resolve_admin_account_group
from TeeBotus.runtime.accounts import (
    INSTANCE_MAPPING_KEY_PURPOSE,
    INSTANCE_STATE_ACCOUNT_ID,
    AccountStore,
    AccountStoreError,
    InstanceSecretProvider,
)
from TeeBotus.runtime.proactive_agent import ProactiveSender, select_proactive_route

CODEX_HISTORY_SCHEMA_VERSION = 1
CODEX_HISTORY_TARGET_GROUP = "status_admins"
CODEX_HISTORY_DISPATCHABLE_STATUSES = frozenset({"queued"})
CODEX_HISTORY_BIBLIOTHEKAR_DIRNAME = "Codex_History_Bibliothek"
CODEX_HISTORY_BIBLIOTHEKAR_README = "README.md"

_OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b")
_TELEGRAM_TOKEN_RE = re.compile(r"\b\d{7,12}:[A-Za-z0-9_\-]{25,}\b")
_SAFE_PATH_SEGMENT_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*)")
_GENERIC_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|cookie)\b\s*[:=]\s*([^\s,;]{12,})"
)


def _safe_instance_name(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("instance name must not be empty")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in text):
        raise ValueError("instance name contains invalid control characters")
    if text in {".", ".."} or "/" in text or "\\" in text:
        raise ValueError("instance name must be a single path segment")
    return text


def _split_safe_relative_parts(value: str, *, operation: str) -> tuple[bool, tuple[str, ...]]:
    text = str(value).strip()
    if "\x00" in text:
        raise ValueError(f"{operation} contains invalid control character")
    if not text:
        raise ValueError(f"{operation} must not be empty")
    if "\\" in text:
        raise ValueError(f"{operation} contains invalid path separator: \\")
    if text == "/":
        return True, tuple()
    is_absolute = text.startswith("/")
    normalized = text[1:] if is_absolute else text
    if not normalized:
        raise ValueError(f"{operation} contains invalid path")
    raw_parts = normalized.split("/")
    parts: list[str] = []
    for part in raw_parts:
        if part in {"", "."}:
            continue
        if part == "..":
            raise ValueError(f"{operation} contains forbidden relative segment: {part}")
        if not _SAFE_PATH_SEGMENT_RE.fullmatch(part):
            raise ValueError(f"{operation} contains invalid path segment: {part}")
        parts.append(part)
    return is_absolute, tuple(parts)


def _safe_repo_root(value: Path, *, operation: str = "repo access") -> Path:
    text = str(value)
    if "\x00" in text:
        raise ValueError(f"{operation} contains invalid control character")
    is_absolute, parts = _split_safe_relative_parts(text, operation=operation)
    if is_absolute:
        return Path("/").joinpath(*parts).resolve() if parts else Path("/").resolve()
    if not parts:
        return Path.cwd()
    return Path.cwd().joinpath(*parts).resolve()


def _safe_output_path(output: str) -> Path:
    is_absolute, parts = _split_safe_relative_parts(output, operation="output path")
    if is_absolute or not parts:
        raise ValueError(f"output path must be a safe relative path: {output}")
    root = Path.cwd().resolve()
    output_path = Path(*parts)
    target = (root / output_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"output path escapes the working directory: {output}") from exc
    return target


@dataclass(frozen=True)
class CodexHistoryReportOptions:
    instances_dir: Path
    instances: tuple[str, ...] = ()
    repo: str = ""
    summary_limit: int = 20
    provider: InstanceSecretProvider | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append_codex_history_summary(
    store: AccountStore,
    *,
    repo_root: str | Path,
    title: str,
    bullets: Sequence[str] = (),
    changed_files: Sequence[str] = (),
    tests: Sequence[str] = (),
    session_id: str = "",
    source: str = "manual_cli",
    status: str = "queued",
    target_group: str = CODEX_HISTORY_TARGET_GROUP,
    codex_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    repo = build_repo_metadata(repo_root)
    version = resolve_repo_version(repo["repo_root"])
    timestamp = utc_now()
    account_id = INSTANCE_STATE_ACCOUNT_ID
    redacted_title = redact_codex_history_text(title).strip() or "Codex run summary"
    redacted_bullets = [redact_codex_history_text(item).strip() for item in bullets if str(item or "").strip()]
    redacted_changed_files = [redact_codex_history_text(item).strip() for item in changed_files if str(item or "").strip()]
    redacted_tests = [redact_codex_history_text(item).strip() for item in tests if str(item or "").strip()]

    with store.codex_history_outbox_lock(account_id):
        rows = store.read_codex_history_outbox(account_id)
        summary_number = _next_summary_number_for_repo(rows, repo["repo_id"])
        summary_prefix = _summary_prefix(version["semver"], summary_number)
        markdown = build_codex_history_markdown(
            summary_prefix=summary_prefix,
            title=redacted_title,
            repo=repo,
            version=version,
            bullets=redacted_bullets,
            changed_files=redacted_changed_files,
            tests=redacted_tests,
            created_at=timestamp,
        )
        codex_payload = {
            "session_id": redact_codex_history_text(session_id).strip(),
            "cwd": repo["repo_root"],
            "finished_at": timestamp,
        }
        if isinstance(codex_metadata, Mapping):
            codex_payload.update({str(key): redact_codex_history_text(value).strip() for key, value in codex_metadata.items()})
        item = {
            "id": _unique_history_id(rows),
            "schema_version": CODEX_HISTORY_SCHEMA_VERSION,
            "kind": "codex_run_summary",
            "source": source,
            "status": status,
            "created_at": timestamp,
            "updated_at": timestamp,
            "project": repo,
            "version": {
                "semver": version["semver"],
                "tag": version["tag"],
                "summary_number": summary_number,
                "summary_prefix": summary_prefix,
            },
            "codex": codex_payload,
            "summary": {
                "title": redacted_title,
                "markdown": markdown,
                "bullets": redacted_bullets,
                "changed_files": redacted_changed_files,
                "tests": redacted_tests,
            },
            "delivery": {
                "target_group": target_group,
                "attempts": 0,
                "last_attempt_at": "",
                "sent_at": "",
                "accepted_at": "",
                "delivered_at": "",
                "acknowledged_at": "",
            },
            "indexing": {
                "indexable": True,
                "repo_history": True,
                "keywords": _history_keywords(repo, version, redacted_title, redacted_bullets, redacted_changed_files, redacted_tests),
            },
            "status_history": [
                {
                    "at": timestamp,
                    "status": status,
                    "reason": "codex_history_summary_created",
                }
            ],
            "summary_number": summary_number,
            "summary_prefix": summary_prefix,
        }
        rows.append(item)
        store.write_codex_history_outbox(account_id, rows)
        _upsert_project(store, account_id, repo, item, timestamp)
        return dict(item)


async def dispatch_codex_history_outbox(
    store: AccountStore,
    *,
    instance_name: str,
    account_ids: Sequence[str] = (),
    senders: Mapping[str, ProactiveSender] | None = None,
    env: Mapping[str, str] | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    timestamp = _iso_timestamp(now)
    resolved_senders = senders or {}
    candidate_account_ids = _codex_history_dispatch_account_ids(store, instance_name=instance_name, account_ids=account_ids, env=env)
    rows = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
    items = [row for row in rows if _codex_history_item_dispatchable(row)]
    if limit > 0:
        items = items[:limit]
    result_rows: list[dict[str, Any]] = []
    for item in items:
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            continue
        if dry_run:
            dry_rows = _dry_run_dispatch_rows(item, candidate_account_ids, store)
            result_rows.extend(dry_rows)
            continue
        _update_codex_history_item_status(store, item_id, "dispatching", reason="worker_claimed", now=timestamp, increment_attempt=True)
        item_results: list[dict[str, Any]] = []
        for account_id in candidate_account_ids:
            item_results.append(
                await _dispatch_codex_history_item_to_account(
                    store,
                    item,
                    account_id,
                    instance_name=instance_name,
                    senders=resolved_senders,
                    now=timestamp,
                )
            )
        if not item_results:
            item_results.append(
                _record_codex_history_dispatch_result(
                    store,
                    item,
                    "",
                    status="skipped",
                    reason="no_recipient_accounts",
                    now=timestamp,
                    instance_name=instance_name,
                )
            )
        final_status = _overall_dispatch_status(item_results)
        final_reason = _overall_dispatch_reason(item_results)
        _update_codex_history_item_status(store, item_id, final_status, reason=final_reason, now=timestamp, dispatch_results=item_results)
        result_rows.extend(item_results)
    return {
        "ok": not any(row.get("status") == "failed" for row in result_rows),
        "dry_run": dry_run,
        "instance": instance_name,
        "generated_at": timestamp,
        "items": result_rows,
        "status_counts": _status_counts(result_rows),
    }


def acknowledge_codex_history_item(
    store: AccountStore,
    item_id: str,
    *,
    instance_name: str,
    account_id: str = "",
    message_ref: str = "",
    now: datetime | None = None,
    reason: str = "manual_acknowledgement",
) -> dict[str, Any]:
    timestamp = _iso_timestamp(now)
    normalized_item_id = str(item_id or "").strip()
    if not normalized_item_id:
        return {"ok": False, "status": "not_found", "item_id": "", "reason": "missing_item_id"}
    item = _find_codex_history_item_by_id(store, normalized_item_id)
    if item is None:
        return {"ok": False, "status": "not_found", "item_id": normalized_item_id, "reason": "missing_item"}
    dispatch_result = _record_codex_history_dispatch_result(
        store,
        item,
        str(account_id or "").strip(),
        status="acknowledged",
        reason=reason,
        now=timestamp,
        instance_name=instance_name,
        message_ref=message_ref,
    )
    _update_codex_history_item_status(
        store,
        normalized_item_id,
        "acknowledged",
        reason=reason,
        now=timestamp,
        dispatch_results=[dispatch_result],
    )
    return {
        "ok": True,
        "status": "acknowledged",
        "item_id": normalized_item_id,
        "dispatch_result": dispatch_result,
    }


def record_codex_history_reply(
    store: AccountStore,
    *,
    instance_name: str,
    channel: str,
    chat_id: str,
    reply_to_message_ref: str,
    account_id: str = "",
    reply_message_ref: str = "",
    reply_text: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Mark a dispatched history item as seen when a user replies to it."""

    normalized_channel = str(channel or "").strip().casefold()
    normalized_chat_id = str(chat_id or "").strip()
    normalized_reply_to = str(reply_to_message_ref or "").strip()
    if not normalized_channel or not normalized_chat_id or not normalized_reply_to:
        return {"ok": False, "status": "not_found", "reason": "missing_reply_target"}
    match = _find_codex_history_dispatch_for_message(
        store,
        instance_name=instance_name,
        channel=normalized_channel,
        chat_id=normalized_chat_id,
        message_ref=normalized_reply_to,
        account_id=account_id,
    )
    if match is None:
        return {"ok": False, "status": "not_found", "reason": "no_matching_dispatch"}
    item_id = str(match.get("codex_history_item_id") or "").strip()
    item = _find_codex_history_item_by_id(store, item_id)
    if item is None:
        return {"ok": False, "status": "not_found", "reason": "missing_history_item", "item_id": item_id}
    timestamp = _iso_timestamp(now)
    route = {"channel": normalized_channel, "chat_id": normalized_chat_id}
    matched_account_id = str(match.get("account_id") or account_id or "").strip()
    delivered = _record_codex_history_dispatch_result(
        store,
        item,
        matched_account_id,
        status="delivered",
        reason=f"{normalized_channel}_reply_observed",
        now=timestamp,
        instance_name=instance_name,
        route=route,
        message_ref=normalized_reply_to,
        reply_message_ref=reply_message_ref,
        reply_text_preview=reply_text,
    )
    _update_codex_history_item_status(
        store,
        item_id,
        "delivered",
        reason=f"{normalized_channel}_reply_observed",
        now=timestamp,
        dispatch_results=[delivered],
    )
    acknowledged = _record_codex_history_dispatch_result(
        store,
        item,
        matched_account_id,
        status="acknowledged",
        reason=f"{normalized_channel}_reply_acknowledged",
        now=timestamp,
        instance_name=instance_name,
        route=route,
        message_ref=normalized_reply_to,
        reply_message_ref=reply_message_ref,
        reply_text_preview=reply_text,
    )
    _update_codex_history_item_status(
        store,
        item_id,
        "acknowledged",
        reason=f"{normalized_channel}_reply_acknowledged",
        now=timestamp,
        dispatch_results=[acknowledged],
    )
    return {
        "ok": True,
        "status": "acknowledged",
        "item_id": item_id,
        "delivered_result": delivered,
        "acknowledged_result": acknowledged,
    }


def record_codex_history_delivery_receipt(
    store: AccountStore,
    *,
    instance_name: str,
    channel: str,
    chat_id: str,
    message_ref: str,
    account_id: str = "",
    receipt_type: str = "delivered",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Mark a dispatched history item as delivered from a native channel receipt."""

    normalized_channel = str(channel or "").strip().casefold()
    normalized_chat_id = str(chat_id or "").strip()
    normalized_message_ref = str(message_ref or "").strip()
    normalized_receipt_type = _normalize_delivery_receipt_type(receipt_type)
    if not normalized_channel or not normalized_chat_id or not normalized_message_ref:
        return {"ok": False, "status": "not_found", "reason": "missing_receipt_target"}
    match = _find_codex_history_dispatch_for_message(
        store,
        instance_name=instance_name,
        channel=normalized_channel,
        chat_id=normalized_chat_id,
        message_ref=normalized_message_ref,
        account_id=account_id,
    )
    if match is None:
        return {"ok": False, "status": "not_found", "reason": "no_matching_dispatch"}
    item_id = str(match.get("codex_history_item_id") or "").strip()
    item = _find_codex_history_item_by_id(store, item_id)
    if item is None:
        return {"ok": False, "status": "not_found", "reason": "missing_history_item", "item_id": item_id}
    timestamp = _iso_timestamp(now)
    route = {"channel": normalized_channel, "chat_id": normalized_chat_id}
    matched_account_id = str(match.get("account_id") or account_id or "").strip()
    reason = f"{normalized_channel}_{normalized_receipt_type}_receipt"
    delivered = _record_codex_history_dispatch_result(
        store,
        item,
        matched_account_id,
        status="delivered",
        reason=reason,
        now=timestamp,
        instance_name=instance_name,
        route=route,
        message_ref=normalized_message_ref,
        receipt_type=normalized_receipt_type,
    )
    current_status = str(item.get("status") or "").strip().casefold()
    if current_status != "acknowledged":
        _update_codex_history_item_status(
            store,
            item_id,
            "delivered",
            reason=reason,
            now=timestamp,
            dispatch_results=[delivered],
        )
    return {
        "ok": True,
        "status": "delivered" if current_status != "acknowledged" else "acknowledged",
        "item_id": item_id,
        "delivered_result": delivered,
    }


def import_codex_session_file(store: AccountStore, session_file: str | Path) -> dict[str, Any]:
    path = _safe_repo_root(Path(session_file), operation="session file")
    parsed = _parse_codex_session_file(path)
    if not parsed["final_text"]:
        return {"status": "skipped", "reason": "missing_final_text", "path": str(path)}
    repo_root = str(parsed["cwd"] or path.parent)
    final_text = str(parsed["final_text"])
    final_hash = "sha256:" + hashlib.sha256(final_text.encode("utf-8")).hexdigest()
    session_id = str(parsed["session_id"] or path.stem)
    turn_id = str(parsed["turn_id"] or "")
    dedupe_key = _codex_session_dedupe_key(session_id=session_id, turn_id=turn_id, final_message_hash=final_hash)
    existing = _find_codex_history_by_dedupe_key(store, dedupe_key)
    if existing is not None:
        return {"status": "duplicate", "reason": "dedupe_key", "item": existing, "path": str(path)}
    title = _codex_session_title(final_text)
    bullets = _codex_session_bullets(final_text)
    tests = _codex_session_tests(final_text)
    item = append_codex_history_summary(
        store,
        repo_root=repo_root,
        title=title,
        bullets=bullets,
        tests=tests,
        session_id=session_id,
        source="codex_session_watcher",
        codex_metadata={
            "turn_id": turn_id,
            "dedupe_key": dedupe_key,
            "final_message_hash": final_hash,
            "source_path_hash": "sha256:" + hashlib.sha256(str(path).encode("utf-8")).hexdigest(),
            "source_mtime": str(parsed.get("source_mtime") or ""),
        },
    )
    return {"status": "imported", "item": item, "path": str(path)}


def import_codex_session_roots(store: AccountStore, roots: Sequence[str | Path], *, limit: int = 1000) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for session_file in _iter_codex_session_files(roots, limit=limit):
        results.append(import_codex_session_file(store, session_file))
    return {
        "ok": not any(result.get("status") == "error" for result in results),
        "items": results,
        "status_counts": _status_counts(results),
    }


def watch_codex_session_roots(
    store: AccountStore,
    roots: Sequence[str | Path],
    *,
    poll_interval_seconds: float = 1.0,
    max_iterations: int = 1,
    follow: bool = False,
    event_mode: str = "poll",
    limit: int = 1000,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    iterations = 0
    if not follow and max_iterations < 1:
        max_iterations = 1
    if poll_interval_seconds < 0:
        poll_interval_seconds = 0.0
    normalized_event_mode = _normalize_watch_event_mode(event_mode)
    items: list[dict[str, Any]] = []
    skipped_unchanged = 0
    last_snapshot: tuple[tuple[str, int, int], ...] | None = None
    while True:
        iterations += 1
        current_snapshot = _codex_session_roots_snapshot(roots, limit=limit) if normalized_event_mode != "poll" else None
        should_scan = normalized_event_mode == "poll" or last_snapshot is None or current_snapshot != last_snapshot
        if should_scan:
            report = import_codex_session_roots(store, roots, limit=limit)
            iteration_items = report.get("items", [])
            if isinstance(iteration_items, list):
                items.extend(iteration_items)
        else:
            skipped_unchanged += 1
        if current_snapshot is not None:
            last_snapshot = current_snapshot
        if not follow and max_iterations > 0 and iterations >= max_iterations:
            break
        if poll_interval_seconds > 0:
            _wait_for_codex_session_change(
                roots,
                poll_interval_seconds=float(poll_interval_seconds),
                event_mode=normalized_event_mode,
                sleep=sleep,
            )
    return {
        "ok": not any(item.get("status") == "error" for item in items),
        "iterations": iterations,
        "follow": bool(follow),
        "event_mode": normalized_event_mode,
        "skipped_unchanged_iterations": skipped_unchanged,
        "items": items,
        "status_counts": _status_counts(items),
    }


def default_codex_session_roots() -> tuple[Path, ...]:
    roots = [Path.home() / ".codex" / "sessions"]
    agents_root = Path.home() / ".codex-agents"
    if agents_root.is_dir():
        roots.extend(path / ".codex" / "sessions" for path in sorted(agents_root.iterdir()) if path.is_dir())
    return tuple(roots)


def export_codex_history_bibliothekar_docs(
    store: AccountStore,
    *,
    instance_dir: str | Path,
    instance_name: str,
    repo: str = "",
    limit: int = 0,
    overwrite: bool = True,
) -> dict[str, Any]:
    """Export redacted Codex history as admin-only Markdown documents.

    The destination intentionally differs from data/Bibliothek so normal user-facing
    Bibliothekar retrieval cannot expose Codex run history by accident.
    """

    safe_instance_name = _safe_instance_name(instance_name)
    safe_instance_dir = _safe_repo_root(Path(instance_dir), operation="instance directory")
    destination = _codex_history_bibliothekar_root(safe_instance_dir)
    rows = _filter_outbox(store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID), repo)
    items = [item for item in rows if _codex_history_item_indexable(item)]
    items = sorted(items, key=_summary_sort_key)
    if limit > 0:
        items = items[-int(limit) :]
    destination.mkdir(parents=True, exist_ok=True)
    _write_codex_history_bibliothekar_readme(destination, safe_instance_name)
    exported: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in items:
        project = item.get("project", {})
        if not isinstance(project, Mapping):
            project = {}
        repo_name = str(project.get("repo_name") or "project").strip() or "project"
        repo_dir = destination / "codex_history" / _safe_filename_component(repo_name, default="project")
        repo_dir.mkdir(parents=True, exist_ok=True)
        target = (repo_dir / _codex_history_bibliothekar_filename(item)).resolve()
        try:
            target.relative_to(destination.resolve())
        except ValueError as exc:
            raise ValueError("codex history export target escapes admin bibliothekar root") from exc
        if target.exists() and not overwrite:
            skipped.append({"item_id": str(item.get("id") or ""), "path": str(target), "reason": "exists"})
            continue
        text = _codex_history_bibliothekar_markdown(item)
        target.write_text(text, encoding="utf-8")
        exported.append(
            {
                "item_id": str(item.get("id") or ""),
                "summary_prefix": str(item.get("summary_prefix") or ""),
                "repo_name": repo_name,
                "path": str(target),
                "categories": _codex_history_bibliothekar_categories(item),
            }
        )
    return {
        "ok": True,
        "instance": safe_instance_name,
        "destination": str(destination),
        "exported": len(exported),
        "skipped": len(skipped),
        "files": exported,
        "skipped_files": skipped,
    }


def codex_history_bibliothekar_chunks(
    store: AccountStore,
    *,
    instance_dir: str | Path,
    instance_name: str,
    repo: str = "",
    limit: int = 0,
) -> tuple[dict[str, Any], ...]:
    safe_instance_name = _safe_instance_name(instance_name)
    safe_instance_dir = _safe_repo_root(Path(instance_dir), operation="instance directory")
    destination = _codex_history_bibliothekar_root(safe_instance_dir)
    rows = _filter_outbox(store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID), repo)
    items = [item for item in rows if _codex_history_item_indexable(item)]
    items = sorted(items, key=_summary_sort_key)
    if limit > 0:
        items = items[-int(limit) :]
    chunks: list[dict[str, Any]] = []
    for item in items:
        chunks.append(_codex_history_bibliothekar_chunk(item, destination=destination, instance_name=safe_instance_name))
    return tuple(chunks)


def build_repo_metadata(repo_root: str | Path) -> dict[str, Any]:
    root = _safe_repo_root(Path(repo_root), operation="repository root")
    git_root = _git_output(root, "rev-parse", "--show-toplevel")
    if git_root:
        root = _safe_repo_root(Path(git_root), operation="repository root from git")
    remote_url = _git_output(root, "remote", "get-url", "origin")
    branch = _git_output(root, "rev-parse", "--abbrev-ref", "HEAD")
    head_commit = _git_output(root, "rev-parse", "HEAD")
    status = _git_output(root, "status", "--porcelain")
    repo_name = _repo_name(root, remote_url)
    identity = _normalize_remote_url(remote_url) or str(root)
    return {
        "repo_id": "sha256:" + hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        "repo_name": repo_name,
        "repo_root": str(root),
        "remote_url": remote_url,
        "provider": _repo_provider(remote_url),
        "branch": branch,
        "head_commit": head_commit,
        "dirty": bool(status.strip()),
    }


def resolve_repo_version(repo_root: str | Path) -> dict[str, str]:
    root = _safe_repo_root(Path(repo_root), operation="repository root")
    semver = _pyproject_version(root) or _version_file(root) or _git_latest_semver_tag(root) or _teebotus_version(root) or "untagged"
    tag = semver if semver.startswith("v") or semver == "untagged" else f"v{semver}"
    return {"semver": semver.removeprefix("v") if semver != "untagged" else semver, "tag": tag}


def redact_codex_history_text(value: object) -> str:
    text = str(value or "")
    text = _OPENAI_KEY_RE.sub("<redacted:openai-key>", text)
    text = _TELEGRAM_TOKEN_RE.sub("<redacted:telegram-token>", text)
    text = _GENERIC_SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=<redacted:secret>", text)
    return text


def build_codex_history_markdown(
    *,
    summary_prefix: str,
    title: str,
    repo: Mapping[str, Any],
    version: Mapping[str, str],
    bullets: Sequence[str],
    changed_files: Sequence[str],
    tests: Sequence[str],
    created_at: str,
) -> str:
    lines = [
        f"# {summary_prefix} {title}",
        "",
        f"- Projekt: `{repo.get('repo_name', '')}`",
        f"- Repo: `{repo.get('repo_root', '')}`",
        f"- Version: `{version.get('tag', '')}`",
        f"- Commit: `{repo.get('head_commit', '') or '<none>'}`",
        f"- Branch: `{repo.get('branch', '') or '<none>'}`",
        f"- Erstellt: `{created_at}`",
        "",
        "## Zusammenfassung",
    ]
    if bullets:
        lines.extend(f"- {bullet}" for bullet in bullets)
    else:
        lines.append("- Keine Detailpunkte angegeben.")
    lines.append("")
    lines.append("## Geaenderte Dateien")
    if changed_files:
        lines.extend(f"- `{path}`" for path in changed_files)
    else:
        lines.append("- Keine Dateien angegeben.")
    lines.append("")
    lines.append("## Verifikation")
    if tests:
        lines.extend(f"- `{test}`" for test in tests)
    else:
        lines.append("- Keine Tests angegeben.")
    lines.append("")
    return "\n".join(lines)


def _codex_history_dispatch_account_ids(
    store: AccountStore,
    *,
    instance_name: str,
    account_ids: Sequence[str],
    env: Mapping[str, str] | None,
) -> tuple[str, ...]:
    candidates = tuple(str(account_id or "").strip().casefold() for account_id in account_ids if str(account_id or "").strip())
    if not candidates:
        group = resolve_admin_account_group(instance_name=instance_name, env=env)
        candidates = tuple(group.account_ids)
    seen: set[str] = set()
    result: list[str] = []
    for account_id in candidates:
        if account_id in seen:
            continue
        seen.add(account_id)
        result.append(account_id)
    return tuple(result)


def _codex_history_item_dispatchable(item: Mapping[str, Any]) -> bool:
    if not isinstance(item, Mapping):
        return False
    if str(item.get("kind") or "").strip() != "codex_run_summary":
        return False
    status = str(item.get("status") or "queued").strip().casefold()
    return status in CODEX_HISTORY_DISPATCHABLE_STATUSES


def _dry_run_dispatch_rows(item: Mapping[str, Any], account_ids: Sequence[str], store: AccountStore) -> list[dict[str, Any]]:
    item_id = str(item.get("id") or "").strip()
    rows: list[dict[str, Any]] = []
    for account_id in account_ids:
        route = _safe_select_route(store, account_id)
        channel = str(route.get("channel") or "").strip().casefold() if isinstance(route, Mapping) else ""
        rows.append(
            {
                "codex_history_item_id": item_id,
                "account_id": account_id,
                "status": "would_send" if route is not None else "would_skip",
                "reason": "" if route is not None else "no_private_route",
                "channel": channel,
                "summary_prefix": item.get("summary_prefix", ""),
            }
        )
    if not rows:
        rows.append(
            {
                "codex_history_item_id": item_id,
                "account_id": "",
                "status": "would_skip",
                "reason": "no_recipient_accounts",
                "channel": "",
                "summary_prefix": item.get("summary_prefix", ""),
            }
        )
    return rows


async def _dispatch_codex_history_item_to_account(
    store: AccountStore,
    item: Mapping[str, Any],
    account_id: str,
    *,
    instance_name: str,
    senders: Mapping[str, ProactiveSender],
    now: str,
) -> dict[str, Any]:
    route = _safe_select_route(store, account_id)
    if route is None:
        return _record_codex_history_dispatch_result(
            store,
            item,
            account_id,
            status="skipped",
            reason="no_private_route",
            now=now,
            instance_name=instance_name,
        )
    channel = str(route.get("channel") or "").strip().casefold()
    chat_id = str(route.get("chat_id") or "").strip()
    if not channel or not chat_id:
        return _record_codex_history_dispatch_result(
            store,
            item,
            account_id,
            status="skipped",
            reason="invalid_route",
            now=now,
            instance_name=instance_name,
            route=route,
        )
    sender = _sender_for_channel(senders, channel)
    if sender is None:
        return _record_codex_history_dispatch_result(
            store,
            item,
            account_id,
            status="failed",
            reason=f"missing_sender:{channel}",
            now=now,
            instance_name=instance_name,
            route=route,
        )
    action = _codex_history_attachment_action(item, chat_id)
    try:
        sent_ref = sender(
            route,
            action,
            {
                "source": "codex_history_dispatch",
                "account_id": account_id,
                "codex_history_item_id": str(item.get("id") or ""),
            },
        )
        if isawaitable(sent_ref):
            sent_ref = await sent_ref
    except Exception as exc:  # noqa: BLE001 - adapter exception types differ per channel.
        return _record_codex_history_dispatch_result(
            store,
            item,
            account_id,
            status="failed",
            reason=f"send_error:{type(exc).__name__}",
            now=now,
            instance_name=instance_name,
            route=route,
        )
    return _record_codex_history_dispatch_result(
        store,
        item,
        account_id,
        status="accepted",
        reason="accepted",
        now=now,
        instance_name=instance_name,
        route=route,
        message_ref=str(sent_ref or ""),
    )


def _safe_select_route(store: AccountStore, account_id: str) -> dict[str, Any] | None:
    try:
        return select_proactive_route(store, account_id)
    except (AccountStoreError, OSError, ValueError):
        return None


def _sender_for_channel(senders: Mapping[str, ProactiveSender], channel: str) -> ProactiveSender | None:
    normalized_channel = str(channel or "").strip().casefold()
    for key, sender in senders.items():
        if str(key or "").strip().casefold() == normalized_channel and callable(sender):
            return sender
    return None


def _codex_history_attachment_action(item: Mapping[str, Any], chat_id: str) -> SendAttachment:
    summary = item.get("summary", {})
    project = item.get("project", {})
    version = item.get("version", {})
    if not isinstance(summary, Mapping):
        summary = {}
    if not isinstance(project, Mapping):
        project = {}
    if not isinstance(version, Mapping):
        version = {}
    markdown = str(summary.get("markdown") or "").strip()
    if not markdown:
        markdown = f"# {item.get('summary_prefix', 'untagged')} {summary.get('title', 'Codex run summary')}\n"
    repo_name = str(project.get("repo_name") or "project").strip() or "project"
    semver = str(version.get("semver") or "untagged").strip() or "untagged"
    caption = f"Release {repo_name} {semver}"
    filename = _codex_history_markdown_filename(repo_name, semver, item.get("summary_number") or version.get("summary_number") or 1)
    return SendAttachment(
        str(chat_id),
        markdown.encode("utf-8"),
        filename,
        "text/markdown",
        caption=caption,
        track=False,
    )


def _codex_history_markdown_filename(repo_name: str, semver: str, summary_number: object) -> str:
    safe_repo = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(repo_name or "project")).strip("._-") or "project"
    safe_semver = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(semver or "untagged")).strip("._-") or "untagged"
    try:
        number = int(summary_number)
    except (TypeError, ValueError):
        number = 1
    return f"{safe_repo}_release_{safe_semver}_{max(1, number):04d}.md"


def _record_codex_history_dispatch_result(
    store: AccountStore,
    item: Mapping[str, Any],
    account_id: str,
    *,
    status: str,
    reason: str,
    now: str,
    instance_name: str,
    route: Mapping[str, Any] | None = None,
    message_ref: str = "",
    reply_message_ref: str = "",
    reply_text_preview: str = "",
    receipt_type: str = "",
) -> dict[str, Any]:
    route = route if isinstance(route, Mapping) else {}
    version = item.get("version", {})
    if not isinstance(version, Mapping):
        version = {}
    row = {
        "schema_version": CODEX_HISTORY_SCHEMA_VERSION,
        "codex_history_item_id": str(item.get("id") or ""),
        "account_id": str(account_id or ""),
        "instance": instance_name,
        "status": str(status or "").strip().casefold(),
        "reason": str(reason or "").strip(),
        "channel": str(route.get("channel") or "").strip().casefold(),
        "chat_id": str(route.get("chat_id") or "").strip(),
        "message_ref": str(message_ref or "").strip(),
        "summary_prefix": str(item.get("summary_prefix") or version.get("summary_prefix") or ""),
        "summary_number": item.get("summary_number") or version.get("summary_number"),
        "created_at": now,
        "updated_at": now,
    }
    normalized_reply_ref = str(reply_message_ref or "").strip()
    if normalized_reply_ref:
        row["reply_message_ref"] = normalized_reply_ref
    normalized_reply_preview = redact_codex_history_text(reply_text_preview).strip()
    if normalized_reply_preview:
        row["reply_text_preview"] = normalized_reply_preview[:240]
    normalized_receipt_type = _normalize_delivery_receipt_type(receipt_type) if str(receipt_type or "").strip() else ""
    if normalized_receipt_type:
        row["receipt_type"] = normalized_receipt_type
    store.append_codex_history_dispatch_result(INSTANCE_STATE_ACCOUNT_ID, row)
    return row


def _normalize_delivery_receipt_type(value: str) -> str:
    normalized = str(value or "delivered").strip().casefold()
    if normalized in {"read", "viewed", "delivered"}:
        return normalized
    return "delivered"


def _update_codex_history_item_status(
    store: AccountStore,
    item_id: str,
    status: str,
    *,
    reason: str,
    now: str,
    increment_attempt: bool = False,
    dispatch_results: Sequence[Mapping[str, Any]] = (),
) -> None:
    normalized_status = str(status or "").strip().casefold()
    normalized_reason = str(reason or "").strip()
    with store.codex_history_outbox_lock(INSTANCE_STATE_ACCOUNT_ID):
        rows = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
        for item in rows:
            if not isinstance(item, dict) or str(item.get("id") or "") != str(item_id or ""):
                continue
            item["status"] = normalized_status
            item["updated_at"] = now
            delivery = item.setdefault("delivery", {})
            if not isinstance(delivery, dict):
                delivery = {}
                item["delivery"] = delivery
            if increment_attempt:
                try:
                    delivery["attempts"] = int(delivery.get("attempts") or 0) + 1
                except (TypeError, ValueError):
                    delivery["attempts"] = 1
                delivery["last_attempt_at"] = now
            if normalized_status == "dispatching":
                delivery["sent_at"] = now
            if normalized_status == "accepted":
                delivery.setdefault("sent_at", now)
                delivery["accepted_at"] = now
            if normalized_status == "delivered":
                delivery.setdefault("sent_at", now)
                delivery.setdefault("accepted_at", now)
                delivery["delivered_at"] = now
            if normalized_status == "acknowledged":
                delivery.setdefault("sent_at", now)
                delivery.setdefault("accepted_at", now)
                delivery.setdefault("delivered_at", now)
                delivery["acknowledged_at"] = now
            if normalized_reason:
                item["last_reason"] = normalized_reason
            if dispatch_results:
                item["last_dispatch_results"] = [dict(row) for row in dispatch_results]
            history = item.setdefault("status_history", [])
            if not isinstance(history, list):
                history = []
                item["status_history"] = history
            history.append({"at": now, "status": normalized_status, "reason": normalized_reason})
            break
        store.write_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID, rows)


def _overall_dispatch_status(rows: Sequence[Mapping[str, Any]]) -> str:
    statuses = {str(row.get("status") or "").strip().casefold() for row in rows if isinstance(row, Mapping)}
    if "acknowledged" in statuses:
        return "acknowledged"
    if "delivered" in statuses:
        return "delivered"
    if "accepted" in statuses:
        return "accepted"
    if "failed" in statuses:
        return "failed"
    if "skipped" in statuses:
        return "skipped"
    return "failed"


def _overall_dispatch_reason(rows: Sequence[Mapping[str, Any]]) -> str:
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("status") or "").strip().casefold() in {"failed", "skipped", "accepted", "delivered", "acknowledged"}:
            return str(row.get("reason") or "").strip()
    return ""


def _iso_timestamp(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse_codex_session_file(path: Path) -> dict[str, Any]:
    session_id = ""
    turn_id = ""
    cwd = ""
    final_text = ""
    try:
        source_mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
    except OSError:
        source_mtime = ""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {"session_id": "", "turn_id": "", "cwd": "", "final_text": "", "source_mtime": source_mtime}
    for raw_line in lines:
        if not raw_line.strip():
            continue
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, Mapping):
            continue
        payload = row.get("payload", {})
        if not isinstance(payload, Mapping):
            payload = {}
        row_type = str(row.get("type") or payload.get("type") or "").strip()
        if row_type == "session_meta":
            session_id = str(payload.get("id") or session_id or "").strip()
            cwd = str(payload.get("cwd") or cwd or "").strip()
        elif row_type == "turn_context":
            turn_id = str(payload.get("turn_id") or turn_id or "").strip()
        else:
            cwd = str(payload.get("cwd") or cwd or "").strip()
        text = _assistant_text_from_codex_payload(payload)
        if text:
            final_text = text
    return {
        "session_id": session_id,
        "turn_id": turn_id,
        "cwd": cwd,
        "final_text": final_text,
        "source_mtime": source_mtime,
    }


def _assistant_text_from_codex_payload(payload: Mapping[str, Any]) -> str:
    role = str(payload.get("role") or "").strip()
    payload_type = str(payload.get("type") or "").strip()
    if role != "assistant" and payload_type not in {"message", "response_item"}:
        return ""
    if role and role != "assistant":
        return ""
    content = payload.get("content")
    return _text_from_codex_content(content).strip()


def _text_from_codex_content(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, Mapping):
        if isinstance(content.get("text"), str):
            return str(content["text"])
        return ""
    if isinstance(content, Sequence) and not isinstance(content, (str, bytes, bytearray)):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, Mapping):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part for part in parts if part.strip())
    return ""


def _codex_session_dedupe_key(*, session_id: str, turn_id: str, final_message_hash: str) -> str:
    raw = "\n".join((str(session_id or ""), str(turn_id or ""), str(final_message_hash or "")))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _find_codex_history_by_dedupe_key(store: AccountStore, dedupe_key: str) -> dict[str, Any] | None:
    for item in store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID):
        if not isinstance(item, Mapping):
            continue
        codex = item.get("codex", {})
        if isinstance(codex, Mapping) and str(codex.get("dedupe_key") or "") == dedupe_key:
            return dict(item)
    return None


def _find_codex_history_item_by_id(store: AccountStore, item_id: str) -> dict[str, Any] | None:
    for item in store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID):
        if not isinstance(item, Mapping):
            continue
        if str(item.get("id") or "").strip() == str(item_id or "").strip():
            return dict(item)
    return None


def _find_codex_history_dispatch_for_message(
    store: AccountStore,
    *,
    instance_name: str,
    channel: str,
    chat_id: str,
    message_ref: str,
    account_id: str = "",
) -> dict[str, Any] | None:
    normalized_instance = str(instance_name or "").strip()
    normalized_channel = str(channel or "").strip().casefold()
    normalized_chat_id = str(chat_id or "").strip()
    normalized_message_ref = str(message_ref or "").strip()
    normalized_account_id = str(account_id or "").strip().casefold()
    if not normalized_channel or not normalized_chat_id or not normalized_message_ref:
        return None
    for row in reversed(store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID)):
        if not isinstance(row, Mapping):
            continue
        if normalized_instance and str(row.get("instance") or "").strip() != normalized_instance:
            continue
        if str(row.get("channel") or "").strip().casefold() != normalized_channel:
            continue
        if str(row.get("chat_id") or "").strip() != normalized_chat_id:
            continue
        if str(row.get("message_ref") or "").strip() != normalized_message_ref:
            continue
        if normalized_account_id and str(row.get("account_id") or "").strip().casefold() != normalized_account_id:
            continue
        item_id = str(row.get("codex_history_item_id") or "").strip()
        if not item_id:
            continue
        return dict(row)
    return None


def _codex_session_title(final_text: str) -> str:
    for line in str(final_text or "").splitlines():
        candidate = line.strip().lstrip("-* ").strip()
        if candidate:
            return candidate[:120]
    return "Codex run summary"


def _codex_session_bullets(final_text: str, *, limit: int = 8) -> tuple[str, ...]:
    bullets: list[str] = []
    for line in str(final_text or "").splitlines():
        text = line.strip()
        if not text:
            continue
        if text.startswith(("- ", "* ")):
            text = text[2:].strip()
        if text and text not in bullets:
            bullets.append(text[:240])
        if len(bullets) >= limit:
            break
    return tuple(bullets)


def _codex_session_tests(final_text: str) -> tuple[str, ...]:
    tests: list[str] = []
    for match in re.finditer(r"\b(?:python3\s+-m\s+pytest|pytest)\s+([A-Za-z0-9_./:\-\[\]]+)", str(final_text or "")):
        command = match.group(0).strip().rstrip(".,;:")
        if command not in tests:
            tests.append(command)
    return tuple(tests)


def _iter_codex_session_files(roots: Sequence[str | Path], *, limit: int) -> tuple[Path, ...]:
    files: list[Path] = []
    for root_value in roots:
        root = _safe_repo_root(Path(root_value), operation="session root")
        if root.is_file() and root.suffix == ".jsonl":
            files.append(root)
            continue
        if not root.is_dir():
            continue
        files.extend(path for path in root.rglob("*.jsonl") if path.is_file())
    files = sorted(set(files), key=lambda path: str(path))
    if limit > 0:
        files = files[:limit]
    return tuple(files)


def _normalize_watch_event_mode(value: str) -> str:
    normalized = str(value or "poll").strip().casefold()
    if normalized not in {"poll", "snapshot", "watchdog", "auto"}:
        raise ValueError(f"unsupported Codex history watch event mode: {value}")
    return normalized


def _codex_session_roots_snapshot(roots: Sequence[str | Path], *, limit: int) -> tuple[tuple[str, int, int], ...]:
    snapshot: list[tuple[str, int, int]] = []
    for path in _iter_codex_session_files(roots, limit=limit):
        try:
            stat = path.stat()
        except OSError:
            continue
        snapshot.append((str(path), int(stat.st_size), int(stat.st_mtime_ns)))
    return tuple(snapshot)


def _wait_for_codex_session_change(
    roots: Sequence[str | Path],
    *,
    poll_interval_seconds: float,
    event_mode: str,
    sleep: Callable[[float], None],
) -> None:
    if poll_interval_seconds <= 0:
        return
    normalized_event_mode = _normalize_watch_event_mode(event_mode)
    if normalized_event_mode in {"auto", "watchdog"}:
        if _wait_for_watchdog_codex_session_change(roots, timeout_seconds=poll_interval_seconds):
            return
        if normalized_event_mode == "watchdog":
            return
    sleep(float(poll_interval_seconds))


def _wait_for_watchdog_codex_session_change(roots: Sequence[str | Path], *, timeout_seconds: float) -> bool:
    try:
        from watchdog.events import FileSystemEventHandler  # type: ignore[import-not-found]
        from watchdog.observers import Observer  # type: ignore[import-not-found]
    except ImportError:
        return False

    changed = threading.Event()

    class _CodexSessionEventHandler(FileSystemEventHandler):  # type: ignore[misc, valid-type]
        def on_any_event(self, event: Any) -> None:  # noqa: ANN401 - watchdog event type is optional.
            if getattr(event, "is_directory", False):
                return
            src_path = str(getattr(event, "src_path", "") or "")
            dest_path = str(getattr(event, "dest_path", "") or "")
            if src_path.endswith(".jsonl") or dest_path.endswith(".jsonl"):
                changed.set()

    observer = Observer()
    scheduled = False
    handler = _CodexSessionEventHandler()
    for root_value in roots:
        try:
            root = _safe_repo_root(Path(root_value), operation="sessions root")
        except ValueError:
            continue
        watch_root = root.parent if root.is_file() else root
        if not watch_root.exists() or not watch_root.is_dir():
            continue
        observer.schedule(handler, str(watch_root), recursive=True)
        scheduled = True
    if not scheduled:
        return False
    try:
        observer.start()
        return bool(changed.wait(max(0.0, float(timeout_seconds))))
    finally:
        observer.stop()
        observer.join(timeout=5.0)


def build_codex_history_report(
    *,
    instances_dir: str | Path = DEFAULT_INSTANCES_DIR,
    instances: Sequence[str] = (),
    repo: str = "",
    summary_limit: int = 20,
    provider: InstanceSecretProvider | None = None,
) -> dict[str, Any]:
    options = CodexHistoryReportOptions(
        instances_dir=_safe_repo_root(Path(instances_dir), operation="instances directory"),
        instances=tuple(instances),
        repo=str(repo or "").strip(),
        summary_limit=max(0, int(summary_limit or 0)),
        provider=provider or ReadOnlySecretToolInstanceSecretProvider(),
    )
    selected_instances = discover_instances(options.instances_dir, options.instances)
    report: dict[str, Any] = {
        "schema_version": CODEX_HISTORY_SCHEMA_VERSION,
        "scope": "codex_history",
        "generated_at": utc_now(),
        "instances_dir": str(options.instances_dir),
        "instance_count": len(selected_instances),
        "instances": [],
        "totals": {
            "projects": 0,
            "outbox_items": 0,
            "dispatch_results": 0,
            "store_errors": 0,
        },
    }
    for instance_name in selected_instances:
        instance_report = build_instance_codex_history_report(
            instances_dir=options.instances_dir,
            instance_name=instance_name,
            provider=options.provider,
            repo=options.repo,
            summary_limit=options.summary_limit,
        )
        report["instances"].append(instance_report)
        _add_totals(report["totals"], instance_report)
    return report


def build_instance_codex_history_report(
    *,
    instances_dir: Path,
    instance_name: str,
    provider: InstanceSecretProvider,
    repo: str = "",
    summary_limit: int = 20,
) -> dict[str, Any]:
    safe_instance_name = _safe_instance_name(instance_name)
    accounts_root = instances_dir / safe_instance_name / "data" / "accounts"
    store = AccountStore(
        accounts_root,
        safe_instance_name,
        secret_provider=provider,
        create_dirs=False,
        secret_guard_purposes=(INSTANCE_MAPPING_KEY_PURPOSE,),
    )
    codex_history: dict[str, Any] = {
        "projects": [],
        "outbox_items": 0,
        "dispatch_results": 0,
        "outbox_status_counts": {},
        "dispatch_status_counts": {},
        "latest_by_repo": [],
        "repo_history": [],
        "errors": [],
    }
    try:
        projects = _filter_projects(store.read_codex_history_projects(INSTANCE_STATE_ACCOUNT_ID), repo)
        outbox = _filter_outbox(store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID), repo)
        dispatch_results = _filter_dispatch_results(
            store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID),
            outbox,
            repo=repo,
        )
    except (AccountStoreError, OSError, ValueError) as exc:
        codex_history["errors"].append(f"{type(exc).__name__}:{exc}")
        projects = []
        outbox = []
        dispatch_results = []
    codex_history["projects"] = projects
    codex_history["outbox_items"] = len(outbox)
    codex_history["dispatch_results"] = len(dispatch_results)
    codex_history["outbox_status_counts"] = _status_counts(outbox)
    codex_history["dispatch_status_counts"] = _status_counts(dispatch_results)
    codex_history["latest_by_repo"] = _latest_by_repo(outbox)
    codex_history["repo_history"] = _repo_history(projects, outbox, dispatch_results, summary_limit=summary_limit)
    return {
        "instance": safe_instance_name,
        "accounts_root": str(accounts_root),
        "accounts_root_exists": accounts_root.exists(),
        "codex_history": codex_history,
    }


def render_text_report(report: Mapping[str, Any]) -> str:
    lines = [
        "TeeBotus Codex-History Report",
        "",
        f"generated_at: {report.get('generated_at', '')}",
        f"instances_dir: {report.get('instances_dir', '')}",
        "",
        "Totals:",
    ]
    totals = report.get("totals", {})
    if isinstance(totals, Mapping):
        for key in sorted(totals):
            lines.append(f"  {key}: {totals[key]}")
    for instance in report.get("instances", []):
        if not isinstance(instance, Mapping):
            continue
        history = instance.get("codex_history", {})
        if not isinstance(history, Mapping):
            history = {}
        lines.extend(["", f"Instance: {instance.get('instance', '')}"])
        lines.append(f"  projects: {len(history.get('projects', []) or [])}")
        lines.append(f"  outbox_items: {history.get('outbox_items', 0)}")
        lines.append(f"  dispatch_results: {history.get('dispatch_results', 0)}")
        for item in history.get("latest_by_repo", []):
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "  latest: "
                f"{item.get('repo_name', '')} {item.get('summary_prefix', '')} "
                f"status={item.get('status', '')} title={item.get('title', '')}"
            )
        repo_history = history.get("repo_history", [])
        if isinstance(repo_history, Sequence) and not isinstance(repo_history, (str, bytes, bytearray)) and repo_history:
            lines.append("  Repo-History:")
            for repo_item in repo_history:
                if not isinstance(repo_item, Mapping):
                    continue
                lines.append(
                    "    "
                    f"{repo_item.get('repo_name', '')} "
                    f"summaries={repo_item.get('summary_count', 0)} "
                    f"statuses={_format_status_counts(repo_item.get('outbox_status_counts', {}))} "
                    f"dispatch={_format_status_counts(repo_item.get('dispatch_status_counts', {}))}"
                )
                for summary in repo_item.get("latest_summaries", []) or []:
                    if not isinstance(summary, Mapping):
                        continue
                    lines.append(
                        "      "
                        f"{summary.get('summary_prefix', '')} "
                        f"{summary.get('status', '')} "
                        f"{summary.get('title', '')}"
                    )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None, *, provider: InstanceSecretProvider | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m TeeBotus.admin codex-history")
    subparsers = parser.add_subparsers(dest="command", required=True)

    append_parser = subparsers.add_parser("append")
    append_parser.add_argument("--instances-dir", default=DEFAULT_INSTANCES_DIR)
    append_parser.add_argument("--instance", required=True)
    append_parser.add_argument("--repo-root", required=True)
    append_parser.add_argument("--title", default="Codex run summary")
    append_parser.add_argument("--bullet", action="append", default=[])
    append_parser.add_argument("--changed-file", action="append", default=[])
    append_parser.add_argument("--test", action="append", default=[])
    append_parser.add_argument("--session-id", default="")
    append_parser.add_argument("--source", default="manual_cli")
    append_parser.add_argument("--format", choices=("text", "json"), default="text")
    append_parser.add_argument("--output", default="")

    report_parser = subparsers.add_parser("report")
    report_parser.add_argument("--instances-dir", default=DEFAULT_INSTANCES_DIR)
    report_parser.add_argument("--instances", default="")
    report_parser.add_argument("--repo", default="")
    report_parser.add_argument("--summary-limit", type=int, default=20)
    report_parser.add_argument("--format", choices=("text", "json"), default="text")
    report_parser.add_argument("--output", default="")

    bibliothekar_export_parser = subparsers.add_parser("bibliothekar-export")
    bibliothekar_export_parser.add_argument("--instances-dir", default=DEFAULT_INSTANCES_DIR)
    bibliothekar_export_parser.add_argument("--instances", default="")
    bibliothekar_export_parser.add_argument("--instance", default="")
    bibliothekar_export_parser.add_argument("--repo", default="")
    bibliothekar_export_parser.add_argument("--limit", type=int, default=0)
    bibliothekar_export_parser.add_argument("--format", choices=("text", "json"), default="text")
    bibliothekar_export_parser.add_argument("--no-overwrite", action="store_true")

    dispatch_parser = subparsers.add_parser("dispatch")
    dispatch_parser.add_argument("--instances-dir", default=DEFAULT_INSTANCES_DIR)
    dispatch_parser.add_argument("--instances", default="")
    dispatch_parser.add_argument("--instance", default="")
    dispatch_parser.add_argument("--limit", type=int, default=100)
    dispatch_parser.add_argument("--format", choices=("text", "json"), default="text")
    dispatch_parser.add_argument("--dry-run", action="store_true")

    acknowledge_parser = subparsers.add_parser("acknowledge")
    acknowledge_parser.add_argument("--instances-dir", default=DEFAULT_INSTANCES_DIR)
    acknowledge_parser.add_argument("--instance", required=True)
    acknowledge_parser.add_argument("--item-id", required=True)
    acknowledge_parser.add_argument("--account-id", default="")
    acknowledge_parser.add_argument("--message-ref", default="")
    acknowledge_parser.add_argument("--format", choices=("text", "json"), default="text")

    receipt_parser = subparsers.add_parser("receipt")
    receipt_parser.add_argument("--instances-dir", default=DEFAULT_INSTANCES_DIR)
    receipt_parser.add_argument("--instance", required=True)
    receipt_parser.add_argument("--channel", required=True)
    receipt_parser.add_argument("--chat-id", required=True)
    receipt_parser.add_argument("--message-ref", required=True)
    receipt_parser.add_argument("--account-id", default="")
    receipt_parser.add_argument("--receipt-type", default="delivered")
    receipt_parser.add_argument("--format", choices=("text", "json"), default="text")

    watch_parser = subparsers.add_parser("watch")
    watch_parser.add_argument("--instances-dir", default=DEFAULT_INSTANCES_DIR)
    watch_parser.add_argument("--instances", default="")
    watch_parser.add_argument("--instance", default="")
    watch_parser.add_argument("--sessions-root", action="append", default=[])
    watch_parser.add_argument("--limit", type=int, default=1000)
    watch_parser.add_argument("--max-iterations", type=int, default=1)
    watch_parser.add_argument("--poll-interval", type=float, default=1.0)
    watch_parser.add_argument("--event-mode", choices=("poll", "snapshot", "watchdog", "auto"), default="poll")
    watch_parser.add_argument("--follow", action="store_true", help="Run until the process is stopped instead of exiting after max iterations.")
    watch_parser.add_argument("--format", choices=("text", "json"), default="text")
    watch_parser.add_argument("--once", action="store_true")

    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "append":
        try:
            store = _store_for_instance(Path(args.instances_dir), args.instance, provider, create_dirs=True)
            item = append_codex_history_summary(
                store,
                repo_root=args.repo_root,
                title=args.title,
                bullets=tuple(args.bullet or ()),
                changed_files=tuple(args.changed_file or ()),
                tests=tuple(args.test or ()),
                session_id=args.session_id,
                source=args.source,
            )
            output_payload = {"ok": True, "item": item}
            output = (
                json.dumps(output_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
                if args.format == "json"
                else f"queued {item['summary_prefix']} {item['project']['repo_name']} {item['id']}\n"
            )
            _write_or_print(output, args.output)
            return 0
        except (OSError, ValueError) as exc:
            print(f"append failed: {exc}", file=sys.stderr)
            return 2
    if args.command == "report":
        try:
            report = build_codex_history_report(
                instances_dir=args.instances_dir,
                instances=parse_csv(getattr(args, "instances", None)),
                repo=args.repo,
                summary_limit=int(args.summary_limit or 0),
                provider=provider,
            )
            output = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n" if args.format == "json" else render_text_report(report)
            _write_or_print(output, args.output)
            return 0
        except (OSError, ValueError) as exc:
            print(f"report failed: {exc}", file=sys.stderr)
            return 2
    if args.command == "bibliothekar-export":
        try:
            selected_instances = parse_csv(getattr(args, "instances", None))
            if args.instance:
                selected_instances = tuple(dict.fromkeys((*selected_instances, str(args.instance).strip())))
            instances_dir = _safe_repo_root(Path(args.instances_dir), operation="instances directory")
            _ensure_explicit_instances_exist(instances_dir, selected_instances)
            reports: list[dict[str, Any]] = []
            for instance_name in discover_instances(instances_dir, selected_instances):
                store = _store_for_instance(instances_dir, instance_name, provider)
                reports.append(
                    export_codex_history_bibliothekar_docs(
                        store,
                        instance_dir=instances_dir / instance_name,
                        instance_name=instance_name,
                        repo=args.repo,
                        limit=int(args.limit or 0),
                        overwrite=not bool(args.no_overwrite),
                    )
                )
            payload = {
                "ok": not any(not report.get("ok") for report in reports),
                "instances_dir": str(instances_dir),
                "instances": reports,
                "totals": {
                    "exported": sum(int(report.get("exported") or 0) for report in reports),
                    "skipped": sum(int(report.get("skipped") or 0) for report in reports),
                },
            }
            output = (
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
                if args.format == "json"
                else _render_bibliothekar_export_report(payload)
            )
            print(output, end="")
            return 0 if payload["ok"] else 1
        except (OSError, ValueError) as exc:
            print(f"bibliothekar-export failed: {exc}", file=sys.stderr)
            return 2
    if args.command == "dispatch":
        try:
            selected_instances = parse_csv(getattr(args, "instances", None))
            if args.instance:
                selected_instances = tuple(dict.fromkeys((*selected_instances, str(args.instance).strip())))
            instances_dir = _safe_repo_root(Path(args.instances_dir), operation="instances directory")
            _ensure_explicit_instances_exist(instances_dir, selected_instances)
            dispatch_reports: list[dict[str, Any]] = []
            selected = discover_instances(instances_dir, selected_instances)
            sender_factory = None if args.dry_run else _runtime_sender_factory(instances_dir)
            for instance_name in selected:
                store = _store_for_instance(instances_dir, instance_name, provider)
                senders = {} if args.dry_run else dict(sender_factory(instance_name, store))  # type: ignore[operator]
                dispatch_reports.append(
                    asyncio.run(
                        dispatch_codex_history_outbox(
                            store,
                            instance_name=instance_name,
                            senders=senders,
                            dry_run=bool(args.dry_run),
                            limit=int(args.limit or 0),
                        )
                    )
                )
            payload = {
                "ok": not any(not report.get("ok") for report in dispatch_reports),
                "dry_run": bool(args.dry_run),
                "instances_dir": str(instances_dir),
                "instances": dispatch_reports,
            }
            output = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n" if args.format == "json" else _render_dispatch_report(payload)
            print(output, end="")
            return 0 if payload["ok"] else 1
        except (OSError, ValueError) as exc:
            print(f"dispatch failed: {exc}", file=sys.stderr)
            return 2
    if args.command == "acknowledge":
        try:
            store = _store_for_instance(Path(args.instances_dir), args.instance, provider)
            payload = acknowledge_codex_history_item(
                store,
                args.item_id,
                instance_name=args.instance,
                account_id=args.account_id,
                message_ref=args.message_ref,
            )
            output = (
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
                if args.format == "json"
                else _render_acknowledge_report(payload)
            )
            print(output, end="")
            return 0 if payload.get("ok") else 1
        except (OSError, ValueError) as exc:
            print(f"acknowledge failed: {exc}", file=sys.stderr)
            return 2
    if args.command == "receipt":
        try:
            store = _store_for_instance(Path(args.instances_dir), args.instance, provider)
            payload = record_codex_history_delivery_receipt(
                store,
                instance_name=args.instance,
                channel=args.channel,
                chat_id=args.chat_id,
                account_id=args.account_id,
                message_ref=args.message_ref,
                receipt_type=args.receipt_type,
            )
            output = (
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
                if args.format == "json"
                else _render_receipt_report(payload)
            )
            print(output, end="")
            return 0 if payload.get("ok") else 1
        except (OSError, ValueError) as exc:
            print(f"receipt failed: {exc}", file=sys.stderr)
            return 2
    if args.command == "watch" and args.once:
        try:
            selected_instances = parse_csv(getattr(args, "instances", None))
            if args.instance:
                selected_instances = tuple(dict.fromkeys((*selected_instances, str(args.instance).strip())))
            instances_dir = _safe_repo_root(Path(args.instances_dir), operation="instances directory")
            _ensure_explicit_instances_exist(instances_dir, selected_instances)
            selected = discover_instances(instances_dir, selected_instances)
            safe_roots = [_safe_repo_root(Path(root), operation="sessions root") for root in tuple(args.sessions_root or ()) or default_codex_session_roots()]
            instance_reports: list[dict[str, Any]] = []
            for instance_name in selected:
                store = _store_for_instance(instances_dir, instance_name, provider)
                import_report = import_codex_session_roots(store, safe_roots, limit=int(args.limit or 0))
                instance_reports.append({"instance": instance_name, **import_report})
            payload = {
                "ok": not any(not report.get("ok") for report in instance_reports),
                "mode": "once",
                "sessions_roots": [str(root) for root in safe_roots],
                "instances_dir": str(instances_dir),
                "instances": instance_reports,
            }
            output = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n" if args.format == "json" else _render_watch_report(payload)
            print(output, end="")
            return 0 if payload["ok"] else 1
        except (OSError, ValueError) as exc:
            print(f"watch failed: {exc}", file=sys.stderr)
            return 2
    if args.command == "watch":
        try:
            selected_instances = parse_csv(getattr(args, "instances", None))
            if args.instance:
                selected_instances = tuple(dict.fromkeys((*selected_instances, str(args.instance).strip())))
            instances_dir = _safe_repo_root(Path(args.instances_dir), operation="instances directory")
            _ensure_explicit_instances_exist(instances_dir, selected_instances)
            safe_roots = [_safe_repo_root(Path(root), operation="sessions root") for root in tuple(args.sessions_root or ()) or default_codex_session_roots()]
            max_iterations = int(args.max_iterations or 0)
            if max_iterations < 1:
                max_iterations = 1
            poll_interval_seconds = float(args.poll_interval or 0.0)
            if poll_interval_seconds < 0.0:
                poll_interval_seconds = 0.0
            instance_reports: list[dict[str, Any]] = []
            selected = discover_instances(instances_dir, selected_instances)
            for instance_name in selected:
                store = _store_for_instance(instances_dir, instance_name, provider)
                watch_report = watch_codex_session_roots(
                    store,
                    safe_roots,
                    poll_interval_seconds=poll_interval_seconds,
                    max_iterations=max_iterations,
                    follow=bool(args.follow),
                    event_mode=str(args.event_mode or "poll"),
                    limit=int(args.limit or 0),
                )
                instance_reports.append({"instance": instance_name, **watch_report})
            payload = {
                "ok": not any(not report.get("ok") for report in instance_reports),
                "mode": "watch",
                "follow": bool(args.follow),
                "event_mode": str(args.event_mode or "poll"),
                "sessions_roots": [str(root) for root in safe_roots],
                "instances_dir": str(instances_dir),
                "instances": instance_reports,
            }
            output = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n" if args.format == "json" else _render_watch_report(payload)
            print(output, end="")
            return 0 if payload["ok"] else 1
        except (OSError, ValueError) as exc:
            print(f"watch failed: {exc}", file=sys.stderr)
            return 2
    if args.command == "watch":
        payload = {
            "ok": False,
            "status": "not_implemented",
            "command": args.command,
            "message": "Use --once for Codex history session import; continuous watching will be wired in a later phase.",
        }
        output = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n" if args.format == "json" else payload["message"] + "\n"
        print(output, end="")
        return 2
    parser.error("unknown command")
    return 2


def _store_for_instance(
    instances_dir: Path,
    instance_name: str,
    provider: InstanceSecretProvider | None,
    *,
    create_dirs: bool = False,
) -> AccountStore:
    safe_instances_dir = _safe_repo_root(instances_dir, operation="instances directory")
    safe_instance_name = _safe_instance_name(instance_name)
    return AccountStore(
        safe_instances_dir / safe_instance_name / "data" / "accounts",
        safe_instance_name,
        secret_provider=provider or ReadOnlySecretToolInstanceSecretProvider(),
        create_dirs=create_dirs,
    )


def _write_or_print(output: str, output_path: str) -> None:
    if output_path:
        _safe_output_path(output_path).write_text(output, encoding="utf-8")
    else:
        print(output, end="")


def _ensure_explicit_instances_exist(instances_dir: Path, requested_instances: Sequence[str]) -> None:
    if not requested_instances:
        return
    normalized_instances = tuple(_safe_instance_name(str(instance_name).strip()) for instance_name in requested_instances if str(instance_name).strip())
    if not normalized_instances:
        return
    safe_instances_dir = _safe_repo_root(instances_dir, operation="instances directory")
    available = {path.name for path in safe_instances_dir.iterdir() if path.is_dir()}
    missing: list[str] = []
    for name in normalized_instances:
        if not name:
            continue
        if name not in available:
            missing.append(name)
    if missing:
        raise ValueError("requested instances not found: " + ", ".join(dict.fromkeys(missing)))


def _runtime_sender_factory(instances_dir: Path):
    from TeeBotus.proactive import runtime_sender_factory

    return runtime_sender_factory(instances_dir)


def _render_dispatch_report(payload: Mapping[str, Any]) -> str:
    lines = ["TeeBotus Codex-History Dispatch", "", f"dry_run: {payload.get('dry_run', False)}"]
    for instance in payload.get("instances", []):
        if not isinstance(instance, Mapping):
            continue
        lines.append("")
        lines.append(f"Instance: {instance.get('instance', '')}")
        status_counts = instance.get("status_counts", {})
        if isinstance(status_counts, Mapping):
            lines.append("  statuses: " + ", ".join(f"{key}={value}" for key, value in sorted(status_counts.items())))
        for item in instance.get("items", []):
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "  dispatch: "
                f"item={item.get('codex_history_item_id', '')} "
                f"account={item.get('account_id', '')} "
                f"status={item.get('status', '')} "
                f"reason={item.get('reason', '')}"
            )
    return "\n".join(lines) + "\n"


def _render_acknowledge_report(payload: Mapping[str, Any]) -> str:
    status = str(payload.get("status") or "unknown")
    item_id = str(payload.get("item_id") or "")
    reason = str(payload.get("reason") or "")
    line = f"acknowledge {status} {item_id}".strip()
    if reason:
        line += f" reason={reason}"
    return line + "\n"


def _render_receipt_report(payload: Mapping[str, Any]) -> str:
    status = str(payload.get("status") or "unknown")
    item_id = str(payload.get("item_id") or "")
    reason = str(payload.get("reason") or "")
    line = f"receipt {status} {item_id}".strip()
    if reason:
        line += f" reason={reason}"
    return line + "\n"


def _render_bibliothekar_export_report(payload: Mapping[str, Any]) -> str:
    lines = ["TeeBotus Codex-History Bibliothekar Export", ""]
    totals = payload.get("totals", {})
    if isinstance(totals, Mapping):
        lines.append(f"exported: {totals.get('exported', 0)}")
        lines.append(f"skipped: {totals.get('skipped', 0)}")
    for instance in payload.get("instances", []):
        if not isinstance(instance, Mapping):
            continue
        lines.append("")
        lines.append(f"Instance: {instance.get('instance', '')}")
        lines.append(f"  destination: {instance.get('destination', '')}")
        lines.append(f"  exported: {instance.get('exported', 0)}")
        lines.append(f"  skipped: {instance.get('skipped', 0)}")
        for item in instance.get("files", []) or []:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "  file: "
                f"{item.get('summary_prefix', '')} "
                f"{item.get('repo_name', '')} "
                f"{item.get('path', '')}"
            )
    return "\n".join(lines) + "\n"


def _render_watch_report(payload: Mapping[str, Any]) -> str:
    lines = ["TeeBotus Codex-History Watch", "", f"mode: {payload.get('mode', '')}"]
    roots = payload.get("sessions_roots", [])
    if isinstance(roots, Sequence) and not isinstance(roots, (str, bytes, bytearray)):
        lines.append("sessions_roots: " + ", ".join(str(root) for root in roots))
    for instance in payload.get("instances", []):
        if not isinstance(instance, Mapping):
            continue
        lines.append("")
        lines.append(f"Instance: {instance.get('instance', '')}")
        status_counts = instance.get("status_counts", {})
        if isinstance(status_counts, Mapping):
            lines.append("  statuses: " + ", ".join(f"{key}={value}" for key, value in sorted(status_counts.items())))
        for item in instance.get("items", []):
            if not isinstance(item, Mapping):
                continue
            item_payload = item.get("item", {})
            summary_prefix = item_payload.get("summary_prefix", "") if isinstance(item_payload, Mapping) else ""
            lines.append(
                "  import: "
                f"status={item.get('status', '')} "
                f"reason={item.get('reason', '')} "
                f"summary={summary_prefix}"
            )
    return "\n".join(lines) + "\n"


def _git_output(repo_root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, ValueError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _repo_name(root: Path, remote_url: str) -> str:
    if remote_url:
        name = remote_url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
        if ":" in name:
            name = name.rsplit(":", 1)[-1].removesuffix(".git")
        if name:
            return name
    return root.name


def _normalize_remote_url(remote_url: str) -> str:
    value = str(remote_url or "").strip()
    if not value:
        return ""
    if "://" not in value and ":" in value:
        host_part, _, path = value.partition(":")
        if "/" not in host_part and ("@" in host_part or "." in host_part or host_part == "localhost"):
            user = "git"
            host = host_part
            if "@" in host_part:
                user, _, host = host_part.partition("@")
            path = path.removesuffix(".git")
            value = f"ssh://{user}@{host}/{path}"
    return value.casefold()


def _repo_provider(remote_url: str) -> str:
    parsed = urlsplit(_normalize_remote_url(remote_url))
    value = (parsed.hostname.casefold() if parsed.hostname else "").strip()
    if value == "github.com":
        return "github"
    if value or remote_url.strip():
        return "git"
    return "local"


def _pyproject_version(root: Path) -> str:
    path = root / "pyproject.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
        return ""
    project = data.get("project", {})
    if not isinstance(project, Mapping):
        return ""
    return str(project.get("version") or "").strip()


def _version_file(root: Path) -> str:
    try:
        return (root / "VERSION").read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        return ""


def _git_latest_semver_tag(root: Path) -> str:
    tag = _git_output(root, "describe", "--tags", "--abbrev=0", "--match", "v[0-9]*")
    if re.match(r"^v?\d+\.\d+\.\d+(?:[-+][A-Za-z0-9_.-]+)?$", tag):
        return tag
    return ""


def _teebotus_version(root: Path) -> str:
    package_root = Path(__file__).resolve().parents[2]
    try:
        if root.resolve() == package_root:
            return __version__
    except OSError:
        return ""
    return ""


def _next_summary_number_for_repo(rows: Sequence[Mapping[str, Any]], repo_id: str) -> int:
    highest = 0
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        project = row.get("project", {})
        if not isinstance(project, Mapping) or project.get("repo_id") != repo_id:
            continue
        try:
            number = int(row.get("summary_number") or row.get("version", {}).get("summary_number") or 0)  # type: ignore[union-attr]
        except (TypeError, ValueError, AttributeError):
            number = 0
        highest = max(highest, number)
    return highest + 1


def _summary_prefix(semver: str, summary_number: int) -> str:
    version = str(semver or "").strip() or "untagged"
    prefix = "untagged" if version == "untagged" else f"v{version.removeprefix('v')}"
    return f"{prefix} #{max(1, int(summary_number)):04d}"


def _unique_history_id(rows: Sequence[Mapping[str, Any]]) -> str:
    existing_ids = {str(row.get("id", "")).strip() for row in rows if isinstance(row, Mapping)}
    item_id = f"hist_{uuid.uuid4().hex}"
    while item_id in existing_ids:
        item_id = f"hist_{uuid.uuid4().hex}"
    return item_id


def _history_keywords(
    repo: Mapping[str, Any],
    version: Mapping[str, str],
    title: str,
    bullets: Sequence[str],
    changed_files: Sequence[str],
    tests: Sequence[str],
) -> list[str]:
    words: set[str] = {
        "codex",
        "history",
        "outbox",
        str(repo.get("repo_name") or "").casefold(),
        str(version.get("tag") or "").casefold(),
    }
    for value in (title, *bullets, *changed_files, *tests):
        for token in re.findall(r"[A-Za-z0-9_.-]{3,}", value):
            words.add(token.casefold())
    return sorted(word for word in words if word)


def _codex_history_bibliothekar_root(instance_dir: Path) -> Path:
    safe_instance_dir = _safe_repo_root(instance_dir, operation="instance directory")
    data_dir = (safe_instance_dir / "data").resolve()
    destination = (data_dir / CODEX_HISTORY_BIBLIOTHEKAR_DIRNAME).resolve()
    normal_library = (data_dir / "Bibliothek").resolve()
    if destination == normal_library:
        raise ValueError("codex history export must not use the normal user Bibliothek")
    try:
        destination.relative_to(data_dir)
    except ValueError as exc:
        raise ValueError("codex history export target escapes instance data directory") from exc
    return destination


def _codex_history_item_indexable(item: Mapping[str, Any]) -> bool:
    if not isinstance(item, Mapping):
        return False
    if str(item.get("kind") or "").strip() != "codex_run_summary":
        return False
    indexing = item.get("indexing", {})
    if isinstance(indexing, Mapping) and indexing.get("indexable") is False:
        return False
    return True


def _write_codex_history_bibliothekar_readme(destination: Path, instance_name: str) -> None:
    readme = destination / CODEX_HISTORY_BIBLIOTHEKAR_README
    text = "\n".join(
        [
            "# TeeBotus Codex History Bibliothekar Export",
            "",
            f"- Instanz: `{instance_name}`",
            "- Zugriff: admin-only",
            "- Quelle: `codex_history_outbox`",
            "- Zweck: separate Indexquelle fuer Qdrant/Bibliothekar-Projekthistory",
            "",
            "Dieser Ordner darf nicht in die normale Nutzerbibliothek `data/Bibliothek` kopiert oder dort gemountet werden.",
            "Nicht-Admin-Nutzer duerfen weder von dieser Sammlung erfahren noch Inhalte daraus erhalten.",
            "",
        ]
    )
    readme.write_text(text, encoding="utf-8")


def _codex_history_bibliothekar_markdown(item: Mapping[str, Any]) -> str:
    project = item.get("project", {})
    summary = item.get("summary", {})
    version = item.get("version", {})
    delivery = item.get("delivery", {})
    codex = item.get("codex", {})
    if not isinstance(project, Mapping):
        project = {}
    if not isinstance(summary, Mapping):
        summary = {}
    if not isinstance(version, Mapping):
        version = {}
    if not isinstance(delivery, Mapping):
        delivery = {}
    if not isinstance(codex, Mapping):
        codex = {}
    categories = _codex_history_bibliothekar_categories(item)
    keywords = _codex_history_bibliothekar_keywords(item, categories)
    title = redact_codex_history_text(summary.get("title") or "Codex run summary").strip() or "Codex run summary"
    markdown = redact_codex_history_text(summary.get("markdown") or "").strip()
    if not markdown:
        markdown = f"# {item.get('summary_prefix', '')} {title}".strip()
    lines = [
        f"# Codex History: {item.get('summary_prefix', '')} {title}".strip(),
        "",
        "> Admin-only TeeBotus Codex-History-Export. Nicht fuer normale Nutzer-Bibliotheken freigeben.",
        "",
        "## Index-Metadaten",
        f"- Kategorie: {', '.join(categories)}",
        f"- Keywords: {', '.join(keywords[:80])}",
        "- Zugriff: admin-only",
        "- Sammlung: codex_history_outbox",
        "- Dokumenttyp: project-history",
        "",
        "## Projekt",
        f"- Repo: `{redact_codex_history_text(project.get('repo_name', '')).strip()}`",
        f"- Repo-Root: `{redact_codex_history_text(project.get('repo_root', '')).strip()}`",
        f"- Remote: `{redact_codex_history_text(project.get('remote_url', '')).strip()}`",
        f"- Provider: `{redact_codex_history_text(project.get('provider', '')).strip()}`",
        f"- Branch: `{redact_codex_history_text(project.get('branch', '')).strip()}`",
        f"- Commit: `{redact_codex_history_text(project.get('head_commit', '')).strip()}`",
        f"- Dirty: `{bool(project.get('dirty'))}`",
        "",
        "## Version und Status",
        f"- SemVer: `{redact_codex_history_text(version.get('semver', '')).strip()}`",
        f"- Tag: `{redact_codex_history_text(version.get('tag', '')).strip()}`",
        f"- Summary: `{redact_codex_history_text(item.get('summary_prefix', '')).strip()}`",
        f"- Status: `{redact_codex_history_text(item.get('status', '')).strip()}`",
        f"- Erstellt: `{redact_codex_history_text(item.get('created_at', '')).strip()}`",
        f"- Aktualisiert: `{redact_codex_history_text(item.get('updated_at', '')).strip()}`",
        f"- Sent: `{redact_codex_history_text(delivery.get('sent_at', '')).strip()}`",
        f"- Accepted: `{redact_codex_history_text(delivery.get('accepted_at', '')).strip()}`",
        f"- Delivered: `{redact_codex_history_text(delivery.get('delivered_at', '')).strip()}`",
        f"- Acknowledged: `{redact_codex_history_text(delivery.get('acknowledged_at', '')).strip()}`",
        "",
        "## Codex",
        f"- Source: `{redact_codex_history_text(item.get('source', '')).strip()}`",
        f"- Session: `{redact_codex_history_text(codex.get('session_id', '')).strip()}`",
        f"- Turn: `{redact_codex_history_text(codex.get('turn_id', '')).strip()}`",
        "",
        "## Summary",
        markdown,
        "",
    ]
    return "\n".join(lines)


def _codex_history_bibliothekar_chunk(item: Mapping[str, Any], *, destination: Path, instance_name: str) -> dict[str, Any]:
    project = item.get("project", {})
    summary = item.get("summary", {})
    version = item.get("version", {})
    if not isinstance(project, Mapping):
        project = {}
    if not isinstance(summary, Mapping):
        summary = {}
    if not isinstance(version, Mapping):
        version = {}
    repo_name = str(project.get("repo_name") or "project").strip() or "project"
    text = _codex_history_bibliothekar_markdown(item)
    filename = _codex_history_bibliothekar_filename(item)
    relative_path = f"codex_history/{_safe_filename_component(repo_name, default='project')}/{filename}"
    file_path = str((destination / relative_path).resolve())
    item_id = str(item.get("id") or "").strip()
    source_seed = item_id or hashlib.sha256(text.encode("utf-8")).hexdigest()
    text_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    categories = _codex_history_bibliothekar_categories(item)
    keywords = _codex_history_bibliothekar_keywords(item, categories)
    title = redact_codex_history_text(summary.get("title") or "Codex run summary").strip() or "Codex run summary"
    summary_prefix = str(item.get("summary_prefix") or version.get("summary_prefix") or "").strip()
    return {
        "chunk_id": f"codex_history:{hashlib.sha256((instance_name + ':' + source_seed).encode('utf-8')).hexdigest()[:32]}",
        "document_id": f"codex_history:{hashlib.sha256(source_seed.encode('utf-8')).hexdigest()[:32]}",
        "source_id": f"codex_history:{item_id or text_sha[:32]}",
        "title": f"{summary_prefix} {title}".strip(),
        "author": "Codex",
        "relative_path": relative_path,
        "file_path": file_path,
        "file_sha256": text_sha,
        "file_type": "md",
        "language": "de",
        "locator": f"Codex-History {summary_prefix}".strip(),
        "page_start": 1,
        "page_end": 1,
        "chapter": "Codex History",
        "section": str(project.get("repo_name") or "project"),
        "license": "private",
        "source_quality": "admin_only",
        "citation_quality": "generated_from_codex_history",
        "source_requires_human_review": False,
        "source_harvest_route": "codex_history_outbox",
        "ingested_at": str(item.get("updated_at") or item.get("created_at") or utc_now()),
        "chunk_index": 1,
        "topics": keywords[:48],
        "categories": categories,
        "text": text,
    }


def _codex_history_bibliothekar_categories(item: Mapping[str, Any]) -> list[str]:
    project = item.get("project", {})
    summary = item.get("summary", {})
    if not isinstance(project, Mapping):
        project = {}
    if not isinstance(summary, Mapping):
        summary = {}
    status = str(item.get("status") or "unknown").strip().casefold() or "unknown"
    repo_name = _safe_filename_component(str(project.get("repo_name") or "project"), default="project").casefold()
    categories: set[str] = {
        "admin-only",
        "codex-history",
        "project-history",
        f"repo-{repo_name}",
        f"status-{_safe_filename_component(status, default='unknown').casefold()}",
    }
    text_parts = [
        str(summary.get("title") or ""),
        _join_codex_history_summary_values(summary.get("bullets", [])),
        _join_codex_history_summary_values(summary.get("changed_files", [])),
        _join_codex_history_summary_values(summary.get("tests", [])),
    ]
    text = " ".join(text_parts).casefold()
    category_terms = {
        "change-feature": ("feature", "gebaut", "implement", "neu", "add", "ergaenz"),
        "change-bugfix": ("fix", "bug", "repar", "fehler", "regress"),
        "change-test": ("test", "pytest", "benchmark", "check", "verify", "verifiz"),
        "change-docs": ("doc", "docs", "readme", "plan", "bericht", ".md"),
        "change-security": ("secret", "auth", "admin", "policy", "guard", "sicher", "encrypt"),
        "change-dependency": ("dependency", "deps", "requirements", "lock", "pin", "version"),
        "change-runtime": ("runtime", "restart", "service", "systemd", "adapter", "telegram", "signal", "matrix"),
        "change-memory": ("memory", "accountstore", "sql", "sqlite", "postgres", "qdrant", "vector"),
        "change-bibliothekar": ("bibliothek", "bibliothekar", "library", "index"),
        "change-llm": ("llm", "openai", "gemini", "litellm", "model", "planner"),
    }
    for category, needles in category_terms.items():
        if any(needle in text for needle in needles):
            categories.add(category)
    return sorted(categories)


def _codex_history_bibliothekar_keywords(item: Mapping[str, Any], categories: Sequence[str]) -> list[str]:
    indexing = item.get("indexing", {})
    words: set[str] = {str(category).casefold() for category in categories if str(category or "").strip()}
    if isinstance(indexing, Mapping):
        keywords = indexing.get("keywords", [])
        if isinstance(keywords, Sequence) and not isinstance(keywords, (str, bytes, bytearray)):
            for keyword in keywords:
                value = str(keyword or "").strip().casefold()
                if value:
                    words.add(value)
    for field in ("summary_prefix", "status", "source", "created_at", "updated_at"):
        value = str(item.get(field) or "").strip().casefold()
        if value:
            words.add(value)
    return sorted(words)


def _join_codex_history_summary_values(value: object) -> str:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return " ".join(str(item or "") for item in value)
    return ""


def _codex_history_bibliothekar_filename(item: Mapping[str, Any]) -> str:
    summary = item.get("summary", {})
    version = item.get("version", {})
    if not isinstance(summary, Mapping):
        summary = {}
    if not isinstance(version, Mapping):
        version = {}
    try:
        number = int(item.get("summary_number") or version.get("summary_number") or 0)
    except (TypeError, ValueError):
        number = 0
    prefix = _safe_filename_component(str(item.get("summary_prefix") or version.get("summary_prefix") or "summary"), default="summary", max_length=48)
    title = _safe_filename_component(str(summary.get("title") or "codex-run"), default="codex-run", max_length=64)
    item_id = _safe_filename_component(str(item.get("id") or uuid.uuid4().hex), default="item", max_length=32)
    return f"{max(number, 0):04d}_{prefix}_{title}_{item_id}.md"


def _safe_filename_component(value: str, *, default: str, max_length: int = 96) -> str:
    text = redact_codex_history_text(value).strip()
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("._-")
    if not safe:
        safe = default
    return safe[:max(8, max_length)].strip("._-") or default


def _upsert_project(store: AccountStore, account_id: str, repo: Mapping[str, Any], item: Mapping[str, Any], timestamp: str) -> None:
    projects = store.read_codex_history_projects(account_id)
    repo_id = str(repo.get("repo_id") or "")
    normalized = dict(repo)
    normalized.update(
        {
            "schema_version": CODEX_HISTORY_SCHEMA_VERSION,
            "updated_at": timestamp,
            "last_summary_id": item.get("id", ""),
            "last_summary_prefix": item.get("summary_prefix", ""),
            "last_summary_at": timestamp,
        }
    )
    replaced = False
    for index, project in enumerate(projects):
        if isinstance(project, Mapping) and project.get("repo_id") == repo_id:
            summary_count = int(project.get("summary_count") or 0) + 1
            normalized["created_at"] = project.get("created_at") or timestamp
            normalized["summary_count"] = summary_count
            projects[index] = normalized
            replaced = True
            break
    if not replaced:
        normalized["created_at"] = timestamp
        normalized["summary_count"] = 1
        projects.append(normalized)
    store.write_codex_history_projects(account_id, projects)


def _filter_projects(projects: Sequence[Mapping[str, Any]], repo: str) -> list[dict[str, Any]]:
    result = []
    for project in projects:
        if not isinstance(project, Mapping):
            continue
        if not _project_matches_repo(project, repo):
            continue
        result.append(dict(project))
    return result


def _filter_outbox(rows: Sequence[Mapping[str, Any]], repo: str) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        project = row.get("project", {})
        if not isinstance(project, Mapping):
            project = {}
        if not _project_matches_repo(project, repo):
            continue
        result.append(dict(row))
    return result


def _filter_dispatch_results(
    rows: Sequence[Mapping[str, Any]],
    outbox: Sequence[Mapping[str, Any]],
    *,
    repo: str,
) -> list[dict[str, Any]]:
    if not str(repo or "").strip():
        return [dict(row) for row in rows if isinstance(row, Mapping)]
    item_ids = {str(row.get("id") or "").strip() for row in outbox if isinstance(row, Mapping)}
    repo_ids = {
        str(row.get("project", {}).get("repo_id") or "").strip()
        for row in outbox
        if isinstance(row, Mapping) and isinstance(row.get("project"), Mapping)
    }
    result = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        item_id = str(row.get("codex_history_item_id") or "").strip()
        repo_id = str(row.get("repo_id") or "").strip()
        if item_id in item_ids or (repo_id and repo_id in repo_ids):
            result.append(dict(row))
    return result


def _project_matches_repo(project: Mapping[str, Any], repo: str) -> bool:
    needle = str(repo or "").strip().casefold()
    if not needle:
        return True
    fields = (
        project.get("repo_name", ""),
        project.get("repo_id", ""),
        project.get("repo_root", ""),
        project.get("remote_url", ""),
    )
    return any(needle in str(value or "").casefold() for value in fields)


def _status_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        status = str(row.get("status") or "unknown").strip().casefold() or "unknown"
        counts[status] += 1
    return dict(sorted(counts.items()))


def _latest_by_repo(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        project = row.get("project", {})
        if not isinstance(project, Mapping):
            continue
        repo_id = str(project.get("repo_id") or "")
        if not repo_id:
            continue
        previous = latest.get(repo_id)
        if previous is None or str(row.get("created_at") or "") >= str(previous.get("created_at") or ""):
            latest[repo_id] = row
    result = []
    for row in latest.values():
        project = row.get("project", {})
        summary = row.get("summary", {})
        if not isinstance(project, Mapping):
            project = {}
        if not isinstance(summary, Mapping):
            summary = {}
        result.append(
            {
                "repo_id": project.get("repo_id", ""),
                "repo_name": project.get("repo_name", ""),
                "summary_prefix": row.get("summary_prefix", ""),
                "status": row.get("status", ""),
                "title": summary.get("title", ""),
                "created_at": row.get("created_at", ""),
            }
        )
    return sorted(result, key=lambda item: (str(item.get("repo_name") or ""), str(item.get("created_at") or "")))


def _repo_history(
    projects: Sequence[Mapping[str, Any]],
    outbox: Sequence[Mapping[str, Any]],
    dispatch_results: Sequence[Mapping[str, Any]],
    *,
    summary_limit: int,
) -> list[dict[str, Any]]:
    grouped_items: dict[str, list[Mapping[str, Any]]] = {}
    project_meta: dict[str, Mapping[str, Any]] = {}
    for project in projects:
        if not isinstance(project, Mapping):
            continue
        repo_id = str(project.get("repo_id") or "").strip()
        if repo_id:
            project_meta[repo_id] = project
    for item in outbox:
        if not isinstance(item, Mapping):
            continue
        project = item.get("project", {})
        if not isinstance(project, Mapping):
            continue
        repo_id = str(project.get("repo_id") or "").strip()
        if not repo_id:
            continue
        project_meta.setdefault(repo_id, project)
        grouped_items.setdefault(repo_id, []).append(item)
    dispatch_by_item_id: dict[str, list[Mapping[str, Any]]] = {}
    for result in dispatch_results:
        if not isinstance(result, Mapping):
            continue
        item_id = str(result.get("codex_history_item_id") or "").strip()
        if item_id:
            dispatch_by_item_id.setdefault(item_id, []).append(result)
    history: list[dict[str, Any]] = []
    for repo_id, project in project_meta.items():
        items = grouped_items.get(repo_id, [])
        item_ids = {str(item.get("id") or "").strip() for item in items if isinstance(item, Mapping)}
        repo_dispatch_results = [
            result
            for item_id in item_ids
            for result in dispatch_by_item_id.get(item_id, [])
            if isinstance(result, Mapping)
        ]
        sorted_items = sorted(items, key=_summary_sort_key, reverse=True)
        if summary_limit > 0:
            sorted_items = sorted_items[:summary_limit]
        history.append(
            {
                "repo_id": repo_id,
                "repo_name": project.get("repo_name", ""),
                "repo_root": project.get("repo_root", ""),
                "remote_url": project.get("remote_url", ""),
                "provider": project.get("provider", ""),
                "branch": project.get("branch", ""),
                "head_commit": project.get("head_commit", ""),
                "summary_count": len(items),
                "outbox_status_counts": _status_counts(items),
                "dispatch_status_counts": _status_counts(repo_dispatch_results),
                "latest_summaries": [_summary_report_item(item) for item in sorted_items],
            }
        )
    return sorted(history, key=lambda item: str(item.get("repo_name") or "").casefold())


def _summary_sort_key(item: Mapping[str, Any]) -> tuple[int, str, str]:
    try:
        number = int(item.get("summary_number") or item.get("version", {}).get("summary_number") or 0)  # type: ignore[union-attr]
    except (AttributeError, TypeError, ValueError):
        number = 0
    return (number, str(item.get("created_at") or ""), str(item.get("id") or ""))


def _summary_report_item(item: Mapping[str, Any]) -> dict[str, Any]:
    summary = item.get("summary", {})
    version = item.get("version", {})
    if not isinstance(summary, Mapping):
        summary = {}
    if not isinstance(version, Mapping):
        version = {}
    return {
        "id": item.get("id", ""),
        "summary_prefix": item.get("summary_prefix") or version.get("summary_prefix", ""),
        "summary_number": item.get("summary_number") or version.get("summary_number"),
        "status": item.get("status", ""),
        "title": summary.get("title", ""),
        "created_at": item.get("created_at", ""),
        "updated_at": item.get("updated_at", ""),
        "changed_files": _summary_list_field(summary, "changed_files"),
        "tests": _summary_list_field(summary, "tests"),
    }


def _summary_list_field(summary: Mapping[str, Any], key: str) -> list[str]:
    value = summary.get(key, [])
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [str(item) for item in value]
    return []


def _format_status_counts(value: object) -> str:
    if not isinstance(value, Mapping) or not value:
        return "none"
    return ", ".join(f"{key}={value[key]}" for key in sorted(value))


def _add_totals(totals: dict[str, int], instance_report: Mapping[str, Any]) -> None:
    history = instance_report.get("codex_history", {})
    if not isinstance(history, Mapping):
        return
    totals["projects"] += len(history.get("projects", []) or [])
    totals["outbox_items"] += int(history.get("outbox_items", 0) or 0)
    totals["dispatch_results"] += int(history.get("dispatch_results", 0) or 0)
    if history.get("errors"):
        totals["store_errors"] += 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
