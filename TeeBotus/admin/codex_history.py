from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import sys
import tomllib
import uuid
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timedelta, timezone
from inspect import isawaitable
from pathlib import Path
from urllib.parse import urlsplit
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from TeeBotus import __version__
from TeeBotus.artifact_outputs import obsidian_incoming_path
from TeeBotus.admin.accounts_report import (
    BOT_INSTRUCTION_FILENAME,
    DEFAULT_INSTANCES_DIR,
    ReadOnlySecretToolInstanceSecretProvider,
    discover_instances,
    parse_csv,
)
from TeeBotus.runtime.actions import SendAttachment
from TeeBotus.runtime.admin_accounts import _resolve_admin_notification_route, runtime_admin_account_ids
from TeeBotus.runtime.accounts import (
    INSTANCE_MAPPING_KEY_PURPOSE,
    INSTANCE_STATE_ACCOUNT_ID,
    AccountStore,
    AccountStoreError,
    InstanceSecretProvider,
)
from TeeBotus.runtime.dotenv import load_project_dotenv_for_instances
from TeeBotus.runtime.proactive_agent import ProactiveSender, select_proactive_route

CODEX_HISTORY_SCHEMA_VERSION = 1
CODEX_HISTORY_TARGET_GROUP = "status_admins"
CODEX_HISTORY_DISPATCHABLE_STATUSES = frozenset({"queued"})
CODEX_HISTORY_DISPATCHABLE_KINDS = frozenset({"codex_run_summary", "codex_strategy_analysis", "codex_graph_artifact"})
CODEX_HISTORY_INDEXABLE_KINDS = frozenset({"codex_run_summary", "codex_strategy_analysis"})
CODEX_HISTORY_BIBLIOTHEKAR_DIRNAME = "Codex_History_Bibliothek"
CODEX_HISTORY_BIBLIOTHEKAR_README = "README.md"
CODEX_HISTORY_DISPATCH_OBSIDIAN_DIRNAME = "Codex_History_Dispatches"
CODEX_HISTORY_GRAPH_DIRNAME = "graphs"
CODEX_HISTORY_DEFAULT_LOCAL_CATEGORY_PROFILE = "local_ollama"
CODEX_HISTORY_DEFAULT_STRATEGY_PROFILE = "local_ollama"
CODEX_HISTORY_DEFAULT_DISPATCH_LIMIT = 0
CODEX_HISTORY_DISPATCHING_STALE_AFTER_SECONDS = 15 * 60
CODEX_HISTORY_FOLLOW_REPORT_ITEMS_LIMIT = 250
CODEX_HISTORY_GRAPH_SVG_ENGINES = frozenset({"builtin", "auto", "mmdc"})
CODEX_HISTORY_LLM_CATEGORY_PURPOSE = "codex_history_categorization"
CODEX_HISTORY_STRATEGY_PURPOSE = "codex_history_strategic_analysis"
CODEX_HISTORY_LINKS_SECTION_TITLE = "## Verknuepfte Summaries"
CODEX_HISTORY_MERMAID_SECTION_TITLE = "## Mermaid-Kontext"
CODEX_HISTORY_MANAGED_SUMMARY_SECTIONS = (
    CODEX_HISTORY_LINKS_SECTION_TITLE,
    CODEX_HISTORY_MERMAID_SECTION_TITLE,
)
CODEX_SESSION_LARGE_FILE_THRESHOLD_BYTES = 16 * 1024 * 1024
CODEX_SESSION_LARGE_FILE_HEAD_BYTES = 512 * 1024
CODEX_SESSION_LARGE_FILE_TAIL_BYTES = 1024 * 1024
CODEX_HISTORY_LLM_CATEGORY_ALLOWLIST = frozenset(
    {
        "change-feature",
        "change-bugfix",
        "change-test",
        "change-docs",
        "change-security",
        "change-dependency",
        "change-runtime",
        "change-memory",
        "change-bibliothekar",
        "change-llm",
        "change-refactor",
        "change-migration",
        "change-performance",
        "change-observability",
        "change-ui",
        "change-cli",
        "change-config",
        "impact-user-visible",
        "impact-admin-only",
        "impact-data-model",
        "risk-security",
        "risk-data-loss",
        "risk-cost",
        "risk-runtime-outage",
        "risk-privacy",
        "work-planning",
        "work-release",
        "work-benchmark",
        "work-strategy",
    }
)

_OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b")
_TELEGRAM_TOKEN_RE = re.compile(r"\b\d{7,12}:[A-Za-z0-9_\-]{25,}\b")
_SAFE_PATH_SEGMENT_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*)")
_SAFE_HIDDEN_PATH_SEGMENT_RE = re.compile(r"\.[A-Za-z0-9](?:[A-Za-z0-9._-]*)")
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


def _split_safe_relative_parts(value: str, *, operation: str, allow_hidden_segments: bool = False) -> tuple[bool, tuple[str, ...]]:
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
        if not _SAFE_PATH_SEGMENT_RE.fullmatch(part) and not (allow_hidden_segments and _SAFE_HIDDEN_PATH_SEGMENT_RE.fullmatch(part)):
            raise ValueError(f"{operation} contains invalid path segment: {part}")
        parts.append(part)
    return is_absolute, tuple(parts)


def _safe_repo_root(value: Path, *, operation: str = "repo access", allow_hidden_segments: bool = False) -> Path:
    text = str(value)
    if "\x00" in text:
        raise ValueError(f"{operation} contains invalid control character")
    is_absolute, parts = _split_safe_relative_parts(text, operation=operation, allow_hidden_segments=allow_hidden_segments)
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


CodexHistoryCategorizer = Callable[[Mapping[str, Any]], Mapping[str, Any] | Sequence[str] | str]
CodexHistoryStrategist = Callable[[Sequence[Mapping[str, Any]]], Mapping[str, Any] | str]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _display_timestamp(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    timezone_name = os.environ.get("TEEBOTUS_CODEX_HISTORY_TIMEZONE", "Europe/Berlin").strip() or "Europe/Berlin"
    try:
        display_timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        display_timezone = datetime.now().astimezone().tzinfo or timezone.utc
    return parsed.astimezone(display_timezone).isoformat(timespec="seconds")


def _display_codex_history_timestamp(value: object) -> str:
    return redact_codex_history_text(_display_timestamp(value)).strip()


def _display_timestamp_filename_prefix(value: object) -> str:
    displayed = _display_timestamp(value)
    date_prefix = re.sub(r"[^0-9T]+", "", displayed[:19].replace("-", "").replace(":", ""))
    if date_prefix:
        return date_prefix
    fallback = _display_timestamp(utc_now())
    return re.sub(r"[^0-9T]+", "", fallback[:19].replace("-", "").replace(":", ""))


def _build_codex_history_summary_item(
    rows: Sequence[Mapping[str, Any]],
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
    timestamp: str | None = None,
) -> dict[str, Any]:
    repo = build_repo_metadata(repo_root)
    version = resolve_repo_version(repo["repo_root"])
    created_at = timestamp or utc_now()
    redacted_title = redact_codex_history_text(title).strip() or "Codex run summary"
    redacted_bullets = [redact_codex_history_text(item).strip() for item in bullets if str(item or "").strip()]
    redacted_changed_files = [redact_codex_history_text(item).strip() for item in changed_files if str(item or "").strip()]
    redacted_tests = [redact_codex_history_text(item).strip() for item in tests if str(item or "").strip()]
    summary_number = _next_summary_number_for_repo(rows, repo["repo_id"])
    summary_prefix = _summary_prefix(version["semver"], summary_number)
    metadata = codex_metadata if isinstance(codex_metadata, Mapping) else {}
    intermediate_metadata = metadata.get("intermediate_messages", ())
    if isinstance(intermediate_metadata, (str, bytes, bytearray)) or not isinstance(intermediate_metadata, Sequence):
        intermediate_metadata = ()
    markdown = build_codex_history_markdown(
        summary_prefix=summary_prefix,
        title=redacted_title,
        repo=repo,
        version=version,
        bullets=redacted_bullets,
        changed_files=redacted_changed_files,
        tests=redacted_tests,
        created_at=created_at,
        goal=str(metadata.get("goal") or ""),
        auftrag=str(metadata.get("auftrag") or ""),
        current_task=str(metadata.get("current_task") or ""),
        intermediate_messages=intermediate_metadata,
    )
    codex_payload = {
        "session_id": redact_codex_history_text(session_id).strip(),
        "cwd": repo["repo_root"],
        "finished_at": created_at,
    }
    if isinstance(codex_metadata, Mapping):
        codex_payload.update({str(key): _redact_codex_history_json(value) for key, value in codex_metadata.items()})
    return {
        "id": _unique_history_id(rows),
        "schema_version": CODEX_HISTORY_SCHEMA_VERSION,
        "kind": "codex_run_summary",
        "source": source,
        "status": status,
        "created_at": created_at,
        "updated_at": created_at,
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
                "at": created_at,
                "status": status,
                "reason": "codex_history_summary_created",
            }
        ],
        "summary_number": summary_number,
        "summary_prefix": summary_prefix,
    }


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
    account_id = INSTANCE_STATE_ACCOUNT_ID
    with store.codex_history_outbox_lock(account_id):
        rows = store.read_codex_history_outbox(account_id)
        timestamp = utc_now()
        item = _build_codex_history_summary_item(
            rows,
            repo_root=repo_root,
            title=title,
            bullets=bullets,
            changed_files=changed_files,
            tests=tests,
            session_id=session_id,
            source=source,
            status=status,
            target_group=target_group,
            codex_metadata=codex_metadata,
            timestamp=timestamp,
        )
        rows.append(item)
        _refresh_codex_history_summary_context_rows(rows)
        store.write_codex_history_outbox(account_id, rows)
        project = item.get("project", {})
        if isinstance(project, Mapping):
            _upsert_project(store, account_id, project, item, timestamp)
        return dict(item)


async def dispatch_codex_history_outbox(
    store: AccountStore,
    *,
    instance_name: str,
    account_ids: Sequence[str] = (),
    senders: Mapping[str, ProactiveSender] | None = None,
    env: Mapping[str, str] | None = None,
    instances_dir: str | Path | None = None,
    secret_provider: InstanceSecretProvider | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    dispatch_now = now or datetime.now(timezone.utc)
    timestamp = _iso_timestamp(dispatch_now)
    resolved_senders = senders or {}
    candidate_account_ids = _codex_history_dispatch_account_ids(store, instance_name=instance_name, account_ids=account_ids, env=env)
    rows = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
    items = [row for row in rows if _codex_history_item_dispatchable(row, now=dispatch_now)]
    items.sort(key=lambda item: _codex_history_dispatch_sort_key(item, now=dispatch_now), reverse=True)
    if limit > 0:
        items = items[:limit]
    result_rows: list[dict[str, Any]] = []
    for item in items:
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            continue
        if dry_run:
            dry_rows = _dry_run_dispatch_rows(
                item,
                candidate_account_ids,
                store,
                instance_name=instance_name,
                instances_dir=instances_dir,
                secret_provider=secret_provider,
            )
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
                    instances_dir=instances_dir,
                    secret_provider=secret_provider,
                    now=timestamp,
                    persist_result=False,
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
                    persist=False,
                )
            )
        store.append_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID, item_results)
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
    account_id = INSTANCE_STATE_ACCOUNT_ID
    imported: list[dict[str, Any]] = []
    with store.codex_history_outbox_lock(account_id):
        rows = store.read_codex_history_outbox(account_id)
        results = _build_codex_session_import_results(rows, session_file)
        result = _aggregate_codex_session_import_results(results, session_file)
        for item_result in results:
            if item_result.get("status") == "imported" and isinstance(item_result.get("item"), Mapping):
                imported.append(dict(item_result["item"]))
        if imported:
            _refresh_codex_history_summary_context_rows(rows)
            store.write_codex_history_outbox(account_id, rows)
    for item in imported:
        project = item.get("project", {})
        if isinstance(project, Mapping):
            _upsert_project(store, account_id, project, item, str(item.get("created_at") or utc_now()))
    return result


def import_codex_session_roots(store: AccountStore, roots: Sequence[str | Path], *, limit: int = 1000) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    imported_items: list[dict[str, Any]] = []
    account_id = INSTANCE_STATE_ACCOUNT_ID
    session_files = _iter_codex_session_files(roots, limit=limit)
    explicit_session_files = _explicit_codex_session_file_roots(roots)
    with store.codex_history_outbox_lock(account_id):
        rows = store.read_codex_history_outbox(account_id)
        for session_file in session_files:
            try:
                file_results = _build_codex_session_import_results(
                    rows,
                    session_file,
                    final_message_limit=0 if session_file in explicit_session_files else 1,
                )
            except (OSError, ValueError, AccountStoreError) as exc:
                file_results = [
                    {
                        "status": "error",
                        "reason": type(exc).__name__,
                        "error": redact_codex_history_text(str(exc)).strip(),
                        "path": str(session_file),
                    }
                ]
            for result in file_results:
                if result.get("status") == "imported" and isinstance(result.get("item"), Mapping):
                    imported_items.append(dict(result["item"]))
                results.append(result)
        if imported_items:
            _refresh_codex_history_summary_context_rows(rows)
            store.write_codex_history_outbox(account_id, rows)
    for item in imported_items:
        project = item.get("project", {})
        if isinstance(project, Mapping):
            _upsert_project(store, account_id, project, item, str(item.get("created_at") or utc_now()))
    return {
        "ok": not any(result.get("status") == "error" for result in results),
        "items": results,
        "status_counts": _status_counts(results),
    }


def _aggregate_codex_session_import_results(results: Sequence[Mapping[str, Any]], session_file: str | Path) -> dict[str, Any]:
    if len(results) == 1:
        return dict(results[0])
    counts = _status_counts(results)
    imported = [result for result in results if result.get("status") == "imported" and isinstance(result.get("item"), Mapping)]
    if imported:
        status = "imported"
    elif counts and set(counts) == {"duplicate"}:
        status = "duplicate"
    elif counts and set(counts) == {"skipped"}:
        status = "skipped"
    elif counts and set(counts) == {"error"}:
        status = "error"
    else:
        status = "mixed"
    aggregate: dict[str, Any] = {
        "status": status,
        "items": [dict(result) for result in results],
        "status_counts": counts,
        "path": str(_safe_repo_root(Path(session_file), operation="session file", allow_hidden_segments=True)),
    }
    if imported:
        aggregate["item"] = dict(imported[-1]["item"])
    return aggregate


def _build_codex_session_import_results(
    rows: list[dict[str, Any]], session_file: str | Path, *, final_message_limit: int = 0
) -> list[dict[str, Any]]:
    path = _safe_repo_root(Path(session_file), operation="session file", allow_hidden_segments=True)
    parsed = _parse_codex_session_file(path)
    final_messages = parsed.get("final_messages", ())
    if not isinstance(final_messages, Sequence) or isinstance(final_messages, (str, bytes, bytearray)):
        final_messages = ()
    if not final_messages:
        return [{"status": "skipped", "reason": "missing_final_text", "path": str(path)}]
    if final_message_limit > 0:
        final_messages = tuple(final_messages)[-int(final_message_limit) :]
    results: list[dict[str, Any]] = []
    for message in final_messages:
        if not isinstance(message, Mapping):
            continue
        result = _build_codex_session_import_result(
            rows,
            path,
            parsed=parsed,
            turn_id=str(message.get("turn_id") or parsed.get("turn_id") or "").strip(),
            final_text=str(message.get("final_text") or "").strip(),
            goal=str(message.get("goal") or parsed.get("goal") or "").strip(),
            auftrag=str(message.get("auftrag") or parsed.get("auftrag") or "").strip(),
            current_task=str(message.get("current_task") or message.get("auftrag") or parsed.get("auftrag") or "").strip(),
            intermediate_messages=message.get("intermediate_messages", ()),
        )
        results.append(result)
    if not results:
        return [{"status": "skipped", "reason": "missing_final_text", "path": str(path)}]
    return results


def _build_codex_session_import_result(
    rows: list[dict[str, Any]],
    path: Path,
    *,
    parsed: Mapping[str, Any],
    turn_id: str,
    final_text: str,
    goal: str = "",
    auftrag: str = "",
    current_task: str = "",
    intermediate_messages: object = (),
) -> dict[str, Any]:
    if not final_text:
        return {"status": "skipped", "reason": "missing_final_text", "path": str(path)}
    repo_root = str(parsed["cwd"] or path.parent)
    if isinstance(intermediate_messages, (str, bytes, bytearray)) or not isinstance(intermediate_messages, Sequence):
        intermediate_messages = ()
    final_hash = "sha256:" + hashlib.sha256(final_text.encode("utf-8")).hexdigest()
    session_id = str(parsed["session_id"] or path.stem)
    dedupe_key = _codex_session_dedupe_key(session_id=session_id, turn_id=turn_id, final_message_hash=final_hash)
    existing = _find_codex_history_by_dedupe_key_in_rows(rows, dedupe_key)
    if existing is not None:
        return {"status": "duplicate", "reason": "dedupe_key", "item": existing, "path": str(path)}
    try:
        item = _build_codex_history_summary_item(
            rows,
            repo_root=repo_root,
            title=_codex_session_title(final_text),
            bullets=_codex_session_bullets(final_text),
            tests=_codex_session_tests(final_text),
            session_id=session_id,
            source="codex_session_watcher",
            codex_metadata={
                "turn_id": turn_id,
                "goal": goal,
                "auftrag": auftrag,
                "current_task": current_task,
                "intermediate_messages": intermediate_messages if isinstance(intermediate_messages, Sequence) else (),
                "dedupe_key": dedupe_key,
                "final_message_hash": final_hash,
                "source_path_hash": "sha256:" + hashlib.sha256(str(path).encode("utf-8")).hexdigest(),
                "source_mtime": str(parsed.get("source_mtime") or ""),
            },
        )
    except ValueError as exc:
        return {
            "status": "skipped",
            "reason": "invalid_repo_root",
            "error": redact_codex_history_text(str(exc)).strip(),
            "path": str(path),
        }
    rows.append(item)
    return {"status": "imported", "item": dict(item), "path": str(path)}


def _find_codex_history_by_dedupe_key_in_rows(rows: Sequence[Mapping[str, Any]], dedupe_key: str) -> dict[str, Any] | None:
    for item in rows:
        if not isinstance(item, Mapping):
            continue
        codex = item.get("codex", {})
        if isinstance(codex, Mapping) and str(codex.get("dedupe_key") or "") == dedupe_key:
            return dict(item)
    return None


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
    post_scan: Callable[[Mapping[str, Any]], None] | None = None,
    post_idle: Callable[[Mapping[str, Any]], None] | None = None,
) -> dict[str, Any]:
    def _post_scan(_instance_name: str, report: Mapping[str, Any]) -> None:
        if callable(post_scan):
            post_scan(report)

    def _post_idle(_instance_name: str, report: Mapping[str, Any]) -> None:
        if callable(post_idle):
            post_idle(report)

    reports = watch_codex_session_roots_for_instances(
        {"": store},
        roots,
        poll_interval_seconds=poll_interval_seconds,
        max_iterations=max_iterations,
        follow=follow,
        event_mode=event_mode,
        limit=limit,
        sleep=sleep,
        post_scan=_post_scan if callable(post_scan) else None,
        post_idle=_post_idle if callable(post_idle) else None,
    )
    report = dict(reports[0]) if reports else {}
    report.pop("instance", None)
    return report


