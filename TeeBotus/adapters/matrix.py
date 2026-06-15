from __future__ import annotations

from io import BytesIO
from typing import Any

from TeeBotus.runtime.accounts import matrix_identity_key
from TeeBotus.runtime.actions import DeleteTrackedMessages, ExportFile, NotifyLinkedIdentity, SendAttachment, SendText, SendTyping
from TeeBotus.runtime.events import IncomingAttachment, IncomingEvent


def matrix_message_to_event(
    room: Any,
    message: Any,
    *,
    instance: str,
    adapter_slot: int,
    account_id: str = "",
    account_label: str = "matrix:1",
) -> IncomingEvent | None:
    sender = str(getattr(message, "sender", "") or "").strip()
    room_id = str(getattr(room, "room_id", "") or "").strip()
    text, reply_to_text = _matrix_message_text_and_reply(message)
    attachments = _matrix_message_attachments(message)
    if not text.strip() and not attachments:
        return None
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
        text=text,
        message_ref=_matrix_message_ref(message),
        reply_to_text=reply_to_text,
        attachments=attachments,
        raw=message,
    )


async def send_matrix_actions(client: Any, actions: list[Any]) -> list[str | None]:
    sent: list[str | None] = []
    for action in actions:
        if isinstance(action, SendText):
            response = await _send_matrix_text(client, action.chat_id, action.text, reply_to_ref=action.reply_to_ref)
            sent.append(_matrix_event_id(response))
        elif isinstance(action, SendTyping):
            await _send_matrix_typing(client, action.chat_id)
            sent.append(None)
        elif isinstance(action, SendAttachment):
            response = await _send_matrix_file_or_error_notice(
                client,
                room_id=action.chat_id,
                data=action.data,
                filename=action.filename,
                content_type=action.content_type,
                caption=action.caption,
                reply_to_ref=action.reply_to_ref,
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
                reply_to_ref=action.reply_to_ref,
            )
            sent.append(_matrix_event_id(response))
        elif isinstance(action, (NotifyLinkedIdentity, DeleteTrackedMessages)):
            sent.append(None)
    return sent


async def _send_matrix_text(client: Any, room_id: str, text: str, *, notice: bool = False, reply_to_ref: str = "") -> Any:
    msgtype = "m.notice" if notice else "m.text"
    send_message = getattr(client, "send_message", None)
    if callable(send_message):
        kwargs: dict[str, Any] = {"message_type": msgtype}
        if reply_to_ref:
            kwargs["reply_to"] = reply_to_ref
        return await send_message(room_id, text, **kwargs)
    content = {"msgtype": msgtype, "body": text}
    _add_matrix_reply_relation(content, reply_to_ref)
    return await client.room_send(
        room_id=room_id,
        message_type="m.room.message",
        content=content,
    )


async def _send_matrix_typing(client: Any, room_id: str) -> None:
    room_typing = getattr(client, "room_typing", None)
    if not callable(room_typing):
        return
    try:
        await room_typing(room_id, True, timeout=3000)
    except Exception:
        return


async def _send_matrix_file_or_error_notice(
    client: Any,
    *,
    room_id: str,
    data: bytes,
    filename: str,
    content_type: str,
    caption: str = "",
    reply_to_ref: str = "",
) -> Any:
    try:
        return await _send_matrix_file(
            client,
            room_id=room_id,
            data=data,
            filename=filename,
            content_type=content_type,
            caption=caption,
            reply_to_ref=reply_to_ref,
        )
    except Exception as exc:
        return await _send_matrix_text(
            client,
            room_id,
            f"Datei konnte nicht gesendet werden: {filename} ({exc})",
            notice=True,
            reply_to_ref=reply_to_ref,
        )


async def _send_matrix_file(
    client: Any,
    *,
    room_id: str,
    data: bytes,
    filename: str,
    content_type: str,
    caption: str = "",
    reply_to_ref: str = "",
) -> Any:
    send_message = getattr(client, "send_message", None)
    attachment = _make_niobot_file_attachment(data=data, filename=filename, content_type=content_type)
    if callable(send_message) and attachment is not None:
        kwargs: dict[str, Any] = {"file": attachment}
        if reply_to_ref:
            kwargs["reply_to"] = reply_to_ref
        return await send_message(room_id, caption or filename, **kwargs)
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
    msgtype = _matrix_msgtype_for_content_type(content_type)
    content = {
        "msgtype": msgtype,
        "body": body,
        "filename": filename,
        "url": str(content_uri),
        "info": {
            "mimetype": content_type or "application/octet-stream",
            "size": len(data),
        },
    }
    _add_matrix_reply_relation(content, reply_to_ref)
    return await client.room_send(
        room_id=room_id,
        message_type="m.room.message",
        content=content,
    )


