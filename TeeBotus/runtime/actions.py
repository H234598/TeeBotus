from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class SendText:
    chat_id: str
    text: str
    track: bool = True
    reply_to_ref: str = ""


@dataclass(frozen=True)
class SendAttachment:
    chat_id: str
    data: bytes
    filename: str
    content_type: str = "application/octet-stream"
    caption: str = ""
    track: bool = True
    reply_to_ref: str = ""


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


@dataclass(frozen=True)
class SendPoll:
    chat_id: str
    question: str
    answers: tuple[str, ...]
    allow_multiple_selections: bool = False
    track: bool = True


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
    | ExportFile
    | NotifyLinkedIdentity
)
