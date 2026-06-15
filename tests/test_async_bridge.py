from __future__ import annotations

import asyncio
import logging

from TeeBotus.runtime.async_bridge import _handle_scheduled_result


def test_handle_scheduled_result_logs_task_failure(caplog) -> None:
    async def fail() -> None:
        raise RuntimeError("dispatch failed")

    async def main() -> asyncio.Task[None]:
        task = asyncio.create_task(fail())
        await asyncio.sleep(0)
        return task

    task = asyncio.run(main())

    with caplog.at_level(logging.ERROR, logger="TeeBotus.async_bridge"):
        _handle_scheduled_result(task, lambda _result: None)

    assert "Background coroutine scheduled on runtime loop failed." in caplog.text


def test_handle_scheduled_result_logs_callback_failure(caplog) -> None:
    async def succeed() -> str:
        return "ok"

    async def main() -> asyncio.Task[str]:
        task = asyncio.create_task(succeed())
        await asyncio.sleep(0)
        return task

    task = asyncio.run(main())

    def fail_callback(_result: str) -> None:
        raise RuntimeError("tracking failed")

    with caplog.at_level(logging.ERROR, logger="TeeBotus.async_bridge"):
        _handle_scheduled_result(task, fail_callback)

    assert "Background coroutine result callback failed." in caplog.text
