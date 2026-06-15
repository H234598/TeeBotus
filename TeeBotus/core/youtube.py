from __future__ import annotations

import json
import logging
import os
import re
import hashlib
import select
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from contextlib import suppress
from pathlib import Path
from typing import Any

from TeeBotus.runtime.maintenance import runtime_dir

LOGGER = logging.getLogger("TeeBotus")
YOUTUBE_TRANSCRIPT_COMMANDS = {"/youtube_transcript", "/yt_transcript"}
YOUTUBE_TRANSCRIPT_TIMEOUT_SECONDS = 15 * 60
YOUTUBE_WHISPER_TIMEOUT_SECONDS = 7200
YOUTUBE_TRANSCRIPTION_HEALTH_CHECK_SECONDS = (5 * 60, 15 * 60, 60 * 60, 90 * 60)
YOUTUBE_TRANSCRIPT_MAX_PIPELINE_CHARS = 60000
YOUTUBE_WHISPER_MODEL = "tiny"
YOUTUBE_FASTER_WHISPER_COMPUTE_TYPE = "int8"
YOUTUBE_FASTER_WHISPER_CPU_THREADS = 2
YOUTUBE_TRANSCRIPT_NICE_LEVEL = 19
YOUTUBE_PARSER_MISSES_FILENAME = "YouTube_Parser_Misses.jsonl"
YOUTUBE_TRANSCRIPT_CACHE_DIRNAME = "youtube_transcripts"


def _default_instances_dir() -> Path:
    return Path(os.getenv("TELEGRAM_BOT_INSTANCES_DIR", "instances").strip() or "instances")


def _utc_timestamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize_command(text: str) -> str:
    first = str(text or "").strip().split(maxsplit=1)[0] if str(text or "").strip() else ""
    return first.split("@", maxsplit=1)[0].casefold()

PROCESS_REGISTRY_FILENAME = "YouTube_Transcription_Processes.json"
_PROCESS_REGISTRY_LOCKS: dict[str, threading.Lock] = {}


class _InstanceProcessRegistry:
    def __init__(self, instance_name: str) -> None:
        self.instance_name = instance_name.strip()
        self._lock = _PROCESS_REGISTRY_LOCKS.setdefault(self.instance_name, threading.Lock())

    def register(self, pid: int) -> int | None:
        if not self.instance_name or pid <= 0:
            return None
        start_time = _read_process_start_time(pid)
        if start_time is None:
            LOGGER.debug("Skipping process registry entry for pid %s because its start time could not be read.", pid)
            return None
        owner_pid = os.getpid()
        owner_start_time = _read_process_start_time(owner_pid)
        with self._lock:
            state = self._load_state()
            processes = state.setdefault("processes", [])
            if not any(
                isinstance(entry, dict)
                and entry.get("pid") == pid
                and entry.get("start_time") == start_time
                for entry in processes
            ):
                processes.append(
                    {
                        "pid": pid,
                        "start_time": start_time,
                        "owner_pid": owner_pid,
                        "owner_start_time": owner_start_time,
                    }
                )
            state["updated_at"] = _utc_timestamp()
            self._write_state(state)
        return start_time

    def unregister(self, pid: int, start_time: int | None = None) -> None:
        if not self.instance_name or pid <= 0 or start_time is None:
            return
        with self._lock:
            state = self._load_state()
            processes = state.get("processes")
            if isinstance(processes, list):
                state["processes"] = [
                    entry
                    for entry in processes
                    if not (
                        isinstance(entry, dict)
                        and entry.get("pid") == pid
                        and (start_time is None or entry.get("start_time") == start_time)
                    )
                ]
                state["updated_at"] = _utc_timestamp()
                self._write_state(state)

    def cleanup_orphans(self, include_current_owner: bool = False) -> None:
        if not self.instance_name:
            return
        with self._lock:
            state = self._load_state()
            processes = [entry for entry in state.get("processes", []) if isinstance(entry, dict)]
            remaining: list[dict[str, Any]] = []
            for entry in processes:
                pid = entry.get("pid")
                start_time = entry.get("start_time")
                if not isinstance(pid, int) or pid <= 0:
                    continue
                if not isinstance(start_time, int) or start_time <= 0:
                    continue
                owner_pid = entry.get("owner_pid")
                owner_start_time = entry.get("owner_start_time")
                if self._process_owner_is_active(owner_pid, owner_start_time, include_current_owner):
                    remaining.append(entry)
                    continue
                process_state = self._process_record_state(pid, start_time)
                if process_state == "unknown":
                    remaining.append(entry)
                    continue
                if process_state != "match":
                    continue
                self._terminate_process_group(pid)
            self._write_state({"processes": remaining, "updated_at": _utc_timestamp()})

    @staticmethod
    def _process_owner_is_active(owner_pid: Any, owner_start_time: Any, include_current_owner: bool) -> bool:
        if not isinstance(owner_pid, int) or owner_pid <= 0:
            return False
        if include_current_owner and owner_pid == os.getpid():
            return False
        if not isinstance(owner_start_time, int) or owner_start_time <= 0:
            return False
        return _read_process_start_time(owner_pid) == owner_start_time

    def _path(self) -> Path:
        return _default_instances_dir() / self.instance_name / "data" / PROCESS_REGISTRY_FILENAME

    def _load_state(self) -> dict[str, Any]:
        path = self._path()
        if not path.exists():
            return {"processes": []}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            LOGGER.debug("Failed to read process registry at %s.", path)
            return {"processes": []}
        if not isinstance(payload, dict):
            return {"processes": []}
        processes = payload.get("processes")
        if isinstance(processes, list):
            payload["processes"] = [
                entry
                for entry in processes
                if isinstance(entry, dict)
                and isinstance(entry.get("pid"), int)
                and entry["pid"] > 0
                and isinstance(entry.get("start_time"), int)
                and entry["start_time"] > 0
            ]
        else:
            stored_pids = payload.get("pids")
            if isinstance(stored_pids, list):
                payload["processes"] = [
                    {"pid": pid, "start_time": _read_process_start_time(pid) or 0}
                    for pid in stored_pids
                    if (isinstance(pid, int) and pid > 0) or (isinstance(pid, str) and pid.isdigit() and int(pid) > 0)
                ]
                payload["processes"] = [entry for entry in payload["processes"] if entry["start_time"] > 0]
            else:
                payload["processes"] = []
        payload.pop("pids", None)
        return payload

    def _write_state(self, state: dict[str, Any]) -> None:
        path = self._path()
        processes = state.get("processes")
        if not isinstance(processes, list) or not processes:
            with suppress(FileNotFoundError):
                path.unlink()
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @staticmethod
    def _process_record_state(pid: int, expected_start_time: int) -> str:
        actual_start_time = _read_process_start_time(pid)
        if actual_start_time is None:
            try:
                os.killpg(pid, 0)
            except ProcessLookupError:
                return "dead"
            except OSError:
                return "unknown"
            return "unknown"
        return "match" if actual_start_time == expected_start_time else "mismatch"

    @staticmethod
    def _terminate_process_group(pid: int) -> None:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except OSError:
            LOGGER.debug("Failed to terminate process group %s with SIGTERM.", pid)
            return
        for _ in range(30):
            try:
                os.killpg(pid, 0)
            except ProcessLookupError:
                return
            except OSError:
                return
            time.sleep(0.1)
        with suppress(ProcessLookupError, OSError):
            os.killpg(pid, signal.SIGKILL)


