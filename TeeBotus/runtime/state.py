from __future__ import annotations

import json
import time
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from TeeBotus.runtime.accounts import (
    ACCOUNTS_DIRNAME,
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
from TeeBotus.runtime.maintenance import maintain_runtime_directory, rotate_runtime_text_file_if_needed

FlowType = Literal["teladi_emergency", "memory_reset", "youtube_options", "account_edit", "link_wtf"] | str
LINK_NOTIFICATIONS_FILENAME = "Link_Notifications.json"
LINK_NOTIFICATION_TTL_SECONDS = 15 * 60
PREVIOUS_RESPONSE_PROVIDER_FIELD = "previous_response_provider"
PREVIOUS_RESPONSE_MODEL_FIELD = "previous_response_model"
PREVIOUS_RESPONSE_KEY_FIELD = "previous_response_key_fingerprint"


@dataclass(frozen=True)
class PendingFlow:
    instance: str
    account_id: str
    flow_type: str
    chat_id: str
    channel: str
    payload: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "instance": self.instance,
            "account_id": self.account_id,
            "flow_type": self.flow_type,
            "chat_id": self.chat_id,
            "channel": self.channel,
            "payload": dict(self.payload),
        }


@dataclass
class RuntimeState:
    """Small in-memory state container for pending account-scoped flows."""

    pending_flows: dict[tuple[str, str, str], dict[str, Any]] = field(default_factory=dict)
    link_notifications: dict[tuple[str, str, str], dict[str, str]] = field(default_factory=dict)
    previous_response_ids: dict[tuple[str, str], str] = field(default_factory=dict)
    previous_response_scopes: dict[tuple[str, str], tuple[str, str, str]] = field(default_factory=dict)
    security_events: list[dict[str, Any]] = field(default_factory=list)

    def set_pending_flow(self, instance_name: str, account_id: str, flow_type: str, payload: dict[str, Any]) -> None:
        self.pending_flows[(instance_name, account_id, flow_type)] = dict(payload)

    def pop_pending_flow(self, instance_name: str, account_id: str, flow_type: str) -> dict[str, Any] | None:
        return self.pending_flows.pop((instance_name, account_id, flow_type), None)

    def get_pending_flow(self, instance_name: str, account_id: str, flow_type: str) -> dict[str, Any] | None:
        payload = self.pending_flows.get((instance_name, account_id, flow_type))
        return dict(payload) if payload is not None else None

    def set_previous_response_id(
        self,
        instance_name: str,
        account_id: str,
        response_id: str | None,
        *,
        provider: str = "",
        model: str = "",
        key_fingerprint: str = "",
    ) -> None:
        key = (instance_name, account_id)
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
    ) -> str | None:
        key = (instance_name, account_id)
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

    def reset_previous_response_id(self, instance_name: str, account_id: str) -> None:
        key = (instance_name, account_id)
        self.previous_response_ids.pop(key, None)
        self.previous_response_scopes.pop(key, None)

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
        if self.instance_dir.suffix:
            self.runtime_dir = self.instance_dir.parent
            inferred_instance_dir = self.runtime_dir.parent.parent if self.runtime_dir.name == "runtime" else self.runtime_dir.parent
        elif self.instance_dir.name == "data":
            self.runtime_dir = self.instance_dir / "runtime"
            inferred_instance_dir = self.instance_dir.parent
        elif self.instance_dir.name == "runtime":
            self.runtime_dir = self.instance_dir
            inferred_instance_dir = self.instance_dir.parent.parent if self.instance_dir.parent.name == "data" else self.instance_dir.parent
        else:
            self.runtime_dir = self.instance_dir / "data" / "runtime"
            inferred_instance_dir = self.instance_dir
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.instance_name = instance_name or inferred_instance_dir.name
        self.secret_provider = secret_provider
        self.security_events_path = self.runtime_dir / "Security_Events.jsonl"
        self.link_notifications_path = self.runtime_dir / LINK_NOTIFICATIONS_FILENAME
        self.accounts_root = self.runtime_dir.parent / "accounts"
        self.link_notifications_persistence_error = ""
        self.llm_state_persistence_error = ""
        self.openai_state_persistence_error = ""
        self._account_store_secret_guard_checked = False
        self._llm_account_store: AccountStore | None = None
        self._load_persisted_link_notifications()

    @property
    def _link_vault(self) -> EncryptedJsonVault:
        if self.secret_provider is None:
            raise AccountStoreError("link-notification persistence has no secret provider")
        self._guard_account_store_secrets()
        return EncryptedJsonVault(self.instance_name, self.secret_provider)

    def _guard_account_store_secrets(self) -> None:
        if self._account_store_secret_guard_checked:
            return
        if isinstance(self.secret_provider, SecretToolInstanceSecretProvider):
            self._account_store_for_llm_state()
        self._account_store_secret_guard_checked = True

    def _account_store_for_llm_state(self) -> AccountStore:
        if self.secret_provider is None:
            raise AccountStoreError("LLM state persistence has no secret provider")
        if self._llm_account_store is None:
            self._llm_account_store = AccountStore(
                self.accounts_root,
                self.instance_name,
                self.secret_provider,
                create_dirs=False,
            )
        return self._llm_account_store

    def set_pending_flow(self, *args, **kwargs) -> None:  # type: ignore[override]
        if len(args) == 1 and isinstance(args[0], PendingFlow):
            flow = args[0]
            self.pending_flows[(flow.instance, flow.account_id, flow.flow_type)] = flow.as_dict()
            return
        return super().set_pending_flow(*args, **kwargs)

    def set_previous_response_id(
        self,
        instance_name: str,
        account_id: str,
        response_id: str | None,
        *,
        provider: str = "",
        model: str = "",
        key_fingerprint: str = "",
    ) -> None:
        super().set_previous_response_id(
            instance_name,
            account_id,
            response_id,
            provider=provider,
            model=model,
            key_fingerprint=key_fingerprint,
        )
        if str(response_id or "").strip():
            self._write_llm_previous_response_id(
                account_id,
                response_id,
                provider=provider,
                model=model,
                key_fingerprint=key_fingerprint,
            )
        else:
            self._clear_llm_previous_response_id(account_id)

    def get_previous_response_id(
        self,
        instance_name: str,
        account_id: str,
        *,
        provider: str = "",
        model: str = "",
        key_fingerprint: str = "",
    ) -> str | None:
        cached = super().get_previous_response_id(
            instance_name,
            account_id,
            provider=provider,
            model=model,
            key_fingerprint=key_fingerprint,
        )
        if cached:
            return cached
        persisted, persisted_scope = self._read_llm_previous_response(account_id)
        if persisted:
            key = (instance_name, account_id)
            self.previous_response_ids[key] = persisted
            if persisted_scope is not None:
                self.previous_response_scopes[key] = persisted_scope
            if provider or model or key_fingerprint:
                return super().get_previous_response_id(
                    instance_name,
                    account_id,
                    provider=provider,
                    model=model,
                    key_fingerprint=key_fingerprint,
                )
        return persisted

    def reset_previous_response_id(self, instance_name: str, account_id: str) -> None:
        super().reset_previous_response_id(instance_name, account_id)
        self._clear_llm_previous_response_id(account_id)

    def record_link_notification(self, *, instance_name: str, account_id: str, new_identity_key: str, old_identity_key: str) -> None:
        super().record_link_notification(
            instance_name=instance_name,
            account_id=account_id,
            new_identity_key=new_identity_key,
            old_identity_key=old_identity_key,
        )
        self._save_link_notifications()

    def pop_link_notification(self, *, instance_name: str, account_id: str, old_identity_key: str = "") -> dict[str, str] | None:
        notification = super().pop_link_notification(
            instance_name=instance_name,
            account_id=account_id,
            old_identity_key=old_identity_key,
        )
        if notification is not None:
            self._save_link_notifications()
        return notification

    def clear_link_notifications_for_new_identity(self, *, instance_name: str, account_id: str, new_identity_key: str) -> int:
        removed = super().clear_link_notifications_for_new_identity(
            instance_name=instance_name,
            account_id=account_id,
            new_identity_key=new_identity_key,
        )
        if removed:
            self._save_link_notifications()
        return removed

    def _purge_expired_link_notifications(self) -> None:
        before = len(self.link_notifications)
        super()._purge_expired_link_notifications()
        if len(self.link_notifications) != before and hasattr(self, "link_notifications_path"):
            self._save_link_notifications()

    def append_security_event(self, event: dict[str, Any]) -> None:
        super().append_security_event(event)
        rotate_runtime_text_file_if_needed(self.security_events_path)
        with self.security_events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        maintain_runtime_directory(self.runtime_dir)

    def _state_path(self, account_id: str, filename: str) -> Path:
        account = validate_sha512_token(account_id, field_name="account_id")
        return self.accounts_root / ACCOUNTS_DIRNAME / account / filename

    def _llm_state_path(self, account_id: str) -> Path:
        return self._state_path(account_id, LLM_STATE_FILENAME)

    def _openai_state_path(self, account_id: str) -> Path:
        return self._state_path(account_id, OPENAI_STATE_FILENAME)

    def _set_llm_state_persistence_error(self, error: str) -> None:
        self.llm_state_persistence_error = error
        self.openai_state_persistence_error = error

    def _llm_state_lock(self, account_id: str):
        try:
            validate_sha512_token(account_id, field_name="account_id")
        except AccountStoreError:
            # Keep the legacy in-memory behavior for invalid IDs; the actual
            # state-path validation below still records the persistence error.
            return nullcontext()
        return account_memory_lock_for_root(self.accounts_root, account_id)

    def _read_llm_state(self, account_id: str) -> dict[str, Any]:
        with self._llm_state_lock(account_id):
            try:
                selected = self._account_store_for_llm_state().read_llm_state(account_id)
                self._set_llm_state_persistence_error("")
                return selected
            except AccountStoreError as exc:
                self._set_llm_state_persistence_error(str(exc))
                return {}

    def _write_llm_state(self, account_id: str, payload: dict[str, Any]) -> None:
        with self._llm_state_lock(account_id):
            try:
                self._account_store_for_llm_state().write_llm_state(account_id, payload)
                self._set_llm_state_persistence_error("")
            except AccountStoreError as exc:
                self._set_llm_state_persistence_error(str(exc))

    def _read_llm_previous_response(self, account_id: str) -> tuple[str | None, tuple[str, str, str] | None]:
        payload = self._read_llm_state(account_id)
        value = str(payload.get("previous_response_id") or "").strip()
        provider = str(payload.get(PREVIOUS_RESPONSE_PROVIDER_FIELD) or "").strip().casefold()
        model = str(payload.get(PREVIOUS_RESPONSE_MODEL_FIELD) or "").strip()
        key_fingerprint = str(payload.get(PREVIOUS_RESPONSE_KEY_FIELD) or "").strip().casefold()
        scope = (provider, model, key_fingerprint) if provider and model else None
        return value or None, scope

    def _read_llm_previous_response_id(self, account_id: str) -> str | None:
        response_id, _scope = self._read_llm_previous_response(account_id)
        return response_id

    def _write_llm_previous_response_id(
        self,
        account_id: str,
        response_id: str,
        *,
        provider: str = "",
        model: str = "",
        key_fingerprint: str = "",
    ) -> None:
        clean_response_id = str(response_id or "").strip()
        if not clean_response_id:
            return
        with self._llm_state_lock(account_id):
            payload = self._read_llm_state(account_id)
            payload["previous_response_id"] = clean_response_id
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
            payload["updated_at"] = utc_now()
            self._write_llm_state(account_id, payload)

    def _clear_llm_previous_response_id(self, account_id: str) -> None:
        with self._llm_state_lock(account_id):
            payload = self._read_llm_state(account_id)
            if not payload or "previous_response_id" not in payload:
                return
            payload.pop("previous_response_id", None)
            payload.pop(PREVIOUS_RESPONSE_PROVIDER_FIELD, None)
            payload.pop(PREVIOUS_RESPONSE_MODEL_FIELD, None)
            payload.pop(PREVIOUS_RESPONSE_KEY_FIELD, None)
            payload["updated_at"] = utc_now()
            self._write_llm_state(account_id, payload)

    def _load_persisted_link_notifications(self) -> None:
        if self.secret_provider is None or not self.link_notifications_path.exists():
            return
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
        except AccountStoreError as exc:
            self.link_notifications_persistence_error = str(exc)
            self.link_notifications = {}
            return
        self.link_notifications = loaded
        self._purge_expired_link_notifications()

    def _save_link_notifications(self) -> None:
        if self.secret_provider is None:
            return
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
            return
        try:
            self._link_vault.write_json(self.link_notifications_path, {"notifications": notifications})
            self.link_notifications_persistence_error = ""
        except AccountStoreError as exc:
            self.link_notifications_persistence_error = str(exc)
