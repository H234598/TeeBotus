from __future__ import annotations

import json
import logging
import sqlite3
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from scripts.check_adapter_deps import (
    LOCKFILE,
    BAD_LITELLM_VERSIONS,
    _check_pyproject_plan2_contract,
    _min_safe_litellm_version,
    _read_pins,
    _version_tuple,
)
from TeeBotus.benchmarks.core import BenchmarkResult, result
from TeeBotus.core.status import account_identity_health_lines, account_memory_index_health_lines, account_secret_health_lines
from TeeBotus.instructions import BotInstructions
from TeeBotus.llm.profiles import select_llm_route
from TeeBotus.runtime.accounts import (
    ACCOUNT_KEYRING_FILENAME,
    ACCOUNT_MEMORY_KEY_PURPOSE,
    INSTANCE_MAPPING_KEY_PURPOSE,
    INSTANCE_PEPPER_PURPOSE,
    AccountStore,
    StaticSecretProvider,
    _instance_secret_fingerprint,
    matrix_identity_key,
    signal_identity_key,
    telegram_identity_key,
    utc_now,
)
from TeeBotus.runtime.sqlite_memory import SQLiteAccountMemoryBackend, SQLiteMemoryConfig
from TeeBotus.runtime.bibliothekar_service import check_bibliothekar_service
from TeeBotus.runtime.config import build_runtime_config
from TeeBotus.runtime.memory_fallback import WarningFallbackAccountMemoryBackend


