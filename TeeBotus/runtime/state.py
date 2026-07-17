from __future__ import annotations

import json
import os
import stat
import threading
import time
from copy import deepcopy
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Literal, Mapping

try:
    import fcntl
except ImportError:  # pragma: no cover - fcntl is unavailable on non-POSIX platforms.
    fcntl = None  # type: ignore[assignment]

from TeeBotus.runtime.accounts import (
    ACCOUNTS_DIRNAME,
    ACCOUNT_MEMORY_LOCK_FILENAME,
    AccountStore,
    AccountStoreError,
    account_memory_lock_for_root,
    EncryptedJsonVault,
    InstanceSecretProvider,
    LLM_STATE_FILENAME,
    OPENAI_STATE_FILENAME,
    SecretToolInstanceSecretProvider,
    utc_now,
    validate_sha512_token,
)
from TeeBotus.runtime.maintenance import (
    _has_symlink_parent,
    _open_append_text_no_follow,
    maintain_runtime_directory,
    rotate_runtime_text_file_if_needed,
)

FlowType = Literal["teladi_emergency", "memory_reset", "youtube_options", "account_edit", "link_wtf"] | str
PendingFlowStateKey = tuple[str, str, str] | tuple[str, str, str, str]
LINK_NOTIFICATIONS_FILENAME = "Link_Notifications.json"
LINK_NOTIFICATION_TTL_SECONDS = 15 * 60
PENDING_FLOW_TTL_SECONDS = 30 * 60
SECURITY_EVENTS_LOCK_FILENAME = ".Security_Events.jsonl.lock"
PREVIOUS_RESPONSE_PROVIDER_FIELD = "previous_response_provider"
PREVIOUS_RESPONSE_MODEL_FIELD = "previous_response_model"
PREVIOUS_RESPONSE_KEY_FIELD = "previous_response_key_fingerprint"
PREVIOUS_RESPONSE_CONVERSATIONS_FIELD = "previous_response_conversations"
LINK_NOTIFICATIONS_LOCK_FILENAME = ".Link_Notifications.json.lock"

_RUNTIME_FILE_THREAD_LOCK = threading.RLock()
_RUNTIME_FILE_LOCK_STATE = threading.local()
_PENDING_FLOW_LOCK = threading.RLock()


@dataclass(frozen=True)
class PendingFlow:
    instance: str
    account_id: str
    flow_type: str
    chat_id: str
    channel: str
    payload: dict[str, Any] = field(default_factory=dict)
    conversation_scope: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "instance": self.instance,
            "account_id": self.account_id,
            "flow_type": self.flow_type,
            "chat_id": self.chat_id,
            "channel": self.channel,
            "payload": deepcopy(self.payload),
        }


@dataclass(frozen=True)
class _PendingPreviousResponseReset:
    response_id: str | None
    scope: tuple[str, str, str] | None
    conversation_entries: dict[str, tuple[str | None, tuple[str, str, str] | None]] = field(default_factory=dict)


PreviousResponseStateKey = tuple[str, str] | tuple[str, str, str]


def _clean_conversation_scope(conversation_scope: str = "") -> str:
    return str(conversation_scope or "").strip()


def pending_flow_scope(
    *,
    channel: str,
    adapter_slot: int | str,
    chat_type: str,
    chat_id: str,
    identity_key: str,
) -> str:
    """Build stable in-memory scope for interactive flows."""
    return json.dumps(
        [
            str(channel or "").strip().casefold(),
            str(adapter_slot or "").strip(),
            str(chat_type or "").strip().casefold(),
            str(chat_id or "").strip(),
            str(identity_key or "").strip(),
        ],
        ensure_ascii=True,
        separators=(",", ":"),
    )


def _previous_response_entry_from_mapping(
    payload: Mapping[str, Any],
    *,
    error_prefix: str,
) -> tuple[str | None, tuple[str, str, str] | None, str]:
    value = str(payload.get("previous_response_id") or "").strip()
    provider = str(payload.get(PREVIOUS_RESPONSE_PROVIDER_FIELD) or "").strip().casefold()
    model = str(payload.get(PREVIOUS_RESPONSE_MODEL_FIELD) or "").strip()
    key_fingerprint = str(payload.get(PREVIOUS_RESPONSE_KEY_FIELD) or "").strip().casefold()
    scope_fields_present = any(
        field_name in payload
        for field_name in (PREVIOUS_RESPONSE_PROVIDER_FIELD, PREVIOUS_RESPONSE_MODEL_FIELD, PREVIOUS_RESPONSE_KEY_FIELD)
    )
    if value and scope_fields_present and (not provider or not model):
        return None, None, f"{error_prefix} scope is incomplete"
    scope = (provider, model, key_fingerprint) if provider and model else None
    return value or None, scope, ""


def _set_persisted_previous_response_fields(
    payload: dict[str, Any],
    response_id: str,
    *,
    provider: str = "",
    model: str = "",
    key_fingerprint: str = "",
) -> None:
    payload["previous_response_id"] = str(response_id or "").strip()
    clean_provider = str(provider or "").strip().casefold()
    clean_model = str(model or "").strip()
    clean_key_fingerprint = str(key_fingerprint or "").strip().casefold()
    if clean_provider and clean_model:
        payload[PREVIOUS_RESPONSE_PROVIDER_FIELD] = clean_provider
        payload[PREVIOUS_RESPONSE_MODEL_FIELD] = clean_model
        if clean_key_fingerprint:
            payload[PREVIOUS_RESPONSE_KEY_FIELD] = clean_key_fingerprint
        else:
            payload.pop(PREVIOUS_RESPONSE_KEY_FIELD, None)
    else:
        payload.pop(PREVIOUS_RESPONSE_PROVIDER_FIELD, None)
        payload.pop(PREVIOUS_RESPONSE_MODEL_FIELD, None)
        payload.pop(PREVIOUS_RESPONSE_KEY_FIELD, None)


def _clear_persisted_previous_response_fields(payload: dict[str, Any]) -> None:
    for field_name in (
        "previous_response_id",
        PREVIOUS_RESPONSE_PROVIDER_FIELD,
        PREVIOUS_RESPONSE_MODEL_FIELD,
        PREVIOUS_RESPONSE_KEY_FIELD,
    ):
        payload.pop(field_name, None)


