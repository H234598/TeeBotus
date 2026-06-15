from __future__ import annotations

import logging
import time
from typing import Any, Callable

LOGGER = logging.getLogger("TeeBotus")
FALLBACK_WARNING_INTERVAL_SECONDS = 300


class WarningFallbackAccountMemoryBackend:
    def __init__(self, primary: Any, fallback: Any, *, label: str) -> None:
        self.primary = primary
        self.fallback = fallback
        self.label = label
        self._fallback_active = False
        self._last_warning_at = 0.0

    def read_entries(self, account_id: str) -> list[dict[str, Any]]:
        return self._call("read_entries", lambda backend: backend.read_entries(account_id))

    def write_entries(self, account_id: str, rows: list[dict[str, Any]]) -> None:
        return self._call("write_entries", lambda backend: backend.write_entries(account_id, rows))

    def read_index(self, account_id: str) -> dict[str, Any]:
        return self._call("read_index", lambda backend: backend.read_index(account_id))

    def write_index(self, account_id: str, data: dict[str, Any]) -> None:
        return self._call("write_index", lambda backend: backend.write_index(account_id, data))

    def _call(self, operation: str, callback: Callable[[Any], Any]) -> Any:
        try:
            result = callback(self.primary)
            if self._fallback_active:
                LOGGER.critical("Account-Memory primary backend recovered label=%s operation=%s. Fallback warning cleared.", self.label, operation)
            self._fallback_active = False
            return result
        except Exception as exc:  # noqa: BLE001
            self._fallback_active = True
            self._warn(operation, exc)
            return callback(self.fallback)

    def _warn(self, operation: str, exc: Exception) -> None:
        now = time.monotonic()
        if now - self._last_warning_at < FALLBACK_WARNING_INTERVAL_SECONDS:
            return
        self._last_warning_at = now
        LOGGER.critical(
            "ACCOUNT MEMORY PRIMARY DATABASE FAILED. USING FALLBACK DATABASE. label=%s operation=%s error=%s. "
            "Datenbank-Normalitaet ist NICHT hergestellt; diese Warnung wiederholt sich periodisch, bis der Primary-Backend wieder funktioniert.",
            self.label,
            operation,
            exc,
        )
