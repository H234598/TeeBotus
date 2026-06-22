from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
from inspect import isawaitable
from typing import Any

from TeeBotus.runtime.accounts import signal_identity_key
from TeeBotus.runtime.action_buttons import text_with_button_fallback
from TeeBotus.runtime.actions import (
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
from TeeBotus.runtime.events import IncomingAttachment, IncomingEvent, IncomingLinkPreview


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
    source_uuid = str(getattr(message, "source_uuid", "") or "")
    source_number = str(getattr(message, "source_number", "") or "")
    source = str(getattr(message, "source", "") or "")
    if not (source_uuid.strip() or source_number.strip() or source.strip()):
        return None
    identity_key = signal_identity_key(
        source_uuid=source_uuid,
        source_number=source_number,
        source=source,
    )
    attachment_names = list(getattr(message, "attachments_local_filenames", []) or [])
    remote_attachment_names = _signal_raw_attachment_filenames(message)
    attachment_data = list(getattr(message, "base64_attachments", []) or [])
    attachments = tuple(
        IncomingAttachment(
            filename=_signal_attachment_name(index, attachment_names, remote_attachment_names),
            content_type=_guess_content_type(_signal_attachment_name(index, attachment_names, remote_attachment_names)),
            data=_safe_b64decode(_signal_attachment_data(index, attachment_data)),
            base64_data=_signal_attachment_data(index, attachment_data),
            view_once=bool(getattr(message, "view_once", False)),
        )
        for index in range(max(len(attachment_names), len(remote_attachment_names), len(attachment_data)))
    )
    recipient = _signal_message_recipient(message)
    recipient = str(recipient or "").strip()
    if not recipient:
        return None
    return IncomingEvent(
        event_id=f"signal:{getattr(message, 'timestamp', '')}",
        instance=instance,
        channel="signal",
        adapter_slot=adapter_slot,
        account_id=account_id,
        identity_key=identity_key,
        chat_id=recipient,
        chat_type="group" if getattr(message, "group", None) else "private",
        sender_id=str(getattr(message, "source_uuid", "") or getattr(message, "source", "") or ""),
        sender_name=str(getattr(message, "source_number", "") or getattr(message, "source", "") or ""),
        sender_username="",
        sender_number=str(getattr(message, "source_number", "") or ""),
        text=str(getattr(message, "text", "") or ""),
        message_ref=_signal_message_ref(message),
        reply_to_text=_signal_quote_text(message),
        attachments=attachments,
        link_previews=_signal_link_previews(message),
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
    typing_target: str | None = None
    try:
        for action in actions:
            if isinstance(action, SendText):
                sent.append(
                    _signal_required_timestamp(
                        await _send_signal_text(
                            context,
                            text_with_button_fallback(action.text, action.buttons),
                            chat_id=action.chat_id,
                            reply_to_ref=action.reply_to_ref,
                            mentions=list(action.mentions) or None,
                            text_mode=_signal_text_mode(action),
                            view_once=action.view_once,
                            link_preview=action.link_preview,
                        ),
                        "Signal text send",
                    )
                )
                typing_target = await _stop_signal_typing_if_started(context, typing_target)
            elif isinstance(action, DelaySeconds):
                typing_target = await _stop_signal_typing_if_started(context, typing_target)
                await asyncio.sleep(max(0.0, float(action.seconds)))
                sent.append(None)
            elif isinstance(action, SendTyping):
                typing_target = await _stop_signal_typing_if_started(context, typing_target)
                typing_target = await _start_signal_typing(context, action.chat_id)
                sent.append(None)
            elif isinstance(action, SendReaction):
                await _send_signal_reaction(context, action.chat_id, action.message_ref, action.emoji)
                sent.append(None)
            elif isinstance(action, SendReceipt):
                await _send_signal_receipt(context, action.chat_id, action.message_ref, action.receipt_type)
                sent.append(None)
            elif isinstance(action, SendEdit):
                sent.append(
                    _signal_required_timestamp(
                        await _send_signal_edit(
                            context,
                            action.chat_id,
                            action.message_ref,
                            action.text,
                            mentions=list(action.mentions) or None,
                            text_mode=action.text_mode,
                            view_once=action.view_once,
                            link_preview=action.link_preview,
                        ),
                        "Signal edit send",
                    )
                )
                typing_target = await _stop_signal_typing_if_started(context, typing_target)
            elif isinstance(action, SendPoll):
                sent.append(
                    _signal_required_timestamp(
                        await _send_signal_poll(
                            context,
                            action.chat_id,
                            action.question,
                            list(action.answers),
                            action.allow_multiple_selections,
                        ),
                        "Signal poll send",
                    )
                )
                typing_target = await _stop_signal_typing_if_started(context, typing_target)
            elif isinstance(action, SendAttachment):
                encoded = base64.b64encode(action.data).decode("ascii")
                sent.append(
                    _signal_required_timestamp(
                        await _send_signal_text(
                            context,
                            action.caption or action.filename,
                            chat_id=action.chat_id,
                            base64_attachments=[encoded],
                            reply_to_ref=action.reply_to_ref,
                            mentions=list(action.mentions) or None,
                            text_mode=action.text_mode,
                            view_once=action.view_once,
                            link_preview=action.link_preview,
                        ),
                        "Signal attachment send",
                    )
                )
                typing_target = await _stop_signal_typing_if_started(context, typing_target)
            elif isinstance(action, NotifyLinkedIdentity):
                sent.append(None)
            elif isinstance(action, DeleteTrackedMessages):
                sent.append(None)
            elif isinstance(action, SetMatrixState):
                sent.append(None)
            elif isinstance(action, UpdateSignalContact):
                await _update_signal_contact(context, action)
                sent.append(None)
            elif isinstance(action, UpdateSignalGroup):
                await _update_signal_group(context, action)
                sent.append(None)
            elif isinstance(action, ExportFile):
                encoded = base64.b64encode(action.data).decode("ascii")
                sent.append(
                    _signal_required_timestamp(
                        await _send_signal_text(
                            context,
                            action.caption or f"Export: {action.filename}",
                            chat_id=action.chat_id,
                            base64_attachments=[encoded],
                            reply_to_ref=action.reply_to_ref,
                        ),
                        "Signal export send",
                    )
                )
                typing_target = await _stop_signal_typing_if_started(context, typing_target)
            else:
                sent.append(None)
    finally:
        if typing_target is not None:
            await _stop_signal_typing_if_started(context, typing_target)
    return sent


async def _update_signal_contact(context: Any, action: UpdateSignalContact) -> None:
    target = str(action.chat_id or "").strip()
    if not target:
        raise RuntimeError("Signal contact update requires a chat_id")
    bot = getattr(context, "bot", None)
    update_contact = getattr(bot, "update_contact", None)
    if not callable(update_contact):
        raise RuntimeError("SignalBot.update_contact is required to update a contact")
    await _maybe_await(update_contact(
        target,
        expiration_in_seconds=action.expiration_in_seconds,
        name=action.name,
    ))


async def _update_signal_group(context: Any, action: UpdateSignalGroup) -> None:
    target = str(action.chat_id or "").strip()
    if not target:
        raise RuntimeError("Signal group update requires a chat_id")
    bot = getattr(context, "bot", None)
    update_group = getattr(bot, "update_group", None)
    if not callable(update_group):
        raise RuntimeError("SignalBot.update_group is required to update a group")
    target = _signal_group_update_target(bot, target)
    await _maybe_await(update_group(
        target,
        base64_avatar=action.base64_avatar,
        description=action.description,
        expiration_in_seconds=action.expiration_in_seconds,
        name=action.name,
    ))


def _signal_group_update_target(bot: Any, group_id: str) -> str:
    target = str(group_id or "").strip()
    get_group = getattr(bot, "get_group", None)
    if not callable(get_group):
        return target
    try:
        group = get_group(target)
    except Exception:
        return target
    if not isinstance(group, dict):
        return target
    resolved = str(group.get("id") or "").strip()
    return resolved or target


async def _send_signal_text(
    context: Any,
    text: str,
    *,
    chat_id: str = "",
    base64_attachments: list[str] | None = None,
    reply_to_ref: str = "",
    mentions: list[dict[str, Any]] | None = None,
    text_mode: str = "",
    view_once: bool = False,
    link_preview: Any | None = None,
) -> int:
    send_kwargs = _signal_send_kwargs(
        base64_attachments=base64_attachments,
        include_base64_attachments=True,
        mentions=mentions,
        text_mode=text_mode,
        view_once=view_once,
        link_preview=link_preview,
    )
    target = str(chat_id or "").strip()
    current_recipient = _signal_context_recipient(context)
    if target and current_recipient and target != current_recipient:
        bot = getattr(context, "bot", None)
        send = getattr(bot, "send", None)
        if not callable(send):
            raise RuntimeError(f"SignalBot.send is required to send to {target}")
        return await _maybe_await(send(target, text, **send_kwargs))
    if _signal_can_use_context_reply(context, reply_to_ref):
        reply = getattr(context, "reply", None)
        return await _maybe_await(reply(text, **send_kwargs))
    quote = _signal_quote_kwargs_for_context(context, reply_to_ref)
    if quote:
        bot = getattr(context, "bot", None)
        send = getattr(bot, "send", None)
        message = getattr(context, "message", None)
        recipient = _signal_message_recipient(message)
        if callable(send) and recipient:
            return await _maybe_await(send(recipient, text, **send_kwargs, **quote))
    return await _maybe_await(context.send(text, **send_kwargs))


def _signal_context_recipient(context: Any) -> str:
    message = getattr(context, "message", None)
    return _signal_message_recipient(message)


def _signal_message_recipient(message: Any) -> str:
    sync_recipient = _signal_raw_sync_recipient(message)
    if sync_recipient:
        return sync_recipient
    recipient_method = getattr(message, "recipient", None)
    if callable(recipient_method):
        try:
            return str(recipient_method() or "").strip()
        except Exception:
            return ""
    return str(getattr(message, "group", "") or getattr(message, "source", "") or "").strip()


async def _start_signal_typing(context: Any, chat_id: str) -> str:
    target = str(chat_id or "").strip()
    current_recipient = _signal_context_recipient(context)
    if target and current_recipient and target != current_recipient:
        bot = getattr(context, "bot", None)
        start_typing = getattr(bot, "start_typing", None)
        if not callable(start_typing):
            raise RuntimeError(f"SignalBot.start_typing is required to type in {target}")
        await _maybe_await(start_typing(target))
        return target
    await _maybe_await(context.start_typing())
    return ""


async def _send_signal_reaction(context: Any, chat_id: str, message_ref: str, emoji: str) -> None:
    _require_signal_current_message_action(context, chat_id, message_ref, "reaction")
    key = str(emoji or "").strip()
    if not key:
        raise RuntimeError("Signal reaction requires an emoji")
    react = getattr(context, "react", None)
    if callable(react):
        await _maybe_await(react(key))
        return
    bot = getattr(context, "bot", None)
    bot_react = getattr(bot, "react", None)
    message = getattr(context, "message", None)
    if callable(bot_react) and message is not None:
        await _maybe_await(bot_react(message, key))
        return
    raise RuntimeError("SignalBot react API is required to send a reaction")


async def _send_signal_receipt(context: Any, chat_id: str, message_ref: str, receipt_type: str) -> None:
    _require_signal_current_message_action(context, chat_id, message_ref, "receipt")
    normalized = str(receipt_type or "read").strip().casefold()
    if normalized not in {"read", "viewed"}:
        normalized = "read"
    receipt = getattr(context, "receipt", None)
    if callable(receipt):
        await _maybe_await(receipt(normalized))
        return
    bot = getattr(context, "bot", None)
    bot_receipt = getattr(bot, "receipt", None)
    message = getattr(context, "message", None)
    if callable(bot_receipt) and message is not None:
        await _maybe_await(bot_receipt(message, normalized))
        return
    raise RuntimeError("SignalBot receipt API is required to send a receipt")


async def _send_signal_edit(
    context: Any,
    chat_id: str,
    message_ref: str,
    text: str,
    *,
    mentions: list[dict[str, Any]] | None = None,
    text_mode: str = "",
    view_once: bool = False,
    link_preview: Any | None = None,
) -> int:
    target = str(chat_id or "").strip()
    current_recipient = _signal_context_recipient(context)
    timestamp = _signal_edit_timestamp(message_ref)
    send_kwargs = _signal_send_kwargs(
        base64_attachments=None,
        include_base64_attachments=False,
        mentions=mentions,
        text_mode=text_mode,
        view_once=view_once,
        link_preview=link_preview,
    )
    if target and current_recipient and target != current_recipient:
        bot = getattr(context, "bot", None)
        send = getattr(bot, "send", None)
        if not callable(send):
            raise RuntimeError(f"SignalBot.send is required to edit in {target}")
        return await _maybe_await(send(target, text, **send_kwargs, edit_timestamp=timestamp))
    current_ref = _signal_message_ref(getattr(context, "message", None))
    edit = getattr(context, "edit", None)
    if callable(edit) and current_ref and current_ref == str(message_ref or "").strip():
        return await _maybe_await(edit(text, timestamp, **send_kwargs))
    bot = getattr(context, "bot", None)
    send = getattr(bot, "send", None)
    recipient = current_recipient or target
    if callable(send) and recipient:
        return await _maybe_await(send(recipient, text, **send_kwargs, edit_timestamp=timestamp))
    raise RuntimeError("SignalBot edit API is required to edit a message")


def _signal_edit_timestamp(message_ref: str) -> int:
    ref = str(message_ref or "").strip()
    if not ref:
        raise RuntimeError("Signal edit requires a message_ref")
    try:
        return int(ref)
    except ValueError as exc:
        raise RuntimeError("Signal edit requires a numeric message_ref") from exc


def _signal_required_timestamp(value: Any, operation: str) -> int:
    try:
        timestamp = int(str(value or "").strip())
    except ValueError as exc:
        raise RuntimeError(f"{operation} returned no numeric timestamp") from exc
    if timestamp <= 0:
        raise RuntimeError(f"{operation} returned no numeric timestamp")
    return timestamp


def _signal_send_kwargs(
    *,
    base64_attachments: list[str] | None,
    include_base64_attachments: bool,
    mentions: list[dict[str, Any]] | None,
    text_mode: str,
    view_once: bool,
    link_preview: Any | None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if include_base64_attachments or base64_attachments is not None:
        kwargs["base64_attachments"] = base64_attachments
    if mentions:
        kwargs["mentions"] = mentions
    if text_mode:
        kwargs["text_mode"] = text_mode
    if view_once:
        kwargs["view_once"] = True
    if link_preview is not None:
        kwargs["link_preview"] = _coerce_signal_link_preview(link_preview)
    return kwargs


def _signal_text_mode(action: Any) -> str:
    mode = str(getattr(action, "text_mode", "") or "").strip()
    if getattr(action, "formatted_text", "") and mode.casefold() in {"html", "formatted", "org.matrix.custom.html"}:
        return ""
    return mode


def _coerce_signal_link_preview(link_preview: Any) -> Any:
    if not isinstance(link_preview, dict):
        return link_preview
    try:
        from signalbot import LinkPreview  # type: ignore[import-not-found]
    except Exception:
        return link_preview
    title = str(link_preview.get("title") or "").strip()
    url = str(link_preview.get("url") or "").strip()
    if not title or not url:
        raise RuntimeError("Signal link_preview requires title and url")
    return LinkPreview(
        base64_thumbnail=link_preview.get("base64_thumbnail"),
        title=title,
        description=link_preview.get("description"),
        url=url,
        id=link_preview.get("id"),
    )


async def _send_signal_poll(
    context: Any,
    chat_id: str,
    question: str,
    answers: list[str],
    allow_multiple_selections: bool,
) -> int:
    target = str(chat_id or "").strip()
    receiver = target or _signal_context_recipient(context)
    if not receiver:
        raise RuntimeError("Signal poll requires a chat_id")
    clean_question = str(question or "").strip()
    clean_answers = [str(answer or "").strip() for answer in answers if str(answer or "").strip()]
    if not clean_question:
        raise RuntimeError("Signal poll requires a question")
    if len(clean_answers) < 2:
        raise RuntimeError("Signal poll requires at least two answers")
    bot = getattr(context, "bot", None)
    poll = getattr(bot, "poll", None)
    if not callable(poll):
        raise RuntimeError("SignalBot.poll is required to send a poll")
    return await _maybe_await(poll(receiver, clean_question, clean_answers, allow_multiple_selections=allow_multiple_selections))


def _require_signal_current_message_action(context: Any, chat_id: str, message_ref: str, action_name: str) -> None:
    target = str(chat_id or "").strip()
    current_recipient = _signal_context_recipient(context)
    if target and current_recipient and target != current_recipient:
        raise RuntimeError(f"Signal {action_name} can only target the current message recipient")
    ref = str(message_ref or "").strip()
    if not ref:
        raise RuntimeError(f"Signal {action_name} requires a message_ref")
    current_ref = _signal_message_ref(getattr(context, "message", None))
    if ref and current_ref and ref != current_ref:
        raise RuntimeError(f"Signal {action_name} can only target the current message")
    if not current_ref:
        raise RuntimeError(f"Signal {action_name} requires the current message")


def _signal_can_use_context_reply(context: Any, reply_to_ref: str) -> bool:
    ref = str(reply_to_ref or "").strip()
    if not ref:
        return False
    message = getattr(context, "message", None)
    timestamp = str(getattr(message, "timestamp", "") or "").strip()
    return bool(timestamp and timestamp == ref and callable(getattr(context, "reply", None)))


def _signal_quote_kwargs_for_context(context: Any, reply_to_ref: str) -> dict[str, Any]:
    ref = str(reply_to_ref or "").strip()
    if not ref:
        return {}
    message = getattr(context, "message", None)
    timestamp = _signal_message_ref(message)
    if not timestamp or timestamp != ref:
        return {}
    try:
        quote_timestamp = int(timestamp)
    except ValueError:
        return {}
    quote_author = str(getattr(message, "source", "") or getattr(message, "source_uuid", "") or "").strip()
    quote_message = str(getattr(message, "text", "") or "").strip()
    if not quote_author or not quote_message:
        return {}
    quote: dict[str, Any] = {
        "quote_author": quote_author,
        "quote_message": quote_message,
        "quote_timestamp": quote_timestamp,
    }
    quote_mentions = _signal_quote_mentions_for_context(context)
    if quote_mentions:
        quote["quote_mentions"] = quote_mentions
    return quote


def _signal_quote_mentions_for_context(context: Any) -> list[dict[str, Any]] | None:
    message = getattr(context, "message", None)
    mentions = getattr(message, "mentions", None)
    if not mentions:
        return None
    convert = getattr(context, "_convert_receive_mentions_into_send_mentions", None)
    if callable(convert):
        try:
            converted = convert(mentions)
        except Exception:
            converted = None
        if isinstance(converted, list) and converted:
            return converted
    if isinstance(mentions, list) and all(isinstance(mention, dict) for mention in mentions):
        return mentions
    return None


def _signal_message_ref(message: Any) -> str:
    message_type = getattr(message, "type", None)
    type_name = getattr(message_type, "name", "")
    if type_name == "EDIT_MESSAGE":
        target = str(getattr(message, "target_sent_timestamp", "") or "").strip()
        if target:
            return target
    return str(getattr(message, "timestamp", "") or "").strip()


async def _stop_signal_typing_if_started(context: Any, typing_target: str | None) -> None:
    if typing_target is None:
        return None
    if typing_target:
        bot = getattr(context, "bot", None)
        stop_typing = getattr(bot, "stop_typing", None)
    else:
        stop_typing = getattr(context, "stop_typing", None)
    if callable(stop_typing):
        try:
            if typing_target:
                await _maybe_await(stop_typing(typing_target))
            else:
                await _maybe_await(stop_typing())
        except Exception:
            pass
    return None


async def _maybe_await(value: Any) -> Any:
    if isawaitable(value):
        return await value
    return value


def _signal_attachment_name(index: int, names: list[Any], remote_names: list[Any] | None = None) -> str:
    if remote_names is not None:
        try:
            remote_value = str(remote_names[index] or "").strip()
        except IndexError:
            remote_value = ""
        if remote_value:
            return remote_value
    try:
        value = str(names[index] or "").strip()
    except IndexError:
        value = ""
    return value or f"signal-attachment-{index + 1}.bin"


def _signal_raw_attachment_filenames(message: Any) -> list[str]:
    raw_message = getattr(message, "raw_message", None)
    if not isinstance(raw_message, str) or not raw_message.strip():
        return []
    try:
        payload = json.loads(raw_message)
    except (TypeError, ValueError):
        return []
    envelope = payload.get("envelope") if isinstance(payload, dict) else {}
    if not isinstance(envelope, dict):
        return []
    data_message = _signal_raw_data_message(envelope)
    attachments = data_message.get("attachments") if isinstance(data_message, dict) else []
    if not isinstance(attachments, list):
        return []
    filenames: list[str] = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            filenames.append("")
            continue
        filenames.append(str(attachment.get("filename") or "").strip())
    return filenames


def _signal_raw_data_message(envelope: dict[str, Any]) -> dict[str, Any]:
    data_message = envelope.get("dataMessage")
    if isinstance(data_message, dict):
        return data_message
    edit_message = envelope.get("editMessage")
    if isinstance(edit_message, dict) and isinstance(edit_message.get("dataMessage"), dict):
        return edit_message["dataMessage"]
    sync_message = envelope.get("syncMessage")
    if isinstance(sync_message, dict):
        sent_message = sync_message.get("sentMessage")
        if isinstance(sent_message, dict):
            if isinstance(sent_message.get("editMessage"), dict) and isinstance(sent_message["editMessage"].get("dataMessage"), dict):
                return sent_message["editMessage"]["dataMessage"]
            return sent_message
    return {}


def _signal_raw_sync_recipient(message: Any) -> str:
    message_type = getattr(message, "type", None)
    if getattr(message_type, "name", "") != "SYNC_MESSAGE":
        return ""
    raw_message = getattr(message, "raw_message", None)
    if not isinstance(raw_message, str) or not raw_message.strip():
        return ""
    try:
        payload = json.loads(raw_message)
    except (TypeError, ValueError):
        return ""
    envelope = payload.get("envelope") if isinstance(payload, dict) else {}
    sync_message = envelope.get("syncMessage") if isinstance(envelope, dict) else {}
    sent_message = sync_message.get("sentMessage") if isinstance(sync_message, dict) else {}
    if not isinstance(sent_message, dict):
        return ""
    for key in ("destination", "destinationUuid", "destinationNumber"):
        value = str(sent_message.get(key) or "").strip()
        if value:
            return value
    return ""


def _safe_b64decode(data: Any) -> bytes:
    if not isinstance(data, str):
        return b""
    try:
        return base64.b64decode(data.encode("ascii"), validate=False)
    except Exception:
        return b""


def _signal_attachment_data(index: int, values: list[Any]) -> str:
    try:
        value = values[index]
    except IndexError:
        return ""
    return value if isinstance(value, str) else ""


def _signal_quote_text(message: Any) -> str | None:
    quote = getattr(message, "quote", None)
    if quote is None:
        return None
    text = str(getattr(quote, "text", "") or "").strip()
    return text or None


def _signal_link_previews(message: Any) -> tuple[IncomingLinkPreview, ...]:
    previews = getattr(message, "link_previews", None) or []
    mapped: list[IncomingLinkPreview] = []
    for preview in previews:
        title = str(getattr(preview, "title", "") or "").strip()
        url = str(getattr(preview, "url", "") or "").strip()
        if not title and not url:
            continue
        mapped.append(
            IncomingLinkPreview(
                title=title,
                url=url,
                description=str(getattr(preview, "description", "") or "").strip(),
                base64_thumbnail=str(getattr(preview, "base64_thumbnail", "") or "").strip(),
                id=str(getattr(preview, "id", "") or "").strip(),
            )
        )
    return tuple(mapped)


def _guess_content_type(filename: str) -> str:
    guessed, _encoding = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def _signal_message_has_user_content(message: Any) -> bool:
    message_type = getattr(message, "type", None)
    type_name = getattr(message_type, "name", "")
    text = str(getattr(message, "text", "") or "").strip()
    if type_name == "SYNC_MESSAGE":
        return text.startswith("/") and bool(_signal_raw_sync_recipient(message))
    if type_name in {
        "CONTACT_SYNC_MESSAGE",
        "DELETE_MESSAGE",
        "GROUP_UPDATE_MESSAGE",
        "REACTION_MESSAGE",
        "READ_MESSAGE",
    }:
        return False
    return bool(
        text
        or (getattr(message, "base64_attachments", None) or [])
        or (getattr(message, "attachments_local_filenames", None) or [])
        or (getattr(message, "link_previews", None) or [])
        or _signal_raw_attachment_filenames(message)
    )
