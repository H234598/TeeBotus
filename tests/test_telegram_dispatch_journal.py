from __future__ import annotations

import multiprocessing
import threading
from pathlib import Path

from TeeBotus.runtime.telegram_dispatch import TelegramDispatchJournal


def _hold_journal_lock(runtime_dir: str, ready, release) -> None:
    journal = TelegramDispatchJournal("Demo", Path(runtime_dir), None)
    with journal._journal_lock():
        ready.set()
        release.wait(5)


def test_telegram_dispatch_journal_lock_serializes_separate_process(tmp_path: Path) -> None:
    context = multiprocessing.get_context("fork")
    ready = context.Event()
    release = context.Event()
    process = context.Process(target=_hold_journal_lock, args=(str(tmp_path), ready, release))
    process.start()
    entered = threading.Event()
    finished = threading.Event()
    journal = TelegramDispatchJournal("Demo", tmp_path, None)

    def acquire_lock() -> None:
        with journal._journal_lock():
            entered.set()
        finished.set()

    thread = threading.Thread(target=acquire_lock)
    try:
        assert ready.wait(5)
        thread.start()
        assert not entered.wait(0.2)
    finally:
        release.set()
        thread.join(5)
        process.join(5)
        if process.is_alive():
            process.terminate()
            process.join(5)

    assert process.exitcode == 0
    assert finished.is_set()
