from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from TeeBotus.runtime.accounts import (
    AccountStoreError,
    EncryptedJsonVault,
    InstanceSecretProvider,
    SecretToolInstanceSecretProvider,
)
from TeeBotus.runtime.maintenance import maintain_runtime_directory, rotate_runtime_text_file_if_needed

FlowType = Literal["teladi_emergency", "memory_reset", "youtube_options", "account_edit", "link_wtf"] | str
LINK_NOTIFICATIONS_FILENAME = "Link_Notifications.json"
LINK_NOTIFICATION_TTL_SECONDS = 15 * 60


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
    security_events: list[dict[str, Any]] = field(default_factory=list)

    def set_pending_flow(self, instance_name: str, account_id: str, flow_type: str, payload: dict[str, Any]) -> None:
        self.pending_flows[(instance_name, account_id, flow_type)] = dict(payload)

    def pop_pending_flow(self, instance_name: str, account_id: str, flow_type: str) -> dict[str, Any] | None:
        return self.pending_flows.pop((instance_name, account_id, flow_type), None)

    def get_pending_flow(self, instance_name: str, account_id: str, flow_type: str) -> dict[str, Any] | None:
        payload = self.pending_flows.get((instance_name, account_id, flow_type))
        return dict(payload) if payload is not None else None

    def set_previous_response_id(self, instance_name: str, account_id: str, response_id: str | None) -> None:
        if response_id:
            self.previous_response_ids[(instance_name, account_id)] = response_id

    def get_previous_response_id(self, instance_name: str, account_id: str) -> str | None:
        return self.previous_response_ids.get((instance_name, account_id))

    def reset_previous_response_id(self, instance_name: str, account_id: str) -> None:
        self.previous_response_ids.pop((instance_name, account_id), None)

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
        self.link_notifications_persistence_error = ""
        self._load_persisted_link_notifications()

    @property
    def _link_vault(self) -> EncryptedJsonVault:
        if self.secret_provider is None:
            raise AccountStoreError("link-notification persistence has no secret provider")
        return EncryptedJsonVault(self.instance_name, self.secret_provider)

    def set_pending_flow(self, *args, **kwargs) -> None:  # type: ignore[override]
        if len(args) == 1 and isinstance(args[0], PendingFlow):
            flow = args[0]
            self.pending_flows[(flow.instance, flow.account_id, flow.flow_type)] = flow.as_dict()
            return
        return super().set_pending_flow(*args, **kwargs)

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
