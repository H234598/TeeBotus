#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from TeeBotus.artifact_outputs import DEFAULT_OBSIDIAN_INCOMING_DIR, obsidian_incoming_path  # noqa: E402
_BENCHMARK_CORE_SPEC = importlib.util.spec_from_file_location(
    "teebotus_benchmark_core_for_plan2_acceptance",
    REPO_ROOT / "TeeBotus" / "benchmarks" / "core.py",
)
if _BENCHMARK_CORE_SPEC is None or _BENCHMARK_CORE_SPEC.loader is None:
    raise RuntimeError("Unable to load TeeBotus benchmark core constants.")
_BENCHMARK_CORE = importlib.util.module_from_spec(_BENCHMARK_CORE_SPEC)
_BENCHMARK_CORE_SPEC.loader.exec_module(_BENCHMARK_CORE)
DEFAULT_BENCHMARK_MD = DEFAULT_OBSIDIAN_INCOMING_DIR / "teebotus-benchmarks-latest.md"
DEFAULT_BENCHMARK_JSON = DEFAULT_OBSIDIAN_INCOMING_DIR / "teebotus-benchmarks-latest.json"
DEFAULT_MEMORY_RECOVERY_JSON = DEFAULT_OBSIDIAN_INCOMING_DIR / "teebotus-memory-recovery-with-legacy.json"
DEFAULT_MEMORY_RECOVERY_TEXT = DEFAULT_OBSIDIAN_INCOMING_DIR / "teebotus-memory-recovery-with-legacy.md"
DEFAULT_LEGACY_IMPORT_JSON = obsidian_incoming_path("teebotus-legacy-import-preflight.json")
DEFAULT_LEGACY_IMPORT_MD = obsidian_incoming_path("teebotus-legacy-import-preflight.md")
DEFAULT_LEGACY_REHEARSAL_JSON = obsidian_incoming_path("teebotus-legacy-import-rehearsal.json")
DEFAULT_LEGACY_REHEARSAL_MD = obsidian_incoming_path("teebotus-legacy-import-rehearsal.md")
DEFAULT_LEGACY_REHEARSAL_COPY_DIR = Path("/tmp/teebotus-plan2-legacy-import-rehearsal")
ACCOUNT_ID_RE = re.compile(r"[0-9a-f]{128}")
LEGACY_IMPORT_REPORT_MODES = frozenset({"dry-run", "apply", "rehearsal-apply", "apply-blocked"})
BENCHMARK_RANKING_NAME_SETS = _BENCHMARK_CORE.BENCHMARK_RANKING_NAME_SETS
BENCHMARK_CONTEXT_DEPENDENCIES = _BENCHMARK_CORE.BENCHMARK_CONTEXT_DEPENDENCIES
BENCHMARK_SELECTION_POLICY = _BENCHMARK_CORE.BENCHMARK_SELECTION_POLICY
REQUIRED_BENCHMARK_CATEGORIES = _BENCHMARK_CORE.REQUIRED_BENCHMARK_CATEGORIES
REQUIRED_BENCHMARK_MIN_RANKING_CANDIDATES = _BENCHMARK_CORE.REQUIRED_BENCHMARK_MIN_RANKING_CANDIDATES
REQUIRED_BENCHMARK_NAME_CATEGORIES = _BENCHMARK_CORE.REQUIRED_BENCHMARK_NAME_CATEGORIES
REQUIRED_BENCHMARK_NAMES = _BENCHMARK_CORE.REQUIRED_BENCHMARK_NAMES
REQUIRED_BENCHMARK_RANKING_CATEGORIES = _BENCHMARK_CORE.REQUIRED_BENCHMARK_RANKING_CATEGORIES
STANDARD_BENCHMARK_FORBIDDEN_CALL_COUNTERS = _BENCHMARK_CORE.STANDARD_BENCHMARK_FORBIDDEN_CALL_COUNTERS
build_benchmark_quality_gate = _BENCHMARK_CORE.build_quality_gate
REQUIRED_BIBLIOTHEKAR_BENCHMARK_NAMES = frozenset(
    {
        "bibliothekar_local_query",
        "bibliothekar_llamaindex_fake_query",
        "bibliothekar_haystack_fake_query",
    }
)
REQUIRED_HF_POOL_EVAL_PURPOSES = frozenset(
    {
        "structured_decision",
        "normal_chat",
        "psychology_explainer",
        "bibliothekar_answer",
        "summarizer",
    }
)
REQUIRED_RETRIEVAL_USERMEMORY_MODELS = frozenset({"intfloat/multilingual-e5-small", "intfloat/multilingual-e5-base"})
REQUIRED_RETRIEVAL_BOOK_MODELS = frozenset({"BAAI/bge-m3", "intfloat/multilingual-e5-base"})
REQUIRED_RETRIEVAL_BACKEND_MODES = frozenset({"local", "llamaindex_fake", "haystack_fake"})
REQUIRED_BIBLIOTHEKAR_CITATION_FIELDS = frozenset(
    {
        "chunk_id",
        "source_id",
        "file",
        "file_path",
        "file_sha256",
        "file_type",
        "language",
        "locator",
        "license",
        "source_quality",
        "citation_quality",
        "ingested_at",
        "chunk_index",
        "embedding_model",
        "citation_format",
    }
)
REQUIRED_PYDANTIC_DECISION_SCHEMAS = frozenset(
    {
        "AgentTaskDecision",
        "BibliothekarQueryDecision",
        "MemoryCandidate",
        "ReminderDecision",
        "SourceQualityDecision",
        "ToolSafetyDecision",
        "ProactiveToolCallDecision",
        "YouTubeOptionsDecision",
    }
)
REQUIRED_BENCHMARK_CONTEXT_KEYS = frozenset({"python", "platform", "machine", "cpu_count", "dependencies"})
RUNTIME_STATUS_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bsyt_[A-Za-z0-9_=-]{12,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{12,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bhf_[A-Za-z0-9]{12,}\b"),
    re.compile(r"\bgsk_[A-Za-z0-9]{12,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
)
RUNTIME_STATUS_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?<!\S)([A-Za-z0-9_-]*(?:api[_-]?key|access[_-]?token|auth[_-]?token|bearer[_-]?token|token|secret|password)"
    r"[A-Za-z0-9_-]*)\s*[:=]\s*([^,\s)]+)",
    re.IGNORECASE,
)
RUNTIME_STATUS_SECRET_ASSIGNMENT_FRAGMENT_RE = re.compile(
    r"([\s=;,])([A-Za-z0-9_-]*(?:api[_-]?key|access[_-]?token|auth[_-]?token|bearer[_-]?token|token|secret|password)"
    r"[A-Za-z0-9_-]*)\s*([:=])\s*([^,\s)]+)",
    re.IGNORECASE,
)
SECRET_FIELD_ASSIGNMENT_RE = re.compile(
    r"(?<!\S)([A-Za-z0-9_-]*(?:api[_-]?key|access[_-]?token|auth[_-]?token|bearer[_-]?token|token|secret|password)[A-Za-z0-9_-]*)\s*[:=]\s*([^,\s)]+)",
    re.IGNORECASE,
)
SECRET_FIELD_NAME_RE = re.compile(
    r"(?:api[_ -]?key|access[_ -]?token|auth[_ -]?token|bearer[_ -]?token|token|secret|password)",
    re.IGNORECASE,
)
RUNTIME_STATUS_URL_CREDENTIAL_RE = re.compile(
    r"(?:[a-z][a-z0-9+.-]*://|(?:target|base_url|url)=)[^\s/@:=]+:[^\s/@]+@",
    re.IGNORECASE,
)
ARTIFACT_SECRET_JSON_FIELD_RE = re.compile(
    r'"([^"]*(?:api[_-]?key|access[_-]?token|auth[_-]?token|bearer[_-]?token|token|secret|password)[^"]*)"\s*:\s*"([^"]*)"',
    re.IGNORECASE,
)
SAFE_RUNTIME_STATUS_SECRET_PLACEHOLDERS = frozenset(
    {"configured", "none", "<redacted>", "<redacted-secret>", "redacted", "missing"}
)
SAFE_RUNTIME_STATUS_SECRET_METADATA_KEYS = frozenset(
    {"api_key_ring", "gemini_api_key_ring", "api_key_instances", "max_output_tokens"}
)
SAFE_RUNTIME_STATUS_SECRET_TEXT_KEYS = frozenset({"tokens", "token_usage", "costs", "limits", "free_tier_guard"})
LOCAL_RUNTIME_TARGET_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


@dataclass(frozen=True)
class AcceptanceCommand:
    label: str
    argv: tuple[str, ...]
    nonfatal: bool = False
    validate_runtime_status: bool = False
    validate_benchmark_artifacts: bool = False
    validate_secret_artifacts: bool = False
    validate_systemd_unit: bool = False


PLAN2_TEST_PATTERNS: tuple[str, ...] = (
    "tests/test_account_store.py",
    "tests/test_account_memory_migration.py",
    "tests/test_activity_profile.py",
    "tests/test_adapter_dependency_install.py",
    "tests/test_adapters.py",
    "tests/test_admin_accounts.py",
    "tests/test_async_bridge.py",
    "tests/test_bot.py",
    "tests/test_check_proactive_agent.py",
    "tests/test_codex_command.py",
    "tests/test_codex_history.py",
    "tests/test_codex_history_systemd.py",
    "tests/test_crew_pilots.py",
    "tests/test_entrypoint_compatibility.py",
    "tests/test_embedding.py",
    "tests/test_engine_identity_flows.py",
    "tests/test_engine_memory_search.py",
    "tests/test_export.py",
    "tests/test_file_artifacts.py",
    "tests/test_handlers.py",
    "tests/test_history_dispatcher_bridge.py",
    "tests/test_history_dispatcher_migration.py",
    "tests/test_instance_quarantine_maintenance.py",
    "tests/test_instructions.py",
    "tests/test_matrix_runner.py",
    "tests/test_memory_artifact_import_job.py",
    "tests/test_message_tracking.py",
    "tests/test_notification_loudness.py",
    "tests/test_program_history.py",
    "tests/test_proactive_*.py",
    "tests/test_registration_parser.py",
    "tests/test_runtime_config.py",
    "tests/test_route_to_llm_command.py",
    "tests/test_runtime_maintenance.py",
    "tests/test_runtime_admin_accounts.py",
    "tests/test_python313_runtime_setup.py",
    "tests/test_runtime_state.py",
    "tests/test_runtime_dotenv.py",
    "tests/test_signal_runner.py",
    "tests/test_sqlite_backup_sync.py",
    "tests/test_systemd.py",
    "tests/test_telegram_dispatch_journal.py",
    "tests/test_telegram_runner.py",
    "tests/test_tts_dialect.py",
    "tests/test_version_notifications.py",
    "tests/test_weather_context.py",
    "tests/test_timezone.py",
    "tests/test_working_memory.py",
    "tests/test_llm_config.py",
    "tests/test_llm_client.py",
    "tests/test_gemini_keyring.py",
    "tests/test_litellm_provider.py",
    "tests/test_logic_audit_round5.py",
    "tests/test_llm_router.py",
    "tests/test_llm_package.py",
    "tests/test_hf_pool_*.py",
    "tests/test_openai_client.py",
    "tests/test_bibliothekar.py",
    "tests/test_bibliothekar_*.py",
    "tests/test_decision_schemas.py",
    "tests/test_embedding_rebuild.py",
    "tests/test_memory_search_service.py",
    "tests/test_pydantic_decisions.py",
    "tests/test_pydantic_decision_fake_model.py",
    "tests/test_pyproject_metadata.py",
    "tests/test_qdrant_*.py",
    "tests/test_qdrant_systemd.py",
    "tests/test_reminder_intent.py",
    "tests/test_source_harvester.py",
    "tests/test_source_quality.py",
    "tests/test_graphs_*.py",
    "tests/test_mcp_tools.py",
    "tests/test_readme_plan2_docs.py",
    "tests/test_secret_hygiene.py",
    "tests/test_selinux_doctor.py",
    "tests/test_semantic_memory_index_benchmark.py",
    "tests/test_benchmarks_runner.py",
    "tests/test_ci_workflow.py",
    "tests/test_cinnamon_applet.py",
    "tests/test_memory_store_benchmark.py",
    "tests/test_plan2_acceptance.py",
    "tests/test_plan3_acceptance.py",
    "tests/test_plan2_optional_extras.py",
    "tests/test_youtube_parser_stats.py",
    "tests/test_youtube_parser_misses_report.py",
    "tests/test_local_transcription.py",
)
LEGACY_IMPORT_TEST_PATTERNS: tuple[str, ...] = ("tests/test_legacy_user_memory_import.py",)
PLAN2_DEFAULT_INSTANCE_NAMES: tuple[str, ...] = ("Bote_der_Wahrheit", "Depressionsbot")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run non-invasive TeeBotus Plan2 acceptance checks.")
    parser.add_argument("--python", default=sys.executable, help="Python executable to use.")
    parser.add_argument("--runtime-channels", default="telegram,signal,matrix", help="Channels for --runtime-status.")
    parser.add_argument("--benchmark-output", default=str(DEFAULT_BENCHMARK_MD), help="Markdown benchmark output path.")
    parser.add_argument("--benchmark-json-output", default=str(DEFAULT_BENCHMARK_JSON), help="JSON benchmark output path.")
    parser.add_argument("--legacy-instances-dir", default="", help="Optional plaintext legacy instances directory for read-only memory recovery/preflight checks.")
    parser.add_argument("--memory-recovery-output", default=str(DEFAULT_MEMORY_RECOVERY_TEXT), help="Text/Markdown memory recovery output path.")
    parser.add_argument("--memory-recovery-json-output", default=str(DEFAULT_MEMORY_RECOVERY_JSON), help="JSON memory recovery output path.")
    parser.add_argument("--legacy-import-output", default=str(DEFAULT_LEGACY_IMPORT_MD), help="Markdown legacy import dry-run output path.")
    parser.add_argument("--legacy-import-json-output", default=str(DEFAULT_LEGACY_IMPORT_JSON), help="JSON legacy import dry-run output path.")
    parser.add_argument("--legacy-rehearsal-output", default=str(DEFAULT_LEGACY_REHEARSAL_MD), help="Markdown legacy import rehearsal output path.")
    parser.add_argument("--legacy-rehearsal-json-output", default=str(DEFAULT_LEGACY_REHEARSAL_JSON), help="JSON legacy import rehearsal output path.")
    parser.add_argument("--legacy-rehearsal-copy-dir", default=str(DEFAULT_LEGACY_REHEARSAL_COPY_DIR), help="Temporary copied instances directory for legacy import rehearsal.")
    parser.add_argument("--include-legacy-import-tests", action="store_true", help="Include legacy user-memory import unit tests in the Plan2 pytest command.")
    parser.add_argument("--entries", type=int, default=2, help="Synthetic benchmark entries.")
    parser.add_argument("--iterations", type=int, default=1, help="Quick benchmark iterations.")
    parser.add_argument("--skip-runtime-status", action="store_true", help="Skip live runtime-status checks.")
    parser.add_argument("--skip-adapter-deps", action="store_true", help="Skip adapter dependency checks.")
    parser.add_argument(
        "--adapter-deps-python-only",
        action="store_true",
        help="Run adapter dependency checks in non-live Python-only mode.",
    )
    parser.add_argument("--include-audit", action="store_true", help="Run pip-audit when installed; audit failures are reported but non-fatal.")
    parser.add_argument(
        "--include-qdrant-live",
        action="store_true",
        help="Probe local Qdrant /collections when explicitly requested; failures are non-fatal.",
    )
    parser.add_argument("--list", action="store_true", help="Print commands without executing them.")
    parser.add_argument("--dry-run", action="store_true", help="Alias for --list; print commands without executing them.")
    args = parser.parse_args(argv)
    if args.skip_adapter_deps and args.adapter_deps_python_only:
        parser.error("--adapter-deps-python-only cannot be combined with --skip-adapter-deps")

    commands = build_acceptance_commands(
        python=args.python,
        runtime_channels=args.runtime_channels,
        benchmark_output=Path(args.benchmark_output),
        benchmark_json_output=Path(args.benchmark_json_output),
        legacy_instances_dir=Path(args.legacy_instances_dir) if args.legacy_instances_dir else None,
        memory_recovery_output=Path(args.memory_recovery_output),
        memory_recovery_json_output=Path(args.memory_recovery_json_output),
        legacy_import_output=Path(args.legacy_import_output),
        legacy_import_json_output=Path(args.legacy_import_json_output),
        legacy_rehearsal_output=Path(args.legacy_rehearsal_output),
        legacy_rehearsal_json_output=Path(args.legacy_rehearsal_json_output),
        legacy_rehearsal_copy_dir=Path(args.legacy_rehearsal_copy_dir),
        entries=args.entries,
        iterations=args.iterations,
        skip_runtime_status=args.skip_runtime_status,
        skip_adapter_deps=args.skip_adapter_deps,
        adapter_deps_python_only=args.adapter_deps_python_only,
        include_audit=args.include_audit,
        include_qdrant_live=args.include_qdrant_live,
        include_legacy_import_tests=args.include_legacy_import_tests,
    )
    if args.list or args.dry_run:
        for command in commands:
            suffix = " (nonfatal)" if command.nonfatal else ""
            print(f"{command.label}: {_format_command(command.argv)}{suffix}")
        return 0

    return run_acceptance_commands(commands)


def build_acceptance_commands(
    *,
    python: str = sys.executable,
    runtime_channels: str = "telegram,signal,matrix",
    benchmark_output: Path = DEFAULT_BENCHMARK_MD,
    benchmark_json_output: Path = DEFAULT_BENCHMARK_JSON,
    legacy_instances_dir: Path | None = None,
    memory_recovery_output: Path = DEFAULT_MEMORY_RECOVERY_TEXT,
    memory_recovery_json_output: Path = DEFAULT_MEMORY_RECOVERY_JSON,
    legacy_import_output: Path = DEFAULT_LEGACY_IMPORT_MD,
    legacy_import_json_output: Path = DEFAULT_LEGACY_IMPORT_JSON,
    legacy_rehearsal_output: Path = DEFAULT_LEGACY_REHEARSAL_MD,
    legacy_rehearsal_json_output: Path = DEFAULT_LEGACY_REHEARSAL_JSON,
    legacy_rehearsal_copy_dir: Path = DEFAULT_LEGACY_REHEARSAL_COPY_DIR,
    entries: int = 2,
    iterations: int = 1,
    skip_runtime_status: bool = False,
    skip_adapter_deps: bool = False,
    adapter_deps_python_only: bool = False,
    include_audit: bool = False,
    include_qdrant_live: bool = False,
    include_legacy_import_tests: bool = False,
) -> list[AcceptanceCommand]:
    if skip_adapter_deps and adapter_deps_python_only:
        raise ValueError("adapter_deps_python_only cannot be combined with skip_adapter_deps")
    commands = [
        AcceptanceCommand("version", (python, "-m", "TeeBotus", "--version")),
    ]
    if not skip_runtime_status:
        commands.append(
            AcceptanceCommand(
                "runtime-status",
                (python, "-m", "TeeBotus", "--runtime-status", "--channels", runtime_channels),
                validate_runtime_status=True,
            )
        )
        for channel in ("telegram", "signal", "matrix"):
            commands.append(
                AcceptanceCommand(
                    f"runtime-status-{channel}",
                    (python, "-m", "TeeBotus", "--runtime-status", "--channels", channel),
                    validate_runtime_status=True,
                )
            )
    commands.append(
        AcceptanceCommand(
            "plan2-pytest",
            (
                python,
                "-m",
                "pytest",
                "-q",
                *_expand_test_patterns(
                    _plan2_test_patterns(include_legacy_import_tests=include_legacy_import_tests)
                ),
            ),
        )
    )
    if legacy_instances_dir is not None:
        commands.extend(_legacy_memory_acceptance_commands(
            python=python,
            legacy_instances_dir=legacy_instances_dir,
            memory_recovery_output=memory_recovery_output,
            memory_recovery_json_output=memory_recovery_json_output,
            legacy_import_output=legacy_import_output,
            legacy_import_json_output=legacy_import_json_output,
            legacy_rehearsal_output=legacy_rehearsal_output,
            legacy_rehearsal_json_output=legacy_rehearsal_json_output,
            legacy_rehearsal_copy_dir=legacy_rehearsal_copy_dir,
        ))
    commands.extend(
        [
            AcceptanceCommand(
                "bibliothekar-status",
                (python, "-m", "TeeBotus.bibliothekar", "status"),
            ),
            AcceptanceCommand(
                "bibliothekar-dry-run",
                (python, "-m", "TeeBotus.bibliothekar", "index", "--source", "tests/fixtures/books", "--dry-run"),
            ),
            AcceptanceCommand(
                "bibliothekar-fixture-query",
                (
                    python,
                    "-m",
                    "TeeBotus.bibliothekar",
                    "--instance",
                    "Depressionsbot",
                    "query",
                    "--source",
                    "tests/fixtures/books",
                    "Testfrage",
                    "--top-k",
                    "3",
                ),
            ),
            AcceptanceCommand(
                "plan2-quick-benchmarks",
                (
                    python,
                    "scripts/run_benchmarks.py",
                    "--quick",
                    "--entries",
                    str(entries),
                    "--iterations",
                    str(iterations),
                    "--output",
                    str(benchmark_output),
                    "--json-output",
                    str(benchmark_json_output),
                ),
                validate_benchmark_artifacts=True,
            ),
            AcceptanceCommand(
                "plan2-optional-extras",
                (python, "scripts/check_plan2_optional_extras.py", "--require-installed"),
            ),
            AcceptanceCommand(
                "qdrant-systemd-print",
                (python, "-m", "TeeBotus.qdrant_systemd", "--print"),
                validate_systemd_unit=True,
            ),
            AcceptanceCommand(
                "teebotus-systemd-print",
                (python, "-m", "TeeBotus.systemd", "--print"),
                validate_systemd_unit=True,
            ),
        ]
    )
    if include_qdrant_live:
        curl = shutil.which("curl")
        if curl:
            commands.append(
                AcceptanceCommand(
                    "qdrant-live-collections",
                    (curl, "-fsS", "http://127.0.0.1:6333/collections"),
                    nonfatal=True,
                )
            )
        else:
            commands.append(
                AcceptanceCommand(
                    "qdrant-live-curl-missing",
                    (python, "-c", "print('curl not installed; qdrant live check skipped')"),
                    nonfatal=True,
                )
            )
    if not skip_adapter_deps:
        adapter_deps_argv = [python, "scripts/check_adapter_deps.py"]
        if adapter_deps_python_only:
            adapter_deps_argv.append("--python-only")
        commands.append(AcceptanceCommand("adapter-deps", tuple(adapter_deps_argv)))
    if include_audit:
        audit = shutil.which("pip-audit")
        if audit:
            commands.append(AcceptanceCommand("pip-audit", (audit,), nonfatal=True))
        else:
            commands.append(AcceptanceCommand("pip-audit-missing", (python, "-c", "print('pip-audit not installed; skipped')"), nonfatal=True))
    return commands


def _plan2_test_patterns(*, include_legacy_import_tests: bool = False) -> tuple[str, ...]:
    if not include_legacy_import_tests:
        return PLAN2_TEST_PATTERNS
    return (*PLAN2_TEST_PATTERNS, *LEGACY_IMPORT_TEST_PATTERNS)


def _legacy_memory_acceptance_commands(
    *,
    python: str,
    legacy_instances_dir: Path,
    memory_recovery_output: Path,
    memory_recovery_json_output: Path,
    legacy_import_output: Path,
    legacy_import_json_output: Path,
    legacy_rehearsal_output: Path,
    legacy_rehearsal_json_output: Path,
    legacy_rehearsal_copy_dir: Path,
) -> list[AcceptanceCommand]:
    commands = [
        AcceptanceCommand(
            "memory-recovery-legacy-json",
            (
                python,
                "-m",
                "TeeBotus.admin",
                "memory-recovery",
                "--instances-dir",
                "instances",
                "--legacy-instances-dir",
                str(legacy_instances_dir),
                "--format",
                "json",
                "--output",
                str(memory_recovery_json_output),
            ),
            validate_secret_artifacts=True,
        ),
        AcceptanceCommand(
            "memory-recovery-legacy-text",
            (
                python,
                "-m",
                "TeeBotus.admin",
                "memory-recovery",
                "--instances-dir",
                "instances",
                "--legacy-instances-dir",
                str(legacy_instances_dir),
                "--output",
                str(memory_recovery_output),
            ),
            validate_secret_artifacts=True,
        ),
        AcceptanceCommand(
            "legacy-import-preflight",
            _legacy_import_command(
                python=python,
                legacy_instances_dir=legacy_instances_dir,
                json_output=legacy_import_json_output,
                markdown_output=legacy_import_output,
            ),
            validate_secret_artifacts=True,
        ),
        AcceptanceCommand(
            "legacy-import-rehearsal",
            _legacy_import_command(
                python=python,
                legacy_instances_dir=legacy_instances_dir,
                json_output=legacy_rehearsal_json_output,
                markdown_output=legacy_rehearsal_output,
                rehearsal_copy_dir=legacy_rehearsal_copy_dir,
                apply=True,
            ),
            validate_secret_artifacts=True,
        ),
    ]
    for instance_name in _discover_plan2_instances():
        commands.append(
            AcceptanceCommand(
                f"legacy-import-preflight-{instance_name}",
                _legacy_import_command(
                    python=python,
                    legacy_instances_dir=legacy_instances_dir,
                    json_output=_instance_artifact_path(legacy_import_json_output, instance_name),
                    markdown_output=_instance_artifact_path(legacy_import_output, instance_name),
                    instance_name=instance_name,
                ),
                validate_secret_artifacts=True,
            )
        )
    return commands


def _legacy_import_command(
    *,
    python: str,
    legacy_instances_dir: Path,
    json_output: Path,
    markdown_output: Path,
    instance_name: str = "",
    rehearsal_copy_dir: Path | None = None,
    apply: bool = False,
) -> tuple[str, ...]:
    argv: list[str] = [
        python,
        "scripts/import_legacy_user_memory.py",
        "--legacy-instances-dir",
        str(legacy_instances_dir),
        "--target-instances-dir",
        "instances",
    ]
    if instance_name:
        argv.extend(["--instance", instance_name])
    if rehearsal_copy_dir is not None:
        argv.extend(["--rehearsal-copy-dir", str(rehearsal_copy_dir)])
    if apply:
        argv.extend(["--replace-unreadable", "--apply"])
    argv.extend(
        [
            "--replace-unreadable-account-metadata",
            "--json-output",
            str(json_output),
            "--markdown-output",
            str(markdown_output),
        ]
    )
    return tuple(argv)


def _discover_plan2_instances(instances_dir: Path = REPO_ROOT / "instances") -> tuple[str, ...]:
    if not instances_dir.exists():
        return PLAN2_DEFAULT_INSTANCE_NAMES
    discovered = tuple(
        path.name
        for path in sorted(instances_dir.iterdir())
        if path.is_dir() and (path / "Bot_Verhalten.md").exists()
    )
    # CI deliberately does not carry user runtime directories. Keep the
    # documented migration targets visible in the generated command matrix so
    # the acceptance contract remains deterministic on a clean checkout.
    return discovered or PLAN2_DEFAULT_INSTANCE_NAMES


def _instance_artifact_path(path: Path, instance_name: str) -> Path:
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", instance_name).strip("_") or "instance"
    return path.with_name(f"{path.stem}-{safe_name}{path.suffix}")


def _prepare_acceptance_command(command: AcceptanceCommand) -> None:
    rehearsal_copy_dir = _option_path(command.argv, "--rehearsal-copy-dir")
    if rehearsal_copy_dir is None:
        return
    path = rehearsal_copy_dir.expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    path = path.resolve(strict=False)
    if not _is_safe_rehearsal_copy_dir(path):
        raise RuntimeError(f"unsafe legacy rehearsal copy dir: {path}")
    target_instances_arg = _option_path(command.argv, "--target-instances-dir")
    target_instances_dir = target_instances_arg if target_instances_arg is not None else Path("instances")
    target_instances_dir = target_instances_dir.expanduser()
    if not target_instances_dir.is_absolute():
        target_instances_dir = REPO_ROOT / target_instances_dir
    resolved_target_instances_dir = target_instances_dir.resolve(strict=False)
    resolved_path = path
    if resolved_path == resolved_target_instances_dir:
        raise RuntimeError("legacy rehearsal copy directory must not be the same as source instances directory")
    if resolved_target_instances_dir in resolved_path.parents:
        raise RuntimeError("legacy rehearsal copy directory must not be inside source instances directory")
    if resolved_path in resolved_target_instances_dir.parents:
        raise RuntimeError("legacy rehearsal copy directory must not contain source instances directory")
    if path.exists() or path.is_symlink():
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()


def _is_safe_rehearsal_copy_dir(path: Path) -> bool:
    resolved = path.resolve(strict=False)
    tmp_root = Path("/tmp").resolve()
    return resolved != tmp_root and tmp_root in resolved.parents and any(
        "teebotus" in node.name.casefold() for node in [resolved, *resolved.parents]
    )


def run_acceptance_commands(commands: Sequence[AcceptanceCommand]) -> int:
    for index, command in enumerate(commands, start=1):
        print(f"\n[{index}/{len(commands)}] {command.label}: {_format_command(command.argv)}", flush=True)
        _prepare_acceptance_command(command)
        capture_output = command.validate_runtime_status or command.validate_systemd_unit
        result = subprocess.run(command.argv, cwd=REPO_ROOT, check=False, text=True, capture_output=capture_output)
        if capture_output:
            if result.stdout:
                _print_console_text(result.stdout)
            if result.stderr:
                _print_console_text(result.stderr, file=sys.stderr)
        if result.returncode and not command.nonfatal:
            print(f"\nPlan2 acceptance failed at {command.label} with exit code {result.returncode}.", file=sys.stderr)
            return result.returncode
        if result.returncode and command.nonfatal:
            print(f"\nNon-fatal Plan2 check failed at {command.label} with exit code {result.returncode}.", file=sys.stderr)
        if command.validate_runtime_status:
            broken_lines = _runtime_status_broken_lines("\n".join(part for part in (result.stdout, result.stderr) if part))
            if broken_lines and not command.nonfatal:
                print(f"\nPlan2 acceptance failed at {command.label}: runtime-status reports broken state.", file=sys.stderr)
                for line in broken_lines:
                    print(f"  {_redact_console_text(line)}", file=sys.stderr)
                return 1
            missing_lines = _runtime_status_missing_required_lines("\n".join(part for part in (result.stdout, result.stderr) if part))
            if missing_lines and not command.nonfatal:
                print(f"\nPlan2 acceptance failed at {command.label}: runtime-status is missing required Plan3 lines.", file=sys.stderr)
                for line in missing_lines:
                    print(f"  {_redact_console_text(line)}", file=sys.stderr)
                return 1
        if command.validate_benchmark_artifacts:
            artifact_errors = _benchmark_artifact_errors(command.argv)
            if artifact_errors and not command.nonfatal:
                print(f"\nPlan2 acceptance failed at {command.label}: benchmark artifacts are invalid.", file=sys.stderr)
                for error in artifact_errors:
                    print(f"  {_redact_console_text(error)}", file=sys.stderr)
                return 1
        if command.validate_secret_artifacts:
            artifact_errors = _secret_artifact_errors(command.argv)
            if _is_legacy_import_command(command.argv):
                artifact_errors.extend(_legacy_import_artifact_errors(command.argv))
            if _is_memory_recovery_json_command(command.argv):
                artifact_errors.extend(_memory_recovery_artifact_errors(command.argv))
            if _is_memory_recovery_text_command(command.argv):
                artifact_errors.extend(_memory_recovery_markdown_artifact_errors(command.argv))
            if artifact_errors and not command.nonfatal:
                print(f"\nPlan2 acceptance failed at {command.label}: output artifacts contain secret-looking content.", file=sys.stderr)
                for error in artifact_errors:
                    print(f"  {_redact_console_text(error)}", file=sys.stderr)
                return 1
        if command.validate_systemd_unit:
            unit_errors = _systemd_unit_errors(command.label, result.stdout or "")
            if unit_errors and not command.nonfatal:
                print(f"\nPlan2 acceptance failed at {command.label}: systemd unit is unsafe.", file=sys.stderr)
                for error in unit_errors:
                    print(f"  {_redact_console_text(error)}", file=sys.stderr)
                return 1
    print("\nPlan2 acceptance checks passed.")
    return 0


def _benchmark_artifact_errors(argv: Sequence[str]) -> list[str]:
    errors: list[str] = []
    markdown_path = _option_path(argv, "--output")
    json_path = _option_path(argv, "--json-output")

    if markdown_path is None:
        errors.append("missing --output for benchmark markdown artifact")
    else:
        errors.extend(_markdown_artifact_errors(markdown_path))

    if json_path is None:
        errors.append("missing --json-output for benchmark JSON artifact")
    else:
        errors.extend(_json_benchmark_artifact_errors(json_path))

    return errors


def _secret_artifact_errors(argv: Sequence[str]) -> list[str]:
    errors: list[str] = []
    paths = _option_paths(argv, ("--output", "--json-output", "--markdown-output"))
    if not paths:
        return ["missing output artifact path for secret validation"]
    for option, path in paths:
        if not path.exists():
            errors.append(f"{option} artifact missing: {path}")
            continue
        if not path.is_file():
            errors.append(f"{option} artifact is not a file: {path}")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if _artifact_text_contains_secret(text):
            errors.append(f"{option} artifact contains secret-looking content: {path}")
    return errors


def _is_legacy_import_command(argv: Sequence[str]) -> bool:
    return any(str(part).endswith("import_legacy_user_memory.py") for part in argv)


def _is_memory_recovery_json_command(argv: Sequence[str]) -> bool:
    return "memory-recovery" in argv and "--format" in argv and _option_value(argv, "--format") == "json"


def _is_memory_recovery_text_command(argv: Sequence[str]) -> bool:
    return "memory-recovery" in argv and _option_value(argv, "--format") != "json"


def _memory_recovery_artifact_errors(argv: Sequence[str]) -> list[str]:
    output_path = _option_path(argv, "--output")
    if output_path is None:
        return ["memory recovery JSON artifact missing --output"]
    if not output_path.exists():
        return [f"memory recovery JSON artifact missing: {output_path}"]
    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"memory recovery JSON artifact is not valid JSON: {output_path}: {exc}"]
    if not isinstance(payload, dict):
        return [f"memory recovery JSON root must be an object: {output_path}"]
    return _memory_recovery_payload_errors(payload, path=output_path)


