from __future__ import annotations

import json
import logging
import os
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("TeeBotus")

WORKING_MEMORY_INDEX_FILENAME = "Working_Memorys.json"
WORKING_MEMORY_ENTRIES_FILENAME = "Working_Memorys.entries.jsonl"
WORKING_MEMORY_MAX_PROMPT_CHARS = 6000
WORKING_MEMORY_PRIVACY_NOTE = (
    "Instanzweites Arbeitsgedaechtnis. Darf keine User-IDs, Namen, Usernames, Chat-IDs, "
    "Chat-Titel, Rohzitate aus Usernachrichten oder eindeutig userbezogene Fakten enthalten."
)
MEMORY_SCHEMA_VERSION = 1
MEMORY_RECENT_LIMIT = 200
MEMORY_KEYWORD_LIMIT = 24
MEMORY_KEYWORD_ENTRY_LIMIT = 250
MEMORY_STOPWORDS = {
    "aber",
    "alle",
    "alles",
    "als",
    "also",
    "auch",
    "auf",
    "aus",
    "bei",
    "bin",
    "bis",
    "bitte",
    "das",
    "dass",
    "dem",
    "den",
    "der",
    "des",
    "die",
    "dies",
    "dir",
    "doch",
    "ein",
    "eine",
    "einem",
    "einen",
    "einer",
    "eines",
    "er",
    "es",
    "hat",
    "hast",
    "ich",
    "ihm",
    "ihn",
    "ihr",
    "im",
    "in",
    "ist",
    "ja",
    "kann",
    "mal",
    "man",
    "mein",
    "mit",
    "mir",
    "mich",
    "nicht",
    "noch",
    "oder",
    "sich",
    "sie",
    "sind",
    "so",
    "und",
    "vom",
    "von",
    "war",
    "was",
    "wenn",
    "wer",
    "wie",
    "wir",
    "wird",
    "wo",
    "zu",
    "zum",
    "zur",
}


@dataclass(frozen=True)
class WorkingMemoryRecord:
    path: Path
    prompt_text: str
    selected_ids: tuple[str, ...]