def _parse_youtube_local_options(text: str, instance_name: str = "", instances_dir: Path | None = None) -> tuple[bool | None, bool | None]:
    learned_options = _parse_learned_youtube_local_options(text, instance_name, instances_dir=instances_dir)
    if learned_options is not None:
        return learned_options
    normalized = re.sub(r"[_-]+", " ", text.casefold())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    yes_words = r"ja|yes|jup|ok|okay|y|true|wahr|an|ein|on|1"
    no_words = r"nein|no|n|nee|false|falsch|aus|off|0"
    live_match = re.search(rf"\blive(?:\s+(?:output|ausgabe))?\s*(?:=|:)?\s*({yes_words}|{no_words})\b", normalized)
    llm_match = re.search(rf"\b(?:llm|send\s*to\s*llm)\s*(?:=|:)?\s*({yes_words}|{no_words})\b", normalized)
    if live_match and llm_match:
        return _yes_no_value(live_match.group(1)), _yes_no_value(llm_match.group(1))
    live_option = _parse_youtube_live_option(normalized)
    llm_option = _parse_youtube_llm_option(normalized)
    if live_option is not None or llm_option is not None:
        return live_option, llm_option
    tokens = re.findall(rf"\b({yes_words}|{no_words})\b", normalized)
    if len(tokens) >= 2:
        return _yes_no_value(tokens[0]), _yes_no_value(tokens[1])
    return None, None


def _parse_learned_youtube_local_options(text: str, instance_name: str, instances_dir: Path | None = None) -> tuple[bool, bool] | None:
    if not instance_name:
        return None
    path = _youtube_parser_misses_path(instance_name, instances_dir=instances_dir)
    if not path.exists():
        return None
    normalized_formulation = _normalize_youtube_option_formulation(text)
    formulation_tokens = _youtube_option_formulation_tokens(normalized_formulation)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        LOGGER.debug("Could not read YouTube parser misses at %s: %s", path, exc)
        return None
    for line in reversed(lines[-200:]):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        learned_formulation = _normalize_youtube_option_formulation(str(entry.get("formulation") or ""))
        if learned_formulation != normalized_formulation and not _learned_youtube_formulation_matches(
            _youtube_option_formulation_tokens(learned_formulation),
            formulation_tokens,
        ):
            continue
        live_value = _coerce_optional_bool(entry.get("llm_live_output"))
        llm_value = _coerce_optional_bool(entry.get("llm_send_to_llm"))
        if live_value is not None and llm_value is not None:
            return live_value, llm_value
    return None


