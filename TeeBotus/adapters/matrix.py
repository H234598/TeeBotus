from __future__ import annotations

import base64
from typing import Any

from TeeBotus.runtime.accounts import matrix_identity_key
from TeeBotus.runtime.actions import DeleteTrackedMessages, ExportFile, NotifyLinkedIdentity, SendAttachment, SendText, SendTyping
from TeeBotus.runtime.events import IncomingEvent


def matrix_message_to_event(
    room: Any,
    message: Any,
    *,
    instance: str,
    adapter_slot: int,
    account_id: str = "",
    account_label: str = "matrix:1",
) -> IncomingEvent:
    sender = str(getattr(message, "sender", "") or "").strip()
    room_id = str(getattr(room, "room_id", "") or "").strip()
    return IncomingEvent(
        event_id=f"matrix:{getattr(message, 'event_id', '')}",
        instance=instance,
        channel="matrix",
        adapter_slot=adapter_slot,
        account_id=account_id,
        identity_key=matrix_identity_key(sender),
        chat_id=room_id,
        chat_type="private" if _matrix_room_is_private(room) else "group",
        sender_id=sender,
        sender_name=str(getattr(message, "sender", "") or ""),
        sender_username=sender,
        sender_number="",
        text=str(getattr(message, "body", "") or ""),
        message_ref=str(getattr(message, "event_id", "") or ""),
        attachments=(),
        raw=message,
    )


async def send_matrix_actions(client: Any, actions: list[Any]) -> list[str | None]:
    sent: list[str | None] = []
    for action in actions:
        if isinstance(action, SendText):
            response = await client.room_send(
                room_id=action.chat_id,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": action.text},
            )
            sent.append(_matrix_event_id(response))
        elif isinstance(action, SendTyping):
            await client.room_typing(action.chat_id, True, timeout=3000)
            sent.append(None)
        elif isinstance(action, SendAttachment):
            caption = action.caption or f"Datei erzeugt: {action.filename}"
            encoded = base64.b64encode(action.data).decode("ascii")
            response = await client.room_send(
                room_id=action.chat_id,
                message_type="m.room.message",
                content={"msgtype": "m.notice", "body": f"{caption}\n\nbase64:{encoded}"},
            )
            sent.append(_matrix_event_id(response))
        elif isinstance(action, ExportFile):
            caption = action.caption or f"Export: {action.filename}"
            encoded = base64.b64encode(action.data).decode("ascii")
            response = await client.room_send(
                room_id=action.chat_id,
                message_type="m.room.message",
                content={"msgtype": "m.notice", "body": f"{caption}\n\nbase64:{encoded}"},
            )
            sent.append(_matrix_event_id(response))
        elif isinstance(action, (NotifyLinkedIdentity, DeleteTrackedMessages)):
            sent.append(None)
    return sent


def _matrix_room_is_private(room: Any) -> bool:
    joined_count = getattr(room, "joined_count", None)
    if isinstance(joined_count, int):
        return joined_count == 2
    member_count = getattr(room, "member_count", None)
    if isinstance(member_count, int):
        return member_count == 2
    users = getattr(room, "users", None)
    if isinstance(users, dict):
        return len(users) == 2
    return False


def _matrix_event_id(response: Any) -> str | None:
    value = getattr(response, "event_id", None)
    if value:
        return str(value)
    return None
