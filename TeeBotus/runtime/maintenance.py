from __future__ import annotations

import errno
import gzip
import logging
import os
import shutil
import sys
import tarfile
import time
import stat as stat_module
from contextlib import ExitStack
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from TeeBotus.runtime.log_context import format_log_context

RUNTIME_DIR = Path("data/runtime")
PRODUCTION_LOG_FILENAME = "teebotus-production.log"
STDIO_LOG_FILENAME = "teebotus-stdio.log"
ACTIVE_RUNTIME_TEXT_FILENAMES = frozenset({PRODUCTION_LOG_FILENAME, STDIO_LOG_FILENAME})
MAX_RUNTIME_TEXT_FILE_BYTES = 2 * 1024 * 1024
COMPRESS_AFTER_SECONDS = 7 * 24 * 60 * 60
MONTHLY_ARCHIVE_AFTER_SECONDS = 60 * 24 * 60 * 60
DEBUG_ALL = 1
LOG_LEVEL_ALIASES = {
    "critical": logging.CRITICAL,
    "crit": logging.CRITICAL,
    "error": logging.ERROR,
    "err": logging.ERROR,
    "warning": logging.WARNING,
    "warn": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
    "debug_all": DEBUG_ALL,
    "debug-all": DEBUG_ALL,
    "debug all": DEBUG_ALL,
    "all": DEBUG_ALL,
    "finest": DEBUG_ALL,
}
THIRD_PARTY_LOG_LEVELS = {
    "httpx": logging.INFO,
    "httpcore": logging.WARNING,
    "urllib3": logging.INFO,
    "LiteLLM": logging.INFO,
    "litellm": logging.INFO,
    "openai": logging.INFO,
    "openai._base_client": logging.WARNING,
    "asyncio": logging.WARNING,
    "apscheduler": logging.INFO,
    "tzlocal": logging.WARNING,
    "websockets": logging.WARNING,
    "websockets.client": logging.WARNING,
}

logging.addLevelName(DEBUG_ALL, "DEBUG_ALL")


def runtime_dir() -> Path:
    return RUNTIME_DIR


def runtime_log_path(base_dir: Path | str | None = None) -> Path:
    return _runtime_base_dir(base_dir) / PRODUCTION_LOG_FILENAME


def configure_runtime_logging(*, level: str | int = "INFO", base_dir: Path | str | None = None, tee_stdio: bool = False) -> None:
    resolved_level = normalize_log_level(level)
    directory = _runtime_base_dir(base_dir)
    runtime_directory_ready = not _has_symlink_parent(directory)
    if runtime_directory_ready:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            directory_stat = directory.stat(follow_symlinks=False)
            runtime_directory_ready = stat_module.S_ISDIR(directory_stat.st_mode)
            if runtime_directory_ready:
                maintain_runtime_directory(directory)
        except OSError:
            runtime_directory_ready = False
    log_path = runtime_log_path(directory)
    stdout_targets_log = _stdout_targets_path(log_path) if runtime_directory_ready else False
    if tee_stdio and runtime_directory_ready:
        install_stdio_tee(directory / STDIO_LOG_FILENAME)

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s%(teebotus_context)s")
    context_filter = TeeBotusLogContextFilter()
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(context_filter)
    handlers: list[logging.Handler] = [stream_handler]
    if runtime_directory_ready and not stdout_targets_log:
        try:
            file_handler = RuntimeTimedRotatingFileHandler(log_path)
        except (OSError, ValueError):
            file_handler = None
        if file_handler is not None:
            file_handler.setFormatter(formatter)
            file_handler.addFilter(context_filter)
            handlers.append(file_handler)
    logging.basicConfig(level=resolved_level, handlers=handlers, force=True)
    _configure_third_party_loggers(resolved_level)
    logging.getLogger("TeeBotus.runtime.maintenance").info(
        "Runtime logging configured level=%s numeric_level=%s available_levels=critical,error,warning,info,debug,debug_all,finest",
        logging.getLevelName(resolved_level),
        resolved_level,
    )


def _runtime_base_dir(base_dir: Path | str | None = None) -> Path:
    if base_dir is None or base_dir == "":
        return runtime_dir()
    return Path(base_dir)