def _parse_youtube_live_option(normalized_text: str) -> bool | None:
    live_name = r"(?:live(?:\s*(?:output|ausgabe|modus))?|liveausgabe|zwischen(?:stand|stände|staende)|chunks?|häppchen|haeppchen)"
    live_delivery = r"(?:post(?:en|est)?|past(?:e|en|est)?|sende(?:n|st)?|schick(?:en|st)?|ausgeb(?:en|e|t)?|zeig(?:en|st)?|meld(?:en|est)?|stream(?:en|st)?|spam(?:men|mst)?)"
    during_words = r"(?:live|während(?:dessen)?|waehrend(?:dessen)?|zwischendurch|unterwegs|parallel|laufend|fortlaufend|sofort|direkt)"
    if re.search(rf"\b(?:ohne|kein(?:e|en|em|er|es)?|nicht)\s+{live_name}\b", normalized_text):
        return False
    if re.search(rf"\b{live_name}\s*(?:=|:)?\s*(?:nein|no|n|nee|false|falsch|aus|off|0|nicht|deaktivier(?:en|t)?|abschalt(?:en|en)?)\b", normalized_text):
        return False
    if re.search(rf"\b(?:nicht|nichts|kein(?:e|en|em|er|es)?)\b.{{0,60}}\b{during_words}\b.{{0,60}}\b{live_delivery}\b", normalized_text):
        return False
    if re.search(rf"\b(?:nicht|nichts|kein(?:e|en|em|er|es)?)\b.{{0,60}}\b{live_delivery}\b.{{0,60}}\b{during_words}\b", normalized_text):
        return False
    if re.search(rf"\b{during_words}\b.{{0,60}}\b(?:nicht|nichts|kein(?:e|en|em|er|es)?)\b.{{0,60}}\b{live_delivery}\b", normalized_text):
        return False
    if re.search(r"\b(?:erst|nur)\s+(?:am\s+ende|nachher|danach|wenn\s+fertig|nach\s+der\s+transkription)\b.{0,80}\b(?:post(?:en)?|past(?:en)?|senden|schicken|ausgeben|melden|antworten)\b", normalized_text):
        return False
    if re.search(rf"\b{live_name}\s*(?:=|:)?\s*(?:ja|yes|jup|ok|okay|y|true|wahr|an|ein|on|1|aktivier(?:en|t)?)\b", normalized_text):
        return True
    if re.search(rf"\b(?:mit|bitte|gern(?:e)?)\b.{{0,30}}\b{live_name}\b", normalized_text):
        return True
    if re.search(rf"\b{live_delivery}\b.{{0,60}}\b{during_words}\b", normalized_text):
        return True
    if re.search(rf"\b{during_words}\b.{{0,60}}\b{live_delivery}\b", normalized_text):
        return True
    if re.search(rf"\b(?:mit\s+)?{live_name}\b", normalized_text):
        return True
    return None


def _parse_youtube_llm_option(normalized_text: str) -> bool | None:
    llm_name = r"(?:llm|send\s*to\s*llm|gpt|chatgpt|openai|ki|ai|modell|model)"
    llm_target = rf"(?:(?:an|ans|zum|zur|in|ins)\s+)?(?:dein(?:e[nm])?\s+)?{llm_name}"
    llm_actions = r"(?:auswert(?:en|ung)?|analysier(?:en|e|t)?|analyse|zusammenfass(?:en|ung)?|summary|summariz(?:e|en)|fazit|bewert(?:en|ung)?|interpretier(?:en|e|t)?)"
    send_verbs = r"(?:schick(?:en)?|send(?:en)?|leit(?:e|en)?|weiter(?:geben|leiten)?|gib|geben|geht|gehen|reich(?:e|en)?|übergib(?:en)?|uebergib(?:en)?)"
    if re.search(rf"\b(?:ohne|kein(?:e|en|em|er|es)?|nicht)\s+{llm_target}\b", normalized_text):
        return False
    if re.search(rf"\b{llm_name}\s*(?:=|:)?\s*(?:nein|no|n|nee|false|falsch|aus|off|0|nicht|deaktivier(?:en|t)?|abschalt(?:en|en)?)\b", normalized_text):
        return False
    llm_negative_fillers = r"(?:(?:mehr|weiter(?:e|en|er)?|noch|extra|zusätzlich|zusaetzlich|bitte|irgendwas)\s+)*"
    if re.search(rf"\b(?:nicht|ohne)\s+{llm_negative_fillers}{llm_actions}\b", normalized_text):
        return False
    if re.search(rf"\bkein(?:e|en|em|er|es)?\s+{llm_negative_fillers}(?:{llm_actions}|{llm_name})\b", normalized_text):
        return False
    if re.search(r"\b(?:nur|bloß|bloss|lediglich)\b.{0,40}\b(?:transkribier(?:en|e)?|transkript|abschrift)\b", normalized_text) and not re.search(rf"\b{llm_name}\s*(?:=|:)?\s*(?:ja|yes|jup|ok|okay|y|true|wahr|an|ein|on|1)\b", normalized_text):
        return False
    if re.search(rf"\b{llm_target}\s*(?:=|:)?\s*(?:ja|yes|jup|ok|okay|y|true|wahr|an|ein|on|1)\b", normalized_text):
        return True
    if re.search(rf"\b(?:an|ans|zum|zur|in|ins)\s+(?:dein(?:e[nm])?\s+)?{llm_name}\b", normalized_text):
        return True
    if re.search(rf"\b(?:aber|mit|durch|per)\s+(?:dein(?:e[nm])?\s+)?{llm_name}\b", normalized_text):
        return True
    if re.search(r"\bsend\s*to\s*llm\b", normalized_text):
        return True
    if re.search(rf"\b{send_verbs}\b.{{0,100}}\b{llm_target}\b", normalized_text):
        return True
    if re.search(rf"\b{llm_target}\b.{{0,100}}\b(?:schick(?:en)?|send(?:en)?|leit(?:e|en)?|weiter(?:geben|leiten)?|gib|geben|{llm_actions})\b", normalized_text):
        return True
    if re.search(rf"\b(?:danach|dann|anschlie(?:ß|ss)end|hinterher|nachher|am\s+ende|nach\s+der\s+transkription)\b.{{0,100}}\b{llm_actions}\b", normalized_text):
        return True
    if re.search(rf"\b{llm_actions}\b.{{0,100}}\b(?:danach|dann|anschlie(?:ß|ss)end|hinterher|nachher|am\s+ende|nach\s+der\s+transkription)\b", normalized_text):
        return True
    if re.search(rf"\b(?:lass|laß)\b.{{0,80}}\b(?:ki|ai|gpt|chatgpt|openai|modell|model)\b.{{0,80}}\b(?:drüber|drueber|drauf|darauf|damit)\b", normalized_text):
        return True
    if re.search(r"\b(?:danach|anschlie(?:ß|ss)end|hinterher|nachher|am\s+ende)\b.{0,80}\b(?:an\s+dich|zu\s+dir|dir\s+geben|gib\s+dir|schick\s+dir)\b", normalized_text):
        return True
    if re.search(r"\b(?:an\s+dich|zu\s+dir|dir)\b.{0,50}\b(?:geben|schicken|senden|weitergeben|weiterleiten|auswerten|analysieren)\b", normalized_text):
        return True
    return None