def _memory_recovery_markdown_artifact_errors(argv: Sequence[str]) -> list[str]:
    output_path = _option_path(argv, "--output")
    if output_path is None:
        return ["memory recovery markdown artifact missing --output"]
    if not output_path.exists():
        return [f"memory recovery markdown artifact missing: {output_path}"]
    if not output_path.is_file():
        return [f"memory recovery markdown artifact is not a file: {output_path}"]
    text = output_path.read_text(encoding="utf-8", errors="replace")
    errors: list[str] = []
    if not text.strip():
        errors.append(f"memory recovery markdown artifact is empty: {output_path}")
    required_sections = {
        "# TeeBotus Account-Memory Recovery Report": "heading",
        "## Totals": "totals section",
        "## Instance:": "instance section",
        "metadata_health": "metadata health summary",
        "recovery_status": "account recovery status",
    }
    for needle, label in required_sections.items():
        if needle not in text:
            errors.append(f"memory recovery markdown artifact lacks {label}: {output_path}")
    if _artifact_text_contains_secret(text):
        errors.append(f"memory recovery markdown artifact contains secret-looking content: {output_path}")
    totals_position = text.find("## Totals")
    instance_position = text.find("## Instance:")
    if totals_position != -1 and instance_position != -1 and totals_position > instance_position:
        errors.append(f"memory recovery markdown artifact places totals after instances: {output_path}")
    if "legacy_plaintext_import:" in text and re.search(r"legacy_plaintext_import:.*sources=`[1-9][0-9]*`", text) and "  - users: `" not in text:
        errors.append(f"memory recovery markdown artifact lacks legacy users summary: {output_path}")
    return errors