def watch_codex_session_roots_for_instances(
    stores: Mapping[str, AccountStore],
    roots: Sequence[str | Path],
    *,
    poll_interval_seconds: float = 1.0,
    max_iterations: int = 1,
    follow: bool = False,
    event_mode: str = "poll",
    limit: int = 1000,
    sleep: Callable[[float], None] = time.sleep,
    post_scan: Callable[[str, Mapping[str, Any]], None] | None = None,
    post_idle: Callable[[str, Mapping[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    if not stores:
        return []
    iterations = 0
    if not follow and max_iterations < 1:
        max_iterations = 1
    if poll_interval_seconds < 0:
        poll_interval_seconds = 0.0
    normalized_event_mode = _normalize_watch_event_mode(event_mode)
    reports_by_instance: dict[str, dict[str, Any]] = {
        instance_name: {
            "instance": instance_name,
            "ok": True,
            "iterations": 0,
            "follow": bool(follow),
            "event_mode": normalized_event_mode,
            "skipped_unchanged_iterations": 0,
            "items": [],
            "retained_items": 0,
            "dropped_items": 0,
            "status_counts": {},
        }
        for instance_name in stores
    }
    status_counters_by_instance: dict[str, Counter[str]] = {instance_name: Counter() for instance_name in stores}
    skipped_unchanged = 0
    last_snapshot: tuple[tuple[str, int, int], ...] | None = None
    while True:
        iterations += 1
        current_snapshot = _codex_session_roots_snapshot(roots, limit=limit) if normalized_event_mode != "poll" else None
        should_scan = normalized_event_mode == "poll" or last_snapshot is None or current_snapshot != last_snapshot
        if should_scan:
            for instance_name, store in stores.items():
                instance_report = reports_by_instance[instance_name]
                instance_report["iterations"] = iterations
                scan_report = import_codex_session_roots(store, roots, limit=limit)
                _update_watch_instance_report(
                    instance_report,
                    status_counters_by_instance[instance_name],
                    scan_report.get("items", []),
                    follow=follow,
                )
                if callable(post_scan):
                    post_scan(instance_name, scan_report)
        else:
            skipped_unchanged += 1
            idle_report = {
                "ok": True,
                "items": [],
                "status_counts": {},
                "reason": "unchanged_snapshot",
            }
            for instance_name, instance_report in reports_by_instance.items():
                instance_report["iterations"] = iterations
                instance_report["skipped_unchanged_iterations"] = skipped_unchanged
                if callable(post_idle):
                    post_idle(instance_name, idle_report)
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
    for instance_report in reports_by_instance.values():
        instance_report["iterations"] = iterations
        instance_report["skipped_unchanged_iterations"] = skipped_unchanged
    return list(reports_by_instance.values())


def _update_watch_instance_report(
    instance_report: dict[str, Any],
    status_counter: Counter[str],
    iteration_items: Any,
    *,
    follow: bool,
) -> None:
    if not isinstance(iteration_items, list):
        iteration_items = []
    status_counter.update(_status_counts(iteration_items))
    items = instance_report.get("items", [])
    if not isinstance(items, list):
        items = []
        instance_report["items"] = items
    items.extend(iteration_items)
    if follow and len(items) > CODEX_HISTORY_FOLLOW_REPORT_ITEMS_LIMIT:
        dropped = len(items) - CODEX_HISTORY_FOLLOW_REPORT_ITEMS_LIMIT
        del items[:dropped]
        instance_report["dropped_items"] = int(instance_report.get("dropped_items", 0) or 0) + dropped
    if any(isinstance(item, Mapping) and item.get("status") == "error" for item in iteration_items):
        instance_report["ok"] = False
    else:
        instance_report["ok"] = bool(instance_report.get("ok", True))
    instance_report["retained_items"] = len(items)
    instance_report["status_counts"] = dict(sorted(status_counter.items()))


def default_codex_session_roots() -> tuple[Path, ...]:
    roots = [Path.home() / ".codex" / "sessions"]
    agents_root = Path.home() / ".codex-agents"
    if agents_root.is_dir():
        roots.extend(
            path / "sessions"
            for path in sorted(agents_root.iterdir())
            if path.is_dir() and _is_default_codex_agent_dir(path)
        )
    return tuple(roots)


def _is_default_codex_agent_dir(path: Path) -> bool:
    name = path.name
    return len(name) == 2 and name[0].islower() and name[1] == "1"


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


def export_codex_history_graph_doc(
    store: AccountStore,
    *,
    instance_dir: str | Path,
    instance_name: str,
    repo: str = "",
    limit: int = 0,
    overwrite: bool = True,
    svg: bool = False,
    queue_svg: bool = False,
    svg_engine: str = "builtin",
    now: datetime | None = None,
) -> dict[str, Any]:
    safe_instance_name = _safe_instance_name(instance_name)
    safe_instance_dir = _safe_repo_root(Path(instance_dir), operation="instance directory")
    destination = _codex_history_bibliothekar_root(safe_instance_dir)
    graph_dir = (destination / CODEX_HISTORY_GRAPH_DIRNAME).resolve()
    try:
        graph_dir.relative_to(destination.resolve())
    except ValueError as exc:
        raise ValueError("codex history graph export target escapes admin bibliothekar root") from exc
    rows = _filter_outbox(store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID), repo)
    items = [item for item in rows if _codex_history_item_indexable(item)]
    items = sorted(items, key=_summary_sort_key)
    if limit > 0:
        items = items[-int(limit) :]
    graph_dir.mkdir(parents=True, exist_ok=True)
    filename = "codex_history_graph.md" if not str(repo or "").strip() else f"codex_history_graph_{_safe_filename_component(repo, default='repo')}.md"
    target = (graph_dir / filename).resolve()
    exported = 0
    skipped = 0
    reason = ""
    if target.exists() and not overwrite:
        skipped = 1
        reason = "exists"
    else:
        target.write_text(_codex_history_graph_markdown(items, instance_name=safe_instance_name, repo_filter=repo), encoding="utf-8")
        exported = 1
    svg_exported = 0
    svg_skipped = 0
    svg_target = target.with_suffix(".svg")
    svg_text = ""
    svg_engine_used = ""
    svg_warning = ""
    if svg or queue_svg:
        svg_text, svg_engine_used, svg_warning = _render_codex_history_graph_svg(
            items,
            instance_name=safe_instance_name,
            repo_filter=repo,
            engine=svg_engine,
        )
    if svg:
        if svg_target.exists() and not overwrite:
            svg_skipped = 1
        else:
            svg_target.write_text(svg_text, encoding="utf-8")
            svg_exported = 1
    queued_item: dict[str, Any] = {}
    if queue_svg:
        queued_item = queue_codex_history_graph_svg_artifact(
            store,
            instance_name=safe_instance_name,
            repo=repo,
            svg_text=svg_text,
            svg_filename=svg_target.name,
            source_path=str(svg_target if svg else target),
            item_count=len(items),
            repo_count=_codex_history_graph_repo_count(items),
            now=now,
        )
    return {
        "ok": True,
        "instance": safe_instance_name,
        "path": str(target),
        "exported": exported,
        "skipped": skipped,
        "reason": reason,
        "svg": bool(svg),
        "svg_path": str(svg_target) if svg else "",
        "svg_engine": svg_engine_used,
        "svg_warning": svg_warning,
        "svg_exported": svg_exported,
        "svg_skipped": svg_skipped,
        "queued_item": queued_item,
        "repo_count": _codex_history_graph_repo_count(items),
        "item_count": len(items),
    }


def queue_codex_history_graph_svg_artifact(
    store: AccountStore,
    *,
    instance_name: str,
    repo: str = "",
    svg_text: str,
    svg_filename: str = "codex_history_graph.svg",
    source_path: str = "",
    item_count: int = 0,
    repo_count: int = 0,
    status: str = "queued",
    now: datetime | None = None,
) -> dict[str, Any]:
    safe_instance_name = _safe_instance_name(instance_name)
    timestamp = _iso_timestamp(now)
    project = _codex_history_graph_project(safe_instance_name, repo=repo)
    version = {"semver": __version__, "tag": f"v{__version__}"}
    normalized_status = str(status or "queued").strip().casefold() or "queued"
    safe_filename = _safe_filename_component(svg_filename, default="codex_history_graph", max_length=128)
    if not safe_filename.endswith(".svg"):
        safe_filename = f"{safe_filename}.svg"
    redacted_svg = redact_codex_history_text(svg_text)
    with store.codex_history_outbox_lock(INSTANCE_STATE_ACCOUNT_ID):
        rows = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
        summary_number = _next_summary_number_for_repo(rows, project["repo_id"])
        summary_prefix = _summary_prefix(version["semver"], summary_number)
        markdown = _codex_history_graph_artifact_markdown(
            summary_prefix=summary_prefix,
            instance_name=safe_instance_name,
            repo_filter=repo,
            svg_filename=safe_filename,
            source_path=source_path,
            item_count=item_count,
            repo_count=repo_count,
            created_at=timestamp,
        )
        item = {
            "id": _unique_history_id(rows),
            "schema_version": CODEX_HISTORY_SCHEMA_VERSION,
            "kind": "codex_graph_artifact",
            "source": "codex_history_graph_export",
            "status": normalized_status,
            "created_at": timestamp,
            "updated_at": timestamp,
            "project": project,
            "version": {
                "semver": version["semver"],
                "tag": version["tag"],
                "summary_number": summary_number,
                "summary_prefix": summary_prefix,
            },
            "codex": {
                "purpose": "codex_history_graph_artifact",
                "repo_filter": str(repo or "").strip(),
                "source_path": redact_codex_history_text(source_path).strip(),
                "generated_at": timestamp,
                "item_count": int(item_count or 0),
                "repo_count": int(repo_count or 0),
            },
            "summary": {
                "title": "Codex-History SVG-Graph",
                "markdown": markdown,
                "bullets": [
                    f"SVG-Graph fuer {int(repo_count or 0)} Repos und {int(item_count or 0)} Summaries erzeugt.",
                    "Als Admin-only Attachment queued.",
                ],
                "changed_files": [],
                "tests": [],
            },
            "attachment": {
                "filename": safe_filename,
                "content_type": "image/svg+xml",
                "caption": f"Codex-History Graph {safe_instance_name}",
                "data_text": redacted_svg,
            },
            "delivery": {
                "target_group": CODEX_HISTORY_TARGET_GROUP,
                "attempts": 0,
                "last_attempt_at": "",
                "sent_at": "",
                "accepted_at": "",
                "delivered_at": "",
                "acknowledged_at": "",
            },
            "indexing": {
                "indexable": False,
                "repo_history": True,
                "categories": ["codex-history-graph", "impact-admin-only"],
                "keywords": ["admin-only", "codex", "history", "graph", "svg", safe_instance_name.casefold()],
            },
            "status_history": [
                {
                    "at": timestamp,
                    "status": normalized_status,
                    "reason": "codex_history_graph_svg_queued",
                }
            ],
            "summary_number": summary_number,
            "summary_prefix": summary_prefix,
        }
        rows.append(item)
        store.write_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID, rows)
        _upsert_project(store, INSTANCE_STATE_ACCOUNT_ID, project, item, timestamp)
    return dict(item)


def categorize_codex_history_outbox(
    store: AccountStore,
    *,
    repo: str = "",
    limit: int = 0,
    categorizer: CodexHistoryCategorizer | None = None,
    profile: str = CODEX_HISTORY_DEFAULT_LOCAL_CATEGORY_PROFILE,
    env: Mapping[str, str] | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Annotate Codex history summaries with local, admin-only categories.

    The default categorizer is deliberately local-only. Remote LLM profiles are
    rejected before any provider call can happen.
    """

    timestamp = _iso_timestamp(now)
    llm_categorizer = categorizer or build_local_codex_history_categorizer(profile=profile, env=env)
    rows = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
    candidates = [item for item in _filter_outbox(rows, repo) if _codex_history_item_indexable(item)]
    candidates = sorted(candidates, key=_summary_sort_key)
    if limit > 0:
        candidates = candidates[-int(limit) :]
    candidate_ids = {str(item.get("id") or "").strip() for item in candidates if isinstance(item, Mapping)}
    categorized: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    updates: dict[str, dict[str, Any]] = {}
    for item in candidates:
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            continue
        base_categories = _codex_history_bibliothekar_categories(item, include_persisted=False)
        try:
            decision = llm_categorizer(item)
            llm_categories = _codex_history_llm_categories_from_decision(decision)
            categories = sorted(set(base_categories).union(llm_categories))
            updates[item_id] = {
                "categories": categories,
                "category_source": "local_llm",
                "category_model": _codex_history_categorizer_model(llm_categorizer, profile),
                "categorized_at": timestamp,
                "category_error": "",
            }
            categorized.append(
                {
                    "item_id": item_id,
                    "summary_prefix": str(item.get("summary_prefix") or ""),
                    "categories": categories,
                    "category_source": "local_llm",
                }
            )
        except Exception as exc:  # noqa: BLE001 - optional local LLMs fail in provider-specific ways.
            detail = redact_codex_history_text(f"{type(exc).__name__}: {exc}")[:240]
            updates[item_id] = {
                "categories": sorted(base_categories),
                "category_source": "deterministic_fallback",
                "category_model": _codex_history_categorizer_model(llm_categorizer, profile),
                "categorized_at": timestamp,
                "category_error": detail,
            }
            errors.append(
                {
                    "item_id": item_id,
                    "summary_prefix": str(item.get("summary_prefix") or ""),
                    "error": detail,
                }
            )
    if updates and not dry_run:
        with store.codex_history_outbox_lock(INSTANCE_STATE_ACCOUNT_ID):
            writable_rows = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
            for row in writable_rows:
                if not isinstance(row, dict):
                    continue
                item_id = str(row.get("id") or "").strip()
                if item_id not in candidate_ids or item_id not in updates:
                    continue
                indexing = row.setdefault("indexing", {})
                if not isinstance(indexing, dict):
                    indexing = {}
                    row["indexing"] = indexing
                indexing.update(updates[item_id])
                row["updated_at"] = timestamp
            store.write_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID, writable_rows)
    return {
        "ok": not errors,
        "dry_run": bool(dry_run),
        "profile": str(profile or CODEX_HISTORY_DEFAULT_LOCAL_CATEGORY_PROFILE).strip() or CODEX_HISTORY_DEFAULT_LOCAL_CATEGORY_PROFILE,
        "scanned": len(candidates),
        "categorized": len(categorized),
        "errors": errors,
        "items": categorized,
        "allowed_categories": sorted(CODEX_HISTORY_LLM_CATEGORY_ALLOWLIST),
    }


def build_local_codex_history_categorizer(
    *,
    profile: str = CODEX_HISTORY_DEFAULT_LOCAL_CATEGORY_PROFILE,
    env: Mapping[str, str] | None = None,
) -> CodexHistoryCategorizer:
    from TeeBotus.instructions import BotInstructions
    from TeeBotus.llm.config import build_text_llm_client, load_llm_profiles, normalize_llm_provider

    profile_name = str(profile or CODEX_HISTORY_DEFAULT_LOCAL_CATEGORY_PROFILE).strip() or CODEX_HISTORY_DEFAULT_LOCAL_CATEGORY_PROFILE
    profiles = load_llm_profiles()
    if profile_name not in profiles:
        raise ValueError(f"unknown local Codex-History categorizer profile: {profile_name}")
    llm_profile = profiles[profile_name]
    if llm_profile.is_remote:
        raise ValueError(f"Codex-History categorizer profile must be local-only: {profile_name}")
    instructions = BotInstructions(
        openai_enabled=False,
        llm_enabled=True,
        llm_provider=normalize_llm_provider(llm_profile.provider),
        llm_model=llm_profile.model,
        llm_base_url=llm_profile.base_url,
        llm_timeout_seconds=90,
        llm_max_output_tokens=300,
        llm_temperature=0.0,
        openai_timeout_seconds=90,
        openai_max_output_tokens=300,
        openai_rule_text=(
            "Du kategorisierst nur TeeBotus Codex-History-Eintraege. "
            "Antworte ausschliesslich als JSON-Objekt mit dem Feld categories."
        ),
    )
    source = os.environ if env is None else env
    api_key = str(source.get(llm_profile.api_key_env, "") or "").strip() if llm_profile.api_key_env else ""
    client = build_text_llm_client(
        instructions=instructions,
        openai_client=None,
        provider=llm_profile.provider,
        model=llm_profile.model,
        api_key=api_key,
        api_base=llm_profile.base_url,
        temperature=0.0,
        max_tokens=300,
        timeout=90,
        use_instruction_fallback_models=False,
        env=source,
    )
    if client is None or not hasattr(client, "create_reply"):
        raise ValueError(f"Codex-History categorizer profile is not usable: {profile_name}")

    def _categorize(item: Mapping[str, Any]) -> Mapping[str, Any]:
        response = client.create_reply(_codex_history_category_prompt(item), instructions)  # type: ignore[attr-defined]
        return _parse_codex_history_llm_category_response(str(getattr(response, "text", "") or ""))

    setattr(_categorize, "category_model", llm_profile.model)
    setattr(_categorize, "category_profile", profile_name)
    return _categorize


def generate_codex_history_strategic_analysis(
    store: AccountStore,
    *,
    instance_name: str,
    repo: str = "",
    limit: int = 20,
    strategist: CodexHistoryStrategist | None = None,
    profile: str = CODEX_HISTORY_DEFAULT_STRATEGY_PROFILE,
    allow_remote: bool = False,
    status: str = "queued",
    force: bool = False,
    dry_run: bool = False,
    env: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    safe_instance_name = _safe_instance_name(instance_name)
    timestamp = _iso_timestamp(now)
    rows = _filter_outbox(store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID), repo)
    candidates = [
        item
        for item in rows
        if isinstance(item, Mapping) and str(item.get("kind") or "").strip() == "codex_run_summary"
    ]
    candidates = sorted(candidates, key=_summary_sort_key)
    if limit > 0:
        candidates = candidates[-int(limit) :]
    if not candidates:
        return {
            "ok": True,
            "status": "skipped",
            "reason": "no_codex_run_summaries",
            "instance": safe_instance_name,
            "repo": str(repo or "").strip(),
            "analyzed": 0,
            "dry_run": bool(dry_run),
            "item": {},
        }
    profile_name = str(profile or CODEX_HISTORY_DEFAULT_STRATEGY_PROFILE).strip() or CODEX_HISTORY_DEFAULT_STRATEGY_PROFILE
    source_fingerprint = _codex_history_strategy_source_fingerprint(candidates)
    if not force:
        cached_item = _latest_codex_history_strategy_for_sources(
            rows,
            repo=repo,
            profile=profile_name,
            source_fingerprint=source_fingerprint,
            source_ids=[str(item.get("id") or "") for item in candidates],
        )
        if cached_item:
            return {
                "ok": True,
                "status": "skipped",
                "reason": "source_set_unchanged",
                "instance": safe_instance_name,
                "repo": str(repo or "").strip(),
                "profile": profile_name,
                "allow_remote": bool(allow_remote),
                "analyzed": len(candidates),
                "dry_run": bool(dry_run),
                "cache_hit": True,
                "cached_item_id": str(cached_item.get("id") or ""),
                "cached_summary_prefix": str(cached_item.get("summary_prefix") or ""),
                "item": dict(cached_item),
            }
    strategy_runner = strategist or build_codex_history_strategist(profile=profile, allow_remote=allow_remote, env=env)
    decision = strategy_runner(tuple(candidates))
    analysis = _normalize_codex_history_strategy_decision(decision)
    project = _codex_history_strategy_project(safe_instance_name, repo=repo)
    version = {"semver": __version__, "tag": f"v{__version__}"}
    normalized_status = str(status or "queued").strip().casefold() or "queued"
    with store.codex_history_outbox_lock(INSTANCE_STATE_ACCOUNT_ID):
        existing_rows = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
        summary_number = _next_summary_number_for_repo(existing_rows, project["repo_id"])
        summary_prefix = _summary_prefix(version["semver"], summary_number)
        markdown = _codex_history_strategy_markdown(
            summary_prefix=summary_prefix,
            instance_name=safe_instance_name,
            repo_filter=repo,
            analysis=analysis,
            source_items=candidates,
            created_at=timestamp,
        )
        bullets = _codex_history_strategy_bullets(analysis)
        item = {
            "id": _unique_history_id(existing_rows),
            "schema_version": CODEX_HISTORY_SCHEMA_VERSION,
            "kind": "codex_strategy_analysis",
            "source": "codex_history_strategy_analysis",
            "status": normalized_status,
            "created_at": timestamp,
            "updated_at": timestamp,
            "project": project,
            "version": {
                "semver": version["semver"],
                "tag": version["tag"],
                "summary_number": summary_number,
                "summary_prefix": summary_prefix,
            },
            "codex": {
                "purpose": CODEX_HISTORY_STRATEGY_PURPOSE,
                "repo_filter": str(repo or "").strip(),
                "analyzed_item_ids": [str(item.get("id") or "") for item in candidates],
                "analyzed_summary_prefixes": [str(item.get("summary_prefix") or "") for item in candidates],
                "generated_at": timestamp,
                "strategy_model": _codex_history_strategist_model(strategy_runner, profile),
                "strategy_profile": profile_name,
                "remote_allowed": bool(allow_remote),
                "source_fingerprint": source_fingerprint,
            },
            "summary": {
                "title": "Strategische Codex-History-Analyse",
                "markdown": markdown,
                "bullets": bullets,
                "changed_files": [],
                "tests": [],
            },
            "delivery": {
                "target_group": CODEX_HISTORY_TARGET_GROUP,
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
                "categories": ["codex-strategy-analysis", "impact-admin-only", "work-strategy"],
                "keywords": _codex_history_strategy_keywords(project, analysis, candidates),
            },
            "status_history": [
                {
                    "at": timestamp,
                    "status": normalized_status,
                    "reason": "codex_history_strategy_analysis_created",
                }
            ],
            "summary_number": summary_number,
            "summary_prefix": summary_prefix,
        }
        if not dry_run:
            existing_rows.append(item)
            store.write_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID, existing_rows)
            _upsert_project(store, INSTANCE_STATE_ACCOUNT_ID, project, item, timestamp)
    return {
        "ok": True,
        "status": "dry_run" if dry_run else normalized_status,
        "instance": safe_instance_name,
        "repo": str(repo or "").strip(),
        "profile": profile_name,
        "allow_remote": bool(allow_remote),
        "analyzed": len(candidates),
        "dry_run": bool(dry_run),
        "cache_hit": False,
        "item": item,
    }


def build_codex_history_strategist(
    *,
    profile: str = CODEX_HISTORY_DEFAULT_STRATEGY_PROFILE,
    allow_remote: bool = False,
    env: Mapping[str, str] | None = None,
) -> CodexHistoryStrategist:
    from TeeBotus.instructions import BotInstructions
    from TeeBotus.llm.config import build_text_llm_client, load_llm_profiles, normalize_llm_provider

    profile_name = str(profile or CODEX_HISTORY_DEFAULT_STRATEGY_PROFILE).strip() or CODEX_HISTORY_DEFAULT_STRATEGY_PROFILE
    profiles = load_llm_profiles()
    if profile_name not in profiles:
        raise ValueError(f"unknown Codex-History strategy profile: {profile_name}")
    llm_profile = profiles[profile_name]
    if llm_profile.is_remote and not allow_remote:
        raise ValueError(f"Codex-History strategy profile is remote; pass allow_remote=True explicitly: {profile_name}")
    instructions = BotInstructions(
        openai_enabled=False,
        llm_enabled=True,
        llm_provider=normalize_llm_provider(llm_profile.provider),
        llm_model=llm_profile.model,
        llm_base_url=llm_profile.base_url,
        llm_timeout_seconds=180,
        llm_max_output_tokens=1400,
        llm_temperature=0.2,
        openai_timeout_seconds=180,
        openai_max_output_tokens=1400,
        openai_rule_text=(
            "Du analysierst ausschliesslich admin-only Codex-History-Summaries. "
            "Antworte als JSON mit future_improvements, strategic_goals, pitfalls_logic_errors, "
            "attack_surface, recommendations und confidence."
        ),
    )
    source = os.environ if env is None else env
    api_key = str(source.get(llm_profile.api_key_env, "") or "").strip() if llm_profile.api_key_env else ""
    client = build_text_llm_client(
        instructions=instructions,
        openai_client=None,
        provider=llm_profile.provider,
        model=llm_profile.model,
        api_key=api_key,
        api_base=llm_profile.base_url,
        temperature=0.2,
        max_tokens=1400,
        timeout=180,
        use_instruction_fallback_models=False,
        env=source,
    )
    if client is None or not hasattr(client, "create_reply"):
        raise ValueError(f"Codex-History strategy profile is not usable: {profile_name}")

    def _strategize(items: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        response = client.create_reply(_codex_history_strategy_prompt(items), instructions)  # type: ignore[attr-defined]
        return _parse_codex_history_strategy_response(str(getattr(response, "text", "") or ""))

    setattr(_strategize, "strategy_model", llm_profile.model)
    setattr(_strategize, "strategy_profile", profile_name)
    return _strategize


def run_codex_history_index(
    store: AccountStore,
    *,
    instance_dir: str | Path,
    instance_name: str,
    repo: str = "",
    limit: int = 0,
    overwrite: bool = True,
    qdrant: bool = False,
    qdrant_url: str = "",
    qdrant_dry_run: bool = False,
    qdrant_ensure: bool = False,
    graph: bool = False,
    graph_svg: bool = False,
    graph_queue_svg: bool = False,
    graph_svg_engine: str = "builtin",
    categorize: bool = False,
    categorize_profile: str = CODEX_HISTORY_DEFAULT_LOCAL_CATEGORY_PROFILE,
    categorize_dry_run: bool = False,
    categorizer: CodexHistoryCategorizer | None = None,
    strategic_analysis: bool = False,
    strategic_analysis_profile: str = CODEX_HISTORY_DEFAULT_STRATEGY_PROFILE,
    strategic_analysis_allow_remote: bool = False,
    strategic_analysis_dry_run: bool = False,
    strategic_analysis_force: bool = False,
    strategist: CodexHistoryStrategist | None = None,
    env: Mapping[str, str] | None = None,
    secret_provider: InstanceSecretProvider | None = None,
) -> dict[str, Any]:
    safe_instance_name = _safe_instance_name(instance_name)
    safe_instance_dir = _safe_repo_root(Path(instance_dir), operation="instance directory")
    category_report: dict[str, Any] = {}
    if categorize:
        category_report = categorize_codex_history_outbox(
            store,
            repo=repo,
            limit=limit,
            categorizer=categorizer,
            profile=categorize_profile,
            env=env,
            dry_run=categorize_dry_run,
        )
    strategy_report: dict[str, Any] = {}
    if strategic_analysis:
        strategy_report = generate_codex_history_strategic_analysis(
            store,
            instance_name=safe_instance_name,
            repo=repo,
            limit=limit if limit > 0 else 20,
            strategist=strategist,
            profile=strategic_analysis_profile,
            allow_remote=strategic_analysis_allow_remote,
            force=strategic_analysis_force,
            dry_run=strategic_analysis_dry_run,
            env=env,
        )
    context_report = refresh_codex_history_summary_context(store, repo=repo)
    export_report = export_codex_history_bibliothekar_docs(
        store,
        instance_dir=safe_instance_dir,
        instance_name=safe_instance_name,
        repo=repo,
        limit=limit,
        overwrite=overwrite,
    )
    graph_report: dict[str, Any] = {}
    if graph or graph_svg or graph_queue_svg:
        graph_report = export_codex_history_graph_doc(
            store,
            instance_dir=safe_instance_dir,
            instance_name=safe_instance_name,
            repo=repo,
            limit=limit,
            overwrite=overwrite,
            svg=graph_svg,
            queue_svg=graph_queue_svg,
            svg_engine=graph_svg_engine,
        )
    ensure_results: list[dict[str, Any]] = []
    qdrant_results: list[dict[str, Any]] = []
    effective_qdrant_url = str(qdrant_url or "").strip()
    if qdrant_ensure:
        from TeeBotus.embedding.rebuild import ensure_qdrant_collections_for_instances

        ensure_results = [
            _jsonable_result(result)
            for result in ensure_qdrant_collections_for_instances(
                instances_dir=safe_instance_dir.parent,
                instance_names=(safe_instance_name,),
                qdrant_url=effective_qdrant_url or None,
                include_codex_history=True,
            )
        ]
    if qdrant:
        from TeeBotus.embedding.rebuild import rebuild_qdrant_codex_history_indexes

        qdrant_results = [
            _jsonable_result(result)
            for result in rebuild_qdrant_codex_history_indexes(
                instances_dir=safe_instance_dir.parent,
                instance_names=(safe_instance_name,),
                qdrant_url=effective_qdrant_url or None,
                repo=repo,
                limit=limit,
                dry_run=qdrant_dry_run,
                secret_provider=secret_provider,
            )
        ]
    ensure_ok = not ensure_results or all(bool(result.get("ok")) for result in ensure_results)
    qdrant_ok = not qdrant_results or not any(str(result.get("status") or "").casefold() == "error" for result in qdrant_results)
    return {
        "ok": bool(export_report.get("ok", True))
        and bool(category_report.get("ok", True))
        and bool(graph_report.get("ok", True))
        and bool(strategy_report.get("ok", True))
        and ensure_ok
        and qdrant_ok,
        "instance": safe_instance_name,
        "categorize": category_report,
        "summary_context": context_report,
        "export": export_report,
        "graph": graph_report,
        "strategic_analysis": strategy_report,
        "qdrant_ensure": ensure_results,
        "qdrant": qdrant_results,
    }


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


def _redact_codex_history_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _redact_codex_history_json(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_redact_codex_history_json(item) for item in value]
    return redact_codex_history_text(value).strip()


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
    goal: str = "",
    auftrag: str = "",
    current_task: str = "",
    intermediate_messages: Sequence[Mapping[str, Any] | str] = (),
) -> str:
    lines = [
        f"# {summary_prefix} {title}",
        "",
        f"- Projekt: `{repo.get('repo_name', '')}`",
        f"- Repo: `{repo.get('repo_root', '')}`",
        f"- Version: `{version.get('tag', '')}`",
        f"- Commit: `{repo.get('head_commit', '') or '<none>'}`",
        f"- Branch: `{repo.get('branch', '') or '<none>'}`",
        f"- Erstellt: `{_display_codex_history_timestamp(created_at)}`",
    ]
    goal_text = _markdown_header_value(goal)
    auftrag_text = _markdown_header_value(auftrag)
    current_task_text = _markdown_header_value(current_task)
    if goal_text:
        lines.append(f"- Goal: `{goal_text}`")
    if auftrag_text:
        lines.append(f"- Auftrag: `{auftrag_text}`")
    if current_task_text and current_task_text != auftrag_text:
        lines.append(f"- Bearbeiteter Auftrag: `{current_task_text}`")
    lines.extend(["", "## Zusammenfassung"])
    if bullets:
        lines.extend(f"- {bullet}" for bullet in bullets)
    else:
        lines.append("- Keine Detailpunkte angegeben.")
    normalized_intermediate = _normalize_codex_intermediate_messages(intermediate_messages)
    if normalized_intermediate:
        lines.append("")
        lines.append("## Arbeitsverlauf")
        lines.append(f"- Zwischenantworten: `{len(normalized_intermediate)}`")
        for message in normalized_intermediate[:5]:
            phase = _markdown_header_value(message.get("phase", "")) or "commentary"
            text = _truncate(str(message.get("text") or ""), 260)
            if text:
                lines.append(f"- `{phase}`: {text}")
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


def _markdown_header_value(value: object, *, max_length: int = 320) -> str:
    text = redact_codex_history_text(value).strip()
    text = re.sub(r"\s+", " ", text)
    text = text.replace("`", "\\`")
    return _truncate(text, max_length) if text else ""


def _normalize_codex_intermediate_messages(messages: Sequence[Mapping[str, Any] | str]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for entry in messages:
        if isinstance(entry, Mapping):
            phase = redact_codex_history_text(entry.get("phase") or "commentary").strip() or "commentary"
            text = redact_codex_history_text(entry.get("text") or "").strip()
            turn_id = redact_codex_history_text(entry.get("turn_id") or "").strip()
        else:
            phase = "commentary"
            text = redact_codex_history_text(entry).strip()
            turn_id = ""
        if not text:
            continue
        item = {"phase": phase, "text": text}
        if turn_id:
            item["turn_id"] = turn_id
        normalized.append(item)
    return normalized


def refresh_codex_history_summary_context(store: AccountStore, *, repo: str = "") -> dict[str, Any]:
    account_id = INSTANCE_STATE_ACCOUNT_ID
    with store.codex_history_outbox_lock(account_id):
        rows = store.read_codex_history_outbox(account_id)
        changed = _refresh_codex_history_summary_context_rows(rows, repo_filter=repo)
        if changed:
            store.write_codex_history_outbox(account_id, rows)
    return {"ok": True, "changed_items": changed, "repo": str(repo or "").strip()}


def _refresh_codex_history_summary_context_rows(rows: list[dict[str, Any]], *, repo_filter: str = "") -> int:
    items = [row for row in rows if _codex_history_context_item(row)]
    repo_filter_text = str(repo_filter or "").strip().casefold()
    if repo_filter_text:
        items = [
            item
            for item in items
            if repo_filter_text in str(item.get("project", {}).get("repo_name", "") if isinstance(item.get("project"), Mapping) else "").casefold()
            or repo_filter_text in str(item.get("project", {}).get("repo_root", "") if isinstance(item.get("project"), Mapping) else "").casefold()
        ]
    if not items:
        return 0
    all_items = [row for row in rows if _codex_history_context_item(row)]
    global_sorted = sorted(all_items, key=_summary_sort_key)
    repo_groups: dict[str, list[dict[str, Any]]] = {}
    for item in all_items:
        project = item.get("project", {})
        if not isinstance(project, Mapping):
            project = {}
        repo_id = str(project.get("repo_id") or project.get("repo_name") or "repo").strip() or "repo"
        repo_groups.setdefault(repo_id, []).append(item)
    for repo_items in repo_groups.values():
        repo_items.sort(key=_summary_sort_key)
    changed = 0
    timestamp = utc_now()
    for item in items:
        project = item.get("project", {})
        if not isinstance(project, Mapping):
            project = {}
        repo_id = str(project.get("repo_id") or project.get("repo_name") or "repo").strip() or "repo"
        repo_items = repo_groups.get(repo_id, [])
        previous_repo, next_repo = _codex_history_neighbors(repo_items, item)
        previous_global, next_global = _codex_history_neighbors(global_sorted, item)
        summary = item.get("summary", {})
        if not isinstance(summary, dict):
            continue
        markdown = str(summary.get("markdown") or "")
        updated = _codex_history_markdown_with_context(
            markdown,
            item=item,
            previous_repo=previous_repo,
            next_repo=next_repo,
            previous_global=previous_global,
            next_global=next_global,
        )
        if updated != markdown:
            summary["markdown"] = updated
            item["updated_at"] = timestamp
            changed += 1
    return changed


def _codex_history_context_item(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    if str(item.get("kind") or "").strip() != "codex_run_summary":
        return False
    summary = item.get("summary", {})
    return isinstance(summary, dict)


def _codex_history_neighbors(items: Sequence[Mapping[str, Any]], current: Mapping[str, Any]) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]:
    current_id = str(current.get("id") or "").strip()
    previous: Mapping[str, Any] | None = None
    for index, item in enumerate(items):
        if str(item.get("id") or "").strip() != current_id:
            previous = item
            continue
        next_item = items[index + 1] if index + 1 < len(items) else None
        return previous, next_item
    return None, None


def _codex_history_markdown_with_context(
    markdown: str,
    *,
    item: Mapping[str, Any],
    previous_repo: Mapping[str, Any] | None,
    next_repo: Mapping[str, Any] | None,
    previous_global: Mapping[str, Any] | None,
    next_global: Mapping[str, Any] | None,
) -> str:
    base = _strip_codex_history_managed_sections(markdown).rstrip()
    sections = [
        _codex_history_links_section(
            item,
            previous_repo=previous_repo,
            next_repo=next_repo,
            previous_global=previous_global,
            next_global=next_global,
        ),
        _codex_history_mermaid_section(item, previous_repo=previous_repo, next_repo=next_repo),
    ]
    return (base + "\n\n" + "\n\n".join(section for section in sections if section.strip()) + "\n").lstrip()


def _strip_codex_history_managed_sections(markdown: str) -> str:
    text = str(markdown or "")
    for title in CODEX_HISTORY_MANAGED_SUMMARY_SECTIONS:
        text = re.sub(rf"(?:\n{{0,2}}){re.escape(title)}\n.*?(?=\n## |\Z)", "", text, flags=re.DOTALL).rstrip()
    return text


def _codex_history_links_section(
    item: Mapping[str, Any],
    *,
    previous_repo: Mapping[str, Any] | None,
    next_repo: Mapping[str, Any] | None,
    previous_global: Mapping[str, Any] | None,
    next_global: Mapping[str, Any] | None,
) -> str:
    del previous_global, next_global
    lines = [CODEX_HISTORY_LINKS_SECTION_TITLE]
    lines.append(f"- Diese Summary: {_codex_history_item_reference(item)}")
    lines.append(f"- Vorherige im Repo: {_codex_history_item_reference(previous_repo) if previous_repo else '`<none>`'}")
    lines.append(f"- Naechste im Repo: {_codex_history_item_reference(next_repo) if next_repo else '`<none>`'}")
    session_id = str(item.get("codex", {}).get("session_id", "") if isinstance(item.get("codex"), Mapping) else "").strip()
    if session_id:
        lines.append(f"- Session: `{redact_codex_history_text(session_id).strip()}`")
    return "\n".join(lines)


def _codex_history_item_reference(item: Mapping[str, Any] | None) -> str:
    if not isinstance(item, Mapping):
        return "`<none>`"
    label = _codex_history_item_label(item)
    item_id = redact_codex_history_text(item.get("id") or "").strip()
    stem = Path(_codex_history_bibliothekar_filename(item)).stem
    if item_id:
        return f"[[{stem}|{label}]] (`{item_id}`)"
    return f"[[{stem}|{label}]]"


def _codex_history_item_label(item: Mapping[str, Any]) -> str:
    summary = item.get("summary", {})
    if not isinstance(summary, Mapping):
        summary = {}
    return _truncate(f"{item.get('summary_prefix', '')} {summary.get('title', 'Codex run summary')}", 90)


def _codex_history_mermaid_section(
    item: Mapping[str, Any],
    *,
    previous_repo: Mapping[str, Any] | None,
    next_repo: Mapping[str, Any] | None,
) -> str:
    project = item.get("project", {})
    if not isinstance(project, Mapping):
        project = {}
    summary = item.get("summary", {})
    if not isinstance(summary, Mapping):
        summary = {}
    repo_name = _mermaid_label(str(project.get("repo_name") or "Repo"), max_length=48)
    current_label = _mermaid_label(_codex_history_item_label(item), max_length=72)
    direction = _codex_history_mermaid_direction(item)
    changed_count = len(_sequence_values(summary.get("changed_files", [])))
    test_count = len(_sequence_values(summary.get("tests", [])))
    bullet_count = len(_sequence_values(summary.get("bullets", [])))
    status = _mermaid_label(str(item.get("status") or "unknown"), max_length=32)
    version = item.get("version", {})
    if not isinstance(version, Mapping):
        version = {}
    summary_prefix = str(item.get("summary_prefix") or "").strip()
    version_value = summary_prefix or str(version.get("tag") or version.get("semver") or "untagged").strip()
    version_label = _mermaid_label(version_value, max_length=48)
    delivery_label = _mermaid_label(_codex_history_mermaid_delivery_label(item), max_length=48)
    status_history_count = _codex_history_status_history_count(item)
    categories = _codex_history_mermaid_categories(item)
    lines = [
        CODEX_HISTORY_MERMAID_SECTION_TITLE,
        "```mermaid",
        f"flowchart {direction}",
        '  subgraph timeline["Repo-Kontext"]',
        "    direction LR",
        f'    repo["{repo_name}"]:::repo',
        f'    current(["{current_label}"]):::current',
        "    repo -->|enthaelt| current",
    ]
    if previous_repo:
        previous_label = _mermaid_label(_codex_history_item_label(previous_repo), max_length=72)
        lines.append(f'    previous["{previous_label}"]:::summary')
        lines.append("    previous -->|vorher| current")
    if next_repo:
        next_label = _mermaid_label(_codex_history_item_label(next_repo), max_length=72)
        lines.append(f'    next["{next_label}"]:::summary')
        lines.append("    current -->|naechste| next")
    lines.extend(
        [
            "  end",
            '  subgraph signals["Signale"]',
            "    direction TB",
            f'    status{{"Status: {status}"}}:::status',
            f'    delivery["Dispatch: {delivery_label}"]:::dispatch',
            f'    history["Status-Historie: {status_history_count}"]:::metric',
            "  end",
            '  subgraph scope["Umfang"]',
            "    direction TB",
            f'    version["Version: {version_label or "unknown"}"]:::version',
            f'    files["Dateien: {changed_count}"]:::metric',
            f'    checks["Checks: {test_count}"]:::metric',
            f'    bullets["Punkte: {bullet_count}"]:::metric',
            "  end",
            "  current -->|Stand| status",
            "  current -->|Versand| delivery",
            "  status -->|Aenderungen| history",
            "  current -->|Release| version",
            "  current -->|Scope| files",
            "  current -->|Verifikation| checks",
            "  current -->|Inhalt| bullets",
        ]
    )
    if categories:
        lines.extend(['  subgraph categories["Kategorien"]', "    direction TB"])
        for index, category in enumerate(categories):
            category_label = _mermaid_label(category, max_length=42)
            lines.append(f'    category_{index}["{category_label}"]:::category')
            lines.append(f"    current -->|tag| category_{index}")
        lines.append("  end")
    lines.extend(
        [
            "  classDef repo fill:#dbeafe,stroke:#2563eb,color:#111827",
            "  classDef current fill:#dcfce7,stroke:#16a34a,color:#111827,stroke-width:2px",
            "  classDef summary fill:#f3f4f6,stroke:#6b7280,color:#111827",
            "  classDef status fill:#fef3c7,stroke:#d97706,color:#111827",
            "  classDef dispatch fill:#fee2e2,stroke:#dc2626,color:#111827",
            "  classDef version fill:#e0f2fe,stroke:#0284c7,color:#111827",
            "  classDef metric fill:#f8fafc,stroke:#64748b,color:#111827",
            "  classDef category fill:#f3e8ff,stroke:#7c3aed,color:#111827",
            "```",
        ]
    )
    return "\n".join(lines)


def _codex_history_mermaid_direction(item: Mapping[str, Any]) -> str:
    summary = item.get("summary", {})
    if not isinstance(summary, Mapping):
        summary = {}
    categories = set(_codex_history_bibliothekar_categories(item))
    if _sequence_values(summary.get("tests", [])) or "change-test" in categories:
        return "TD"
    if any(category.startswith("risk-") for category in categories) or "change-security" in categories:
        return "BT"
    if "change-docs" in categories or "change-bibliothekar" in categories:
        return "RL"
    signature = "|".join(
        [
            str(item.get("id") or ""),
            str(item.get("summary_prefix") or ""),
            str(summary.get("title") or ""),
            ",".join(sorted(categories)),
        ]
    )
    directions = ("LR", "TD", "RL")
    digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()
    return directions[int(digest[:2], 16) % len(directions)]


def _codex_history_mermaid_categories(item: Mapping[str, Any]) -> list[str]:
    ignored = {"admin-only", "codex-history", "project-history"}
    priority_prefixes = ("risk-", "impact-", "change-", "work-")
    categories = []
    for category in _codex_history_bibliothekar_categories(item):
        value = str(category or "").strip()
        if not value or value in ignored or value.startswith(("repo-", "status-")):
            continue
        categories.append(value)
    categories.sort(
        key=lambda value: (
            next((index for index, prefix in enumerate(priority_prefixes) if value.startswith(prefix)), len(priority_prefixes)),
            value,
        )
    )
    return categories[:5]


def _codex_history_mermaid_delivery_label(item: Mapping[str, Any]) -> str:
    delivery = item.get("delivery", {})
    if not isinstance(delivery, Mapping):
        delivery = {}
    stages = (
        ("acknowledged", "acknowledged_at"),
        ("delivered", "delivered_at"),
        ("accepted", "accepted_at"),
        ("sent", "sent_at"),
    )
    for label, field in stages:
        if str(delivery.get(field) or "").strip():
            return label
    attempts = delivery.get("attempts", 0)
    try:
        attempt_count = int(attempts or 0)
    except (TypeError, ValueError):
        attempt_count = 0
    if attempt_count > 0:
        return f"attempts: {attempt_count}"
    return "not sent"


def _codex_history_status_history_count(item: Mapping[str, Any]) -> int:
    status_history = item.get("status_history", [])
    if isinstance(status_history, Sequence) and not isinstance(status_history, (str, bytes, bytearray)):
        return len(status_history)
    return 0


_CODEX_HISTORY_MARKDOWN_TIMESTAMP_RE = re.compile(
    r"^(?P<prefix>[ \t]*-[ \t]*(?:Erstellt|Aktualisiert|Sent|Accepted|Delivered|Acknowledged):[ \t]*`)"
    r"(?P<timestamp>[^`\n]+)"
    r"(?P<suffix>`[ \t]*)$",
    re.MULTILINE,
)


def rewrite_codex_history_markdown_display_times(markdown: object) -> tuple[str, int]:
    text = str(markdown or "")
    rewritten = 0

    def _replace(match: re.Match[str]) -> str:
        nonlocal rewritten
        original = match.group("timestamp").strip()
        displayed = _display_codex_history_timestamp(original)
        if not displayed or displayed == original:
            return match.group(0)
        rewritten += 1
        return f"{match.group('prefix')}{displayed}{match.group('suffix')}"

    return _CODEX_HISTORY_MARKDOWN_TIMESTAMP_RE.sub(_replace, text), rewritten


def rewrite_codex_history_display_times(
    store: AccountStore,
    *,
    instance_name: str,
    repo: str = "",
    dry_run: bool = True,
    include_dispatch_files: bool = False,
) -> dict[str, Any]:
    safe_instance_name = _safe_instance_name(instance_name)
    report: dict[str, Any] = {
        "ok": True,
        "instance": safe_instance_name,
        "repo": str(repo or "").strip(),
        "dry_run": bool(dry_run),
        "include_dispatch_files": bool(include_dispatch_files),
        "scanned_items": 0,
        "changed_items": 0,
        "timestamp_rewrites": 0,
        "changed_item_ids": [],
        "dispatch_files": {
            "scanned": 0,
            "changed": 0,
            "renamed": 0,
            "missing": 0,
            "unsafe": 0,
            "errors": [],
        },
    }
    with store.codex_history_outbox_lock(INSTANCE_STATE_ACCOUNT_ID):
        rows = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
        rewritten_rows: list[dict[str, Any]] = []
        item_by_id: dict[str, Mapping[str, Any]] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                rewritten_rows.append(dict(row) if isinstance(row, dict) else {"value": row})
                continue
            if not _codex_history_item_matches_repo(row, repo):
                copied = dict(row)
                rewritten_rows.append(copied)
                item_id = str(copied.get("id") or "").strip()
                if item_id:
                    item_by_id[item_id] = copied
                continue
            report["scanned_items"] += 1
            item = copy.deepcopy(dict(row))
            item_id = str(item.get("id") or "").strip()
            summary = item.get("summary", {})
            item_rewrites = 0
            if isinstance(summary, Mapping):
                markdown = summary.get("markdown")
                if isinstance(markdown, str) and markdown:
                    rewritten_markdown, item_rewrites = rewrite_codex_history_markdown_display_times(markdown)
                    if rewritten_markdown != markdown:
                        new_summary = dict(summary)
                        new_summary["markdown"] = rewritten_markdown
                        item["summary"] = new_summary
            if item_rewrites:
                report["changed_items"] += 1
                report["timestamp_rewrites"] += item_rewrites
                if item_id:
                    report["changed_item_ids"].append(item_id)
            rewritten_rows.append(item)
            if item_id:
                item_by_id[item_id] = item
        dispatch_rows: list[dict[str, Any]] = []
        dispatch_rows_changed = False
        if include_dispatch_files:
            dispatch_rows = store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID)
            dispatch_rows_changed = _rewrite_codex_history_dispatch_files(
                dispatch_rows,
                item_by_id=item_by_id,
                repo=repo,
                dry_run=bool(dry_run),
                report=report["dispatch_files"],
            )
        if not dry_run:
            if report["changed_items"]:
                store.write_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID, rewritten_rows)
            if include_dispatch_files and dispatch_rows_changed:
                store.write_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID, dispatch_rows)
    return report


def rewrite_codex_history_display_times_for_instances(
    *,
    instances_dir: str | Path = DEFAULT_INSTANCES_DIR,
    instances: Sequence[str] = (),
    repo: str = "",
    dry_run: bool = True,
    include_dispatch_files: bool = False,
    provider: InstanceSecretProvider | None = None,
) -> dict[str, Any]:
    safe_instances_dir = _safe_repo_root(Path(instances_dir), operation="instances directory")
    selected_instances = tuple(instances)
    _ensure_explicit_instances_exist(safe_instances_dir, selected_instances)
    reports: list[dict[str, Any]] = []
    for instance_name in discover_instances(safe_instances_dir, selected_instances):
        try:
            store = _store_for_instance(safe_instances_dir, instance_name, provider)
            reports.append(
                rewrite_codex_history_display_times(
                    store,
                    instance_name=instance_name,
                    repo=repo,
                    dry_run=dry_run,
                    include_dispatch_files=include_dispatch_files,
                )
            )
        except (AccountStoreError, OSError, ValueError) as exc:
            reports.append(
                {
                    "ok": False,
                    "instance": str(instance_name or ""),
                    "error": f"{type(exc).__name__}:{exc}",
                    "dry_run": bool(dry_run),
                }
            )
    totals = {
        "instances": len(reports),
        "scanned_items": sum(int(report.get("scanned_items") or 0) for report in reports),
        "changed_items": sum(int(report.get("changed_items") or 0) for report in reports),
        "timestamp_rewrites": sum(int(report.get("timestamp_rewrites") or 0) for report in reports),
        "dispatch_files_changed": sum(int(report.get("dispatch_files", {}).get("changed") or 0) for report in reports if isinstance(report.get("dispatch_files"), Mapping)),
        "dispatch_files_renamed": sum(int(report.get("dispatch_files", {}).get("renamed") or 0) for report in reports if isinstance(report.get("dispatch_files"), Mapping)),
        "errors": sum(1 for report in reports if not bool(report.get("ok", True))),
    }
    return {
        "ok": not any(not bool(report.get("ok", True)) for report in reports),
        "schema_version": CODEX_HISTORY_SCHEMA_VERSION,
        "scope": "codex_history_time_rewrite",
        "generated_at": utc_now(),
        "instances_dir": str(safe_instances_dir),
        "repo": str(repo or "").strip(),
        "dry_run": bool(dry_run),
        "include_dispatch_files": bool(include_dispatch_files),
        "instances": reports,
        "totals": totals,
    }


def _codex_history_item_matches_repo(item: Mapping[str, Any], repo: str) -> bool:
    project = item.get("project", {})
    if not isinstance(project, Mapping):
        project = {}
    return _project_matches_repo(project, repo)


def _rewrite_codex_history_dispatch_files(
    dispatch_rows: list[dict[str, Any]],
    *,
    item_by_id: Mapping[str, Mapping[str, Any]],
    repo: str,
    dry_run: bool,
    report: dict[str, Any],
) -> bool:
    changed_rows = False
    for row in dispatch_rows:
        if not isinstance(row, dict):
            continue
        item_id = str(row.get("codex_history_item_id") or "").strip()
        item = item_by_id.get(item_id)
        if not item or not _codex_history_item_matches_repo(item, repo):
            continue
        path_text = str(row.get("obsidian_path") or "").strip()
        if not path_text:
            continue
        path = Path(path_text).expanduser()
        report["scanned"] = int(report.get("scanned") or 0) + 1
        if not _is_codex_history_dispatch_markdown_path(path):
            report["unsafe"] = int(report.get("unsafe") or 0) + 1
            continue
        if not path.exists():
            report["missing"] = int(report.get("missing") or 0) + 1
            continue
        try:
            original_text = path.read_text(encoding="utf-8")
            rewritten_text, rewrites = rewrite_codex_history_markdown_display_times(original_text)
            target_path = _local_codex_history_dispatch_path(path, item)
            changed_text = rewritten_text != original_text
            renamed = target_path != path
            if changed_text:
                report["changed"] = int(report.get("changed") or 0) + 1
            if renamed:
                report["renamed"] = int(report.get("renamed") or 0) + 1
            if dry_run:
                continue
            if changed_text:
                path.write_text(rewritten_text, encoding="utf-8")
            if renamed:
                if target_path.exists():
                    _append_dispatch_file_error(report, path, f"target exists: {target_path}")
                    continue
                path.rename(target_path)
                row["obsidian_path"] = str(target_path)
                changed_rows = True
            if rewrites and not changed_rows:
                changed_rows = True
        except OSError as exc:
            _append_dispatch_file_error(report, path, f"{type(exc).__name__}:{exc}")
    return changed_rows


def _is_codex_history_dispatch_markdown_path(path: Path) -> bool:
    return path.suffix.casefold() == ".md" and CODEX_HISTORY_DISPATCH_OBSIDIAN_DIRNAME in path.parts


def _local_codex_history_dispatch_path(path: Path, item: Mapping[str, Any]) -> Path:
    local_prefix = _display_timestamp_filename_prefix(str(item.get("created_at") or ""))
    if not local_prefix:
        return path
    name = path.name
    if name.startswith(f"{local_prefix}_"):
        return path
    new_name = re.sub(r"^\d{8}T\d{6}_", f"{local_prefix}_", name, count=1)
    if new_name == name:
        return path
    return path.with_name(new_name)


def _append_dispatch_file_error(report: dict[str, Any], path: Path, message: str) -> None:
    errors = report.setdefault("errors", [])
    if isinstance(errors, list):
        errors.append({"path": str(path), "error": message})


def _codex_history_dispatch_account_ids(
    store: AccountStore,
    *,
    instance_name: str,
    account_ids: Sequence[str],
    env: Mapping[str, str] | None,
) -> tuple[str, ...]:
    candidates = tuple(str(account_id or "").strip().casefold() for account_id in account_ids if str(account_id or "").strip())
    if not candidates:
        candidates = tuple(runtime_admin_account_ids(store, instance_name=instance_name, env=env))
    seen: set[str] = set()
    result: list[str] = []
    for account_id in candidates:
        if account_id in seen:
            continue
        seen.add(account_id)
        result.append(account_id)
    return tuple(result)


def _codex_history_item_dispatchable(item: Mapping[str, Any], *, now: datetime | None = None) -> bool:
    if not isinstance(item, Mapping):
        return False
    if str(item.get("kind") or "").strip() not in CODEX_HISTORY_DISPATCHABLE_KINDS:
        return False
    status = str(item.get("status") or "queued").strip().casefold()
    if status in CODEX_HISTORY_DISPATCHABLE_STATUSES:
        return True
    if status == "dispatching":
        return _codex_history_item_dispatching_stale(item, now=now)
    return False


def _codex_history_item_dispatching_stale(item: Mapping[str, Any], *, now: datetime | None = None) -> bool:
    if str(item.get("status") or "").strip().casefold() != "dispatching":
        return False
    delivery = item.get("delivery", {})
    if not isinstance(delivery, Mapping):
        delivery = {}
    marker = (
        str(delivery.get("last_attempt_at") or "").strip()
        or str(item.get("updated_at") or "").strip()
        or str(item.get("created_at") or "").strip()
    )
    if not marker:
        return True
    claimed_at = _parse_codex_history_timestamp(marker)
    if claimed_at is None:
        return True
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return reference - claimed_at >= timedelta(seconds=CODEX_HISTORY_DISPATCHING_STALE_AFTER_SECONDS)


def _parse_codex_history_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _codex_history_dispatch_sort_key(item: Mapping[str, Any], *, now: datetime | None = None) -> tuple[int, str, str, str]:
    dispatching_priority = 1 if _codex_history_item_dispatching_stale(item, now=now) else 0
    return (
        dispatching_priority,
        str(item.get("updated_at") or item.get("created_at") or "").strip(),
        str(item.get("created_at") or "").strip(),
        str(item.get("id") or "").strip(),
    )


def _dry_run_dispatch_rows(
    item: Mapping[str, Any],
    account_ids: Sequence[str],
    store: AccountStore,
    *,
    instance_name: str,
    instances_dir: str | Path | None,
    secret_provider: InstanceSecretProvider | None,
) -> list[dict[str, Any]]:
    item_id = str(item.get("id") or "").strip()
    rows: list[dict[str, Any]] = []
    for account_id in account_ids:
        route, reason = _resolve_codex_history_dispatch_route(
            store,
            account_id,
            instance_name=instance_name,
            instances_dir=instances_dir,
            secret_provider=secret_provider,
        )
        channel = str(route.get("channel") or "").strip().casefold() if isinstance(route, Mapping) else ""
        rows.append(
            {
                "codex_history_item_id": item_id,
                "account_id": account_id,
                "status": "would_send" if route is not None else "would_skip",
                "reason": "" if route is not None else (reason or "no_private_route"),
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
    instances_dir: str | Path | None,
    secret_provider: InstanceSecretProvider | None,
    now: str,
    persist_result: bool = True,
) -> dict[str, Any]:
    route, route_reason = _resolve_codex_history_dispatch_route(
        store,
        account_id,
        instance_name=instance_name,
        instances_dir=instances_dir,
        secret_provider=secret_provider,
    )
    if route is None:
        return _record_codex_history_dispatch_result(
            store,
            item,
            account_id,
            status="skipped",
            reason=route_reason or "no_private_route",
            now=now,
            instance_name=instance_name,
            persist=persist_result,
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
            persist=persist_result,
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
            persist=persist_result,
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
            persist=persist_result,
        )
    obsidian_path, obsidian_error = _write_codex_history_dispatch_markdown(item)
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
        obsidian_path=obsidian_path,
        obsidian_error=obsidian_error,
        persist=persist_result,
    )


def _safe_select_route(store: AccountStore, account_id: str) -> dict[str, Any] | None:
    try:
        return select_proactive_route(store, account_id)
    except (AccountStoreError, OSError, ValueError):
        return None


def _resolve_codex_history_dispatch_route(
    store: AccountStore,
    account_id: str,
    *,
    instance_name: str,
    instances_dir: str | Path | None,
    secret_provider: InstanceSecretProvider | None,
) -> tuple[dict[str, Any] | None, str]:
    if instances_dir is not None:
        try:
            safe_instances_dir = _safe_repo_root(Path(instances_dir), operation="instances directory")
            resolution = _resolve_admin_notification_route(
                store,
                account_id,
                instances_dir=safe_instances_dir,
                summary_instance_name=_safe_instance_name(instance_name),
                store_factory=lambda accounts_root, source_instance_name: AccountStore(
                    accounts_root,
                    source_instance_name,
                    secret_provider=secret_provider or ReadOnlySecretToolInstanceSecretProvider(),
                    create_dirs=False,
                ),
            )
        except (AccountStoreError, OSError, ValueError):
            resolution = None
        if resolution is not None:
            if resolution.route is not None:
                return dict(resolution.route), str(resolution.reason or "")
            if resolution.status != "not_local":
                return None, str(resolution.reason or resolution.status or "no_private_route")
    route = _safe_select_route(store, account_id)
    if route is not None:
        return route, ""
    return None, "no_private_route"


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
    attachment = item.get("attachment", {})
    if not isinstance(summary, Mapping):
        summary = {}
    if not isinstance(project, Mapping):
        project = {}
    if not isinstance(version, Mapping):
        version = {}
    repo_name = str(project.get("repo_name") or "project").strip() or "project"
    semver = str(version.get("semver") or "untagged").strip() or "untagged"
    caption = f"Release {repo_name} {semver}"
    if isinstance(attachment, Mapping):
        data_text = str(attachment.get("data_text") or "")
        filename = _safe_filename_component(str(attachment.get("filename") or ""), default="codex-history-artifact", max_length=128)
        content_type = str(attachment.get("content_type") or "").strip() or "application/octet-stream"
        attachment_caption = str(attachment.get("caption") or "").strip()
        if data_text and filename:
            return SendAttachment(
                str(chat_id),
                data_text.encode("utf-8"),
                filename,
                content_type,
                caption=attachment_caption or caption,
                track=False,
            )
    markdown = str(summary.get("markdown") or "").strip()
    if not markdown:
        markdown = f"# {item.get('summary_prefix', 'untagged')} {summary.get('title', 'Codex run summary')}\n"
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


def _write_codex_history_dispatch_markdown(item: Mapping[str, Any]) -> tuple[str, str]:
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
    created_at = str(item.get("created_at") or "").strip()
    date_prefix = _display_timestamp_filename_prefix(created_at)
    repo_name = str(project.get("repo_name") or "project").strip() or "project"
    semver = str(version.get("semver") or "untagged").strip() or "untagged"
    summary_number = item.get("summary_number") or version.get("summary_number") or 1
    base_name = _codex_history_markdown_filename(repo_name, semver, summary_number)
    item_id = _safe_filename_component(str(item.get("id") or "codex-history"), default="codex-history", max_length=48)
    path = obsidian_incoming_path(CODEX_HISTORY_DISPATCH_OBSIDIAN_DIRNAME, f"{date_prefix}_{item_id}_{base_name}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown.rstrip() + "\n", encoding="utf-8")
    except OSError as exc:
        return "", f"{type(exc).__name__}:{exc}"
    return str(path), ""


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
    obsidian_path: str = "",
    obsidian_error: str = "",
    persist: bool = True,
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
    normalized_obsidian_path = str(obsidian_path or "").strip()
    if normalized_obsidian_path:
        row["obsidian_path"] = normalized_obsidian_path
    normalized_obsidian_error = redact_codex_history_text(obsidian_error).strip()
    if normalized_obsidian_error:
        row["obsidian_error"] = normalized_obsidian_error[:240]
    if persist:
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
            replace_item = getattr(store, "replace_codex_history_outbox_item", None)
            if callable(replace_item) and replace_item(INSTANCE_STATE_ACCOUNT_ID, item):
                return
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
        failed_rows = [
            row
            for row in rows
            if isinstance(row, Mapping) and str(row.get("status") or "").strip().casefold() == "failed"
        ]
        if failed_rows and all(_codex_history_dispatch_failure_retryable(row) for row in failed_rows):
            return "queued"
        return "failed"
    if "skipped" in statuses:
        return "skipped"
    return "failed"


def _codex_history_dispatch_failure_retryable(row: Mapping[str, Any]) -> bool:
    reason = str(row.get("reason") or "").strip().casefold()
    return reason.startswith("send_error:")


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
    final_messages: list[dict[str, Any]] = []
    user_messages_by_turn: dict[str, list[str]] = {}
    goals_by_turn: dict[str, str] = {}
    intermediate_by_turn: dict[str, list[dict[str, str]]] = {}
    latest_goal = ""
    latest_auftrag = ""
    try:
        source_mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
    except OSError:
        source_mtime = ""
    try:
        lines = _iter_codex_session_text_lines(path)
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
            role = str(payload.get("role") or "").strip()
            phase = str(payload.get("phase") or "").strip().casefold()
            payload_text = _codex_payload_text(payload)
            if role == "user" and payload_text:
                extracted_goal = _extract_codex_goal(payload_text)
                if extracted_goal:
                    latest_goal = extracted_goal
                    goals_by_turn[turn_id] = extracted_goal
                visible_text = _visible_codex_user_text(payload_text)
                if visible_text:
                    latest_auftrag = visible_text
                    user_messages_by_turn.setdefault(turn_id, []).append(visible_text)
            elif role == "assistant" and payload_text and phase and phase not in {"final", "final_answer"}:
                intermediate_by_turn.setdefault(turn_id, []).append(
                    {
                        "turn_id": turn_id,
                        "phase": phase,
                        "text": _truncate(redact_codex_history_text(payload_text).strip(), 1000),
                    }
                )
            text = _assistant_text_from_codex_payload(payload)
            if text:
                final_text = text
                turn_user_messages = user_messages_by_turn.get(turn_id) or []
                message_goal = goals_by_turn.get(turn_id) or latest_goal
                message_auftrag = turn_user_messages[-1] if turn_user_messages else latest_auftrag
                final_messages.append(
                    {
                        "turn_id": turn_id,
                        "final_text": text,
                        "goal": message_goal,
                        "auftrag": message_auftrag,
                        "current_task": message_auftrag,
                        "intermediate_messages": intermediate_by_turn.get(turn_id, []),
                    }
                )
    except OSError:
        return {
            "session_id": "",
            "turn_id": "",
            "cwd": "",
            "final_text": "",
            "final_messages": [],
            "source_mtime": source_mtime,
            "goal": "",
            "auftrag": "",
        }
    return {
        "session_id": session_id,
        "turn_id": turn_id,
        "cwd": cwd,
        "final_text": final_text,
        "final_messages": final_messages,
        "source_mtime": source_mtime,
        "goal": latest_goal,
        "auftrag": latest_auftrag,
    }


def _iter_codex_session_text_lines(path: Path) -> Iterator[str]:
    stat = path.stat()
    if stat.st_size <= CODEX_SESSION_LARGE_FILE_THRESHOLD_BYTES:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            yield from handle
        return
    head_bytes = max(0, int(CODEX_SESSION_LARGE_FILE_HEAD_BYTES))
    tail_bytes = max(0, int(CODEX_SESSION_LARGE_FILE_TAIL_BYTES))
    with path.open("rb") as handle:
        if head_bytes:
            head = handle.read(head_bytes)
            yield from _complete_text_lines_from_bytes(head, keep_last_partial=False)
        if tail_bytes:
            tail_start = max(head_bytes, stat.st_size - tail_bytes)
            handle.seek(tail_start)
            if tail_start > 0:
                handle.readline()
            tail = handle.read(tail_bytes)
            yield from _complete_text_lines_from_bytes(tail, keep_last_partial=True)


def _complete_text_lines_from_bytes(data: bytes, *, keep_last_partial: bool) -> Iterator[str]:
    if not data:
        return
    lines = data.splitlines(keepends=True)
    if not keep_last_partial and lines and not lines[-1].endswith((b"\n", b"\r")):
        lines = lines[:-1]
    for line in lines:
        yield line.decode("utf-8", errors="replace")


def _assistant_text_from_codex_payload(payload: Mapping[str, Any]) -> str:
    role = str(payload.get("role") or "").strip()
    payload_type = str(payload.get("type") or "").strip()
    if role != "assistant" and payload_type not in {"message", "response_item"}:
        return ""
    if role and role != "assistant":
        return ""
    phase = str(payload.get("phase") or "").strip().casefold()
    if role == "assistant" and phase and phase not in {"final", "final_answer"}:
        return ""
    return _codex_payload_text(payload).strip()


def _codex_payload_text(payload: Mapping[str, Any]) -> str:
    content = payload.get("content")
    return _text_from_codex_content(content).strip()


def _extract_codex_goal(text: object) -> str:
    raw = str(text or "")
    match = re.search(
        r"<codex_internal_context\b[^>]*\bsource=[\"']goal[\"'][^>]*>(?P<body>.*?)</codex_internal_context>",
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return ""
    body = match.group("body")
    objective_match = re.search(r"<objective>(?P<objective>.*?)</objective>", body, flags=re.IGNORECASE | re.DOTALL)
    goal = objective_match.group("objective") if objective_match else body
    return _truncate(redact_codex_history_text(goal).strip(), 500)


def _visible_codex_user_text(text: object) -> str:
    raw = str(text or "")
    raw = re.sub(
        r"<codex_internal_context\b[^>]*>.*?</codex_internal_context>",
        " ",
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )
    raw = re.sub(r"<environment_context>.*?</environment_context>", " ", raw, flags=re.IGNORECASE | re.DOTALL)
    raw = re.sub(r"<turn_aborted>.*?</turn_aborted>", " ", raw, flags=re.IGNORECASE | re.DOTALL)
    raw = re.sub(r"\s+", " ", raw).strip()
    return _truncate(redact_codex_history_text(raw).strip(), 500)


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
    return _find_codex_history_by_dedupe_key_in_rows(store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID), dedupe_key)


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
        root = _safe_repo_root(Path(root_value), operation="session root", allow_hidden_segments=True)
        if root.is_file() and root.suffix == ".jsonl":
            files.append(root)
            continue
        if not root.is_dir():
            continue
        files.extend(path for path in root.rglob("*.jsonl") if path.is_file() and _is_codex_session_log_path(path))
    files = sorted(set(files), key=_codex_session_file_import_sort_key)
    if limit > 0:
        files = files[:limit]
    files = sorted(files, key=_codex_session_file_processing_sort_key)
    return tuple(files)


def _explicit_codex_session_file_roots(roots: Sequence[str | Path]) -> set[Path]:
    files: set[Path] = set()
    for root_value in roots:
        root = _safe_repo_root(Path(root_value), operation="session root", allow_hidden_segments=True)
        if root.is_file() and root.suffix == ".jsonl":
            files.add(root)
    return files


def _is_codex_session_log_path(path: Path) -> bool:
    return "sessions" in path.parts


def _codex_session_file_import_sort_key(path: Path) -> tuple[int, str]:
    try:
        stat = path.stat()
    except OSError:
        return (0, str(path))
    return (-int(stat.st_mtime_ns), str(path))


def _codex_session_file_processing_sort_key(path: Path) -> tuple[int, str]:
    try:
        stat = path.stat()
    except OSError:
        return (0, str(path))
    return (int(stat.st_mtime_ns), str(path))


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
        watchdog_result = _wait_for_watchdog_codex_session_change(roots, timeout_seconds=poll_interval_seconds)
        if watchdog_result is True:
            return
        if watchdog_result is False and normalized_event_mode == "watchdog":
            return
    sleep(float(poll_interval_seconds))


def _wait_for_watchdog_codex_session_change(roots: Sequence[str | Path], *, timeout_seconds: float) -> bool | None:
    try:
        from watchdog.events import FileSystemEventHandler  # type: ignore[import-not-found]
        from watchdog.observers import Observer  # type: ignore[import-not-found]
    except ImportError:
        return None

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
            root = _safe_repo_root(Path(root_value), operation="sessions root", allow_hidden_segments=True)
        except ValueError:
            continue
        watch_root = root.parent if root.is_file() else root
        if not watch_root.exists() or not watch_root.is_dir():
            continue
        observer.schedule(handler, str(watch_root), recursive=True)
        scheduled = True
    if not scheduled:
        return None
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

    rewrite_times_parser = subparsers.add_parser("rewrite-times")
    rewrite_times_parser.add_argument("--instances-dir", default=DEFAULT_INSTANCES_DIR)
    rewrite_times_parser.add_argument("--instances", default="")
    rewrite_times_parser.add_argument("--instance", default="")
    rewrite_times_parser.add_argument("--repo", default="")
    rewrite_times_parser.add_argument("--apply", action="store_true", help="Rewrite persisted rows instead of only reporting changes.")
    rewrite_times_parser.add_argument(
        "--include-dispatch-files",
        action="store_true",
        help="Also rewrite linked Codex_History_Dispatches Markdown files and rename their timestamp prefix.",
    )
    rewrite_times_parser.add_argument("--format", choices=("text", "json"), default="text")
    rewrite_times_parser.add_argument("--output", default="")

    bibliothekar_export_parser = subparsers.add_parser("bibliothekar-export")
    bibliothekar_export_parser.add_argument("--instances-dir", default=DEFAULT_INSTANCES_DIR)
    bibliothekar_export_parser.add_argument("--instances", default="")
    bibliothekar_export_parser.add_argument("--instance", default="")
    bibliothekar_export_parser.add_argument("--repo", default="")
    bibliothekar_export_parser.add_argument("--limit", type=int, default=0)
    bibliothekar_export_parser.add_argument("--format", choices=("text", "json"), default="text")
    bibliothekar_export_parser.add_argument("--no-overwrite", action="store_true")

    categorize_parser = subparsers.add_parser("categorize")
    categorize_parser.add_argument("--instances-dir", default=DEFAULT_INSTANCES_DIR)
    categorize_parser.add_argument("--instances", default="")
    categorize_parser.add_argument("--instance", default="")
    categorize_parser.add_argument("--repo", default="")
    categorize_parser.add_argument("--limit", type=int, default=0)
    categorize_parser.add_argument("--profile", default=CODEX_HISTORY_DEFAULT_LOCAL_CATEGORY_PROFILE)
    categorize_parser.add_argument("--dry-run", action="store_true")
    categorize_parser.add_argument("--format", choices=("text", "json"), default="text")

    graph_export_parser = subparsers.add_parser("graph-export")
    graph_export_parser.add_argument("--instances-dir", default=DEFAULT_INSTANCES_DIR)
    graph_export_parser.add_argument("--instances", default="")
    graph_export_parser.add_argument("--instance", default="")
    graph_export_parser.add_argument("--repo", default="")
    graph_export_parser.add_argument("--limit", type=int, default=0)
    graph_export_parser.add_argument("--format", choices=("text", "json"), default="text")
    graph_export_parser.add_argument("--no-overwrite", action="store_true")
    graph_export_parser.add_argument("--svg", action="store_true", help="Also export a dependency-free SVG graph image.")
    graph_export_parser.add_argument(
        "--svg-engine",
        choices=sorted(CODEX_HISTORY_GRAPH_SVG_ENGINES),
        default="builtin",
        help="SVG renderer: builtin is dependency-free, auto uses mmdc when installed, mmdc requires Mermaid CLI.",
    )
    graph_export_parser.add_argument("--queue-svg", action="store_true", help="Queue the SVG graph as an admin-only dispatch attachment.")

    strategic_analysis_parser = subparsers.add_parser("strategic-analysis")
    strategic_analysis_parser.add_argument("--instances-dir", default=DEFAULT_INSTANCES_DIR)
    strategic_analysis_parser.add_argument("--instances", default="")
    strategic_analysis_parser.add_argument("--instance", default="")
    strategic_analysis_parser.add_argument("--repo", default="")
    strategic_analysis_parser.add_argument("--limit", type=int, default=20)
    strategic_analysis_parser.add_argument("--profile", default=CODEX_HISTORY_DEFAULT_STRATEGY_PROFILE)
    strategic_analysis_parser.add_argument("--allow-remote", action="store_true")
    strategic_analysis_parser.add_argument("--force", action="store_true", help="Generate a new strategy report even when the source set is unchanged.")
    strategic_analysis_parser.add_argument("--dry-run", action="store_true")
    strategic_analysis_parser.add_argument("--format", choices=("text", "json"), default="text")

    index_parser = subparsers.add_parser("index")
    index_parser.add_argument("--instances-dir", default=DEFAULT_INSTANCES_DIR)
    index_parser.add_argument("--instances", default="")
    index_parser.add_argument("--instance", default="")
    index_parser.add_argument("--repo", default="")
    index_parser.add_argument("--limit", type=int, default=0)
    index_parser.add_argument("--format", choices=("text", "json"), default="text")
    index_parser.add_argument("--no-overwrite", action="store_true")
    index_parser.add_argument("--qdrant", action="store_true")
    index_parser.add_argument("--qdrant-url", default="")
    index_parser.add_argument("--qdrant-dry-run", action="store_true")
    index_parser.add_argument("--qdrant-ensure", action="store_true")
    index_parser.add_argument("--graph", action="store_true")
    index_parser.add_argument("--graph-svg", action="store_true")
    index_parser.add_argument("--graph-svg-engine", choices=sorted(CODEX_HISTORY_GRAPH_SVG_ENGINES), default="builtin")
    index_parser.add_argument("--graph-queue-svg", action="store_true")
    index_parser.add_argument("--categorize", action="store_true")
    index_parser.add_argument("--categorize-profile", default=CODEX_HISTORY_DEFAULT_LOCAL_CATEGORY_PROFILE)
    index_parser.add_argument("--categorize-dry-run", action="store_true")
    index_parser.add_argument("--strategic-analysis", action="store_true")
    index_parser.add_argument("--strategic-analysis-profile", default=CODEX_HISTORY_DEFAULT_STRATEGY_PROFILE)
    index_parser.add_argument("--strategic-analysis-allow-remote", action="store_true")
    index_parser.add_argument("--strategic-analysis-force", action="store_true")
    index_parser.add_argument("--strategic-analysis-dry-run", action="store_true")

    dispatch_parser = subparsers.add_parser("dispatch")
    dispatch_parser.add_argument("--instances-dir", default=DEFAULT_INSTANCES_DIR)
    dispatch_parser.add_argument("--instances", default="")
    dispatch_parser.add_argument("--instance", default="")
    dispatch_parser.add_argument(
        "--limit",
        type=int,
        default=CODEX_HISTORY_DEFAULT_DISPATCH_LIMIT,
        help="Limit dispatch to latest N queued summaries; 0 means all.",
    )
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
    watch_parser.add_argument("--poll-interval", type=float, default=300.0)
    watch_parser.add_argument("--event-mode", choices=("poll", "snapshot", "watchdog", "auto"), default="poll")
    watch_parser.add_argument("--follow", action="store_true", help="Run until the process is stopped instead of exiting after max iterations.")
    watch_parser.add_argument("--format", choices=("text", "json"), default="text")
    watch_parser.add_argument("--once", action="store_true")
    watch_parser.add_argument("--post-index", action="store_true", help="After each scan, export Codex-History docs to the admin-only Bibliothekar folder.")
    watch_parser.add_argument("--post-index-repo", default="", help="Repo filter for post-index export/rebuild.")
    watch_parser.add_argument("--post-index-limit", type=int, default=0, help="Limit post-index to latest N summaries after repo filtering.")
    watch_parser.add_argument("--post-index-qdrant", action="store_true", help="Also rebuild the admin-only Codex-History Qdrant collection after scans.")
    watch_parser.add_argument("--post-index-qdrant-url", default="", help="Override Qdrant URL for post-index rebuild.")
    watch_parser.add_argument("--post-index-qdrant-dry-run", action="store_true", help="Count post-index Qdrant chunks without writing Qdrant.")
    watch_parser.add_argument("--post-index-qdrant-ensure", action="store_true", help="Ensure Qdrant collections before post-index rebuild.")
    watch_parser.add_argument("--dispatch", action="store_true", help="After each scan, dispatch queued Codex-History summaries to status admins.")
    watch_parser.add_argument(
        "--dispatch-limit",
        type=int,
        default=CODEX_HISTORY_DEFAULT_DISPATCH_LIMIT,
        help="Limit post-scan dispatch to latest N queued summaries; 0 means all.",
    )
    watch_parser.add_argument("--dispatch-dry-run", action="store_true", help="Resolve post-scan dispatch targets without sending messages.")

    args = parser.parse_args(list(argv) if argv is not None else None)
    load_project_dotenv_for_instances(getattr(args, "instances_dir", DEFAULT_INSTANCES_DIR))
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
    if args.command == "rewrite-times":
        try:
            selected_instances = parse_csv(getattr(args, "instances", None))
            if args.instance:
                selected_instances = tuple(dict.fromkeys((*selected_instances, str(args.instance).strip())))
            payload = rewrite_codex_history_display_times_for_instances(
                instances_dir=args.instances_dir,
                instances=selected_instances,
                repo=args.repo,
                dry_run=not bool(args.apply),
                include_dispatch_files=bool(args.include_dispatch_files),
                provider=provider,
            )
            output = (
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
                if args.format == "json"
                else _render_rewrite_times_report(payload)
            )
            _write_or_print(output, args.output)
            return 0 if payload["ok"] else 1
        except (OSError, ValueError) as exc:
            print(f"rewrite-times failed: {exc}", file=sys.stderr)
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
    if args.command == "categorize":
        try:
            selected_instances = parse_csv(getattr(args, "instances", None))
            if args.instance:
                selected_instances = tuple(dict.fromkeys((*selected_instances, str(args.instance).strip())))
            instances_dir = _safe_repo_root(Path(args.instances_dir), operation="instances directory")
            _ensure_explicit_instances_exist(instances_dir, selected_instances)
            reports: list[dict[str, Any]] = []
            for instance_name in discover_instances(instances_dir, selected_instances):
                store = _store_for_instance(instances_dir, instance_name, provider)
                report = categorize_codex_history_outbox(
                    store,
                    repo=args.repo,
                    limit=int(args.limit or 0),
                    profile=args.profile,
                    dry_run=bool(args.dry_run),
                )
                reports.append({"instance": instance_name, **report})
            payload = {
                "ok": not any(not report.get("ok") for report in reports),
                "instances_dir": str(instances_dir),
                "instances": reports,
                "totals": {
                    "scanned": sum(int(report.get("scanned") or 0) for report in reports),
                    "categorized": sum(int(report.get("categorized") or 0) for report in reports),
                    "errors": sum(len(report.get("errors") or []) for report in reports),
                },
            }
            output = (
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
                if args.format == "json"
                else _render_categorize_report(payload)
            )
            print(output, end="")
            return 0 if payload["ok"] else 1
        except (OSError, ValueError) as exc:
            print(f"categorize failed: {exc}", file=sys.stderr)
            return 2
    if args.command == "graph-export":
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
                    export_codex_history_graph_doc(
                        store,
                        instance_dir=instances_dir / instance_name,
                        instance_name=instance_name,
                        repo=args.repo,
                        limit=int(args.limit or 0),
                        overwrite=not bool(args.no_overwrite),
                        svg=bool(args.svg),
                        queue_svg=bool(args.queue_svg),
                        svg_engine=args.svg_engine,
                    )
                )
            payload = {
                "ok": not any(not report.get("ok") for report in reports),
                "instances_dir": str(instances_dir),
                "instances": reports,
                "totals": {
                    "exported": sum(int(report.get("exported") or 0) for report in reports),
                    "skipped": sum(int(report.get("skipped") or 0) for report in reports),
                    "svg_exported": sum(int(report.get("svg_exported") or 0) for report in reports),
                    "svg_skipped": sum(int(report.get("svg_skipped") or 0) for report in reports),
                    "queued": sum(1 for report in reports if report.get("queued_item")),
                    "repos": sum(int(report.get("repo_count") or 0) for report in reports),
                    "items": sum(int(report.get("item_count") or 0) for report in reports),
                },
            }
            output = (
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
                if args.format == "json"
                else _render_graph_export_report(payload)
            )
            print(output, end="")
            return 0 if payload["ok"] else 1
        except (OSError, ValueError) as exc:
            print(f"graph-export failed: {exc}", file=sys.stderr)
            return 2
    if args.command == "strategic-analysis":
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
                    generate_codex_history_strategic_analysis(
                        store,
                        instance_name=instance_name,
                        repo=args.repo,
                        limit=int(args.limit or 0),
                        profile=args.profile,
                        allow_remote=bool(args.allow_remote),
                        force=bool(args.force),
                        dry_run=bool(args.dry_run),
                    )
                )
            payload = {
                "ok": not any(not report.get("ok") for report in reports),
                "instances_dir": str(instances_dir),
                "instances": reports,
                "totals": {
                    "generated": sum(1 for report in reports if report.get("item") and not report.get("cache_hit")),
                    "analyzed": sum(int(report.get("analyzed") or 0) for report in reports),
                    "skipped": sum(1 for report in reports if str(report.get("status") or "") == "skipped"),
                    "cached": sum(1 for report in reports if report.get("cache_hit")),
                },
            }
            output = (
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
                if args.format == "json"
                else _render_strategic_analysis_report(payload)
            )
            print(output, end="")
            return 0 if payload["ok"] else 1
        except (OSError, ValueError) as exc:
            print(f"strategic-analysis failed: {exc}", file=sys.stderr)
            return 2
    if args.command == "index":
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
                    run_codex_history_index(
                        store,
                        instance_dir=instances_dir / instance_name,
                        instance_name=instance_name,
                        repo=args.repo,
                        limit=int(args.limit or 0),
                        overwrite=not bool(args.no_overwrite),
                        qdrant=bool(args.qdrant),
                        qdrant_url=args.qdrant_url,
                        qdrant_dry_run=bool(args.qdrant_dry_run),
                        qdrant_ensure=bool(args.qdrant_ensure),
                        graph=bool(args.graph),
                        graph_svg=bool(args.graph_svg),
                        graph_queue_svg=bool(args.graph_queue_svg),
                        graph_svg_engine=args.graph_svg_engine,
                        categorize=bool(args.categorize),
                        categorize_profile=args.categorize_profile,
                        categorize_dry_run=bool(args.categorize_dry_run),
                        strategic_analysis=bool(args.strategic_analysis),
                        strategic_analysis_profile=args.strategic_analysis_profile,
                        strategic_analysis_allow_remote=bool(args.strategic_analysis_allow_remote),
                        strategic_analysis_force=bool(args.strategic_analysis_force),
                        strategic_analysis_dry_run=bool(args.strategic_analysis_dry_run),
                        secret_provider=provider or ReadOnlySecretToolInstanceSecretProvider(),
                    )
                )
            payload = {
                "ok": not any(not report.get("ok") for report in reports),
                "instances_dir": str(instances_dir),
                "instances": reports,
                "totals": _index_totals(reports),
            }
            output = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n" if args.format == "json" else _render_index_report(payload)
            print(output, end="")
            return 0 if payload["ok"] else 1
        except (OSError, ValueError) as exc:
            print(f"index failed: {exc}", file=sys.stderr)
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
                            instances_dir=instances_dir,
                            secret_provider=provider,
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
            safe_roots = [
                _safe_repo_root(Path(root), operation="sessions root", allow_hidden_segments=True)
                for root in tuple(args.sessions_root or ()) or default_codex_session_roots()
            ]
            instance_reports: list[dict[str, Any]] = []
            for instance_name in selected:
                store = _store_for_instance(instances_dir, instance_name, provider)
                import_report = import_codex_session_roots(store, safe_roots, limit=int(args.limit or 0))
                instance_report = {"instance": instance_name, **import_report}
                post_index = _watch_post_index_report(store, instances_dir, instance_name, args, provider)
                if post_index:
                    instance_report["post_index"] = post_index
                dispatch_report = _watch_dispatch_report(store, instances_dir, instance_name, args)
                if dispatch_report:
                    instance_report["dispatch"] = dispatch_report
                instance_reports.append(instance_report)
            payload = {
                "ok": _watch_payload_ok(instance_reports),
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
            safe_roots = [
                _safe_repo_root(Path(root), operation="sessions root", allow_hidden_segments=True)
                for root in tuple(args.sessions_root or ()) or default_codex_session_roots()
            ]
            max_iterations = int(args.max_iterations or 0)
            if max_iterations < 1:
                max_iterations = 1
            poll_interval_seconds = float(args.poll_interval or 0.0)
            if poll_interval_seconds < 0.0:
                poll_interval_seconds = 0.0
            instance_reports: list[dict[str, Any]] = []
            selected = discover_instances(instances_dir, selected_instances)
            sender_factory = None if args.dispatch_dry_run or not args.dispatch else _runtime_sender_factory(instances_dir)
            stores = {instance_name: _store_for_instance(instances_dir, instance_name, provider) for instance_name in selected}
            post_index_reports_by_instance: dict[str, list[dict[str, Any]]] = {}
            dispatch_reports_by_instance: dict[str, list[dict[str, Any]]] = {}
            post_scan_callbacks: dict[str, Callable[[Mapping[str, Any]], None]] = {}
            post_idle_callbacks: dict[str, Callable[[Mapping[str, Any]], None]] = {}
            for instance_name, store in stores.items():
                post_index_reports: list[dict[str, Any]] = []
                dispatch_reports: list[dict[str, Any]] = []
                post_index_reports_by_instance[instance_name] = post_index_reports
                dispatch_reports_by_instance[instance_name] = dispatch_reports
                callback = _watch_post_index_callback(
                    store,
                    instances_dir,
                    instance_name,
                    args,
                    provider,
                    post_index_reports,
                    dispatch_reports,
                    sender_factory=sender_factory,
                )
                if callback is not None:
                    post_scan_callbacks[instance_name] = callback
                idle_callback = _watch_dispatch_idle_callback(
                    store,
                    instances_dir,
                    instance_name,
                    args,
                    dispatch_reports,
                    sender_factory=sender_factory,
                )
                if idle_callback is not None:
                    post_idle_callbacks[instance_name] = idle_callback

            def _post_scan(instance_name: str, scan_report: Mapping[str, Any]) -> None:
                _emit_follow_scan_report(instance_name, scan_report, args)
                callback = post_scan_callbacks.get(instance_name)
                if callback is not None:
                    callback(scan_report)

            def _post_idle(instance_name: str, idle_report: Mapping[str, Any]) -> None:
                callback = post_idle_callbacks.get(instance_name)
                if callback is not None:
                    callback(idle_report)

            raw_instance_reports = watch_codex_session_roots_for_instances(
                stores,
                safe_roots,
                poll_interval_seconds=poll_interval_seconds,
                max_iterations=max_iterations,
                follow=bool(args.follow),
                event_mode=str(args.event_mode or "poll"),
                limit=int(args.limit or 0),
                post_scan=_post_scan,
                post_idle=_post_idle if post_idle_callbacks else None,
            )
            instance_reports = []
            for instance_report in raw_instance_reports:
                instance_name = str(instance_report.get("instance") or "")
                post_index_reports = post_index_reports_by_instance.get(instance_name, [])
                dispatch_reports = dispatch_reports_by_instance.get(instance_name, [])
                if post_index_reports:
                    instance_report["post_index"] = post_index_reports[-1]
                    instance_report["post_index_runs"] = post_index_reports
                if dispatch_reports:
                    instance_report["dispatch"] = dispatch_reports[-1]
                    instance_report["dispatch_runs"] = dispatch_reports
                instance_reports.append(instance_report)
            payload = {
                "ok": _watch_payload_ok(instance_reports),
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
        try:
            _safe_output_path(output_path).write_text(output, encoding="utf-8")
        except OSError as exc:
            raise OSError(f"unable to write output: {exc}") from exc
    else:
        print(output, end="")


def _ensure_explicit_instances_exist(instances_dir: Path, requested_instances: Sequence[str]) -> None:
    if not requested_instances:
        return
    normalized_instances = tuple(_safe_instance_name(str(instance_name).strip()) for instance_name in requested_instances if str(instance_name).strip())
    if not normalized_instances:
        return
    safe_instances_dir = _safe_repo_root(instances_dir, operation="instances directory")
    available = {
        path.name
        for path in safe_instances_dir.iterdir()
        if path.is_dir() and (path / BOT_INSTRUCTION_FILENAME).exists()
    }
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


def _watch_post_index_callback(
    store: AccountStore,
    instances_dir: Path,
    instance_name: str,
    args: argparse.Namespace,
    provider: InstanceSecretProvider | None,
    reports: list[dict[str, Any]],
    dispatch_reports: list[dict[str, Any]],
    *,
    sender_factory: Any | None = None,
) -> Callable[[Mapping[str, Any]], None] | None:
    qdrant = bool(getattr(args, "post_index_qdrant", False))
    qdrant_ensure = bool(getattr(args, "post_index_qdrant_ensure", False))
    dispatch = bool(getattr(args, "dispatch", False))
    if not (bool(getattr(args, "post_index", False)) or qdrant or qdrant_ensure or dispatch):
        return None

    def _callback(_scan_report: Mapping[str, Any]) -> None:
        post_index = _watch_post_index_report(store, instances_dir, instance_name, args, provider)
        if post_index:
            reports.append(post_index)
        dispatch_report = _watch_dispatch_report(
            store,
            instances_dir,
            instance_name,
            args,
            sender_factory=sender_factory,
        )
        if dispatch_report:
            dispatch_reports.append(dispatch_report)
            _emit_follow_dispatch_report(dispatch_report, args)

    return _callback


def _watch_dispatch_idle_callback(
    store: AccountStore,
    instances_dir: Path,
    instance_name: str,
    args: argparse.Namespace,
    dispatch_reports: list[dict[str, Any]],
    *,
    sender_factory: Any | None = None,
) -> Callable[[Mapping[str, Any]], None] | None:
    if not bool(getattr(args, "dispatch", False)):
        return None

    def _callback(_idle_report: Mapping[str, Any]) -> None:
        dispatch_report = _watch_dispatch_report(
            store,
            instances_dir,
            instance_name,
            args,
            sender_factory=sender_factory,
        )
        if dispatch_report:
            dispatch_reports.append(dispatch_report)
            _emit_follow_dispatch_report(dispatch_report, args)

    return _callback


def _emit_follow_scan_report(instance_name: str, scan_report: Mapping[str, Any], args: argparse.Namespace) -> None:
    if not bool(getattr(args, "follow", False)):
        return
    if str(getattr(args, "format", "text") or "text") != "text":
        return
    lines = ["TeeBotus Codex-History Scan", "", f"Instance: {instance_name}"]
    status_counts = scan_report.get("status_counts", {})
    if isinstance(status_counts, Mapping):
        lines.append("  statuses: " + ", ".join(f"{key}={value}" for key, value in sorted(status_counts.items())))
    for item in _watch_detail_items(scan_report.get("items", [])):
        if not isinstance(item, Mapping):
            continue
        lines.append(_watch_import_detail_line(item))
    print("\n".join(lines) + "\n", flush=True)


def _emit_follow_dispatch_report(dispatch_report: Mapping[str, Any], args: argparse.Namespace) -> None:
    if not bool(getattr(args, "follow", False)):
        return
    if str(getattr(args, "format", "text") or "text") != "text":
        return
    print(_render_dispatch_report(dispatch_report), end="", flush=True)


def _watch_dispatch_report(
    store: AccountStore,
    instances_dir: Path,
    instance_name: str,
    args: argparse.Namespace,
    *,
    sender_factory: Any | None = None,
) -> dict[str, Any]:
    if not bool(getattr(args, "dispatch", False)):
        return {}
    dry_run = bool(getattr(args, "dispatch_dry_run", False))
    if dry_run:
        senders: dict[str, Any] = {}
    else:
        factory = sender_factory or _runtime_sender_factory(instances_dir)
        senders = dict(factory(instance_name, store))
    report = asyncio.run(
        dispatch_codex_history_outbox(
            store,
            instance_name=instance_name,
            senders=senders,
            instances_dir=instances_dir,
            secret_provider=ReadOnlySecretToolInstanceSecretProvider(),
            dry_run=dry_run,
            limit=int(getattr(args, "dispatch_limit", 0) or 0),
        )
    )
    return {
        "ok": bool(report.get("ok", True)),
        "dry_run": dry_run,
        "instances_dir": str(instances_dir),
        "instances": [report],
    }


def _watch_post_index_report(
    store: AccountStore,
    instances_dir: Path,
    instance_name: str,
    args: argparse.Namespace,
    provider: InstanceSecretProvider | None,
) -> dict[str, Any]:
    qdrant = bool(getattr(args, "post_index_qdrant", False))
    qdrant_ensure = bool(getattr(args, "post_index_qdrant_ensure", False))
    if not (bool(getattr(args, "post_index", False)) or qdrant or qdrant_ensure):
        return {}
    return run_codex_history_index(
        store,
        instance_dir=instances_dir / instance_name,
        instance_name=instance_name,
        repo=str(getattr(args, "post_index_repo", "") or ""),
        limit=int(getattr(args, "post_index_limit", 0) or 0),
        qdrant=qdrant,
        qdrant_url=str(getattr(args, "post_index_qdrant_url", "") or ""),
        qdrant_dry_run=bool(getattr(args, "post_index_qdrant_dry_run", False)),
        qdrant_ensure=qdrant_ensure,
        secret_provider=provider or ReadOnlySecretToolInstanceSecretProvider(),
    )


def _watch_payload_ok(instance_reports: Sequence[Mapping[str, Any]]) -> bool:
    for report in instance_reports:
        if not isinstance(report, Mapping):
            continue
        if not bool(report.get("ok", True)):
            return False
        post_index = report.get("post_index")
        if isinstance(post_index, Mapping) and not bool(post_index.get("ok", True)):
            return False
        # Dispatch failures are persisted per item; retryable channel send
        # errors are requeued by dispatch status handling. The watcher itself
        # should still exit successfully so systemd timers do not enter a
        # failed state on channel errors.
    return True


def _index_totals(reports: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    totals = {
        "categorized": 0,
        "category_errors": 0,
        "exported": 0,
        "skipped": 0,
        "graph_files": 0,
        "graph_svg_files": 0,
        "graph_queued": 0,
        "graph_items": 0,
        "strategy_reports": 0,
        "strategy_cached": 0,
        "strategy_analyzed": 0,
        "qdrant_points": 0,
        "qdrant_errors": 0,
    }
    for report in reports:
        if not isinstance(report, Mapping):
            continue
        category_report = report.get("categorize", {})
        if isinstance(category_report, Mapping):
            totals["categorized"] += int(category_report.get("categorized") or 0)
            totals["category_errors"] += len(category_report.get("errors") or [])
        export = report.get("export", {})
        if isinstance(export, Mapping):
            totals["exported"] += int(export.get("exported") or 0)
            totals["skipped"] += int(export.get("skipped") or 0)
        graph = report.get("graph", {})
        if isinstance(graph, Mapping):
            totals["graph_files"] += int(graph.get("exported") or 0)
            totals["graph_svg_files"] += int(graph.get("svg_exported") or 0)
            if graph.get("queued_item"):
                totals["graph_queued"] += 1
            totals["graph_items"] += int(graph.get("item_count") or 0)
        strategy = report.get("strategic_analysis", {})
        if isinstance(strategy, Mapping):
            if strategy.get("cache_hit"):
                totals["strategy_cached"] += 1
            elif strategy.get("item"):
                totals["strategy_reports"] += 1
            totals["strategy_analyzed"] += int(strategy.get("analyzed") or 0)
        for result in report.get("qdrant", []) or []:
            if not isinstance(result, Mapping):
                continue
            totals["qdrant_points"] += int(result.get("point_count") or 0)
            if str(result.get("status") or "").casefold() == "error":
                totals["qdrant_errors"] += 1
    return totals


def _jsonable_result(value: object) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    return {"value": str(value)}


def _render_rewrite_times_report(payload: Mapping[str, Any]) -> str:
    lines = [
        "TeeBotus Codex-History Time Rewrite",
        "",
        f"dry_run: {payload.get('dry_run', True)}",
        f"include_dispatch_files: {payload.get('include_dispatch_files', False)}",
    ]
    totals = payload.get("totals", {})
    if isinstance(totals, Mapping):
        lines.extend(
            [
                f"scanned_items: {totals.get('scanned_items', 0)}",
                f"changed_items: {totals.get('changed_items', 0)}",
                f"timestamp_rewrites: {totals.get('timestamp_rewrites', 0)}",
                f"dispatch_files_changed: {totals.get('dispatch_files_changed', 0)}",
                f"dispatch_files_renamed: {totals.get('dispatch_files_renamed', 0)}",
                f"errors: {totals.get('errors', 0)}",
            ]
        )
    for instance in payload.get("instances", []):
        if not isinstance(instance, Mapping):
            continue
        lines.append("")
        lines.append(f"Instance: {instance.get('instance', '')}")
        if not bool(instance.get("ok", True)):
            lines.append(f"  error: {instance.get('error', '')}")
            continue
        lines.append(f"  scanned_items: {instance.get('scanned_items', 0)}")
        lines.append(f"  changed_items: {instance.get('changed_items', 0)}")
        lines.append(f"  timestamp_rewrites: {instance.get('timestamp_rewrites', 0)}")
        dispatch_files = instance.get("dispatch_files", {})
        if isinstance(dispatch_files, Mapping):
            lines.append(
                "  dispatch_files: "
                f"scanned={dispatch_files.get('scanned', 0)} "
                f"changed={dispatch_files.get('changed', 0)} "
                f"renamed={dispatch_files.get('renamed', 0)} "
                f"missing={dispatch_files.get('missing', 0)} "
                f"unsafe={dispatch_files.get('unsafe', 0)} "
                f"errors={len(dispatch_files.get('errors', []) or [])}"
            )
    return "\n".join(lines) + "\n"


def _render_dispatch_report(payload: Mapping[str, Any]) -> str:
    lines = ["TeeBotus Codex-History Dispatch", "", f"dry_run: {payload.get('dry_run', False)}"]
    for instance in payload.get("instances", []):
        if not isinstance(instance, Mapping):
            continue
        lines.append("")
        lines.append(f"Instance: {instance.get('instance', '')}")
        status_counts = instance.get("status_counts", {})
        lines.append("  statuses: " + _format_status_counts(status_counts))
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


def _render_categorize_report(payload: Mapping[str, Any]) -> str:
    lines = ["TeeBotus Codex-History Categorize", ""]
    totals = payload.get("totals", {})
    if isinstance(totals, Mapping):
        lines.append(f"scanned: {totals.get('scanned', 0)}")
        lines.append(f"categorized: {totals.get('categorized', 0)}")
        lines.append(f"errors: {totals.get('errors', 0)}")
    for instance in payload.get("instances", []) or []:
        if not isinstance(instance, Mapping):
            continue
        lines.append("")
        lines.append(f"Instance: {instance.get('instance', '')}")
        lines.append(f"  profile: {instance.get('profile', '')}")
        lines.append(f"  dry_run: {bool(instance.get('dry_run', False))}")
        lines.append(f"  scanned: {instance.get('scanned', 0)}")
        lines.append(f"  categorized: {instance.get('categorized', 0)}")
        for item in instance.get("items", []) or []:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "  item: "
                f"{item.get('summary_prefix', '')} "
                f"{item.get('item_id', '')} "
                f"categories={','.join(item.get('categories', []) or [])}"
            )
        for item in instance.get("errors", []) or []:
            if isinstance(item, Mapping):
                lines.append(f"  error: {item.get('summary_prefix', '')} {item.get('error', '')}")
    return "\n".join(lines) + "\n"


def _render_graph_export_report(payload: Mapping[str, Any]) -> str:
    lines = ["TeeBotus Codex-History Graph Export", ""]
    totals = payload.get("totals", {})
    if isinstance(totals, Mapping):
        lines.append(f"exported: {totals.get('exported', 0)}")
        lines.append(f"skipped: {totals.get('skipped', 0)}")
        lines.append(f"svg_exported: {totals.get('svg_exported', 0)}")
        lines.append(f"svg_skipped: {totals.get('svg_skipped', 0)}")
        lines.append(f"queued: {totals.get('queued', 0)}")
        lines.append(f"repos: {totals.get('repos', 0)}")
        lines.append(f"items: {totals.get('items', 0)}")
    for instance in payload.get("instances", []) or []:
        if not isinstance(instance, Mapping):
            continue
        lines.append("")
        lines.append(f"Instance: {instance.get('instance', '')}")
        lines.append(f"  path: {instance.get('path', '')}")
        if instance.get("svg_path"):
            lines.append(f"  svg_path: {instance.get('svg_path', '')}")
        if instance.get("svg_engine"):
            lines.append(f"  svg_engine: {instance.get('svg_engine', '')}")
        if instance.get("svg_warning"):
            lines.append(f"  svg_warning: {instance.get('svg_warning', '')}")
        lines.append(f"  exported: {instance.get('exported', 0)}")
        lines.append(f"  svg_exported: {instance.get('svg_exported', 0)}")
        queued_item = instance.get("queued_item", {})
        if isinstance(queued_item, Mapping) and queued_item:
            lines.append(f"  queued: {queued_item.get('summary_prefix', '')} {queued_item.get('id', '')}")
        lines.append(f"  skipped: {instance.get('skipped', 0)}")
        lines.append(f"  repos: {instance.get('repo_count', 0)}")
        lines.append(f"  items: {instance.get('item_count', 0)}")
    return "\n".join(lines) + "\n"


def _render_strategic_analysis_report(payload: Mapping[str, Any]) -> str:
    lines = ["TeeBotus Codex-History Strategic Analysis", ""]
    totals = payload.get("totals", {})
    if isinstance(totals, Mapping):
        lines.append(f"generated: {totals.get('generated', 0)}")
        lines.append(f"analyzed: {totals.get('analyzed', 0)}")
        lines.append(f"skipped: {totals.get('skipped', 0)}")
        lines.append(f"cached: {totals.get('cached', 0)}")
    for instance in payload.get("instances", []) or []:
        if not isinstance(instance, Mapping):
            continue
        item = instance.get("item", {})
        if not isinstance(item, Mapping):
            item = {}
        lines.append("")
        lines.append(f"Instance: {instance.get('instance', '')}")
        lines.append(f"  status: {instance.get('status', '')}")
        lines.append(f"  dry_run: {bool(instance.get('dry_run', False))}")
        lines.append(f"  cache_hit: {bool(instance.get('cache_hit', False))}")
        if instance.get("reason"):
            lines.append(f"  reason: {instance.get('reason', '')}")
        lines.append(f"  analyzed: {instance.get('analyzed', 0)}")
        if item:
            lines.append(f"  item: {item.get('summary_prefix', '')} {item.get('id', '')}")
    return "\n".join(lines) + "\n"


def _render_index_report(payload: Mapping[str, Any]) -> str:
    lines = ["TeeBotus Codex-History Index", ""]
    totals = payload.get("totals", {})
    if isinstance(totals, Mapping):
        lines.append(f"categorized: {totals.get('categorized', 0)}")
        lines.append(f"category_errors: {totals.get('category_errors', 0)}")
        lines.append(f"exported: {totals.get('exported', 0)}")
        lines.append(f"skipped: {totals.get('skipped', 0)}")
        lines.append(f"graph_files: {totals.get('graph_files', 0)}")
        lines.append(f"graph_svg_files: {totals.get('graph_svg_files', 0)}")
        lines.append(f"graph_queued: {totals.get('graph_queued', 0)}")
        lines.append(f"graph_items: {totals.get('graph_items', 0)}")
        lines.append(f"strategy_reports: {totals.get('strategy_reports', 0)}")
        lines.append(f"strategy_cached: {totals.get('strategy_cached', 0)}")
        lines.append(f"strategy_analyzed: {totals.get('strategy_analyzed', 0)}")
        lines.append(f"qdrant_points: {totals.get('qdrant_points', 0)}")
        lines.append(f"qdrant_errors: {totals.get('qdrant_errors', 0)}")
    for instance in payload.get("instances", []):
        if not isinstance(instance, Mapping):
            continue
        export = instance.get("export", {})
        if not isinstance(export, Mapping):
            export = {}
        category_report = instance.get("categorize", {})
        if not isinstance(category_report, Mapping):
            category_report = {}
        graph = instance.get("graph", {})
        if not isinstance(graph, Mapping):
            graph = {}
        strategy = instance.get("strategic_analysis", {})
        if not isinstance(strategy, Mapping):
            strategy = {}
        lines.append("")
        lines.append(f"Instance: {instance.get('instance', '')}")
        lines.append(f"  ok: {bool(instance.get('ok', False))}")
        if category_report:
            lines.append(
                "  categorize: "
                f"profile={category_report.get('profile', '')} "
                f"dry_run={bool(category_report.get('dry_run', False))} "
                f"scanned={category_report.get('scanned', 0)} "
                f"categorized={category_report.get('categorized', 0)} "
                f"errors={len(category_report.get('errors') or [])}"
            )
        lines.append(f"  destination: {export.get('destination', '')}")
        lines.append(f"  exported: {export.get('exported', 0)}")
        lines.append(f"  skipped: {export.get('skipped', 0)}")
        if graph:
            queued_item = graph.get("queued_item", {})
            queued_prefix = queued_item.get("summary_prefix", "") if isinstance(queued_item, Mapping) else ""
            lines.append(
                "  graph: "
                f"path={graph.get('path', '')} "
                f"svg_path={graph.get('svg_path', '')} "
                f"queued={queued_prefix} "
                f"repos={graph.get('repo_count', 0)} "
                f"items={graph.get('item_count', 0)}"
            )
        if strategy:
            item = strategy.get("item", {})
            summary_prefix = item.get("summary_prefix", "") if isinstance(item, Mapping) else ""
            lines.append(
                "  strategic_analysis: "
                f"status={strategy.get('status', '')} "
                f"dry_run={bool(strategy.get('dry_run', False))} "
                f"cache_hit={bool(strategy.get('cache_hit', False))} "
                f"analyzed={strategy.get('analyzed', 0)} "
                f"summary={summary_prefix}"
            )
        for result in instance.get("qdrant_ensure", []) or []:
            if isinstance(result, Mapping):
                lines.append(
                    "  qdrant_ensure: "
                    f"collection={result.get('collection_name', '')} "
                    f"status={result.get('status', '')} "
                    f"ok={result.get('ok', '')}"
                )
        for result in instance.get("qdrant", []) or []:
            if isinstance(result, Mapping):
                lines.append(
                    "  qdrant: "
                    f"collection={result.get('collection_name', '')} "
                    f"status={result.get('status', '')} "
                    f"chunks={result.get('chunk_count', 0)} "
                    f"points={result.get('point_count', 0)}"
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
        for item in _watch_detail_items(instance.get("items", [])):
            if not isinstance(item, Mapping):
                continue
            lines.append(_watch_import_detail_line(item))
        post_index = instance.get("post_index")
        if isinstance(post_index, Mapping):
            export = post_index.get("export", {})
            if not isinstance(export, Mapping):
                export = {}
            lines.append(
                "  post_index: "
                f"ok={bool(post_index.get('ok', False))} "
                f"exported={export.get('exported', 0)} "
                f"skipped={export.get('skipped', 0)}"
            )
            for result in post_index.get("qdrant", []) or []:
                if isinstance(result, Mapping):
                    lines.append(
                        "  post_index_qdrant: "
                        f"collection={result.get('collection_name', '')} "
                        f"status={result.get('status', '')} "
                        f"points={result.get('point_count', 0)}"
                    )
        dispatch = instance.get("dispatch")
        if isinstance(dispatch, Mapping):
            dispatch_instances = dispatch.get("instances", [])
            if isinstance(dispatch_instances, Sequence) and not isinstance(dispatch_instances, (str, bytes, bytearray)):
                for dispatch_instance in dispatch_instances:
                    if not isinstance(dispatch_instance, Mapping):
                        continue
                    dispatch_counts = dispatch_instance.get("status_counts", {})
                    if not isinstance(dispatch_counts, Mapping):
                        dispatch_counts = {}
                    lines.append(
                        "  dispatch: "
                        f"ok={bool(dispatch_instance.get('ok', False))} "
                        f"dry_run={bool(dispatch_instance.get('dry_run', False))} "
                        f"statuses={_format_status_counts(dispatch_counts)}"
                    )
                    for item in dispatch_instance.get("items", []) or []:
                        if not isinstance(item, Mapping):
                            continue
                        lines.append(
                            "  dispatch_item: "
                            f"item={item.get('codex_history_item_id', '')} "
                            f"account={item.get('account_id', '')} "
                            f"channel={item.get('channel', '')} "
                            f"status={item.get('status', '')} "
                            f"reason={item.get('reason', '')}"
                        )
    return "\n".join(lines) + "\n"


def _watch_detail_items(items: Any) -> list[Mapping[str, Any]]:
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes, bytearray)):
        return []
    details: list[Mapping[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("status") or "").strip().casefold() == "duplicate":
            continue
        details.append(item)
    return details


def _watch_import_detail_line(item: Mapping[str, Any]) -> str:
    item_payload = item.get("item", {})
    summary_prefix = item_payload.get("summary_prefix", "") if isinstance(item_payload, Mapping) else ""
    path_text = str(item.get("path") or "")
    line = (
        "  import: "
        f"status={item.get('status', '')} "
        f"reason={item.get('reason', '')} "
        f"summary={summary_prefix}"
    )
    if path_text:
        line += f" path={path_text}"
    return line


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
    if str(item.get("kind") or "").strip() not in CODEX_HISTORY_INDEXABLE_KINDS:
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
        f"- Erstellt: `{_display_codex_history_timestamp(item.get('created_at', ''))}`",
        f"- Aktualisiert: `{_display_codex_history_timestamp(item.get('updated_at', ''))}`",
        f"- Sent: `{_display_codex_history_timestamp(delivery.get('sent_at', ''))}`",
        f"- Accepted: `{_display_codex_history_timestamp(delivery.get('accepted_at', ''))}`",
        f"- Delivered: `{_display_codex_history_timestamp(delivery.get('delivered_at', ''))}`",
        f"- Acknowledged: `{_display_codex_history_timestamp(delivery.get('acknowledged_at', ''))}`",
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


def _codex_history_graph_markdown(items: Sequence[Mapping[str, Any]], *, instance_name: str, repo_filter: str = "") -> str:
    repos: dict[str, dict[str, Any]] = {}
    for item in items:
        project = item.get("project", {})
        if not isinstance(project, Mapping):
            project = {}
        repo_id = str(project.get("repo_id") or project.get("repo_name") or "repo").strip() or "repo"
        repo_entry = repos.setdefault(
            repo_id,
            {
                "name": str(project.get("repo_name") or "project").strip() or "project",
                "items": [],
            },
        )
        repo_entry["items"].append(item)
    graph_direction = "TD" if len(repos) > 2 else "LR"
    status_counts = Counter(str(item.get("status") or "unknown").strip().casefold() or "unknown" for item in items if isinstance(item, Mapping))
    category_counts: Counter[str] = Counter()
    for item in items:
        if isinstance(item, Mapping):
            category_counts.update(_codex_history_mermaid_categories(item))
    lines = [
        f"# Codex History Graph: {redact_codex_history_text(instance_name).strip()}",
        "",
        "> Admin-only TeeBotus Codex-History-Graph. Nicht fuer normale Nutzer-Bibliotheken freigeben.",
        "",
        f"- Instanz: `{redact_codex_history_text(instance_name).strip()}`",
        f"- Repo-Filter: `{redact_codex_history_text(repo_filter).strip() or '<alle>'}`",
        f"- Repos: `{len(repos)}`",
        f"- Summaries: `{len(items)}`",
        f"- Erstellt: `{_display_codex_history_timestamp(utc_now())}`",
        "",
        "```mermaid",
        f"flowchart {graph_direction}",
        '  scope["Admin Codex-History"]:::scope',
        f'  totals["{len(items)} Summaries / {len(repos)} Repos"]:::metric',
        f'  status_overview["Status: {_mermaid_label(_codex_history_counter_label(status_counts), max_length=72)}"]:::status',
        f'  category_overview["Top-Kategorien: {_mermaid_label(_codex_history_counter_label(category_counts), max_length=72)}"]:::category',
        "  scope --> totals",
        "  scope --> status_overview",
        "  scope --> category_overview",
    ]
    if not repos:
        lines.append('  empty["Keine indexierbaren Codex-History-Eintraege"]:::empty')
        lines.append("  scope --> empty")
    for repo_index, (_repo_id, repo_entry) in enumerate(sorted(repos.items(), key=lambda entry: str(entry[1].get("name", "")).casefold())):
        repo_node = f"repo_{repo_index}"
        repo_name = _mermaid_label(str(repo_entry.get("name") or "project"), max_length=48)
        repo_items = list(repo_entry.get("items") or [])
        repo_items = sorted((item for item in repo_items if isinstance(item, Mapping)), key=_summary_sort_key)
        repo_status_counts = Counter(str(item.get("status") or "unknown").strip().casefold() or "unknown" for item in repo_items)
        repo_stats_node = f"repo_{repo_index}_stats"
        lines.append(f'  {repo_node}["{repo_name}"]:::repo')
        lines.append(f"  scope --> {repo_node}")
        lines.append(f'  {repo_stats_node}["{len(repo_items)} Summaries / {_mermaid_label(_codex_history_counter_label(repo_status_counts), max_length=48)}"]:::metric')
        lines.append(f"  {repo_node} --> {repo_stats_node}")
        previous_node = ""
        for item_index, item in enumerate(repo_items[-20:]):
            item_node = f"item_{repo_index}_{item_index}"
            summary = item.get("summary", {})
            if not isinstance(summary, Mapping):
                summary = {}
            title = str(summary.get("title") or "Codex run summary")
            label = _mermaid_label(f"{item.get('summary_prefix', '')} {title}", max_length=72)
            lines.append(f'  {item_node}["{label}"]:::summary')
            if previous_node:
                lines.append(f"  {previous_node} --> {item_node}")
            else:
                lines.append(f"  {repo_node} --> {item_node}")
            status_node = f"status_{repo_index}_{item_index}"
            status = _safe_filename_component(str(item.get("status") or "unknown"), default="unknown", max_length=32)
            lines.append(f'  {status_node}["status: {status}"]:::status')
            lines.append(f"  {item_node} --> {status_node}")
            category_nodes = _codex_history_graph_category_nodes(item, repo_index=repo_index, item_index=item_index)
            for category_node, category_label in category_nodes:
                lines.append(f'  {category_node}["{_mermaid_label(category_label, max_length=42)}"]:::category')
                lines.append(f"  {item_node} --> {category_node}")
            previous_node = item_node
    lines.extend(
        [
            "  classDef scope fill:#1f2937,color:#fff,stroke:#111827",
            "  classDef repo fill:#dbeafe,stroke:#2563eb,color:#111827",
            "  classDef summary fill:#ecfdf5,stroke:#059669,color:#111827",
            "  classDef status fill:#fef3c7,stroke:#d97706,color:#111827",
            "  classDef category fill:#f3e8ff,stroke:#7c3aed,color:#111827",
            "  classDef metric fill:#f8fafc,stroke:#64748b,color:#111827",
            "  classDef empty fill:#fee2e2,stroke:#dc2626,color:#111827",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _codex_history_counter_label(counter: Counter[str], *, max_items: int = 4) -> str:
    if not counter:
        return "none"
    parts = [f"{name}={count}" for name, count in counter.most_common(max_items)]
    remaining = sum(counter.values()) - sum(count for _name, count in counter.most_common(max_items))
    if remaining > 0:
        parts.append(f"other={remaining}")
    return ", ".join(parts)


def _codex_history_graph_project(instance_name: str, *, repo: str = "") -> dict[str, Any]:
    repo_filter = str(repo or "").strip()
    repo_name = "Codex-History-Graph" if not repo_filter else f"Codex-History-Graph-{repo_filter}"
    identity = f"codex-history-graph:v1:{instance_name}:{repo_filter}"
    return {
        "repo_id": "sha256:" + hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        "repo_name": repo_name,
        "repo_root": "",
        "remote_url": "",
        "provider": "internal",
        "branch": "",
        "head_commit": "",
        "dirty": False,
    }


def _codex_history_graph_artifact_markdown(
    *,
    summary_prefix: str,
    instance_name: str,
    repo_filter: str,
    svg_filename: str,
    source_path: str,
    item_count: int,
    repo_count: int,
    created_at: str,
) -> str:
    lines = [
        f"# {summary_prefix} Codex-History SVG-Graph",
        "",
        "> Admin-only TeeBotus Codex-History-Graph. Nicht fuer normale Nutzer-Bibliotheken freigeben.",
        "",
        f"- Instanz: `{redact_codex_history_text(instance_name).strip()}`",
        f"- Repo-Filter: `{redact_codex_history_text(repo_filter).strip() or '<alle>'}`",
        f"- SVG-Datei: `{redact_codex_history_text(svg_filename).strip()}`",
        f"- Quelle: `{redact_codex_history_text(source_path).strip()}`",
        f"- Repos: `{int(repo_count or 0)}`",
        f"- Summaries: `{int(item_count or 0)}`",
        f"- Erstellt: `{_display_codex_history_timestamp(created_at)}`",
        "",
        "Das zugehoerige SVG wird als Attachment dieses Codex-History-Outbox-Eintrags versendet.",
        "",
    ]
    return "\n".join(lines)


def _render_codex_history_graph_svg(
    items: Sequence[Mapping[str, Any]],
    *,
    instance_name: str,
    repo_filter: str = "",
    engine: str = "builtin",
) -> tuple[str, str, str]:
    requested = _codex_history_graph_svg_engine(engine)
    warning = ""
    if requested in {"auto", "mmdc"}:
        mmdc_path = shutil.which("mmdc")
        if mmdc_path:
            try:
                return (
                    _codex_history_graph_svg_mmdc(
                        items,
                        instance_name=instance_name,
                        repo_filter=repo_filter,
                        mmdc_path=mmdc_path,
                    ),
                    "mmdc",
                    "",
                )
            except (OSError, subprocess.SubprocessError, ValueError) as exc:
                message = _truncate(redact_codex_history_text(f"{type(exc).__name__}: {exc}"), 240)
                if requested == "mmdc":
                    raise ValueError(f"mmdc svg render failed: {message}") from exc
                warning = f"mmdc_failed_fallback_builtin:{message}"
        elif requested == "mmdc":
            raise ValueError("mmdc svg render requested but Mermaid CLI executable 'mmdc' was not found")
        else:
            warning = "mmdc_not_found_fallback_builtin"
    return _codex_history_graph_svg(items, instance_name=instance_name, repo_filter=repo_filter), "builtin", warning


def _codex_history_graph_svg_engine(value: str) -> str:
    engine = str(value or "builtin").strip().casefold()
    if engine not in CODEX_HISTORY_GRAPH_SVG_ENGINES:
        raise ValueError(f"unsupported codex history graph svg engine: {value}")
    return engine


def _codex_history_graph_svg_mmdc(
    items: Sequence[Mapping[str, Any]],
    *,
    instance_name: str,
    repo_filter: str,
    mmdc_path: str,
) -> str:
    mermaid = _codex_history_graph_mermaid_source(items, instance_name=instance_name, repo_filter=repo_filter)
    with tempfile.TemporaryDirectory(prefix="teebotus-codex-history-graph-") as tmp_dir:
        input_path = Path(tmp_dir) / "graph.mmd"
        output_path = Path(tmp_dir) / "graph.svg"
        input_path.write_text(mermaid, encoding="utf-8")
        result = subprocess.run(
            [mmdc_path, "-i", str(input_path), "-o", str(output_path), "-b", "transparent"],
            capture_output=True,
            check=False,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            detail = _truncate((result.stderr or result.stdout or "mmdc failed").strip(), 500)
            raise ValueError(detail)
        svg_text = output_path.read_text(encoding="utf-8")
        if "<svg" not in svg_text:
            raise ValueError("mmdc did not produce an SVG document")
        return svg_text


def _codex_history_graph_mermaid_source(items: Sequence[Mapping[str, Any]], *, instance_name: str, repo_filter: str = "") -> str:
    markdown = _codex_history_graph_markdown(items, instance_name=instance_name, repo_filter=repo_filter)
    lines = markdown.splitlines()
    in_block = False
    found_block = False
    ended_block = False
    body_lines: list[str] = []
    for line in lines:
        if not in_block:
            if line == "```mermaid":
                in_block = True
                found_block = True
            continue
        if line.strip() == "```":
            ended_block = True
            break
        body_lines.append(line)
    if not found_block or not ended_block:
        raise ValueError("codex history graph markdown does not contain a mermaid block")
    return "\n".join(body_lines).strip() + "\n"


def _codex_history_graph_svg(items: Sequence[Mapping[str, Any]], *, instance_name: str, repo_filter: str = "") -> str:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for item in items:
        project = item.get("project", {}) if isinstance(item, Mapping) else {}
        if not isinstance(project, Mapping):
            project = {}
        repo_name = str(project.get("repo_name") or "project").strip() or "project"
        grouped.setdefault(repo_name, []).append(item)
    repo_rows = [(repo, sorted(rows, key=_summary_sort_key)[-8:]) for repo, rows in sorted(grouped.items(), key=lambda entry: entry[0].casefold())]
    width = 1400
    row_height = 132
    height = 180 + max(1, len(repo_rows)) * row_height
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="TeeBotus Codex History Graph">',
        "<style>",
        "text{font-family:Inter,Arial,sans-serif;fill:#111827}",
        ".title{font-size:28px;font-weight:700}",
        ".meta{font-size:14px;fill:#4b5563}",
        ".repo{font-size:18px;font-weight:700}",
        ".small{font-size:12px;fill:#374151}",
        ".card{fill:#ecfdf5;stroke:#059669;stroke-width:1.2}",
        ".repoBox{fill:#dbeafe;stroke:#2563eb;stroke-width:1.2}",
        ".pill{fill:#f3e8ff;stroke:#7c3aed;stroke-width:1}",
        ".status{fill:#fef3c7;stroke:#d97706;stroke-width:1}",
        "</style>",
        '<rect x="0" y="0" width="1400" height="' + str(height) + '" fill="#f9fafb"/>',
        f'<text class="title" x="36" y="48">{_svg_text("TeeBotus Codex-History")}</text>',
        f'<text class="meta" x="36" y="76">Instanz: {_svg_text(instance_name)} | Repo-Filter: {_svg_text(repo_filter or "<alle>")} | Repos: {len(repo_rows)} | Summaries: {len(items)}</text>',
        '<text class="meta" x="36" y="102">Admin-only. Nicht in normale Nutzerbibliotheken freigeben.</text>',
    ]
    if not repo_rows:
        lines.extend(
            [
                '<rect class="repoBox" x="36" y="132" width="1328" height="72" rx="8"/>',
                '<text class="repo" x="60" y="176">Keine indexierbaren Codex-History-Eintraege</text>',
            ]
        )
    for repo_index, (repo_name, rows) in enumerate(repo_rows):
        y = 132 + repo_index * row_height
        lines.append(f'<rect class="repoBox" x="36" y="{y}" width="250" height="92" rx="8"/>')
        lines.append(f'<text class="repo" x="56" y="{y + 32}">{_svg_text(_truncate(repo_name, 28))}</text>')
        lines.append(f'<text class="small" x="56" y="{y + 56}">{len(rows)} letzte Summaries</text>')
        card_width = 126
        gap = 12
        for item_index, item in enumerate(rows):
            x = 314 + item_index * (card_width + gap)
            if x + card_width > width - 36:
                break
            summary = item.get("summary", {})
            if not isinstance(summary, Mapping):
                summary = {}
            title = _truncate(str(summary.get("title") or "Codex run summary"), 18)
            prefix = _truncate(str(item.get("summary_prefix") or ""), 16)
            status = _truncate(str(item.get("status") or "unknown"), 14)
            category = _truncate(_first_graph_category(item), 18)
            lines.append(f'<rect class="card" x="{x}" y="{y}" width="{card_width}" height="92" rx="8"/>')
            lines.append(f'<text class="small" x="{x + 10}" y="{y + 22}">{_svg_text(prefix)}</text>')
            lines.append(f'<text class="small" x="{x + 10}" y="{y + 44}">{_svg_text(title)}</text>')
            lines.append(f'<rect class="status" x="{x + 10}" y="{y + 56}" width="{card_width - 20}" height="18" rx="9"/>')
            lines.append(f'<text class="small" x="{x + 18}" y="{y + 69}">{_svg_text(status)}</text>')
            lines.append(f'<text class="small" x="{x + 10}" y="{y + 88}">{_svg_text(category)}</text>')
            if item_index > 0:
                prev_x = x - gap
                lines.append(f'<line x1="{prev_x}" y1="{y + 46}" x2="{x}" y2="{y + 46}" stroke="#059669" stroke-width="1.4"/>')
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def _first_graph_category(item: Mapping[str, Any]) -> str:
    for category in _codex_history_bibliothekar_categories(item):
        if category.startswith(("change-", "risk-", "impact-", "work-", "codex-strategy")):
            return category
    return "project-history"


def _svg_text(value: object) -> str:
    return html.escape(redact_codex_history_text(value).strip(), quote=True)


def _truncate(value: str, max_length: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_length:
        return text
    return text[: max(3, max_length - 3)].rstrip() + "..."


def _codex_history_graph_category_nodes(item: Mapping[str, Any], *, repo_index: int, item_index: int) -> list[tuple[str, str]]:
    categories = [
        category
        for category in _codex_history_bibliothekar_categories(item)
        if category.startswith(("change-", "risk-", "impact-", "work-"))
    ][:5]
    return [(f"cat_{repo_index}_{item_index}_{index}", category) for index, category in enumerate(categories)]


def _codex_history_graph_repo_count(items: Sequence[Mapping[str, Any]]) -> int:
    repo_ids: set[str] = set()
    for item in items:
        project = item.get("project", {}) if isinstance(item, Mapping) else {}
        if not isinstance(project, Mapping):
            project = {}
        repo_ids.add(str(project.get("repo_id") or project.get("repo_name") or "repo"))
    return len(repo_ids)


def _mermaid_label(value: str, *, max_length: int) -> str:
    text = redact_codex_history_text(value).replace("\r", " ").replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) > max_length:
        text = text[: max(8, max_length - 3)].rstrip() + "..."
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _codex_history_strategy_project(instance_name: str, *, repo: str = "") -> dict[str, Any]:
    repo_filter = str(repo or "").strip()
    repo_name = "Codex-History-Strategie" if not repo_filter else f"Codex-History-Strategie-{repo_filter}"
    identity = f"codex-history-strategy:v1:{instance_name}:{repo_filter}"
    return {
        "repo_id": "sha256:" + hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        "repo_name": repo_name,
        "repo_root": "",
        "remote_url": "",
        "provider": "internal",
        "branch": "",
        "head_commit": "",
        "dirty": False,
    }


def _codex_history_strategy_prompt(items: Sequence[Mapping[str, Any]]) -> str:
    payload = {
        "task": "Analysiere die letzten TeeBotus Codex-History-Summaries strategisch.",
        "rules": [
            "Return only JSON.",
            "Keine Secrets, Tokens oder privaten Rohdaten ausgeben.",
            "Fokussiere Feature-/Bugfix-Vergleich, Risiken, naechste sinnvolle Ziele und Angriffsoberflaechen.",
            "Jede Liste 2 bis 8 kurze Punkte.",
        ],
        "schema": {
            "future_improvements": ["..."],
            "strategic_goals": ["..."],
            "pitfalls_logic_errors": ["..."],
            "attack_surface": ["..."],
            "recommendations": ["..."],
            "confidence": "low|medium|high",
        },
        "summaries": [_codex_history_strategy_source_summary(item) for item in items[-40:]],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _parse_codex_history_strategy_response(text: str) -> dict[str, Any]:
    payload = _json_object_from_text(text)
    if not payload:
        raise ValueError("strategy model returned no JSON object")
    return _normalize_codex_history_strategy_decision(payload)


def _normalize_codex_history_strategy_decision(decision: Mapping[str, Any] | str) -> dict[str, Any]:
    if isinstance(decision, str):
        payload = _json_object_from_text(decision)
        if payload:
            decision = payload
        else:
            decision = {"recommendations": [decision]}
    if not isinstance(decision, Mapping):
        decision = {}
    sections = {
        "future_improvements": _strategy_section_values(decision.get("future_improvements", [])),
        "strategic_goals": _strategy_section_values(decision.get("strategic_goals", [])),
        "pitfalls_logic_errors": _strategy_section_values(decision.get("pitfalls_logic_errors", [])),
        "attack_surface": _strategy_section_values(decision.get("attack_surface", [])),
        "recommendations": _strategy_section_values(decision.get("recommendations", [])),
    }
    if not any(sections.values()):
        sections["recommendations"] = ["Keine verwertbaren Strategiepunkte erzeugt; Rohantwort pruefen."]
    confidence = str(decision.get("confidence") or "medium").strip().casefold()
    if confidence not in {"low", "medium", "high"}:
        confidence = "medium"
    return {**sections, "confidence": confidence}


def _codex_history_strategy_source_fingerprint(items: Sequence[Mapping[str, Any]]) -> str:
    source = [
        {
            "id": str(item.get("id") or ""),
            "summary_prefix": str(item.get("summary_prefix") or ""),
            "updated_at": str(item.get("updated_at") or item.get("created_at") or ""),
            "status": str(item.get("status") or ""),
        }
        for item in items
        if isinstance(item, Mapping)
    ]
    return hashlib.sha256(json.dumps(source, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _latest_codex_history_strategy_for_sources(
    rows: Sequence[Mapping[str, Any]],
    *,
    repo: str,
    profile: str,
    source_fingerprint: str,
    source_ids: Sequence[str],
) -> dict[str, Any]:
    repo_filter = str(repo or "").strip()
    profile_name = str(profile or CODEX_HISTORY_DEFAULT_STRATEGY_PROFILE).strip() or CODEX_HISTORY_DEFAULT_STRATEGY_PROFILE
    expected_ids = tuple(str(item_id or "") for item_id in source_ids)
    for row in reversed([row for row in rows if isinstance(row, Mapping)]):
        if str(row.get("kind") or "").strip() != "codex_strategy_analysis":
            continue
        codex = row.get("codex", {})
        if not isinstance(codex, Mapping):
            continue
        if str(codex.get("repo_filter") or "").strip() != repo_filter:
            continue
        cached_profile = str(codex.get("strategy_profile") or codex.get("strategy_model") or "").strip()
        if cached_profile and cached_profile != profile_name:
            continue
        cached_fingerprint = str(codex.get("source_fingerprint") or "").strip()
        if cached_fingerprint:
            if cached_fingerprint == source_fingerprint:
                return dict(row)
            continue
        cached_ids = tuple(str(item_id or "") for item_id in (codex.get("analyzed_item_ids") or []))
        if cached_ids == expected_ids:
            return dict(row)
    return {}


def _strategy_section_values(value: object) -> list[str]:
    if isinstance(value, str):
        raw_values = [part.strip() for part in re.split(r"[\n;]+", value) if part.strip()]
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        raw_values = [str(item or "").strip() for item in value if str(item or "").strip()]
    else:
        raw_values = []
    result: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        text = redact_codex_history_text(raw)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        text = text[:360]
        marker = text.casefold()
        if marker in seen:
            continue
        seen.add(marker)
        result.append(text)
        if len(result) >= 8:
            break
    return result


def _codex_history_strategy_markdown(
    *,
    summary_prefix: str,
    instance_name: str,
    repo_filter: str,
    analysis: Mapping[str, Any],
    source_items: Sequence[Mapping[str, Any]],
    created_at: str,
) -> str:
    lines = [
        f"# {summary_prefix} Strategische Codex-History-Analyse",
        "",
        "> Admin-only TeeBotus Codex-History-Analyse. Nicht fuer normale Nutzer-Bibliotheken freigeben.",
        "",
        f"- Instanz: `{redact_codex_history_text(instance_name).strip()}`",
        f"- Repo-Filter: `{redact_codex_history_text(repo_filter).strip() or '<alle>'}`",
        f"- Analysierte Summaries: `{len(source_items)}`",
        f"- Erstellt: `{_display_codex_history_timestamp(created_at)}`",
        f"- Confidence: `{redact_codex_history_text(analysis.get('confidence', '')).strip()}`",
        "",
    ]
    section_titles = (
        ("future_improvements", "Zukunft und Verbesserungen"),
        ("strategic_goals", "Strategische Ziele"),
        ("pitfalls_logic_errors", "Fallstricke und Logikfehler"),
        ("attack_surface", "Neue Angriffsoberflaechen"),
        ("recommendations", "Empfehlungen"),
    )
    for key, title in section_titles:
        lines.append(f"## {title}")
        values = analysis.get(key, [])
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)) and values:
            lines.extend(f"- {value}" for value in values)
        else:
            lines.append("- Keine belastbaren Punkte erzeugt.")
        lines.append("")
    lines.append("## Quellen-Summaries")
    for item in source_items[-40:]:
        source = _codex_history_strategy_source_summary(item)
        lines.append(
            "- "
            f"`{source.get('summary_prefix', '')}` "
            f"`{source.get('repo_name', '')}` "
            f"{source.get('title', '')}"
        )
    lines.append("")
    return "\n".join(lines)


def _codex_history_strategy_source_summary(item: Mapping[str, Any]) -> dict[str, Any]:
    project = item.get("project", {})
    summary = item.get("summary", {})
    version = item.get("version", {})
    if not isinstance(project, Mapping):
        project = {}
    if not isinstance(summary, Mapping):
        summary = {}
    if not isinstance(version, Mapping):
        version = {}
    return {
        "id": str(item.get("id") or ""),
        "summary_prefix": redact_codex_history_text(item.get("summary_prefix") or version.get("summary_prefix") or "").strip(),
        "repo_name": redact_codex_history_text(project.get("repo_name", "")).strip(),
        "status": redact_codex_history_text(item.get("status", "")).strip(),
        "created_at": redact_codex_history_text(item.get("created_at", "")).strip(),
        "title": redact_codex_history_text(summary.get("title", "")).strip()[:180],
        "bullets": [redact_codex_history_text(value)[:220] for value in _sequence_values(summary.get("bullets", []))[:6]],
        "changed_files": [redact_codex_history_text(value)[:180] for value in _sequence_values(summary.get("changed_files", []))[:8]],
        "tests": [redact_codex_history_text(value)[:180] for value in _sequence_values(summary.get("tests", []))[:6]],
    }


def _codex_history_strategy_bullets(analysis: Mapping[str, Any]) -> list[str]:
    bullets: list[str] = []
    for key in ("recommendations", "strategic_goals", "pitfalls_logic_errors", "attack_surface", "future_improvements"):
        values = analysis.get(key, [])
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)):
            for value in values:
                text = str(value or "").strip()
                if text:
                    bullets.append(text[:240])
                if len(bullets) >= 8:
                    return bullets
    return bullets or ["Strategische Analyse erzeugt."]


def _codex_history_strategy_keywords(project: Mapping[str, Any], analysis: Mapping[str, Any], source_items: Sequence[Mapping[str, Any]]) -> list[str]:
    words: set[str] = {
        "codex",
        "history",
        "strategy",
        "analysis",
        "strategic-analysis",
        "admin-only",
        str(project.get("repo_name") or "").casefold(),
    }
    for item in source_items:
        source = _codex_history_strategy_source_summary(item)
        for value in (source.get("repo_name", ""), source.get("summary_prefix", ""), source.get("title", "")):
            for token in re.findall(r"[A-Za-z0-9_.-]{3,}", str(value or "")):
                words.add(token.casefold())
    for key in ("future_improvements", "strategic_goals", "pitfalls_logic_errors", "attack_surface", "recommendations"):
        values = analysis.get(key, [])
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)):
            for value in values:
                for token in re.findall(r"[A-Za-z0-9_.-]{3,}", str(value or "")):
                    words.add(token.casefold())
    return sorted(word for word in words if word)[:160]


def _codex_history_strategist_model(strategist: object, profile: str) -> str:
    model = str(getattr(strategist, "strategy_model", "") or "").strip()
    if model:
        return model
    return str(getattr(strategist, "strategy_profile", "") or profile or "").strip()


def _codex_history_category_prompt(item: Mapping[str, Any]) -> str:
    project = item.get("project", {})
    summary = item.get("summary", {})
    version = item.get("version", {})
    if not isinstance(project, Mapping):
        project = {}
    if not isinstance(summary, Mapping):
        summary = {}
    if not isinstance(version, Mapping):
        version = {}
    payload = {
        "task": "Select matching categories for this TeeBotus Codex-History entry.",
        "rules": [
            "Return only JSON.",
            "Use only categories from allowed_categories.",
            "Do not invent repo/status/admin scope categories.",
            "Prefer 2 to 8 categories.",
        ],
        "schema": {"categories": ["change-feature", "risk-security"], "rationale": "optional short German reason"},
        "allowed_categories": sorted(CODEX_HISTORY_LLM_CATEGORY_ALLOWLIST),
        "entry": {
            "repo_name": redact_codex_history_text(project.get("repo_name", "")),
            "summary_prefix": redact_codex_history_text(item.get("summary_prefix") or version.get("summary_prefix") or ""),
            "title": redact_codex_history_text(summary.get("title", "")),
            "bullets": [redact_codex_history_text(value)[:280] for value in _sequence_values(summary.get("bullets", []))[:12]],
            "changed_files": [redact_codex_history_text(value)[:240] for value in _sequence_values(summary.get("changed_files", []))[:24]],
            "tests": [redact_codex_history_text(value)[:240] for value in _sequence_values(summary.get("tests", []))[:12]],
        },
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _parse_codex_history_llm_category_response(text: str) -> dict[str, Any]:
    payload = _json_object_from_text(text)
    if not payload:
        raise ValueError("local categorizer returned no JSON object")
    categories = _normalize_codex_history_llm_categories(payload.get("categories", []))
    if not categories:
        raise ValueError("local categorizer returned no allowed categories")
    rationale = redact_codex_history_text(payload.get("rationale", "")).strip()[:240]
    result: dict[str, Any] = {"categories": categories}
    if rationale:
        result["rationale"] = rationale
    return result


def _codex_history_llm_categories_from_decision(decision: Mapping[str, Any] | Sequence[str] | str) -> list[str]:
    if isinstance(decision, Mapping):
        return _normalize_codex_history_llm_categories(decision.get("categories", []))
    return _normalize_codex_history_llm_categories(decision)


def _normalize_codex_history_llm_categories(value: object) -> list[str]:
    raw_values: list[str] = []
    if isinstance(value, str):
        raw_values = [part.strip() for part in re.split(r"[,;\n]+", value) if part.strip()]
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        raw_values = [str(item or "").strip() for item in value if str(item or "").strip()]
    result: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        category = re.sub(r"[^a-z0-9_.-]+", "-", raw.casefold()).strip(".-_")
        if category not in CODEX_HISTORY_LLM_CATEGORY_ALLOWLIST:
            continue
        if category in seen:
            continue
        seen.add(category)
        result.append(category)
    return result[:32]


def _json_object_from_text(text: str) -> dict[str, Any]:
    value = str(text or "").strip()
    if not value:
        return {}
    try:
        payload = json.loads(value)
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        pass
    start = value.find("{")
    end = value.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        payload = json.loads(value[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _codex_history_categorizer_model(categorizer: object, profile: str) -> str:
    model = str(getattr(categorizer, "category_model", "") or "").strip()
    if model:
        return model
    return str(getattr(categorizer, "category_profile", "") or profile or "").strip()


def _codex_history_bibliothekar_categories(item: Mapping[str, Any], *, include_persisted: bool = True) -> list[str]:
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
    if str(item.get("kind") or "").strip() == "codex_strategy_analysis":
        categories.update({"codex-strategy-analysis", "impact-admin-only", "work-strategy"})
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
    if include_persisted:
        indexing = item.get("indexing", {})
        if isinstance(indexing, Mapping):
            categories.update(_normalize_codex_history_llm_categories(indexing.get("categories", [])))
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


def _sequence_values(value: object) -> list[str]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [str(item or "") for item in value if str(item or "").strip()]
    return []


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
        if previous is None or _summary_sort_key(row) >= _summary_sort_key(previous):
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