def _parse_youtube_local_options_from_llm_response(text: str) -> tuple[bool, bool] | None:
    payload = _extract_json_object(text)
    if payload is None:
        return None
    live_value = _coerce_optional_bool(payload.get("live_output"))
    llm_value = _coerce_optional_bool(payload.get("send_to_llm"))
    if live_value is None or llm_value is None:
        return None
    return live_value, llm_value


def _extract_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if not stripped:
        return None
    candidates = [stripped]
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        candidates.insert(0, fenced.group(1))
    inline = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    if inline:
        candidates.append(inline.group(0))
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _coerce_optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "yes", "ja", "jup", "on", "an", "1"}:
            return True
        if normalized in {"false", "no", "nein", "nee", "off", "aus", "0"}:
            return False
    return None


def _record_youtube_parser_miss(
    instance_name: str,
    text: str,
    parser_options: tuple[bool | None, bool | None],
    llm_options: tuple[bool, bool],
    context: str,
    instances_dir: Path | None = None,
) -> None:
    path = _youtube_parser_misses_path(instance_name, instances_dir=instances_dir)
    entry = {
        "created_at": _utc_timestamp(),
        "context": context,
        "formulation": _redact_youtube_urls(text.strip())[:1000],
        "parser_live_output": parser_options[0],
        "parser_send_to_llm": parser_options[1],
        "llm_live_output": llm_options[0],
        "llm_send_to_llm": llm_options[1],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError as exc:
        LOGGER.warning("Could not record YouTube parser miss at %s: %s", path, exc)


def _youtube_parser_misses_path(instance_name: str, instances_dir: Path | None = None) -> Path:
    instance = instance_name.strip() or "default"
    return (instances_dir or _default_instances_dir()) / instance / "data" / YOUTUBE_PARSER_MISSES_FILENAME


def _redact_youtube_urls(text: str) -> str:
    return re.sub(r"https?://\S+", "<youtube-url>", text)


def _normalize_youtube_option_formulation(text: str) -> str:
    redacted = _redact_youtube_urls(text)
    normalized = re.sub(r"[_-]+", " ", redacted.casefold())
    return re.sub(r"\s+", " ", normalized).strip()


def _youtube_option_formulation_tokens(normalized_text: str) -> set[str]:
    stop_words = {
        "bitte",
        "mach",
        "mache",
        "das",
        "den",
        "die",
        "der",
        "ein",
        "eine",
        "einen",
        "mal",
        "versuch",
        "versuchs",
        "transkribiere",
        "transkribier",
        "transkribieren",
        "youtube",
        "video",
        "link",
        "url",
        "und",
        "oder",
        "mit",
        "ohne",
        "an",
        "ans",
        "zum",
        "zur",
        "in",
        "ins",
        "ja",
        "nein",
        "true",
        "false",
        "on",
        "off",
        "0",
        "1",
        "youtube-url",
    }
    return {
        token
        for token in re.findall(r"[a-zäöüß]+|[0-9]+", normalized_text)
        if len(token) >= 3 and token not in stop_words
    }


def _learned_youtube_formulation_matches(learned_tokens: set[str], candidate_tokens: set[str]) -> bool:
    if len(learned_tokens) < 3:
        return False
    return learned_tokens.issubset(candidate_tokens)


def _yes_no_value(value: str) -> bool:
    return value.casefold() in {"ja", "yes", "jup", "ok", "okay", "y", "true", "wahr", "an", "ein", "on", "1"}


def _build_youtube_pipeline_text(user_text: str, transcript: str, source: str, url: str) -> str:
    clipped_transcript = transcript
    if len(clipped_transcript) > YOUTUBE_TRANSCRIPT_MAX_PIPELINE_CHARS:
        clipped_transcript = clipped_transcript[:YOUTUBE_TRANSCRIPT_MAX_PIPELINE_CHARS].rstrip() + "\n[Transkript gekuerzt]"
    return (
        f"{user_text.strip()}\n\n"
        "YouTube-Transkript:\n"
        f"- Quelle: {url}\n"
        f"- Transkriptquelle: {source}\n"
        f"{clipped_transcript}"
    ).strip()


class YouTubeTranscriptError(RuntimeError):
    """Raised when a YouTube transcript cannot be produced locally."""

    def __init__(self, message: str, *, needs_local_transcription: bool = False) -> None:
        super().__init__(message)
        self.needs_local_transcription = needs_local_transcription


def transcribe_youtube_video(
    url: str,
    local_allowed: bool = True,
    live_callback=None,
    instance_name: str = "",
) -> tuple[str, str]:
    normalized_url = _validated_youtube_url(url)
    cached = _read_cached_youtube_transcript(normalized_url)
    if cached:
        return cached, "Cache"
    if shutil.which("yt-dlp") is None:
        raise YouTubeTranscriptError("yt-dlp ist nicht installiert.")

    with tempfile.TemporaryDirectory(prefix="telegram-bot-youtube-") as directory:
        workdir = Path(directory)
        subtitle_text = _download_youtube_subtitles(normalized_url, workdir, instance_name=instance_name)
        if subtitle_text:
            _write_cached_youtube_transcript(normalized_url, subtitle_text)
            return subtitle_text, "YouTube-Untertitel"
        if not local_allowed:
            raise YouTubeTranscriptError("keine YouTube-Untertitel gefunden.", needs_local_transcription=True)
        whisper_text = _transcribe_youtube_audio_with_whisper(
            normalized_url,
            workdir,
            live_callback=live_callback,
            instance_name=instance_name,
        )
        if whisper_text:
            _write_cached_youtube_transcript(normalized_url, whisper_text)
            return whisper_text, "lokales Whisper"
    raise YouTubeTranscriptError("kein Transkript erzeugt.")


def _extract_youtube_url(text: str) -> str:
    parts = text.split(maxsplit=1)
    search_text = parts[1] if len(parts) >= 2 and _normalize_command(text) in YOUTUBE_TRANSCRIPT_COMMANDS else text
    for candidate in re.findall(r"https?://\S+", search_text):
        try:
            return _validated_youtube_url(candidate.rstrip(".,;)>]\"'"))
        except YouTubeTranscriptError:
            continue
    return ""


def _has_youtube_transcript_intent(text: str) -> bool:
    normalized = text.casefold()
    normalized = normalized.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    normalized = re.sub(r"[_-]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    mentions_youtube = bool(re.search(r"\b(?:youtube|yt)\b|youtu\.be|youtube\.com", normalized))
    mentions_video = bool(re.search(r"\b(?:video|clip|aufnahme|recording)\b", normalized))
    mentions_transcript = bool(
        re.search(
            r"trans(?:krib|crib)|transcript|transkript|transkription|untertitel|abschrift|abschreib|abtippen|verschriftlich|mitschrift",
            normalized,
        )
    )
    mentions_text_output = bool(re.search(r"\b(?:text|texte|output|ausgabe|schrift|wortlaut)\b", normalized))
    if mentions_youtube and (mentions_transcript or mentions_text_output or mentions_video):
        return True
    if mentions_video and (mentions_transcript or mentions_text_output):
        return True
    if mentions_transcript and re.search(r"\b(?:dies(?:e[rsn]?|en)?|das|den|diese|diesen|scheiss|scheiß|mist|ding|teil)\b", normalized):
        return True
    return False


def _default_youtube_local_options(live_enabled: bool | None, llm_enabled: bool | None) -> tuple[bool, bool]:
    """Fall back to a local transcript-only job when the user gave no options."""
    return (live_enabled if live_enabled is not None else False, llm_enabled if llm_enabled is not None else False)


def _validated_youtube_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url.strip())
    host = parsed.netloc.casefold().removeprefix("www.")
    if parsed.scheme not in {"http", "https"} or host not in {"youtube.com", "m.youtube.com", "youtu.be", "youtube-nocookie.com"}:
        raise YouTubeTranscriptError("bitte eine gueltige YouTube-URL angeben.")
    return urllib.parse.urlunparse(parsed)


def _youtube_transcript_cache_dir() -> Path:
    return runtime_dir() / YOUTUBE_TRANSCRIPT_CACHE_DIRNAME


def _youtube_transcript_cache_path(url: str) -> Path:
    key = _youtube_video_cache_key(url)
    return _youtube_transcript_cache_dir() / f"{key}.txt"


def _youtube_video_cache_key(url: str) -> str:
    parsed = urllib.parse.urlparse(_validated_youtube_url(url))
    host = parsed.netloc.casefold().removeprefix("www.")
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/", maxsplit=1)[0]
        if video_id:
            return _safe_youtube_cache_key(video_id)
    query = urllib.parse.parse_qs(parsed.query)
    if query.get("v") and query["v"][0]:
        return _safe_youtube_cache_key(query["v"][0])
    parts = [part for part in parsed.path.split("/") if part]
    for marker in ("shorts", "embed", "live"):
        if marker in parts:
            index = parts.index(marker)
            if index + 1 < len(parts):
                return _safe_youtube_cache_key(parts[index + 1])
    digest = hashlib.sha256(urllib.parse.urlunparse(parsed._replace(query="", fragment="")).encode("utf-8")).hexdigest()
    return f"url-{digest[:32]}"


def _safe_youtube_cache_key(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
    return cleaned[:120] or "unknown"


def _read_cached_youtube_transcript(url: str) -> str:
    path = _youtube_transcript_cache_path(url)
    try:
        text = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    except OSError as exc:
        LOGGER.warning("Could not read YouTube transcript cache at %s: %s", path, exc)
        return ""
    return text


def _write_cached_youtube_transcript(url: str, transcript: str) -> None:
    text = transcript.strip()
    if not text:
        return
    path = _youtube_transcript_cache_path(url)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(text + "\n", encoding="utf-8")
        os.replace(tmp_path, path)
    except OSError as exc:
        LOGGER.warning("Could not write YouTube transcript cache at %s: %s", path, exc)
        with suppress(OSError):
            tmp_path.unlink()


def _download_youtube_subtitles(url: str, workdir: Path, instance_name: str = "") -> str:
    result = _run_local_command(
        [
            "yt-dlp",
            "--skip-download",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs",
            "en.*,de.*",
            "--convert-subs",
            "srt",
            "-o",
            "%(id)s.%(ext)s",
            url,
        ],
        workdir,
        YOUTUBE_TRANSCRIPT_TIMEOUT_SECONDS,
        instance_name=instance_name,
    )
    if result.returncode != 0 and not list(workdir.glob("*.srt")):
        LOGGER.debug("yt-dlp subtitle download failed: %s", result.stderr.strip())
    return _read_first_srt_as_text(workdir)


def _transcribe_youtube_audio_with_whisper(
    url: str,
    workdir: Path,
    live_callback=None,
    instance_name: str = "",
) -> str:
    audio_result = _run_local_command(
        ["yt-dlp", "-x", "--audio-format", "mp3", "-o", "youtube-audio.%(ext)s", url],
        workdir,
        YOUTUBE_TRANSCRIPT_TIMEOUT_SECONDS,
        instance_name=instance_name,
    )
    if audio_result.returncode != 0:
        raise YouTubeTranscriptError(f"Audio konnte nicht geladen werden: {_short_process_error(audio_result)}")

    audio_files = sorted(workdir.glob("youtube-audio*.mp3"))
    if not audio_files:
        raise YouTubeTranscriptError("Audio wurde nicht als MP3 erzeugt.")

    if _has_python_module("faster_whisper"):
        return _transcribe_audio_with_faster_whisper(
            audio_files[0],
            workdir,
            live_callback=live_callback,
            instance_name=instance_name,
        )
    if shutil.which("whisper") is None:
        raise YouTubeTranscriptError("keine YouTube-Untertitel gefunden und weder faster-whisper noch whisper ist installiert.")
    return _transcribe_audio_with_openai_whisper_cli(audio_files[0], workdir, instance_name=instance_name)


def _transcribe_audio_with_faster_whisper(
    audio_path: Path,
    workdir: Path,
    live_callback=None,
    instance_name: str = "",
) -> str:
    return _transcribe_audio_with_faster_whisper_model(
        audio_path,
        workdir,
        YOUTUBE_WHISPER_MODEL,
        live_callback=live_callback,
        instance_name=instance_name,
    )


def _transcribe_audio_with_faster_whisper_model(
    audio_path: Path,
    workdir: Path,
    model_name: str,
    live_callback=None,
    instance_name: str = "",
) -> str:
    code = """
import sys
from pathlib import Path
from faster_whisper import WhisperModel

audio_path = Path(sys.argv[1])
model_name = sys.argv[2]
compute_type = sys.argv[3]
cpu_threads = int(sys.argv[4])
model = WhisperModel(model_name, device="cpu", compute_type=compute_type, cpu_threads=cpu_threads, num_workers=1)
segments, _ = model.transcribe(str(audio_path))
for segment in segments:
    text = segment.text.strip()
    if text:
        print(text, flush=True)
"""
    command = [
        sys.executable,
        "-c",
        code,
        str(audio_path),
        model_name,
        YOUTUBE_FASTER_WHISPER_COMPUTE_TYPE,
        str(YOUTUBE_FASTER_WHISPER_CPU_THREADS),
    ]
    result = _run_local_command_streaming(
        command,
        workdir,
        YOUTUBE_WHISPER_TIMEOUT_SECONDS,
        line_callback=live_callback,
        instance_name=instance_name,
    )
    if result.returncode != 0:
        if result.returncode < 0:
            raise YouTubeTranscriptError(f"faster-whisper wurde abgebrochen ({_process_signal_name(result.returncode)}).")
        raise YouTubeTranscriptError(f"faster-whisper konnte nicht transkribieren: {_short_process_error(result)}")
    text = result.stdout.strip()
    if not text:
        raise YouTubeTranscriptError("faster-whisper hat kein Transkript erzeugt.")
    if live_callback is not None:
        live_callback("", force=True)
    return text


def _transcribe_audio_with_openai_whisper_cli(audio_path: Path, workdir: Path, instance_name: str = "") -> str:
    whisper_result = _run_local_command(
        [
            "whisper",
            str(audio_path),
            "--model",
            YOUTUBE_WHISPER_MODEL,
            "--language",
            "English",
            "--output_format",
            "srt",
            "--output_dir",
            str(workdir),
        ],
        workdir,
        YOUTUBE_WHISPER_TIMEOUT_SECONDS,
        instance_name=instance_name,
    )
    if whisper_result.returncode != 0:
        raise YouTubeTranscriptError(f"Whisper konnte nicht transkribieren: {_short_process_error(whisper_result)}")
    return _read_first_srt_as_text(workdir)


def _has_python_module(module_name: str) -> bool:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module_name}"],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _run_local_command(
    command: list[str],
    workdir: Path,
    timeout: int,
    instance_name: str = "",
) -> subprocess.CompletedProcess[str]:
    registry = _InstanceProcessRegistry(instance_name)
    process: subprocess.Popen[str] | None = None
    registry_start_time: int | None = None
    env = os.environ.copy()
    env.update(
        {
            "OMP_NUM_THREADS": str(YOUTUBE_FASTER_WHISPER_CPU_THREADS),
            "OPENBLAS_NUM_THREADS": str(YOUTUBE_FASTER_WHISPER_CPU_THREADS),
            "MKL_NUM_THREADS": str(YOUTUBE_FASTER_WHISPER_CPU_THREADS),
            "NUMEXPR_NUM_THREADS": str(YOUTUBE_FASTER_WHISPER_CPU_THREADS),
            "VECLIB_MAXIMUM_THREADS": str(YOUTUBE_FASTER_WHISPER_CPU_THREADS),
        }
    )
    try:
        process = subprocess.Popen(
            _lowest_priority_command(command),
            cwd=workdir,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            start_new_session=True,
        )
        registry_start_time = registry.register(process.pid)
        stdout, stderr = process.communicate(timeout=timeout)
        return subprocess.CompletedProcess(command, process.returncode or 0, stdout, stderr)
    except TimeoutError as exc:
        raise YouTubeTranscriptError(f"lokaler Prozess lief in ein Timeout: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        _terminate_process_group(process)
        raise YouTubeTranscriptError(f"lokaler Prozess lief laenger als {timeout} Sekunden.") from exc
    except OSError as exc:
        raise YouTubeTranscriptError(f"lokaler Prozess konnte nicht gestartet werden: {exc}") from exc
    finally:
        if process is not None and registry_start_time is not None:
            registry.unregister(process.pid, registry_start_time)


def _run_local_command_streaming(
    command: list[str],
    workdir: Path,
    timeout: int,
    line_callback=None,
    instance_name: str = "",
) -> subprocess.CompletedProcess[str]:
    registry = _InstanceProcessRegistry(instance_name)
    stdout_lines: list[str] = []
    stderr = ""
    start = time.monotonic()
    process: subprocess.Popen[str] | None = None
    registry_start_time: int | None = None
    pending_health_checks = list(YOUTUBE_TRANSCRIPTION_HEALTH_CHECK_SECONDS)
    try:
        env = os.environ.copy()
        env.update(
            {
                "OMP_NUM_THREADS": str(YOUTUBE_FASTER_WHISPER_CPU_THREADS),
                "OPENBLAS_NUM_THREADS": str(YOUTUBE_FASTER_WHISPER_CPU_THREADS),
                "MKL_NUM_THREADS": str(YOUTUBE_FASTER_WHISPER_CPU_THREADS),
                "NUMEXPR_NUM_THREADS": str(YOUTUBE_FASTER_WHISPER_CPU_THREADS),
                "VECLIB_MAXIMUM_THREADS": str(YOUTUBE_FASTER_WHISPER_CPU_THREADS),
            }
        )
        process = subprocess.Popen(
            _lowest_priority_command(command),
            cwd=workdir,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            start_new_session=True,
        )
        registry_start_time = registry.register(process.pid)
        assert process.stdout is not None
        while True:
            elapsed = time.monotonic() - start
            if pending_health_checks and elapsed >= pending_health_checks[0]:
                health_error = _transcription_process_health_error(process, registry_start_time)
                if health_error:
                    _terminate_process_group(process)
                    _, stderr = process.communicate()
                    raise YouTubeTranscriptError(
                        f"Transkriptionsprozess ist nach {int(pending_health_checks[0])} Sekunden nicht ok ({health_error}). Ich habe ihn beendet."
                    )
                pending_health_checks.pop(0)
            if elapsed > timeout:
                _terminate_process_group(process)
                _, stderr = process.communicate()
                raise YouTubeTranscriptError(f"lokaler Prozess lief laenger als {timeout} Sekunden.")
            ready, _, _ = select.select([process.stdout], [], [], 0.1)
            if ready:
                line = process.stdout.readline()
                if line:
                    stdout_lines.append(line)
                    if line_callback is not None:
                        line_callback(line)
                    continue
            if process.poll() is not None:
                break
        remaining_stdout, stderr = process.communicate(timeout=5)
        if remaining_stdout:
            stdout_lines.append(remaining_stdout)
            if line_callback is not None:
                for line in remaining_stdout.splitlines():
                    line_callback(line)
    except subprocess.TimeoutExpired:
        _terminate_process_group(process)
        _, stderr = process.communicate()
        raise YouTubeTranscriptError(f"lokaler Prozess lief laenger als {timeout} Sekunden.")
    finally:
        if process is not None and registry_start_time is not None:
            registry.unregister(process.pid, registry_start_time)
    returncode = process.returncode if process is not None and process.returncode is not None else 0
    return subprocess.CompletedProcess(command, returncode, "".join(stdout_lines), stderr)


def _terminate_process_group(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.pid <= 0:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        LOGGER.debug("Failed to terminate process group %s with SIGTERM.", process.pid)
        return
    for _ in range(30):
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        except OSError:
            return
        time.sleep(0.1)
    with suppress(ProcessLookupError, OSError):
        os.killpg(process.pid, signal.SIGKILL)


def _transcription_process_health_error(process: subprocess.Popen[str] | None, expected_start_time: int | None) -> str:
    if process is None or process.pid <= 0:
        return "kein Prozess"
    returncode = process.poll()
    if returncode is not None:
        return f"Prozess ist bereits beendet, exit={returncode}"
    if expected_start_time is not None:
        actual_start_time = _read_process_start_time(process.pid)
        if actual_start_time is None:
            return "Prozess-Startzeit nicht mehr lesbar"
        if actual_start_time != expected_start_time:
            return "PID wurde wiederverwendet"
    process_state = _read_process_state(process.pid)
    if process_state and process_state.startswith("Z"):
        return "Prozess ist Zombie"
    return ""


def _read_process_state(pid: int) -> str:
    try:
        for line in Path(f"/proc/{pid}/status").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("State:"):
                return line.split(":", maxsplit=1)[1].strip()
    except OSError:
        return ""
    return ""


def _read_process_start_time(pid: int) -> int | None:
    if pid <= 0:
        return None
    stat_path = Path("/proc") / str(pid) / "stat"
    try:
        stat_text = stat_path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        closing = stat_text.rindex(")")
        stat_fields = stat_text[closing + 2 :].split()
        start_time_field_index = 19  # field 22 in /proc/<pid>/stat, after pid+comm
        return int(stat_fields[start_time_field_index])
    except (ValueError, IndexError):
        return None


def _lowest_priority_command(command: list[str]) -> list[str]:
    wrapped = list(command)
    if shutil.which("ionice") is not None:
        wrapped = ["ionice", "-c", "3", *wrapped]
    if shutil.which("nice") is not None:
        wrapped = ["nice", "-n", str(YOUTUBE_TRANSCRIPT_NICE_LEVEL), *wrapped]
    return wrapped


def _read_first_srt_as_text(workdir: Path) -> str:
    for path in sorted(workdir.glob("*.srt")):
        text = _srt_to_plain_text(path.read_text(encoding="utf-8", errors="replace"))
        if text:
            return text
    return ""


def _srt_to_plain_text(srt_text: str) -> str:
    lines: list[str] = []
    previous = ""
    for raw_line in srt_text.splitlines():
        line = raw_line.strip()
        if not line or line.isdigit() or "-->" in line:
            continue
        line = re.sub(r"<[^>]+>", "", line).strip()
        if not line or line == previous:
            continue
        lines.append(line)
        previous = line
    return "\n".join(lines).strip()


def _short_process_error(result: subprocess.CompletedProcess[str]) -> str:
    text = _filter_process_noise(result.stderr or result.stdout or "").strip()
    if not text:
        return f"Exitcode {result.returncode}"
    return text[-500:]


def _filter_process_noise(text: str) -> str:
    lines = []
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if "multiprocessing/resource_tracker.py" in stripped:
            continue
        if "resource_tracker:" in stripped and "leaked semaphore objects" in stripped:
            continue
        if stripped.startswith("warnings.warn("):
            continue
        lines.append(line)
    return "\n".join(lines)


def _process_signal_name(returncode: int) -> str:
    signal_number = abs(int(returncode))
    try:
        return signal.Signals(signal_number).name
    except ValueError:
        return f"Signal {signal_number}"
