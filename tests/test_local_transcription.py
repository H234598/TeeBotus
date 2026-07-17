from __future__ import annotations

import json
import subprocess
from pathlib import Path

import TeeBotus.core.local_transcription as local_transcription
import TeeBotus.core.youtube as youtube


def test_python_module_probe_is_cached(monkeypatch) -> None:
    calls = []

    class Result:
        returncode = 0

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return Result()

    monkeypatch.setattr(youtube.subprocess, "run", fake_run)
    youtube._has_python_module.cache_clear()

    assert youtube._has_python_module("faster_whisper") is True
    assert youtube._has_python_module("faster_whisper") is True
    assert len(calls) == 1


def test_local_transcription_passes_language_to_faster_whisper(monkeypatch) -> None:
    calls: dict[str, object] = {}

    monkeypatch.setattr(local_transcription, "_has_python_module", lambda name: name == "faster_whisper")

    def fake_transcribe(audio_path, workdir, model_name, *, language="", instance_name=""):
        calls.update(
            {
                "audio_path": audio_path,
                "workdir": workdir,
                "model_name": model_name,
                "language": language,
                "instance_name": instance_name,
            }
        )
        return "deutsches Transkript"

    monkeypatch.setattr(local_transcription, "_transcribe_audio_with_faster_whisper_model", fake_transcribe)

    result = local_transcription.transcribe_local_audio(
        b"audio",
        "voice.ogg",
        model="small",
        language="de",
        instance_name="Depressionsbot",
    )

    assert result == "deutsches Transkript"
    assert calls["model_name"] == "small"
    assert calls["language"] == "de"
    assert calls["instance_name"] == "Depressionsbot"
    assert isinstance(calls["audio_path"], Path)


def test_faster_whisper_subprocess_receives_language(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_run(command, workdir, timeout, *, line_callback=None, instance_name=""):
        captured.update(
            {
                "command": command,
                "workdir": workdir,
                "timeout": timeout,
                "line_callback": line_callback,
                "instance_name": instance_name,
            }
        )
        return subprocess.CompletedProcess(command, 0, "transcript\n", "")

    monkeypatch.setattr(youtube, "_run_local_command_streaming", fake_run)
    audio_path = tmp_path / "voice.ogg"
    audio_path.write_bytes(b"audio")

    result = youtube._transcribe_audio_with_faster_whisper_model(
        audio_path,
        tmp_path,
        "small",
        language="de",
        instance_name="Depressionsbot",
    )

    command = captured["command"]
    assert result == "transcript"
    assert isinstance(command, list)
    assert command[-1] == "de"
    assert "language = sys.argv[5].strip()" in command[2]
    assert 'transcribe_kwargs = {"language": language} if language else {}' in command[2]
    assert captured["instance_name"] == "Depressionsbot"


def test_youtube_whisper_cli_does_not_force_english(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_run(command, workdir, timeout, *, instance_name=""):
        captured.update({"command": command, "workdir": workdir, "timeout": timeout, "instance_name": instance_name})
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(youtube, "_run_local_command", fake_run)
    monkeypatch.setattr(youtube, "_read_first_srt_as_text", lambda _workdir: "deutsches Transkript")
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"audio")

    result = youtube._transcribe_audio_with_openai_whisper_cli(audio_path, tmp_path, instance_name="Demo")

    assert result == "deutsches Transkript"
    command = captured["command"]
    assert isinstance(command, list)
    assert "--language" not in command
    assert captured["instance_name"] == "Demo"


def test_youtube_parser_miss_write_uses_process_lock(tmp_path: Path, monkeypatch) -> None:
    calls: list[int] = []
    original_flock = youtube.fcntl.flock if youtube.fcntl is not None else None

    def observe_flock(*args):
        calls.append(args[1])
        assert original_flock is not None
        return original_flock(*args)

    if original_flock is not None:
        monkeypatch.setattr(youtube.fcntl, "flock", observe_flock)

    youtube._record_youtube_parser_miss(
        "Demo",
        "Bitte transkribiere https://youtu.be/example",
        (None, True),
        (False, True),
        "test",
        instances_dir=tmp_path / "instances",
    )

    miss_path = tmp_path / "instances" / "Demo" / "data" / youtube.YOUTUBE_PARSER_MISSES_FILENAME
    assert json.loads(miss_path.read_text(encoding="utf-8"))["context"] == "test"
    if original_flock is not None:
        assert calls == [youtube.fcntl.LOCK_EX, youtube.fcntl.LOCK_UN]
