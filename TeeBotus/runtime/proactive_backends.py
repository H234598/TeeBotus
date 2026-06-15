from __future__ import annotations

from inspect import isawaitable
from typing import Any, Mapping

from TeeBotus.adapters.matrix import send_matrix_actions
from TeeBotus.adapters.telegram import send_telegram_actions
from TeeBotus.runtime.actions import SendText
from TeeBotus.runtime.proactive_agent import ProactiveSender


def telegram_proactive_sender(apis: Any | Mapping[int, Any]) -> ProactiveSender:
    api_by_slot = _slot_mapping(apis)

    def sender(route: dict[str, Any], action: SendText, _item: dict[str, Any]) -> Any:
        api = _object_for_route_slot(api_by_slot, route)
        sent = send_telegram_actions(api, [action])
        return sent[0] if sent else None

    return sender


def signal_proactive_sender(bots: Any | Mapping[int, Any]) -> ProactiveSender:
    bot_by_slot = _slot_mapping(bots)

    async def sender(route: dict[str, Any], action: SendText, _item: dict[str, Any]) -> Any:
        bot = _object_for_route_slot(bot_by_slot, route)
        send = getattr(bot, "send", None)
        if not callable(send):
            raise RuntimeError("SignalBot.send is required for proactive Signal dispatch")
        result = send(
            action.chat_id,
            action.text,
            mentions=list(action.mentions) or None,
            text_mode=action.text_mode or None,
            view_once=action.view_once,
            link_preview=action.link_preview,
        )
        if isawaitable(result):
            return await result
        return result

    return sender


def matrix_proactive_sender(clients: Any | Mapping[int, Any]) -> ProactiveSender:
    client_by_slot = _slot_mapping(clients)

    async def sender(route: dict[str, Any], action: SendText, _item: dict[str, Any]) -> Any:
        client = _object_for_route_slot(client_by_slot, route)
        sent = await send_matrix_actions(client, [action])
        return sent[0] if sent else None

    return sender


def _slot_mapping(value: Any | Mapping[int, Any]) -> dict[int, Any]:
    if isinstance(value, Mapping):
        return {_normalize_slot(slot): obj for slot, obj in value.items()}
    return {1: value}


def _object_for_route_slot(objects: Mapping[int, Any], route: Mapping[str, Any]) -> Any:
    slot = _normalize_slot(route.get("adapter_slot", 1))
    if slot in objects:
        return objects[slot]
    if len(objects) == 1 and 1 in objects:
        return objects[1]
    raise KeyError(f"no proactive backend object configured for adapter slot {slot}")


def _normalize_slot(value: Any) -> int:
    try:
        slot = int(value)
    except (TypeError, ValueError):
        return 1
    return max(1, slot)
