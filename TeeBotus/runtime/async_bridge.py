from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable, Coroutine
from typing import Any


LOGGER = logging.getLogger("TeeBotus.async_bridge")
BACKGROUND_DISPATCH_TIMEOUT_SECONDS = 60.0


def run_background_coroutine(
    coroutine_factory: Callable[[], Coroutine[Any, Any, Any]],
    *,
    loop: asyncio.AbstractEventLoop | None,
    loop_thread_id: int | None,
    on_scheduled_result: Callable[[Any], None] | None = None,
    timeout: float = BACKGROUND_DISPATCH_TIMEOUT_SECONDS,
) -> Any:
    """Run a background coroutine on the runtime loop when one is available."""
    if loop is not None and not loop.is_closed():
        if threading.get_ident() == loop_thread_id:
            try:
                running_loop = asyncio.get_running_loop()
            except RuntimeError:
                running_loop = None
            if running_loop is loop:
                task = loop.create_task(coroutine_factory())
                if on_scheduled_result is not None:
                    task.add_done_callback(lambda completed: _handle_scheduled_result(completed, on_scheduled_result))
                return None

        future = asyncio.run_coroutine_threadsafe(coroutine_factory(), loop)
        try:
            return future.result(timeout=timeout)
        except Exception:
            future.cancel()
            raise

    return asyncio.run(coroutine_factory())


def _handle_scheduled_result(task: asyncio.Task[Any], callback: Callable[[Any], None]) -> None:
    try:
        result = task.result()
    except Exception:
        LOGGER.exception("Background coroutine scheduled on runtime loop failed.")
        return
    try:
        callback(result)
    except Exception:
        LOGGER.exception("Background coroutine result callback failed.")