def _make_niobot_file_attachment(*, data: bytes, filename: str, content_type: str) -> Any | None:
    try:
        from niobot.attachment import FileAttachment  # type: ignore[import-not-found]
    except Exception:
        return None
    return FileAttachment(
        BytesIO(data),
        file_name=filename,
        mime_type=content_type or "application/octet-stream",
        size_bytes=len(data),
    )


def _add_matrix_reply_relation(content: dict[str, Any], reply_to_ref: str) -> None:
    event_id = str(reply_to_ref or "").strip()
    if not event_id:
        return
    content["m.relates_to"] = {"m.in_reply_to": {"event_id": event_id}}


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


def _matrix_message_attachments(message: Any) -> tuple[IncomingAttachment, ...]:
    content = _matrix_effective_content(message)
    msgtype = str(content.get("msgtype") or "").strip()
    url = str(getattr(message, "url", "") or content.get("url") or "").strip()
    if not url:
        return ()
    if msgtype not in {"m.file", "m.image", "m.audio", "m.video"}:
        return ()
    filename = str(content.get("filename") or content.get("body") or getattr(message, "body", "") or "").strip() or "matrix-attachment.bin"
    info = content.get("info") if isinstance(content.get("info"), dict) else {}
    content_type = str(info.get("mimetype") or _matrix_content_type_for_msgtype(msgtype)).strip() or "application/octet-stream"
    return (
        IncomingAttachment(
            filename=filename,
            content_type=content_type,
            data=b"",
            base64_data=url,
        ),
    )


def _matrix_message_text_and_reply(message: Any) -> tuple[str, str | None]:
    content = _matrix_message_content(message)
    relates_to = content.get("m.relates_to") if isinstance(content.get("m.relates_to"), dict) else {}
    if relates_to.get("rel_type") == "m.replace":
        new_content = content.get("m.new_content") if isinstance(content.get("m.new_content"), dict) else {}
        return str(new_content.get("body") or content.get("body") or getattr(message, "body", "") or ""), None
    body = str(content.get("body") or getattr(message, "body", "") or "")
    in_reply_to = relates_to.get("m.in_reply_to") if isinstance(relates_to.get("m.in_reply_to"), dict) else {}
    if not in_reply_to:
        return body, None
    reply_lines: list[str] = []
    remainder: list[str] = []
    in_reply_block = True
    for line in body.splitlines():
        if in_reply_block and line.startswith(">"):
            reply_lines.append(line.lstrip("> ").rstrip())
            continue
        if in_reply_block and not line.strip():
            in_reply_block = False
            continue
        in_reply_block = False
        remainder.append(line)
    reply_text = "\n".join(line for line in reply_lines if line).strip() or None
    text = "\n".join(remainder).strip()
    return (text if text else body, reply_text)


def _matrix_message_ref(message: Any) -> str:
    content = _matrix_message_content(message)
    relates_to = content.get("m.relates_to") if isinstance(content.get("m.relates_to"), dict) else {}
    if relates_to.get("rel_type") == "m.replace":
        replacement_target = str(relates_to.get("event_id") or "").strip()
        if replacement_target:
            return replacement_target
    return str(getattr(message, "event_id", "") or "")


def _matrix_effective_content(message: Any) -> dict[str, Any]:
    content = _matrix_message_content(message)
    relates_to = content.get("m.relates_to") if isinstance(content.get("m.relates_to"), dict) else {}
    if relates_to.get("rel_type") == "m.replace" and isinstance(content.get("m.new_content"), dict):
        return content["m.new_content"]
    return content


def _matrix_message_content(message: Any) -> dict[str, Any]:
    source = getattr(message, "source", None)
    content = source.get("content", {}) if isinstance(source, dict) else {}
    return content if isinstance(content, dict) else {}


def _matrix_content_type_for_msgtype(msgtype: str) -> str:
    if msgtype == "m.image":
        return "image/*"
    if msgtype == "m.audio":
        return "audio/*"
    if msgtype == "m.video":
        return "video/*"
    return "application/octet-stream"


def _matrix_msgtype_for_content_type(content_type: str) -> str:
    normalized = str(content_type or "").strip().casefold()
    if normalized.startswith("image/"):
        return "m.image"
    if normalized.startswith("audio/"):
        return "m.audio"
    if normalized.startswith("video/"):
        return "m.video"
    return "m.file"


def _matrix_event_id(response: Any) -> str | None:
    value = getattr(response, "event_id", None)
    if value:
        return str(value)
    return None