def normalize_log_level(level: str | int) -> int:
    if isinstance(level, bool):
        return logging.INFO
    if isinstance(level, int):
        return _normalize_numeric_log_level(level)
    text = str(level or "INFO").strip()
    if not text:
        return logging.INFO
    numeric_text = text[1:] if text[:1] in {"+", "-"} else text
    if numeric_text.isdigit():
        return _normalize_numeric_log_level(int(text))
    normalized = text.casefold().replace("_", " ").replace("-", " ")
    return LOG_LEVEL_ALIASES.get(normalized, LOG_LEVEL_ALIASES.get(text.casefold(), logging.INFO))


def _normalize_numeric_log_level(level: int) -> int:
    if level == DEBUG_ALL:
        return DEBUG_ALL
    if level < logging.DEBUG:
        return logging.INFO
    return min(logging.CRITICAL, level)


class TeeBotusLogContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context = format_log_context()
        record.teebotus_context = f" context={context}" if context else ""
        return True


def _configure_third_party_loggers(level: int) -> None:
    for logger_name, logger_level in THIRD_PARTY_LOG_LEVELS.items():
        logging.getLogger(logger_name).setLevel(logger_level)


def install_stdio_tee(path: Path) -> None:
    if _has_symlink_parent(path):
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    target_path = _absolute_without_symlink_resolution(path)
    if _stream_tee_target(sys.stdout) == target_path and _stream_tee_target(sys.stderr) == target_path:
        return
    try:
        handle = _open_append_text_no_follow(target_path)
    except (OSError, ValueError):
        return
    if handle is None:
        return
    sys.stdout = _install_stream_tee(sys.stdout, handle, target_path)  # type: ignore[assignment]
    sys.stderr = _install_stream_tee(sys.stderr, handle, target_path)  # type: ignore[assignment]


class TeeStream:
    def __init__(self, primary: object, secondary: object, target: Path) -> None:
        self.primary = primary
        self.secondary = secondary
        self._teebotus_tee_target = target
        self.encoding = getattr(primary, "encoding", "utf-8")
        self.errors = getattr(primary, "errors", "strict")

    def write(self, text: str) -> int:
        primary_write = getattr(self.primary, "write")
        secondary_write = getattr(self.secondary, "write")
        primary_write(text)
        try:
            secondary_write(text)
        except (OSError, ValueError):
            pass
        return len(text)

    def flush(self) -> None:
        primary_flush = getattr(self.primary, "flush", None)
        if callable(primary_flush):
            primary_flush()
        secondary_flush = getattr(self.secondary, "flush", None)
        if callable(secondary_flush):
            try:
                secondary_flush()
            except (OSError, ValueError):
                pass

    def fileno(self) -> int:
        fileno = getattr(self.primary, "fileno")
        return int(fileno())

    def isatty(self) -> bool:
        isatty = getattr(self.primary, "isatty", None)
        return bool(isatty()) if callable(isatty) else False

    def writable(self) -> bool:
        return True


def _stream_tee_target(stream: object) -> Path | None:
    if isinstance(stream, TeeStream) and getattr(stream.secondary, "closed", False):
        return None
    target = getattr(stream, "_teebotus_tee_target", None)
    if isinstance(target, Path):
        return _absolute_without_symlink_resolution(target)
    return None


def _install_stream_tee(stream: object, secondary: object, target: Path) -> object:
    if _stream_tee_target(stream) == target:
        return stream
    if isinstance(stream, TeeStream):
        _close_quietly(stream.secondary)
        stream = stream.primary
    return TeeStream(stream, secondary, target)


def _open_append_text_no_follow(path: Path) -> object | None:
    if _has_symlink_parent(path):
        return None
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        if exc.errno in {
            errno.EACCES,
            errno.EISDIR,
            errno.ELOOP,
            errno.ENODEV,
            errno.ENOENT,
            errno.ENOTDIR,
            errno.ENXIO,
            errno.EPERM,
            errno.EROFS,
        }:
            return None
        raise
    try:
        stat = os.fstat(fd)
        if not stat_module.S_ISREG(stat.st_mode):
            _close_fd_quietly(fd)
            return None
        return os.fdopen(fd, "a", encoding="utf-8", buffering=1)
    except Exception:
        _close_fd_quietly(fd)
        raise


def _absolute_without_symlink_resolution(path: Path) -> Path:
    if path.is_absolute():
        return path
    return Path.cwd() / path


def _has_symlink_parent(path: Path) -> bool:
    absolute = _absolute_without_symlink_resolution(path)
    for parent in absolute.parents:
        try:
            if parent.is_symlink():
                return True
        except OSError:
            return True
    return False


