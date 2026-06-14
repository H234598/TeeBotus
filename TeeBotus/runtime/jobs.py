from __future__ import annotations

import concurrent.futures
import logging
from dataclasses import dataclass
from typing import Any, Callable

LOGGER = logging.getLogger("TeeBotus.jobs")
YOUTUBE_LOCAL_TRANSCRIPTION_WORKERS = 1


@dataclass(frozen=True)
class Job:
    kind: str
    instance: str
    channel: str
    chat_id: str
    account_id: str
    payload: dict[str, Any]


class JobRunner:
    def __init__(self, max_workers: int = 2) -> None:
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, max_workers), thread_name_prefix="teebotus-job")

    def submit(self, job: Job, callback: Callable[[Job], Any]) -> concurrent.futures.Future[Any]:
        future = self._executor.submit(callback, job)
        future.add_done_callback(self._log_unhandled_exception)
        return future

    def shutdown(self, wait: bool = False) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=False)

    @staticmethod
    def _log_unhandled_exception(future: concurrent.futures.Future[Any]) -> None:
        try:
            future.result()
        except Exception:
            LOGGER.exception("Unhandled TeeBotus job error.")


class YouTubeTranscriptionJobRunner:
    def __init__(self, max_workers: int = YOUTUBE_LOCAL_TRANSCRIPTION_WORKERS) -> None:
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, max_workers),
            thread_name_prefix="youtube-transcript-job",
        )

    def submit(self, callback: Callable[[], Any]) -> concurrent.futures.Future[Any]:
        future = self._executor.submit(callback)
        future.add_done_callback(self._log_unhandled_exception)
        return future

    def shutdown(self, wait: bool = False) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=False)

    @staticmethod
    def _log_unhandled_exception(future: concurrent.futures.Future[Any]) -> None:
        try:
            future.result()
        except Exception:
            LOGGER.exception("Unhandled YouTube transcription job error.")
