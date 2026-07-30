from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from TeeBotus.history_dispatcher_bridge import (
    CallbackSpool,
    HistoryDispatcherBridge,
    HistoryDispatcherClient,
    HistoryDispatcherProtocolError,
    ProviderCallbackSpool,
)
from TeeBotus.runtime.accounts import (
    INSTANCE_STATE_ACCOUNT_ID,
    AccountStore,
    InstanceSecretProvider,
)


PROVIDER_V2_LEGACY_SPOOL_DIRNAME = ".History_Dispatcher_Callbacks"
PROVIDER_V2_CALLBACK_SPOOL_DIRNAME = ".History_Dispatcher_Provider_V2_Callbacks"
MAX_PROVIDER_V2_VISIBLE_TEXT_BYTES = 512 * 1024
_SAFE_OPAQUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
_REASON_RE = re.compile(r"[^a-z0-9_]+")
_ALLOWED_HISTORY_KINDS = frozenset(
    {
        "task_completion",
        "subagent_completion",
        "intermediate_update",
    }
)
_SUCCESS_STATUSES = frozenset({"accepted", "delivered", "acknowledged"})


def _opaque(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise HistoryDispatcherProtocolError(f"{field} must be a string")
    normalized = value.strip()
    if not _SAFE_OPAQUE_RE.fullmatch(normalized):
        raise HistoryDispatcherProtocolError(f"{field} is invalid")
    return normalized


def _bounded_text(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise HistoryDispatcherProtocolError(f"{field} must be a string")
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise HistoryDispatcherProtocolError(f"{field} must not be empty")
    if len(normalized.encode("utf-8")) > MAX_PROVIDER_V2_VISIBLE_TEXT_BYTES:
        raise HistoryDispatcherProtocolError(f"{field} exceeds the byte limit")
    return normalized


def _reason_code(value: object, *, default: str) -> str:
    normalized = str(value or "").strip().casefold()
    normalized = _REASON_RE.sub("_", normalized).strip("_")
    return (normalized or default)[:96]


def build_provider_v2_bridge(
    store: AccountStore,
    *,
    instance_name: str,
    socket_path: str | Path,
    secret_provider: InstanceSecretProvider | None = None,
) -> HistoryDispatcherBridge:
    if not isinstance(store, AccountStore):
        raise TypeError("provider-v2 bridge requires an AccountStore")
    provider = secret_provider or store.secret_provider
    state_dir = store.account_dir(INSTANCE_STATE_ACCOUNT_ID)
    return HistoryDispatcherBridge(
        HistoryDispatcherClient(socket_path, timeout_seconds=10),
        CallbackSpool(state_dir / PROVIDER_V2_LEGACY_SPOOL_DIRNAME),
        provider_spool=ProviderCallbackSpool(
            state_dir / PROVIDER_V2_CALLBACK_SPOOL_DIRNAME,
            secret_provider=provider,
            instance_name=instance_name,
        ),
    )


def provider_v2_claim_to_legacy_item(
    claim: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(claim, Mapping):
        raise HistoryDispatcherProtocolError("provider claim must be an object")
    if "reconciliation_only" in claim:
        raise HistoryDispatcherProtocolError(
            "reconciliation-only claim cannot enter the Telegram transport adapter"
        )
    event_id = _opaque(claim.get("event_id"), field="event_id")
    payload = claim.get("payload")
    if not isinstance(payload, Mapping):
        raise HistoryDispatcherProtocolError("provider claim payload must be an object")
    history_kind = str(payload.get("history_kind") or "").strip().casefold()
    if history_kind not in _ALLOWED_HISTORY_KINDS:
        raise HistoryDispatcherProtocolError("provider claim history_kind is unsupported")
    text = _bounded_text(payload.get("text"), field="payload.text")
    timestamp = str(payload.get("timestamp") or "").strip()
    if len(timestamp) > 64 or any(ord(character) < 0x20 for character in timestamp):
        raise HistoryDispatcherProtocolError("provider claim timestamp is invalid")
    project_id = _opaque(
        payload.get("project_id", "proj_unknown"),
        field="project_id",
    )
    project_label = str(payload.get("project_label") or "History Dispatcher").strip()
    if not project_label or len(project_label) > 120:
        raise HistoryDispatcherProtocolError("provider claim project_label is invalid")
    try:
        ordinal = int(payload.get("source_ordinal") or 1)
    except (TypeError, ValueError) as exc:
        raise HistoryDispatcherProtocolError(
            "provider claim source_ordinal is invalid"
        ) from exc
    ordinal = max(1, min(ordinal, 1_000_000))
    title = {
        "task_completion": "Codex task completion",
        "subagent_completion": "Codex sub-agent completion",
        "intermediate_update": "Codex intermediate update",
    }[history_kind]
    return {
        "id": event_id,
        "schema_version": 1,
        "kind": "codex_run_summary",
        "source": "history_dispatcher_provider_v2",
        "status": "dispatching",
        "created_at": timestamp,
        "updated_at": timestamp,
        "project": {
            "repo_id": project_id,
            "repo_name": project_label,
            "repo_root": "",
        },
        "version": {
            "semver": "provider-v2",
            "tag": "",
            "summary_number": ordinal,
            "summary_prefix": history_kind,
        },
        "summary": {
            "title": title,
            "text": text,
            "markdown": text,
            "bullets": [],
            "changed_files": [],
            "tests": [],
        },
        "delivery": {
            "target_group": "status_admins",
            "attempts": max(1, int(claim.get("attempt_no") or 1)),
        },
        "codex": {
            "session_key": str(payload.get("session_key") or ""),
            "turn_key": str(payload.get("turn_key") or ""),
            "parent_thread_key": str(payload.get("parent_thread_key") or ""),
        },
        "summary_number": ordinal,
        "summary_prefix": history_kind,
    }


def provider_v2_dispatch_result_to_outcome(
    result: Mapping[str, Any],
    *,
    recipient_ref: str,
) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        raise HistoryDispatcherProtocolError("transport result must be an object")
    normalized_recipient = _opaque(recipient_ref, field="recipient_ref")
    account_id = str(result.get("account_id") or "").strip().casefold()
    if account_id and account_id != normalized_recipient.casefold():
        raise HistoryDispatcherProtocolError("transport result recipient mismatch")
    raw_status = str(result.get("status") or "failed").strip().casefold()
    possible_duplicate = bool(result.get("possible_duplicate"))
    if possible_duplicate or raw_status == "possible_duplicate":
        status = "possible_duplicate"
    elif raw_status in _SUCCESS_STATUSES:
        status = raw_status
    elif raw_status == "skipped":
        status = "skipped"
    else:
        status = "failed"
    outcome: dict[str, Any] = {
        "recipient_ref": normalized_recipient,
        "status": status,
    }
    if possible_duplicate:
        outcome["possible_duplicate"] = True
    message_ref = str(result.get("message_ref") or "").strip()
    if message_ref:
        digest = hashlib.sha256(message_ref.encode("utf-8")).hexdigest()[:48]
        outcome["message_ref_key"] = f"message_{digest}"
    reason = str(result.get("reason") or "").strip()
    if status not in _SUCCESS_STATUSES and reason:
        outcome["reason_code"] = _reason_code(
            reason,
            default="transport_result",
        )
    return outcome