def benchmark_status_doctor(*, iterations: int) -> BenchmarkResult:
    with tempfile.TemporaryDirectory(prefix="teebotus-bench-status-") as tmp:
        root = Path(tmp)
        instances_dir = root / "instances"
        instance_dir = instances_dir / "Bench"
        instance_dir.mkdir(parents=True)
        (instance_dir / "Bot_Verhalten.md").write_text(
            "## LLM\n- enabled: true\n- profile: local_ollama\n\n## Bibliothekar\n- enabled: true\n- backend: local\n",
            encoding="utf-8",
        )
        secret_provider = StaticSecretProvider(b"x" * 32)
        account_store = AccountStore(instance_dir / "data" / "accounts", "Bench", secret_provider=secret_provider)
        account_id = account_store.resolve_or_create_account(telegram_identity_key(42), display_label="Bench")
        _registered_account_id, account_secret = account_store.register_account(account_id)
        account_store.link_identity(signal_identity_key(source_uuid="bench-signal-uuid"), account_id, account_secret, display_label="Bench Signal")
        account_store.link_identity(matrix_identity_key("@bench:example"), account_id, account_secret, display_label="Bench Matrix")
        memory_id = account_store.append_structured_memory_entry(
            account_id,
            {
                "kind": "observation",
                "memory_type": "episodic",
                "user_text": "Benchmark Memory",
                "bot_text": "Benchmark Antwort",
                "importance": 0.5,
                "salience": 0.5,
            },
        )
        memory_id = str(memory_id or "")
        _write_static_secret_manifest(instance_dir / "data" / "accounts", instance_name="Bench", secret=b"x" * 32)
        env = {
            "TEEBOTUS_INSTANCES_DIR": str(instances_dir),
            "TEEBOTUS_INSTANCE": "Bench",
            "TELEGRAM_BOT_TOKEN_BENCH": "telegram-token",
            "SIGNAL_BOT_SERVICE_BENCH": "http://127.0.0.1:8080",
            "SIGNAL_BOT_PHONE_NUMBER_BENCH": "+491",
            "MATRIX_BOT_HOMESERVER_BENCH": "https://matrix.example",
            "MATRIX_BOT_USER_ID_BENCH": "@bench:example",
            "MATRIX_BOT_ACCESS_TOKEN_BENCH": "matrix-token",
            "TEEBOTUS_LLM_PROFILE_BENCH": "local_ollama",
        }
        instructions = BotInstructions(bibliothekar_backend="local")
        health_timings = [_timed_ms(lambda: check_bibliothekar_service("Bench", instances_dir, instructions)) for _ in range(iterations)]
        config_results = []
        config_timings = [
            _timed_ms(lambda: config_results.append(build_runtime_config(env=env, cli_channels="telegram,signal,matrix")))
            for _ in range(iterations)
        ]
        pins = _read_pins(LOCKFILE)
        dependency_checks = []
        dependency_timings = [
            _timed_ms(
                lambda: dependency_checks.extend(
                    [
                        _check_pyproject_plan2_contract(),
                        _benchmark_litellm_pin_guard(pins["litellm"]),
                    ]
                )
            )
            for _ in range(iterations)
        ]
        account_crypto_lines: list[str] = []
        account_memory_lines: list[str] = []
        account_identity_lines: list[str] = []
        account_health_timings = [
            _timed_ms(
                lambda: (
                    account_crypto_lines.extend(
                        account_secret_health_lines(instance_name="Bench", project_root=root, secret_provider=secret_provider)
                    ),
                    account_memory_lines.extend(
                        account_memory_index_health_lines(instance_name="Bench", project_root=root, secret_provider=secret_provider)
                    ),
                    account_identity_lines.extend(
                        account_identity_health_lines(
                            instance_name="Bench",
                            project_root=root,
                            env=env,
                            runtime_channels=("telegram", "signal", "matrix"),
                            secret_provider=secret_provider,
                        )
                    ),
                )
            )
            for _ in range(iterations)
        ]
        latest_config = config_results[-1] if config_results else None
        latest_health = check_bibliothekar_service("Bench", instances_dir, instructions)
        latest_dependency_checks = dependency_checks[-2:] if len(dependency_checks) >= 2 else dependency_checks
        latest_account_crypto_lines = account_crypto_lines[-1:] if account_crypto_lines else []
        latest_account_memory_lines = account_memory_lines[-1:] if account_memory_lines else []
        latest_account_identity_lines = account_identity_lines[-1:] if account_identity_lines else []
        account_crypto_ok = any(line.startswith("account_crypto=Bench status=ok") for line in latest_account_crypto_lines)
        account_memory_ok = any(line.startswith(f"account_memory=Bench/{account_id} status=ok") for line in latest_account_memory_lines)
        account_identity_ok = any(line.startswith("account_identity=Bench status=ok") for line in latest_account_identity_lines)
        dependency_ok = all(ok for ok, _message in latest_dependency_checks)
        runtime_channels = list(latest_config.channels) if latest_config is not None else []
        runtime_accounts = sum(len(instance.accounts) for instance in latest_config.instances) if latest_config is not None else 0
        decision_route = select_llm_route("structured_decision")
        from TeeBotus.runtime.crew_pilots import crew_pilot_status_lines

        crew_lines = crew_pilot_status_lines(dependency_available=False)
        ok = (
            latest_config is not None
            and runtime_channels == ["telegram", "signal", "matrix"]
            and runtime_accounts == 3
            and latest_health.status == "ready"
            and decision_route.provider == "hf_pool"
            and bool(crew_lines)
            and dependency_ok
            and account_crypto_ok
            and account_memory_ok
            and account_identity_ok
        )
        return result(
            name="status_doctor_runtime_dependency_health",
            category="status_doctor",
            iterations=iterations * 4,
            total_ms=sum(health_timings) + sum(config_timings) + sum(dependency_timings) + sum(account_health_timings),
            ok=ok,
            errors=0 if ok else 1,
            payload_bytes=len(json.dumps(env, ensure_ascii=False).encode("utf-8")),
            index_bytes=LOCKFILE.stat().st_size if LOCKFILE.exists() else 0,
            details={
                "runtime_instances": list(latest_config.selected_instances) if latest_config is not None else [],
                "runtime_channels": runtime_channels,
                "runtime_accounts": runtime_accounts,
                "bibliothekar_status": latest_health.status,
                "bibliothekar_backend": latest_health.backend,
                "decision_provider": decision_route.provider,
                "decision_model": decision_route.model,
                "decision_profile": decision_route.profile_name,
                "crew_pilot_lines": len(crew_lines),
                "dependency_checks": [message for _ok, message in latest_dependency_checks],
                "dependency_ok": dependency_ok,
                "account_crypto_status": latest_account_crypto_lines[0] if latest_account_crypto_lines else "",
                "account_memory_status": next(
                    (line for line in latest_account_memory_lines if line.startswith("account_memory=Bench/")),
                    latest_account_memory_lines[0] if latest_account_memory_lines else "",
                ),
                "account_crypto_ok": account_crypto_ok,
                "account_memory_ok": account_memory_ok,
                "account_identity_status": latest_account_identity_lines[0] if latest_account_identity_lines else "",
                "account_identity_ok": account_identity_ok,
                "account_memory_id_present": bool(memory_id),
                "median_runtime_config_ms": statistics.median(config_timings),
                "median_backend_health_ms": statistics.median(health_timings),
                "median_dependency_check_ms": statistics.median(dependency_timings),
                "median_account_health_ms": statistics.median(account_health_timings),
            },
        )


