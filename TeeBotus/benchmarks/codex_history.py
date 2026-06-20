from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from TeeBotus.admin.codex_history import import_codex_session_roots, watch_codex_session_roots
from TeeBotus.benchmarks.core import BenchmarkResult, result
from TeeBotus.codex_history_systemd import render_codex_history_collector_timer_units
from TeeBotus.runtime.accounts import (
    CODEX_HISTORY_OUTBOX_FILENAME,
    INSTANCE_STATE_ACCOUNT_ID,
    AccountStore,
    StaticSecretProvider,
)


def benchmark_codex_history_collector_timer_render(*, iterations: int) -> BenchmarkResult:
    render_count = max(1, int(iterations or 0))
    with tempfile.TemporaryDirectory(prefix="teebotus-bench-codex-timer-") as tmp:
        root = Path(tmp)
        latest: Any = None

        def _render() -> None:
            nonlocal latest
            for _ in range(render_count):
                latest = render_codex_history_collector_timer_units(
                    repo_root=root / "repo",
                    run_user="",
                    sessions_roots=(root / "sessions",),
                    interval="5min",
                    event_mode="snapshot",
                    poll_interval_seconds=0,
                )

        elapsed_ms = _timed_ms(_render)
        service_text = getattr(latest, "service_text", "")
        timer_text = getattr(latest, "timer_text", "")
        ok = (
            "Type=oneshot" in service_text
            and "--once" in service_text
            and "Restart=" not in service_text
            and "OnUnitActiveSec=5min" in timer_text
        )
        return result(
            name="codex_history_collector_timer_render",
            category="codex_history",
            iterations=render_count,
            total_ms=elapsed_ms,
            ok=bool(ok),
            errors=0 if ok else 1,
            payload_bytes=len(service_text) + len(timer_text),
            index_bytes=0,
            note="systemd collector timer render",
            details={
                "timer_name": getattr(latest, "timer_name", ""),
                "service_name": getattr(latest, "service_name", ""),
                "interval": "5min",
                "event_mode": "snapshot",
                "network_calls": 0,
            },
        )


def benchmark_codex_history_session_importer(*, iterations: int) -> BenchmarkResult:
    session_count = max(1, int(iterations or 0))
    with tempfile.TemporaryDirectory(prefix="teebotus-bench-codex-import-") as tmp:
        root = Path(tmp)
        repo_root = _setup_benchmark_repo(root / "repo")
        sessions_root = root / "sessions"
        payload_bytes = 0
        for index in range(session_count):
            path = _write_codex_session_file(
                sessions_root / f"session-{index:06d}.jsonl",
                repo_root=repo_root,
                session_id=f"bench-import-{index:06d}",
                turn_id=f"turn-import-{index:06d}",
                final_text=f"Codex benchmark import {index}\n- pytest tests/test_codex_history.py\n- Ergebnis: Benchmark Import",
            )
            payload_bytes += path.stat().st_size
        store = AccountStore(root / "accounts", "Bench", StaticSecretProvider(b"i" * 32))
        report: dict[str, Any] = {}

        def _import() -> None:
            report.update(import_codex_session_roots(store, (sessions_root,), limit=session_count))

        elapsed_ms = _timed_ms(_import)
        status_counts = report.get("status_counts", {})
        outbox_path = store.account_dir(INSTANCE_STATE_ACCOUNT_ID) / CODEX_HISTORY_OUTBOX_FILENAME
        imported = int(status_counts.get("imported", 0))
        ok = imported == session_count and outbox_path.exists()
        return result(
            name="codex_history_session_importer",
            category="codex_history",
            iterations=session_count,
            total_ms=elapsed_ms,
            ok=bool(ok),
            errors=0 if ok else 1,
            payload_bytes=payload_bytes,
            index_bytes=outbox_path.stat().st_size if outbox_path.exists() else 0,
            note="import_codex_session_roots batch",
            details={
                "session_count": session_count,
                "status_counts": status_counts,
                "limit": session_count,
                "watch_mode": "import",
                "repo_root": str(repo_root),
                "sessions_root": str(sessions_root),
                "import_calls": 1,
            },
        )


