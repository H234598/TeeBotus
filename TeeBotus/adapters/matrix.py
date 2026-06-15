from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
from io import BytesIO
from typing import Any

from TeeBotus.runtime.accounts import matrix_identity_key
from TeeBotus.runtime.actions import (
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
    sender = _matrix_message_sender(message)
    room_id = str(getattr(room, "room_id", "") or "").strip()
    if not room_id:
        return None
    display_name = _matrix_message_display_name(message)
    try:
        identity_key = matrix_identity_key(sender, localpart=_matrix_sender_localpart(sender), display_name=display_name)
    except Exception:
        return None
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
        identity_key=identity_key,
        chat_id=room_id,
        chat_type="private" if _matrix_room_is_private(room) else "group",
        sender_id=sender,
        sender_name=display_name or sender,
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
            response = await _send_matrix_text(
                client,
                action.chat_id,
                action.text,
                reply_to_ref=action.reply_to_ref,
                mentions=list(action.mentions),
                text_mode=action.text_mode,
            )
            sent.append(_matrix_event_id(response))
        elif isinstance(action, SendTyping):
            await _send_matrix_typing(client, action.chat_id)
            sent.append(None)
        elif isinstance(action, SendReaction):
            response = await _send_matrix_reaction(client, action.chat_id, action.message_ref, action.emoji)
            sent.append(_matrix_event_id(response))
        elif isinstance(action, SendReceipt):
            await _send_matrix_receipt(client, action.chat_id, action.message_ref, action.receipt_type)
            sent.append(None)
        elif isinstance(action, SendEdit):
            response = await _send_matrix_edit(
                client,
                action.chat_id,
                action.message_ref,
                action.text,
                mentions=list(action.mentions),
                text_mode=action.text_mode,
            )
            sent.append(_matrix_event_id(response))
        elif isinstance(action, SendPoll):
            response = await _send_matrix_poll(
                client,
                action.chat_id,
                action.question,
                list(action.answers),
                action.allow_multiple_selections,
            )
            sent.append(_matrix_event_id(response))
        elif isinstance(action, SetMatrixState):
            await _set_matrix_state(client, action.chat_id, action.event_type, action.content, state_key=action.state_key)
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
                mentions=list(action.mentions),
                text_mode=action.text_mode,
                view_once=action.view_once,
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
        elif isinstance(action, (NotifyLinkedIdentity, DeleteTrackedMessages, UpdateSignalContact, UpdateSignalGroup)):
            sent.append(None)
    return sent


async def _send_matrix_text(
    client: Any,
    room_id: str,
    text: str,
    *,
    notice: bool = False,
    reply_to_ref: str = "",
    mentions: list[dict[str, Any]] | None = None,
    text_mode: str = "",
) -> Any:
    msgtype = "m.notice" if notice else "m.text"
    send_message = getattr(client, "send_message", None)
    if callable(send_message) and not mentions and not _matrix_is_html_text_mode(text_mode):
        kwargs: dict[str, Any] = {"message_type": msgtype, "clean_mentions": True}
        if reply_to_ref:
            kwargs["reply_to"] = reply_to_ref
        response = await send_message(room_id, text, **kwargs)
        _raise_matrix_response_error(response)
        return response
    content = _matrix_text_content(msgtype, text, text_mode=text_mode)
    _add_matrix_reply_relation(content, reply_to_ref)
    _add_matrix_mentions(content, mentions or [])
    response = await client.room_send(
        room_id=room_id,
        message_type="m.room.message",
        content=content,
    )
    _raise_matrix_response_error(response)
    return response


async def _send_matrix_typing(client: Any, room_id: str) -> None:
    room_typing = getattr(client, "room_typing", None)
    if not callable(room_typing):
        return
    try:
        await room_typing(room_id, True, timeout=3000)
    except Exception:
        return


async def _send_matrix_reaction(client: Any, room_id: str, event_id: str, emoji: str) -> Any:
    target = str(event_id or "").strip()
    key = str(emoji or "").strip()
    if not target:
        raise RuntimeError("Matrix reaction requires a message_ref")
    if not key:
        raise RuntimeError("Matrix reaction requires an emoji")
    add_reaction = getattr(client, "add_reaction", None)
    if callable(add_reaction):
        response = await add_reaction(room_id, target, key)
        _raise_matrix_response_error(response)
        return response
    response = await client.room_send(
        room_id=room_id,
        message_type="m.reaction",
        content={
            "m.relates_to": {
                "rel_type": "m.annotation",
                "event_id": target,
                "key": key,
            }
        },
    )
    _raise_matrix_response_error(response)
    return response


async def _send_matrix_receipt(client: Any, room_id: str, event_id: str, receipt_type: str) -> None:
    target = str(event_id or "").strip()
    if not target:
        raise RuntimeError("Matrix receipt requires a message_ref")
    update_receipt_marker = getattr(client, "update_receipt_marker", None)
    if callable(update_receipt_marker):
        response = await update_receipt_marker(room_id, target, receipt_type=_matrix_receipt_type(receipt_type))
        _raise_matrix_response_error(response)
        return
    room_read_markers = getattr(client, "room_read_markers", None)
    if callable(room_read_markers):
        response = await room_read_markers(room_id, target, read_event=target)
        _raise_matrix_response_error(response)


async def _send_matrix_edit(
    client: Any,
    room_id: str,
    event_id: str,
    text: str,
    *,
    mentions: list[dict[str, Any]] | None = None,
    text_mode: str = "",
) -> Any:
    target = str(event_id or "").strip()
    if not target:
        raise RuntimeError("Matrix edit requires a message_ref")
    body = str(text or "")
    edit_message = getattr(client, "edit_message", None)
    if callable(edit_message) and not mentions and not _matrix_is_html_text_mode(text_mode):
        response = await edit_message(room_id, target, body, message_type="m.text", clean_mentions=True)
        _raise_matrix_response_error(response)
        return response
    new_content = _matrix_text_content("m.text", body, text_mode=text_mode)
    content = {
        "msgtype": "m.text",
        "body": f"* {new_content['body']}",
        "m.new_content": new_content,
        "m.relates_to": {
            "rel_type": "m.replace",
            "event_id": target,
        },
    }
    if "formatted_body" in new_content:
        content["format"] = new_content["format"]
        content["formatted_body"] = f"* {new_content['formatted_body']}"
    _add_matrix_mentions(content, mentions or [])
    _add_matrix_mentions(content["m.new_content"], mentions or [])
    response = await client.room_send(
        room_id=room_id,
        message_type="m.room.message",
        content=content,
    )
    _raise_matrix_response_error(response)
    return response


async def _send_matrix_poll(
    client: Any,
    room_id: str,
    question: str,
    answers: list[str],
    allow_multiple_selections: bool,
) -> Any:
    clean_question = str(question or "").strip()
    clean_answers = [str(answer or "").strip() for answer in answers if str(answer or "").strip()]
    if not clean_question:
        raise RuntimeError("Matrix poll requires a question")
    if len(clean_answers) < 2:
        raise RuntimeError("Matrix poll requires at least two answers")
    fallback = _matrix_poll_fallback(clean_question, clean_answers, allow_multiple_selections)
    content = {
        "msgtype": "org.matrix.msc3381.poll.start",
        "body": fallback,
        "org.matrix.msc1767.text": fallback,
        "org.matrix.msc3381.poll.start": {
            "max_selections": len(clean_answers) if allow_multiple_selections else 1,
            "question": {"org.matrix.msc1767.text": clean_question},
            "answers": [
                {"id": str(index), "org.matrix.msc1767.text": answer}
                for index, answer in enumerate(clean_answers, start=1)
            ],
        },
    }
    response = await client.room_send(
        room_id=room_id,
        message_type="m.room.message",
        content=content,
    )
    _raise_matrix_response_error(response)
    return response


def _matrix_poll_fallback(question: str, answers: list[str], allow_multiple_selections: bool) -> str:
    mode = "Mehrfachauswahl" if allow_multiple_selections else "Einzelauswahl"
    options = "\n".join(f"{index}. {answer}" for index, answer in enumerate(answers, start=1))
    return f"{question}\n({mode})\n{options}"


async def _set_matrix_state(client: Any, room_id: str, event_type: str, content: dict[str, Any], *, state_key: str = "") -> None:
    normalized_event_type = str(event_type or "").strip()
    if not normalized_event_type:
        raise RuntimeError("Matrix state event requires an event_type")
    if not isinstance(content, dict):
        raise RuntimeError("Matrix state event content must be a dict")
    update_room_topic = getattr(client, "update_room_topic", None)
    topic = str(content.get("topic") or "")
    if normalized_event_type == "m.room.topic" and not state_key and callable(update_room_topic) and topic:
        response = await update_room_topic(room_id, topic)
        _raise_matrix_response_error(response)
        return
    response = await client.room_put_state(
        room_id=room_id,
        event_type=normalized_event_type,
        content=content,
        state_key=str(state_key or ""),
    )
    _raise_matrix_response_error(response)


def _matrix_receipt_type(receipt_type: str) -> Any:
    normalized = str(receipt_type or "read").strip().casefold()
    try:
        from nio import ReceiptType  # type: ignore[import-not-found]
    except Exception:
        return normalized
    if normalized == "viewed" and hasattr(ReceiptType, "read_private"):
        return ReceiptType.read_private
    return ReceiptType.read


async def _send_matrix_file_or_error_notice(
    client: Any,
    *,
    room_id: str,
    data: bytes,
    filename: str,
    content_type: str,
    caption: str = "",
    reply_to_ref: str = "",
    mentions: list[dict[str, Any]] | None = None,
    text_mode: str = "",
    view_once: bool = False,
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
            mentions=mentions,
            text_mode=text_mode,
            view_once=view_once,
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
    mentions: list[dict[str, Any]] | None = None,
    text_mode: str = "",
    view_once: bool = False,
) -> Any:
    if view_once:
        raise RuntimeError("Matrix view_once attachments are not supported")
    send_message = getattr(client, "send_message", None)
    attachment = _make_niobot_file_attachment(data=data, filename=filename, content_type=content_type)
    encrypt_upload = _matrix_room_is_encrypted(client, room_id)
    if callable(send_message) and attachment is not None and not mentions and not _matrix_is_html_text_mode(text_mode) and not encrypt_upload:
        kwargs: dict[str, Any] = {"file": attachment, "clean_mentions": True}
        if reply_to_ref:
            kwargs["reply_to"] = reply_to_ref
        response = await send_message(room_id, caption or filename, **kwargs)
        _raise_matrix_response_error(response)
        return response
    upload_response, _keys = await client.upload(
        BytesIO(data),
        content_type=content_type or "application/octet-stream",
        filename=filename,
        filesize=len(data),
        encrypt=encrypt_upload,
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
    if encrypt_upload:
        if not isinstance(_keys, dict):
            raise RuntimeError("Matrix encrypted upload returned no decryption metadata")
        encrypted_file = dict(_keys)
        encrypted_file["url"] = str(content_uri)
        content.pop("url", None)
        content["file"] = encrypted_file
    _add_matrix_reply_relation(content, reply_to_ref)
    _add_matrix_mentions(content, mentions or [])
    if caption and _matrix_is_html_text_mode(text_mode):
        _add_matrix_html_format(content, caption)
    response = await client.room_send(
        room_id=room_id,
        message_type="m.room.message",
        content=content,
    )
    _raise_matrix_response_error(response)
    return response


def _make_niobot_file_attachment(*, data: bytes, filename: str, content_type: str) -> Any | None:
    try:
        from niobot import attachment as niobot_attachment  # type: ignore[import-not-found]
    except Exception:
        return None
    attachment_class = _niobot_attachment_class(niobot_attachment, content_type)
    return attachment_class(
        BytesIO(data),
        file_name=filename,
        mime_type=content_type or "application/octet-stream",
        size_bytes=len(data),
    )


def _niobot_attachment_class(niobot_attachment: Any, content_type: str) -> Any:
    normalized = str(content_type or "").casefold()
    if normalized.startswith("image/") and hasattr(niobot_attachment, "ImageAttachment"):
        return niobot_attachment.ImageAttachment
    if normalized.startswith("audio/") and hasattr(niobot_attachment, "AudioAttachment"):
        return niobot_attachment.AudioAttachment
    if normalized.startswith("video/") and hasattr(niobot_attachment, "VideoAttachment"):
        return niobot_attachment.VideoAttachment
    return niobot_attachment.FileAttachment


def _add_matrix_reply_relation(content: dict[str, Any], reply_to_ref: str) -> None:
    event_id = str(reply_to_ref or "").strip()
    if not event_id:
        return
    content["m.relates_to"] = {"m.in_reply_to": {"event_id": event_id}}


def _add_matrix_mentions(content: dict[str, Any], mentions: list[dict[str, Any]]) -> None:
    user_ids: list[str] = []
    for mention in mentions:
        for key in ("user_id", "mxid", "matrix_user_id", "author"):
            value = str(mention.get(key) or "").strip()
            if value.startswith("@") and ":" in value and value not in user_ids:
                user_ids.append(value)
                break
    if user_ids:
        content["m.mentions"] = {"user_ids": user_ids}


def _matrix_text_content(msgtype: str, text: str, *, text_mode: str = "") -> dict[str, Any]:
    content = {"msgtype": msgtype, "body": str(text or "")}
    if _matrix_is_html_text_mode(text_mode):
        _add_matrix_html_format(content, str(text or ""))
    return content


def _add_matrix_html_format(content: dict[str, Any], html_text: str) -> None:
    content["body"] = _matrix_plain_body_from_html(html_text)
    content["format"] = "org.matrix.custom.html"
    content["formatted_body"] = html_text


def _matrix_is_html_text_mode(text_mode: str) -> bool:
    return str(text_mode or "").strip().casefold() in {"html", "formatted", "org.matrix.custom.html"}


def _matrix_room_is_encrypted(client: Any, room_id: str) -> bool:
    rooms = getattr(client, "rooms", None)
    room = rooms.get(room_id) if isinstance(rooms, dict) else None
    if room is None:
        get_room = getattr(client, "room", None)
        if callable(get_room):
            try:
                room = get_room(room_id)
            except Exception:
                room = None
    return bool(getattr(room, "encrypted", False))


def _matrix_plain_body_from_html(html_text: str) -> str:
    parser = _MatrixPlainTextParser()
    parser.feed(str(html_text or ""))
    parser.close()
    return parser.text.strip() or unescape(str(html_text or ""))


class _MatrixPlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    @property
    def text(self) -> str:
        return "".join(self._parts)

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "p", "div", "li"} and self._parts and not self._parts[-1].endswith("\n"):
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "div", "li"} and self._parts and not self._parts[-1].endswith("\n"):
            self._parts.append("\n")


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


