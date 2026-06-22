from __future__ import annotations

import errno
import gzip
import io
import logging
import os
import shutil
import sys
import tarfile
import time
from pathlib import Path

import pytest

from TeeBotus.runtime.maintenance import (
    ACTIVE_RUNTIME_TEXT_FILENAMES,
    DEBUG_ALL,
    RuntimeTimedRotatingFileHandler,
    STDIO_LOG_FILENAME,
    TeeStream,
    _stdout_targets_path,
    configure_runtime_logging,
    gzip_file,
    install_stdio_tee,
    maintain_runtime_directory,
    normalize_log_level,
    runtime_dir,
    runtime_log_path,
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


def test_rotate_runtime_text_file_accepts_string_path(tmp_path):
    path = tmp_path / "Security_Events.jsonl"
    path.write_text("0123456789\n", encoding="utf-8")

    compressed = rotate_runtime_text_file_if_needed(str(path), max_bytes=4)

    assert compressed is not None
    assert compressed.suffix == ".gz"
    assert not path.exists()


def test_rotate_runtime_text_file_does_not_overwrite_target_created_during_rotation(tmp_path, monkeypatch):
    path = tmp_path / "Security_Events.jsonl"
    path.write_text("0123456789\n", encoding="utf-8")
    real_link = os.link
    raced_target: Path | None = None

    def racing_link(source, destination, *args, **kwargs):
        nonlocal raced_target
        destination_path = Path(destination)
        if destination_path.suffix != ".gz" and destination_path.name.startswith(f"{path.name}.") and raced_target is None:
            raced_target = destination_path
            destination_path.write_text("existing target\n", encoding="utf-8")
            raise FileExistsError(destination)
        return real_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "link", racing_link)

    compressed = rotate_runtime_text_file_if_needed(path, max_bytes=4)

    assert raced_target is not None
    assert raced_target.read_text(encoding="utf-8") == "existing target\n"
    assert compressed is not None
    assert compressed.exists()
    assert compressed != raced_target.with_name(f"{raced_target.name}.gz")
    assert not path.exists()
    with gzip.open(compressed, "rt", encoding="utf-8") as handle:
        assert handle.read() == "0123456789\n"


def test_rotate_runtime_text_file_skips_broken_symlink_rotation_target(tmp_path, monkeypatch):
    path = tmp_path / "Security_Events.jsonl"
    path.write_text("0123456789\n", encoding="utf-8")
    blocked_target = tmp_path / f"{path.name}.2026-06-22-181200"
    blocked_target.symlink_to(tmp_path / "missing-target")
    monkeypatch.setattr("TeeBotus.runtime.maintenance._next_rotated_path", lambda _path: blocked_target)

    compressed = rotate_runtime_text_file_if_needed(path, max_bytes=4)

    assert compressed is not None
    assert compressed.name.startswith(f"{blocked_target.name}.")
    assert blocked_target.is_symlink()
    assert not path.exists()
    with gzip.open(compressed, "rt", encoding="utf-8") as handle:
        assert handle.read() == "0123456789\n"


def test_rotate_runtime_text_file_preserves_source_replaced_before_cleanup(tmp_path, monkeypatch):
    path = tmp_path / "Security_Events.jsonl"
    path.write_text("0123456789\n", encoding="utf-8")
    real_link = os.link
    raced = False

    def racing_link(source, destination, *args, **kwargs):
        nonlocal raced
        result = real_link(source, destination, *args, **kwargs)
        destination_path = Path(destination)
        if destination_path.suffix != ".gz" and destination_path.name.startswith(f"{path.name}.") and not raced:
            raced = True
            path.unlink()
            path.write_text("replacement\n", encoding="utf-8")
        return result

    monkeypatch.setattr(os, "link", racing_link)

    compressed = rotate_runtime_text_file_if_needed(path, max_bytes=4)

    assert raced is True
    assert path.read_text(encoding="utf-8") == "replacement\n"
    assert compressed is not None
    with gzip.open(compressed, "rt", encoding="utf-8") as handle:
        assert handle.read() == "0123456789\n"


def test_rotate_runtime_text_file_skips_source_replaced_before_link(tmp_path, monkeypatch):
    path = tmp_path / "Security_Events.jsonl"
    path.write_text("0123456789\n", encoding="utf-8")
    real_link = os.link
    raced = False

    def racing_link(source, destination, *args, **kwargs):
        nonlocal raced
        destination_path = Path(destination)
        if destination_path.suffix != ".gz" and destination_path.name.startswith(f"{path.name}.") and not raced:
            raced = True
            path.unlink()
            path.write_text("replacement\n", encoding="utf-8")
        return real_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "link", racing_link)

    assert rotate_runtime_text_file_if_needed(path, max_bytes=4) is None

    assert raced is True
    assert path.read_text(encoding="utf-8") == "replacement\n"
    assert not list(tmp_path.glob(f"{path.name}.*.gz"))


def test_rotate_runtime_text_file_preserves_rotated_path_replaced_before_link_stat(tmp_path, monkeypatch):
    path = tmp_path / "Security_Events.jsonl"
    path.write_text("0123456789\n", encoding="utf-8")
    rotated = tmp_path / "Security_Events.jsonl.2026-06-22-181200"
    monkeypatch.setattr("TeeBotus.runtime.maintenance._next_rotated_path", lambda _path: rotated)
    real_stat = os.stat
    raced = False

    def racing_stat(file, *args, **kwargs):
        nonlocal raced
        if Path(file) == rotated and not raced:
            raced = True
            rotated.unlink()
            rotated.write_text("raced target\n", encoding="utf-8")
        return real_stat(file, *args, **kwargs)

    monkeypatch.setattr(os, "stat", racing_stat)

    assert rotate_runtime_text_file_if_needed(path, max_bytes=4) is None

    assert raced is True
    assert path.read_text(encoding="utf-8") == "0123456789\n"
    assert rotated.read_text(encoding="utf-8") == "raced target\n"
    assert not (tmp_path / f"{rotated.name}.gz").exists()


def test_rotate_runtime_text_file_keeps_rotated_file_when_compression_fails(tmp_path, monkeypatch):
    path = tmp_path / "Security_Events.jsonl"
    path.write_text("0123456789\n", encoding="utf-8")
    rotated = tmp_path / "Security_Events.jsonl.2026-06-22-181200"
    monkeypatch.setattr("TeeBotus.runtime.maintenance._next_rotated_path", lambda _path: rotated)

    def fail_copy(*_args, **_kwargs):
        raise OSError("copy failed")

    monkeypatch.setattr(shutil, "copyfileobj", fail_copy)

    result = rotate_runtime_text_file_if_needed(path, max_bytes=4)

    assert result == rotated
    assert rotated.read_text(encoding="utf-8") == "0123456789\n"
    assert not path.exists()
    assert not (tmp_path / f"{rotated.name}.gz").exists()
    assert not list(tmp_path.glob(".*.tmp"))


def test_rotate_runtime_text_file_keeps_rotated_file_when_compression_value_error_fails(tmp_path, monkeypatch):
    path = tmp_path / "Security_Events.jsonl"
    path.write_text("0123456789\n", encoding="utf-8")
    rotated = tmp_path / "Security_Events.jsonl.2026-06-22-181200"
    monkeypatch.setattr("TeeBotus.runtime.maintenance._next_rotated_path", lambda _path: rotated)

    def fail_copy(*_args, **_kwargs):
        raise ValueError("copy failed")

    monkeypatch.setattr(shutil, "copyfileobj", fail_copy)

    result = rotate_runtime_text_file_if_needed(path, max_bytes=4)

    assert result == rotated
    assert rotated.read_text(encoding="utf-8") == "0123456789\n"
    assert not path.exists()
    assert not (tmp_path / f"{rotated.name}.gz").exists()
    assert not list(tmp_path.glob(".*.tmp"))


def test_rotate_runtime_text_file_preserves_active_runtime_log_names(tmp_path):
    for filename in ACTIVE_RUNTIME_TEXT_FILENAMES:
        path = tmp_path / filename
        path.write_text("0123456789\n", encoding="utf-8")

        assert rotate_runtime_text_file_if_needed(path, max_bytes=4) is None
        assert path.read_text(encoding="utf-8") == "0123456789\n"
        assert not list(tmp_path.glob(f"{filename}.*.gz"))


def test_rotate_runtime_text_file_preserves_compressed_and_temporary_files(tmp_path):
    for filename in ("teebotus-production.log.2026-06-01.gz", "Security_Events.jsonl.tmp"):
        path = tmp_path / filename
        path.write_text("0123456789\n", encoding="utf-8")

        assert rotate_runtime_text_file_if_needed(path, max_bytes=4) is None
        assert path.read_text(encoding="utf-8") == "0123456789\n"
        assert not list(tmp_path.glob(f"{filename}.*"))


def test_rotate_runtime_text_file_preserves_symlinked_file(tmp_path):
    target = tmp_path / "external-target.txt"
    target.write_text("0123456789\n", encoding="utf-8")
    symlink = tmp_path / "Security_Events.jsonl"
    symlink.symlink_to(target)

    assert rotate_runtime_text_file_if_needed(symlink, max_bytes=4) is None

    assert symlink.is_symlink()
    assert target.read_text(encoding="utf-8") == "0123456789\n"
    assert not list(tmp_path.glob("Security_Events.jsonl.*.gz"))


def test_rotate_runtime_text_file_ignores_non_file_paths(tmp_path):
    directory = tmp_path / "Security_Events.jsonl"
    directory.mkdir()

    assert rotate_runtime_text_file_if_needed(directory, max_bytes=4) is None
    assert directory.is_dir()