def _memory_recovery_payload_errors(payload: Mapping[str, Any], *, path: Path | None = None) -> list[str]:
    prefix = f"{path}: " if path is not None else ""
    errors: list[str] = []
    if payload.get("schema_version") != 2:
        errors.append(f"{prefix}memory recovery schema_version must be 2")
    instances = payload.get("instances")
    if not isinstance(instances, list):
        errors.append(f"{prefix}memory recovery instances must be a list")
        instances = []
    instance_count = payload.get("instance_count")
    if not _is_nonnegative_integer(instance_count):
        errors.append(f"{prefix}memory recovery instance_count must be a non-negative integer")
    elif int(instance_count or 0) != len(instances):
        errors.append(f"{prefix}memory recovery instance_count must match instances length")
    totals = payload.get("totals")
    if not isinstance(totals, Mapping):
        errors.append(f"{prefix}memory recovery totals must be an object")
        totals = {}
    required_total_keys = (
        "accounts",
        "recoverable_accounts",
        "unrecoverable_accounts",
        "empty_accounts",
        "no_source_accounts",
        "sources",
        "readable_sources",
        "unreadable_sources",
        "legacy_plaintext_sources",
        "legacy_plaintext_entries",
    )
    for key in required_total_keys:
        if not _is_nonnegative_integer(totals.get(key)):
            errors.append(f"{prefix}memory recovery totals.{key} must be a non-negative integer")
    derived = _derive_memory_recovery_totals(instances)
    for key, value in derived.items():
        if _is_nonnegative_integer(totals.get(key)) and int(totals.get(key) or 0) != value:
            errors.append(f"{prefix}memory recovery totals.{key} must match instances ({value})")
    errors.extend(_memory_recovery_source_structure_errors(instances, prefix=prefix))
    errors.extend(_memory_recovery_metadata_health_errors(instances, prefix=prefix))
    errors.extend(_memory_recovery_legacy_command_errors(instances, prefix=prefix))
    return errors


def _derive_memory_recovery_totals(instances: Sequence[Any]) -> dict[str, int]:
    totals = {
        "accounts": 0,
        "recoverable_accounts": 0,
        "unrecoverable_accounts": 0,
        "empty_accounts": 0,
        "no_source_accounts": 0,
        "sources": 0,
        "readable_sources": 0,
        "unreadable_sources": 0,
        "metadata_broken_instances": 0,
        "metadata_unreadable_items": 0,
        "metadata_unreadable_accounts": 0,
        "legacy_plaintext_sources": 0,
        "legacy_plaintext_entries": 0,
    }
    for instance in instances:
        if not isinstance(instance, Mapping):
            continue
        metadata = instance.get("metadata_health")
        if isinstance(metadata, Mapping):
            items = metadata.get("items") if isinstance(metadata.get("items"), list) else []
            if metadata.get("readable") is False or items:
                totals["metadata_broken_instances"] += 1
            totals["metadata_unreadable_items"] += len(items)
            unreadable_accounts: set[str] = set()
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                account_ids = item.get("account_ids") if isinstance(item.get("account_ids"), list) else []
                unreadable_accounts.update(str(account_id) for account_id in account_ids if ACCOUNT_ID_RE.fullmatch(str(account_id)))
            totals["metadata_unreadable_accounts"] += len(unreadable_accounts)
        accounts = instance.get("accounts")
        if isinstance(accounts, list):
            for account in accounts:
                if not isinstance(account, Mapping):
                    continue
                totals["accounts"] += 1
                status = str(account.get("recovery_status") or "")
                if account.get("recoverable"):
                    totals["recoverable_accounts"] += 1
                if status == "unrecoverable":
                    totals["unrecoverable_accounts"] += 1
                elif status == "empty":
                    totals["empty_accounts"] += 1
                elif status == "no_sources":
                    totals["no_source_accounts"] += 1
                sources = account.get("sources")
                if isinstance(sources, list):
                    for source in sources:
                        if not isinstance(source, Mapping):
                            continue
                        totals["sources"] += 1
                        if source.get("readable"):
                            totals["readable_sources"] += 1
                        else:
                            totals["unreadable_sources"] += 1
        legacy = instance.get("legacy_plaintext_import")
        if isinstance(legacy, Mapping):
            if _is_nonnegative_integer(legacy.get("sources")):
                totals["legacy_plaintext_sources"] += int(legacy.get("sources") or 0)
            if _is_nonnegative_integer(legacy.get("entries")):
                totals["legacy_plaintext_entries"] += int(legacy.get("entries") or 0)
    return totals


def _memory_recovery_source_structure_errors(instances: Sequence[Any], *, prefix: str) -> list[str]:
    errors: list[str] = []
    valid_statuses = {"recoverable", "unrecoverable", "empty", "no_sources"}
    for instance_index, instance in enumerate(instances):
        if not isinstance(instance, Mapping):
            errors.append(f"{prefix}memory recovery instances[{instance_index}] must be an object")
            continue
        instance_name = str(instance.get("instance") or f"instances[{instance_index}]")
        source_count = instance.get("source_count")
        instance_sources = instance.get("sources")
        if not _is_nonnegative_integer(source_count):
            errors.append(f"{prefix}memory recovery source_count must be a non-negative integer for {instance_name}")
        if not isinstance(instance_sources, list):
            errors.append(f"{prefix}memory recovery sources must be a list for {instance_name}")
            instance_sources = []
        elif _is_nonnegative_integer(source_count) and int(source_count or 0) != len(instance_sources):
            errors.append(f"{prefix}memory recovery source_count must match sources length for {instance_name}")
        instance_source_names: set[str] = set()
        for source_index, source in enumerate(instance_sources):
            source_label = f"{instance_name}.sources[{source_index}]"
            errors.extend(_memory_recovery_source_errors(source, source_label, prefix=prefix, require_payload_fields=False))
            if isinstance(source, Mapping):
                name = str(source.get("name") or "").strip()
                if name:
                    if name in instance_source_names:
                        errors.append(f"{prefix}memory recovery {source_label}.name is duplicated")
                    instance_source_names.add(name)
        accounts = instance.get("accounts")
        if not isinstance(accounts, list):
            errors.append(f"{prefix}memory recovery accounts must be a list for {instance_name}")
            continue
        seen_account_ids: set[str] = set()
        for account_index, account in enumerate(accounts):
            account_label = f"{instance_name}.accounts[{account_index}]"
            if not isinstance(account, Mapping):
                errors.append(f"{prefix}memory recovery {account_label} must be an object")
                continue
            account_id = str(account.get("account_id") or "")
            if not ACCOUNT_ID_RE.fullmatch(account_id):
                errors.append(f"{prefix}memory recovery {account_label}.account_id must be a 128-char hex account id")
            elif account_id in seen_account_ids:
                errors.append(f"{prefix}memory recovery {account_label}.account_id is duplicated")
            seen_account_ids.add(account_id)
            status = str(account.get("recovery_status") or "")
            if status not in valid_statuses:
                errors.append(f"{prefix}memory recovery {account_label}.recovery_status must be one of {', '.join(sorted(valid_statuses))}")
            if not isinstance(account.get("recoverable"), bool):
                errors.append(f"{prefix}memory recovery {account_label}.recoverable must be boolean")
            elif bool(account.get("recoverable")) != (status == "recoverable"):
                errors.append(f"{prefix}memory recovery {account_label}.recoverable must match recovery_status")
            sources = account.get("sources")
            if not isinstance(sources, list):
                errors.append(f"{prefix}memory recovery {account_label}.sources must be a list")
                continue
            has_recoverable_payload = False
            for source_index, source in enumerate(sources):
                source_label = f"{account_label}.sources[{source_index}]"
                errors.extend(_memory_recovery_source_errors(source, source_label, prefix=prefix, require_payload_fields=True))
                if not isinstance(source, Mapping):
                    continue
                source_name = str(source.get("name") or "").strip()
                if instance_source_names and source_name and source_name not in instance_source_names:
                    errors.append(f"{prefix}memory recovery {source_label}.name must reference instance sources")
                if _memory_recovery_source_has_recoverable_payload(source):
                    has_recoverable_payload = True
            if status == "recoverable" and not has_recoverable_payload:
                errors.append(f"{prefix}memory recovery {account_label}.recoverable requires at least one readable payload source")
    return errors


def _memory_recovery_source_errors(source: Any, label: str, *, prefix: str, require_payload_fields: bool) -> list[str]:
    if not isinstance(source, Mapping):
        return [f"{prefix}memory recovery {label} must be an object"]
    errors: list[str] = []
    for key in ("name", "kind", "path"):
        if not str(source.get(key) or "").strip():
            errors.append(f"{prefix}memory recovery {label}.{key} must be non-empty")
    if not isinstance(source.get("active"), bool):
        errors.append(f"{prefix}memory recovery {label}.active must be boolean")
    if not require_payload_fields:
        return errors
    if source.get("payload_kind") not in {"encrypted_account_memory", "legacy_plaintext_user_memory"}:
        errors.append(
            f"{prefix}memory recovery {label}.payload_kind must be encrypted_account_memory or legacy_plaintext_user_memory"
        )
    if not isinstance(source.get("readable"), bool):
        errors.append(f"{prefix}memory recovery {label}.readable must be boolean")
    for key in ("entries", "raw_entries"):
        if not _is_nonnegative_integer(source.get(key)):
            errors.append(f"{prefix}memory recovery {label}.{key} must be a non-negative integer")
    for key in ("index_present", "raw_index_present"):
        if not isinstance(source.get(key), bool):
            errors.append(f"{prefix}memory recovery {label}.{key} must be boolean")
    if "error" not in source:
        errors.append(f"{prefix}memory recovery {label}.error must be present")
    elif not isinstance(source.get("error"), str):
        errors.append(f"{prefix}memory recovery {label}.error must be a string")
    partial = source.get("partial")
    fully_readable = source.get("fully_readable")
    if "partial" in source and not isinstance(partial, bool):
        errors.append(f"{prefix}memory recovery {label}.partial must be boolean")
    if "fully_readable" in source and not isinstance(fully_readable, bool):
        errors.append(f"{prefix}memory recovery {label}.fully_readable must be boolean")
    if partial is True:
        if source.get("readable") is not True:
            errors.append(f"{prefix}memory recovery {label}.partial true requires readable=true")
        if not str(source.get("error") or "").strip():
            errors.append(f"{prefix}memory recovery {label}.partial true requires non-empty error")
        if not _memory_recovery_source_has_recoverable_payload(source):
            errors.append(f"{prefix}memory recovery {label}.partial true requires recoverable payload")
    if fully_readable is True:
        if source.get("readable") is not True:
            errors.append(f"{prefix}memory recovery {label}.fully_readable true requires readable=true")
        if str(source.get("error") or "").strip():
            errors.append(f"{prefix}memory recovery {label}.fully_readable true requires empty error")
    if partial is True and fully_readable is True:
        errors.append(f"{prefix}memory recovery {label}.partial and fully_readable cannot both be true")
    return errors


def _memory_recovery_source_has_recoverable_payload(source: Mapping[str, Any]) -> bool:
    if source.get("readable") is not True:
        return False
    if _is_nonnegative_integer(source.get("entries")) and int(source.get("entries") or 0) > 0:
        return True
    return source.get("index_present") is True


def _memory_recovery_legacy_command_errors(instances: Sequence[Any], *, prefix: str) -> list[str]:
    errors: list[str] = []
    for instance in instances:
        if not isinstance(instance, Mapping):
            continue
        legacy = instance.get("legacy_plaintext_import")
        if not isinstance(legacy, Mapping):
            continue
        command = str(legacy.get("dry_run_command") or "")
        instance_name = str(instance.get("instance") or "<unknown>")
        if "scripts/import_legacy_user_memory.py" not in command:
            errors.append(f"{prefix}memory recovery legacy dry_run_command missing import script for {instance_name}")
        if "--replace-unreadable-account-metadata" not in command:
            errors.append(f"{prefix}memory recovery legacy dry_run_command missing metadata replacement flag for {instance_name}")
        if "--json-output" not in command or "--markdown-output" not in command:
            errors.append(f"{prefix}memory recovery legacy dry_run_command must write JSON and Markdown artifacts for {instance_name}")
        errors.extend(_memory_recovery_legacy_users_errors(legacy, instance_name=instance_name, prefix=prefix))
    return errors


def _memory_recovery_legacy_users_errors(legacy: Mapping[str, Any], *, instance_name: str, prefix: str) -> list[str]:
    errors: list[str] = []
    status = str(legacy.get("status") or "").strip()
    valid_statuses = {"available", "missing", "encrypted-only", "malformed-only", "no-users-path", "empty"}
    if status not in valid_statuses:
        errors.append(f"{prefix}memory recovery legacy status must be one of {', '.join(sorted(valid_statuses))} for {instance_name}")
    for key in ("requested_legacy_instances_dir_exists", "legacy_instances_dir_exists", "path_exists"):
        if not isinstance(legacy.get(key), bool):
            errors.append(f"{prefix}memory recovery legacy {key} must be boolean for {instance_name}")
    sources = legacy.get("sources")
    entries = legacy.get("entries")
    if not _is_nonnegative_integer(sources):
        errors.append(f"{prefix}memory recovery legacy sources must be a non-negative integer for {instance_name}")
    if not _is_nonnegative_integer(entries):
        errors.append(f"{prefix}memory recovery legacy entries must be a non-negative integer for {instance_name}")
    users = legacy.get("users")
    if not isinstance(users, list):
        errors.append(f"{prefix}memory recovery legacy users must be a list for {instance_name}")
        return errors
    if _is_nonnegative_integer(sources) and int(sources or 0) != len(users):
        errors.append(f"{prefix}memory recovery legacy users length must match sources for {instance_name}")
    seen_user_ids: set[str] = set()
    summed_entries = 0
    entries_valid = True
    for user_index, user in enumerate(users):
        label = f"{instance_name}.legacy_plaintext_import.users[{user_index}]"
        if not isinstance(user, Mapping):
            errors.append(f"{prefix}memory recovery {label} must be an object")
            entries_valid = False
            continue
        user_id = str(user.get("user_id") or "").strip()
        if not user_id:
            errors.append(f"{prefix}memory recovery {label}.user_id must be non-empty")
        elif user_id in seen_user_ids:
            errors.append(f"{prefix}memory recovery {label}.user_id is duplicated")
        seen_user_ids.add(user_id)
        if not str(user.get("path") or "").strip():
            errors.append(f"{prefix}memory recovery {label}.path must be non-empty")
        user_entries = user.get("entries")
        if not _is_nonnegative_integer(user_entries):
            errors.append(f"{prefix}memory recovery {label}.entries must be a non-negative integer")
            entries_valid = False
            continue
        summed_entries += int(user_entries or 0)
    if entries_valid and _is_nonnegative_integer(entries) and int(entries or 0) != summed_entries:
        errors.append(f"{prefix}memory recovery legacy users entries sum must match entries for {instance_name}")
    if status == "available" and _is_nonnegative_integer(sources) and int(sources or 0) == 0:
        errors.append(f"{prefix}memory recovery legacy status available requires sources for {instance_name}")
    if status == "missing" and legacy.get("requested_legacy_instances_dir_exists") is not False:
        errors.append(f"{prefix}memory recovery legacy status missing requires requested_legacy_instances_dir_exists=false for {instance_name}")
    if status != "missing" and legacy.get("requested_legacy_instances_dir_exists") is False:
        errors.append(f"{prefix}memory recovery legacy missing requested path must use status missing for {instance_name}")
    if status == "no-users-path" and legacy.get("path_exists") is not False:
        errors.append(f"{prefix}memory recovery legacy status no-users-path requires path_exists=false for {instance_name}")
    return errors