def _matrix_message_sender(message: Any) -> str:
    sender = str(getattr(message, "sender", "") or "").strip()
    if sender:
        return sender
    source = getattr(message, "source", None)
    if isinstance(source, dict):
        return str(source.get("sender") or "").strip()
    return ""


def _matrix_sender_localpart(sender: str) -> str:
    value = str(sender or "").strip()
    if value.startswith("@") and ":" in value:
        return value[1:].split(":", maxsplit=1)[0]
    return value


def _matrix_message_display_name(message: Any) -> str:
    for attr in ("sender_name", "display_name"):
        value = str(getattr(message, attr, "") or "").strip()
        if value:
            return value
    source = getattr(message, "source", None)
    unsigned = source.get("unsigned") if isinstance(source, dict) else None
    if isinstance(unsigned, dict):
        value = str(unsigned.get("sender_display_name") or "").strip()
        if value:
            return value
    content = source.get("content") if isinstance(source, dict) else None
    if isinstance(content, dict):
        return str(content.get("displayname") or "").strip()
    return ""


def _matrix_message_attachments(message: Any) -> tuple[IncomingAttachment, ...]:
    content = _matrix_effective_content(message)
    msgtype = str(content.get("msgtype") or "").strip()
    file_info = content.get("file") if isinstance(content.get("file"), dict) else {}
    url = str(getattr(message, "url", "") or content.get("url") or file_info.get("url") or "").strip()
    if not url:
        return ()
    if msgtype not in {"m.file", "m.image", "m.audio", "m.video"}:
        return ()
    filename = str(content.get("filename") or content.get("body") or getattr(message, "body", "") or "").strip() or "matrix-attachment.bin"
    info = content.get("info") if isinstance(content.get("info"), dict) else {}
    content_type = str(info.get("mimetype") or file_info.get("mimetype") or _matrix_content_type_for_msgtype(msgtype)).strip() or "application/octet-stream"
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


def _raise_matrix_response_error(response: Any) -> None:
    if _matrix_event_id(response):
        return
    message = str(getattr(response, "message", "") or "").strip()
    if not message:
        return
    status_code = str(getattr(response, "status_code", "") or "").strip()
    detail = f"{status_code}: {message}" if status_code else message
    raise RuntimeError(detail)
