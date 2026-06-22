from __future__ import annotations

import contextlib
import contextvars
import itertools
import time
from collections.abc import Iterator, Mapping
from typing import Any


_LOG_CONTEXT: contextvars.ContextVar[dict[str, str]] = contextvars.ContextVar("teebotus_log_context", default={})
_CALL_COUNTER = itertools.count(1)
_CONTEXT_KEY_ORDER = (
    "instance",
    "channel",
    "slot",
    "event_id",
    "chat_id",
    "message_id",
    "component",
    "operation",
    "purpose",
    "llm_call_id",
    "provider",
    "model",
    "api_base",
    "schema",
)


def next_llm_call_id(prefix: str = "llm") -> str:
    clean_prefix = "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in str(prefix or "llm").strip())
    return f"{clean_prefix or 'llm'}-{int(time.time() * 1000):x}-{next(_CALL_COUNTER)}"


def current_log_context() -> Mapping[str, str]:
    return dict(_LOG_CONTEXT.get())


@contextlib.contextmanager
def logging_context(**values: Any) -> Iterator[None]:
    current = dict(_LOG_CONTEXT.get())
    for key, value in values.items():
        text = str(value or "").strip()
        if text:
            current[str(key)] = text
    token = _LOG_CONTEXT.set(current)
    try:
        yield
    finally:
        _LOG_CONTEXT.reset(token)


def format_log_context() -> str:
    context = _LOG_CONTEXT.get()
    if not context:
        return ""
    ordered = [key for key in _CONTEXT_KEY_ORDER if key in context]
    ordered.extend(sorted(key for key in context if key not in set(ordered)))
    parts = [f"{key}={_context_value(context[key])}" for key in ordered if str(context.get(key, "")).strip()]
    return " ".join(parts)


def _context_value(value: object) -> str:
    text = str(value or "").replace("\n", "\\n").replace("\r", "\\r").strip()
    return text[:240]
