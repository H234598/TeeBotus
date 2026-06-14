from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class SendText:
    chat_id: str
    text: str
    track: bool = True


@dataclass(frozen=True)
class SendAttachment:
    chat_id: str
    data: bytes
    filename: str
    content_type: str = "application/octet-stream"
    caption: str = ""
    track: bool = True


@dataclass(frozen=True)
class DeleteTrackedMessages:
    chat_id: str
    count: int | Literal["all"]


@dataclass(frozen=True)
class SendTyping:
    chat_id: str


@dataclass(frozen=True)
class ExportFile:
    chat_id: str
    filename: str
    content_type: str
    data: bytes
    caption: str = ""


@dataclass(frozen=True)
class NotifyLinkedIdentity:
    identity_key: str
    text: str
    account_id: str
    new_identity_key: str
    track: bool = False


OutgoingAction = SendText | SendAttachment | DeleteTrackedMessages | SendTyping | ExportFile | NotifyLinkedIdentity