class WorkingMemoryStore:
    def __init__(self, instance_name: str, instances_dir: str | Path = "instances") -> None:
        self.instance_name = instance_name
        self.instances_dir = Path(instances_dir)
        self._lock = threading.Lock()

    def ensure(self) -> Path:
        path = self._path()
        try:
            with self._lock:
                data = self._load_or_initialize(path)
                _write_json_file(path, data)
                _working_memory_entries_path(path).touch(exist_ok=True)
        except OSError as exc:
            LOGGER.warning(
                "Instance working memory unavailable at %s; existing data preserved: %s",
                path,
                exc,
            )
        return path

    def prepare(self, query_text: str, max_chars: int = WORKING_MEMORY_MAX_PROMPT_CHARS) -> WorkingMemoryRecord:
        path = self._path()
        with self._lock:
            data = self._load_or_initialize(path)
            prompt_text, selected_ids = _select_working_memory_prompt(path, data, query_text, max_chars)
        return WorkingMemoryRecord(path=path, prompt_text=prompt_text, selected_ids=tuple(selected_ids))

    def append_manual(self, text: str, kind: str = "manual") -> str:
        sanitized = _sanitize_working_memory_text(text)
        if not sanitized:
            return ""
        path = self._path()
        timestamp = _utc_timestamp()
        entry = {
            "id": _new_working_memory_id(),
            "created_at": timestamp,
            "updated_at": timestamp,
            "kind": str(kind or "manual").strip() or "manual",
            "text": sanitized,
            "keywords": _memory_keywords(sanitized),
        }
        with self._lock:
            data = self._load_or_initialize(path)
            entries_path = _working_memory_entries_path(path)
            offset = _store_working_memory_entry(path, data, entry)
            data["updated_at"] = timestamp
            try:
                _write_json_file(path, data)
            except Exception:
                _truncate_working_memory_entries(entries_path, offset)
                raise
        return str(entry["id"])

    def _path(self) -> Path:
        return self.instances_dir / self.instance_name / "data" / WORKING_MEMORY_INDEX_FILENAME

    def _load_or_initialize(self, path: Path) -> dict[str, Any]:
        path.parent.mkdir(parents=True, exist_ok=True)
        entries_path = _working_memory_entries_path(path)
        if not path.exists():
            data = _new_working_memory_data(self.instance_name)
            _write_json_file(path, data)
            entries_path.touch(exist_ok=True)
            return data
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            backup_path = _move_corrupt_json_file(path)
            LOGGER.warning(
                "Resetting invalid instance working memory at %s: %s. Corrupt file preserved at %s.",
                path,
                exc,
                backup_path,
            )
            payload = _new_working_memory_data(self.instance_name)
        except OSError as exc:
            raise OSError(f"Unable to read instance working memory at {path}") from exc
        if not isinstance(payload, dict):
            backup_path = _move_corrupt_json_file(path)
            LOGGER.warning(
                "Resetting invalid instance working memory at %s: expected JSON object. Corrupt file preserved at %s.",
                path,
                backup_path,
            )
            payload = _new_working_memory_data(self.instance_name)
        index = payload.get("index")
        invalid_index = "index" in payload and not isinstance(index, dict)
        if isinstance(index, dict):
            invalid_index = any(
                key in index and not isinstance(index[key], expected_type)
                for key, expected_type in (
                    ("keywords", dict),
                    ("recent_ids", list),
                    ("entries", dict),
                )
            )
        if invalid_index:
            backup_path = _move_corrupt_json_file(path)
            LOGGER.warning(
                "Resetting invalid instance working memory at %s: invalid index structure. Corrupt file preserved at %s.",
                path,
                backup_path,
            )
            payload = _new_working_memory_data(self.instance_name)
        _normalize_working_memory_data(payload, self.instance_name)
        entries_path.touch(exist_ok=True)
        return payload


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_working_memory_data(instance_name: str) -> dict[str, Any]:
    timestamp = _utc_timestamp()
    return {
        "schema_version": MEMORY_SCHEMA_VERSION,
        "scope": "instance",
        "instance_name": instance_name,
        "privacy": WORKING_MEMORY_PRIVACY_NOTE,
        "created_at": timestamp,
        "updated_at": timestamp,
        "entry_store": WORKING_MEMORY_ENTRIES_FILENAME,
        "index": {
            "keywords": {},
            "recent_ids": [],
            "entries": {},
        },
    }


def _normalize_working_memory_data(data: dict[str, Any], instance_name: str) -> None:
    data["schema_version"] = MEMORY_SCHEMA_VERSION
    data["scope"] = "instance"
    data["instance_name"] = str(instance_name)
    data["privacy"] = WORKING_MEMORY_PRIVACY_NOTE
    data.setdefault("created_at", _utc_timestamp())
    data.setdefault("updated_at", data["created_at"])
    data["entry_store"] = WORKING_MEMORY_ENTRIES_FILENAME
    index = data.setdefault("index", {})
    if not isinstance(index, dict):
        index = {}
        data["index"] = index
    if not isinstance(index.get("keywords"), dict):
        index["keywords"] = {}
    if not isinstance(index.get("recent_ids"), list):
        index["recent_ids"] = []
    if not isinstance(index.get("entries"), dict):
        index["entries"] = {}
    data.pop("sender_id", None)
    data.pop("profile", None)
    data.pop("memories", None)


