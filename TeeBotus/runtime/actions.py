from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class MessageButton:
    label: str
    text: str = ""
    url: str = ""


@dataclass(frozen=True)
class SendText:
    chat_id: str
    text: str
    track: bool = True
    reply_to_ref: str = ""
    mentions: tuple[dict[str, Any], ...] = ()
    text_mode: str = ""
    formatted_text: str = ""
    view_once: bool = False
    link_preview: Any | None = None
    buttons: tuple[MessageButton, ...] = ()


@dataclass(frozen=True)
class SendAttachment:
    chat_id: str
    data: bytes
    filename: str
    content_type: str = "application/octet-stream"
    caption: str = ""
    track: bool = True
    reply_to_ref: str = ""
    mentions: tuple[dict[str, Any], ...] = ()
    text_mode: str = ""
    view_once: bool = False
    link_preview: Any | None = None


@dataclass(frozen=True)
class DeleteTrackedMessages:
    chat_id: str
    count: int | Literal["all"]


@dataclass(frozen=True)
class SendTyping:
    chat_id: str


@dataclass(frozen=True)
class SendReaction:
    chat_id: str
    message_ref: str
    emoji: str


@dataclass(frozen=True)
class SendReceipt:
    chat_id: str
    message_ref: str
    receipt_type: Literal["read", "viewed"] = "read"


@dataclass(frozen=True)
class SendEdit:
    chat_id: str
    message_ref: str
    text: str
    track: bool = False
    mentions: tuple[dict[str, Any], ...] = ()
    text_mode: str = ""
    view_once: bool = False
    link_preview: Any | None = None


@dataclass(frozen=True)
class SendPoll:
    chat_id: str
    question: str
    answers: tuple[str, ...]
    allow_multiple_selections: bool = False
    track: bool = True


@dataclass(frozen=True)
class SetMatrixState:
    chat_id: str
    event_type: str
    content: dict[str, Any]
    state_key: str = ""


@dataclass(frozen=True)
class UpdateSignalContact:
    chat_id: str
    expiration_in_seconds: int | None = None
    name: str | None = None


@dataclass(frozen=True)
class UpdateSignalGroup:
    chat_id: str
    base64_avatar: str | None = None
    description: str | None = None
    expiration_in_seconds: int | None = None
    name: str | None = None


@dataclass(frozen=True)
class ExportFile:
    chat_id: str
    filename: str
    content_type: str
    data: bytes
    caption: str = ""
    reply_to_ref: str = ""


@dataclass(frozen=True)
class NotifyLinkedIdentity:
    identity_key: str
    text: str
    account_id: str
    new_identity_key: str
    track: bool = False


OutgoingAction = (
    SendText
    | SendAttachment
    | DeleteTrackedMessages
    | SendTyping
    | SendReaction
    | SendReceipt
    | SendEdit
    | SendPoll
    | SetMatrixState
    | UpdateSignalContact
    | UpdateSignalGroup
    | ExportFile
    | NotifyLinkedIdentity
)
