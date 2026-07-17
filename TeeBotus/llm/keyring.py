from __future__ import annotations

import os
import threading
from collections.abc import Mapping, Sequence


class RotatingAPIKeyRing:
    """Named process-local API key ring that advances only on exhaustion."""

    def __init__(self, keys: Sequence[str], *, name: str = "") -> None:
        self.keys = _dedupe_nonempty(keys)
        self.name = str(name or "").strip()
        self._state = _state_for(self.keys, self.name)

    def __bool__(self) -> bool:
        return bool(self.keys)

    def ordered_keys(self) -> tuple[str, ...]:
        if not self.keys:
            return ()
        with self._state.lock:
            start = self._state.cursor % len(self.keys)
            return tuple((*self.keys[start:], *self.keys[:start]))

    def mark_limited(self, key: str) -> None:
        self._move_cursor(key, offset=1)

    def mark_success(self, key: str) -> None:
        self._move_cursor(key, offset=0)

    def _move_cursor(self, key: str, *, offset: int) -> None:
        if not self.keys:
            return
        try:
            index = self.keys.index(str(key or "").strip())
        except ValueError:
            return
        with self._state.lock:
            # Ignore late results from requests that started before rotation.
            if index != self._state.cursor % len(self.keys):
                return
            self._state.cursor = (index + offset) % len(self.keys)


class _RingState:
    def __init__(self) -> None:
        self.cursor = 0
        self.lock = threading.Lock()


_REGISTRY_LOCK = threading.Lock()
_REGISTRY: dict[tuple[str, tuple[str, ...]], _RingState] = {}


def _state_for(keys: tuple[str, ...], name: str) -> _RingState:
    registry_key = (str(name or "").strip(), keys)
    with _REGISTRY_LOCK:
        state = _REGISTRY.get(registry_key)
        if state is None:
            state = _RingState()
            _REGISTRY[registry_key] = state
        return state


def resolve_gemini_api_key_ring(env: Mapping[str, str] | None = None, *, instance_name: str = "", scope: str = "") -> tuple[str, ...]:
    source = os.environ if env is None else env
    token = _env_token(instance_name)
    scope_token = _env_token(scope)
    for name in _flat_ring_env_names(token, scope_token):
        keys = _parse_csv(source.get(name))
        if keys:
            return keys
    buckets = _numbered_gemini_key_buckets(source, token=token, scope_token=scope_token)
    if buckets:
        return interleave_key_buckets(buckets)
    # Google documents both names. If both are present, GOOGLE_API_KEY wins.
    google_key = source.get("GOOGLE_API_KEY", "").strip()
    if google_key:
        return (google_key,)
    return _dedupe_nonempty((source.get("GEMINI_API_KEY", ""),))


def interleave_key_buckets(buckets: Sequence[Sequence[str]]) -> tuple[str, ...]:
    normalized = [tuple(_dedupe_nonempty(bucket)) for bucket in buckets if _dedupe_nonempty(bucket)]
    if not normalized:
        return ()
    result: list[str] = []
    max_len = max(len(bucket) for bucket in normalized)
    for column in range(max_len):
        for bucket in normalized:
            if column < len(bucket):
                result.append(bucket[column])
    return _dedupe_nonempty(result)


def _numbered_gemini_key_buckets(source: Mapping[str, str], *, token: str, scope_token: str = "") -> tuple[tuple[str, ...], ...]:
    prefixes = []
    if token and scope_token:
        prefixes.extend(
            [
                f"TEEBOTUS_GEMINI_API_KEYS_{token}_{scope_token}_ACCOUNT_",
                f"GEMINI_API_KEYS_{token}_{scope_token}_ACCOUNT_",
            ]
        )
    if scope_token:
        prefixes.extend(
            [
                f"TEEBOTUS_GEMINI_API_KEYS_{scope_token}_ACCOUNT_",
                f"GEMINI_API_KEYS_{scope_token}_ACCOUNT_",
            ]
        )
    if token:
        prefixes.extend(
            [
                f"TEEBOTUS_GEMINI_API_KEYS_{token}_ACCOUNT_",
                f"GEMINI_API_KEYS_{token}_ACCOUNT_",
            ]
        )
    prefixes.extend(
        [
            "TEEBOTUS_GEMINI_API_KEYS_ACCOUNT_",
            "GEMINI_API_KEYS_ACCOUNT_",
            "GEMINI_API_KEYS_",
        ]
    )
    buckets_by_index: dict[int, tuple[str, ...]] = {}
    for prefix in prefixes:
        for key, value in source.items():
            if not key.startswith(prefix):
                continue
            suffix = key[len(prefix) :]
            if not suffix.isdigit():
                continue
            index = int(suffix)
            buckets_by_index.setdefault(index, _parse_csv(value))
    return tuple(buckets_by_index[index] for index in sorted(buckets_by_index) if buckets_by_index[index])


def _flat_ring_env_names(token: str, scope_token: str = "") -> tuple[str, ...]:
    names: list[str] = []
    if token and scope_token:
        names.extend(
            [
                f"TEEBOTUS_GEMINI_API_KEY_RING_{token}_{scope_token}",
                f"GEMINI_API_KEY_RING_{token}_{scope_token}",
            ]
        )
    if scope_token:
        names.extend(
            [
                f"TEEBOTUS_GEMINI_API_KEY_RING_{scope_token}",
                f"GEMINI_API_KEY_RING_{scope_token}",
            ]
        )
    if token:
        names.extend(
            [
                f"TEEBOTUS_GEMINI_API_KEY_RING_{token}",
                f"GEMINI_API_KEY_RING_{token}",
            ]
        )
    names.extend(("TEEBOTUS_GEMINI_API_KEY_RING", "GEMINI_API_KEY_RING", "GEMINI_API_KEYS"))
    return tuple(names)


def _parse_csv(value: object) -> tuple[str, ...]:
    return _dedupe_nonempty(str(value or "").split(","))


def _dedupe_nonempty(values: Sequence[object]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return tuple(result)


def _env_token(value: str) -> str:
    token = "".join(char if char.isalnum() else "_" for char in str(value or "").strip().upper())
    return "_".join(part for part in token.split("_") if part)


__all__ = [
    "RotatingAPIKeyRing",
    "interleave_key_buckets",
    "resolve_gemini_api_key_ring",
]
