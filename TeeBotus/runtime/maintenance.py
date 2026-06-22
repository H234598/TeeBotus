from __future__ import annotations

import gzip
import logging
import os
import shutil
import sys
import tarfile
import time
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


def runtime_log_path(base_dir: Path | None = None) -> Path:
    return (base_dir or runtime_dir()) / PRODUCTION_LOG_FILENAME


def configure_runtime_logging(*, level: str | int = "INFO", base_dir: Path | None = None, tee_stdio: bool = False) -> None:
    resolved_level = normalize_log_level(level)
    directory = base_dir or runtime_dir()
    directory.mkdir(parents=True, exist_ok=True)
    maintain_runtime_directory(directory)
    log_path = runtime_log_path(directory)
    stdout_targets_log = _stdout_targets_path(log_path)
    if tee_stdio:
        install_stdio_tee(directory / STDIO_LOG_FILENAME)

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s%(teebotus_context)s")
    context_filter = TeeBotusLogContextFilter()
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(context_filter)
    handlers: list[logging.Handler] = [stream_handler]
    if not stdout_targets_log:
        file_handler = RuntimeTimedRotatingFileHandler(log_path)
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


def normalize_log_level(level: str | int) -> int:
    if isinstance(level, int):
        return _normalize_numeric_log_level(level)
    text = str(level or "INFO").strip()
    if not text:
        return logging.INFO
    if text.isdigit():
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
    path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path = path.resolve()
    if _stream_tee_target(sys.stdout) == resolved_path and _stream_tee_target(sys.stderr) == resolved_path:
        return
    handle = resolved_path.open("a", encoding="utf-8", buffering=1)
    sys.stdout = TeeStream(sys.stdout, handle, resolved_path)  # type: ignore[assignment]
    sys.stderr = TeeStream(sys.stderr, handle, resolved_path)  # type: ignore[assignment]


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
        secondary_write(text)
        return len(text)

    def flush(self) -> None:
        for stream in (self.primary, self.secondary):
            flush = getattr(stream, "flush", None)
            if callable(flush):
                flush()

    def fileno(self) -> int:
        fileno = getattr(self.primary, "fileno")
        return int(fileno())

    def isatty(self) -> bool:
        isatty = getattr(self.primary, "isatty", None)
        return bool(isatty()) if callable(isatty) else False

    def writable(self) -> bool:
        return True


def _stream_tee_target(stream: object) -> Path | None:
    target = getattr(stream, "_teebotus_tee_target", None)
    if isinstance(target, Path):
        return target.resolve()
    return None


class RuntimeTimedRotatingFileHandler(TimedRotatingFileHandler):
    def __init__(self, filename: Path) -> None:
        super().__init__(filename, when="midnight", interval=1, backupCount=0, encoding="utf-8")
        self.suffix = "%Y-%m-%d"

    def doRollover(self) -> None:  # noqa: N802 - stdlib override name
        super().doRollover()
        maintain_runtime_directory(Path(self.baseFilename).parent)


def _stdout_targets_path(path: Path) -> bool:
    try:
        stdout_stat = os.fstat(sys.stdout.fileno())
        path_stat = path.stat()
    except (AttributeError, FileNotFoundError, OSError, ValueError):
        return False
    return stdout_stat.st_dev == path_stat.st_dev and stdout_stat.st_ino == path_stat.st_ino


def rotate_runtime_text_file_if_needed(path: Path, *, max_bytes: int = MAX_RUNTIME_TEXT_FILE_BYTES) -> Path | None:
    if not path.exists() or path.stat().st_size <= max_bytes:
        return None
    rotated = _next_rotated_path(path)
    path.rename(rotated)
    return gzip_file(rotated)


def maintain_runtime_directory(
    runtime_path: Path,
    *,
    now: float | None = None,
    max_bytes: int = MAX_RUNTIME_TEXT_FILE_BYTES,
    compress_after_seconds: int = COMPRESS_AFTER_SECONDS,
    monthly_archive_after_seconds: int = MONTHLY_ARCHIVE_AFTER_SECONDS,
) -> None:
    runtime_path.mkdir(parents=True, exist_ok=True)
    resolved_now = time.time() if now is None else now
    for path in list(_runtime_text_files(runtime_path)):
        try:
            age = max(0.0, resolved_now - path.stat().st_mtime)
            if path.stat().st_size > max_bytes or age >= compress_after_seconds:
                gzip_file(path)
        except OSError:
            continue
    _archive_old_compressed_files(runtime_path, now=resolved_now, archive_after_seconds=monthly_archive_after_seconds)


def gzip_file(path: Path) -> Path:
    if path.suffix == ".gz" or not path.exists():
        return path
    stat = path.stat()
    target = _unique_path(path.with_name(f"{path.name}.gz"))
    temporary = _unique_path(path.with_name(f".{target.name}.tmp"))
    try:
        with path.open("rb") as source, gzip.open(temporary, "wb") as sink:
            shutil.copyfileobj(source, sink)
        os.utime(temporary, (stat.st_atime, stat.st_mtime))
        temporary.replace(target)
    except Exception:
        _unlink_quietly(temporary)
        raise
    path.unlink()
    return target


def _runtime_text_files(runtime_path: Path) -> list[Path]:
    archive_dir = runtime_path / "monthly_archives"
    result: list[Path] = []
    for pattern in ("*.log", "*.log.*", "*.jsonl", "*.jsonl.*"):
        for path in runtime_path.glob(pattern):
            if not path.is_file() or path.suffix == ".gz":
                continue
            if _is_temporary_runtime_file(path):
                continue
            if path.name in ACTIVE_RUNTIME_TEXT_FILENAMES:
                continue
            if archive_dir in path.parents:
                continue
            result.append(path)
    return sorted(set(result))


def _archive_old_compressed_files(runtime_path: Path, *, now: float, archive_after_seconds: int) -> None:
    archive_dir = runtime_path / "monthly_archives"
    groups: dict[str, list[Path]] = {}
    for path in runtime_path.glob("*.gz"):
        try:
            age = now - path.stat().st_mtime
        except OSError:
            continue
        if age < archive_after_seconds:
            continue
        month = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m")
        groups.setdefault(month, []).append(path)

    for month, paths in groups.items():
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = _unique_path(archive_dir / f"teebotus-runtime-{month}.tar.gz")
        temporary = _unique_path(archive_dir / f".{archive_path.name}.tmp")
        added_paths: list[Path] = []
        try:
            with tarfile.open(temporary, "w:gz") as archive:
                for path in paths:
                    try:
                        archive.add(path, arcname=path.name)
                    except FileNotFoundError:
                        continue
                    added_paths.append(path)
            if not added_paths:
                _unlink_quietly(temporary)
                continue
            temporary.replace(archive_path)
        except Exception:
            _unlink_quietly(temporary)
            raise
        for path in added_paths:
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def _next_rotated_path(path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    return _unique_path(path.with_name(f"{path.name}.{timestamp}"))


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _is_temporary_runtime_file(path: Path) -> bool:
    return path.name.startswith(".") or path.suffix == ".tmp"


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.name}.{index}")
        if not candidate.exists():
            return candidate
    raise OSError(f"could not find free runtime archive path for {path}")
