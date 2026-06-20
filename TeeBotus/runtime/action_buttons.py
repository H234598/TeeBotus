from __future__ import annotations

from collections.abc import Sequence

from TeeBotus.core.version_notifications import DEFAULT_REPO_URL
from TeeBotus.runtime.actions import MessageButton

TERMS_DOCUMENT_URL = f"{DEFAULT_REPO_URL}/blob/main/docs/AGB.md"

YES_NO_BUTTONS = (
    MessageButton("Ja", "ja"),
    MessageButton("Nein", "nein"),
)

MEMORY_RESET_BUTTONS = (
    MessageButton("Ja, loeschen", "ja"),
    MessageButton("Nein", "nein"),
)

NOTIFICATION_LOUDNESS_BUTTONS = (
    MessageButton("Ja, ist laut", "ja, laut"),
    MessageButton("Nein", "nein"),
)

ACCOUNT_EDIT_BUTTONS = (
    MessageButton("Kanal trennen", "unlink"),
    MessageButton("Secret rotieren", "rotate_secret"),
    MessageButton("Abbrechen", "abbrechen"),
)

ACCOUNT_UNLINK_CONFIRM_BUTTONS = (
    MessageButton("Ja, trennen", "ja"),
    MessageButton("Nein", "nein"),
)

YOUTUBE_LOCAL_OPTIONS_BUTTONS = (
    MessageButton("Live an, LLM aus", "live ja, llm nein"),
    MessageButton("Live aus, LLM aus", "live nein, llm nein"),
    MessageButton("Live an, LLM an", "live ja, llm ja"),
)

LEGAL_CONSENT_BUTTONS = (
    MessageButton("Alter 16+ bestaetigen", "Ich bin ueber 16 und akzeptiere Datenschutz und AGB."),
    MessageButton("AGB", url=TERMS_DOCUMENT_URL),
    MessageButton("Datenschutz bestaetigen", "Datenschutz bestaetigt"),
)


def text_with_button_fallback(text: str, buttons: Sequence[MessageButton] | None) -> str:
    clean_text = str(text or "").rstrip()
    rows = []
    for button in buttons or ():
        label = str(button.label or "").strip()
        if not label:
            continue
        target = str(button.text or button.url or "").strip()
        rows.append(f"- {label}: {target}" if target else f"- {label}")
    if not rows:
        return clean_text
    suffix = "Optionen:\n" + "\n".join(rows)
    return f"{clean_text}\n\n{suffix}" if clean_text else suffix


__all__ = [
    "ACCOUNT_EDIT_BUTTONS",
    "ACCOUNT_UNLINK_CONFIRM_BUTTONS",
    "LEGAL_CONSENT_BUTTONS",
    "MEMORY_RESET_BUTTONS",
    "NOTIFICATION_LOUDNESS_BUTTONS",
    "TERMS_DOCUMENT_URL",
    "YES_NO_BUTTONS",
    "YOUTUBE_LOCAL_OPTIONS_BUTTONS",
    "text_with_button_fallback",
]