def test_runtime_maintenance_compresses_old_logs(tmp_path):
    now = time.time()
    path = tmp_path / "teebotus-production.log.2026-06-01"
    path.write_text("old log\n", encoding="utf-8")
    os.utime(path, (now - 8 * 24 * 60 * 60, now - 8 * 24 * 60 * 60))

    maintain_runtime_directory(tmp_path, now=now)

    compressed = tmp_path / f"{path.name}.gz"
    assert compressed.exists()
    assert not path.exists()


def test_runtime_maintenance_accepts_string_path(tmp_path):
    now = time.time()
    path = tmp_path / "teebotus-production.log.2026-06-01"
    path.write_text("old log\n", encoding="utf-8")
    os.utime(path, (now - 8 * 24 * 60 * 60, now - 8 * 24 * 60 * 60))

    maintain_runtime_directory(str(tmp_path), now=now)

    assert (tmp_path / f"{path.name}.gz").exists()
    assert not path.exists()


def test_runtime_maintenance_refuses_symlinked_runtime_root(tmp_path):
    now = time.time()
    old_mtime = now - 8 * 24 * 60 * 60
    external_runtime_dir = tmp_path / "external-runtime"
    external_runtime_dir.mkdir()
    path = external_runtime_dir / "teebotus-production.log.2026-06-01"
    path.write_text("old log\n", encoding="utf-8")
    os.utime(path, (old_mtime, old_mtime))
    runtime_link = tmp_path / "runtime-link"
    runtime_link.symlink_to(external_runtime_dir, target_is_directory=True)

    maintain_runtime_directory(runtime_link, now=now)

    assert runtime_link.is_symlink()
    assert path.read_text(encoding="utf-8") == "old log\n"
    assert not (external_runtime_dir / f"{path.name}.gz").exists()


def test_runtime_maintenance_refuses_symlinked_runtime_parent(tmp_path):
    now = time.time()
    external_parent = tmp_path / "external-parent"
    external_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(external_parent, target_is_directory=True)

    maintain_runtime_directory(linked_parent / "runtime", now=now)

    assert linked_parent.is_symlink()
    assert not (external_parent / "runtime").exists()


