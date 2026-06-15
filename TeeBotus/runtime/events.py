from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Channel = Literal["telegram", "signal", "matrix"]
ChatType = Literal["private", "group", "unknown"]


@dataclass(frozen=True)
class IncomingAttachment:
    data: bytes = b""
    filename: str = ""
    content_type: str = "application/octet-stream"
    base64_data: str = ""
    view_once: bool = False


@dataclass(frozen=True)
class IncomingLinkPreview:
    title: str = ""
    url: str = ""
    description: str = ""
    base64_thumbnail: str = ""
    id: str = ""


@dataclass(frozen=True, init=False)
class IncomingEvent:
    event_id: str
    instance: str
    channel: Channel
    adapter_slot: int
    account_id: str
    identity_key: str
    chat_id: str
    chat_type: ChatType
    sender_id: str
    text: str
    message_ref: str
    sender_name: str
    sender_username: str
    sender_number: str
    reply_to_text: str | None
    attachments: tuple[IncomingAttachment, ...]
    link_previews: tuple[IncomingLinkPreview, ...]
    raw: Any

    def __init__(
        self,
        event_id: str,
        channel: Channel,
        adapter_slot: int,
        identity_key: str,
        chat_id: str,
        chat_type: ChatType,
        sender_id: str,
        text: str,
        message_ref: str,
        *,
        instance: str = "",
        instance_name: str = "",
        account_id: str = "",
        account_label: str = "",
        sender_name: str = "",
        sender_username: str = "",
        sender_number: str = "",
        reply_to_text: str | None = None,
        attachments: tuple[IncomingAttachment, ...] = (),
        link_previews: tuple[IncomingLinkPreview, ...] = (),
        raw: Any = None,
    ) -> None:
        object.__setattr__(self, "event_id", event_id)
        object.__setattr__(self, "instance", instance or instance_name)
        object.__setattr__(self, "channel", channel)
        object.__setattr__(self, "adapter_slot", adapter_slot)
        object.__setattr__(self, "account_id", account_id)
        object.__setattr__(self, "identity_key", identity_key)
        object.__setattr__(self, "chat_id", chat_id)
        object.__setattr__(self, "chat_type", chat_type)
        object.__setattr__(self, "sender_id", sender_id)
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "message_ref", message_ref)
        object.__setattr__(self, "sender_name", sender_name)
        object.__setattr__(self, "sender_username", sender_username)
        object.__setattr__(self, "sender_number", sender_number)
        object.__setattr__(self, "reply_to_text", reply_to_text)
        object.__setattr__(self, "attachments", attachments)
        object.__setattr__(self, "link_previews", link_previews)
        object.__setattr__(self, "raw", raw)


    def with_account(self, account_id: str) -> "IncomingEvent":
        return IncomingEvent(
            event_id=self.event_id,
            instance=self.instance,
            channel=self.channel,
            adapter_slot=self.adapter_slot,
            account_id=account_id,
            identity_key=self.identity_key,
            chat_id=self.chat_id,
            chat_type=self.chat_type,
            sender_id=self.sender_id,
            sender_name=self.sender_name,
            sender_username=self.sender_username,
            sender_number=self.sender_number,
            text=self.text,
            message_ref=self.message_ref,
            reply_to_text=self.reply_to_text,
            attachments=self.attachments,
            link_previews=self.link_previews,
            raw=self.raw,
        )

    def with_attachments(self, attachments: tuple[IncomingAttachment, ...]) -> "IncomingEvent":
        return IncomingEvent(
            event_id=self.event_id,
            instance=self.instance,
            channel=self.channel,
            adapter_slot=self.adapter_slot,
            account_id=self.account_id,
            identity_key=self.identity_key,
            chat_id=self.chat_id,
            chat_type=self.chat_type,
            sender_id=self.sender_id,
            sender_name=self.sender_name,
            sender_username=self.sender_username,
            sender_number=self.sender_number,
            text=self.text,
            message_ref=self.message_ref,
            reply_to_text=self.reply_to_text,
            attachments=attachments,
            link_previews=self.link_previews,
            raw=self.raw,
        )

    def with_link_previews(self, link_previews: tuple[IncomingLinkPreview, ...]) -> "IncomingEvent":
        return IncomingEvent(
            event_id=self.event_id,
            instance=self.instance,
            channel=self.channel,
            adapter_slot=self.adapter_slot,
            account_id=self.account_id,
            identity_key=self.identity_key,
            chat_id=self.chat_id,
            chat_type=self.chat_type,
            sender_id=self.sender_id,
            sender_name=self.sender_name,
            sender_username=self.sender_username,
            sender_number=self.sender_number,
            text=self.text,
            message_ref=self.message_ref,
            reply_to_text=self.reply_to_text,
            attachments=self.attachments,
            link_previews=link_previews,
            raw=self.raw,
        )

    def with_reply_to_text(self, reply_to_text: str | None) -> "IncomingEvent":
        return IncomingEvent(
            event_id=self.event_id,
            instance=self.instance,
            channel=self.channel,
            adapter_slot=self.adapter_slot,
            account_id=self.account_id,
            identity_key=self.identity_key,
            chat_id=self.chat_id,
            chat_type=self.chat_type,
            sender_id=self.sender_id,
            sender_name=self.sender_name,
            sender_username=self.sender_username,
            sender_number=self.sender_number,
            text=self.text,
            message_ref=self.message_ref,
            reply_to_text=reply_to_text,
            attachments=self.attachments,
            link_previews=self.link_previews,
            raw=self.raw,
        )

    @property
    def instance_name(self) -> str:
        return self.instance

    @property
    def is_private(self) -> bool:
        return self.chat_type == "private"

    @property
    def is_group(self) -> bool:
        return self.chat_type == "group"
