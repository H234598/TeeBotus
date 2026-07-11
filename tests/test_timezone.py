from __future__ import annotations

from datetime import datetime, timezone

from TeeBotus.runtime.timezone import DEFAULT_TIMEZONE_NAME, TEEBOTUS_TIMEZONE_ENV, configured_timezone, to_local


def test_invalid_configured_timezone_uses_stable_default(monkeypatch) -> None:
    monkeypatch.setenv(TEEBOTUS_TIMEZONE_ENV, "Not/A/Timezone")

    configured = configured_timezone()

    assert getattr(configured, "key", "") == DEFAULT_TIMEZONE_NAME


def test_to_local_uses_configured_timezone_for_utc_input(monkeypatch) -> None:
    monkeypatch.setenv(TEEBOTUS_TIMEZONE_ENV, DEFAULT_TIMEZONE_NAME)

    converted = to_local(datetime(2026, 1, 15, 12, tzinfo=timezone.utc))

    assert converted.isoformat() == "2026-01-15T13:00:00+01:00"