def _memory_recovery_metadata_health_errors(instances: Sequence[Any], *, prefix: str) -> list[str]:
    errors: list[str] = []
    for instance_index, instance in enumerate(instances):
        if not isinstance(instance, Mapping):
            continue
        instance_name = str(instance.get("instance") or f"instances[{instance_index}]")
        metadata = instance.get("metadata_health")
        if not isinstance(metadata, Mapping):
            errors.append(f"{prefix}memory recovery metadata_health must be an object for {instance_name}")
            continue
        readable = metadata.get("readable")
        if not isinstance(readable, bool):
            errors.append(f"{prefix}memory recovery metadata_health.readable must be boolean for {instance_name}")
        unreadable_items = metadata.get("unreadable_items")
        if not _is_nonnegative_integer(unreadable_items):
            errors.append(f"{prefix}memory recovery metadata_health.unreadable_items must be a non-negative integer for {instance_name}")
        items = metadata.get("items")
        if not isinstance(items, list):
            errors.append(f"{prefix}memory recovery metadata_health.items must be a list for {instance_name}")
            continue
        if _is_nonnegative_integer(unreadable_items) and int(unreadable_items or 0) != len(items):
            errors.append(f"{prefix}memory recovery metadata_health.unreadable_items must match items length for {instance_name}")
        if readable is True and items:
            errors.append(f"{prefix}memory recovery metadata_health.readable true requires empty items for {instance_name}")
        if readable is False and not items:
            errors.append(f"{prefix}memory recovery metadata_health.readable false requires unreadable items for {instance_name}")
        for item_index, item in enumerate(items):
            label = f"{instance_name}.metadata_health.items[{item_index}]"
            if not isinstance(item, Mapping):
                errors.append(f"{prefix}memory recovery {label} must be an object")
                continue
            if not str(item.get("kind") or "").strip():
                errors.append(f"{prefix}memory recovery {label}.kind must be non-empty")
            if not str(item.get("path") or "").strip():
                errors.append(f"{prefix}memory recovery {label}.path must be non-empty")
            if not str(item.get("error") or "").strip():
                errors.append(f"{prefix}memory recovery {label}.error must be non-empty")
            account_ids = item.get("account_ids", [])
            if not isinstance(account_ids, list):
                errors.append(f"{prefix}memory recovery {label}.account_ids must be a list")
                continue
            invalid_account_ids = [str(account_id) for account_id in account_ids if not ACCOUNT_ID_RE.fullmatch(str(account_id))]
            if invalid_account_ids:
                errors.append(f"{prefix}memory recovery {label}.account_ids contains invalid account ids")
    return errors


