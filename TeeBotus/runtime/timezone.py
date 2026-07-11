"""Timezone helpers for user-facing scheduling policies.

Storage and transport timestamps remain UTC/offset-aware.  Scheduling rules,
activity profiles, and notification wake windows need one stable local
timezone instead of inheriting the process timezone (which differs between
the desktop and CI runners).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TEEBOTUS_TIMEZONE_ENV = "TEEBOTUS_TIMEZONE"
DEFAULT_TIMEZONE_NAME = "Europe/Berlin"


def configured_timezone() -> tzinfo:
    """Return the configured user-local timezone with a safe fallback."""

    name = os.environ.get(TEEBOTUS_TIMEZONE_ENV, DEFAULT_TIMEZONE_NAME).strip() or DEFAULT_TIMEZONE_NAME
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        try:
            return ZoneInfo(DEFAULT_TIMEZONE_NAME)
        except (ZoneInfoNotFoundError, ValueError):
            return timezone.utc


def local_now() -> datetime:
    """Return the current instant in the configured user-local timezone."""

    return datetime.now(timezone.utc).astimezone(configured_timezone())


def to_local(value: datetime) -> datetime:
    """Convert an aware/naive timestamp to the configured user-local time."""

    aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(configured_timezone())
