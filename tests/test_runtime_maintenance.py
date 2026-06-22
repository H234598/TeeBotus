from __future__ import annotations

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
    configure_runtime_logging,
    gzip_file,
    install_stdio_tee,
    maintain_runtime_directory,
    normalize_log_level,
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


def test_rotate_runtime_text_file_preserves_active_runtime_log_names(tmp_path):
    for filename in ACTIVE_RUNTIME_TEXT_FILENAMES:
        path = tmp_path / filename
        path.write_text("0123456789\n", encoding="utf-8")

        assert rotate_runtime_text_file_if_needed(path, max_bytes=4) is None
        assert path.read_text(encoding="utf-8") == "0123456789\n"
        assert not list(tmp_path.glob(f"{filename}.*.gz"))


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


def test_gzip_file_preserves_symlinked_runtime_file(tmp_path):
    target = tmp_path / "external-target.txt"
    target.write_text("do not copy\n", encoding="utf-8")
    symlink = tmp_path / "linked-runtime.log"
    symlink.symlink_to(target)

    assert gzip_file(symlink) == symlink

    assert symlink.is_symlink()
    assert target.read_text(encoding="utf-8") == "do not copy\n"
    assert not (tmp_path / f"{symlink.name}.gz").exists()


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
    assert normalize_log_level(0) == logging.INFO
    assert normalize_log_level("0") == logging.INFO
    assert normalize_log_level(5) == logging.INFO
    assert normalize_log_level("9") == logging.INFO
    assert normalize_log_level(-5) == logging.INFO
    assert normalize_log_level("10") == logging.DEBUG
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


def test_configure_runtime_logging_uses_file_handler_when_stdout_is_not_runtime_log(tmp_path):
    configure_runtime_logging(base_dir=tmp_path)

    handlers = logging.getLogger().handlers
    assert any(isinstance(handler, RuntimeTimedRotatingFileHandler) for handler in handlers)


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