def _legacy_import_artifact_errors(argv: Sequence[str]) -> list[str]:
    json_path = _option_path(argv, "--json-output")
    markdown_path = _option_path(argv, "--markdown-output")
    errors: list[str] = []
    if json_path is None:
        errors.append("legacy import artifact missing --json-output for apply_safety validation")
    else:
        if not json_path.exists():
            errors.append(f"legacy import JSON artifact missing: {json_path}")
        else:
            try:
                payload = json.loads(json_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                errors.append(f"legacy import JSON artifact is not valid JSON: {json_path}: {exc}")
            else:
                if not isinstance(payload, dict):
                    errors.append(f"legacy import JSON root must be an object: {json_path}")
                else:
                    errors.extend(_legacy_import_payload_errors(payload, path=json_path))
                    errors.extend(_legacy_import_scope_errors(payload, argv, path=json_path))
    if markdown_path is None:
        errors.append("legacy import artifact missing --markdown-output for report validation")
    else:
        errors.extend(_legacy_import_markdown_artifact_errors(markdown_path))
    return errors


def _legacy_import_markdown_artifact_errors(path: Path) -> list[str]:
    if not path.exists():
        return [f"legacy import markdown artifact missing: {path}"]
    if not path.is_file():
        return [f"legacy import markdown artifact is not a file: {path}"]
    text = path.read_text(encoding="utf-8", errors="replace")
    errors: list[str] = []
    if not text.strip():
        errors.append(f"legacy import markdown artifact is empty: {path}")
    required_sections = {
        "# TeeBotus Legacy User Memory Import": "heading",
        "## Apply Safety": "apply safety section",
        "## Totals": "totals section",
        "## Events": "events section",
        "- apply_allowed_now:": "apply_allowed_now field",
        "- apply_requires_stopped_bot:": "apply_requires_stopped_bot field",
        "- running_bot_process_count:": "running_bot_process_count field",
    }
    for needle, label in required_sections.items():
        if needle not in text:
            errors.append(f"legacy import markdown artifact lacks {label}: {path}")
    if _artifact_text_contains_secret(text):
        errors.append(f"legacy import markdown artifact contains secret-looking content: {path}")
    totals_position = text.find("## Totals")
    events_position = text.find("## Events")
    running_position = text.find("### Running Bot Processes")
    if totals_position != -1 and events_position != -1 and totals_position > events_position:
        errors.append(f"legacy import markdown artifact places totals after events: {path}")
    if totals_position != -1 and running_position != -1 and totals_position > running_position:
        errors.append(f"legacy import markdown artifact places running processes before totals: {path}")
    for line in text.splitlines():
        if "action=`" not in line or "metadata-reset" not in line:
            if "metadata_reset_accounts=`" in line:
                errors.extend(_legacy_import_markdown_reset_accounts_errors(line, path))
            continue
        if "metadata_unreadable" not in line:
            errors.append(f"legacy import markdown artifact metadata-reset event lacks metadata_unreadable flag: {path}")
        errors.extend(_legacy_import_markdown_reset_accounts_errors(line, path))
    return errors


def _legacy_import_markdown_reset_accounts_errors(line: str, path: Path) -> list[str]:
    if "metadata_reset_accounts=`" not in line:
        return []
    errors: list[str] = []
    if "metadata_unreadable" not in line and "metadata-reset" not in line:
        errors.append(f"legacy import markdown artifact metadata_reset_accounts lacks metadata reset context: {path}")
    match = re.search(r"metadata_reset_accounts=`([^`]*)`", line)
    if match is None:
        errors.append(f"legacy import markdown artifact metadata_reset_accounts is malformed: {path}")
        return errors
    tokens = [token.strip() for token in match.group(1).split(",") if token.strip()]
    if not tokens:
        errors.append(f"legacy import markdown artifact metadata_reset_accounts is empty: {path}")
        return errors
    for token in tokens:
        if re.fullmatch(r"[0-9a-f]{12}", token):
            continue
        if re.fullmatch(r"\+[1-9][0-9]*", token):
            continue
        errors.append(f"legacy import markdown artifact metadata_reset_accounts contains invalid short account id: {path}")
        break
    return errors


def _legacy_import_payload_errors(payload: Mapping[str, Any], *, path: Path | None = None) -> list[str]:
    prefix = f"{path}: " if path is not None else ""
    errors: list[str] = []
    if payload.get("schema_version") != 1:
        errors.append(f"{prefix}legacy import report schema_version must be 1")
    mode = str(payload.get("mode") or "").strip()
    if mode not in LEGACY_IMPORT_REPORT_MODES:
        errors.append(f"{prefix}legacy import report mode must be one of {', '.join(sorted(LEGACY_IMPORT_REPORT_MODES))}")
    apply_safety = payload.get("apply_safety")
    if not isinstance(apply_safety, Mapping):
        errors.append(f"{prefix}legacy import report missing apply_safety object")
        return errors
    running_count = apply_safety.get("running_bot_process_count")
    if not _is_nonnegative_integer(running_count):
        errors.append(f"{prefix}apply_safety.running_bot_process_count must be a non-negative integer")
        running_count = 0
    running_processes = apply_safety.get("running_bot_processes")
    if not isinstance(running_processes, list):
        errors.append(f"{prefix}apply_safety.running_bot_processes must be a list")
        running_processes = []
    elif _is_nonnegative_integer(running_count) and len(running_processes) != int(running_count or 0):
        errors.append(f"{prefix}apply_safety.running_bot_process_count must match running_bot_processes length")
    for index, process in enumerate(running_processes):
        if not isinstance(process, Mapping):
            errors.append(f"{prefix}apply_safety.running_bot_processes[{index}] must be an object")
            continue
        if not str(process.get("pid") or "").strip():
            errors.append(f"{prefix}apply_safety.running_bot_processes[{index}] missing pid")
        if not str(process.get("cmdline") or "").strip():
            errors.append(f"{prefix}apply_safety.running_bot_processes[{index}] missing cmdline")
    if not isinstance(apply_safety.get("apply_allowed_now"), bool):
        errors.append(f"{prefix}apply_safety.apply_allowed_now must be boolean")
    if not isinstance(apply_safety.get("apply_requires_stopped_bot"), bool):
        errors.append(f"{prefix}apply_safety.apply_requires_stopped_bot must be boolean")
    message = str(apply_safety.get("message") or "").strip()
    if not message:
        errors.append(f"{prefix}apply_safety.message must be non-empty")
    options = payload.get("options") if isinstance(payload.get("options"), Mapping) else {}
    allow_running_bot = bool(options.get("allow_running_bot"))
    rehearsal_active = bool(options.get("rehearsal_active"))
    if rehearsal_active and mode != "rehearsal-apply":
        errors.append(f"{prefix}legacy import report mode must be rehearsal-apply when rehearsal_active is true")
    if mode == "rehearsal-apply" and not rehearsal_active:
        errors.append(f"{prefix}legacy import report mode rehearsal-apply requires rehearsal_active")
    if mode == "apply-blocked":
        if rehearsal_active:
            errors.append(f"{prefix}legacy import report mode apply-blocked must not be rehearsal_active")
        if allow_running_bot:
            errors.append(f"{prefix}legacy import report mode apply-blocked must not set allow_running_bot")
        if int(running_count or 0) <= 0:
            errors.append(f"{prefix}legacy import report mode apply-blocked requires detected runtime processes")
        if apply_safety.get("apply_allowed_now") is not False:
            errors.append(f"{prefix}apply_safety.apply_allowed_now must be false for apply-blocked reports")
        if apply_safety.get("apply_requires_stopped_bot") is not True:
            errors.append(f"{prefix}apply_safety.apply_requires_stopped_bot must be true for apply-blocked reports")
    if rehearsal_active:
        if apply_safety.get("apply_allowed_now") is not True:
            errors.append(f"{prefix}apply_safety.apply_allowed_now must be true for rehearsal imports")
        if apply_safety.get("apply_requires_stopped_bot") is not False:
            errors.append(f"{prefix}apply_safety.apply_requires_stopped_bot must be false for rehearsal imports")
        if not str(options.get("rehearsal_copy_dir") or "").strip():
            errors.append(f"{prefix}legacy import rehearsal_copy_dir must be non-empty when rehearsal_active is true")
    if int(running_count or 0) > 0 and not allow_running_bot and not rehearsal_active:
        if apply_safety.get("apply_allowed_now") is not False:
            errors.append(f"{prefix}apply_safety.apply_allowed_now must be false while runtime processes are detected")
        if apply_safety.get("apply_requires_stopped_bot") is not True:
            errors.append(f"{prefix}apply_safety.apply_requires_stopped_bot must be true while runtime processes are detected")
    if int(running_count or 0) == 0 and apply_safety.get("apply_requires_stopped_bot") is not False:
        errors.append(f"{prefix}apply_safety.apply_requires_stopped_bot must be false when no runtime processes are detected")
    errors.extend(_legacy_import_event_totals_errors(payload, prefix=prefix))
    return errors


def _legacy_import_event_totals_errors(payload: Mapping[str, Any], *, prefix: str = "") -> list[str]:
    errors: list[str] = []
    totals = payload.get("totals")
    if not isinstance(totals, Mapping):
        return [f"{prefix}legacy import report missing totals object"]
    events = payload.get("events")
    if not isinstance(events, list):
        return [f"{prefix}legacy import report events must be a list"]
    required_total_keys = (
        "sources",
        "imported_sources",
        "skipped_sources",
        "malformed_sources",
        "encrypted_sources",
        "entries_seen",
        "entries_imported",
        "accounts_created",
        "accounts_existing",
        "unreadable_targets",
        "unreadable_metadata",
        "backups_created",
        "metadata_backups_created",
        "account_store_resets",
    )
    for key in required_total_keys:
        if not _is_nonnegative_integer(totals.get(key)):
            errors.append(f"{prefix}legacy import totals.{key} must be a non-negative integer")
    derived = {
        "sources": len(events),
        "entries_seen": 0,
        "entries_imported": 0,
        "accounts_created": 0,
        "accounts_existing": 0,
        "unreadable_targets": 0,
        "unreadable_metadata": 0,
        "malformed_sources": 0,
        "encrypted_sources": 0,
    }
    skipped_sources = 0
    for index, event in enumerate(events):
        label = f"legacy import events[{index}]"
        if not isinstance(event, Mapping):
            errors.append(f"{prefix}{label} must be an object")
            continue
        instance_name = str(event.get("instance") or "").strip()
        legacy_user_id = str(event.get("legacy_user_id") or "").strip()
        identity = str(event.get("identity") or "").strip()
        account_id = str(event.get("account_id") or "").strip()
        if not instance_name:
            errors.append(f"{prefix}{label}.instance must be non-empty")
        if not legacy_user_id:
            errors.append(f"{prefix}{label}.legacy_user_id must be non-empty")
        if identity != f"telegram:user:{legacy_user_id}":
            errors.append(f"{prefix}{label}.identity must match legacy_user_id")
        if not _legacy_import_event_account_id_is_valid(account_id):
            errors.append(f"{prefix}{label}.account_id must be a SHA-512 account id or an allowed dry-run placeholder")
        action = str(event.get("action") or "").strip()
        if not action:
            errors.append(f"{prefix}{label}.action must be non-empty")
        mode = str(payload.get("mode") or "")
        if mode in {"apply", "rehearsal-apply"} and action and not action.startswith("skip-") and not ACCOUNT_ID_RE.fullmatch(account_id):
            errors.append(f"{prefix}{label}.account_id must be concrete for apply imports")
        if action.startswith("skip-"):
            skipped_sources += 1
        entries = event.get("entries")
        imported = event.get("imported")
        entries_count: int | None = None
        imported_count: int | None = None
        if not _is_nonnegative_integer(entries):
            errors.append(f"{prefix}{label}.entries must be a non-negative integer")
        else:
            entries_count = int(entries or 0)
            derived["entries_seen"] += entries_count
        if not _is_nonnegative_integer(imported):
            errors.append(f"{prefix}{label}.imported must be a non-negative integer")
        else:
            imported_count = int(imported or 0)
            derived["entries_imported"] += imported_count
        if entries_count is not None and imported_count is not None and imported_count > entries_count:
            errors.append(f"{prefix}{label}.imported must not exceed entries")
        if action.startswith("skip-") and imported_count not in (None, 0):
            errors.append(f"{prefix}{label}.skip actions must not import entries")
        source_skip_actions = {"skip-empty", "skip-malformed-source", "skip-encrypted-source"}
        if action in {"skip-malformed-source", "skip-encrypted-source"}:
            if account_id != "<not-created>":
                errors.append(f"{prefix}{label}.{action} must use account_id <not-created>")
            if entries_count not in (None, 0) or imported_count not in (None, 0):
                errors.append(f"{prefix}{label}.{action} must have zero entries and zero imported")
            if event.get("account_created") is True:
                errors.append(f"{prefix}{label}.{action} must not create an account")
            if event.get("metadata_unreadable") is True or event.get("target_unreadable") is True:
                errors.append(f"{prefix}{label}.{action} must not claim unreadable target or metadata")
            if not str(event.get("error") or "").strip():
                errors.append(f"{prefix}{label}.{action} must include an error")
            if action == "skip-malformed-source":
                derived["malformed_sources"] += 1
            else:
                derived["encrypted_sources"] += 1
        if action == "skip-empty":
            if account_id != "<not-created>":
                errors.append(f"{prefix}{label}.skip-empty must use account_id <not-created>")
            if entries_count not in (None, 0) or imported_count not in (None, 0):
                errors.append(f"{prefix}{label}.skip-empty must have zero entries and zero imported")
            if event.get("account_created") is True:
                errors.append(f"{prefix}{label}.skip-empty must not create an account")
            if event.get("metadata_unreadable") is True or event.get("target_unreadable") is True:
                errors.append(f"{prefix}{label}.skip-empty must not claim unreadable target or metadata")
        elif account_id == "<not-created>" and action not in source_skip_actions:
            errors.append(f"{prefix}{label}.account_id <not-created> is only valid for source skip actions")
        if action == "skip-unreadable-account-metadata":
            if account_id != "<metadata-unreadable>":
                errors.append(f"{prefix}{label}.skip-unreadable-account-metadata must use account_id <metadata-unreadable>")
            if event.get("metadata_unreadable") is not True:
                errors.append(f"{prefix}{label}.skip-unreadable-account-metadata must set metadata_unreadable")
        elif account_id == "<metadata-unreadable>":
            errors.append(f"{prefix}{label}.account_id <metadata-unreadable> is only valid for skip-unreadable-account-metadata")
        if action == "skip-unreadable-target":
            if event.get("target_unreadable") is not True:
                errors.append(f"{prefix}{label}.skip-unreadable-target must set target_unreadable")
            if imported_count not in (None, 0):
                errors.append(f"{prefix}{label}.skip-unreadable-target must not import entries")
        if event.get("account_created") is True and account_id in {"<not-created>", "<metadata-unreadable>"}:
            errors.append(f"{prefix}{label}.account_created requires a new or concrete account id")
        if event.get("account_created") is True:
            derived["accounts_created"] += 1
        elif ACCOUNT_ID_RE.fullmatch(account_id):
            derived["accounts_existing"] += 1
        if event.get("target_unreadable") is True:
            derived["unreadable_targets"] += 1
        metadata_unreadable = event.get("metadata_unreadable") is True
        if metadata_unreadable or "metadata-reset" in action:
            derived["unreadable_metadata"] += 1
        if "metadata-reset" in action and not metadata_unreadable:
            errors.append(f"{prefix}{label}.metadata_unreadable must be true for metadata-reset actions")
        reset_accounts = event.get("metadata_reset_existing_accounts")
        if reset_accounts is not None:
            if not isinstance(reset_accounts, list):
                errors.append(f"{prefix}{label}.metadata_reset_existing_accounts must be a list")
            else:
                invalid_reset_accounts = [str(account_id) for account_id in reset_accounts if not ACCOUNT_ID_RE.fullmatch(str(account_id))]
                if invalid_reset_accounts:
                    errors.append(f"{prefix}{label}.metadata_reset_existing_accounts contains invalid account ids")
                if not metadata_unreadable and "metadata-reset" not in action:
                    errors.append(f"{prefix}{label}.metadata_reset_existing_accounts requires metadata_unreadable or metadata-reset action")
    if _is_nonnegative_integer(totals.get("sources")) and _is_nonnegative_integer(totals.get("imported_sources")) and _is_nonnegative_integer(totals.get("skipped_sources")):
        imported_sources = int(totals.get("imported_sources") or 0)
        total_sources = int(totals.get("sources") or 0)
        if imported_sources + int(totals.get("skipped_sources") or 0) != total_sources:
            errors.append(f"{prefix}legacy import totals.imported_sources + skipped_sources must equal sources")
        if imported_sources != total_sources - skipped_sources:
            errors.append(f"{prefix}legacy import totals.imported_sources must match non-skipped events")
    for key, value in derived.items():
        if _is_nonnegative_integer(totals.get(key)) and int(totals.get(key) or 0) != value:
            errors.append(f"{prefix}legacy import totals.{key} must match events ({value})")
    return errors


def _legacy_import_event_account_id_is_valid(account_id: str) -> bool:
    return bool(ACCOUNT_ID_RE.fullmatch(account_id) or account_id in {"<new>", "<metadata-unreadable>", "<not-created>"})


def _legacy_import_scope_errors(payload: Mapping[str, Any], argv: Sequence[str], *, path: Path | None = None) -> list[str]:
    expected_instance = _option_value(argv, "--instance")
    if not expected_instance:
        return []
    prefix = f"{path}: " if path is not None else ""
    errors: list[str] = []
    instances = payload.get("instances")
    if instances != [expected_instance]:
        errors.append(f"{prefix}legacy import report instances must equal [{expected_instance}]")
    events = payload.get("events")
    if not isinstance(events, list):
        errors.append(f"{prefix}legacy import report events must be a list")
        return errors
    out_of_scope = sorted(
        {
            str(event.get("instance") or "")
            for event in events
            if isinstance(event, Mapping) and str(event.get("instance") or "") != expected_instance
        }
    )
    if out_of_scope:
        errors.append(f"{prefix}legacy import report contains out-of-scope instances: {', '.join(out_of_scope)}")
    return errors


def _markdown_artifact_errors(path: Path) -> list[str]:
    if not path.exists():
        return [f"benchmark markdown artifact missing: {path}"]
    if not path.is_file():
        return [f"benchmark markdown artifact is not a file: {path}"]
    text = path.read_text(encoding="utf-8", errors="replace")
    errors: list[str] = []
    if not text.strip():
        errors.append(f"benchmark markdown artifact is empty: {path}")
    if "# TeeBotus Benchmarks" not in text:
        errors.append(f"benchmark markdown artifact lacks heading: {path}")
    for marker in (
        "- python:",
        "- platform:",
        "- machine:",
        "- cpu_count:",
        "- quick: True",
        "- include_live: False",
    ):
        if marker not in text:
            errors.append(f"benchmark markdown artifact lacks context marker {marker!r}: {path}")
    if "## Dependencies" not in text:
        errors.append(f"benchmark markdown artifact lacks dependencies section: {path}")
    if "| package | version | status |" not in text:
        errors.append(f"benchmark markdown artifact lacks dependencies table: {path}")
    for dependency in BENCHMARK_CONTEXT_DEPENDENCIES:
        if not re.search(rf"^\| {re.escape(dependency)} \|", text, flags=re.MULTILINE):
            errors.append(f"benchmark markdown artifact lacks {dependency} dependency row: {path}")
    if "## Results" not in text:
        errors.append(f"benchmark markdown artifact lacks results section: {path}")
    if "| name | category | status | mode | iterations | total_ms | throughput_ops_s | errors | payload_bytes | index_bytes | note | details |" not in text:
        errors.append(f"benchmark markdown artifact lacks results table: {path}")
    for name, expected_category in sorted(REQUIRED_BENCHMARK_NAME_CATEGORIES.items()):
        if not re.search(rf"^\| {re.escape(name)} \|", text, flags=re.MULTILINE):
            errors.append(f"benchmark markdown artifact missing required benchmark result {name}: {path}")
        elif not re.search(rf"^\| {re.escape(name)} \| {re.escape(expected_category)} \|", text, flags=re.MULTILINE):
            errors.append(f"benchmark markdown artifact required result {name} category must be {expected_category}: {path}")
    if "## Stable Backend Rankings" not in text:
        errors.append(f"benchmark markdown artifact lacks stable backend rankings section: {path}")
    if "| category | rank | name | mode | throughput_ops_s | total_ms | errors | note |" not in text:
        errors.append(f"benchmark markdown artifact lacks stable backend rankings table: {path}")
    for category in sorted(REQUIRED_BENCHMARK_RANKING_CATEGORIES):
        ranking_rows = re.findall(rf"^\| {re.escape(category)} \| \d+ \|", text, flags=re.MULTILINE)
        if not ranking_rows:
            errors.append(f"benchmark markdown artifact missing required benchmark ranking {category}: {path}")
        elif len(ranking_rows) < REQUIRED_BENCHMARK_MIN_RANKING_CANDIDATES:
            errors.append(
                f"benchmark markdown artifact ranking {category} must compare at least "
                f"{REQUIRED_BENCHMARK_MIN_RANKING_CANDIDATES} candidates: {path}"
            )
    if "## Quality Gate" not in text:
        errors.append(f"benchmark markdown artifact lacks quality gate section: {path}")
    if "- status: ok" not in text:
        errors.append(f"benchmark markdown artifact lacks ok quality/regression status: {path}")
    if "## Regression Check" not in text:
        errors.append(f"benchmark markdown artifact lacks regression section: {path}")
    if "Die Rangliste dokumentiert Messwerte nur" not in text:
        errors.append(f"benchmark markdown artifact lacks no-auto-switching note: {path}")
    if "Standard-Benchmarks nutzen keine echten Provider-Calls und keine Netzsendung." not in text:
        errors.append(f"benchmark markdown artifact lacks no-live-calls note: {path}")
    if _artifact_text_contains_secret(text):
        errors.append(f"benchmark markdown artifact contains secret-looking content: {path}")
    return errors


def _json_benchmark_artifact_errors(path: Path) -> list[str]:
    if not path.exists():
        return [f"benchmark JSON artifact missing: {path}"]
    if not path.is_file():
        return [f"benchmark JSON artifact is not a file: {path}"]
    raw = path.read_text(encoding="utf-8")
    secret_errors = [f"benchmark JSON artifact contains secret-looking content: {path}"] if _artifact_text_contains_secret(raw) else []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [f"benchmark JSON artifact is not valid JSON: {path}: {exc}"]
    return [*secret_errors, *_benchmark_payload_errors(payload, path=path)]


def _benchmark_payload_errors(payload: Any, *, path: Path | None = None) -> list[str]:
    prefix = f"{path}: " if path is not None else ""
    if not isinstance(payload, dict):
        return [f"{prefix}benchmark JSON root must be an object"]
    errors: list[str] = []
    if payload.get("schema_version") != 1:
        errors.append(f"{prefix}schema_version must be 1")
    if payload.get("ok") is not True:
        errors.append(f"{prefix}ok must be true")
    if payload.get("quick") is not True:
        errors.append(f"{prefix}quick must be true for standard Plan2 benchmark artifacts")
    if payload.get("include_live") is not False:
        errors.append(f"{prefix}include_live must be false for standard Plan2 benchmark artifacts")
    if payload.get("live_hf", False) is not False:
        errors.append(f"{prefix}live_hf must be false for standard Plan2 benchmark artifacts")
    if payload.get("live_qdrant", False) is not False:
        errors.append(f"{prefix}live_qdrant must be false for standard Plan2 benchmark artifacts")
    errors.extend(_benchmark_context_errors(payload.get("context"), prefix=prefix))
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        errors.append(f"{prefix}results must be a non-empty list")
    elif not any(isinstance(result, dict) and result.get("ok") is True for result in results):
        errors.append(f"{prefix}results must contain at least one ok result")
    else:
        duplicate_result_names = _duplicate_benchmark_result_names(results)
        if duplicate_result_names:
            errors.append(f"{prefix}benchmark result names must be unique: {', '.join(duplicate_result_names)}")
        categories = {
            str(result.get("category") or "")
            for result in results
            if isinstance(result, dict) and result.get("ok") is True and not result.get("skipped")
        }
        missing_categories = sorted(REQUIRED_BENCHMARK_CATEGORIES - categories)
        if missing_categories:
            errors.append(f"{prefix}benchmark results missing required categories: {', '.join(missing_categories)}")
        successful_names = {
            str(result.get("name") or "")
            for result in results
            if isinstance(result, dict) and result.get("ok") is True and not result.get("skipped")
        }
        missing_bibliothekar_results = sorted(REQUIRED_BIBLIOTHEKAR_BENCHMARK_NAMES - successful_names)
        if missing_bibliothekar_results:
            errors.append(f"{prefix}benchmark results missing required bibliothekar backends: {', '.join(missing_bibliothekar_results)}")
        for index, result in enumerate(results):
            if not isinstance(result, dict):
                errors.append(f"{prefix}results[{index}] must be an object")
                continue
            for key in ("name", "category", "mode", "iterations", "total_ms", "throughput_ops_s", "errors", "payload_bytes", "index_bytes", "details"):
                if key not in result:
                    errors.append(f"{prefix}results[{index}] missing {key}")
            for key in ("total_ms", "throughput_ops_s", "payload_bytes", "index_bytes"):
                if key in result and not _is_nonnegative_number(result.get(key)):
                    errors.append(f"{prefix}results[{index}] {key} must be a non-negative number")
            if "iterations" in result and not _is_nonnegative_integer(result.get("iterations")):
                errors.append(f"{prefix}results[{index}] iterations must be a non-negative integer")
            if "errors" in result and not _is_nonnegative_integer(result.get("errors")):
                errors.append(f"{prefix}results[{index}] errors must be a non-negative integer")
            if "ok" not in result and "skipped" not in result:
                errors.append(f"{prefix}results[{index}] missing ok/skipped status")
            if result.get("skipped"):
                if result.get("ok") is True:
                    errors.append(f"{prefix}results[{index}] skipped result must not be ok")
                if _is_nonnegative_integer(result.get("iterations")) and int(result.get("iterations") or 0) != 0:
                    errors.append(f"{prefix}results[{index}] skipped result iterations must be 0")
                if _is_nonnegative_integer(result.get("errors")) and int(result.get("errors") or 0) != 0:
                    errors.append(f"{prefix}results[{index}] skipped result errors must be 0")
                if not str(result.get("reason") or "").strip():
                    errors.append(f"{prefix}results[{index}] skipped result reason must be non-empty")
                if not str(result.get("mode") or "").strip():
                    errors.append(f"{prefix}results[{index}] skipped result mode must be non-empty")
                details = result.get("details")
                if not isinstance(details, Mapping) or not details:
                    errors.append(f"{prefix}results[{index}] details must be a non-empty object")
                    continue
                missing_counters = sorted(STANDARD_BENCHMARK_FORBIDDEN_CALL_COUNTERS - set(details))
                if missing_counters:
                    errors.append(f"{prefix}results[{index}] details missing standard no-live counters: {', '.join(missing_counters)}")
                for key, value in _forbidden_standard_benchmark_calls(details):
                    errors.append(f"{prefix}results[{index}] details.{key} must be 0 in standard Plan2 benchmark artifacts, got {value}")
                continue
            if "iterations" in result and not _is_positive_integer(result.get("iterations")):
                errors.append(f"{prefix}results[{index}] iterations must be a positive integer")
            if _is_nonnegative_integer(result.get("errors")) and int(result.get("errors") or 0) != 0:
                errors.append(f"{prefix}results[{index}] errors must be 0 for ok standard benchmark results")
            if not result.get("ok"):
                errors.append(f"{prefix}results[{index}] must be ok or skipped")
            if not _is_positive_number(result.get("payload_bytes")) and not _is_positive_number(result.get("index_bytes")):
                errors.append(f"{prefix}results[{index}] must report payload_bytes or index_bytes")
            details = result.get("details")
            if not isinstance(details, Mapping) or not details:
                errors.append(f"{prefix}results[{index}] details must be a non-empty object")
                continue
            if str(result.get("mode") or "local").casefold().startswith("live"):
                errors.append(f"{prefix}results[{index}] must not use live mode in standard Plan2 benchmark artifacts")
            missing_counters = sorted(STANDARD_BENCHMARK_FORBIDDEN_CALL_COUNTERS - set(details))
            if missing_counters:
                errors.append(f"{prefix}results[{index}] details missing standard no-live counters: {', '.join(missing_counters)}")
            for key, value in _forbidden_standard_benchmark_calls(details):
                errors.append(f"{prefix}results[{index}] details.{key} must be 0 in standard Plan2 benchmark artifacts, got {value}")
            if str(result.get("category") or "") == "bibliothekar":
                errors.extend(_bibliothekar_benchmark_detail_errors(details, result_index=index, prefix=prefix))
            if str(result.get("name") or "") == "hf_pool_eval_matrix":
                errors.extend(_hf_pool_eval_benchmark_detail_errors(details, result_index=index, prefix=prefix))
            if str(result.get("name") or "") == "retrieval_embedding_reranker_matrix":
                errors.extend(_retrieval_benchmark_detail_errors(details, result_index=index, prefix=prefix))
            if str(result.get("name") or "") == "pydantic_structured_decisions":
                errors.extend(_pydantic_decision_benchmark_detail_errors(details, result_index=index, prefix=prefix))
        errors.extend(_required_hf_pool_eval_benchmark_errors(results, prefix=prefix))
        errors.extend(_required_retrieval_benchmark_errors(results, prefix=prefix))
        errors.extend(_required_pydantic_decision_benchmark_errors(results, prefix=prefix))
    comparisons = payload.get("comparisons")
    if not isinstance(comparisons, dict):
        errors.append(f"{prefix}comparisons must be an object")
    else:
        if comparisons.get("auto_switching") is not False:
            errors.append(f"{prefix}comparisons.auto_switching must be false")
        if comparisons.get("selection_policy") != BENCHMARK_SELECTION_POLICY:
            errors.append(f"{prefix}comparisons.selection_policy must be {BENCHMARK_SELECTION_POLICY}")
        rankings = comparisons.get("stable_backend_rankings")
        if not isinstance(rankings, list) or not rankings:
            errors.append(f"{prefix}comparisons.stable_backend_rankings must be a non-empty list")
        else:
            ranking_categories = {
                str(ranking.get("category") or "")
                for ranking in rankings
                if isinstance(ranking, dict) and isinstance(ranking.get("candidates"), list) and ranking.get("candidates")
            }
            missing_rankings = sorted(REQUIRED_BENCHMARK_RANKING_CATEGORIES - ranking_categories)
            if missing_rankings:
                errors.append(f"{prefix}benchmark rankings missing required categories: {', '.join(missing_rankings)}")
            successful_results = _successful_benchmark_results_by_name(results)
            skipped_results = _skipped_benchmark_results_by_name(results)
            errors.extend(
                _benchmark_ranking_errors(
                    rankings,
                    successful_results=successful_results,
                    skipped_results=skipped_results,
                    prefix=prefix,
                )
            )
    if isinstance(results, list) and isinstance(comparisons, dict):
        computed_quality_gate = build_benchmark_quality_gate(results, comparisons=comparisons, quick=True, include_live=False)
        if computed_quality_gate.get("ok") is not True:
            for error in computed_quality_gate.get("errors", []):
                errors.append(f"{prefix}computed quality_gate: {error}")
    successful_results_for_regression = _successful_benchmark_results_by_name(results) if isinstance(results, list) else {}
    errors.extend(
        _benchmark_regression_errors(
            payload.get("regression"),
            successful_results=successful_results_for_regression,
            prefix=prefix,
        )
    )
    quality_gate = payload.get("quality_gate")
    if not isinstance(quality_gate, dict):
        errors.append(f"{prefix}quality_gate must be an object")
    else:
        if quality_gate.get("ok") is not True:
            errors.append(f"{prefix}quality_gate.ok must be true")
        if quality_gate.get("status") != "ok":
            errors.append(f"{prefix}quality_gate.status must be ok")
        if not _is_nonnegative_integer(quality_gate.get("checked_results")):
            errors.append(f"{prefix}quality_gate.checked_results must be a non-negative integer")
        elif isinstance(results, list) and int(quality_gate.get("checked_results") or 0) != len(results):
            errors.append(f"{prefix}quality_gate.checked_results must match results length")
        if not _is_nonnegative_integer(quality_gate.get("error_count")):
            errors.append(f"{prefix}quality_gate.error_count must be a non-negative integer")
        elif int(quality_gate.get("error_count") or 0) != 0:
            errors.append(f"{prefix}quality_gate.error_count must be 0")
        if not isinstance(quality_gate.get("errors"), list):
            errors.append(f"{prefix}quality_gate.errors must be a list")
    return errors


def _benchmark_regression_errors(
    regression: Any,
    *,
    successful_results: Mapping[str, Mapping[str, Any]],
    prefix: str = "",
) -> list[str]:
    errors: list[str] = []
    if not isinstance(regression, dict):
        return [f"{prefix}regression must be an object"]
    if "status" not in regression or "failed" not in regression:
        return [f"{prefix}regression must contain status and failed"]
    status = str(regression.get("status") or "")
    if status not in {"not_configured", "ok"}:
        errors.append(f"{prefix}regression.status must be not_configured or ok")
    if regression.get("failed") is not False:
        errors.append(f"{prefix}regression.failed must be false")
    for key in ("max_total_ms_factor", "min_throughput_factor"):
        if key in regression and not _is_positive_number(regression.get(key)):
            errors.append(f"{prefix}regression.{key} must be a positive number")
    entries = regression.get("entries")
    if not isinstance(entries, list):
        errors.append(f"{prefix}regression.entries must be a list")
        entries = []
    if status == "not_configured" and entries:
        errors.append(f"{prefix}regression.entries must be empty when status is not_configured")
    if status == "ok":
        if not str(regression.get("baseline_json") or "").strip():
            errors.append(f"{prefix}regression.baseline_json must be non-empty when status is ok")
        if not entries:
            errors.append(f"{prefix}regression.entries must be non-empty when status is ok")
        matched_results = regression.get("matched_results")
        if not _is_nonnegative_integer(matched_results):
            errors.append(f"{prefix}regression.matched_results must be a non-negative integer when status is ok")
        elif int(matched_results or 0) != len(entries):
            errors.append(f"{prefix}regression.matched_results must match regression entries length")
    seen_names: set[str] = set()
    for index, entry in enumerate(entries):
        entry_prefix = f"{prefix}regression.entries[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{entry_prefix} must be an object")
            continue
        name = str(entry.get("name") or "")
        if not name:
            errors.append(f"{entry_prefix}.name must be non-empty")
        elif name in seen_names:
            errors.append(f"{prefix}regression duplicate entry name: {name}")
        seen_names.add(name)
        if name and name not in successful_results:
            errors.append(f"{entry_prefix} must reference a successful benchmark result")
        entry_status = str(entry.get("status") or "")
        if entry_status != "ok":
            errors.append(f"{entry_prefix}.status must be ok")
        for key in (
            "previous_total_ms",
            "current_total_ms",
            "total_ms_factor",
            "previous_throughput_ops_s",
            "current_throughput_ops_s",
            "throughput_factor",
        ):
            if key not in entry:
                errors.append(f"{entry_prefix}.{key} missing")
            elif not _is_nonnegative_number(entry.get(key)):
                errors.append(f"{entry_prefix}.{key} must be a non-negative number")
        result = successful_results.get(name)
        if result:
            for entry_key, result_key in (
                ("current_total_ms", "total_ms"),
                ("current_throughput_ops_s", "throughput_ops_s"),
            ):
                if entry_key in entry and _is_nonnegative_number(entry.get(entry_key)) and _is_nonnegative_number(result.get(result_key)):
                    if float(entry.get(entry_key) or 0.0) != float(result.get(result_key) or 0.0):
                        errors.append(f"{entry_prefix}.{entry_key} must match current result {result_key}")
    return errors


