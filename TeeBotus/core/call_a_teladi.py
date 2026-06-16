from __future__ import annotations


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
