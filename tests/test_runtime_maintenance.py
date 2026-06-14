from __future__ import annotations

import gzip
import os
import tarfile
import time

from TeeBotus.runtime.maintenance import maintain_runtime_directory, rotate_runtime_text_file_if_needed


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
