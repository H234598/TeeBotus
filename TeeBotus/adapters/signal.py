from __future__ import annotations

import base64
from typing import Any

from TeeBotus.runtime.accounts import signal_identity_key
from TeeBotus.runtime.actions import DeleteTrackedMessages, ExportFile, NotifyLinkedIdentity, SendAttachment, SendText, SendTyping
from TeeBotus.runtime.events import IncomingAttachment, IncomingEvent


def signal_message_to_event(
    message: Any,
    *,
    instance: str,
    adapter_slot: int,
    account_id: str = "",
    account_label: str = "signal:1",
) -> IncomingEvent | None:
    if not _signal_message_has_user_content(message):
        return None
    identity_key = signal_identity_key(
        source_uuid=str(getattr(message, "source_uuid", "") or ""),
        source_number=str(getattr(message, "source_number", "") or ""),
        source=str(getattr(message, "source", "") or ""),
    )
    attachment_names = list(getattr(message, "attachments_local_filenames", []) or [])
    attachment_data = list(getattr(message, "base64_attachments", []) or [])
    attachments = tuple(
        IncomingAttachment(
            filename=_signal_attachment_name(index, attachment_names),
            content_type=_guess_content_type(_signal_attachment_name(index, attachment_names)),
            data=_safe_b64decode(data),
            base64_data=data if isinstance(data, str) else "",
        )
        for index, data in enumerate(attachment_data)
    )
    recipient = message.recipient() if callable(getattr(message, "recipient", None)) else (getattr(message, "group", "") or getattr(message, "source", ""))
    return IncomingEvent(
        event_id=f"signal:{getattr(message, 'timestamp', '')}",
        instance=instance,
        channel="signal",
        adapter_slot=adapter_slot,
        account_id=account_id,
        identity_key=identity_key,
        chat_id=str(recipient),
        chat_type="group" if getattr(message, "group", None) else "private",
        sender_id=str(getattr(message, "source_uuid", "") or getattr(message, "source", "") or ""),
        sender_name=str(getattr(message, "source_number", "") or getattr(message, "source", "") or ""),
        sender_username="",
        sender_number=str(getattr(message, "source_number", "") or ""),
        text=str(getattr(message, "text", "") or ""),
        message_ref=str(getattr(message, "timestamp", "") or ""),
        attachments=attachments,
        raw=message,
    )


def signal_context_to_event(
    *,
    context: Any,
    instance_name: str,
    adapter_slot: int,
    account_label: str,
) -> IncomingEvent | None:
    return signal_message_to_event(context.message, instance=instance_name, adapter_slot=adapter_slot, account_id="", account_label=account_label)


async def send_signal_actions(context: Any, actions: list[Any]) -> list[int | None]:
    sent: list[int | None] = []
    typing_started = False
    try:
        for action in actions:
            if isinstance(action, SendText):
                sent.append(await context.send(action.text))
                typing_started = await _stop_signal_typing_if_started(context, typing_started)
            elif isinstance(action, SendTyping):
                await context.start_typing()
                typing_started = True
                sent.append(None)
            elif isinstance(action, SendAttachment):
                encoded = base64.b64encode(action.data).decode("ascii")
                sent.append(await context.send(action.caption, base64_attachments=[encoded]))
                typing_started = await _stop_signal_typing_if_started(context, typing_started)
            elif isinstance(action, NotifyLinkedIdentity):
                sent.append(None)
            elif isinstance(action, DeleteTrackedMessages):
                sent.append(None)
            elif isinstance(action, ExportFile):
                encoded = base64.b64encode(action.data).decode("ascii")
                sent.append(await context.send(f"Export: {action.filename}", base64_attachments=[encoded]))
                typing_started = await _stop_signal_typing_if_started(context, typing_started)
    finally:
        if typing_started:
            await _stop_signal_typing_if_started(context, typing_started)
    return sent


async def _stop_signal_typing_if_started(context: Any, typing_started: bool) -> bool:
    if not typing_started:
        return False
    stop_typing = getattr(context, "stop_typing", None)
    if callable(stop_typing):
        try:
            await stop_typing()
        except Exception:
            pass
    return False


def _signal_attachment_name(index: int, names: list[Any]) -> str:
    try:
        value = str(names[index] or "").strip()
    except IndexError:
        value = ""
    return value or f"signal-attachment-{index + 1}.bin"


def _safe_b64decode(data: Any) -> bytes:
    if not isinstance(data, str):
        return b""
    try:
        return base64.b64decode(data.encode("ascii"), validate=False)
    except Exception:
        return b""


def _guess_content_type(filename: str) -> str:
    lower = filename.casefold()
    if lower.endswith((".ogg", ".opus", ".oga")):
        return "audio/ogg"
    if lower.endswith(".mp3"):
        return "audio/mpeg"
    if lower.endswith(".wav"):
        return "audio/wav"
    if lower.endswith(".m4a"):
        return "audio/mp4"
    return "application/octet-stream"


def _signal_message_has_user_content(message: Any) -> bool:
    message_type = getattr(message, "type", None)
    type_name = getattr(message_type, "name", "")
    if type_name in {
        "CONTACT_SYNC_MESSAGE",
        "DELETE_MESSAGE",
        "GROUP_UPDATE_MESSAGE",
        "REACTION_MESSAGE",
        "READ_MESSAGE",
        "SYNC_MESSAGE",
    }:
        return False
    return bool(
        str(getattr(message, "text", "") or "")
        or (getattr(message, "base64_attachments", None) or [])
        or (getattr(message, "attachments_local_filenames", None) or [])
    )