def _bibliothekar_benchmark_detail_errors(details: Mapping[str, Any], *, result_index: int, prefix: str = "") -> list[str]:
    errors: list[str] = []
    if details.get("provenance_fields_complete") is not True:
        errors.append(f"{prefix}results[{result_index}] bibliothekar provenance_fields_complete must be true")
    missing = details.get("citation_missing_fields")
    if not isinstance(missing, list):
        errors.append(f"{prefix}results[{result_index}] bibliothekar citation_missing_fields must be a list")
    elif missing:
        errors.append(f"{prefix}results[{result_index}] bibliothekar citation_missing_fields must be empty, got: {', '.join(str(item) for item in missing)}")
    required = details.get("citation_required_fields")
    if not isinstance(required, list):
        errors.append(f"{prefix}results[{result_index}] bibliothekar citation_required_fields must be a list")
    else:
        missing_required = sorted(REQUIRED_BIBLIOTHEKAR_CITATION_FIELDS - {str(item) for item in required})
        if missing_required:
            errors.append(f"{prefix}results[{result_index}] bibliothekar citation_required_fields missing: {', '.join(missing_required)}")
    return errors


def _required_pydantic_decision_benchmark_errors(results: Any, *, prefix: str = "") -> list[str]:
    if not isinstance(results, list):
        return []
    for result in results:
        if (
            isinstance(result, Mapping)
            and result.get("ok") is True
            and not result.get("skipped")
            and str(result.get("name") or "") == "pydantic_structured_decisions"
        ):
            return []
    return [f"{prefix}benchmark results missing required pydantic_structured_decisions result"]


def _required_hf_pool_eval_benchmark_errors(results: Any, *, prefix: str = "") -> list[str]:
    if not isinstance(results, list):
        return []
    for result in results:
        if (
            isinstance(result, Mapping)
            and result.get("ok") is True
            and not result.get("skipped")
            and str(result.get("name") or "") == "hf_pool_eval_matrix"
        ):
            return []
    return [f"{prefix}benchmark results missing required hf_pool_eval_matrix result"]


def _hf_pool_eval_benchmark_detail_errors(details: Mapping[str, Any], *, result_index: int, prefix: str = "") -> list[str]:
    errors: list[str] = []
    purposes = details.get("purposes")
    if not isinstance(purposes, list):
        errors.append(f"{prefix}results[{result_index}] hf_pool purposes must be a list")
    else:
        missing = sorted(REQUIRED_HF_POOL_EVAL_PURPOSES - {str(item) for item in purposes})
        if missing:
            errors.append(f"{prefix}results[{result_index}] hf_pool purposes missing required evals: {', '.join(missing)}")
    required_true_flags = {
        "structured_decision_json_valid",
        "psychology_quality_ok",
        "bibliothekar_citation_faithful",
        "summarizer_faithful",
        "provider_failure_fallback",
        "cooldown_fallback",
    }
    for key in sorted(required_true_flags):
        if details.get(key) is not True:
            errors.append(f"{prefix}results[{result_index}] hf_pool {key} must be true")
    errors.extend(
        _required_string_list_errors(
            details.get("routed_purposes"),
            required=REQUIRED_HF_POOL_EVAL_PURPOSES,
            label="hf_pool routed_purposes",
            result_index=result_index,
            prefix=prefix,
        )
    )
    confidence = details.get("structured_decision_confidence")
    if not _is_nonnegative_number(confidence) or float(confidence) > 1:
        errors.append(f"{prefix}results[{result_index}] hf_pool structured_decision_confidence must be between 0 and 1")
    if not _is_positive_number(details.get("normal_chat_median_latency_ms")):
        errors.append(f"{prefix}results[{result_index}] hf_pool normal_chat_median_latency_ms must be positive")
    if not _is_positive_integer(details.get("psychology_quality_score")) or int(details.get("psychology_quality_score") or 0) < 3:
        errors.append(f"{prefix}results[{result_index}] hf_pool psychology_quality_score must be at least 3")
    errors.extend(
        _required_true_mapping_errors(
            details.get("psychology_quality_checks"),
            required=frozenset({"validierend", "keine_diagnose", "kleiner_schritt", "sanft"}),
            label="hf_pool psychology_quality_checks",
            result_index=result_index,
            prefix=prefix,
        )
    )
    errors.extend(
        _required_true_mapping_errors(
            details.get("bibliothekar_citation_fields"),
            required=frozenset({"chunk_id", "file", "locator"}),
            label="hf_pool bibliothekar_citation_fields",
            result_index=result_index,
            prefix=prefix,
        )
    )
    errors.extend(
        _required_true_mapping_errors(
            details.get("summarizer_terms"),
            required=frozenset({"aktivierung", "schlafhygiene", "kleine_aufgaben"}),
            label="hf_pool summarizer_terms",
            result_index=result_index,
            prefix=prefix,
        )
    )
    if details.get("summarizer_hallucinated") is not False:
        errors.append(f"{prefix}results[{result_index}] hf_pool summarizer_hallucinated must be false")
    cooldown_state_key = str(details.get("cooldown_state_key") or "")
    if "/" not in cooldown_state_key or cooldown_state_key.startswith("/") or cooldown_state_key.endswith("/"):
        errors.append(f"{prefix}results[{result_index}] hf_pool cooldown_state_key must be pool-scoped")
    if details.get("cooldown_network_calls") not in {0, 0.0}:
        errors.append(f"{prefix}results[{result_index}] hf_pool cooldown_network_calls must be 0")
    if not _is_positive_integer(details.get("mock_executor_calls")) or int(details.get("mock_executor_calls") or 0) < len(REQUIRED_HF_POOL_EVAL_PURPOSES):
        errors.append(f"{prefix}results[{result_index}] hf_pool mock_executor_calls must cover all eval purposes")
    return errors


def _required_retrieval_benchmark_errors(results: Any, *, prefix: str = "") -> list[str]:
    if not isinstance(results, list):
        return []
    for result in results:
        if (
            isinstance(result, Mapping)
            and result.get("ok") is True
            and not result.get("skipped")
            and str(result.get("name") or "") == "retrieval_embedding_reranker_matrix"
        ):
            return []
    return [f"{prefix}benchmark results missing required retrieval_embedding_reranker_matrix result"]


def _retrieval_benchmark_detail_errors(details: Mapping[str, Any], *, result_index: int, prefix: str = "") -> list[str]:
    errors: list[str] = []
    errors.extend(
        _required_string_list_errors(
            details.get("usermemory_models"),
            required=REQUIRED_RETRIEVAL_USERMEMORY_MODELS,
            label="retrieval usermemory_models",
            result_index=result_index,
            prefix=prefix,
        )
    )
    errors.extend(
        _required_string_list_errors(
            details.get("book_models"),
            required=REQUIRED_RETRIEVAL_BOOK_MODELS,
            label="retrieval book_models",
            result_index=result_index,
            prefix=prefix,
        )
    )
    errors.extend(
        _required_string_list_errors(
            details.get("backend_modes"),
            required=REQUIRED_RETRIEVAL_BACKEND_MODES,
            label="retrieval backend_modes",
            result_index=result_index,
            prefix=prefix,
        )
    )
    comparison = details.get("reranker_comparison")
    if not isinstance(comparison, Mapping):
        errors.append(f"{prefix}results[{result_index}] retrieval reranker_comparison must be an object")
    else:
        if comparison.get("without_reranker_model") != "BAAI/bge-m3":
            errors.append(f"{prefix}results[{result_index}] retrieval without_reranker_model must be BAAI/bge-m3")
        if comparison.get("with_reranker_model") != "BAAI/bge-reranker-v2-m3":
            errors.append(f"{prefix}results[{result_index}] retrieval with_reranker_model must be BAAI/bge-reranker-v2-m3")
        for key in ("without_reranker_top", "with_reranker_top"):
            value = comparison.get(key)
            if not isinstance(value, list) or len(value) < 1:
                errors.append(f"{prefix}results[{result_index}] retrieval {key} must be a non-empty list")
    selected = details.get("backend_selected")
    if not isinstance(selected, Mapping):
        errors.append(f"{prefix}results[{result_index}] retrieval backend_selected must be an object")
    else:
        missing = sorted(REQUIRED_RETRIEVAL_BACKEND_MODES - {str(key) for key in selected})
        if missing:
            errors.append(f"{prefix}results[{result_index}] retrieval backend_selected missing: {', '.join(missing)}")
        for key, value in selected.items():
            if str(key) in REQUIRED_RETRIEVAL_BACKEND_MODES and not _is_positive_integer(value):
                errors.append(f"{prefix}results[{result_index}] retrieval backend_selected.{key} must be a positive integer")
    return errors


def _required_string_list_errors(value: Any, *, required: frozenset[str], label: str, result_index: int, prefix: str = "") -> list[str]:
    if not isinstance(value, list):
        return [f"{prefix}results[{result_index}] {label} must be a list"]
    missing = sorted(required - {str(item) for item in value})
    if missing:
        return [f"{prefix}results[{result_index}] {label} missing: {', '.join(missing)}"]
    return []


def _required_true_mapping_errors(value: Any, *, required: frozenset[str], label: str, result_index: int, prefix: str = "") -> list[str]:
    if not isinstance(value, Mapping):
        return [f"{prefix}results[{result_index}] {label} must be an object"]
    missing = sorted(required - {str(key) for key in value})
    errors: list[str] = []
    if missing:
        errors.append(f"{prefix}results[{result_index}] {label} missing: {', '.join(missing)}")
    false_items = sorted(str(key) for key in required if key in value and value.get(key) is not True)
    if false_items:
        errors.append(f"{prefix}results[{result_index}] {label} entries must be true: {', '.join(false_items)}")
    return errors


def _pydantic_decision_benchmark_detail_errors(details: Mapping[str, Any], *, result_index: int, prefix: str = "") -> list[str]:
    errors: list[str] = []
    schemas = details.get("schemas")
    if not isinstance(schemas, list):
        errors.append(f"{prefix}results[{result_index}] pydantic schemas must be a list")
        return errors
    missing = sorted(REQUIRED_PYDANTIC_DECISION_SCHEMAS - {str(item) for item in schemas})
    if missing:
        errors.append(f"{prefix}results[{result_index}] pydantic schemas missing required decisions: {', '.join(missing)}")
    if not _is_positive_integer(details.get("fake_agent_calls")):
        errors.append(f"{prefix}results[{result_index}] pydantic fake_agent_calls must be a positive integer")
    return errors


def _successful_benchmark_results_by_name(results: Any) -> dict[str, Mapping[str, Any]]:
    if not isinstance(results, list):
        return {}
    successful: dict[str, Mapping[str, Any]] = {}
    for result in results:
        if not isinstance(result, Mapping):
            continue
        name = str(result.get("name") or "")
        if (
            name
            and result.get("ok") is True
            and not result.get("skipped")
            and _is_nonnegative_integer(result.get("errors"))
            and int(result.get("errors") or 0) == 0
        ):
            successful[name] = result
    return successful


