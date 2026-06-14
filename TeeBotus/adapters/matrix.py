from __future__ import annotations

from io import BytesIO
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
            response = await _send_matrix_file_or_error_notice(
                client,
                room_id=action.chat_id,
                data=action.data,
                filename=action.filename,
                content_type=action.content_type,
                caption=action.caption,
            )
            sent.append(_matrix_event_id(response))
        elif isinstance(action, ExportFile):
            response = await _send_matrix_file_or_error_notice(
                client,
                room_id=action.chat_id,
                data=action.data,
                filename=action.filename,
                content_type=action.content_type,
                caption=action.caption or f"Export: {action.filename}",
            )
            sent.append(_matrix_event_id(response))
        elif isinstance(action, (NotifyLinkedIdentity, DeleteTrackedMessages)):
            sent.append(None)
    return sent


async def _send_matrix_file_or_error_notice(
    client: Any,
    *,
    room_id: str,
    data: bytes,
    filename: str,
    content_type: str,
    caption: str = "",
) -> Any:
    try:
        return await _send_matrix_file(
            client,
            room_id=room_id,
            data=data,
            filename=filename,
            content_type=content_type,
            caption=caption,
        )
    except Exception as exc:
        return await client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content={
                "msgtype": "m.notice",
                "body": f"Datei konnte nicht gesendet werden: {filename} ({exc})",
            },
        )


async def _send_matrix_file(
    client: Any,
    *,
    room_id: str,
    data: bytes,
    filename: str,
    content_type: str,
    caption: str = "",
) -> Any:
    upload_response, _keys = await client.upload(
        BytesIO(data),
        content_type=content_type or "application/octet-stream",
        filename=filename,
        filesize=len(data),
    )
    content_uri = getattr(upload_response, "content_uri", None)
    if not content_uri:
        message = getattr(upload_response, "message", "") or "Matrix upload returned no content URI"
        raise RuntimeError(str(message))
    body = caption or filename
    return await client.room_send(
        room_id=room_id,
        message_type="m.room.message",
        content={
            "msgtype": "m.file",
            "body": body,
            "filename": filename,
            "url": str(content_uri),
            "info": {
                "mimetype": content_type or "application/octet-stream",
                "size": len(data),
            },
        },
    )


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