class RuntimeTimedRotatingFileHandler(TimedRotatingFileHandler):
    def __init__(self, filename: Path) -> None:
        super().__init__(filename, when="midnight", interval=1, backupCount=0, encoding="utf-8", delay=True)
        self.suffix = "%Y-%m-%d"
        self.stream = self._open()

    def _open(self):  # type: ignore[override]
        stream = _open_append_text_no_follow(Path(self.baseFilename))
        if stream is None:
            raise OSError(f"refusing unsafe runtime log path: {self.baseFilename}")
        return stream

    def rotation_filename(self, default_name: str) -> str:
        return str(_unique_path(Path(default_name)))

    def rotate(self, source: str, dest: str) -> None:
        source_path = Path(source)
        try:
            source_stat = os.stat(source_path, follow_symlinks=False)
        except OSError:
            return
        if not stat_module.S_ISREG(source_stat.st_mode):
            return
        rotated = _link_file_to_unique_path(source_path, Path(dest), expected_stat=source_stat)
        if rotated is not None:
            _unlink_if_same_file(source_path, source_stat)

    def doRollover(self) -> None:  # noqa: N802 - stdlib override name
        super().doRollover()
        maintain_runtime_directory(Path(self.baseFilename).parent)


def _stdout_targets_path(path: Path) -> bool:
    try:
        stdout_stat = os.fstat(sys.stdout.fileno())
        path_stat = os.stat(path, follow_symlinks=False)
    except (AttributeError, FileNotFoundError, OSError, ValueError):
        return False
    if not stat_module.S_ISREG(path_stat.st_mode):
        return False
    return stdout_stat.st_dev == path_stat.st_dev and stdout_stat.st_ino == path_stat.st_ino


def rotate_runtime_text_file_if_needed(path: Path, *, max_bytes: int = MAX_RUNTIME_TEXT_FILE_BYTES) -> Path | None:
    if path.name in ACTIVE_RUNTIME_TEXT_FILENAMES:
        return None
    if _is_compressed_runtime_file(path) or _is_temporary_runtime_file(path):
        return None
    if path.is_symlink() or not path.is_file():
        return None
    try:
        source_stat = os.stat(path, follow_symlinks=False)
    except OSError:
        return None
    if not stat_module.S_ISREG(source_stat.st_mode) or source_stat.st_size <= max_bytes:
        return None
    rotated = _link_file_to_unique_path(path, _next_rotated_path(path), expected_stat=source_stat)
    if rotated is None:
        return None
    _unlink_if_same_file(path, source_stat)
    try:
        return gzip_file(rotated, expected_stat=source_stat)
    except (OSError, ValueError):
        return rotated


def maintain_runtime_directory(
    runtime_path: Path,
    *,
    now: float | None = None,
    max_bytes: int = MAX_RUNTIME_TEXT_FILE_BYTES,
    compress_after_seconds: int = COMPRESS_AFTER_SECONDS,
    monthly_archive_after_seconds: int = MONTHLY_ARCHIVE_AFTER_SECONDS,
) -> None:
    if _has_symlink_parent(runtime_path):
        return
    try:
        runtime_path.mkdir(parents=True, exist_ok=True)
        runtime_stat = runtime_path.stat(follow_symlinks=False)
    except OSError:
        return
    if not stat_module.S_ISDIR(runtime_stat.st_mode):
        return
    resolved_now = time.time() if now is None else now
    for path in list(_runtime_text_files(runtime_path)):
        try:
            file_stat = path.stat(follow_symlinks=False)
            if not stat_module.S_ISREG(file_stat.st_mode):
                continue
            age = max(0.0, resolved_now - file_stat.st_mtime)
            if file_stat.st_size > max_bytes or age >= compress_after_seconds:
                gzip_file(path, expected_stat=file_stat)
        except (OSError, ValueError):
            continue
    _archive_old_compressed_files(runtime_path, now=resolved_now, archive_after_seconds=monthly_archive_after_seconds)


