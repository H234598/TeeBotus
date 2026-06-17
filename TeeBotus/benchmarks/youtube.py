from __future__ import annotations

import json
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from TeeBotus.benchmarks.core import BenchmarkResult, result
from TeeBotus.core.youtube import YouTubeTranscriptError, _has_youtube_transcript_intent, _parse_youtube_local_options
import TeeBotus.core.youtube as youtube_module
from TeeBotus.instructions import BotInstructions
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, signal_identity_key
from TeeBotus.runtime.engine import TeeBotusEngine
from TeeBotus.runtime.events import IncomingEvent
import TeeBotus.runtime.engine as engine_module


def benchmark_youtube_parser(*, iterations: int) -> BenchmarkResult:
    samples = [
        "transkribiere dieses Video: https://youtu.be/dQw4w9WgXcQ",
        "/youtube_transcript https://youtube.com/watch?v=dQw4w9WgXcQ",
        "yt output bitte, live off llm off https://youtu.be/dQw4w9WgXcQ",
    ]

    def parse_all() -> int:
        hits = 0
        for sample in samples:
            hits += int(_has_youtube_transcript_intent(sample))
            _parse_youtube_local_options(sample)
        return hits

    hit_count = 0
    timings = []
    for _ in range(iterations):
        start = time.perf_counter()
        hit_count += parse_all()
        timings.append((time.perf_counter() - start) * 1000)
    return result(
        name="youtube_parser_local",
        category="transcription_youtube",
        iterations=iterations * len(samples),
        total_ms=sum(timings),
        payload_bytes=sum(len(sample.encode("utf-8")) for sample in samples),
        index_bytes=len(json.dumps({"samples": len(samples)}, ensure_ascii=False).encode("utf-8")),
        details={"intent_hits": hit_count, "sample_count": len(samples), "median_batch_ms": statistics.median(timings)},
    )


def benchmark_youtube_local_job_queue(*, iterations: int) -> BenchmarkResult:
    original_transcribe = engine_module.transcribe_youtube_video
    transcribe_calls: list[dict[str, Any]] = []
    dispatched_texts: list[str] = []
    started_jobs = 0

    class FakeRunner:
        def submit(self, callback: Callable[[], Any]) -> object:
            nonlocal started_jobs
            started_jobs += 1
            callback()
            return object()

    class CountingLLMClient:
        def __init__(self) -> None:
            self.calls = 0

        def create_reply(self, *_args: Any, **_kwargs: Any) -> Any:
            self.calls += 1
            raise AssertionError("benchmark must not call LLM")

    def fake_transcribe(_url: str, **kwargs: Any) -> tuple[str, str]:
        transcribe_calls.append(dict(kwargs))
        if kwargs.get("local_allowed") is False:
            raise YouTubeTranscriptError("keine YouTube-Untertitel gefunden.", needs_local_transcription=True)
        return "Lokales Benchmark-Transkript.", "lokales Whisper"

    try:
        engine_module.transcribe_youtube_video = fake_transcribe
        with tempfile.TemporaryDirectory(prefix="teebotus-bench-youtube-engine-") as tmp:
            store = AccountStore(Path(tmp) / "accounts", "Bench", StaticSecretProvider(b"y" * 32))
            identity = signal_identity_key(source_uuid="bench-youtube")
            client = CountingLLMClient()
            engine = TeeBotusEngine(
                account_store=store,
                instructions=BotInstructions(openai_enabled=True, youtube_option_llm_fallback=False),
                openai_client=client,
                youtube_job_runner=FakeRunner(),
                background_action_dispatcher=lambda _event, actions: dispatched_texts.extend(
                    str(getattr(action, "text", "")) for action in actions if getattr(action, "text", "")
                ),
            )

            def run_once(index: int) -> None:
                event = IncomingEvent(
                    event_id=f"signal:{index}",
                    instance="Bench",
                    channel="signal",
                    adapter_slot=1,
                    account_id="",
                    identity_key=identity,
                    chat_id="chat-1",
                    chat_type="private",
                    sender_id=identity,
                    sender_name=identity,
                    text="/youtube_transcript https://youtu.be/dQw4w9WgXcQ mach bitte die passende variante",
                    message_ref=str(index),
                )
                engine.process(event)

            timings = [_timed_ms(lambda index=index: run_once(index)) for index in range(iterations)]
            expected_transcribe_calls = iterations * 2
            errors = 0
            if client.calls:
                errors += client.calls
            if len(transcribe_calls) != expected_transcribe_calls:
                errors += 1
            if started_jobs != iterations:
                errors += 1
            if len(dispatched_texts) != iterations:
                errors += 1
            if not all("Lokales Benchmark-Transkript." in text for text in dispatched_texts):
                errors += 1
            return result(
                name="youtube_local_job_queue_no_llm",
                category="transcription_youtube",
                iterations=iterations,
                total_ms=sum(timings),
                ok=errors == 0,
                errors=errors,
                payload_bytes=sum(len(text.encode("utf-8")) for text in dispatched_texts),
                note="fake_local_transcription_no_provider_calls",
                details={
                    "started_jobs": started_jobs,
                    "background_dispatches": len(dispatched_texts),
                    "transcribe_calls": len(transcribe_calls),
                    "llm_calls": client.calls,
                    "median_engine_ms": statistics.median(timings),
                    "network_calls": 0,
                },
            )
    finally:
        engine_module.transcribe_youtube_video = original_transcribe


