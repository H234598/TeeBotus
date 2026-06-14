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

RUNTIME_DIR = Path("data/runtime")
PRODUCTION_LOG_FILENAME = "teebotus-production.log"
MAX_RUNTIME_TEXT_FILE_BYTES = 2 * 1024 * 1024
COMPRESS_AFTER_SECONDS = 7 * 24 * 60 * 60
MONTHLY_ARCHIVE_AFTER_SECONDS = 60 * 24 * 60 * 60


def runtime_dir() -> Path:
    return RUNTIME_DIR


def runtime_log_path(base_dir: Path | None = None) -> Path:
    return (base_dir or runtime_dir()) / PRODUCTION_LOG_FILENAME


def configure_runtime_logging(*, level: str | int = "INFO", base_dir: Path | None = None) -> None:
    directory = base_dir or runtime_dir()
    directory.mkdir(parents=True, exist_ok=True)
    maintain_runtime_directory(directory)

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    file_handler = RuntimeTimedRotatingFileHandler(runtime_log_path(directory))
    file_handler.setFormatter(formatter)
    logging.basicConfig(level=level, handlers=[stream_handler, file_handler], force=True)


class RuntimeTimedRotatingFileHandler(TimedRotatingFileHandler):
    def __init__(self, filename: Path) -> None:
        super().__init__(filename, when="midnight", interval=1, backupCount=0, encoding="utf-8")
        self.suffix = "%Y-%m-%d"

    def doRollover(self) -> None:  # noqa: N802 - stdlib override name
        super().doRollover()
        maintain_runtime_directory(Path(self.baseFilename).parent)


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
    with path.open("rb") as source, gzip.open(target, "wb") as sink:
        shutil.copyfileobj(source, sink)
    os.utime(target, (stat.st_atime, stat.st_mtime))
    path.unlink()
    return target


def _runtime_text_files(runtime_path: Path) -> list[Path]:
    archive_dir = runtime_path / "monthly_archives"
    result: list[Path] = []
    for pattern in ("*.log", "*.log.*", "*.jsonl", "*.jsonl.*"):
        for path in runtime_path.glob(pattern):
            if not path.is_file() or path.suffix == ".gz":
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
        with tarfile.open(archive_path, "w:gz") as archive:
            for path in paths:
                archive.add(path, arcname=path.name)
        for path in paths:
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def _next_rotated_path(path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    return _unique_path(path.with_name(f"{path.name}.{timestamp}"))


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.name}.{index}")
        if not candidate.exists():
            return candidate
    raise OSError(f"could not find free runtime archive path for {path}")
