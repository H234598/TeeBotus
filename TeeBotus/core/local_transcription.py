from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from TeeBotus.core.youtube import (
    YOUTUBE_WHISPER_TIMEOUT_SECONDS,
    _has_python_module,
    _read_first_srt_as_text,
    _run_local_command,
    _transcribe_audio_with_faster_whisper_model,
)


class LocalTranscriptionError(RuntimeError):
    """Raised when a local audio transcription backend cannot produce text."""


@dataclass(frozen=True)
class LocalTranscriptionHealth:
    instance_name: str
    ok: bool
    backend: str
    model: str
    engine: str = ""
    error: str = ""


def check_local_transcription_backend(instance_name: str, instructions: object) -> LocalTranscriptionHealth | None:
    backend = str(getattr(instructions, "openai_transcription_backend", "openai") or "openai").strip().casefold()
    if backend != "local":
        return None
    model = str(getattr(instructions, "local_transcription_model", "") or "tiny").strip() or "tiny"
    if _has_python_module("faster_whisper"):
        return LocalTranscriptionHealth(instance_name, True, backend, model, engine="faster-whisper")
    whisper_path = shutil.which("whisper")
    if whisper_path:
        return LocalTranscriptionHealth(instance_name, True, backend, model, engine=whisper_path)
    return LocalTranscriptionHealth(instance_name, False, backend, model, error="weder faster-whisper noch whisper ist lokal installiert")


def transcribe_local_audio(
    audio: bytes,
    filename: str,
    *,
    model: str = "tiny",
    language: str = "",
    instance_name: str = "",
) -> str:
    if not isinstance(audio, bytes) or not audio:
        raise LocalTranscriptionError("lokale Transkription bekam keine Audiodaten")
    suffix = Path(str(filename or "audio.ogg")).suffix or ".ogg"
    with tempfile.TemporaryDirectory(prefix="teebotus-local-transcription-") as directory:
        workdir = Path(directory)
        audio_path = workdir / f"voice{suffix}"
        audio_path.write_bytes(audio)
        if _has_python_module("faster_whisper"):
            return _transcribe_audio_with_faster_whisper_model(
                audio_path,
                workdir,
                str(model or "tiny").strip() or "tiny",
                instance_name=instance_name,
            )
        if shutil.which("whisper") is None:
            raise LocalTranscriptionError("weder faster-whisper noch whisper ist lokal installiert")
        return _transcribe_audio_with_whisper_cli(
            audio_path,
            workdir,
            model=str(model or "tiny").strip() or "tiny",
            language=language,
            instance_name=instance_name,
        )


def _transcribe_audio_with_whisper_cli(
    audio_path: Path,
    workdir: Path,
    *,
    model: str,
    language: str,
    instance_name: str = "",
) -> str:
    command = [
        "whisper",
        str(audio_path),
        "--model",
        model,
        "--output_format",
        "srt",
        "--output_dir",
        str(workdir),
    ]
    normalized_language = str(language or "").strip()
    if normalized_language:
        command.extend(["--language", normalized_language])
    result = _run_local_command(command, workdir, YOUTUBE_WHISPER_TIMEOUT_SECONDS, instance_name=instance_name)
    if result.returncode != 0:
        raise LocalTranscriptionError(_short_local_process_error(result.stderr))
    text = _read_first_srt_as_text(workdir)
    if not text:
        raise LocalTranscriptionError("lokales Whisper hat kein Transkript erzeugt")
    return text


def _short_local_process_error(stderr: str) -> str:
    text = " ".join(str(stderr or "").split())
    if not text:
        return "lokale Transkription fehlgeschlagen"
    return text[:400]