def benchmark_youtube_local_pipeline_cache(*, iterations: int) -> BenchmarkResult:
    original_which = youtube_module.shutil.which
    original_download_subtitles = youtube_module._download_youtube_subtitles
    original_transcribe_whisper = youtube_module._transcribe_youtube_audio_with_whisper
    original_runtime_dir = youtube_module.runtime_dir
    subtitle_calls = 0
    whisper_calls = 0
    live_chunks = 0
    transcripts: list[str] = []
    sources: list[str] = []

    def fake_which(command: str) -> str | None:
        if command == "yt-dlp":
            return "/usr/bin/yt-dlp"
        return original_which(command)

    def fake_download_subtitles(_url: str, _workdir: Path, instance_name: str = "") -> str:
        nonlocal subtitle_calls
        subtitle_calls += 1
        return ""

    def fake_transcribe_whisper(_url: str, _workdir: Path, live_callback=None, instance_name: str = "") -> str:
        nonlocal whisper_calls, live_chunks
        whisper_calls += 1
        if callable(live_callback):
            live_callback(f"Benchmark-Chunk {whisper_calls}")
            live_chunks += 1
        return f"Lokales Whisper Benchmark Transkript {whisper_calls}."

    try:
        with tempfile.TemporaryDirectory(prefix="teebotus-bench-youtube-pipeline-") as tmp:
            root = Path(tmp)
            youtube_module.shutil.which = fake_which
            youtube_module._download_youtube_subtitles = fake_download_subtitles
            youtube_module._transcribe_youtube_audio_with_whisper = fake_transcribe_whisper
            youtube_module.runtime_dir = lambda: root / "runtime"
            live_events: list[str] = []
            pipeline_timings = []
            cache_timings = []
            for index in range(iterations):
                url = f"https://youtube.com/watch?v=bench{index:04d}"
                pipeline_timings.append(
                    _timed_ms(
                        lambda url=url: _collect_youtube_transcript(
                            url,
                            transcripts=transcripts,
                            sources=sources,
                            live_events=live_events,
                        )
                    )
                )
                cache_timings.append(
                    _timed_ms(
                        lambda url=url: _collect_youtube_transcript(
                            url,
                            transcripts=transcripts,
                            sources=sources,
                            live_events=live_events,
                        )
                    )
                )
            cache_dir = root / "runtime" / "youtube_transcripts"
            cache_files = sorted(cache_dir.glob("*.txt")) if cache_dir.exists() else []
            cache_bytes = sum(path.stat().st_size for path in cache_files)
            whisper_sources = sources[0::2]
            cache_sources = sources[1::2]
            errors = 0
            if subtitle_calls != iterations:
                errors += 1
            if whisper_calls != iterations:
                errors += 1
            if len(cache_files) != iterations:
                errors += 1
            if whisper_sources != ["lokales Whisper"] * iterations:
                errors += 1
            if cache_sources != ["Cache"] * iterations:
                errors += 1
            if live_chunks != iterations or len(live_events) != iterations:
                errors += 1
            return result(
                name="youtube_local_pipeline_cache_no_openai",
                category="transcription_youtube",
                iterations=iterations * 2,
                total_ms=sum(pipeline_timings) + sum(cache_timings),
                ok=errors == 0,
                errors=errors,
                payload_bytes=sum(len(text.encode("utf-8")) for text in transcripts),
                index_bytes=cache_bytes,
                note="fake_yt_dlp_and_whisper_cache_no_provider_calls",
                details={
                    "subtitle_attempts": subtitle_calls,
                    "whisper_calls": whisper_calls,
                    "cache_reads": cache_sources.count("Cache"),
                    "cache_files": len(cache_files),
                    "live_chunks": live_chunks,
                    "median_pipeline_ms": statistics.median(pipeline_timings) if pipeline_timings else 0.0,
                    "median_cache_ms": statistics.median(cache_timings) if cache_timings else 0.0,
                    "openai_calls": 0,
                    "network_calls": 0,
                },
            )
    finally:
        youtube_module.shutil.which = original_which
        youtube_module._download_youtube_subtitles = original_download_subtitles
        youtube_module._transcribe_youtube_audio_with_whisper = original_transcribe_whisper
        youtube_module.runtime_dir = original_runtime_dir


def _collect_youtube_transcript(url: str, *, transcripts: list[str], sources: list[str], live_events: list[str]) -> None:
    transcript, source = youtube_module.transcribe_youtube_video(
        url,
        local_allowed=True,
        live_callback=lambda chunk: live_events.append(str(chunk)),
        instance_name="Bench",
    )
    transcripts.append(transcript)
    sources.append(source)


def _timed_ms(func: Callable[[], Any]) -> float:
    start = time.perf_counter()
    func()
    return (time.perf_counter() - start) * 1000


__all__ = [
    "benchmark_youtube_local_job_queue",
    "benchmark_youtube_local_pipeline_cache",
    "benchmark_youtube_parser",
]
