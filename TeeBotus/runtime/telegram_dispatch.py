from __future__ import annotations

import base64
import threading
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any

from TeeBotus.runtime.accounts import EncryptedJsonVault, INSTANCE_MAPPING_KEY_PURPOSE, InstanceSecretProvider
from TeeBotus.runtime.actions import (
    DelaySeconds,
    DeleteTrackedMessages,
    ExportFile,
    MessageButton,
    NotifyLinkedIdentity,
    SendAttachment,
    SendEdit,
    SendPoll,
    SendReaction,
    SendReceipt,
    SendText,
    SendTyping,
    SetMatrixState,
    UpdateSignalContact,
    UpdateSignalGroup,
)
from TeeBotus.runtime.engine import EngineResult
from TeeBotus.runtime.events import IncomingEvent

TELEGRAM_DISPATCH_JOURNAL_FILENAME = "Telegram_Dispatch_Journal.json"
TELEGRAM_DISPATCH_JOURNAL_SCHEMA_VERSION = 1
_JOURNAL_LOCK = threading.RLock()

_ACTION_TYPES = {
    action_type.__name__: action_type
    for action_type in (
        DelaySeconds,
        DeleteTrackedMessages,
        ExportFile,
        NotifyLinkedIdentity,
        SendAttachment,
        SendEdit,
        SendPoll,
        SendReaction,
        SendReceipt,
        SendText,
        SendTyping,
        SetMatrixState,
        UpdateSignalContact,
        UpdateSignalGroup,
    )
}


class TelegramDispatchJournalError(RuntimeError):
    """Raised when a pending Telegram dispatch cannot be read safely."""


class TelegramDispatchJournalEntry:
    def __init__(
        self,
        *,
        event: IncomingEvent,
        engine_result: EngineResult,
        completed_action_indices: set[int],
    ) -> None:
        self.event = event
        self.engine_result = engine_result
        self.completed_action_indices = set(completed_action_indices)


class TelegramDispatchJournal:
    """Encrypted, transient action journal for Telegram update retries.

    The journal stores an explicit allowlisted action schema rather than Python
    objects or pickles. It closes the process-restart gap for deterministic
    retries; the unavoidable crash window between a remote send and recording
    that send remains at-least-once by design.
    """

    def __init__(
        self,
        instance_name: str,
        runtime_dir: Path,
        secret_provider: InstanceSecretProvider | None,
    ) -> None:
        self.instance_name = str(instance_name or "").strip()
        self.runtime_dir = Path(runtime_dir)
        self.path = self.runtime_dir / TELEGRAM_DISPATCH_JOURNAL_FILENAME
        self.secret_provider = secret_provider

    @property
    def enabled(self) -> bool:
        return self.secret_provider is not None

    def load(self, key: str) -> TelegramDispatchJournalEntry | None:
        if not self.enabled:
            return None
        clean_key = str(key or "").strip()
        if not clean_key:
            return None
        with _JOURNAL_LOCK:
            payload = self._read_payload()
            raw_entry = payload["entries"].get(clean_key)
            if raw_entry is None:
                return None
            return _deserialize_entry(raw_entry)

    def create(self, key: str, event: IncomingEvent, engine_result: EngineResult) -> None:
        if not self.enabled:
            return
        clean_key = str(key or "").strip()
        if not clean_key:
            return
        entry = _serialize_entry(event, engine_result, set())
        with _JOURNAL_LOCK:
            payload = self._read_payload()
            payload["entries"].setdefault(clean_key, entry)
            self._write_payload(payload)

    def mark_action_completed(self, key: str, action_index: int) -> None:
        if not self.enabled:
            return
        clean_key = str(key or "").strip()
        index = int(action_index)
        with _JOURNAL_LOCK:
            payload = self._read_payload()
            raw_entry = payload["entries"].get(clean_key)
            if raw_entry is None:
                raise TelegramDispatchJournalError(f"missing Telegram dispatch journal entry: {clean_key}")
            completed = raw_entry.get("completed_action_indices")
            if not isinstance(completed, list):
                raise TelegramDispatchJournalError("Telegram dispatch journal completion list is invalid")
            if index not in completed:
                completed.append(index)
                completed.sort()
                self._write_payload(payload)

    def complete(self, key: str) -> None:
        if not self.enabled:
            return
        clean_key = str(key or "").strip()
        if not clean_key:
            return
        with _JOURNAL_LOCK:
            payload = self._read_payload()
            if clean_key in payload["entries"]:
                del payload["entries"][clean_key]
                self._write_payload(payload)

    def _vault(self) -> EncryptedJsonVault:
        if self.secret_provider is None:
            raise TelegramDispatchJournalError("Telegram dispatch journal has no secret provider")
        return EncryptedJsonVault(
            self.instance_name,
            self.secret_provider,
            purpose=INSTANCE_MAPPING_KEY_PURPOSE,
            root=self.runtime_dir,
        )

    def _read_payload(self) -> dict[str, Any]:
        try:
            payload = self._vault().read_json(
                self.path,
                {"schema_version": TELEGRAM_DISPATCH_JOURNAL_SCHEMA_VERSION, "entries": {}},
            )
        except Exception as exc:  # noqa: BLE001 - journal failures must fail closed.
            raise TelegramDispatchJournalError(f"could not read Telegram dispatch journal: {self.path}") from exc
        if payload.get("schema_version") != TELEGRAM_DISPATCH_JOURNAL_SCHEMA_VERSION:
            raise TelegramDispatchJournalError(f"unsupported Telegram dispatch journal schema: {self.path}")
        entries = payload.get("entries")
        if not isinstance(entries, dict):
            raise TelegramDispatchJournalError(f"Telegram dispatch journal entries are invalid: {self.path}")
        return {"schema_version": TELEGRAM_DISPATCH_JOURNAL_SCHEMA_VERSION, "entries": entries}

    def _write_payload(self, payload: dict[str, Any]) -> None:
        try:
            self._vault().write_json(self.path, payload)
        except Exception as exc:  # noqa: BLE001 - caller must not acknowledge an unjournaled dispatch.
            raise TelegramDispatchJournalError(f"could not write Telegram dispatch journal: {self.path}") from exc