@dataclass
class RuntimeState:
    """Small in-memory state container for pending account-scoped flows."""

    pending_flows: dict[PendingFlowStateKey, dict[str, Any]] = field(default_factory=dict)
    pending_flow_created_at: dict[PendingFlowStateKey, float] = field(default_factory=dict)
    link_notifications: dict[tuple[str, str, str], dict[str, str]] = field(default_factory=dict)
    previous_response_ids: dict[PreviousResponseStateKey, str] = field(default_factory=dict)
    previous_response_scopes: dict[PreviousResponseStateKey, tuple[str, str, str]] = field(default_factory=dict)
    pending_previous_response_resets: dict[PreviousResponseStateKey, _PendingPreviousResponseReset] = field(default_factory=dict)
    security_events: list[dict[str, Any]] = field(default_factory=list)
    security_events_persistence_error: str = ""

    def _pending_flow_key(
        self,
        instance_name: str,
        account_id: str,
        flow_type: str,
        conversation_scope: str = "",
    ) -> PendingFlowStateKey:
        clean_scope = str(conversation_scope or "").strip()
        if clean_scope:
            return (instance_name, account_id, flow_type, clean_scope)
        return (instance_name, account_id, flow_type)

    def _pending_flow_lookup_key(
        self,
        instance_name: str,
        account_id: str,
        flow_type: str,
        conversation_scope: str = "",
    ) -> PendingFlowStateKey:
        key = self._pending_flow_key(instance_name, account_id, flow_type, conversation_scope)
        if key in self.pending_flows:
            return key
        if len(key) == 4:
            legacy_key = key[:3]
            if legacy_key in self.pending_flows:
                return legacy_key
            return key
        scoped_keys = [candidate for candidate in self.pending_flows if len(candidate) == 4 and candidate[:3] == key]
        return scoped_keys[0] if len(scoped_keys) == 1 else key

    def set_pending_flow(
        self,
        instance_name: str,
        account_id: str,
        flow_type: str,
        payload: dict[str, Any],
        *,
        conversation_scope: str = "",
    ) -> None:
        key = self._pending_flow_key(instance_name, account_id, flow_type, conversation_scope)
        self.pending_flows[key] = deepcopy(payload)
        self.pending_flow_created_at[key] = time.time()

    def pop_pending_flow(
        self,
        instance_name: str,
        account_id: str,
        flow_type: str,
        *,
        conversation_scope: str = "",
    ) -> dict[str, Any] | None:
        self._purge_expired_pending_flows()
        key = self._pending_flow_lookup_key(instance_name, account_id, flow_type, conversation_scope)
        self.pending_flow_created_at.pop(key, None)
        return self.pending_flows.pop(key, None)

    def get_pending_flow(
        self,
        instance_name: str,
        account_id: str,
        flow_type: str,
        *,
        conversation_scope: str = "",
    ) -> dict[str, Any] | None:
        self._purge_expired_pending_flows()
        key = self._pending_flow_lookup_key(instance_name, account_id, flow_type, conversation_scope)
        payload = self.pending_flows.get(key)
        return deepcopy(payload) if payload is not None else None

    def _purge_expired_pending_flows(self) -> None:
        now = time.time()
        for key, created_at in list(self.pending_flow_created_at.items()):
            if created_at <= 0 or now - created_at > PENDING_FLOW_TTL_SECONDS:
                self.pending_flow_created_at.pop(key, None)
                self.pending_flows.pop(key, None)

    def _previous_response_key(
        self,
        instance_name: str,
        account_id: str,
        conversation_scope: str = "",
    ) -> PreviousResponseStateKey:
        clean_scope = _clean_conversation_scope(conversation_scope)
        if clean_scope:
            return (instance_name, account_id, clean_scope)
        return (instance_name, account_id)

    def _current_previous_response_state(
        self,
        instance_name: str,
        account_id: str,
        conversation_scope: str = "",
    ) -> tuple[str | None, tuple[str, str, str] | None]:
        key = self._previous_response_key(instance_name, account_id, conversation_scope)
        return self.previous_response_ids.get(key), self.previous_response_scopes.get(key)

    def _iter_previous_response_states_for_account(
        self,
        instance_name: str,
        account_id: str,
    ) -> list[tuple[str, str, tuple[str, str, str] | None]]:
        prefix = (instance_name, account_id)
        result: list[tuple[str, str, tuple[str, str, str] | None]] = []
        for key, response_id in self.previous_response_ids.items():
            if key[:2] != prefix:
                continue
            conversation_scope = key[2] if len(key) == 3 else ""
            result.append((conversation_scope, response_id, self.previous_response_scopes.get(key)))
        result.sort(key=lambda item: (item[0] != "", item[0]))
        return result

    def _clear_previous_response_state(
        self,
        instance_name: str,
        account_id: str,
        conversation_scope: str = "",
    ) -> None:
        clean_scope = _clean_conversation_scope(conversation_scope)
        if clean_scope:
            key = (instance_name, account_id, clean_scope)
            self.previous_response_ids.pop(key, None)
            self.previous_response_scopes.pop(key, None)
            return
        prefix = (instance_name, account_id)
        for key in list(self.previous_response_ids):
            if key[:2] == prefix:
                self.previous_response_ids.pop(key, None)
        for key in list(self.previous_response_scopes):
            if key[:2] == prefix:
                self.previous_response_scopes.pop(key, None)

    def set_previous_response_id(
        self,
        instance_name: str,
        account_id: str,
        response_id: str | None,
        *,
        provider: str = "",
        model: str = "",
        key_fingerprint: str = "",
        conversation_scope: str = "",
    ) -> None:
        key = self._previous_response_key(instance_name, account_id, conversation_scope)
        clean_response_id = str(response_id or "").strip()
        if clean_response_id:
            self.previous_response_ids[key] = clean_response_id
            clean_provider = str(provider or "").strip().casefold()
            clean_model = str(model or "").strip()
            clean_key_fingerprint = str(key_fingerprint or "").strip().casefold()
            if clean_provider and clean_model:
                self.previous_response_scopes[key] = (clean_provider, clean_model, clean_key_fingerprint)
            else:
                # An unscoped ID is retained for backwards-compatible direct
                # callers, but a provider-aware lookup must reject it.
                self.previous_response_scopes.pop(key, None)
        else:
            self.previous_response_ids.pop(key, None)
            self.previous_response_scopes.pop(key, None)

    def get_previous_response_id(
        self,
        instance_name: str,
        account_id: str,
        *,
        provider: str = "",
        model: str = "",
        key_fingerprint: str = "",
        conversation_scope: str = "",
    ) -> str | None:
        key = self._previous_response_key(instance_name, account_id, conversation_scope)
        response_id = self.previous_response_ids.get(key)
        if not response_id:
            return None
        clean_provider = str(provider or "").strip().casefold()
        clean_model = str(model or "").strip()
        clean_key_fingerprint = str(key_fingerprint or "").strip().casefold()
        if clean_provider or clean_model or clean_key_fingerprint:
            stored_scope = self.previous_response_scopes.get(key)
            if stored_scope is None:
                return None
            if clean_provider and stored_scope[0] != clean_provider:
                return None
            if clean_model and stored_scope[1] != clean_model:
                return None
            if stored_scope[2] != clean_key_fingerprint:
                return None
        return response_id

    def reset_previous_response_id(self, instance_name: str, account_id: str, *, conversation_scope: str = "") -> None:
        self._clear_previous_response_state(instance_name, account_id, conversation_scope)

    def record_link_notification(self, *, instance_name: str, account_id: str, new_identity_key: str, old_identity_key: str) -> None:
        self.link_notifications[(instance_name, account_id, old_identity_key)] = {
            "new_identity_key": new_identity_key,
            "old_identity_key": old_identity_key,
            "created_at": str(time.time()),
        }

    def pop_link_notification(self, *, instance_name: str, account_id: str, old_identity_key: str = "") -> dict[str, str] | None:
        self._purge_expired_link_notifications()
        if old_identity_key:
            return self.link_notifications.pop((instance_name, account_id, old_identity_key), None)
        prefix = (instance_name, account_id)
        for key in list(self.link_notifications):
            if key[:2] == prefix:
                return self.link_notifications.pop(key)
        return None

    def list_link_notifications(self, *, instance_name: str, account_id: str) -> list[dict[str, str]]:
        self._purge_expired_link_notifications()
        prefix = (instance_name, account_id)
        return [dict(payload) for key, payload in self.link_notifications.items() if key[:2] == prefix]

    def clear_link_notifications_for_new_identity(self, *, instance_name: str, account_id: str, new_identity_key: str) -> int:
        prefix = (instance_name, account_id)
        removed = 0
        for key, payload in list(self.link_notifications.items()):
            if key[:2] == prefix and payload.get("new_identity_key") == new_identity_key:
                self.link_notifications.pop(key, None)
                removed += 1
        return removed

    def _purge_expired_link_notifications(self) -> None:
        now = time.time()
        for key, payload in list(self.link_notifications.items()):
            try:
                created_at = float(payload.get("created_at", "0"))
            except (TypeError, ValueError):
                created_at = 0.0
            if created_at <= 0 or now - created_at > LINK_NOTIFICATION_TTL_SECONDS:
                self.link_notifications.pop(key, None)

    def append_security_event(self, event: dict[str, Any]) -> None:
        self.security_events.append(dict(event))