def benchmark_codex_history_watcher_poll_loop(*, iterations: int) -> BenchmarkResult:
    session_count = max(1, int(iterations or 0))
    with tempfile.TemporaryDirectory(prefix="teebotus-bench-codex-watch-") as tmp:
        root = Path(tmp)
        repo_root = _setup_benchmark_repo(root / "repo")
        sessions_root = root / "sessions"
        poll_interval_seconds = 0.001
        session_file = sessions_root / "session.jsonl"
        _write_codex_session_file(
            session_file,
            repo_root=repo_root,
            session_id="bench-watch-000000",
            turn_id="turn-watch-000000",
            final_text="Codex benchmark watch\n- Erstlauf",
        )

        store = AccountStore(root / "accounts", "Bench", StaticSecretProvider(b"w" * 32))
        wrote = {"count": 1}

        def _refresh_session_file(_: float) -> None:
            if wrote["count"] >= session_count:
                return
            index = wrote["count"]
            _write_codex_session_file(
                session_file,
                repo_root=repo_root,
                session_id=f"bench-watch-{index:06d}",
                turn_id=f"turn-watch-{index:06d}",
                final_text=f"Codex benchmark watch\n- Lauf {index}",
            )
            wrote["count"] += 1

        watch_status_counts: dict[str, int] = {}

        def _accumulate_status_counts(scan_report: Mapping[str, Any]) -> None:
            current_counts = scan_report.get("status_counts")
            if not isinstance(current_counts, Mapping):
                return
            for key, value in current_counts.items():
                if isinstance(value, int):
                    watch_status_counts[str(key)] = watch_status_counts.get(str(key), 0) + int(value)

        elapsed_ms = _timed_ms(
            lambda: watch_codex_session_roots(
                store,
                (sessions_root,),
                poll_interval_seconds=poll_interval_seconds,
                max_iterations=session_count,
                follow=False,
                event_mode="snapshot",
                limit=session_count,
                sleep=_refresh_session_file,
                post_scan=_accumulate_status_counts,
            )
        )
        payload_bytes = sum(path.stat().st_size for path in sessions_root.glob("*.jsonl") if path.is_file())
        outbox_path = store.account_dir(INSTANCE_STATE_ACCOUNT_ID) / CODEX_HISTORY_OUTBOX_FILENAME
        status_counts = dict(watch_status_counts)
        outbox_size = outbox_path.stat().st_size if outbox_path.exists() else 0
        imported = int(status_counts.get("imported", 0))
        ok = imported == wrote["count"] and outbox_size > 0
        return result(
            name="codex_history_watcher_poll_loop",
            category="codex_history",
            iterations=session_count,
            total_ms=elapsed_ms,
            ok=bool(ok),
            errors=0 if ok else 1,
            payload_bytes=payload_bytes,
            index_bytes=outbox_size,
            note="watch_codex_session_roots snapshot",
            details={
                "session_count": session_count,
                "status_counts": status_counts,
                "limit": session_count,
                "event_mode": "snapshot",
                "repo_root": str(repo_root),
                "sessions_root": str(sessions_root),
                "poll_interval_seconds": poll_interval_seconds,
                "iterations_requested": session_count,
                "files_written": wrote["count"],
            },
        )


def _write_codex_session_file(
    path: Path,
    *,
    repo_root: Path,
    session_id: str,
    turn_id: str,
    final_text: str,
) -> Path:
    rows: list[dict[str, Any]] = [
        {"type": "session_meta", "payload": {"id": session_id, "cwd": str(repo_root)}},
        {"type": "turn_context", "payload": {"turn_id": turn_id}},
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": final_text}],
            },
        },
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return path


def _setup_benchmark_repo(repo_root: Path) -> Path:
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "codex-history-benchmark"',
                'version = "3.0.0"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    return repo_root


def _timed_ms(func: Callable[[], Any]) -> float:
    start = time.perf_counter()
    func()
    return (time.perf_counter() - start) * 1000


__all__ = [
    "benchmark_codex_history_collector_timer_render",
    "benchmark_codex_history_session_importer",
    "benchmark_codex_history_watcher_poll_loop",
]
