from __future__ import annotations

import asyncio
import logging

from TeeBotus.runtime.async_bridge import _handle_scheduled_result, run_background_coroutine


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


def test_run_background_coroutine_schedules_on_running_loop_without_thread_id() -> None:
    async def main() -> None:
        results: list[str] = []

        async def work() -> str:
            return "ok"

        result = run_background_coroutine(
            work,
            loop=asyncio.get_running_loop(),
            loop_thread_id=None,
            on_scheduled_result=results.append,
        )

        assert result is None
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert results == ["ok"]

    asyncio.run(main())


def test_run_background_coroutine_falls_back_when_loop_is_not_running() -> None:
    loop = asyncio.new_event_loop()
    try:
        async def work() -> str:
            return "ok"

        assert run_background_coroutine(work, loop=loop, loop_thread_id=None) == "ok"
    finally:
        loop.close()
