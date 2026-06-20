from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from TeeBotus.runtime.accounts import AccountStore, AccountStoreError, TOKEN_HEX_RE
from TeeBotus.runtime.events import IncomingEvent

STATUS_AUTH_CODE_ENV = "TEEBOTUS_STATUS_AUTH_CODE"
STATUS_AUTH_CODES_ENV = "TEEBOTUS_STATUS_AUTH_CODES"
STATUS_AUTH_CODE_INSTANCE_ENV_PREFIX = "TEEBOTUS_STATUS_AUTH_CODE_"
STATUS_AUTH_CODES_INSTANCE_ENV_PREFIX = "TEEBOTUS_STATUS_AUTH_CODES_"
STATUS_AUTH_INSTANCES_ENV = "TEEBOTUS_STATUS_AUTH_INSTANCES"
STATUS_AUTH_CONFIRMATION_TEXT = "Statuszugang aktiviert."
DEFAULT_STATUS_AUTH_INSTANCES = ("TeeBotus_Logger",)

_AUTH_CODE_SEPARATOR_RE = re.compile(r"[\s,;]+")


@dataclass(frozen=True)
class StatusAuthGateResult:
    allowed: bool
    account_id: str = ""
    action_text: str = ""
    reason: str = ""


def _normalize_status_auth_state(state: Any) -> dict[str, Any]:
    return dict(state) if isinstance(state, Mapping) else {}


def status_auth_codes(*, instance_name: str = "", env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    source = os.environ if env is None else env
    codes: list[str] = []
    seen: set[str] = set()
    for env_name, split_value in _status_auth_env_names(instance_name):
        if env_name not in source:
            continue
        raw_value = str(source.get(env_name) or "").strip()
        if not raw_value:
            continue
        values = _AUTH_CODE_SEPARATOR_RE.split(raw_value) if split_value else (raw_value,)
        for value in values:
            code = str(value or "").strip()
            if not code or code in seen:
                continue
            seen.add(code)
            codes.append(code)
    return tuple(codes)


def status_auth_enabled(*, instance_name: str = "", env: Mapping[str, str] | None = None) -> bool:
    return status_auth_instance_protected(instance_name, env=env) and bool(status_auth_codes(instance_name=instance_name, env=env))


def status_auth_instance_protected(instance_name: str, *, env: Mapping[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    raw_instances = source.get(STATUS_AUTH_INSTANCES_ENV)
    if raw_instances is None:
        protected = DEFAULT_STATUS_AUTH_INSTANCES
    else:
        protected = tuple(value for value in _AUTH_CODE_SEPARATOR_RE.split(str(raw_instances or "")) if value)
    instance_token = _env_instance_token(instance_name)
    protected_tokens = {_env_instance_token(value) for value in protected if _env_instance_token(value)}
    return "*" in protected_tokens or "ALL" in protected_tokens or instance_token in protected_tokens


def text_contains_status_auth_code(text: str, *, instance_name: str = "", env: Mapping[str, str] | None = None) -> bool:
    haystack = str(text or "")
    if not haystack:
        return False
    return any(code in haystack for code in status_auth_codes(instance_name=instance_name, env=env))


def status_auth_state_authorized(account_store: AccountStore, account_id: str) -> bool:
    if TOKEN_HEX_RE.fullmatch(str(account_id or "").strip().casefold()) is None:
        return False
    try:
        state = _normalize_status_auth_state(account_store.read_status_auth_state(account_id))
    except (AccountStoreError, OSError, ValueError):
        return False
    return bool(state.get("authorized") is True)


def status_auth_recipient_account_ids(account_store: AccountStore) -> tuple[str, ...]:
    account_ids: list[str] = []
    for account_id in account_store.list_account_ids(include_unresolvable=False):
        if status_auth_state_authorized(account_store, account_id):
            account_ids.append(account_id)
    return tuple(account_ids)


def evaluate_status_auth_gate(
    account_store: AccountStore,
    event: IncomingEvent,
    *,
    env: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> StatusAuthGateResult:
    if not status_auth_enabled(instance_name=event.instance, env=env):
        return StatusAuthGateResult(True, event.account_id)
    account_id = event.account_id or account_store.get_account_for_identity(event.identity_key) or ""
    if account_id and status_auth_state_authorized(account_store, account_id):
        return StatusAuthGateResult(True, account_id)
    if not text_contains_status_auth_code(event.text, instance_name=event.instance, env=env):
        return StatusAuthGateResult(False, account_id, reason="unauthorized")
    if not _is_private_chat_type(event.chat_type):
        return StatusAuthGateResult(False, account_id, reason="non_private_auth_attempt")
    account_id = account_store.resolve_or_create_account(event.identity_key, display_label=event.sender_name)
    if event.chat_id:
        account_store.update_identity_route(
            event.identity_key,
            channel=event.channel,
            chat_id=event.chat_id,
            chat_type=_normalize_chat_type(event.chat_type),
            adapter_slot=event.adapter_slot,
        )
    authorize_status_recipient(account_store, account_id, event, now=now)
    return StatusAuthGateResult(False, account_id, action_text=STATUS_AUTH_CONFIRMATION_TEXT, reason="authorized")


def authorize_status_recipient(
    account_store: AccountStore,
    account_id: str,
    event: IncomingEvent,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")
    try:
        current = _normalize_status_auth_state(account_store.read_status_auth_state(account_id))
    except (AccountStoreError, OSError, ValueError):
        current = {}
    state = dict(current)
    state.update(
        {
            "schema_version": 1,
            "authorized": True,
            "authorized_at": state.get("authorized_at") or timestamp,
            "updated_at": timestamp,
            "source": "runtime_code",
            "last_identity_key": event.identity_key,
            "last_channel": event.channel,
            "last_chat_id": event.chat_id,
            "last_chat_type": event.chat_type,
            "last_adapter_slot": event.adapter_slot,
        }
    )
    account_store.write_status_auth_state(account_id, state)
    return state


def _status_auth_env_names(instance_name: str) -> tuple[tuple[str, bool], ...]:
    instance_token = _env_instance_token(instance_name)
    names: list[tuple[str, bool]] = []
    if instance_token:
        names.extend(
            [
                (f"{STATUS_AUTH_CODE_INSTANCE_ENV_PREFIX}{instance_token}", False),
                (f"{STATUS_AUTH_CODES_INSTANCE_ENV_PREFIX}{instance_token}", True),
            ]
        )
    names.extend([(STATUS_AUTH_CODE_ENV, False), (STATUS_AUTH_CODES_ENV, True)])
    return tuple(names)


def _env_instance_token(instance_name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", str(instance_name or "").strip().upper()).strip("_")


def _normalize_chat_type(chat_type: Any) -> str:
    return str(chat_type or "").strip().casefold()


def _is_private_chat_type(chat_type: Any) -> bool:
    return _normalize_chat_type(chat_type) == "private"
