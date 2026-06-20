from __future__ import annotations

import gzip
import io
import logging
import os
import sys
import tarfile
import time

from TeeBotus.runtime.maintenance import (
    RuntimeTimedRotatingFileHandler,
    STDIO_LOG_FILENAME,
    configure_runtime_logging,
    maintain_runtime_directory,
    rotate_runtime_text_file_if_needed,
)


def test_rotate_runtime_text_file_compresses_oversized_active_file(tmp_path):
    path = tmp_path / "Security_Events.jsonl"
    path.write_text("0123456789\n", encoding="utf-8")

    compressed = rotate_runtime_text_file_if_needed(path, max_bytes=4)

    assert compressed is not None
    assert compressed.suffix == ".gz"
    assert not path.exists()
    with gzip.open(compressed, "rt", encoding="utf-8") as handle:
        assert handle.read() == "0123456789\n"


def test_runtime_maintenance_compresses_old_logs(tmp_path):
    now = time.time()
    path = tmp_path / "teebotus-production.log.2026-06-01"
    path.write_text("old log\n", encoding="utf-8")
    os.utime(path, (now - 8 * 24 * 60 * 60, now - 8 * 24 * 60 * 60))

    maintain_runtime_directory(tmp_path, now=now)

    compressed = tmp_path / f"{path.name}.gz"
    assert compressed.exists()
    assert not path.exists()


def test_runtime_maintenance_archives_compressed_logs_older_than_two_months(tmp_path):
    now = time.time()
    old_mtime = now - 70 * 24 * 60 * 60
    path = tmp_path / "teebotus-production.log.2026-03-01.gz"
    path.write_bytes(b"compressed-ish")
    os.utime(path, (old_mtime, old_mtime))

    maintain_runtime_directory(tmp_path, now=now)

    archives = sorted((tmp_path / "monthly_archives").glob("teebotus-runtime-*.tar.gz"))
    assert len(archives) == 1
    assert not path.exists()
    with tarfile.open(archives[0], "r:gz") as archive:
        assert "teebotus-production.log.2026-03-01.gz" in archive.getnames()


def test_runtime_maintenance_archives_old_uncompressed_logs_in_same_pass(tmp_path):
    now = time.time()
    old_mtime = now - 70 * 24 * 60 * 60
    path = tmp_path / "teebotus-production.log.2026-03-01"
    path.write_text("old log\n", encoding="utf-8")
    os.utime(path, (old_mtime, old_mtime))

    maintain_runtime_directory(tmp_path, now=now)

    archives = sorted((tmp_path / "monthly_archives").glob("teebotus-runtime-*.tar.gz"))
    assert len(archives) == 1
    assert not path.exists()
    assert not (tmp_path / f"{path.name}.gz").exists()
    with tarfile.open(archives[0], "r:gz") as archive:
        assert "teebotus-production.log.2026-03-01.gz" in archive.getnames()


def test_configure_runtime_logging_skips_file_handler_when_stdout_already_targets_runtime_log(tmp_path, monkeypatch):
    log_path = tmp_path / "teebotus-production.log"
    log_path.touch()
    with log_path.open("a", encoding="utf-8") as redirected_stdout:
        monkeypatch.setattr(sys, "stdout", redirected_stdout)

        configure_runtime_logging(base_dir=tmp_path)

        handlers = logging.getLogger().handlers
        assert len(handlers) == 1
        assert not any(isinstance(handler, RuntimeTimedRotatingFileHandler) for handler in handlers)


def test_configure_runtime_logging_uses_file_handler_when_stdout_is_not_runtime_log(tmp_path):
    configure_runtime_logging(base_dir=tmp_path)

    handlers = logging.getLogger().handlers
    assert any(isinstance(handler, RuntimeTimedRotatingFileHandler) for handler in handlers)


def test_configure_runtime_logging_can_tee_stdio_to_runtime_log(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())

    configure_runtime_logging(base_dir=tmp_path, tee_stdio=True)
    print("stdout probe")
    print("stderr probe", file=sys.stderr)
    sys.stdout.flush()
    sys.stderr.flush()

    stdio_log = tmp_path / STDIO_LOG_FILENAME
    assert "stdout probe" in stdio_log.read_text(encoding="utf-8")
    assert "stderr probe" in stdio_log.read_text(encoding="utf-8")