def test_runtime_maintenance_does_not_compress_replacement_after_age_check(tmp_path, monkeypatch):
    now = time.time()
    old_mtime = now - 8 * 24 * 60 * 60
    path = tmp_path / "teebotus-production.log.2026-06-01"
    path.write_text("old log\n", encoding="utf-8")
    os.utime(path, (old_mtime, old_mtime))
    real_open = os.open
    raced = False

    def racing_open(file, flags, *args, **kwargs):
        nonlocal raced
        if Path(file) == path and not raced:
            raced = True
            path.unlink()
            path.write_text("new log\n", encoding="utf-8")
            os.utime(path, (now, now))
        return real_open(file, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", racing_open)

    maintain_runtime_directory(tmp_path, now=now)

    assert raced is True
    assert path.read_text(encoding="utf-8") == "new log\n"
    assert not (tmp_path / f"{path.name}.gz").exists()


def test_runtime_maintenance_continues_when_gzip_fdopen_fails(tmp_path, monkeypatch):
    now = time.time()
    old_mtime = now - 8 * 24 * 60 * 60
    broken = tmp_path / "teebotus-production.log.2026-06-01"
    broken.write_text("broken log\n", encoding="utf-8")
    os.utime(broken, (old_mtime, old_mtime))
    compressible = tmp_path / "Security_Events.jsonl.2026-06-01"
    compressible.write_text("compress me\n", encoding="utf-8")
    os.utime(compressible, (old_mtime, old_mtime))
    real_open = os.open
    real_fdopen = os.fdopen
    broken_fds: set[int] = set()

    def recording_open(file, flags, *args, **kwargs):
        fd = real_open(file, flags, *args, **kwargs)
        if Path(file) == broken:
            broken_fds.add(fd)
        return fd

    def fail_broken_fdopen(fd, mode="r", *args, **kwargs):
        if fd in broken_fds and mode == "rb":
            raise ValueError("broken gzip source fdopen")
        return real_fdopen(fd, mode, *args, **kwargs)

    monkeypatch.setattr(os, "open", recording_open)
    monkeypatch.setattr(os, "fdopen", fail_broken_fdopen)

    maintain_runtime_directory(tmp_path, now=now)

    assert broken.read_text(encoding="utf-8") == "broken log\n"
    assert not (tmp_path / f"{broken.name}.gz").exists()
    assert not compressible.exists()
    assert (tmp_path / f"{compressible.name}.gz").exists()


def test_runtime_maintenance_preserves_active_runtime_logs(tmp_path):
    now = time.time()
    old_mtime = now - 8 * 24 * 60 * 60
    for filename in ACTIVE_RUNTIME_TEXT_FILENAMES:
        path = tmp_path / filename
        path.write_text("active log\n", encoding="utf-8")
        os.utime(path, (old_mtime, old_mtime))

    rotated = tmp_path / "teebotus-production.log.2026-06-01"
    rotated.write_text("rotated log\n", encoding="utf-8")
    os.utime(rotated, (old_mtime, old_mtime))

    maintain_runtime_directory(tmp_path, now=now)

    for filename in ACTIVE_RUNTIME_TEXT_FILENAMES:
        assert (tmp_path / filename).read_text(encoding="utf-8") == "active log\n"
        assert not (tmp_path / f"{filename}.gz").exists()
    assert not rotated.exists()
    assert (tmp_path / f"{rotated.name}.gz").exists()


def test_runtime_maintenance_preserves_temporary_runtime_files(tmp_path):
    now = time.time()
    old_mtime = now - 8 * 24 * 60 * 60
    temporary_files = (
        tmp_path / "teebotus-production.log.tmp",
        tmp_path / ".teebotus-production.log.2026-06-01.gz.tmp",
        tmp_path / "Security_Events.jsonl.tmp",
    )
    for path in temporary_files:
        path.write_text("temporary\n", encoding="utf-8")
        os.utime(path, (old_mtime, old_mtime))
    rotated = tmp_path / "teebotus-production.log.2026-06-01"
    rotated.write_text("rotated log\n", encoding="utf-8")
    os.utime(rotated, (old_mtime, old_mtime))

    maintain_runtime_directory(tmp_path, now=now)

    for path in temporary_files:
        assert path.read_text(encoding="utf-8") == "temporary\n"
        assert not (tmp_path / f"{path.name}.gz").exists()
    assert not rotated.exists()
    assert (tmp_path / f"{rotated.name}.gz").exists()


def test_runtime_maintenance_does_not_recompress_numbered_compressed_logs(tmp_path):
    now = time.time()
    old_mtime = now - 8 * 24 * 60 * 60
    path = tmp_path / "teebotus-production.log.2026-06-01.gz.1"
    path.write_bytes(b"compressed-ish")
    os.utime(path, (old_mtime, old_mtime))

    maintain_runtime_directory(tmp_path, now=now)

    assert path.read_bytes() == b"compressed-ish"
    assert not (tmp_path / f"{path.name}.gz").exists()


def test_runtime_maintenance_preserves_symlinked_runtime_text_files(tmp_path):
    now = time.time()
    old_mtime = now - 8 * 24 * 60 * 60
    target = tmp_path / "external-target.txt"
    target.write_text("do not copy\n", encoding="utf-8")
    symlink = tmp_path / "linked-runtime.log"
    symlink.symlink_to(target)
    os.utime(symlink, (old_mtime, old_mtime), follow_symlinks=False)
    rotated = tmp_path / "teebotus-production.log.2026-06-01"
    rotated.write_text("rotated log\n", encoding="utf-8")
    os.utime(rotated, (old_mtime, old_mtime))

    maintain_runtime_directory(tmp_path, now=now)

    assert symlink.is_symlink()
    assert symlink.read_text(encoding="utf-8") == "do not copy\n"
    assert not (tmp_path / f"{symlink.name}.gz").exists()
    assert not rotated.exists()
    assert (tmp_path / f"{rotated.name}.gz").exists()


def test_runtime_maintenance_skips_text_files_that_disappear_during_scan(tmp_path, monkeypatch):
    now = time.time()
    old_mtime = now - 8 * 24 * 60 * 60
    disappearing = tmp_path / "Security_Events.jsonl"
    disappearing.write_text("gone\n", encoding="utf-8")
    os.utime(disappearing, (old_mtime, old_mtime))
    rotated = tmp_path / "teebotus-production.log.2026-06-01"
    rotated.write_text("rotated log\n", encoding="utf-8")
    os.utime(rotated, (old_mtime, old_mtime))
    real_stat = Path.stat
    raced = False

    def disappearing_stat(self, *args, **kwargs):
        nonlocal raced
        if self == disappearing and kwargs.get("follow_symlinks") is False and not raced:
            raced = True
            disappearing.unlink()
            raise FileNotFoundError(self)
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", disappearing_stat)

    maintain_runtime_directory(tmp_path, now=now)

    assert raced is True
    assert not disappearing.exists()
    assert not rotated.exists()
    assert (tmp_path / f"{rotated.name}.gz").exists()


def test_runtime_maintenance_skips_text_scan_when_runtime_glob_fails(tmp_path, monkeypatch):
    now = time.time()
    real_glob = Path.glob

    def fail_runtime_glob(self, pattern):
        if self == tmp_path:
            raise PermissionError(f"glob failed for {pattern}")
        return real_glob(self, pattern)

    monkeypatch.setattr(Path, "glob", fail_runtime_glob)

    maintain_runtime_directory(tmp_path, now=now)

    assert not (tmp_path / "monthly_archives").exists()


def test_runtime_maintenance_skips_text_file_replaced_by_symlink_after_scan(tmp_path, monkeypatch):
    now = time.time()
    old_mtime = now - 8 * 24 * 60 * 60
    path = tmp_path / "teebotus-production.log.2026-06-01"
    path.write_text("old log\n", encoding="utf-8")
    os.utime(path, (old_mtime, old_mtime))
    external = tmp_path / "external-target.txt"
    external.write_text("do not copy\n", encoding="utf-8")
    real_stat = Path.stat
    stat_calls = 0

    def racing_stat(self, *args, **kwargs):
        nonlocal stat_calls
        if self == path and kwargs.get("follow_symlinks") is False:
            stat_calls += 1
            if stat_calls == 2:
                path.unlink()
                path.symlink_to(external)
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", racing_stat)

    maintain_runtime_directory(tmp_path, now=now)

    assert stat_calls == 2
    assert path.is_symlink()
    assert external.read_text(encoding="utf-8") == "do not copy\n"
    assert not (tmp_path / f"{path.name}.gz").exists()


def test_gzip_file_preserves_symlinked_runtime_file(tmp_path):
    target = tmp_path / "external-target.txt"
    target.write_text("do not copy\n", encoding="utf-8")
    symlink = tmp_path / "linked-runtime.log"
    symlink.symlink_to(target)

    assert gzip_file(symlink) == symlink

    assert symlink.is_symlink()
    assert target.read_text(encoding="utf-8") == "do not copy\n"
    assert not (tmp_path / f"{symlink.name}.gz").exists()


def test_gzip_file_accepts_string_path(tmp_path):
    path = tmp_path / "teebotus-production.log.2026-06-01"
    path.write_text("old log\n", encoding="utf-8")

    published = gzip_file(str(path))

    assert published == tmp_path / f"{path.name}.gz"
    assert not path.exists()
    with gzip.open(published, "rt", encoding="utf-8") as handle:
        assert handle.read() == "old log\n"


def test_gzip_file_preserves_temporary_runtime_file(tmp_path):
    path = tmp_path / ".teebotus-production.log.2026-06-01.gz.tmp"
    path.write_text("temporary\n", encoding="utf-8")

    assert gzip_file(path) == path

    assert path.read_text(encoding="utf-8") == "temporary\n"
    assert not (tmp_path / f"{path.name}.gz").exists()


def test_gzip_file_preserves_path_replaced_by_symlink_before_open(tmp_path, monkeypatch):
    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("O_NOFOLLOW is required to reject symlink open races")
    path = tmp_path / "teebotus-production.log.2026-06-01"
    path.write_text("old log\n", encoding="utf-8")
    external = tmp_path / "external-target.txt"
    external.write_text("do not copy\n", encoding="utf-8")
    real_open = os.open
    raced = False

    def racing_open(file, flags, *args, **kwargs):
        nonlocal raced
        if Path(file) == path and not raced:
            raced = True
            path.unlink()
            path.symlink_to(external)
        return real_open(file, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", racing_open)

    assert gzip_file(path) == path

    assert raced is True
    assert path.is_symlink()
    assert external.read_text(encoding="utf-8") == "do not copy\n"
    assert not (tmp_path / f"{path.name}.gz").exists()


def test_gzip_file_does_not_overwrite_target_created_during_publish(tmp_path, monkeypatch):
    path = tmp_path / "teebotus-production.log.2026-06-01"
    path.write_text("old log\n", encoding="utf-8")
    target = tmp_path / f"{path.name}.gz"
    real_link = os.link
    raced = False

    def racing_link(source, destination, *args, **kwargs):
        nonlocal raced
        destination_path = Path(destination)
        if destination_path == target and not raced:
            raced = True
            destination_path.write_text("existing target\n", encoding="utf-8")
            raise FileExistsError(destination)
        return real_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "link", racing_link)

    published = gzip_file(path)

    assert raced is True
    assert target.read_text(encoding="utf-8") == "existing target\n"
    assert published != target
    assert published.exists()
    assert not path.exists()
    with gzip.open(published, "rt", encoding="utf-8") as handle:
        assert handle.read() == "old log\n"


def test_gzip_file_skips_broken_symlink_target(tmp_path):
    path = tmp_path / "teebotus-production.log.2026-06-01"
    path.write_text("old log\n", encoding="utf-8")
    blocked_target = tmp_path / f"{path.name}.gz"
    blocked_target.symlink_to(tmp_path / "missing-target")

    published = gzip_file(path)

    assert published.name == f"{blocked_target.name}.1"
    assert blocked_target.is_symlink()
    assert not path.exists()
    with gzip.open(published, "rt", encoding="utf-8") as handle:
        assert handle.read() == "old log\n"


def test_gzip_file_skips_target_when_existence_check_fails(tmp_path, monkeypatch):
    path = tmp_path / "teebotus-production.log.2026-06-01"
    path.write_text("old log\n", encoding="utf-8")
    blocked_target = tmp_path / f"{path.name}.gz"
    real_lexists = os.path.lexists

    def fail_target_lexists(file):
        if Path(file) == blocked_target:
            raise PermissionError("cannot inspect target")
        return real_lexists(file)

    monkeypatch.setattr(os.path, "lexists", fail_target_lexists)

    published = gzip_file(path)

    assert published == blocked_target.with_name(f"{blocked_target.name}.1")
    assert not blocked_target.exists()
    assert not path.exists()
    with gzip.open(published, "rt", encoding="utf-8") as handle:
        assert handle.read() == "old log\n"


def test_gzip_file_does_not_overwrite_temporary_file_created_during_open(tmp_path, monkeypatch):
    path = tmp_path / "teebotus-production.log.2026-06-01"
    path.write_text("old log\n", encoding="utf-8")
    blocked_temporary = tmp_path / f".{path.name}.gz.tmp"
    real_open = os.open
    raced = False

    def racing_open(file, flags, *args, **kwargs):
        nonlocal raced
        file_path = Path(file)
        if file_path == blocked_temporary and flags & os.O_CREAT and not raced:
            raced = True
            blocked_temporary.write_text("existing temporary\n", encoding="utf-8")
            raise FileExistsError(file)
        return real_open(file, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", racing_open)

    published = gzip_file(path)

    assert raced is True
    assert blocked_temporary.read_text(encoding="utf-8") == "existing temporary\n"
    assert not (tmp_path / f"{blocked_temporary.name}.1").exists()
    assert not path.exists()
    with gzip.open(published, "rt", encoding="utf-8") as handle:
        assert handle.read() == "old log\n"


def test_gzip_file_does_not_publish_temporary_path_replaced_before_publish(tmp_path, monkeypatch):
    path = tmp_path / "teebotus-production.log.2026-06-01"
    path.write_text("old log\n", encoding="utf-8")
    target = tmp_path / f"{path.name}.gz"
    temporary = tmp_path / f".{target.name}.tmp"
    external = tmp_path / "external-target"
    external.write_text("do not publish\n", encoding="utf-8")
    real_link = os.link
    raced = False

    def racing_link(source, destination, *args, **kwargs):
        nonlocal raced
        if Path(source) == temporary and Path(destination) == target and not raced:
            raced = True
            temporary.unlink()
            temporary.symlink_to(external)
        return real_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "link", racing_link)

    with pytest.raises(OSError, match="temporary file changed before publish"):
        gzip_file(path)

    assert raced is True
    assert path.read_text(encoding="utf-8") == "old log\n"
    assert temporary.is_symlink()
    assert external.read_text(encoding="utf-8") == "do not publish\n"
    assert not os.path.lexists(target)


def test_gzip_file_does_not_utime_temporary_symlink_replacement(tmp_path, monkeypatch):
    source_mtime = 1_700_000_000
    external_mtime = 1_710_000_000
    path = tmp_path / "teebotus-production.log.2026-06-01"
    path.write_text("old log\n", encoding="utf-8")
    os.utime(path, (source_mtime, source_mtime))
    target = tmp_path / f"{path.name}.gz"
    temporary = tmp_path / f".{target.name}.tmp"
    external = tmp_path / "external-target"
    external.write_text("do not touch mtime\n", encoding="utf-8")
    os.utime(external, (external_mtime, external_mtime))
    real_utime = os.utime
    raced = False

    def racing_utime(file, times=None, *args, **kwargs):
        nonlocal raced
        if Path(file) == temporary and not raced:
            raced = True
            temporary.unlink()
            temporary.symlink_to(external)
        return real_utime(file, times, *args, **kwargs)

    monkeypatch.setattr(os, "utime", racing_utime)

    with pytest.raises(OSError, match="temporary file changed before publish"):
        gzip_file(path)

    assert raced is True
    assert path.read_text(encoding="utf-8") == "old log\n"
    assert temporary.is_symlink()
    assert external.stat().st_mtime == pytest.approx(external_mtime)
    assert not os.path.lexists(target)


def test_gzip_file_preserves_source_replaced_before_cleanup(tmp_path, monkeypatch):
    path = tmp_path / "teebotus-production.log.2026-06-01"
    path.write_text("old log\n", encoding="utf-8")
    target = tmp_path / f"{path.name}.gz"
    real_link = os.link
    raced = False

    def racing_link(source, destination, *args, **kwargs):
        nonlocal raced
        real_link(source, destination, *args, **kwargs)
        if Path(destination) == target and not raced:
            raced = True
            path.unlink()
            path.write_text("new log\n", encoding="utf-8")

    monkeypatch.setattr(os, "link", racing_link)

    published = gzip_file(path)

    assert raced is True
    assert published == target
    assert path.read_text(encoding="utf-8") == "new log\n"
    with gzip.open(published, "rt", encoding="utf-8") as handle:
        assert handle.read() == "old log\n"


def test_gzip_file_keeps_published_target_when_temporary_cleanup_fails(tmp_path, monkeypatch):
    path = tmp_path / "teebotus-production.log.2026-06-01"
    path.write_text("old log\n", encoding="utf-8")
    original_unlink = Path.unlink

    def fail_temporary_unlink(self, *_args, **_kwargs):
        if self.name.startswith(".") and ".gz.tmp" in self.name:
            raise PermissionError("cleanup failed")
        return original_unlink(self)

    monkeypatch.setattr(Path, "unlink", fail_temporary_unlink)

    published = gzip_file(path)

    assert published.exists()
    assert not path.exists()
    with gzip.open(published, "rt", encoding="utf-8") as handle:
        assert handle.read() == "old log\n"
    temporary_files = list(tmp_path.glob(".*.tmp"))
    assert len(temporary_files) == 1


def test_gzip_file_keeps_published_target_when_source_disappears_after_publish(tmp_path, monkeypatch):
    path = tmp_path / "teebotus-production.log.2026-06-01"
    path.write_text("old log\n", encoding="utf-8")
    original_unlink = Path.unlink
    raced = False

    def disappear_source_unlink(self, *_args, **_kwargs):
        nonlocal raced
        if self == path and not raced:
            raced = True
            original_unlink(self)
            raise FileNotFoundError(self)
        return original_unlink(self)

    monkeypatch.setattr(Path, "unlink", disappear_source_unlink)

    published = gzip_file(path)

    assert raced is True
    assert published.exists()
    assert not path.exists()
    with gzip.open(published, "rt", encoding="utf-8") as handle:
        assert handle.read() == "old log\n"


def test_gzip_file_removes_partial_temporary_file_on_copy_failure(tmp_path, monkeypatch):
    path = tmp_path / "teebotus-production.log.2026-06-01"
    path.write_text("old log\n", encoding="utf-8")

    def fail_copy(*_args, **_kwargs):
        raise OSError("copy failed")

    monkeypatch.setattr(shutil, "copyfileobj", fail_copy)

    with pytest.raises(OSError, match="copy failed"):
        gzip_file(path)

    assert path.read_text(encoding="utf-8") == "old log\n"
    assert not (tmp_path / f"{path.name}.gz").exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_gzip_file_removes_temporary_file_when_source_fdopen_fails(tmp_path, monkeypatch):
    path = tmp_path / "teebotus-production.log.2026-06-01"
    path.write_text("old log\n", encoding="utf-8")
    real_fdopen = os.fdopen
    real_close = os.close
    closed_fds: list[int] = []

    def fail_source_fdopen(fd, mode="r", *args, **kwargs):
        if mode == "rb":
            raise OSError("source fdopen failed")
        return real_fdopen(fd, mode, *args, **kwargs)

    def counting_close(fd):
        closed_fds.append(fd)
        return real_close(fd)

    monkeypatch.setattr(os, "fdopen", fail_source_fdopen)
    monkeypatch.setattr(os, "close", counting_close)

    with pytest.raises(OSError, match="source fdopen failed"):
        gzip_file(path)

    assert path.read_text(encoding="utf-8") == "old log\n"
    assert not (tmp_path / f"{path.name}.gz").exists()
    assert not list(tmp_path.glob(".*.tmp"))
    assert len(closed_fds) >= 2


def test_gzip_file_closes_source_fd_when_temporary_open_fails(tmp_path, monkeypatch):
    path = tmp_path / "teebotus-production.log.2026-06-01"
    path.write_text("old log\n", encoding="utf-8")
    real_open = os.open
    real_close = os.close
    source_fd: int | None = None
    closed_fds: list[int] = []

    def fail_temporary_open(file, flags, *args, **kwargs):
        nonlocal source_fd
        file_path = Path(file)
        if file_path == path:
            source_fd = real_open(file, flags, *args, **kwargs)
            return source_fd
        if file_path.name.startswith(f".{path.name}.gz.tmp") and flags & os.O_CREAT:
            raise PermissionError("temporary open failed")
        return real_open(file, flags, *args, **kwargs)

    def counting_close(fd):
        closed_fds.append(fd)
        return real_close(fd)

    monkeypatch.setattr(os, "open", fail_temporary_open)
    monkeypatch.setattr(os, "close", counting_close)

    with pytest.raises(PermissionError, match="temporary open failed"):
        gzip_file(path)

    assert source_fd in closed_fds
    assert path.read_text(encoding="utf-8") == "old log\n"
    assert not (tmp_path / f"{path.name}.gz").exists()
    assert not list(tmp_path.glob(".*.tmp"))


def test_gzip_file_closes_temporary_fd_when_temporary_stat_fails(tmp_path, monkeypatch):
    path = tmp_path / "teebotus-production.log.2026-06-01"
    path.write_text("old log\n", encoding="utf-8")
    real_open = os.open
    real_fstat = os.fstat
    real_close = os.close
    temporary_fd: int | None = None
    closed_fds: list[int] = []

    def recording_open(file, flags, *args, **kwargs):
        nonlocal temporary_fd
        fd = real_open(file, flags, *args, **kwargs)
        if Path(file).name.startswith(f".{path.name}.gz.tmp") and flags & os.O_CREAT:
            temporary_fd = fd
        return fd

    def fail_temporary_fstat(fd):
        if fd == temporary_fd:
            raise ValueError("temporary stat failed")
        return real_fstat(fd)

    def counting_close(fd):
        closed_fds.append(fd)
        return real_close(fd)

    monkeypatch.setattr(os, "open", recording_open)
    monkeypatch.setattr(os, "fstat", fail_temporary_fstat)
    monkeypatch.setattr(os, "close", counting_close)

    with pytest.raises(ValueError, match="temporary stat failed"):
        gzip_file(path)

    assert temporary_fd in closed_fds
    assert path.read_text(encoding="utf-8") == "old log\n"
    assert not (tmp_path / f"{path.name}.gz").exists()
    assert len(list(tmp_path.glob(".*.tmp"))) == 1


def test_gzip_file_preserves_primary_error_when_fd_close_cleanup_fails(tmp_path, monkeypatch):
    path = tmp_path / "teebotus-production.log.2026-06-01"
    path.write_text("old log\n", encoding="utf-8")
    real_fdopen = os.fdopen
    real_close = os.close

    def fail_source_fdopen(fd, mode="r", *args, **kwargs):
        if mode == "rb":
            raise OSError("source fdopen failed")
        return real_fdopen(fd, mode, *args, **kwargs)

    def fail_close_after_closing(fd):
        real_close(fd)
        raise OSError("close cleanup failed")

    monkeypatch.setattr(os, "fdopen", fail_source_fdopen)
    monkeypatch.setattr(os, "close", fail_close_after_closing)

    with pytest.raises(OSError, match="source fdopen failed"):
        gzip_file(path)

    assert path.read_text(encoding="utf-8") == "old log\n"
    assert not (tmp_path / f"{path.name}.gz").exists()
    assert not list(tmp_path.glob(".*.tmp"))


def test_gzip_file_preserves_primary_error_when_temporary_cleanup_fails(tmp_path, monkeypatch):
    path = tmp_path / "teebotus-production.log.2026-06-01"
    path.write_text("old log\n", encoding="utf-8")
    original_unlink = Path.unlink

    def fail_copy(*_args, **_kwargs):
        raise OSError("copy failed")

    def fail_temporary_unlink(self, *_args, **_kwargs):
        if self.name.startswith(".") and ".gz.tmp" in self.name:
            raise PermissionError("cleanup failed")
        return original_unlink(self)

    monkeypatch.setattr(shutil, "copyfileobj", fail_copy)
    monkeypatch.setattr(Path, "unlink", fail_temporary_unlink)

    with pytest.raises(OSError, match="copy failed"):
        gzip_file(path)

    assert path.read_text(encoding="utf-8") == "old log\n"


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


def test_runtime_maintenance_archives_numbered_compressed_logs(tmp_path):
    now = time.time()
    old_mtime = now - 70 * 24 * 60 * 60
    path = tmp_path / "teebotus-production.log.2026-03-01.gz.1"
    path.write_bytes(b"compressed-ish")
    os.utime(path, (old_mtime, old_mtime))

    maintain_runtime_directory(tmp_path, now=now)

    archives = sorted((tmp_path / "monthly_archives").glob("teebotus-runtime-*.tar.gz"))
    assert len(archives) == 1
    assert not path.exists()
    with tarfile.open(archives[0], "r:gz") as archive:
        assert path.name in archive.getnames()


def test_runtime_maintenance_skips_compressed_directories_before_archive_setup(tmp_path):
    now = time.time()
    old_mtime = now - 70 * 24 * 60 * 60
    directory = tmp_path / "teebotus-production.log.2026-03-01.gz"
    directory.mkdir()
    os.utime(directory, (old_mtime, old_mtime))

    maintain_runtime_directory(tmp_path, now=now)

    assert directory.is_dir()
    assert not (tmp_path / "monthly_archives").exists()


def test_runtime_maintenance_skips_archive_scan_when_runtime_listing_fails(tmp_path, monkeypatch):
    now = time.time()
    real_iterdir = Path.iterdir

    def fail_runtime_iterdir(self):
        if self == tmp_path:
            raise PermissionError("runtime listing failed")
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", fail_runtime_iterdir)

    maintain_runtime_directory(tmp_path, now=now)

    assert not (tmp_path / "monthly_archives").exists()


def test_runtime_maintenance_keeps_sources_when_archive_write_fails(tmp_path, monkeypatch):
    now = time.time()
    old_mtime = now - 70 * 24 * 60 * 60
    path = tmp_path / "teebotus-production.log.2026-03-01.gz"
    path.write_bytes(b"compressed-ish")
    os.utime(path, (old_mtime, old_mtime))

    def fail_addfile(_self, _tarinfo, _fileobj=None):
        raise OSError("unexpected end of data")

    monkeypatch.setattr(tarfile.TarFile, "addfile", fail_addfile)

    maintain_runtime_directory(tmp_path, now=now)

    assert path.read_bytes() == b"compressed-ish"
    assert not list((tmp_path / "monthly_archives").glob("teebotus-runtime-*.tar.gz"))
    assert not list((tmp_path / "monthly_archives").glob("*.tmp"))


def test_runtime_maintenance_keeps_sources_when_archive_fdopen_fails(tmp_path, monkeypatch):
    now = time.time()
    old_mtime = now - 70 * 24 * 60 * 60
    path = tmp_path / "teebotus-production.log.2026-03-01.gz"
    path.write_bytes(b"compressed-ish")
    os.utime(path, (old_mtime, old_mtime))
    real_fdopen = os.fdopen

    def fail_archive_fdopen(fd, mode="r", *args, **kwargs):
        if mode == "wb":
            raise ValueError("archive fdopen failed")
        return real_fdopen(fd, mode, *args, **kwargs)

    monkeypatch.setattr(os, "fdopen", fail_archive_fdopen)

    maintain_runtime_directory(tmp_path, now=now)

    assert path.read_bytes() == b"compressed-ish"
    assert not list((tmp_path / "monthly_archives").glob("teebotus-runtime-*.tar.gz"))
    assert not list((tmp_path / "monthly_archives").glob("*.tmp"))


def test_runtime_maintenance_keeps_sources_when_archive_directory_is_blocked(tmp_path):
    now = time.time()
    old_mtime = now - 70 * 24 * 60 * 60
    path = tmp_path / "teebotus-production.log.2026-03-01.gz"
    path.write_bytes(b"compressed-ish")
    os.utime(path, (old_mtime, old_mtime))
    blocked_archive_dir = tmp_path / "monthly_archives"
    blocked_archive_dir.write_text("not a directory\n", encoding="utf-8")

    maintain_runtime_directory(tmp_path, now=now)

    assert path.read_bytes() == b"compressed-ish"
    assert blocked_archive_dir.read_text(encoding="utf-8") == "not a directory\n"


def test_runtime_maintenance_refuses_symlinked_archive_directory(tmp_path):
    now = time.time()
    old_mtime = now - 70 * 24 * 60 * 60
    path = tmp_path / "teebotus-production.log.2026-03-01.gz"
    path.write_bytes(b"compressed-ish")
    os.utime(path, (old_mtime, old_mtime))
    external_archive_dir = tmp_path / "external-archives"
    external_archive_dir.mkdir()
    archive_dir = tmp_path / "monthly_archives"
    archive_dir.symlink_to(external_archive_dir, target_is_directory=True)

    maintain_runtime_directory(tmp_path, now=now)

    assert path.read_bytes() == b"compressed-ish"
    assert archive_dir.is_symlink()
    assert not list(external_archive_dir.iterdir())


def test_runtime_maintenance_groups_compressed_logs_with_single_stat(tmp_path, monkeypatch):
    now = time.time()
    old_mtime = now - 70 * 24 * 60 * 60
    path = tmp_path / "teebotus-production.log.2026-03-01.gz"
    path.write_bytes(b"compressed-ish")
    os.utime(path, (old_mtime, old_mtime))
    real_stat = Path.stat
    stat_calls: dict[Path, int] = {}

    def counting_stat(self, *args, **kwargs):
        if self == path:
            stat_calls[self] = stat_calls.get(self, 0) + 1
            if stat_calls[self] > 1:
                raise FileNotFoundError(self)
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", counting_stat)

    maintain_runtime_directory(tmp_path, now=now)

    assert stat_calls[path] == 1
    archives = sorted((tmp_path / "monthly_archives").glob("teebotus-runtime-*.tar.gz"))
    assert len(archives) == 1


def test_runtime_maintenance_preserves_temporary_compressed_runtime_files(tmp_path):
    now = time.time()
    old_mtime = now - 70 * 24 * 60 * 60
    temporary_files = (
        tmp_path / "teebotus-production.log.tmp.gz",
        tmp_path / ".teebotus-production.log.2026-03-01.gz",
    )
    for path in temporary_files:
        path.write_bytes(b"temporary")
        os.utime(path, (old_mtime, old_mtime))
    archiveable = tmp_path / "teebotus-production.log.2026-03-01.gz"
    archiveable.write_bytes(b"compressed-ish")
    os.utime(archiveable, (old_mtime, old_mtime))

    maintain_runtime_directory(tmp_path, now=now)

    for path in temporary_files:
        assert path.exists()
    assert not archiveable.exists()
    archives = sorted((tmp_path / "monthly_archives").glob("teebotus-runtime-*.tar.gz"))
    assert len(archives) == 1
    with tarfile.open(archives[0], "r:gz") as archive:
        names = archive.getnames()
    assert archiveable.name in names
    assert all(path.name not in names for path in temporary_files)


def test_runtime_maintenance_does_not_overwrite_archive_created_during_publish(tmp_path, monkeypatch):
    now = time.time()
    old_mtime = now - 70 * 24 * 60 * 60
    path = tmp_path / "teebotus-production.log.2026-03-01.gz"
    path.write_bytes(b"compressed-ish")
    os.utime(path, (old_mtime, old_mtime))
    real_link = os.link
    raced_target: Path | None = None

    def racing_link(source, destination, *args, **kwargs):
        nonlocal raced_target
        destination_path = Path(destination)
        if destination_path.parent.name == "monthly_archives" and raced_target is None:
            raced_target = destination_path
            destination_path.write_bytes(b"existing archive")
            raise FileExistsError(destination)
        return real_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "link", racing_link)

    maintain_runtime_directory(tmp_path, now=now)

    assert raced_target is not None
    assert raced_target.read_bytes() == b"existing archive"
    archives = sorted((tmp_path / "monthly_archives").glob("teebotus-runtime-*.tar.gz*"))
    published_archives = [archive for archive in archives if archive != raced_target]
    assert len(published_archives) == 1
    assert not path.exists()
    with tarfile.open(published_archives[0], "r:gz") as archive:
        assert path.name in archive.getnames()


