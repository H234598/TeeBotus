from __future__ import annotations

from inspect import isawaitable
from typing import Any, Mapping

from TeeBotus.adapters.matrix import send_matrix_actions
from TeeBotus.adapters.signal import send_signal_actions
from TeeBotus.adapters.telegram import send_telegram_actions
from TeeBotus.runtime.actions import OutgoingAction
from TeeBotus.runtime.proactive_agent import ProactiveSender


def telegram_proactive_sender(apis: Any | Mapping[int, Any]) -> ProactiveSender:
    api_by_slot = _slot_mapping(apis)

    def sender(route: dict[str, Any], action: OutgoingAction, _item: dict[str, Any]) -> Any:
        api = _object_for_route_slot(api_by_slot, route)
        sent = send_telegram_actions(api, [action])
        return sent[0] if sent else None

    return sender


def signal_proactive_sender(bots: Any | Mapping[int, Any]) -> ProactiveSender:
    bot_by_slot = _slot_mapping(bots)

    async def sender(route: dict[str, Any], action: OutgoingAction, _item: dict[str, Any]) -> Any:
        bot = _object_for_route_slot(bot_by_slot, route)
        sent = await send_signal_actions(_SignalProactiveContext(bot, _signal_action_chat_id(action, route), _signal_action_message_ref(action)), [action])
        return sent[0] if sent else None

    return sender


class _SignalProactiveMessage:
    def __init__(self, recipient: str, message_ref: str = "") -> None:
        self.timestamp = str(message_ref or "").strip()
        self.source = recipient
        self.source_uuid = recipient
        self.group = recipient if recipient.startswith("group.") else ""
        self.text = ""

    def recipient(self) -> str:
        return self.group or self.source


class _SignalProactiveContext:
    def __init__(self, bot: Any, recipient: str, message_ref: str = "") -> None:
        self.bot = bot
        self.message = _SignalProactiveMessage(str(recipient or "").strip(), str(message_ref or "").strip())

    async def send(self, text: str, **kwargs: Any) -> Any:
        send = getattr(self.bot, "send", None)
        if not callable(send):
            raise RuntimeError("SignalBot.send is required for proactive Signal dispatch")
        return await _maybe_await(send(self.message.recipient(), text, **kwargs))

    async def reply(self, text: str, **kwargs: Any) -> Any:
        return await self.send(text, **kwargs)

    async def edit(self, text: str, edit_timestamp: int, **kwargs: Any) -> Any:
        return await self.send(text, edit_timestamp=edit_timestamp, **kwargs)

    async def start_typing(self) -> Any:
        start_typing = getattr(self.bot, "start_typing", None)
        if not callable(start_typing):
            raise RuntimeError("SignalBot.start_typing is required for proactive Signal dispatch")
        return await _maybe_await(start_typing(self.message.recipient()))

    async def stop_typing(self) -> Any:
        stop_typing = getattr(self.bot, "stop_typing", None)
        if not callable(stop_typing):
            return None
        return await _maybe_await(stop_typing(self.message.recipient()))

    async def react(self, emoji: str) -> Any:
        react = getattr(self.bot, "react", None)
        if not callable(react):
            raise RuntimeError("SignalBot.react is required for proactive Signal dispatch")
        return await _maybe_await(react(self.message, emoji))

    async def receipt(self, receipt_type: str) -> Any:
        receipt = getattr(self.bot, "receipt", None)
        if not callable(receipt):
            raise RuntimeError("SignalBot.receipt is required for proactive Signal dispatch")
        return await _maybe_await(receipt(self.message, receipt_type))

    async def remote_delete(self, timestamp: int) -> Any:
        remote_delete = getattr(self.bot, "remote_delete", None)
        if not callable(remote_delete):
            raise RuntimeError("SignalBot.remote_delete is required for proactive Signal dispatch")
        return await _maybe_await(remote_delete(self.message.recipient(), timestamp))

    async def delete_attachment(self, attachment_filename: str) -> Any:
        delete_attachment = getattr(self.bot, "delete_attachment", None)
        if not callable(delete_attachment):
            raise RuntimeError("SignalBot.delete_attachment is required for proactive Signal dispatch")
        return await _maybe_await(delete_attachment(attachment_filename))


def matrix_proactive_sender(clients: Any | Mapping[int, Any]) -> ProactiveSender:
    client_by_slot = _slot_mapping(clients)

    async def sender(route: dict[str, Any], action: OutgoingAction, _item: dict[str, Any]) -> Any:
        client = _object_for_route_slot(client_by_slot, route)
        ensure_started = getattr(client, "ensure_started", None)
        if callable(ensure_started):
            result = ensure_started()
            if isawaitable(result):
                await result
        sent = await send_matrix_actions(client, [action])
        return sent[0] if sent else None

    return sender


def _signal_action_chat_id(action: OutgoingAction, route: Mapping[str, Any]) -> str:
    chat_id = getattr(action, "chat_id", "")
    if str(chat_id or "").strip():
        return str(chat_id).strip()
    return str(route.get("chat_id") or route.get("receiver") or "").strip()


def _signal_action_message_ref(action: OutgoingAction) -> str:
    return str(getattr(action, "message_ref", "") or "").strip()


async def _maybe_await(value: Any) -> Any:
    if isawaitable(value):
        return await value
    return value


def _slot_mapping(value: Any | Mapping[int, Any]) -> dict[int, Any]:
    if isinstance(value, Mapping):
        normalized: dict[int, Any] = {}
        for slot, obj in value.items():
            normalized_slot = _normalize_slot(slot)
            if normalized_slot is None:
                raise ValueError(f"invalid adapter slot {slot!r}")
            normalized[normalized_slot] = obj
        return normalized
    return {1: value}


def _object_for_route_slot(objects: Mapping[int, Any], route: Mapping[str, Any]) -> Any:
    raw_slot = route.get("adapter_slot", 1)
    slot = _normalize_slot(raw_slot)
    if slot is None:
        raise KeyError(f"invalid adapter slot {raw_slot!r}")
    if slot in objects:
        return objects[slot]
    if len(objects) == 1 and 1 in objects:
        return objects[1]
    raise KeyError(f"no proactive backend object configured for adapter slot {slot}")


def _normalize_slot(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        slot = value
    elif isinstance(value, str):
        text = value.strip()
        if not text.isdecimal():
            return None
        slot = int(text)
    else:
        return None
    return slot if slot >= 1 else None
