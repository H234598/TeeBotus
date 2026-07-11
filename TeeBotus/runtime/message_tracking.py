from __future__ import annotations

import json
import os
import stat
import tempfile
import threading
from contextlib import contextmanager
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

try:
    import fcntl
except ImportError:  # pragma: no cover - fcntl is unavailable on non-POSIX platforms.
    fcntl = None  # type: ignore[assignment]

RefKind = Literal["telegram_message_id", "signal_timestamp", "matrix_event_id"]
MESSAGE_TRACKER_FILENAME = "Sent_Message_Refs.json"


def _normalize_max_refs(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 100


@dataclass(frozen=True)
class SentMessageRef:
    channel: str
    instance_name: str
    account_id: str
    chat_id: str
    message_ref: str
    ref_kind: RefKind


class MessageTracker:
    """Tracks bot messages for current-chat cleanup only.

    Supports in-memory tracking and optional JSON persistence when constructed with a
    path. Persistence keeps cleanup state across the integration-scaffold lifetime
    without widening cleanup beyond the current chat.
    """

    def __init__(self, root_or_max_refs: Path | str | int | None = None, max_refs_per_chat: int = 100) -> None:
        self.storage_path: Path | None = None
        if isinstance(root_or_max_refs, int):
            self.max_refs_per_chat = _normalize_max_refs(root_or_max_refs)
        else:
            self.max_refs_per_chat = _normalize_max_refs(max_refs_per_chat)
            if root_or_max_refs is not None:
                candidate = Path(root_or_max_refs)
                self.storage_path = candidate if candidate.suffix else candidate / MESSAGE_TRACKER_FILENAME
        self._lock = threading.RLock()
        self.refs: dict[tuple[str, str, str], list[SentMessageRef]] = {}
        self._load()

    def record(self, ref: SentMessageRef) -> None:
        with self._lock, self._storage_lock(exclusive=True):
            self._reload_from_disk()
            key = (ref.instance_name, ref.channel, ref.chat_id)
            values = self.refs.setdefault(key, [])
            ref_key = (ref.account_id, ref.message_ref, ref.ref_kind)
            if any((existing.account_id, existing.message_ref, existing.ref_kind) == ref_key for existing in values):
                return
            values.append(ref)
            self._trim_values(values)
            self._save()

    def restore_for_cleanup(self, refs: list[SentMessageRef]) -> None:
        if not refs:
            return
        with self._lock, self._storage_lock(exclusive=True):
            self._reload_from_disk()
            changed = False
            grouped: dict[tuple[str, str, str], list[SentMessageRef]] = {}
            for ref in refs:
                grouped.setdefault((ref.instance_name, ref.channel, ref.chat_id), []).append(ref)
            for key, popped_refs in grouped.items():
                values = self.refs.setdefault(key, [])
                existing = {(ref.account_id, ref.message_ref, ref.ref_kind) for ref in values}
                for ref in reversed(popped_refs):
                    ref_key = (ref.account_id, ref.message_ref, ref.ref_kind)
                    if ref_key in existing:
                        continue
                    values.append(ref)
                    existing.add(ref_key)
                    changed = True
                self._trim_values(values)
            if changed:
                self._save()

    def list_for_chat(self, chat_id: str, *, instance_name: str | None = None, channel: str | None = None) -> list[SentMessageRef]:
        with self._lock, self._storage_lock(exclusive=False):
            self._reload_from_disk()
            selected: list[SentMessageRef] = []
            for (inst, ch, cid), values in self.refs.items():
                if cid != str(chat_id):
                    continue
                if instance_name is not None and inst != instance_name:
                    continue
                if channel is not None and ch != channel:
                    continue
                selected.extend(values)
            return list(selected)

    def pop_for_chat(self, chat_id: str, count: int | str = "all", *, instance_name: str | None = None, channel: str | None = None) -> list[SentMessageRef]:
        with self._lock, self._storage_lock(exclusive=True):
            self._reload_from_disk()
            selected: list[SentMessageRef] = []
            changed = False
            for key in list(self.refs):
                inst, ch, cid = key
                if cid != str(chat_id):
                    continue
                if instance_name is not None and inst != instance_name:
                    continue
                if channel is not None and ch != channel:
                    continue
                values = self.refs[key]
                if count == "all":
                    chosen = list(reversed(values))
                    if chosen:
                        changed = True
                    self.refs[key] = []
                else:
                    n = max(0, int(count))
                    chosen = list(reversed(values[-n:])) if n else []
                    if n and chosen:
                        del values[-n:]
                        changed = True
                selected.extend(chosen)
            if changed:
                self._save()
            return selected

    def pop_for_cleanup(self, *, instance_name: str, channel: str, chat_id: str, count: int | str) -> list[SentMessageRef]:
        return self.pop_for_chat(chat_id, count, instance_name=instance_name, channel=channel)

    def _load(self) -> None:
        with self._lock, self._storage_lock(exclusive=False):
            self._reload_from_disk()

    def _reload_from_disk(self) -> None:
        path = self.storage_path
        if path is None:
            return
        if not path.exists():
            if path.parent.exists():
                self.refs = {}
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        rows = payload.get("refs") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return
        loaded: dict[tuple[str, str, str], list[SentMessageRef]] = {}
        seen_by_chat: dict[tuple[str, str, str], set[tuple[str, str, str]]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                ref = SentMessageRef(
                    channel=str(row["channel"]),
                    instance_name=str(row["instance_name"]),
                    account_id=str(row.get("account_id", "")),
                    chat_id=str(row["chat_id"]),
                    message_ref=str(row["message_ref"]),
                    ref_kind=str(row["ref_kind"]),  # type: ignore[arg-type]
                )
            except KeyError:
                continue
            if ref.ref_kind not in {"telegram_message_id", "signal_timestamp", "matrix_event_id"}:
                continue
            key = (ref.instance_name, ref.channel, ref.chat_id)
            ref_key = (ref.account_id, ref.message_ref, ref.ref_kind)
            seen = seen_by_chat.setdefault(key, set())
            if ref_key in seen:
                continue
            seen.add(ref_key)
            loaded.setdefault(key, []).append(ref)
        self.refs = loaded
        for values in self.refs.values():
            self._trim_values(values)

    def _trim_values(self, values: list[SentMessageRef]) -> None:
        if self.max_refs_per_chat <= 0:
            values.clear()
            return
        del values[:-self.max_refs_per_chat]

    def _save(self) -> None:
        path = self.storage_path
        if path is None:
            return
        rows = [asdict(ref) for values in self.refs.values() for ref in values]
        path.parent.mkdir(parents=True, exist_ok=True)
        if not rows:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            return
        payload = (json.dumps({"refs": rows}, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass
            os.replace(temp_path, path)
        finally:
            temp_path.unlink(missing_ok=True)

    @contextmanager
    def _storage_lock(self, *, exclusive: bool) -> Iterator[None]:
        path = self.storage_path
        if path is None or fcntl is None:
            yield
            return
        lock_path = path.with_name(f".{path.name}.lock")
        try:
            if not lock_path.parent.exists():
                if not exclusive:
                    yield
                    return
                lock_path.parent.mkdir(parents=True, exist_ok=True)
            handle = lock_path.open("a+b")
        except OSError:
            yield
            return
        try:
            try:
                os.chmod(lock_path, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
            except OSError:
                yield
                return
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