def gzip_file(path: Path, *, expected_stat: os.stat_result | None = None) -> Path:
    if path.is_symlink() or _is_compressed_runtime_file(path) or _is_temporary_runtime_file(path) or not path.is_file():
        return path
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return path
    except OSError as exc:
        if exc.errno in {errno.EISDIR, errno.ELOOP, errno.ENOTDIR}:
            return path
        raise
    try:
        source_stat = os.fstat(fd)
    except OSError:
        _close_fd_quietly(fd)
        raise
    if not stat_module.S_ISREG(source_stat.st_mode):
        _close_fd_quietly(fd)
        return path
    if expected_stat is not None and not _same_file_stat(source_stat, expected_stat):
        _close_fd_quietly(fd)
        return path
    target = _unique_path(path.with_name(f"{path.name}.gz"))
    source_fd: int | None = fd
    temporary: Path | None = None
    temporary_fd: int | None = None
    temporary_stat: os.stat_result | None = None
    try:
        temporary, temporary_fd, temporary_stat = _create_unique_file(path.with_name(f".{target.name}.tmp"))
        with ExitStack() as stack:
            source = stack.enter_context(os.fdopen(source_fd, "rb"))
            source_fd = None
            raw_sink = stack.enter_context(os.fdopen(temporary_fd, "wb"))
            temporary_fd = None
            with gzip.GzipFile(fileobj=raw_sink, mode="wb") as sink:
                shutil.copyfileobj(source, sink)
        os.utime(temporary, (source_stat.st_atime, source_stat.st_mtime), follow_symlinks=False)
        published = _publish_temporary_file(temporary, target, expected_stat=temporary_stat)
    except Exception:
        if source_fd is not None:
            _close_fd_quietly(source_fd)
        if temporary_fd is not None:
            _close_fd_quietly(temporary_fd)
        if temporary is not None and temporary_stat is not None:
            _unlink_if_same_file(temporary, temporary_stat)
        raise
    _unlink_if_same_file(path, source_stat)
    return published


def _runtime_text_files(runtime_path: Path) -> list[Path]:
    archive_dir = runtime_path / "monthly_archives"
    result: list[Path] = []
    for pattern in ("*.log", "*.log.*", "*.jsonl", "*.jsonl.*"):
        try:
            candidates = list(runtime_path.glob(pattern))
        except OSError:
            continue
        for path in candidates:
            if _is_compressed_runtime_file(path) or _is_temporary_runtime_file(path):
                continue
            try:
                path_stat = path.stat(follow_symlinks=False)
            except OSError:
                continue
            if not stat_module.S_ISREG(path_stat.st_mode):
                continue
            if path.name in ACTIVE_RUNTIME_TEXT_FILENAMES:
                continue
            if archive_dir in path.parents:
                continue
            result.append(path)
    return sorted(set(result))


def _archive_old_compressed_files(runtime_path: Path, *, now: float, archive_after_seconds: int) -> None:
    archive_dir = runtime_path / "monthly_archives"
    groups: dict[str, list[tuple[Path, os.stat_result]]] = {}
    try:
        candidates = list(runtime_path.iterdir())
    except OSError:
        return
    for path in candidates:
        if not _is_compressed_runtime_file(path):
            continue
        if _is_temporary_runtime_file(path):
            continue
        try:
            stat = path.stat(follow_symlinks=False)
        except OSError:
            continue
        if not stat_module.S_ISREG(stat.st_mode):
            continue
        age = now - stat.st_mtime
        if age < archive_after_seconds:
            continue
        month = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m")
        groups.setdefault(month, []).append((path, stat))

    for month, paths in groups.items():
        try:
            archive_dir.mkdir(parents=True, exist_ok=True)
            archive_dir_stat = archive_dir.stat(follow_symlinks=False)
        except OSError:
            continue
        if not stat_module.S_ISDIR(archive_dir_stat.st_mode):
            continue
        archive_path = _unique_path(archive_dir / f"teebotus-runtime-{month}.tar.gz")
        temporary: Path | None = None
        temporary_fd: int | None = None
        temporary_stat: os.stat_result | None = None
        added_paths: list[tuple[Path, os.stat_result]] = []
        try:
            temporary, temporary_fd, temporary_stat = _create_unique_file(archive_dir / f".{archive_path.name}.tmp")
            with os.fdopen(temporary_fd, "wb") as raw_archive:
                temporary_fd = None
                with tarfile.open(fileobj=raw_archive, mode="w:gz") as archive:
                    for path, selected_stat in paths:
                        archived_stat = _add_regular_file_to_archive(archive, path, expected_stat=selected_stat)
                        if archived_stat is None:
                            continue
                        added_paths.append((path, archived_stat))
            if not added_paths:
                _unlink_if_same_file(temporary, temporary_stat)
                continue
            _publish_temporary_file(temporary, archive_path, expected_stat=temporary_stat)
        except (OSError, ValueError, tarfile.TarError):
            if temporary_fd is not None:
                _close_fd_quietly(temporary_fd)
            if temporary is not None and temporary_stat is not None:
                _unlink_if_same_file(temporary, temporary_stat)
            continue
        for path, archived_stat in added_paths:
            _unlink_if_same_file(path, archived_stat)