def _write_static_secret_manifest(accounts_root: Path, *, instance_name: str, secret: bytes) -> None:
    purposes = {}
    now = utc_now()
    for purpose in (INSTANCE_MAPPING_KEY_PURPOSE, ACCOUNT_MEMORY_KEY_PURPOSE, INSTANCE_PEPPER_PURPOSE):
        purposes[purpose] = {
            "algorithm": "HMAC-SHA256",
            "created_at": now,
            "fingerprint": _instance_secret_fingerprint(instance_name, purpose, secret),
            "purpose": purpose,
        }
    (accounts_root / ACCOUNT_KEYRING_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "instance": instance_name,
                "purposes": purposes,
                "updated_at": now,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _benchmark_litellm_pin_guard(expected: str) -> tuple[bool, str]:
    min_safe_litellm = _min_safe_litellm_version()
    if expected in BAD_LITELLM_VERSIONS:
        return False, f"litellm pin={expected} is blocked due to known compromised PyPI releases"
    if _version_tuple(expected) < _version_tuple(min_safe_litellm):
        return False, f"litellm pin={expected} is below security minimum {min_safe_litellm}"
    return True, f"litellm supply_chain_guard=ok pin={expected} installed_check=skipped_for_quick_benchmark"


def benchmark_database_fallback_policy(*, iterations: int) -> BenchmarkResult:
    class Backend:
        def __init__(self, *, fail_write: bool = False) -> None:
            self.fail_write = fail_write
            self.entries: dict[str, list[dict[str, str]]] = {}
            self.indexes: dict[str, dict[str, Any]] = {}
            self.write_entries_count = 0
            self.write_index_count = 0

        def read_entries(self, account_id: str) -> list[dict[str, str]]:
            return [dict(row) for row in self.entries.get(account_id, [])]

        def write_entries(self, account_id: str, rows: list[dict[str, str]]) -> None:
            self.write_entries_count += 1
            if self.fail_write:
                raise OSError("primary unavailable")
            self.entries[account_id] = [dict(row) for row in rows]

        def read_index(self, account_id: str) -> dict[str, Any]:
            return dict(self.indexes.get(account_id, {}))

        def write_index(self, account_id: str, data: dict[str, Any]) -> None:
            self.write_index_count += 1
            if self.fail_write:
                raise OSError("primary unavailable")
            self.indexes[account_id] = dict(data)

    class CountingCriticalHandler(logging.Handler):
        def __init__(self) -> None:
            super().__init__(level=logging.CRITICAL)
            self.messages: list[str] = []

        def emit(self, record: logging.LogRecord) -> None:
            self.messages.append(record.getMessage())

    primary = Backend(fail_write=True)
    secondary = Backend()
    backend = WarningFallbackAccountMemoryBackend(primary, secondary, label="Bench:sqlite")
    account_id = "b" * 128
    handler = CountingCriticalHandler()
    logger = logging.getLogger("TeeBotus")
    logger.addHandler(handler)
    previous_level = logger.level
    logger.setLevel(min(previous_level, logging.CRITICAL) if previous_level else logging.CRITICAL)
    try:
        timings = []
        for index in range(iterations):
            entry = {"id": f"mem_fallback_{index:06d}", "user_text": "Fallback Benchmark"}
            timings.append(_timed_ms(lambda entry=entry: backend.write_entries(account_id, [entry])))
            timings.append(
                _timed_ms(
                    lambda index=index: backend.write_index(
                        account_id,
                        {
                            "scope": "account",
                            "index": {"entries": {f"mem_fallback_{index:06d}": {}}},
                        },
                    )
                )
            )
        primary.fail_write = False
        timings.append(_timed_ms(lambda: backend.read_entries(account_id)))
        timings.append(_timed_ms(lambda: backend.read_index(account_id)))
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
    synced_entries = primary.entries.get(account_id) == secondary.entries.get(account_id)
    synced_index = primary.indexes.get(account_id) == secondary.indexes.get(account_id)
    warning_count = sum(1 for message in handler.messages if "ACCOUNT MEMORY PRIMARY DATABASE FAILED" in message)
    recovery_count = sum(1 for message in handler.messages if "primary backend recovered" in message)
    errors = 0
    if not synced_entries:
        errors += 1
    if not synced_index:
        errors += 1
    if warning_count < 1:
        errors += 1
    if recovery_count < 1:
        errors += 1
    return result(
        name="database_fallback_policy",
        category="database_fallback",
        iterations=iterations * 2 + 2,
        total_ms=sum(timings),
        ok=errors == 0,
        errors=errors,
        payload_bytes=sum(len(json.dumps(row, ensure_ascii=False)) for row in primary.entries.get(account_id, [])),
        note="primary_failure_secondary_sync_recovery_warning",
        details={
            "primary": "sqlite-primary",
            "secondary": "sqlite-fallback",
            "fallback_warnings": warning_count,
            "recovery_warnings": recovery_count,
            "synced_entries": synced_entries,
            "synced_index": synced_index,
            "primary_entry_writes": primary.write_entries_count,
            "secondary_entry_writes": secondary.write_entries_count,
            "primary_index_writes": primary.write_index_count,
            "secondary_index_writes": secondary.write_index_count,
            "median_operation_ms": statistics.median(timings),
        },
    )


def benchmark_database_fallback_collection_corruption(*, iterations: int) -> BenchmarkResult:
    class CountingCriticalHandler(logging.Handler):
        def __init__(self) -> None:
            super().__init__(level=logging.CRITICAL)
            self.messages: list[str] = []

        def emit(self, record: logging.LogRecord) -> None:
            self.messages.append(record.getMessage())

    def _inject_corrupt_collection_row(path: Path, *, account_id: str, collection: str, item_key: str) -> None:
        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE account_jsonl_collections SET payload_ciphertext = ? WHERE instance_name = ? AND account_id = ? AND collection = ? AND item_key = ?",
                (b"not-an-encrypted-value", "Bench", account_id, collection, item_key),
            )

    iterations = max(1, int(iterations))
    handler = CountingCriticalHandler()
    logger = logging.getLogger("TeeBotus")
    previous_level = logger.level
    provider = StaticSecretProvider(b"x" * 32)
    timings: list[float] = []
    rows_seen = 0
    try:
        logger.addHandler(handler)
        logger.setLevel(min(previous_level, logging.CRITICAL) if previous_level else logging.CRITICAL)
        with tempfile.TemporaryDirectory(prefix="teebotus-bench-decrypt-") as tmp:
            root = Path(tmp)
            account_id = "b" * 128
            primary = SQLiteAccountMemoryBackend(
                instance_name="Bench",
                provider=provider,
                purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
                config=SQLiteMemoryConfig(path=root / "Account_Memory.sqlite3"),
            )
            secondary = SQLiteAccountMemoryBackend(
                instance_name="Bench",
                provider=provider,
                purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
                config=SQLiteMemoryConfig(path=root / "Account_Memory.sqlite3.fallback"),
            )
            backend = WarningFallbackAccountMemoryBackend(primary, secondary, label="Bench:sqlite-collection")
            payload_example = json.dumps({"id": "example", "value": "value"}, ensure_ascii=False)
            for iteration in range(iterations):
                collection = "agent_state"
                rows = [
                    {"id": f"corrupt-{iteration:04d}", "value": "state for corruption"},
                    {"id": f"valid-{iteration:04d}", "value": "valid-state"},
                ]
                backend.write_collection(account_id, collection, rows)
                _inject_corrupt_collection_row(root / "Account_Memory.sqlite3", account_id=account_id, collection=collection, item_key=f"corrupt-{iteration:04d}")
                start_lenient = time.perf_counter()
                read_rows = backend.read_collection(account_id, collection)
                timings.append((time.perf_counter() - start_lenient) * 1000)
                rows_seen += len(read_rows)
            fallback_warnings = sum(1 for message in handler.messages if "ACCOUNT MEMORY PRIMARY DATABASE FAILED. USING FALLBACK DATABASE." in message)
            recovery_warnings = sum(1 for message in handler.messages if "primary backend recovered" in message)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)

    corruption_messages = [message for message in handler.messages if "skipped corrupt collection rows" in message]
    corruption_hits = len(corruption_messages)
    rows_skipped = 0
    for message in corruption_messages:
        marker = "skipped="
        marker_index = message.find(marker)
        if marker_index == -1:
            rows_skipped += 1
            continue
        value_start = marker_index + len(marker)
        value = ""
        while value_start < len(message) and message[value_start].isdigit() is False:
            value_start += 1
        while value_start < len(message) and message[value_start].isdigit():
            value += message[value_start]
            value_start += 1
        if value:
            rows_skipped += int(value)
        else:
            rows_skipped += 1

    errors = 0
    if corruption_hits < 1:
        errors += 1
    if not fallback_warnings:
        errors += 1
    if corruption_hits and not rows_skipped:
        errors += 1
    if rows_seen < iterations:
        errors += 1

    return result(
        name="database_fallback_collection_corruption",
        category="database_fallback",
        iterations=iterations,
        total_ms=sum(timings),
        ok=errors == 0,
        errors=errors,
        payload_bytes=len(payload_example),
        note="database_fallback_collection_corruption_warning",
        details={
            "primary": "sqlite-primary",
            "secondary": "sqlite-fallback",
            "fallback_warnings": fallback_warnings,
            "recovery_warnings": recovery_warnings,
            "corrupted_rows_injected": iterations,
            "collection_rows_seen": rows_seen,
            "collection_rows_skipped": rows_skipped,
            "corrupt_collection_rows_detected": corruption_hits,
        },
    )


def _timed_ms(func: Callable[[], Any]) -> float:
    start = time.perf_counter()
    func()
    return (time.perf_counter() - start) * 1000


__all__ = [
    "benchmark_database_fallback_collection_corruption",
    "benchmark_database_fallback_policy",
    "benchmark_status_doctor",
]