def _duplicate_benchmark_result_names(results: Any) -> list[str]:
    if not isinstance(results, list):
        return []
    seen: set[str] = set()
    duplicates: set[str] = set()
    for result in results:
        if not isinstance(result, Mapping):
            continue
        name = str(result.get("name") or "")
        if not name:
            continue
        if name in seen:
            duplicates.add(name)
        seen.add(name)
    return sorted(duplicates)


def _skipped_benchmark_results_by_name(results: Any) -> dict[str, Mapping[str, Any]]:
    if not isinstance(results, list):
        return {}
    skipped: dict[str, Mapping[str, Any]] = {}
    for result in results:
        if not isinstance(result, Mapping):
            continue
        name = str(result.get("name") or "")
        if name and result.get("skipped") is True:
            skipped[name] = result
    return skipped


def _benchmark_ranking_errors(
    rankings: list[Any],
    *,
    successful_results: Mapping[str, Mapping[str, Any]],
    skipped_results: Mapping[str, Mapping[str, Any]],
    prefix: str,
) -> list[str]:
    errors: list[str] = []
    for ranking_index, ranking in enumerate(rankings):
        if not isinstance(ranking, Mapping):
            errors.append(f"{prefix}rankings[{ranking_index}] must be an object")
            continue
        category = str(ranking.get("category") or "")
        fastest_stable = str(ranking.get("fastest_stable") or "")
        candidates = ranking.get("candidates")
        skipped = ranking.get("skipped", [])
        if not category:
            errors.append(f"{prefix}rankings[{ranking_index}] category must be non-empty")
        elif category not in REQUIRED_BENCHMARK_RANKING_CATEGORIES:
            errors.append(f"{prefix}rankings[{ranking_index}] category must be one of required benchmark ranking categories")
        if not isinstance(candidates, list) or not candidates:
            errors.append(f"{prefix}rankings[{ranking_index}] candidates must be a non-empty list")
            continue
        if category in REQUIRED_BENCHMARK_RANKING_CATEGORIES and len(candidates) < REQUIRED_BENCHMARK_MIN_RANKING_CANDIDATES:
            errors.append(
                f"{prefix}rankings[{ranking_index}] {category} must compare at least "
                f"{REQUIRED_BENCHMARK_MIN_RANKING_CANDIDATES} successful candidates"
            )
        expected_ranking_names = BENCHMARK_RANKING_NAME_SETS.get(category, frozenset())
        candidate_names = {
            str(candidate.get("name") or "")
            for candidate in candidates
            if isinstance(candidate, Mapping)
        }
        if category == "bibliothekar":
            missing_bibliothekar_candidates = sorted(REQUIRED_BIBLIOTHEKAR_BENCHMARK_NAMES - candidate_names)
            if missing_bibliothekar_candidates:
                errors.append(
                    f"{prefix}rankings[{ranking_index}] bibliothekar candidates missing required backends: "
                    f"{', '.join(missing_bibliothekar_candidates)}"
                )
        if not fastest_stable:
            errors.append(f"{prefix}rankings[{ranking_index}] fastest_stable must be non-empty")
        if not isinstance(skipped, list):
            errors.append(f"{prefix}rankings[{ranking_index}] skipped must be a list")
            skipped = []
        skipped_names: set[str] = set()
        for skipped_index, skipped_item in enumerate(skipped):
            if not isinstance(skipped_item, Mapping):
                errors.append(f"{prefix}rankings[{ranking_index}].skipped[{skipped_index}] must be an object")
                continue
            skipped_name = str(skipped_item.get("name") or "")
            skipped_mode = str(skipped_item.get("mode") or "")
            skipped_reason = str(skipped_item.get("reason") or "")
            if not skipped_name:
                errors.append(f"{prefix}rankings[{ranking_index}].skipped[{skipped_index}] name must be non-empty")
            elif skipped_name in skipped_names:
                errors.append(f"{prefix}rankings[{ranking_index}] duplicate skipped name: {skipped_name}")
            skipped_names.add(skipped_name)
            if skipped_name and expected_ranking_names and skipped_name not in expected_ranking_names:
                errors.append(
                    f"{prefix}rankings[{ranking_index}].skipped[{skipped_index}] "
                    f"name must belong to {category} ranking benchmark set"
                )
            if not skipped_mode:
                errors.append(f"{prefix}rankings[{ranking_index}].skipped[{skipped_index}] mode must be non-empty")
            if not skipped_reason:
                errors.append(f"{prefix}rankings[{ranking_index}].skipped[{skipped_index}] reason must be non-empty")
            skipped_result = skipped_results.get(skipped_name)
            if skipped_name and skipped_result is None:
                errors.append(f"{prefix}rankings[{ranking_index}].skipped[{skipped_index}] must reference a skipped result")
            elif skipped_result is not None:
                if category and str(skipped_result.get("category") or "") != category:
                    errors.append(f"{prefix}rankings[{ranking_index}].skipped[{skipped_index}] category must match skipped result category")
                if skipped_mode and skipped_mode != str(skipped_result.get("mode") or ""):
                    errors.append(f"{prefix}rankings[{ranking_index}].skipped[{skipped_index}] mode must match skipped result")
                if skipped_reason and skipped_reason != str(skipped_result.get("reason") or ""):
                    errors.append(f"{prefix}rankings[{ranking_index}].skipped[{skipped_index}] reason must match skipped result")
        seen_names: set[str] = set()
        for candidate_index, candidate in enumerate(candidates, start=1):
            if not isinstance(candidate, Mapping):
                errors.append(f"{prefix}rankings[{ranking_index}].candidates[{candidate_index - 1}] must be an object")
                continue
            candidate_name = str(candidate.get("name") or "")
            if not candidate_name:
                errors.append(f"{prefix}rankings[{ranking_index}].candidates[{candidate_index - 1}] name must be non-empty")
            elif candidate_name in seen_names:
                errors.append(f"{prefix}rankings[{ranking_index}] duplicate candidate name: {candidate_name}")
            seen_names.add(candidate_name)
            if candidate_name and expected_ranking_names and candidate_name not in expected_ranking_names:
                errors.append(
                    f"{prefix}rankings[{ranking_index}].candidates[{candidate_index - 1}] "
                    f"name must belong to {category} ranking benchmark set"
                )
            result = successful_results.get(candidate_name)
            if candidate_name and result is None:
                errors.append(f"{prefix}rankings[{ranking_index}].candidates[{candidate_index - 1}] must reference a successful result")
            elif result is not None:
                result_category = str(result.get("category") or "")
                if category and result_category and result_category != category:
                    errors.append(f"{prefix}rankings[{ranking_index}].candidates[{candidate_index - 1}] category must match result category")
                for key in ("mode", "throughput_ops_s", "total_ms", "errors", "payload_bytes", "index_bytes"):
                    if candidate.get(key) != result.get(key):
                        errors.append(f"{prefix}rankings[{ranking_index}].candidates[{candidate_index - 1}] {key} must match result")
            if candidate.get("rank") != candidate_index:
                errors.append(f"{prefix}rankings[{ranking_index}].candidates[{candidate_index - 1}] rank must be {candidate_index}")
            for key in ("throughput_ops_s", "total_ms", "payload_bytes", "index_bytes"):
                if not _is_nonnegative_number(candidate.get(key)):
                    errors.append(f"{prefix}rankings[{ranking_index}].candidates[{candidate_index - 1}] {key} must be a non-negative number")
            if not _is_nonnegative_integer(candidate.get("errors")):
                errors.append(f"{prefix}rankings[{ranking_index}].candidates[{candidate_index - 1}] errors must be a non-negative integer")
            elif int(candidate.get("errors") or 0) != 0:
                errors.append(f"{prefix}rankings[{ranking_index}].candidates[{candidate_index - 1}] errors must be 0")
            if str(candidate.get("mode") or "").casefold().startswith("live"):
                errors.append(f"{prefix}rankings[{ranking_index}].candidates[{candidate_index - 1}] must not use live mode")
            if not _is_positive_number(candidate.get("payload_bytes")) and not _is_positive_number(candidate.get("index_bytes")):
                errors.append(f"{prefix}rankings[{ranking_index}].candidates[{candidate_index - 1}] must report payload_bytes or index_bytes")
        for skipped_name in sorted(skipped_names & seen_names):
            if skipped_name:
                errors.append(f"{prefix}rankings[{ranking_index}] skipped item must not also be a candidate: {skipped_name}")
        first_name = str(candidates[0].get("name") or "") if isinstance(candidates[0], Mapping) else ""
        if fastest_stable and first_name and fastest_stable != first_name:
            errors.append(f"{prefix}rankings[{ranking_index}] fastest_stable must match rank 1 candidate")
        if fastest_stable and fastest_stable in skipped_names:
            errors.append(f"{prefix}rankings[{ranking_index}] fastest_stable must not be skipped")
    return errors


def _systemd_unit_errors(label: str, text: str) -> list[str]:
    errors: list[str] = []
    if not text.strip():
        return ["systemd unit output is empty"]
    if "[Unit]" not in text or "[Service]" not in text or "[Install]" not in text:
        errors.append("systemd unit lacks required sections")
    lines = [line.strip() for line in text.splitlines()]
    if label == "qdrant-systemd-print":
        required = {
            "-p 127.0.0.1:6333:6333": "Qdrant must bind only to 127.0.0.1:6333",
            "-v teebotus-qdrant:/qdrant/storage": "Qdrant storage volume missing",
        }
        for needle, message in required.items():
            if needle not in text:
                errors.append(message)
        preflight_lines = [line for line in lines if line.startswith("ExecStartPre=")]
        if not any("podman volume exists teebotus-qdrant" in line for line in preflight_lines) or not any(
            "podman volume create teebotus-qdrant" in line for line in preflight_lines
        ):
            errors.append("Qdrant volume preflight missing")
        if "qdrant/qdrant:latest" in text or re.search(r"\bqdrant/qdrant(?:\s|$)", text):
            errors.append("Qdrant image must be pinned and must not use latest")
        if "-p 0.0.0.0:" in text or "-p [::]:" in text:
            errors.append("Qdrant unit must not expose public bind hosts")
    elif label == "teebotus-systemd-print":
        required = {
            "EnvironmentFile=-": "TeeBotus EnvironmentFile missing",
            "ExecStartPre=": "TeeBotus env-file permission preflight missing",
            "--check-env-file": "TeeBotus env-file permission check missing",
            "NoNewPrivileges=true": "TeeBotus NoNewPrivileges hardening missing",
            "PrivateTmp=true": "TeeBotus PrivateTmp hardening missing",
            "ExecStart=": "TeeBotus ExecStart missing",
        }
        for needle, message in required.items():
            if needle not in text:
                errors.append(message)
        execstart_lines = [line for line in lines if line.startswith("ExecStart=")]
        if not any("-m TeeBotus --all --channels telegram,signal,matrix" in line for line in execstart_lines):
            errors.append("TeeBotus ExecStart must run the multi-channel bot")
    return errors


def _is_nonnegative_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def _is_positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _is_nonnegative_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_positive_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _benchmark_context_errors(context: Any, *, prefix: str) -> list[str]:
    if not isinstance(context, dict):
        return [f"{prefix}context must be an object with python/platform/cpu/dependency metadata"]
    errors: list[str] = []
    missing = sorted(REQUIRED_BENCHMARK_CONTEXT_KEYS - set(context))
    if missing:
        errors.append(f"{prefix}context missing required keys: {', '.join(missing)}")
    if "cpu_count" in context and not _is_nonnegative_integer(context.get("cpu_count")):
        errors.append(f"{prefix}context.cpu_count must be a non-negative integer")
    dependencies = context.get("dependencies")
    if not isinstance(dependencies, dict) or not dependencies:
        errors.append(f"{prefix}context.dependencies must be a non-empty object")
    else:
        missing_dependencies = sorted(set(BENCHMARK_CONTEXT_DEPENDENCIES) - set(dependencies))
        if missing_dependencies:
            errors.append(f"{prefix}context.dependencies missing required packages: {', '.join(missing_dependencies)}")
        for package in BENCHMARK_CONTEXT_DEPENDENCIES:
            info = dependencies.get(package)
            if not isinstance(info, dict):
                continue
            if not str(info.get("status") or "").strip():
                errors.append(f"{prefix}context.dependencies.{package}.status must be non-empty")
            if "version" not in info:
                errors.append(f"{prefix}context.dependencies.{package}.version must be present")
    for key in ("python", "platform", "machine"):
        if key in context and not str(context.get(key) or "").strip():
            errors.append(f"{prefix}context.{key} must be non-empty")
    return errors


def _forbidden_standard_benchmark_calls(details: Mapping[str, Any]) -> list[tuple[str, int | float]]:
    forbidden: list[tuple[str, int | float]] = []
    for key, value in details.items():
        key_text = str(key)
        if isinstance(value, Mapping):
            forbidden.extend((f"{key_text}.{nested_key}", nested_value) for nested_key, nested_value in _forbidden_standard_benchmark_calls(value))
            continue
        if key_text not in STANDARD_BENCHMARK_FORBIDDEN_CALL_COUNTERS:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if value > 0:
            forbidden.append((key_text, value))
    return forbidden


def _option_path(argv: Sequence[str], option: str) -> Path | None:
    value = _option_value(argv, option)
    return Path(value) if value is not None else None


def _option_value(argv: Sequence[str], option: str) -> str | None:
    try:
        index = argv.index(option)
    except ValueError:
        return None
    value_index = index + 1
    if value_index >= len(argv):
        return None
    return str(argv[value_index])


def _option_paths(argv: Sequence[str], options: Sequence[str]) -> list[tuple[str, Path]]:
    paths: list[tuple[str, Path]] = []
    for option in options:
        path = _option_path(argv, option)
        if path is not None:
            paths.append((option, path))
    return paths


def _runtime_status_broken_lines(output: str) -> list[str]:
    broken: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _runtime_status_line_is_broken(stripped):
            broken.append(stripped)
    return broken


def _runtime_status_missing_required_lines(output: str) -> list[str]:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    required_prefixes = {
        "hf_pool=": "hf_pool health line",
        "llm_route=structured_decision": "structured decision provider line",
        "llm_route=bibliothekar_answer": "bibliothekar Gemini route line",
        "structured_decision=": "structured decision instance line",
        "qdrant=": "qdrant health line",
        "qdrant_collection=teebotus_user_memory": "qdrant user-memory collection line",
        "qdrant_collection=teebotus_bibliothekar_chunks": "qdrant bibliothekar collection line",
    }
    missing: list[str] = []
    for prefix, label in required_prefixes.items():
        if not any(line.startswith(prefix) for line in lines):
            missing.append(f"runtime-status missing {label}: {prefix}")
    missing.extend(_runtime_status_structured_route_errors(lines))
    missing.extend(_runtime_status_bibliothekar_route_errors(lines))
    missing.extend(_runtime_status_account_memory_recovery_errors(lines))
    missing.extend(_runtime_status_account_memory_recovery_legacy_errors(lines))
    return missing


def _runtime_status_structured_route_errors(lines: Sequence[str]) -> list[str]:
    route = next((line for line in lines if line.startswith("llm_route=structured_decision")), "")
    if not route:
        return []
    errors: list[str] = []
    if " profile=hf_pool_structured" not in route:
        errors.append("runtime-status structured decision route must use profile=hf_pool_structured")
    if " provider=hf_pool" not in route:
        errors.append("runtime-status structured decision route must use provider=hf_pool")
    if " model=pool:default#structured_decision" not in route:
        errors.append("runtime-status structured decision route must use model=pool:default#structured_decision")
    if not any(status in route for status in (" status=configured", " status=unavailable")):
        errors.append("runtime-status structured decision route status must be configured or unavailable")
    if " status=unavailable" in route and " fallback=" not in route:
        errors.append("runtime-status unavailable structured decision route must show fallback")
    return errors


def _runtime_status_bibliothekar_route_errors(lines: Sequence[str]) -> list[str]:
    route = next((line for line in lines if line.startswith("llm_route=bibliothekar_answer")), "")
    if not route:
        return []
    errors: list[str] = []
    if " profile=gemini_flash_stateful" not in route:
        errors.append("runtime-status bibliothekar route must use profile=gemini_flash_stateful")
    if " provider=litellm_gemini_stateful" not in route:
        errors.append("runtime-status bibliothekar route must use provider=litellm_gemini_stateful")
    if " model=gemini/gemini-3.5-flash" not in route:
        errors.append("runtime-status bibliothekar route must use model=gemini/gemini-3.5-flash")
    if " google_mode=stateful" not in route:
        errors.append("runtime-status bibliothekar route must show google_mode=stateful")
    if " free_tier_guard=" not in route:
        errors.append("runtime-status bibliothekar route must show free_tier_guard")
    return errors