class RuntimeStateStore(RuntimeState):
    """File-backed compatible state API used by the integration scaffold.

    Security events are JSONL plaintext metadata. Link notifications are identity
    mappings, so they are persisted through the same encrypted instance vault used for
    account identity mapping. Pending conversational flows remain runtime-scoped.
    """

    def __init__(
        self,
        instance_dir: Path,
        *,
        instance_name: str = "",
        secret_provider: InstanceSecretProvider | None = None,
    ) -> None:
        super().__init__()
        self.instance_dir = Path(instance_dir)
        if self.instance_dir.name == "data":
            self.runtime_dir = self.instance_dir / "runtime"
            inferred_instance_dir = self.instance_dir.parent
        elif self.instance_dir.name == "runtime":
            self.runtime_dir = self.instance_dir
            inferred_instance_dir = self.instance_dir.parent.parent if self.instance_dir.parent.name == "data" else self.instance_dir.parent
        elif self.instance_dir.is_dir():
            self.runtime_dir = self.instance_dir / "data" / "runtime"
            inferred_instance_dir = self.instance_dir
        elif self.instance_dir.suffix:
            self.runtime_dir = self.instance_dir.parent
            inferred_instance_dir = self.runtime_dir.parent.parent if self.runtime_dir.name == "runtime" else self.runtime_dir.parent
        else:
            self.runtime_dir = self.instance_dir / "data" / "runtime"
            inferred_instance_dir = self.instance_dir
        if _has_symlink_parent(self.runtime_dir) or self.runtime_dir.is_symlink():
            raise AccountStoreError(f"refusing unsafe runtime directory: {self.runtime_dir}")
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.instance_name = instance_name or inferred_instance_dir.name
        self.secret_provider = secret_provider
        self.security_events_path = self.runtime_dir / "Security_Events.jsonl"
        self.link_notifications_path = self.runtime_dir / LINK_NOTIFICATIONS_FILENAME
        self.accounts_root = self.runtime_dir.parent / "accounts"
        self.link_notifications_persistence_error = ""
        self.llm_state_persistence_error = ""
        self.openai_state_persistence_error = ""
        self._llm_state_persistence_errors: dict[str, str] = {}
        self._account_store_secret_guard_checked = False
        self._account_store_secret_guard_provider: object | None = None
        self._llm_account_store: AccountStore | None = None
        self._llm_account_store_secret_provider: object | None = None
        with self._link_notifications_lock():
            self._load_persisted_link_notifications()

    @contextmanager
    def _runtime_file_lock(self, lock_filename: str) -> Iterator[None]:
        lock_path = self.runtime_dir / lock_filename
        if _has_symlink_parent(lock_path) or lock_path.is_symlink():
            raise AccountStoreError(f"refusing unsafe runtime lock path: {lock_path}")
        with _RUNTIME_FILE_THREAD_LOCK:
            held_paths = getattr(_RUNTIME_FILE_LOCK_STATE, "paths", None)
            if held_paths is None:
                held_paths = set()
                _RUNTIME_FILE_LOCK_STATE.paths = held_paths
            lock_key = os.path.realpath(os.fspath(lock_path))
            if lock_key in held_paths:
                yield
                return
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            try:
                file_descriptor = os.open(lock_path, flags, 0o600)
            except OSError as exc:
                raise AccountStoreError(f"could not open runtime lock path: {lock_path}") from exc
            with os.fdopen(file_descriptor, "a+b") as handle:
                try:
                    os.fchmod(handle.fileno(), stat.S_IRUSR | stat.S_IWUSR)
                except OSError:
                    pass
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                held_paths.add(lock_key)
                try:
                    yield
                finally:
                    held_paths.discard(lock_key)
                    if fcntl is not None:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            if not held_paths:
                del _RUNTIME_FILE_LOCK_STATE.paths

    @contextmanager
    def _link_notifications_lock(self) -> Iterator[None]:
        with self._runtime_file_lock(LINK_NOTIFICATIONS_LOCK_FILENAME):
            yield

    @contextmanager
    def _security_events_lock(self) -> Iterator[None]:
        with self._runtime_file_lock(SECURITY_EVENTS_LOCK_FILENAME):
            yield

    @property
    def _link_vault(self) -> EncryptedJsonVault:
        if self.secret_provider is None:
            raise AccountStoreError("link-notification persistence has no secret provider")
        if _has_symlink_parent(self.link_notifications_path):
            raise AccountStoreError(f"refusing unsafe link-notification path: {self.link_notifications_path}")
        try:
            link_stat = os.stat(self.link_notifications_path, follow_symlinks=False)
        except FileNotFoundError:
            link_stat = None
        except OSError as exc:
            raise AccountStoreError(f"could not inspect link-notification path: {self.link_notifications_path}") from exc
        if link_stat is not None and (stat.S_ISLNK(link_stat.st_mode) or link_stat.st_nlink > 1):
            raise AccountStoreError(f"refusing unsafe link-notification path: {self.link_notifications_path}")
        if link_stat is not None and stat.S_ISREG(link_stat.st_mode):
            try:
                os.chmod(self.link_notifications_path, stat.S_IRUSR | stat.S_IWUSR)
            except OSError as exc:
                raise AccountStoreError(f"could not secure link-notification path: {self.link_notifications_path}") from exc
        self._guard_account_store_secrets()
        return EncryptedJsonVault(self.instance_name, self.secret_provider, root=self.runtime_dir)

    def _guard_account_store_secrets(self) -> None:
        if self._account_store_secret_guard_checked and self._account_store_secret_guard_provider is self.secret_provider:
            return
        if isinstance(self.secret_provider, SecretToolInstanceSecretProvider):
            self._account_store_for_llm_state()
        self._account_store_secret_guard_checked = True
        self._account_store_secret_guard_provider = self.secret_provider

    def _account_store_for_llm_state(self) -> AccountStore:
        if self.secret_provider is None:
            raise AccountStoreError("LLM state persistence has no secret provider")
        self._ensure_safe_accounts_root()
        if self._llm_account_store is None or self._llm_account_store_secret_provider is not self.secret_provider:
            self._llm_account_store = AccountStore(
                self.accounts_root,
                self.instance_name,
                self.secret_provider,
                create_dirs=False,
            )
            self._llm_account_store_secret_provider = self.secret_provider
        return self._llm_account_store

    def _ensure_safe_accounts_root(self) -> None:
        for root in (self.accounts_root, self.accounts_root / ACCOUNTS_DIRNAME):
            if _has_symlink_parent(root) or root.is_symlink():
                raise AccountStoreError(f"refusing unsafe account state root: {root}")

    def set_pending_flow(self, *args, **kwargs) -> None:  # type: ignore[override]
        if len(args) == 1 and isinstance(args[0], PendingFlow):
            flow = args[0]
            self._ensure_instance_scope(flow.instance)
            with _PENDING_FLOW_LOCK:
                super().set_pending_flow(
                    flow.instance,
                    flow.account_id,
                    flow.flow_type,
                    flow.as_dict(),
                    conversation_scope=flow.conversation_scope,
                )
            return
        instance_name = args[0] if args else kwargs.get("instance_name", "")
        self._ensure_instance_scope(instance_name)
        with _PENDING_FLOW_LOCK:
            return super().set_pending_flow(*args, **kwargs)

    def pop_pending_flow(
        self,
        instance_name: str,
        account_id: str,
        flow_type: str,
        *,
        conversation_scope: str = "",
    ) -> dict[str, Any] | None:
        self._ensure_instance_scope(instance_name)
        with _PENDING_FLOW_LOCK:
            return super().pop_pending_flow(instance_name, account_id, flow_type, conversation_scope=conversation_scope)

    def get_pending_flow(
        self,
        instance_name: str,
        account_id: str,
        flow_type: str,
        *,
        conversation_scope: str = "",
    ) -> dict[str, Any] | None:
        self._ensure_instance_scope(instance_name)
        with _PENDING_FLOW_LOCK:
            return super().get_pending_flow(instance_name, account_id, flow_type, conversation_scope=conversation_scope)

    def set_previous_response_id(
        self,
        instance_name: str,
        account_id: str,
        response_id: str | None,
        *,
        provider: str = "",
        model: str = "",
        key_fingerprint: str = "",
        conversation_scope: str = "",
    ) -> None:
        self._ensure_instance_scope(instance_name)
        with self._llm_state_lock(account_id):
            key = self._previous_response_key(instance_name, account_id, conversation_scope)
            previous_response_id, previous_response_scope = self._current_previous_response_state(
                instance_name,
                account_id,
                conversation_scope,
            )
            super().set_previous_response_id(
                instance_name,
                account_id,
                response_id,
                provider=provider,
                model=model,
                key_fingerprint=key_fingerprint,
                conversation_scope=conversation_scope,
            )
            if str(response_id or "").strip():
                persisted = self._write_llm_previous_response_id(
                    account_id,
                    response_id,
                    provider=provider,
                    model=model,
                    key_fingerprint=key_fingerprint,
                    conversation_scope=conversation_scope,
                )
                if persisted:
                    self.pending_previous_response_resets.pop(key, None)
                else:
                    self.pending_previous_response_resets.setdefault(
                        key,
                        _PendingPreviousResponseReset(previous_response_id, previous_response_scope),
                    )
            else:
                previous_conversation_entries = (
                    dict(self._previous_response_snapshot_for_account(instance_name, account_id)[2])
                    if not _clean_conversation_scope(conversation_scope)
                    else {}
                )
                self.pending_previous_response_resets.setdefault(
                    key,
                    _PendingPreviousResponseReset(previous_response_id, previous_response_scope, previous_conversation_entries),
                )
                if self._clear_llm_previous_response_id(account_id, conversation_scope=conversation_scope):
                    self.pending_previous_response_resets.pop(key, None)

    def get_previous_response_id(
        self,
        instance_name: str,
        account_id: str,
        *,
        provider: str = "",
        model: str = "",
        key_fingerprint: str = "",
        conversation_scope: str = "",
    ) -> str | None:
        self._ensure_instance_scope(instance_name)
        key = self._previous_response_key(instance_name, account_id, conversation_scope)
        account_reset_key = self._previous_response_key(instance_name, account_id)
        with self._llm_state_lock(account_id):
            persisted, persisted_scope, _legacy_fallback_used, persistence_error = self._read_llm_previous_response(
                account_id,
                conversation_scope=conversation_scope,
            )
            if persistence_error:
                if account_reset_key in self.pending_previous_response_resets and self._clear_llm_previous_response_id(account_id):
                    self._clear_pending_previous_response_resets(instance_name, account_id)
                    super().reset_previous_response_id(instance_name, account_id)
                    return None
                if key in self.pending_previous_response_resets and self._clear_llm_previous_response_id(
                    account_id,
                    conversation_scope=conversation_scope,
                ):
                    self.pending_previous_response_resets.pop(key, None)
                    super().reset_previous_response_id(instance_name, account_id, conversation_scope=conversation_scope)
                    return None
                return super().get_previous_response_id(
                    instance_name,
                    account_id,
                    provider=provider,
                    model=model,
                    key_fingerprint=key_fingerprint,
                    conversation_scope=conversation_scope,
                )
            if account_reset_key in self.pending_previous_response_resets:
                account_pending_reset = self.pending_previous_response_resets[account_reset_key]
                persisted_snapshot = self._read_llm_previous_response_snapshot(account_id)
                if not persisted_snapshot[3] and self._recover_account_previous_response_after_reset(
                    instance_name,
                    account_id,
                    pending_reset=account_pending_reset,
                    persisted_snapshot=persisted_snapshot,
                ):
                    self._clear_pending_previous_response_resets(instance_name, account_id)
                    return super().get_previous_response_id(
                        instance_name,
                        account_id,
                        provider=provider,
                        model=model,
                        key_fingerprint=key_fingerprint,
                        conversation_scope=conversation_scope,
                    )
                if not persisted_snapshot[3]:
                    self.pending_previous_response_resets.pop(account_reset_key, None)
            if key in self.pending_previous_response_resets:
                pending_reset = self.pending_previous_response_resets[key]
                stale_response_id = pending_reset.response_id
                stale_scope = pending_reset.scope
                current_response_id, current_scope = self._current_previous_response_state(
                    instance_name,
                    account_id,
                    conversation_scope,
                )
                persisted_matches_stale = (
                    (persisted is None and stale_response_id is None)
                    or (persisted == stale_response_id and persisted_scope == stale_scope)
                )
                if current_response_id and (
                    current_response_id != stale_response_id
                    or current_scope != stale_scope
                    or not persisted
                ) and (not persisted or persisted_matches_stale):
                    persisted_current = self._write_llm_previous_response_id(
                        account_id,
                        current_response_id,
                        provider=current_scope[0] if current_scope else "",
                        model=current_scope[1] if current_scope else "",
                        key_fingerprint=current_scope[2] if current_scope else "",
                        conversation_scope=conversation_scope,
                    )
                    if persisted_current:
                        self.pending_previous_response_resets.pop(key, None)
                    return super().get_previous_response_id(
                        instance_name,
                        account_id,
                        provider=provider,
                        model=model,
                        key_fingerprint=key_fingerprint,
                        conversation_scope=conversation_scope,
                    )
                if current_response_id and current_response_id == stale_response_id and persisted_matches_stale:
                    self.pending_previous_response_resets.pop(key, None)
                elif persisted_matches_stale:
                    if self._clear_llm_previous_response_id(account_id, conversation_scope=conversation_scope):
                        self.pending_previous_response_resets.pop(key, None)
                        self._clear_previous_response_state(instance_name, account_id, conversation_scope)
                        return None
                else:
                    self.pending_previous_response_resets.pop(key, None)
            if persisted:
                self.previous_response_ids[key] = persisted
                if persisted_scope is not None:
                    self.previous_response_scopes[key] = persisted_scope
                else:
                    self.previous_response_scopes.pop(key, None)
                return super().get_previous_response_id(
                    instance_name,
                    account_id,
                    provider=provider,
                    model=model,
                    key_fingerprint=key_fingerprint,
                    conversation_scope=conversation_scope,
                )
            self._clear_previous_response_state(instance_name, account_id, conversation_scope)
            return None

    def reset_previous_response_id(self, instance_name: str, account_id: str, *, conversation_scope: str = "") -> None:
        self._ensure_instance_scope(instance_name)
        with self._llm_state_lock(account_id):
            key = self._previous_response_key(instance_name, account_id, conversation_scope)
            if key not in self.pending_previous_response_resets:
                persisted, persisted_scope, _legacy_fallback_used, persistence_error = self._read_llm_previous_response(
                    account_id,
                    conversation_scope=conversation_scope,
                )
                if persistence_error:
                    persisted, persisted_scope = self._current_previous_response_state(
                        instance_name,
                        account_id,
                        conversation_scope,
                    )
                    persisted_conversation_entries = (
                        dict(self._previous_response_snapshot_for_account(instance_name, account_id)[2])
                        if not _clean_conversation_scope(conversation_scope)
                        else {}
                    )
                else:
                    persisted_conversation_entries = (
                        self._read_llm_previous_response_snapshot(account_id)[2]
                        if not _clean_conversation_scope(conversation_scope)
                        else {}
                    )
                self.pending_previous_response_resets[key] = _PendingPreviousResponseReset(
                    persisted,
                    persisted_scope,
                    persisted_conversation_entries,
                )
            super().reset_previous_response_id(instance_name, account_id, conversation_scope=conversation_scope)
            if self._clear_llm_previous_response_id(account_id, conversation_scope=conversation_scope):
                self.pending_previous_response_resets.pop(key, None)

    def _clear_pending_previous_response_resets(
        self,
        instance_name: str,
        account_id: str,
        conversation_scope: str = "",
    ) -> None:
        clean_scope = _clean_conversation_scope(conversation_scope)
        if clean_scope:
            self.pending_previous_response_resets.pop((instance_name, account_id, clean_scope), None)
            return
        prefix = (instance_name, account_id)
        for key in list(self.pending_previous_response_resets):
            if key[:2] == prefix:
                self.pending_previous_response_resets.pop(key, None)

    def _previous_response_snapshot_for_account(
        self,
        instance_name: str,
        account_id: str,
    ) -> tuple[str | None, tuple[str, str, str] | None, dict[str, tuple[str | None, tuple[str, str, str] | None]]]:
        top_response_id, top_scope = self._current_previous_response_state(instance_name, account_id)
        conversation_entries = {
            conversation_scope: (response_id, response_scope)
            for conversation_scope, response_id, response_scope in self._iter_previous_response_states_for_account(instance_name, account_id)
            if conversation_scope
        }
        return top_response_id, top_scope, conversation_entries

    def _recover_account_previous_response_after_reset(
        self,
        instance_name: str,
        account_id: str,
        *,
        pending_reset: _PendingPreviousResponseReset,
        persisted_snapshot: tuple[
            str | None,
            tuple[str, str, str] | None,
            dict[str, tuple[str | None, tuple[str, str, str] | None]],
            str,
        ],
    ) -> bool:
        current_top_response_id, current_top_scope, current_conversation_entries = self._previous_response_snapshot_for_account(
            instance_name,
            account_id,
        )
        persisted_response_id, persisted_scope, persisted_conversation_entries, _persistence_error = persisted_snapshot
        persisted_matches_stale = (
            persisted_response_id == pending_reset.response_id
            and persisted_scope == pending_reset.scope
            and persisted_conversation_entries == pending_reset.conversation_entries
        )
        persisted_has_data = self._previous_response_snapshot_has_data(
            persisted_response_id,
            persisted_scope,
            persisted_conversation_entries,
        )
        current_has_local_data = self._previous_response_snapshot_has_data(
            current_top_response_id,
            current_top_scope,
            current_conversation_entries,
        )
        if not current_has_local_data:
            if persisted_has_data and not persisted_matches_stale:
                return False
            return self._clear_llm_previous_response_id(account_id)
        if persisted_has_data and not persisted_matches_stale:
            return False
        if not self._clear_llm_previous_response_id(account_id):
            return False
        current_entries = self._iter_previous_response_states_for_account(instance_name, account_id)
        for conversation_scope, response_id, response_scope in current_entries:
            if not self._write_llm_previous_response_id(
                account_id,
                response_id,
                provider=response_scope[0] if response_scope else "",
                model=response_scope[1] if response_scope else "",
                key_fingerprint=response_scope[2] if response_scope else "",
                conversation_scope=conversation_scope,
            ):
                return False
        return True

    def _previous_response_snapshot_has_data(
        self,
        response_id: str | None,
        response_scope: tuple[str, str, str] | None,
        conversation_entries: Mapping[str, tuple[str | None, tuple[str, str, str] | None]],
    ) -> bool:
        # Provider metadata without response ID is orphaned state, not a live
        # conversation. Reset must be able to remove it after persistence
        # recovers.
        if response_id:
            return True
        return bool(conversation_entries)

    def _ensure_instance_scope(self, instance_name: str) -> None:
        expected = str(self.instance_name or "").strip()
        actual = str(instance_name or "").strip()
        if expected and actual != expected:
            raise AccountStoreError(
                f"runtime state instance mismatch: expected={expected} actual={actual}"
            )

    def record_link_notification(self, *, instance_name: str, account_id: str, new_identity_key: str, old_identity_key: str) -> None:
        self._ensure_instance_scope(instance_name)
        try:
            with self._link_notifications_lock():
                self._refresh_persisted_link_notifications()
                super().record_link_notification(
                    instance_name=instance_name,
                    account_id=account_id,
                    new_identity_key=new_identity_key,
                    old_identity_key=old_identity_key,
                )
                self._save_link_notifications()
        except (AccountStoreError, OSError, RuntimeError, TypeError, ValueError) as exc:
            self.link_notifications_persistence_error = str(exc)
            raise

    def pop_link_notification(self, *, instance_name: str, account_id: str, old_identity_key: str = "") -> dict[str, str] | None:
        self._ensure_instance_scope(instance_name)
        try:
            with self._link_notifications_lock():
                self._refresh_persisted_link_notifications()
                notification = super().pop_link_notification(
                    instance_name=instance_name,
                    account_id=account_id,
                    old_identity_key=old_identity_key,
                )
                if notification is not None:
                    self._save_link_notifications()
                return notification
        except (AccountStoreError, OSError, RuntimeError, TypeError, ValueError) as exc:
            self.link_notifications_persistence_error = str(exc)
            raise

    def clear_link_notifications_for_new_identity(self, *, instance_name: str, account_id: str, new_identity_key: str) -> int:
        self._ensure_instance_scope(instance_name)
        try:
            with self._link_notifications_lock():
                self._refresh_persisted_link_notifications()
                removed = super().clear_link_notifications_for_new_identity(
                    instance_name=instance_name,
                    account_id=account_id,
                    new_identity_key=new_identity_key,
                )
                if removed:
                    self._save_link_notifications()
                return removed
        except (AccountStoreError, OSError, RuntimeError, TypeError, ValueError) as exc:
            self.link_notifications_persistence_error = str(exc)
            raise

    def _purge_expired_link_notifications(self) -> None:
        before = len(self.link_notifications)
        super()._purge_expired_link_notifications()
        if len(self.link_notifications) != before and hasattr(self, "link_notifications_path"):
            self._save_link_notifications()

    def list_link_notifications(self, *, instance_name: str, account_id: str) -> list[dict[str, str]]:
        self._ensure_instance_scope(instance_name)
        try:
            with self._link_notifications_lock():
                self._refresh_persisted_link_notifications()
                return super().list_link_notifications(instance_name=instance_name, account_id=account_id)
        except (AccountStoreError, OSError, RuntimeError, TypeError, ValueError) as exc:
            self.link_notifications_persistence_error = str(exc)
            raise

    def append_security_event(self, event: dict[str, Any]) -> None:
        try:
            with self._security_events_lock():
                try:
                    serialized_event = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
                    try:
                        security_stat = os.stat(self.security_events_path, follow_symlinks=False)
                    except FileNotFoundError:
                        security_stat = None
                    except OSError as exc:
                        raise AccountStoreError(f"could not inspect security event path: {self.security_events_path}") from exc
                    if security_stat is not None and (stat.S_ISLNK(security_stat.st_mode) or security_stat.st_nlink > 1):
                        raise AccountStoreError(f"refusing unsafe security event path: {self.security_events_path}")
                    super().append_security_event(event)
                    rotate_runtime_text_file_if_needed(self.security_events_path)
                    handle = _open_append_text_no_follow(self.security_events_path)
                    if handle is None:
                        raise AccountStoreError(f"refusing unavailable or unsafe security event path: {self.security_events_path}")
                    with handle:
                        try:
                            handle_stat = os.fstat(handle.fileno())
                            if handle_stat.st_nlink > 1:
                                raise AccountStoreError(f"refusing unsafe security event path: {self.security_events_path}")
                            os.fchmod(handle.fileno(), stat.S_IRUSR | stat.S_IWUSR)
                        except OSError as exc:
                            raise AccountStoreError(f"could not secure security event path: {self.security_events_path}") from exc
                        handle.write(serialized_event)
                    maintain_runtime_directory(self.runtime_dir)
                except (AccountStoreError, OSError, RuntimeError, TypeError, ValueError) as exc:
                    self.security_events_persistence_error = str(exc)
                    raise
                self.security_events_persistence_error = ""
        except (AccountStoreError, OSError, RuntimeError, TypeError, ValueError) as exc:
            self.security_events_persistence_error = str(exc)
            raise

    def _state_path(self, account_id: str, filename: str) -> Path:
        account = validate_sha512_token(account_id, field_name="account_id")
        return self.accounts_root / ACCOUNTS_DIRNAME / account / filename

    def _llm_state_path(self, account_id: str) -> Path:
        return self._state_path(account_id, LLM_STATE_FILENAME)

    def _openai_state_path(self, account_id: str) -> Path:
        return self._state_path(account_id, OPENAI_STATE_FILENAME)

    def _set_llm_state_persistence_error(self, error: str, *, account_id: str = "") -> None:
        account = str(account_id or "").strip()
        if account:
            if error:
                self._llm_state_persistence_errors[account] = error
            else:
                self._llm_state_persistence_errors.pop(account, None)
            error = next(iter(self._llm_state_persistence_errors.values()), "")
        self.llm_state_persistence_error = error
        self.openai_state_persistence_error = error

    def _llm_state_lock(self, account_id: str):
        try:
            validate_sha512_token(account_id, field_name="account_id")
        except AccountStoreError:
            # Keep the legacy in-memory behavior for invalid IDs; the actual
            # state-path validation below still records the persistence error.
            return nullcontext()
        try:
            self._ensure_safe_accounts_root()
            account_dir = self.accounts_root / ACCOUNTS_DIRNAME / account_id
            if _has_symlink_parent(account_dir) or account_dir.is_symlink():
                raise AccountStoreError(f"refusing unsafe account state directory: {account_dir}")
            memory_lock_path = account_dir / ACCOUNT_MEMORY_LOCK_FILENAME
            try:
                memory_lock_stat = os.stat(memory_lock_path, follow_symlinks=False)
            except FileNotFoundError:
                memory_lock_stat = None
            except OSError as exc:
                raise AccountStoreError(f"could not inspect account memory lock: {memory_lock_path}") from exc
            if memory_lock_stat is not None and (stat.S_ISLNK(memory_lock_stat.st_mode) or memory_lock_stat.st_nlink > 1):
                raise AccountStoreError(f"refusing unsafe account memory lock: {memory_lock_path}")
            for filename in (LLM_STATE_FILENAME, OPENAI_STATE_FILENAME):
                state_path = account_dir / filename
                try:
                    state_stat = os.stat(state_path, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    raise AccountStoreError(f"could not inspect account state file: {state_path}") from exc
                if stat.S_ISLNK(state_stat.st_mode) or state_stat.st_nlink > 1:
                    raise AccountStoreError(f"refusing unsafe account state file: {state_path}")
                if stat.S_ISREG(state_stat.st_mode):
                    try:
                        os.chmod(state_path, stat.S_IRUSR | stat.S_IWUSR)
                    except OSError as exc:
                        raise AccountStoreError(f"could not secure account state file: {state_path}") from exc
            return account_memory_lock_for_root(self.accounts_root, account_id)
        except (AccountStoreError, OSError, RuntimeError, TypeError, ValueError) as exc:
            self._set_llm_state_persistence_error(str(exc), account_id=account_id)
            raise

    def _read_llm_state(self, account_id: str) -> tuple[dict[str, Any], str]:
        with self._llm_state_lock(account_id):
            try:
                selected = self._account_store_for_llm_state().read_llm_state(account_id)
                self._set_llm_state_persistence_error("", account_id=account_id)
                return selected, ""
            except (AccountStoreError, OSError, TypeError, ValueError) as exc:
                error = str(exc)
                self._set_llm_state_persistence_error(error, account_id=account_id)
                return {}, error

    def _write_llm_state(self, account_id: str, payload: dict[str, Any]) -> bool:
        with self._llm_state_lock(account_id):
            try:
                self._account_store_for_llm_state().write_llm_state(account_id, payload)
                self._set_llm_state_persistence_error("", account_id=account_id)
                return True
            except (AccountStoreError, OSError, TypeError, ValueError) as exc:
                self._set_llm_state_persistence_error(str(exc), account_id=account_id)
                return False

    def _read_llm_previous_response(
        self,
        account_id: str,
        *,
        conversation_scope: str = "",
    ) -> tuple[str | None, tuple[str, str, str] | None, bool, str]:
        payload, persistence_error = self._read_llm_state(account_id)
        clean_scope = _clean_conversation_scope(conversation_scope)
        if clean_scope:
            conversations_present = PREVIOUS_RESPONSE_CONVERSATIONS_FIELD in payload
            if conversations_present:
                conversations = payload.get(PREVIOUS_RESPONSE_CONVERSATIONS_FIELD)
                if not isinstance(conversations, dict):
                    error = "LLM state previous response conversations are invalid"
                    self._set_llm_state_persistence_error(error, account_id=account_id)
                    return None, None, True, error
                entry = conversations.get(clean_scope)
                if entry is None:
                    return None, None, True, persistence_error
                if not isinstance(entry, Mapping):
                    error = "LLM state previous response conversation entry is invalid"
                    self._set_llm_state_persistence_error(error, account_id=account_id)
                    return None, None, True, error
                value, scope, error = _previous_response_entry_from_mapping(
                    entry,
                    error_prefix="LLM state previous response conversation",
                )
                if error:
                    self._set_llm_state_persistence_error(error, account_id=account_id)
                    return None, None, True, error
                return value, scope, True, persistence_error
            value, scope, error = _previous_response_entry_from_mapping(
                payload,
                error_prefix="LLM state previous response",
            )
            if error:
                self._set_llm_state_persistence_error(error, account_id=account_id)
                return None, None, False, error
            return value, scope, False, persistence_error
        value, scope, error = _previous_response_entry_from_mapping(
            payload,
            error_prefix="LLM state previous response",
        )
        if error:
            self._set_llm_state_persistence_error(error, account_id=account_id)
            return None, None, False, error
        return value, scope, PREVIOUS_RESPONSE_CONVERSATIONS_FIELD in payload, persistence_error

    def _read_llm_previous_response_id(self, account_id: str, *, conversation_scope: str = "") -> str | None:
        response_id, _scope, _legacy_fallback_used, _persistence_error = self._read_llm_previous_response(
            account_id,
            conversation_scope=conversation_scope,
        )
        return response_id

    def _read_llm_previous_response_snapshot(
        self,
        account_id: str,
    ) -> tuple[
        str | None,
        tuple[str, str, str] | None,
        dict[str, tuple[str | None, tuple[str, str, str] | None]],
        str,
    ]:
        payload, persistence_error = self._read_llm_state(account_id)
        top_response_id, top_scope, error = _previous_response_entry_from_mapping(
            payload,
            error_prefix="LLM state previous response",
        )
        if error:
            self._set_llm_state_persistence_error(error, account_id=account_id)
            return None, None, {}, error
        conversation_entries: dict[str, tuple[str | None, tuple[str, str, str] | None]] = {}
        conversations = payload.get(PREVIOUS_RESPONSE_CONVERSATIONS_FIELD)
        if conversations is not None:
            if not isinstance(conversations, dict):
                error = "LLM state previous response conversations are invalid"
                self._set_llm_state_persistence_error(error, account_id=account_id)
                return None, None, {}, error
            for raw_scope, raw_entry in conversations.items():
                conversation_scope = _clean_conversation_scope(raw_scope)
                if not conversation_scope:
                    error = "LLM state previous response conversation key is invalid"
                    self._set_llm_state_persistence_error(error, account_id=account_id)
                    return None, None, {}, error
                if not isinstance(raw_entry, Mapping):
                    error = "LLM state previous response conversation entry is invalid"
                    self._set_llm_state_persistence_error(error, account_id=account_id)
                    return None, None, {}, error
                response_id, response_scope, error = _previous_response_entry_from_mapping(
                    raw_entry,
                    error_prefix="LLM state previous response conversation",
                )
                if error:
                    self._set_llm_state_persistence_error(error, account_id=account_id)
                    return None, None, {}, error
                if response_id or response_scope is not None or raw_entry:
                    conversation_entries[conversation_scope] = (response_id, response_scope)
        return top_response_id, top_scope, conversation_entries, persistence_error

    def _write_llm_previous_response_id(
        self,
        account_id: str,
        response_id: str,
        *,
        provider: str = "",
        model: str = "",
        key_fingerprint: str = "",
        conversation_scope: str = "",
    ) -> bool:
        clean_response_id = str(response_id or "").strip()
        if not clean_response_id:
            return False
        clean_conversation_scope = _clean_conversation_scope(conversation_scope)
        with self._llm_state_lock(account_id):
            payload, persistence_error = self._read_llm_state(account_id)
            if persistence_error:
                return False
            clean_provider = str(provider or "").strip().casefold()
            clean_model = str(model or "").strip()
            clean_key_fingerprint = str(key_fingerprint or "").strip().casefold()
            if clean_conversation_scope:
                conversations = payload.get(PREVIOUS_RESPONSE_CONVERSATIONS_FIELD, {})
                if conversations is None:
                    conversations = {}
                if not isinstance(conversations, dict):
                    error = "LLM state previous response conversations are invalid"
                    self._set_llm_state_persistence_error(error, account_id=account_id)
                    return False
                entry: dict[str, Any] = {"previous_response_id": clean_response_id}
                if clean_provider and clean_model:
                    entry[PREVIOUS_RESPONSE_PROVIDER_FIELD] = clean_provider
                    entry[PREVIOUS_RESPONSE_MODEL_FIELD] = clean_model
                    if clean_key_fingerprint:
                        entry[PREVIOUS_RESPONSE_KEY_FIELD] = clean_key_fingerprint
                else:
                    entry.pop(PREVIOUS_RESPONSE_PROVIDER_FIELD, None)
                    entry.pop(PREVIOUS_RESPONSE_MODEL_FIELD, None)
                    entry.pop(PREVIOUS_RESPONSE_KEY_FIELD, None)
                payload[PREVIOUS_RESPONSE_CONVERSATIONS_FIELD] = {
                    **conversations,
                    clean_conversation_scope: entry,
                }
                # Keep old unscoped readers useful without letting Engine use
                # this account-wide mirror for scoped lookups.
                _set_persisted_previous_response_fields(
                    payload,
                    clean_response_id,
                    provider=clean_provider,
                    model=clean_model,
                    key_fingerprint=clean_key_fingerprint,
                )
            else:
                _set_persisted_previous_response_fields(
                    payload,
                    clean_response_id,
                    provider=clean_provider,
                    model=clean_model,
                    key_fingerprint=clean_key_fingerprint,
                )
            payload["updated_at"] = utc_now()
            return self._write_llm_state(account_id, payload)

    def _clear_llm_previous_response_id(self, account_id: str, *, conversation_scope: str = "") -> bool:
        with self._llm_state_lock(account_id):
            payload, persistence_error = self._read_llm_state(account_id)
            if persistence_error:
                return False
            clean_conversation_scope = _clean_conversation_scope(conversation_scope)
            if clean_conversation_scope:
                conversations = payload.get(PREVIOUS_RESPONSE_CONVERSATIONS_FIELD)
                if conversations is None:
                    return True
                if not isinstance(conversations, dict):
                    error = "LLM state previous response conversations are invalid"
                    self._set_llm_state_persistence_error(error, account_id=account_id)
                    return False
                if clean_conversation_scope not in conversations:
                    return True
                updated_conversations = dict(conversations)
                removed_entry = updated_conversations.pop(clean_conversation_scope, None)
                payload[PREVIOUS_RESPONSE_CONVERSATIONS_FIELD] = updated_conversations
                if (
                    isinstance(removed_entry, Mapping)
                    and str(payload.get("previous_response_id") or "").strip()
                    == str(removed_entry.get("previous_response_id") or "").strip()
                ):
                    mirrored = False
                    for candidate in reversed(list(updated_conversations.values())):
                        if not isinstance(candidate, Mapping):
                            continue
                        candidate_id, candidate_scope, candidate_error = _previous_response_entry_from_mapping(
                            candidate,
                            error_prefix="LLM state previous response conversation",
                        )
                        if candidate_error:
                            error = candidate_error
                            self._set_llm_state_persistence_error(error, account_id=account_id)
                            return False
                        if not candidate_id:
                            continue
                        _set_persisted_previous_response_fields(
                            payload,
                            candidate_id,
                            provider=candidate_scope[0] if candidate_scope else "",
                            model=candidate_scope[1] if candidate_scope else "",
                            key_fingerprint=candidate_scope[2] if candidate_scope else "",
                        )
                        mirrored = True
                        break
                    if not mirrored:
                        _clear_persisted_previous_response_fields(payload)
                payload["updated_at"] = utc_now()
                return self._write_llm_state(account_id, payload)
            state_fields = {
                "previous_response_id",
                PREVIOUS_RESPONSE_PROVIDER_FIELD,
                PREVIOUS_RESPONSE_MODEL_FIELD,
                PREVIOUS_RESPONSE_KEY_FIELD,
                PREVIOUS_RESPONSE_CONVERSATIONS_FIELD,
            }
            if not payload or not state_fields.intersection(payload):
                return True
            for field_name in state_fields:
                payload.pop(field_name, None)
            payload["updated_at"] = utc_now()
            return self._write_llm_state(account_id, payload)

    def _load_persisted_link_notifications(self) -> None:
        if self.secret_provider is None:
            self.link_notifications_persistence_error = "link-notification persistence has no secret provider"
            return
        try:
            path_exists = self.link_notifications_path.exists()
        except (OSError, ValueError) as exc:
            self.link_notifications_persistence_error = str(exc)
            return
        if not path_exists:
            if self.link_notifications and self.link_notifications_persistence_error:
                # A previous write may have failed while the notification was
                # retained in memory. Retry it once the provider is available.
                self._save_link_notifications()
                return
            self.link_notifications = {}
            self.link_notifications_persistence_error = ""
            return
        existing = dict(self.link_notifications)
        had_persistence_error = bool(self.link_notifications_persistence_error)
        try:
            payload = self._link_vault.read_json(self.link_notifications_path, {"notifications": []})
            notifications = payload.get("notifications", []) if isinstance(payload, dict) else []
            if not isinstance(notifications, list):
                raise AccountStoreError("link-notification state must contain a notifications list")
            loaded: dict[tuple[str, str, str], dict[str, str]] = {}
            for item in notifications:
                if not isinstance(item, dict):
                    raise AccountStoreError("link-notification state contains a non-object item")
                instance = str(item.get("instance") or "")
                account_id = str(item.get("account_id") or "")
                old_identity_key = str(item.get("old_identity_key") or "")
                new_identity_key = str(item.get("new_identity_key") or "")
                created_at = str(item.get("created_at") or "")
                if not (instance and account_id and old_identity_key and new_identity_key and created_at):
                    raise AccountStoreError("link-notification state contains an incomplete item")
                loaded[(instance, account_id, old_identity_key)] = {
                    "new_identity_key": new_identity_key,
                    "old_identity_key": old_identity_key,
                    "created_at": created_at,
                }
        except (AccountStoreError, OSError, TypeError, ValueError) as exc:
            self.link_notifications_persistence_error = str(exc)
            self.link_notifications = existing
            return
        if had_persistence_error:
            loaded.update(existing)
        self.link_notifications = loaded
        self.link_notifications_persistence_error = ""
        self._purge_expired_link_notifications()
        if had_persistence_error and not self.link_notifications_persistence_error:
            self._save_link_notifications()

    def _refresh_persisted_link_notifications(self) -> None:
        """Refresh link notifications written by another runtime bridge."""

        self._load_persisted_link_notifications()

    def _save_link_notifications(self) -> None:
        if self.secret_provider is None:
            self.link_notifications_persistence_error = "link-notification persistence has no secret provider"
            return
        with self._link_notifications_lock():
            notifications = [
                {
                    "instance": instance,
                    "account_id": account_id,
                    "old_identity_key": old_identity_key,
                    **dict(payload),
                }
                for (instance, account_id, old_identity_key), payload in sorted(self.link_notifications.items())
            ]
            if not notifications:
                try:
                    self.link_notifications_path.unlink()
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    self.link_notifications_persistence_error = str(exc)
                    return
                self.link_notifications_persistence_error = ""
                return
            try:
                self._link_vault.write_json(self.link_notifications_path, {"notifications": notifications})
                self.link_notifications_persistence_error = ""
            except (AccountStoreError, OSError, TypeError, ValueError) as exc:
                self.link_notifications_persistence_error = str(exc)