def _serialize_entry(event: IncomingEvent, engine_result: EngineResult, completed: set[int]) -> dict[str, Any]:
    return {
        "event": {
            "event_id": event.event_id,
            "instance": event.instance,
            "channel": event.channel,
            "adapter_slot": event.adapter_slot,
            "account_id": event.account_id,
            "identity_key": event.identity_key,
            "chat_id": event.chat_id,
            "chat_type": event.chat_type,
            "sender_id": event.sender_id,
            "sender_name": event.sender_name,
            "sender_username": event.sender_username,
            "sender_number": event.sender_number,
            "text": event.text,
            "message_ref": event.message_ref,
            "reply_to_text": event.reply_to_text,
            "reply_to_bot": event.reply_to_bot,
        },
        "account_id": engine_result.account_id,
        "handled": bool(engine_result.handled),
        "suppress_notification_loudness_prompt": bool(engine_result.suppress_notification_loudness_prompt),
        "actions": [_serialize_action(action) for action in engine_result.actions],
        "completed_action_indices": sorted(int(index) for index in completed),
    }


def _deserialize_entry(raw_entry: Any) -> TelegramDispatchJournalEntry:
    if not isinstance(raw_entry, dict):
        raise TelegramDispatchJournalError("Telegram dispatch journal entry is not an object")
    raw_event = raw_entry.get("event")
    raw_actions = raw_entry.get("actions")
    raw_completed = raw_entry.get("completed_action_indices", [])
    if not isinstance(raw_event, dict) or not isinstance(raw_actions, list) or not isinstance(raw_completed, list):
        raise TelegramDispatchJournalError("Telegram dispatch journal entry has invalid fields")
    try:
        event = IncomingEvent(
            event_id=str(raw_event["event_id"]),
            instance=str(raw_event.get("instance") or ""),
            channel=str(raw_event.get("channel") or "telegram"),  # type: ignore[arg-type]
            adapter_slot=int(raw_event.get("adapter_slot", 1)),
            account_id=str(raw_event.get("account_id") or ""),
            identity_key=str(raw_event.get("identity_key") or ""),
            chat_id=str(raw_event["chat_id"]),
            chat_type=str(raw_event.get("chat_type") or "private"),  # type: ignore[arg-type]
            sender_id=str(raw_event.get("sender_id") or ""),
            text=str(raw_event.get("text") or ""),
            message_ref=str(raw_event.get("message_ref") or ""),
            sender_name=str(raw_event.get("sender_name") or ""),
            sender_username=str(raw_event.get("sender_username") or ""),
            sender_number=str(raw_event.get("sender_number") or ""),
            reply_to_text=raw_event.get("reply_to_text"),
            reply_to_bot=bool(raw_event.get("reply_to_bot", False)),
            raw=None,
        )
        actions = [_deserialize_action(raw_action) for raw_action in raw_actions]
        completed = {int(index) for index in raw_completed}
        if any(index < 0 or index >= len(actions) for index in completed):
            raise TelegramDispatchJournalError("Telegram dispatch journal completion index is out of range")
        engine_result = EngineResult(
            str(raw_entry.get("account_id") or event.account_id),
            actions,
            handled=bool(raw_entry.get("handled", False)),
            suppress_notification_loudness_prompt=bool(raw_entry.get("suppress_notification_loudness_prompt", False)),
        )
    except TelegramDispatchJournalError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise TelegramDispatchJournalError("Telegram dispatch journal entry cannot be decoded") from exc
    return TelegramDispatchJournalEntry(event=event, engine_result=engine_result, completed_action_indices=completed)