def _runtime_status_account_memory_recovery_legacy_errors(lines: Sequence[str]) -> list[str]:
    errors: list[str] = []
    for line in lines:
        if not line.startswith("account_memory_recovery_legacy="):
            continue
        fields, orphan_tokens = _runtime_status_fields(line)
        instance_name = fields.get("account_memory_recovery_legacy") or "<unknown>"
        if orphan_tokens:
            errors.append(f"runtime-status account-memory legacy recovery line has unkeyed tokens for {instance_name}: {' '.join(orphan_tokens)}")
        if fields.get("status") != "available":
            errors.append(f"runtime-status account-memory legacy recovery must use status=available for {instance_name}")
        for key in ("sources", "entries"):
            value = fields.get(key)
            if _runtime_status_positive_integer_value(value) is None:
                errors.append(f"runtime-status account-memory legacy recovery {key} must be positive for {instance_name}")
        if not fields.get("path"):
            errors.append(f"runtime-status account-memory legacy recovery must include path for {instance_name}")
        command = fields.get("command", "")
        apply_command = fields.get("apply_command", "")
        legacy_path = fields.get("path", "")
        errors.extend(
            _runtime_status_legacy_recovery_command_errors(
                command,
                instance_name=instance_name,
                command_label="command",
                require_apply=False,
            )
        )
        errors.extend(
            _runtime_status_legacy_recovery_command_errors(
                apply_command,
                instance_name=instance_name,
                command_label="apply_command",
                require_apply=True,
            )
        )
        errors.extend(
            _runtime_status_legacy_recovery_path_errors(
                legacy_path,
                command,
                apply_command,
                instance_name=instance_name,
            )
        )
    return errors


def _runtime_status_account_memory_recovery_errors(lines: Sequence[str]) -> list[str]:
    errors: list[str] = []
    broken_instances = _runtime_status_broken_account_memory_instances(lines)
    recovery_instances: set[str] = set()
    for line in lines:
        if not line.startswith("account_memory_recovery="):
            continue
        fields, orphan_tokens = _runtime_status_fields(line)
        instance_name = fields.get("account_memory_recovery") or "<unknown>"
        recovery_instances.add(instance_name)
        if orphan_tokens:
            errors.append(f"runtime-status account-memory recovery line has unkeyed tokens for {instance_name}: {' '.join(orphan_tokens)}")
        if fields.get("status") != "needed":
            errors.append(f"runtime-status account-memory recovery must use status=needed for {instance_name}")
        errors.extend(
            _runtime_status_recovery_command_errors(
                fields.get("command", ""),
                instance_name=instance_name,
            )
        )
    for instance_name in sorted(broken_instances - recovery_instances):
        errors.append(f"runtime-status account-memory recovery missing for broken account-memory instance {instance_name}")
    return errors


def _runtime_status_broken_account_memory_instances(lines: Sequence[str]) -> set[str]:
    broken_instances: set[str] = set()
    for line in lines:
        if not line.startswith(("account_memory=", "account_memory_metadata=")):
            continue
        if " status=broken" not in line:
            continue
        fields, _orphan_tokens = _runtime_status_fields(line)
        instance_name = fields.get("account_memory_metadata", "")
        if not instance_name:
            instance_name = fields.get("account_memory", "").split("/", 1)[0]
        if instance_name:
            broken_instances.add(instance_name)
    return broken_instances


def _runtime_status_recovery_command_errors(command: str, *, instance_name: str) -> list[str]:
    if not command:
        return [f"runtime-status account-memory recovery missing command for {instance_name}"]
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return [f"runtime-status account-memory recovery command is not shell-parseable for {instance_name}: {exc}"]
    errors: list[str] = []
    if "TeeBotus.admin" not in argv or "memory-recovery" not in argv:
        errors.append(f"runtime-status account-memory recovery command must call TeeBotus.admin memory-recovery for {instance_name}")
    if "--instances-dir" not in argv:
        errors.append(f"runtime-status account-memory recovery command missing --instances-dir for {instance_name}")
    if "--instances" not in argv:
        errors.append(f"runtime-status account-memory recovery command missing --instances for {instance_name}")
    elif _option_value(argv, "--instances") != instance_name:
        errors.append(f"runtime-status account-memory recovery command instance does not match status line for {instance_name}")
    return errors


def _runtime_status_legacy_recovery_command_errors(command: str, *, instance_name: str, command_label: str, require_apply: bool) -> list[str]:
    if not command:
        return [f"runtime-status account-memory legacy recovery missing {command_label} for {instance_name}"]
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return [f"runtime-status account-memory legacy recovery {command_label} is not shell-parseable for {instance_name}: {exc}"]
    errors: list[str] = []
    if "scripts/import_legacy_user_memory.py" not in argv:
        errors.append(f"runtime-status account-memory legacy recovery {command_label} missing import script for {instance_name}")
    if "--legacy-instances-dir" not in argv:
        errors.append(f"runtime-status account-memory legacy recovery {command_label} missing --legacy-instances-dir for {instance_name}")
    if "--target-instances-dir" not in argv:
        errors.append(f"runtime-status account-memory legacy recovery {command_label} missing --target-instances-dir for {instance_name}")
    if "--instance" not in argv:
        errors.append(f"runtime-status account-memory legacy recovery {command_label} missing --instance for {instance_name}")
    elif _option_value(argv, "--instance") != instance_name:
        errors.append(f"runtime-status account-memory legacy recovery {command_label} instance does not match status line for {instance_name}")
    if "--replace-unreadable-account-metadata" not in argv:
        errors.append(f"runtime-status account-memory legacy recovery {command_label} missing metadata replacement flag for {instance_name}")
    if require_apply:
        if "--apply" not in argv:
            errors.append(f"runtime-status account-memory legacy recovery {command_label} missing --apply for {instance_name}")
        if "--replace-unreadable" not in argv:
            errors.append(f"runtime-status account-memory legacy recovery {command_label} missing --replace-unreadable for {instance_name}")
    else:
        if "--apply" in argv:
            errors.append(f"runtime-status account-memory legacy recovery preflight command must not include --apply for {instance_name}")
        if "--json-output" not in argv or "--markdown-output" not in argv:
            errors.append(f"runtime-status account-memory legacy recovery preflight command must write JSON and Markdown artifacts for {instance_name}")
    return errors


def _runtime_status_legacy_recovery_path_errors(legacy_path: str, command: str, apply_command: str, *, instance_name: str) -> list[str]:
    if not legacy_path:
        return []
    errors: list[str] = []
    preflight_legacy_dir = _runtime_status_command_option(command, "--legacy-instances-dir")
    apply_legacy_dir = _runtime_status_command_option(apply_command, "--legacy-instances-dir")
    if preflight_legacy_dir and apply_legacy_dir and preflight_legacy_dir != apply_legacy_dir:
        errors.append(f"runtime-status account-memory legacy recovery command and apply_command legacy paths differ for {instance_name}")
    for command_label, command_legacy_dir in (("command", preflight_legacy_dir), ("apply_command", apply_legacy_dir)):
        if not command_legacy_dir:
            continue
        if not _runtime_status_path_is_equal_or_below(legacy_path, command_legacy_dir):
            errors.append(
                f"runtime-status account-memory legacy recovery path is not below {command_label} --legacy-instances-dir for {instance_name}"
            )
    return errors


def _runtime_status_command_option(command: str, option: str) -> str:
    try:
        argv = shlex.split(command)
    except ValueError:
        return ""
    return _option_value(argv, option) or ""


def _runtime_status_path_is_equal_or_below(path_value: str, root_value: str) -> bool:
    path = Path(path_value).expanduser().resolve(strict=False)
    root = Path(root_value).expanduser().resolve(strict=False)
    return path == root or root in path.parents


def _runtime_status_positive_integer_value(value: str | None) -> int | None:
    try:
        parsed = int(str(value or "").strip())
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _runtime_status_line_is_broken(line: str) -> bool:
    if _runtime_status_line_contains_secret(line):
        return True
    if line.startswith("bibliothekar=") and " store=qdrant" in line and _runtime_status_qdrant_target_is_unsafe(line):
        return True
    if " status=broken" in line:
        return True
    if "account_memory_recovery=" in line and " status=needed" in line:
        return True
    status_by_prefix = {
        "llm=": {"degraded", "missing_key"},
        "ollama=": {"unreachable"},
        "signal_service=": {"unreachable"},
        "signal_account=": {"missing", "unavailable"},
        "matrix_homeserver=": {"unreachable"},
        "local_transcription=": {"unavailable"},
        "bibliothekar=": {"unavailable", "unreachable"},
        "qdrant=": {"unreachable", "disabled"},
        "qdrant_collection=": {"unavailable"},
    }
    for prefix, problem_statuses in status_by_prefix.items():
        if not line.startswith(prefix):
            continue
        return any(f" status={status}" in line for status in problem_statuses)
    return False


def _runtime_status_qdrant_target_is_unsafe(line: str) -> bool:
    target = _runtime_status_field(line, "target")
    if not target:
        return True
    try:
        parsed = urlparse(target)
    except ValueError:
        return True
    if parsed.username or parsed.password:
        return True
    if parsed.query or parsed.fragment:
        return True
    if parsed.path not in {"", "/"}:
        return True
    try:
        port = parsed.port
    except ValueError:
        return True
    if port is None:
        return True
    host = (parsed.hostname or "").strip().casefold()
    if not host:
        host = target.rsplit(":", 1)[0].strip("[]").casefold()
    return host not in LOCAL_RUNTIME_TARGET_HOSTS


def _runtime_status_field(line: str, key: str) -> str:
    prefix = f"{key}="
    for part in line.split():
        if part.startswith(prefix):
            return part[len(prefix) :].strip()
    return ""


def _runtime_status_fields(line: str) -> tuple[dict[str, str], list[str]]:
    try:
        parts = shlex.split(line)
    except ValueError:
        return {}, [line]
    fields: dict[str, str] = {}
    orphan_tokens: list[str] = []
    for part in parts:
        if "=" not in part:
            orphan_tokens.append(part)
            continue
        key, value = part.split("=", 1)
        fields[key] = value
    return fields, orphan_tokens


def _runtime_status_line_contains_secret(line: str) -> bool:
    if any(pattern.search(line) for pattern in RUNTIME_STATUS_SECRET_PATTERNS):
        return True
    if RUNTIME_STATUS_URL_CREDENTIAL_RE.search(line):
        return True
    for match in RUNTIME_STATUS_SECRET_ASSIGNMENT_RE.finditer(line):
        if _secret_assignment_value_is_unsafe(match.group(1), match.group(2)):
            return True
    for match in RUNTIME_STATUS_SECRET_ASSIGNMENT_FRAGMENT_RE.finditer(line):
        if _secret_assignment_value_is_unsafe(match.group(2), match.group(4)):
            return True
    return False


def _artifact_text_contains_secret(text: str) -> bool:
    if any(pattern.search(text) for pattern in RUNTIME_STATUS_SECRET_PATTERNS):
        return True
    if RUNTIME_STATUS_URL_CREDENTIAL_RE.search(text):
        return True
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if payload is not None and _json_payload_contains_secret(payload):
        return True
    for line in text.splitlines():
        if _runtime_status_line_contains_secret(line):
            return True
        for match in SECRET_FIELD_ASSIGNMENT_RE.finditer(line):
            if _secret_assignment_value_is_unsafe(match.group(1), match.group(2)):
                return True
    for match in ARTIFACT_SECRET_JSON_FIELD_RE.finditer(text):
        key = str(match.group(1) or "").strip().casefold()
        value = str(match.group(2) or "").strip()
        if not value:
            continue
        normalized_value = value.casefold()
        if normalized_value in SAFE_RUNTIME_STATUS_SECRET_PLACEHOLDERS:
            continue
        if _secret_field_value_is_env_reference(key, value):
            continue
        return True
    return False


def _print_console_text(value: object, *, file: Any | None = None) -> None:
    text = _redact_console_text(value)
    print(text, end="" if text.endswith("\n") else "\n", file=sys.stdout if file is None else file)


def _redact_console_text(value: object) -> str:
    text = str(value or "")
    for pattern in RUNTIME_STATUS_SECRET_PATTERNS:
        text = pattern.sub("<redacted-secret>", text)
    text = RUNTIME_STATUS_URL_CREDENTIAL_RE.sub(_redact_console_url_credentials, text)
    text = RUNTIME_STATUS_SECRET_ASSIGNMENT_RE.sub(_redact_console_secret_assignment, text)
    text = RUNTIME_STATUS_SECRET_ASSIGNMENT_FRAGMENT_RE.sub(_redact_console_secret_assignment_fragment, text)
    text = SECRET_FIELD_ASSIGNMENT_RE.sub(_redact_console_secret_assignment, text)
    return ARTIFACT_SECRET_JSON_FIELD_RE.sub(_redact_console_json_secret_field, text)


def _redact_console_url_credentials(match: re.Match[str]) -> str:
    value = match.group(0)
    if "://" in value:
        return value.split("://", 1)[0] + "://<redacted>@"
    if "=" in value:
        return value.split("=", 1)[0] + "=<redacted>@"
    return "<redacted>@"


def _redact_console_secret_assignment(match: re.Match[str]) -> str:
    if not _secret_assignment_value_is_unsafe(match.group(1), match.group(2)):
        return match.group(0)
    prefix = match.group(0)[: match.start(2) - match.start(0)]
    return f"{prefix}<redacted>"


def _redact_console_secret_assignment_fragment(match: re.Match[str]) -> str:
    if not _secret_assignment_value_is_unsafe(match.group(2), match.group(4)):
        return match.group(0)
    return f"{match.group(1)}{match.group(2)}{match.group(3)}<redacted>"


def _redact_console_json_secret_field(match: re.Match[str]) -> str:
    key = str(match.group(1) or "")
    value = str(match.group(2) or "")
    if not _secret_assignment_value_is_unsafe(key, value, allow_status_text_keys=False):
        return match.group(0)
    prefix = match.group(0)[: match.start(2) - match.start(0)]
    suffix = match.group(0)[match.end(2) - match.start(0) :]
    return f"{prefix}<redacted>{suffix}"


def _json_payload_contains_secret(value: Any, *, key_hint: str = "") -> bool:
    if isinstance(value, Mapping):
        for key, nested_value in value.items():
            nested_key = str(key or "")
            if _json_payload_contains_secret(nested_value, key_hint=nested_key):
                return True
        return False
    if isinstance(value, list):
        return any(_json_payload_contains_secret(item, key_hint=key_hint) for item in value)
    if isinstance(value, str):
        if any(pattern.search(value) for pattern in RUNTIME_STATUS_SECRET_PATTERNS):
            return True
        if RUNTIME_STATUS_URL_CREDENTIAL_RE.search(value):
            return True
        if SECRET_FIELD_NAME_RE.search(key_hint):
            return _secret_assignment_value_is_unsafe(key_hint, value, allow_status_text_keys=False)
    return False


def _secret_assignment_value_is_unsafe(key: object, value: object, *, allow_status_text_keys: bool = True) -> bool:
    key_text = str(key or "").strip().casefold().replace("-", "_").replace(" ", "_")
    value_text = str(value or "").strip().strip("\"'`")
    if not value_text:
        return False
    normalized_value = value_text.casefold()
    if normalized_value in SAFE_RUNTIME_STATUS_SECRET_PLACEHOLDERS:
        return False
    if _secret_field_value_is_env_reference(key_text, value_text):
        return False
    if key_text in SAFE_RUNTIME_STATUS_SECRET_METADATA_KEYS and (
        value_text.isdigit() or re.fullmatch(r"\d+/\d+", value_text) is not None
    ):
        return False
    if allow_status_text_keys and key_text in SAFE_RUNTIME_STATUS_SECRET_TEXT_KEYS:
        return False
    if key_text == "account_secrets" and _secret_field_value_is_account_secrets_path(value_text):
        return False
    return True


def _secret_field_value_is_env_reference(key: object, value: object) -> bool:
    key_text = str(key or "").strip().casefold().replace("-", "_").replace(" ", "_")
    value_text = str(value or "").strip()
    return key_text.endswith("_env") and re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", value_text) is not None


def _secret_field_value_is_account_secrets_path(value: object) -> bool:
    value_text = str(value or "").strip().strip("\"'`")
    return value_text.endswith("Account_Secrets.json") and ("/" in value_text or "\\" in value_text)


def _expand_test_patterns(patterns: Sequence[str]) -> list[str]:
    expanded: list[str] = []
    for pattern in patterns:
        if any(char in pattern for char in "*?["):
            matches = sorted(path.relative_to(REPO_ROOT).as_posix() for path in REPO_ROOT.glob(pattern))
            expanded.extend(matches or [pattern])
        else:
            expanded.append(pattern)
    return expanded


def _format_command(argv: Sequence[str]) -> str:
    return " ".join(_quote_arg(part) for part in argv)


def _quote_arg(part: str) -> str:
    if not part:
        return "''"
    if all(char.isalnum() or char in "._/:-=," for char in part):
        return part
    return "'" + part.replace("'", "'\"'\"'") + "'"


if __name__ == "__main__":
    raise SystemExit(main())
