from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class TeladiPendingFlow:
    """Account-scoped pending Teladi emergency flow."""

    instance_name: str
    account_id: str
    channel: str
    chat_id: str
    requested_at: str

    @classmethod
    def start(cls, *, instance_name: str, account_id: str, channel: str, chat_id: str) -> "TeladiPendingFlow":
        return cls(
            instance_name=instance_name,
            account_id=account_id,
            channel=channel,
            chat_id=chat_id,
            requested_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )


def build_teladi_header(
    *,
    instance_name: str,
    channel: str,
    account_id: str,
    identity_key: str,
    chat_id: str,
    source_label: str = "",
) -> str:
    """Build a messenger-neutral emergency provenance header."""
    parts = [
        "[TeeBotus Emergency]",
        f"Instanz: {instance_name}",
        f"Quelle: {channel}",
        f"Account: {account_id}",
        f"Identity: {identity_key}",
        f"Chat: {chat_id}",
    ]
    if source_label:
        parts.append(f"Absender: {source_label}")
    return "\n".join(parts)


def build_teladi_message(header: str, text: str) -> str:
    """Combine the provenance header with the user-supplied emergency text."""
    return f"{header}\n\n{text.strip()}" if text.strip() else header
