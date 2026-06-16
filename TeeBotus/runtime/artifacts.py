from __future__ import annotations


def safe_artifact_name(value: object, *, default: str = "artifact") -> str:
    text = str(value or "").strip()
    safe = "".join(char if char.isalnum() or char in "._-" else "_" for char in text).strip("_")
    return safe or default