def _add_regular_file_to_archive(
    archive: tarfile.TarFile,
    path: Path,
    *,
    expected_stat: os.stat_result | None = None,
) -> os.stat_result | None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return None
    try:
        archived_stat = os.fstat(fd)
    except (OSError, ValueError):
        _close_fd_quietly(fd)
        return None
    if not stat_module.S_ISREG(archived_stat.st_mode):
        _close_fd_quietly(fd)
        return None
    if expected_stat is not None and not _same_file_stat(archived_stat, expected_stat):
        _close_fd_quietly(fd)
        return None
    try:
        source_handle = os.fdopen(fd, "rb")
    except (OSError, ValueError):
        _close_fd_quietly(fd)
        return None
    with source_handle as source:
        try:
            tarinfo = archive.gettarinfo(arcname=path.name, fileobj=source)
        except OSError:
            return None
        if tarinfo is None or not tarinfo.isreg():
            return None
        archive.addfile(tarinfo, source)
    return archived_stat


def _unlink_if_same_file(path: Path, expected_stat: os.stat_result) -> None:
    try:
        current_stat = os.stat(path, follow_symlinks=False)
    except OSError:
        return
    if not _same_file_stat(current_stat, expected_stat):
        return
    _unlink_quietly(path)


def _same_file_stat(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _link_file_to_unique_path(source: Path, target: Path, *, expected_stat: os.stat_result) -> Path | None:
    linked = target
    while True:
        try:
            os.link(source, linked, follow_symlinks=False)
        except FileExistsError:
            linked = _unique_path(target)
            continue
        except OSError:
            return None
        try:
            linked_stat = os.stat(linked, follow_symlinks=False)
        except OSError:
            return None
        if _same_file_stat(linked_stat, expected_stat):
            return linked
        try:
            current_source_stat = os.stat(source, follow_symlinks=False)
        except OSError:
            current_source_stat = None
        if current_source_stat is not None and _same_file_stat(linked_stat, current_source_stat):
            _unlink_if_same_file(linked, linked_stat)
        return None


def _create_unique_file(path: Path) -> tuple[Path, int, os.stat_result]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    candidate = _unique_path(path)
    while True:
        try:
            fd = os.open(candidate, flags, 0o600)
        except FileExistsError:
            candidate = _unique_path(path)
            continue
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                candidate = _unique_path(path)
                continue
            raise
        try:
            return candidate, fd, os.fstat(fd)
        except (OSError, ValueError):
            _close_fd_quietly(fd)
            raise


def _next_rotated_path(path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    return _unique_path(path.with_name(f"{path.name}.{timestamp}"))


def _publish_temporary_file(temporary: Path, target: Path, *, expected_stat: os.stat_result) -> Path:
    published = target
    while True:
        try:
            os.link(temporary, published, follow_symlinks=False)
        except FileExistsError:
            published = _unique_path(target)
            continue
        linked_stat = os.stat(published, follow_symlinks=False)
        if not _same_file_stat(linked_stat, expected_stat):
            try:
                current_temp_stat = os.stat(temporary, follow_symlinks=False)
            except OSError:
                current_temp_stat = None
            if current_temp_stat is not None and _same_file_stat(linked_stat, current_temp_stat):
                _unlink_if_same_file(published, linked_stat)
            raise OSError(f"runtime temporary file changed before publish: {temporary}")
        _unlink_if_same_file(temporary, expected_stat)
        return published


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _close_fd_quietly(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass


def _close_quietly(stream: object) -> None:
    close = getattr(stream, "close", None)
    if callable(close):
        try:
            close()
        except (OSError, ValueError):
            pass


def _is_temporary_runtime_file(path: Path) -> bool:
    return path.name.startswith(".") or ".tmp" in path.suffixes


def _is_compressed_runtime_file(path: Path) -> bool:
    return ".gz" in path.suffixes


def _unique_path(path: Path) -> Path:
    if not _path_exists_or_symlink(path):
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.name}.{index}")
        if not _path_exists_or_symlink(candidate):
            return candidate
    raise OSError(f"could not find free runtime archive path for {path}")


def _path_exists_or_symlink(path: Path) -> bool:
    return os.path.lexists(path)