def test_runtime_maintenance_skips_broken_symlink_archive_target(tmp_path):
    now = time.time()
    old_mtime = time.mktime(time.strptime("2026-03-01", "%Y-%m-%d"))
    path = tmp_path / "teebotus-production.log.2026-03-01.gz"
    path.write_bytes(b"compressed-ish")
    os.utime(path, (old_mtime, old_mtime))
    archive_dir = tmp_path / "monthly_archives"
    archive_dir.mkdir()
    blocked_target = archive_dir / "teebotus-runtime-2026-03.tar.gz"
    blocked_target.symlink_to(tmp_path / "missing-target")

    maintain_runtime_directory(tmp_path, now=now)

    assert blocked_target.is_symlink()
    archives = sorted(archive_dir.glob("teebotus-runtime-2026-03.tar.gz*"))
    published_archives = [archive for archive in archives if archive != blocked_target]
    assert len(published_archives) == 1
    assert published_archives[0].name == f"{blocked_target.name}.1"
    with tarfile.open(published_archives[0], "r:gz") as archive:
        assert path.name in archive.getnames()


def test_runtime_maintenance_does_not_overwrite_archive_temporary_file_created_during_open(tmp_path, monkeypatch):
    now = time.time()
    old_mtime = time.mktime(time.strptime("2026-03-01", "%Y-%m-%d"))
    path = tmp_path / "teebotus-production.log.2026-03-01.gz"
    path.write_bytes(b"compressed-ish")
    os.utime(path, (old_mtime, old_mtime))
    archive_dir = tmp_path / "monthly_archives"
    blocked_temporary = archive_dir / ".teebotus-runtime-2026-03.tar.gz.tmp"
    real_open = os.open
    raced = False

    def racing_open(file, flags, *args, **kwargs):
        nonlocal raced
        file_path = Path(file)
        if file_path == blocked_temporary and flags & os.O_CREAT and not raced:
            raced = True
            blocked_temporary.write_text("existing temporary\n", encoding="utf-8")
            raise FileExistsError(file)
        return real_open(file, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", racing_open)

    maintain_runtime_directory(tmp_path, now=now)

    assert raced is True
    assert blocked_temporary.read_text(encoding="utf-8") == "existing temporary\n"
    assert not (archive_dir / f"{blocked_temporary.name}.1").exists()
    archives = sorted(archive_dir.glob("teebotus-runtime-2026-03.tar.gz*"))
    assert len(archives) == 1
    with tarfile.open(archives[0], "r:gz") as archive:
        assert path.name in archive.getnames()


def test_runtime_maintenance_preserves_archived_path_replaced_before_cleanup(tmp_path, monkeypatch):
    now = time.time()
    old_mtime = now - 70 * 24 * 60 * 60
    path = tmp_path / "teebotus-production.log.2026-03-01.gz"
    path.write_bytes(b"compressed-ish")
    os.utime(path, (old_mtime, old_mtime))
    real_link = os.link
    raced = False

    def racing_link(source, destination, *args, **kwargs):
        nonlocal raced
        real_link(source, destination, *args, **kwargs)
        destination_path = Path(destination)
        if destination_path.parent.name == "monthly_archives" and not raced:
            raced = True
            path.unlink()
            path.write_bytes(b"replacement")

    monkeypatch.setattr(os, "link", racing_link)

    maintain_runtime_directory(tmp_path, now=now)

    assert raced is True
    assert path.read_bytes() == b"replacement"
    archives = sorted((tmp_path / "monthly_archives").glob("teebotus-runtime-*.tar.gz"))
    assert len(archives) == 1
    with tarfile.open(archives[0], "r:gz") as archive:
        member = archive.extractfile(path.name)
        assert member is not None
        assert member.read() == b"compressed-ish"


def test_runtime_maintenance_preserves_symlinked_compressed_runtime_files(tmp_path):
    now = time.time()
    old_mtime = now - 70 * 24 * 60 * 60
    target = tmp_path / "external-compressed.gz"
    target.write_bytes(b"do-not-archive")
    symlink = tmp_path / "linked-runtime.log.gz"
    symlink.symlink_to(target)
    os.utime(symlink, (old_mtime, old_mtime), follow_symlinks=False)
    archiveable = tmp_path / "teebotus-production.log.2026-03-01.gz"
    archiveable.write_bytes(b"compressed-ish")
    os.utime(archiveable, (old_mtime, old_mtime))

    maintain_runtime_directory(tmp_path, now=now)

    assert symlink.is_symlink()
    assert target.exists()
    assert not archiveable.exists()
    archives = sorted((tmp_path / "monthly_archives").glob("teebotus-runtime-*.tar.gz"))
    assert len(archives) == 1
    with tarfile.open(archives[0], "r:gz") as archive:
        names = archive.getnames()
    assert archiveable.name in names
    assert symlink.name not in names


def test_runtime_maintenance_skips_compressed_file_replaced_by_symlink_during_scan(tmp_path, monkeypatch):
    now = time.time()
    old_mtime = now - 70 * 24 * 60 * 60
    path = tmp_path / "teebotus-production.log.2026-03-01.gz"
    path.write_bytes(b"compressed-ish")
    os.utime(path, (old_mtime, old_mtime))
    external = tmp_path / "external.gz"
    external.write_bytes(b"do-not-archive")
    real_stat = Path.stat
    raced = False

    def racing_stat(self, *args, **kwargs):
        nonlocal raced
        if self == path and kwargs.get("follow_symlinks") is False and not raced:
            raced = True
            path.unlink()
            path.symlink_to(external)
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", racing_stat)

    maintain_runtime_directory(tmp_path, now=now)

    assert raced is True
    assert path.is_symlink()
    assert external.read_bytes() == b"do-not-archive"
    assert not list((tmp_path / "monthly_archives").glob("teebotus-runtime-*.tar.gz"))


def test_runtime_maintenance_skips_archive_files_that_disappear_before_open(tmp_path, monkeypatch):
    now = time.time()
    old_mtime = now - 70 * 24 * 60 * 60
    path = tmp_path / "teebotus-production.log.2026-03-01.gz"
    path.write_bytes(b"compressed-ish")
    os.utime(path, (old_mtime, old_mtime))
    real_open = os.open

    def disappearing_open(file, flags, *args, **kwargs):
        if Path(file) == path:
            os.unlink(path)
            raise FileNotFoundError(path)
        return real_open(file, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", disappearing_open)

    maintain_runtime_directory(tmp_path, now=now)

    assert not path.exists()
    assert not list((tmp_path / "monthly_archives").glob("teebotus-runtime-*.tar.gz"))
    assert not list((tmp_path / "monthly_archives").glob("*.tmp"))


def test_runtime_maintenance_closes_archive_source_fd_when_fdopen_fails(tmp_path, monkeypatch):
    now = time.time()
    old_mtime = now - 70 * 24 * 60 * 60
    path = tmp_path / "teebotus-production.log.2026-03-01.gz"
    path.write_bytes(b"compressed-ish")
    os.utime(path, (old_mtime, old_mtime))
    real_fdopen = os.fdopen
    real_close = os.close
    source_fd: int | None = None
    closed_fds: set[int] = set()

    def fail_archive_source_fdopen(fd, mode="r", *args, **kwargs):
        nonlocal source_fd
        if mode == "rb":
            source_fd = fd
            raise ValueError("archive source fdopen failed")
        return real_fdopen(fd, mode, *args, **kwargs)

    def recording_close(fd):
        closed_fds.add(fd)
        return real_close(fd)

    monkeypatch.setattr(os, "fdopen", fail_archive_source_fdopen)
    monkeypatch.setattr(os, "close", recording_close)

    maintain_runtime_directory(tmp_path, now=now)

    assert source_fd is not None
    assert source_fd in closed_fds
    assert path.read_bytes() == b"compressed-ish"
    assert not list((tmp_path / "monthly_archives").glob("teebotus-runtime-*.tar.gz"))


def test_runtime_maintenance_skips_archive_files_replaced_before_open(tmp_path, monkeypatch):
    now = time.time()
    old_mtime = now - 70 * 24 * 60 * 60
    path = tmp_path / "teebotus-production.log.2026-03-01.gz"
    path.write_bytes(b"compressed-ish")
    os.utime(path, (old_mtime, old_mtime))
    real_open = os.open
    raced = False

    def racing_open(file, flags, *args, **kwargs):
        nonlocal raced
        if Path(file) == path and not raced:
            raced = True
            path.unlink()
            path.write_bytes(b"replacement")
            os.utime(path, (now, now))
        return real_open(file, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", racing_open)

    maintain_runtime_directory(tmp_path, now=now)

    assert raced is True
    assert path.read_bytes() == b"replacement"
    assert not list((tmp_path / "monthly_archives").glob("teebotus-runtime-*.tar.gz"))
    assert not list((tmp_path / "monthly_archives").glob("*.tmp"))


def test_runtime_maintenance_skips_archive_files_replaced_by_symlink_before_open(tmp_path, monkeypatch):
    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("O_NOFOLLOW is required to reject symlink archive races")
    now = time.time()
    old_mtime = now - 70 * 24 * 60 * 60
    path = tmp_path / "teebotus-production.log.2026-03-01.gz"
    path.write_bytes(b"compressed-ish")
    os.utime(path, (old_mtime, old_mtime))
    external = tmp_path / "external.gz"
    external.write_bytes(b"do-not-archive")
    real_open = os.open
    raced = False

    def racing_open(file, flags, *args, **kwargs):
        nonlocal raced
        if Path(file) == path and not raced:
            raced = True
            path.unlink()
            path.symlink_to(external)
        return real_open(file, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", racing_open)

    maintain_runtime_directory(tmp_path, now=now)

    assert raced is True
    assert path.is_symlink()
    assert external.read_bytes() == b"do-not-archive"
    assert not list((tmp_path / "monthly_archives").glob("teebotus-runtime-*.tar.gz"))
    assert not list((tmp_path / "monthly_archives").glob("*.tmp"))


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


def test_normalize_log_level_accepts_documented_debug_all_spellings():
    assert normalize_log_level("debug_all") == DEBUG_ALL
    assert normalize_log_level("debug-all") == DEBUG_ALL
    assert normalize_log_level("finest") == DEBUG_ALL
    assert normalize_log_level(1) == DEBUG_ALL
    assert normalize_log_level("1") == DEBUG_ALL


def test_normalize_log_level_rejects_undocumented_numeric_trace_levels():
    assert normalize_log_level(False) == logging.INFO
    assert normalize_log_level(True) == logging.INFO
    assert normalize_log_level(0) == logging.INFO
    assert normalize_log_level("0") == logging.INFO
    assert normalize_log_level(5) == logging.INFO
    assert normalize_log_level("9") == logging.INFO
    assert normalize_log_level(-5) == logging.INFO
    assert normalize_log_level("-5") == logging.INFO
    assert normalize_log_level("10") == logging.DEBUG
    assert normalize_log_level("+10") == logging.DEBUG
    assert normalize_log_level(60) == logging.CRITICAL


def test_configure_runtime_logging_skips_file_handler_when_stdout_already_targets_runtime_log(tmp_path, monkeypatch):
    log_path = tmp_path / "teebotus-production.log"
    log_path.touch()
    with log_path.open("a", encoding="utf-8") as redirected_stdout:
        monkeypatch.setattr(sys, "stdout", redirected_stdout)

        configure_runtime_logging(base_dir=tmp_path)

        handlers = logging.getLogger().handlers
        assert len(handlers) == 1
        assert not any(isinstance(handler, RuntimeTimedRotatingFileHandler) for handler in handlers)


def test_stdout_targets_path_does_not_follow_runtime_log_symlink(tmp_path, monkeypatch):
    external = tmp_path / "external.log"
    external.touch()
    log_path = tmp_path / "teebotus-production.log"
    log_path.symlink_to(external)

    with external.open("a", encoding="utf-8") as redirected_stdout:
        monkeypatch.setattr(sys, "stdout", redirected_stdout)

        assert _stdout_targets_path(log_path) is False


def test_configure_runtime_logging_uses_file_handler_when_stdout_is_not_runtime_log(tmp_path):
    configure_runtime_logging(base_dir=tmp_path)

    handlers = logging.getLogger().handlers
    assert any(isinstance(handler, RuntimeTimedRotatingFileHandler) for handler in handlers)


def test_configure_runtime_logging_accepts_string_base_dir(tmp_path):
    configure_runtime_logging(base_dir=str(tmp_path))

    handlers = logging.getLogger().handlers
    assert any(isinstance(handler, RuntimeTimedRotatingFileHandler) for handler in handlers)
    assert (tmp_path / "teebotus-production.log").exists()


def test_runtime_log_path_treats_empty_string_as_default_runtime_dir():
    assert runtime_log_path("") == runtime_dir() / "teebotus-production.log"


def test_configure_runtime_logging_continues_when_runtime_directory_is_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    blocked_runtime_dir = tmp_path / "runtime-as-file"
    blocked_runtime_dir.write_text("not a directory\n", encoding="utf-8")

    configure_runtime_logging(base_dir=blocked_runtime_dir, tee_stdio=True)
    logging.getLogger("TeeBotus.test").warning("stream only")
    for handler in logging.getLogger().handlers:
        handler.flush()

    handlers = logging.getLogger().handlers
    assert len(handlers) == 1
    assert not any(isinstance(handler, RuntimeTimedRotatingFileHandler) for handler in handlers)
    assert "stream only" in sys.stdout.getvalue()
    assert blocked_runtime_dir.read_text(encoding="utf-8") == "not a directory\n"


def test_configure_runtime_logging_refuses_symlinked_runtime_log_path(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    external = tmp_path / "external.log"
    external.write_text("", encoding="utf-8")
    log_path = tmp_path / "teebotus-production.log"
    log_path.symlink_to(external)

    configure_runtime_logging(base_dir=tmp_path)
    logging.getLogger("TeeBotus.test").warning("probe")
    for handler in logging.getLogger().handlers:
        handler.flush()

    handlers = logging.getLogger().handlers
    assert not any(isinstance(handler, RuntimeTimedRotatingFileHandler) for handler in handlers)
    assert external.read_text(encoding="utf-8") == ""


def test_configure_runtime_logging_continues_when_file_handler_fdopen_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    real_fdopen = os.fdopen

    def fail_runtime_log_fdopen(fd, mode="r", *args, **kwargs):
        if mode == "a":
            raise ValueError("runtime log fdopen failed")
        return real_fdopen(fd, mode, *args, **kwargs)

    monkeypatch.setattr(os, "fdopen", fail_runtime_log_fdopen)

    configure_runtime_logging(base_dir=tmp_path)
    logging.getLogger("TeeBotus.test").warning("stream only")
    for handler in logging.getLogger().handlers:
        handler.flush()

    handlers = logging.getLogger().handlers
    assert len(handlers) == 1
    assert not any(isinstance(handler, RuntimeTimedRotatingFileHandler) for handler in handlers)
    assert "stream only" in sys.stdout.getvalue()


def test_configure_runtime_logging_refuses_symlinked_runtime_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    external_runtime_dir = tmp_path / "external-runtime"
    external_runtime_dir.mkdir()
    runtime_dir = tmp_path / "runtime-link"
    runtime_dir.symlink_to(external_runtime_dir, target_is_directory=True)

    configure_runtime_logging(base_dir=runtime_dir, tee_stdio=True)
    logging.getLogger("TeeBotus.test").warning("probe")
    for handler in logging.getLogger().handlers:
        handler.flush()

    handlers = logging.getLogger().handlers
    assert not any(isinstance(handler, RuntimeTimedRotatingFileHandler) for handler in handlers)
    assert not (external_runtime_dir / "teebotus-production.log").exists()
    assert not (external_runtime_dir / STDIO_LOG_FILENAME).exists()


def test_configure_runtime_logging_refuses_symlinked_runtime_ancestor(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    external_parent = tmp_path / "external-parent"
    external_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(external_parent, target_is_directory=True)

    configure_runtime_logging(base_dir=linked_parent / "runtime")
    logging.getLogger("TeeBotus.test").warning("probe")
    for handler in logging.getLogger().handlers:
        handler.flush()

    handlers = logging.getLogger().handlers
    assert not any(isinstance(handler, RuntimeTimedRotatingFileHandler) for handler in handlers)
    assert not (external_parent / "runtime").exists()


def test_configure_runtime_logging_refuses_path_when_parent_check_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    blocked_parent = tmp_path / "blocked-parent"
    real_is_symlink = Path.is_symlink

    def fail_parent_check(self):
        if self == blocked_parent:
            raise PermissionError("cannot inspect parent")
        return real_is_symlink(self)

    monkeypatch.setattr(Path, "is_symlink", fail_parent_check)

    configure_runtime_logging(base_dir=blocked_parent / "runtime")
    logging.getLogger("TeeBotus.test").warning("probe")
    for handler in logging.getLogger().handlers:
        handler.flush()

    handlers = logging.getLogger().handlers
    assert not any(isinstance(handler, RuntimeTimedRotatingFileHandler) for handler in handlers)
    assert not blocked_parent.exists()


def test_runtime_file_handler_rollover_preserves_existing_rotated_log(tmp_path):
    log_path = tmp_path / "teebotus-production.log"
    handler = RuntimeTimedRotatingFileHandler(log_path)
    try:
        date_suffix = time.strftime(handler.suffix, time.localtime(handler.rolloverAt - handler.interval))
        existing_rotated = log_path.with_name(f"{log_path.name}.{date_suffix}")
        existing_rotated.write_text("existing rotated\n", encoding="utf-8")
        handler.stream.write("current log\n")
        handler.stream.flush()

        handler.doRollover()

        numbered_rotated = existing_rotated.with_name(f"{existing_rotated.name}.1")
        assert existing_rotated.read_text(encoding="utf-8") == "existing rotated\n"
        assert numbered_rotated.read_text(encoding="utf-8") == "current log\n"
    finally:
        handler.close()


def test_runtime_file_handler_rollover_preserves_rotated_log_created_during_rotate(tmp_path, monkeypatch):
    log_path = tmp_path / "teebotus-production.log"
    handler = RuntimeTimedRotatingFileHandler(log_path)
    try:
        date_suffix = time.strftime(handler.suffix, time.localtime(handler.rolloverAt - handler.interval))
        raced_rotated = log_path.with_name(f"{log_path.name}.{date_suffix}")
        real_link = os.link
        raced = False

        def racing_link(source, destination, *args, **kwargs):
            nonlocal raced
            destination_path = Path(destination)
            if destination_path == raced_rotated and not raced:
                raced = True
                raced_rotated.write_text("raced rotated\n", encoding="utf-8")
                raise FileExistsError(destination)
            return real_link(source, destination, *args, **kwargs)

        monkeypatch.setattr(os, "link", racing_link)
        handler.stream.write("current log\n")
        handler.stream.flush()

        handler.doRollover()

        numbered_rotated = raced_rotated.with_name(f"{raced_rotated.name}.1")
        assert raced is True
        assert raced_rotated.read_text(encoding="utf-8") == "raced rotated\n"
        assert numbered_rotated.read_text(encoding="utf-8") == "current log\n"
    finally:
        handler.close()


def test_configure_runtime_logging_caps_provider_sdk_logs_during_debug_all(tmp_path):
    for logger_name in ("litellm", "LiteLLM", "openai", "openai._base_client"):
        logging.getLogger(logger_name).setLevel(logging.NOTSET)

    configure_runtime_logging(level="debug_all", base_dir=tmp_path)

    assert logging.getLogger().level == 1
    assert logging.getLogger("litellm").level == logging.INFO
    assert logging.getLogger("LiteLLM").level == logging.INFO
    assert logging.getLogger("openai").level == logging.INFO
    assert logging.getLogger("openai._base_client").level == logging.WARNING


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


def test_configure_runtime_logging_disables_existing_stdio_tee(tmp_path, monkeypatch):
    primary_stdout = io.StringIO()
    primary_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", primary_stdout)
    monkeypatch.setattr(sys, "stderr", primary_stderr)
    stdio_log = tmp_path / STDIO_LOG_FILENAME

    install_stdio_tee(stdio_log)
    assert isinstance(sys.stdout, TeeStream)
    assert isinstance(sys.stderr, TeeStream)
    old_stdout = sys.stdout
    old_stderr = sys.stderr

    configure_runtime_logging(base_dir=tmp_path, tee_stdio=False)
    print("stdout after disable")
    print("stderr after disable", file=sys.stderr)
    sys.stdout.flush()
    sys.stderr.flush()

    assert sys.stdout is primary_stdout
    assert sys.stderr is primary_stderr
    assert old_stdout.secondary.closed
    assert old_stderr.secondary.closed
    assert "stdout after disable" in primary_stdout.getvalue()
    assert "stderr after disable" in primary_stderr.getvalue()
    assert "stdout after disable" not in stdio_log.read_text(encoding="utf-8")


def test_configure_runtime_logging_removes_stale_stdio_tee_when_reinstall_fails(tmp_path, monkeypatch):
    primary_stdout = io.StringIO()
    primary_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", primary_stdout)
    monkeypatch.setattr(sys, "stderr", primary_stderr)
    old_stdio_log = tmp_path / "old" / STDIO_LOG_FILENAME
    new_runtime = tmp_path / "new"
    new_stdio_log = new_runtime / STDIO_LOG_FILENAME
    install_stdio_tee(old_stdio_log)
    assert isinstance(sys.stdout, TeeStream)
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    real_open = os.open

    def fail_new_stdio_open(file, flags, *args, **kwargs):
        if Path(file) == new_stdio_log:
            raise PermissionError(errno.EACCES, "permission denied", str(file))
        return real_open(file, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", fail_new_stdio_open)

    configure_runtime_logging(base_dir=new_runtime, tee_stdio=True)
    print("stdout after failed reinstall")
    print("stderr after failed reinstall", file=sys.stderr)
    sys.stdout.flush()
    sys.stderr.flush()

    assert sys.stdout is primary_stdout
    assert sys.stderr is primary_stderr
    assert old_stdout.secondary.closed
    assert old_stderr.secondary.closed
    assert "stdout after failed reinstall" in primary_stdout.getvalue()
    assert "stderr after failed reinstall" in primary_stderr.getvalue()
    assert "stdout after failed reinstall" not in old_stdio_log.read_text(encoding="utf-8")
    assert not new_stdio_log.exists()


def test_install_stdio_tee_repairs_half_installed_state_without_double_stdout_writes(tmp_path, monkeypatch):
    primary_stdout = io.StringIO()
    primary_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", primary_stdout)
    monkeypatch.setattr(sys, "stderr", primary_stderr)
    path = tmp_path / STDIO_LOG_FILENAME

    install_stdio_tee(path)
    monkeypatch.setattr(sys, "stderr", primary_stderr)
    install_stdio_tee(path)
    print("stdout once")
    print("stderr once", file=sys.stderr)
    sys.stdout.flush()
    sys.stderr.flush()

    assert path.read_text(encoding="utf-8").splitlines().count("stdout once") == 1
    assert path.read_text(encoding="utf-8").splitlines().count("stderr once") == 1


def test_install_stdio_tee_accepts_string_path(tmp_path, monkeypatch):
    primary_stdout = io.StringIO()
    primary_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", primary_stdout)
    monkeypatch.setattr(sys, "stderr", primary_stderr)
    path = tmp_path / STDIO_LOG_FILENAME

    install_stdio_tee(str(path))
    print("stdout string path")
    sys.stdout.flush()
    sys.stderr.flush()

    assert "stdout string path" in path.read_text(encoding="utf-8")


def test_install_stdio_tee_repairs_closed_existing_target(tmp_path, monkeypatch):
    primary_stdout = io.StringIO()
    primary_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", primary_stdout)
    monkeypatch.setattr(sys, "stderr", primary_stderr)
    path = tmp_path / STDIO_LOG_FILENAME

    install_stdio_tee(path)
    assert isinstance(sys.stdout, TeeStream)
    sys.stdout.secondary.close()
    install_stdio_tee(path)
    print("stdout after repair")
    print("stderr after repair", file=sys.stderr)
    sys.stdout.flush()
    sys.stderr.flush()

    log_text = path.read_text(encoding="utf-8")
    assert "stdout after repair" in log_text
    assert "stderr after repair" in log_text


def test_install_stdio_tee_skips_when_target_directory_cannot_be_created(tmp_path, monkeypatch):
    primary_stdout = io.StringIO()
    primary_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", primary_stdout)
    monkeypatch.setattr(sys, "stderr", primary_stderr)
    path = tmp_path / "blocked" / STDIO_LOG_FILENAME
    real_mkdir = Path.mkdir

    def fail_target_mkdir(self, *args, **kwargs):
        if self == path.parent:
            raise PermissionError("blocked target directory")
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_target_mkdir)

    install_stdio_tee(path)
    print("stdout only")
    sys.stdout.flush()
    sys.stderr.flush()

    assert not isinstance(sys.stdout, TeeStream)
    assert not isinstance(sys.stderr, TeeStream)
    assert not path.parent.exists()


def test_install_stdio_tee_skips_when_target_directory_disappears_after_mkdir(tmp_path, monkeypatch):
    primary_stdout = io.StringIO()
    primary_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", primary_stdout)
    monkeypatch.setattr(sys, "stderr", primary_stderr)
    path = tmp_path / "runtime" / STDIO_LOG_FILENAME
    real_open = os.open

    def removing_open(file, flags, *args, **kwargs):
        if Path(file) == path and path.parent.exists():
            path.parent.rmdir()
        return real_open(file, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", removing_open)

    install_stdio_tee(path)
    print("stdout only")
    sys.stdout.flush()
    sys.stderr.flush()

    assert not isinstance(sys.stdout, TeeStream)
    assert not isinstance(sys.stderr, TeeStream)
    assert not path.parent.exists()


def test_install_stdio_tee_skips_when_target_open_is_denied(tmp_path, monkeypatch):
    primary_stdout = io.StringIO()
    primary_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", primary_stdout)
    monkeypatch.setattr(sys, "stderr", primary_stderr)
    path = tmp_path / "runtime" / STDIO_LOG_FILENAME
    real_open = os.open

    def denied_open(file, flags, *args, **kwargs):
        if Path(file) == path:
            raise PermissionError(errno.EACCES, "permission denied", str(file))
        return real_open(file, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", denied_open)

    install_stdio_tee(path)
    print("stdout only")
    sys.stdout.flush()
    sys.stderr.flush()

    assert not isinstance(sys.stdout, TeeStream)
    assert not isinstance(sys.stderr, TeeStream)
    assert not path.exists()


def test_install_stdio_tee_skips_when_target_fdopen_fails(tmp_path, monkeypatch):
    primary_stdout = io.StringIO()
    primary_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", primary_stdout)
    monkeypatch.setattr(sys, "stderr", primary_stderr)
    path = tmp_path / "runtime" / STDIO_LOG_FILENAME
    real_fdopen = os.fdopen

    def fail_stdio_fdopen(fd, mode="r", *args, **kwargs):
        if mode == "a":
            raise OSError("stdio fdopen failed")
        return real_fdopen(fd, mode, *args, **kwargs)

    monkeypatch.setattr(os, "fdopen", fail_stdio_fdopen)

    install_stdio_tee(path)
    print("stdout only")
    sys.stdout.flush()
    sys.stderr.flush()

    assert not isinstance(sys.stdout, TeeStream)
    assert not isinstance(sys.stderr, TeeStream)


def test_install_stdio_tee_refuses_symlinked_target_parent_before_mkdir(tmp_path, monkeypatch):
    primary_stdout = io.StringIO()
    primary_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", primary_stdout)
    monkeypatch.setattr(sys, "stderr", primary_stderr)
    external_parent = tmp_path / "external-parent"
    external_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(external_parent, target_is_directory=True)
    path = linked_parent / "runtime" / STDIO_LOG_FILENAME

    install_stdio_tee(path)
    print("stdout only")
    sys.stdout.flush()
    sys.stderr.flush()

    assert not isinstance(sys.stdout, TeeStream)
    assert not isinstance(sys.stderr, TeeStream)
    assert not (external_parent / "runtime").exists()


def test_install_stdio_tee_refuses_symlinked_parent_hidden_by_dotdot(tmp_path, monkeypatch):
    primary_stdout = io.StringIO()
    primary_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", primary_stdout)
    monkeypatch.setattr(sys, "stderr", primary_stderr)
    external_parent = tmp_path / "external-parent"
    nested_target = external_parent / "nested"
    nested_target.mkdir(parents=True)
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(nested_target, target_is_directory=True)
    path = linked_parent / ".." / "runtime" / STDIO_LOG_FILENAME

    install_stdio_tee(path)
    print("stdout only")
    sys.stdout.flush()
    sys.stderr.flush()

    assert not isinstance(sys.stdout, TeeStream)
    assert not isinstance(sys.stderr, TeeStream)
    assert not (external_parent / "runtime").exists()
    assert not (tmp_path / "runtime").exists()


def test_install_stdio_tee_retargets_existing_tee_without_writing_old_target(tmp_path, monkeypatch):
    primary_stdout = io.StringIO()
    primary_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", primary_stdout)
    monkeypatch.setattr(sys, "stderr", primary_stderr)
    old_path = tmp_path / "old-stdio.log"
    new_path = tmp_path / "new-stdio.log"

    install_stdio_tee(old_path)
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    install_stdio_tee(new_path)
    print("new target only")
    sys.stdout.flush()
    sys.stderr.flush()

    assert old_path.read_text(encoding="utf-8") == ""
    assert "new target only" in new_path.read_text(encoding="utf-8")
    assert isinstance(old_stdout, TeeStream)
    assert isinstance(old_stderr, TeeStream)
    assert old_stdout.secondary.closed
    assert old_stderr.secondary.closed


def test_install_stdio_tee_refuses_symlinked_target(tmp_path, monkeypatch):
    primary_stdout = io.StringIO()
    primary_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", primary_stdout)
    monkeypatch.setattr(sys, "stderr", primary_stderr)
    external = tmp_path / "external.log"
    external.write_text("", encoding="utf-8")
    path = tmp_path / STDIO_LOG_FILENAME
    path.symlink_to(external)

    install_stdio_tee(path)
    print("do not tee")
    sys.stdout.flush()
    sys.stderr.flush()

    assert not isinstance(sys.stdout, TeeStream)
    assert not isinstance(sys.stderr, TeeStream)
    assert external.read_text(encoding="utf-8") == ""


def test_install_stdio_tee_refuses_fifo_target_without_blocking(tmp_path, monkeypatch):
    if not hasattr(os, "mkfifo"):
        pytest.skip("mkfifo is not available on this platform")
    primary_stdout = io.StringIO()
    primary_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", primary_stdout)
    monkeypatch.setattr(sys, "stderr", primary_stderr)
    path = tmp_path / STDIO_LOG_FILENAME
    os.mkfifo(path)

    install_stdio_tee(path)
    print("do not tee to fifo")
    sys.stdout.flush()
    sys.stderr.flush()

    assert not isinstance(sys.stdout, TeeStream)
    assert not isinstance(sys.stderr, TeeStream)


def test_tee_stream_keeps_primary_stream_working_when_secondary_fails():
    class FailingSecondary(io.StringIO):
        def write(self, _text):
            raise OSError("secondary write failed")

        def flush(self):
            raise OSError("secondary flush failed")

    primary = io.StringIO()
    tee = TeeStream(primary, FailingSecondary(), Path("secondary.log"))

    assert tee.write("probe") == 5
    tee.flush()

    assert primary.getvalue() == "probe"


def test_tee_stream_keeps_primary_stream_working_when_secondary_is_closed():
    primary = io.StringIO()
    secondary = io.StringIO()
    secondary.close()
    tee = TeeStream(primary, secondary, Path("secondary.log"))

    assert tee.write("probe") == 5
    tee.flush()

    assert primary.getvalue() == "probe"