def _serialize_action(action: Any) -> dict[str, Any]:
    action_type = type(action)
    if action_type.__name__ not in _ACTION_TYPES or not is_dataclass(action):
        raise TelegramDispatchJournalError(f"unsupported Telegram dispatch action: {action_type.__name__}")
    return {
        "type": action_type.__name__,
        "fields": {item.name: _encode_value(getattr(action, item.name)) for item in fields(action)},
    }


def _deserialize_action(raw_action: Any) -> Any:
    if not isinstance(raw_action, dict):
        raise TelegramDispatchJournalError("Telegram dispatch action is not an object")
    action_type = _ACTION_TYPES.get(str(raw_action.get("type") or ""))
    raw_fields = raw_action.get("fields")
    if action_type is None or not isinstance(raw_fields, dict):
        raise TelegramDispatchJournalError("Telegram dispatch action type or fields are invalid")
    try:
        return action_type(**{str(key): _decode_value(value) for key, value in raw_fields.items()})
    except (TypeError, ValueError) as exc:
        raise TelegramDispatchJournalError("Telegram dispatch action cannot be constructed") from exc


def _encode_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return {"__type__": "bytes", "value": base64.b64encode(value).decode("ascii")}
    if isinstance(value, MessageButton):
        return {
            "__type__": "MessageButton",
            "value": {"label": value.label, "text": value.text, "url": value.url},
        }
    if isinstance(value, tuple):
        return {"__type__": "tuple", "value": [_encode_value(item) for item in value]}
    if isinstance(value, list):
        return [_encode_value(item) for item in value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TelegramDispatchJournalError("Telegram dispatch value contains a non-string mapping key")
        return {key: _encode_value(item) for key, item in value.items()}
    raise TelegramDispatchJournalError(f"unsupported Telegram dispatch value: {type(value).__name__}")


def _decode_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_decode_value(item) for item in value]
    if not isinstance(value, dict):
        return value
    marker = value.get("__type__")
    if marker == "bytes":
        try:
            return base64.b64decode(str(value["value"]).encode("ascii"), validate=True)
        except (KeyError, ValueError) as exc:
            raise TelegramDispatchJournalError("Telegram dispatch bytes value is invalid") from exc
    if marker == "MessageButton":
        raw_button = value.get("value")
        if not isinstance(raw_button, dict):
            raise TelegramDispatchJournalError("Telegram dispatch MessageButton value is invalid")
        try:
            return MessageButton(
                label=str(raw_button["label"]),
                text=str(raw_button.get("text") or ""),
                url=str(raw_button.get("url") or ""),
            )
        except KeyError as exc:
            raise TelegramDispatchJournalError("Telegram dispatch MessageButton is incomplete") from exc
    if marker == "tuple":
        raw_items = value.get("value")
        if not isinstance(raw_items, list):
            raise TelegramDispatchJournalError("Telegram dispatch tuple value is invalid")
        return tuple(_decode_value(item) for item in raw_items)
    if marker:
        raise TelegramDispatchJournalError(f"unknown Telegram dispatch value marker: {marker}")
    return {str(key): _decode_value(item) for key, item in value.items()}


__all__ = [
    "TELEGRAM_DISPATCH_JOURNAL_FILENAME",
    "TelegramDispatchJournal",
    "TelegramDispatchJournalEntry",
    "TelegramDispatchJournalError",
]