def _select_working_memory_prompt(index_path: Path, data: dict[str, Any], query_text: str, max_chars: int) -> tuple[str, list[str]]:
    if max_chars < 1:
        return "", []
    _normalize_working_memory_data(data, str(data.get("instance_name", "")))
    index = data.get("index") if isinstance(data.get("index"), dict) else {}
    entry_index = index.get("entries") if isinstance(index.get("entries"), dict) else {}
    if not entry_index:
        return "", []
    scores: dict[str, int] = {}
    keyword_index = index.get("keywords") if isinstance(index.get("keywords"), dict) else {}
    for keyword in _memory_keywords(query_text):
        for memory_id in keyword_index.get(keyword, []):
            if memory_id in entry_index:
                scores[memory_id] = scores.get(memory_id, 0) + 1
    recent_ids = [str(memory_id) for memory_id in index.get("recent_ids", [])] if isinstance(index.get("recent_ids"), list) else []
    if scores:
        ordered_ids = sorted(
            scores,
            key=lambda memory_id: (
                scores[memory_id],
                recent_ids.index(memory_id) if memory_id in recent_ids else -1,
            ),
            reverse=True,
        )
        ordered_ids.extend(memory_id for memory_id in reversed(recent_ids) if memory_id in entry_index and memory_id not in ordered_ids)
    else:
        ordered_ids = list(reversed(recent_ids))
    if not ordered_ids:
        ordered_ids = list(reversed(list(entry_index.keys())))
    selected: list[dict[str, Any]] = []
    selected_ids: list[str] = []
    for memory_id in ordered_ids:
        memory = _read_working_memory_entry(index_path, data, memory_id)
        if memory is None or memory_id in selected_ids:
            continue
        candidate = _compact_working_memory_for_prompt(memory)
        candidate_payload = _working_memory_prompt_payload(data, [*selected_ids, memory_id], [*selected, candidate])
        candidate_text = json.dumps(candidate_payload, ensure_ascii=False, indent=2)
        if len(candidate_text) > max_chars:
            if selected:
                break
            candidate["text"] = _clip_memory_text(str(candidate.get("text", "")), max(200, max_chars // 2))
            candidate_payload = _working_memory_prompt_payload(data, [memory_id], [candidate])
            candidate_text = json.dumps(candidate_payload, ensure_ascii=False, indent=2)
            if len(candidate_text) > max_chars:
                break
        selected.append(candidate)
        selected_ids.append(memory_id)
    if not selected:
        return "", []
    return json.dumps(_working_memory_prompt_payload(data, selected_ids, selected), ensure_ascii=False, indent=2), selected_ids


def _working_memory_prompt_payload(
    data: dict[str, Any],
    selected_ids: list[str],
    selected: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "scope": "instance",
        "instance_name": str(data.get("instance_name", "")),
        "privacy": WORKING_MEMORY_PRIVACY_NOTE,
        "selected_working_memory_ids": selected_ids,
        "memories": selected,
    }


def _store_working_memory_entry(index_path: Path, data: dict[str, Any], entry: dict[str, Any]) -> int:
    _normalize_working_memory_data(data, str(data.get("instance_name", "")))
    memory_id = str(entry.get("id") or _new_working_memory_id())
    entry["id"] = memory_id
    entry["text"] = _sanitize_working_memory_text(str(entry.get("text", "")))
    keywords = _memory_keywords(str(entry.get("text", "")))
    entry["keywords"] = keywords
    entries_path = _working_memory_entries_path(index_path)
    entries_path.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    offset = 0
    try:
        with entries_path.open("ab") as file:
            offset = file.tell()
            file.write(line)
    except Exception:
        _truncate_working_memory_entries(entries_path, offset)
        raise
    index = data.setdefault("index", {})
    entry_index = index.setdefault("entries", {})
    if not isinstance(entry_index, dict):
        entry_index = {}
        index["entries"] = entry_index
    entry_index[memory_id] = {
        "offset": offset,
        "length": len(line),
        "created_at": str(entry.get("created_at", "")),
        "updated_at": str(entry.get("updated_at", "")),
        "kind": str(entry.get("kind", "")),
        "keywords": keywords,
    }
    keyword_index = index.setdefault("keywords", {})
    if not isinstance(keyword_index, dict):
        keyword_index = {}
        index["keywords"] = keyword_index
    for keyword in keywords[:MEMORY_KEYWORD_LIMIT]:
        entries = keyword_index.setdefault(keyword, [])
        if not isinstance(entries, list):
            entries = []
            keyword_index[keyword] = entries
        if memory_id not in entries:
            entries.append(memory_id)
            del entries[:-MEMORY_KEYWORD_ENTRY_LIMIT]
    recent_ids = index.setdefault("recent_ids", [])
    if not isinstance(recent_ids, list):
        recent_ids = []
        index["recent_ids"] = recent_ids
    if memory_id in recent_ids:
        recent_ids.remove(memory_id)
    recent_ids.append(memory_id)
    del recent_ids[:-MEMORY_RECENT_LIMIT]
    return offset


def _truncate_working_memory_entries(path: Path, offset: int) -> None:
    try:
        with path.open("r+b") as file:
            file.truncate(offset)
    except OSError:
        LOGGER.exception("Failed to roll back instance working memory entries path=%s.", path)


def _read_working_memory_entry(index_path: Path, data: dict[str, Any], memory_id: str) -> dict[str, Any] | None:
    index = data.get("index") if isinstance(data.get("index"), dict) else {}
    entries = index.get("entries") if isinstance(index.get("entries"), dict) else {}
    metadata = entries.get(memory_id)
    if not isinstance(metadata, dict):
        return None
    try:
        offset = int(metadata.get("offset"))
        length = int(metadata.get("length"))
    except (TypeError, ValueError):
        return None
    try:
        with _working_memory_entries_path(index_path).open("rb") as file:
            file.seek(offset)
            payload = json.loads(file.read(length).decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        LOGGER.exception("Failed to read JSONL instance working memory entry id=%s.", memory_id)
        return None
    if not isinstance(payload, dict) or str(payload.get("id", "")) != memory_id:
        return None
    return payload


def _working_memory_entries_path(index_path: Path) -> Path:
    return index_path.parent / WORKING_MEMORY_ENTRIES_FILENAME


def _compact_working_memory_for_prompt(memory: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(memory.get("id", "")),
        "created_at": str(memory.get("created_at", "")),
        "kind": str(memory.get("kind", "")),
        "keywords": memory.get("keywords", []) if isinstance(memory.get("keywords"), list) else [],
        "text": str(memory.get("text", "")),
    }


def _sanitize_working_memory_text(text: str) -> str:
    sanitized = str(text or "").strip()
    sanitized = re.sub(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[email entfernt]", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"(?<!\w)@[A-Za-z0-9_]{3,}", "[handle entfernt]", sanitized)
    sanitized = re.sub(r"https?://\S+|www\.\S+", "[url entfernt]", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"\b\+?\d[\d\s()./-]{4,}\d\b", "[zahl entfernt]", sanitized)
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    return sanitized


def _memory_keywords(text: str) -> list[str]:
    keywords: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"\b\w{3,}\b", str(text or "").casefold(), re.UNICODE):
        keyword = match.group(0).strip("_")
        if not keyword or keyword in MEMORY_STOPWORDS or keyword.isdigit():
            continue
        if keyword in seen:
            continue
        seen.add(keyword)
        keywords.append(keyword)
        if len(keywords) >= MEMORY_KEYWORD_LIMIT:
            break
    return keywords


def _new_working_memory_id() -> str:
    return f"wm_{uuid.uuid4().hex}"


def _clip_memory_text(text: str, max_chars: int) -> str:
    stripped = str(text or "").strip()
    if len(stripped) <= max_chars:
        return stripped
    return stripped[:max_chars].rstrip() + "\n[gekuerzt]"


def _write_json_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary_path.open("w", encoding="utf-8") as file:
            file.write(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, path)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            LOGGER.warning("Failed to remove temporary JSON state path=%s", temporary_path)


def _move_corrupt_json_file(path: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = path.with_name(f"{path.name}.corrupt.{timestamp}")
    for index in range(1, 1000):
        candidate = backup_path if index == 1 else path.with_name(f"{path.name}.corrupt.{timestamp}.{index}")
        if candidate.exists():
            continue
        try:
            path.rename(candidate)
            return candidate
        except FileNotFoundError:
            return candidate
    return path
