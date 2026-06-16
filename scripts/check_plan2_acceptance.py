#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCHMARK_MD = Path.home() / "Downloads" / "teebotus-benchmarks-latest.md"
DEFAULT_BENCHMARK_JSON = Path.home() / "Downloads" / "teebotus-benchmarks-latest.json"
DEFAULT_MEMORY_RECOVERY_JSON = Path.home() / "Downloads" / "teebotus-memory-recovery-with-legacy.json"
DEFAULT_MEMORY_RECOVERY_TEXT = Path.home() / "Downloads" / "teebotus-memory-recovery-with-legacy.md"
DEFAULT_LEGACY_IMPORT_JSON = Path.home() / "Downloads" / "teebotus-legacy-import-preflight.json"
DEFAULT_LEGACY_IMPORT_MD = Path.home() / "Downloads" / "teebotus-legacy-import-preflight.md"
REQUIRED_BENCHMARK_CATEGORIES = frozenset(
    {
        "account_memory",
        "bibliothekar",
        "database_fallback",
        "langgraph_flows",
        "llm_router",
        "mcp_tools",
        "messenger_adapters",
        "proactive_agent",
        "pydantic_ai",
        "status_doctor",
        "transcription_youtube",
    }
)
REQUIRED_BENCHMARK_RANKING_CATEGORIES = frozenset(
    {
        "account_memory",
        "bibliothekar",
        "langgraph_flows",
        "transcription_youtube",
    }
)
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
        "ingested_at",
        "chunk_index",
        "embedding_model",
        "citation_format",
    }
)
STANDARD_BENCHMARK_FORBIDDEN_CALL_COUNTERS = frozenset({"network_calls", "openai_calls", "provider_calls", "remote_calls", "llm_calls"})
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
    r"\b([A-Za-z0-9_]*(?:api[_-]?key|access[_-]?token|auth[_-]?token|bearer[_-]?token|token|secret|password)[A-Za-z0-9_]*)=([^,\s)]+)",
    re.IGNORECASE,
)
SECRET_FIELD_ASSIGNMENT_RE = re.compile(
    r"\b([A-Za-z0-9_ -]*(?:api[_ -]?key|access[_ -]?token|auth[_ -]?token|bearer[_ -]?token|token|secret|password)[A-Za-z0-9_ -]*)\s*[:=]\s*([^,\s)]+)",
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
SAFE_RUNTIME_STATUS_SECRET_PLACEHOLDERS = frozenset({"configured", "none", "<redacted>", "redacted", "missing"})
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
    "tests/test_entrypoint_compatibility.py",
    "tests/test_engine_identity_flows.py",
    "tests/test_export.py",
    "tests/test_file_artifacts.py",
    "tests/test_handlers.py",
    "tests/test_instructions.py",
    "tests/test_matrix_runner.py",
    "tests/test_message_tracking.py",
    "tests/test_notification_loudness.py",
    "tests/test_program_history.py",
    "tests/test_proactive_*.py",
    "tests/test_registration_parser.py",
    "tests/test_runtime_config.py",
    "tests/test_runtime_maintenance.py",
    "tests/test_runtime_state.py",
    "tests/test_signal_runner.py",
    "tests/test_systemd.py",
    "tests/test_tts_dialect.py",
    "tests/test_version_notifications.py",
    "tests/test_weather_context.py",
    "tests/test_working_memory.py",
    "tests/test_llm_config.py",
    "tests/test_llm_client.py",
    "tests/test_litellm_provider.py",
    "tests/test_logic_audit_round5.py",
    "tests/test_llm_router.py",
    "tests/test_llm_package.py",
    "tests/test_openai_client.py",
    "tests/test_bibliothekar.py",
    "tests/test_bibliothekar_*.py",
    "tests/test_pydantic_decisions.py",
    "tests/test_pyproject_metadata.py",
    "tests/test_qdrant_systemd.py",
    "tests/test_reminder_intent.py",
    "tests/test_graphs_*.py",
    "tests/test_mcp_tools.py",
    "tests/test_readme_plan2_docs.py",
    "tests/test_secret_hygiene.py",
    "tests/test_legacy_user_memory_import.py",
    "tests/test_benchmarks_runner.py",
    "tests/test_ci_workflow.py",
    "tests/test_memory_store_benchmark.py",
    "tests/test_plan2_acceptance.py",
    "tests/test_plan2_optional_extras.py",
    "tests/test_youtube_parser_stats.py",
    "tests/test_youtube_parser_misses_report.py",
)


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
    parser.add_argument("--entries", type=int, default=2, help="Synthetic benchmark entries.")
    parser.add_argument("--iterations", type=int, default=1, help="Quick benchmark iterations.")
    parser.add_argument("--skip-runtime-status", action="store_true", help="Skip live runtime-status checks.")
    parser.add_argument("--skip-adapter-deps", action="store_true", help="Skip adapter dependency checks.")
    parser.add_argument("--include-audit", action="store_true", help="Run pip-audit when installed; audit failures are reported but non-fatal.")
    parser.add_argument(
        "--include-qdrant-live",
        action="store_true",
        help="Probe local Qdrant /collections when explicitly requested; failures are non-fatal.",
    )
    parser.add_argument("--list", action="store_true", help="Print commands without executing them.")
    args = parser.parse_args(argv)

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
        entries=args.entries,
        iterations=args.iterations,
        skip_runtime_status=args.skip_runtime_status,
        skip_adapter_deps=args.skip_adapter_deps,
        include_audit=args.include_audit,
        include_qdrant_live=args.include_qdrant_live,
    )
    if args.list:
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
    entries: int = 2,
    iterations: int = 1,
    skip_runtime_status: bool = False,
    skip_adapter_deps: bool = False,
    include_audit: bool = False,
    include_qdrant_live: bool = False,
) -> list[AcceptanceCommand]:
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
            (python, "-m", "pytest", "-q", *_expand_test_patterns(PLAN2_TEST_PATTERNS)),
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
        commands.append(AcceptanceCommand("adapter-deps", (python, "scripts/check_adapter_deps.py")))
    if include_audit:
        audit = shutil.which("pip-audit")
        if audit:
            commands.append(AcceptanceCommand("pip-audit", (audit,), nonfatal=True))
        else:
            commands.append(AcceptanceCommand("pip-audit-missing", (python, "-c", "print('pip-audit not installed; skipped')"), nonfatal=True))
    return commands


def _legacy_memory_acceptance_commands(
    *,
    python: str,
    legacy_instances_dir: Path,
    memory_recovery_output: Path,
    memory_recovery_json_output: Path,
    legacy_import_output: Path,
    legacy_import_json_output: Path,
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
        return ()
    return tuple(
        path.name
        for path in sorted(instances_dir.iterdir())
        if path.is_dir() and (path / "Bot_Verhalten.md").exists()
    )


def _instance_artifact_path(path: Path, instance_name: str) -> Path:
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", instance_name).strip("_") or "instance"
    return path.with_name(f"{path.stem}-{safe_name}{path.suffix}")


def run_acceptance_commands(commands: Sequence[AcceptanceCommand]) -> int:
    for index, command in enumerate(commands, start=1):
        print(f"\n[{index}/{len(commands)}] {command.label}: {_format_command(command.argv)}", flush=True)
        capture_output = command.validate_runtime_status or command.validate_systemd_unit
        result = subprocess.run(command.argv, cwd=REPO_ROOT, check=False, text=True, capture_output=capture_output)
        if capture_output:
            if result.stdout:
                print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
            if result.stderr:
                print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)
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
                    print(f"  {line}", file=sys.stderr)
                return 1
        if command.validate_benchmark_artifacts:
            artifact_errors = _benchmark_artifact_errors(command.argv)
            if artifact_errors and not command.nonfatal:
                print(f"\nPlan2 acceptance failed at {command.label}: benchmark artifacts are invalid.", file=sys.stderr)
                for error in artifact_errors:
                    print(f"  {error}", file=sys.stderr)
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
                    print(f"  {error}", file=sys.stderr)
                return 1
        if command.validate_systemd_unit:
            unit_errors = _systemd_unit_errors(command.label, result.stdout or "")
            if unit_errors and not command.nonfatal:
                print(f"\nPlan2 acceptance failed at {command.label}: systemd unit is unsafe.", file=sys.stderr)
                for error in unit_errors:
                    print(f"  {error}", file=sys.stderr)
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
        "legacy_plaintext_sources": 0,
        "legacy_plaintext_entries": 0,
    }
    for instance in instances:
        if not isinstance(instance, Mapping):
            continue
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
            totals["legacy_plaintext_sources"] += int(legacy.get("sources", 0) or 0)
            totals["legacy_plaintext_entries"] += int(legacy.get("entries", 0) or 0)
    return totals


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
    return errors


def _legacy_import_payload_errors(payload: Mapping[str, Any], *, path: Path | None = None) -> list[str]:
    prefix = f"{path}: " if path is not None else ""
    errors: list[str] = []
    apply_safety = payload.get("apply_safety")
    if not isinstance(apply_safety, Mapping):
        return [f"{prefix}legacy import report missing apply_safety object"]
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
    if int(running_count or 0) > 0 and not allow_running_bot:
        if apply_safety.get("apply_allowed_now") is not False:
            errors.append(f"{prefix}apply_safety.apply_allowed_now must be false while runtime processes are detected")
        if apply_safety.get("apply_requires_stopped_bot") is not True:
            errors.append(f"{prefix}apply_safety.apply_requires_stopped_bot must be true while runtime processes are detected")
    if int(running_count or 0) == 0 and apply_safety.get("apply_requires_stopped_bot") is not False:
        errors.append(f"{prefix}apply_safety.apply_requires_stopped_bot must be false when no runtime processes are detected")
    return errors


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
    if "## Results" not in text:
        errors.append(f"benchmark markdown artifact lacks results section: {path}")
    if "## Regression Check" not in text:
        errors.append(f"benchmark markdown artifact lacks regression section: {path}")
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
    errors.extend(_benchmark_context_errors(payload.get("context"), prefix=prefix))
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        errors.append(f"{prefix}results must be a non-empty list")
    elif not any(isinstance(result, dict) and result.get("ok") is True for result in results):
        errors.append(f"{prefix}results must contain at least one ok result")
    else:
        categories = {
            str(result.get("category") or "")
            for result in results
            if isinstance(result, dict) and result.get("ok") is True and not result.get("skipped")
        }
        missing_categories = sorted(REQUIRED_BENCHMARK_CATEGORIES - categories)
        if missing_categories:
            errors.append(f"{prefix}benchmark results missing required categories: {', '.join(missing_categories)}")
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
            if "errors" in result and not _is_nonnegative_integer(result.get("errors")):
                errors.append(f"{prefix}results[{index}] errors must be a non-negative integer")
            if "ok" not in result and "skipped" not in result:
                errors.append(f"{prefix}results[{index}] missing ok/skipped status")
            if result.get("skipped"):
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
            if str(result.get("mode") or "local").casefold() == "live":
                errors.append(f"{prefix}results[{index}] must not use live mode in standard Plan2 benchmark artifacts")
            missing_counters = sorted(STANDARD_BENCHMARK_FORBIDDEN_CALL_COUNTERS - set(details))
            if missing_counters:
                errors.append(f"{prefix}results[{index}] details missing standard no-live counters: {', '.join(missing_counters)}")
            for key, value in _forbidden_standard_benchmark_calls(details):
                errors.append(f"{prefix}results[{index}] details.{key} must be 0 in standard Plan2 benchmark artifacts, got {value}")
            if str(result.get("category") or "") == "bibliothekar":
                errors.extend(_bibliothekar_benchmark_detail_errors(details, result_index=index, prefix=prefix))
    comparisons = payload.get("comparisons")
    if not isinstance(comparisons, dict):
        errors.append(f"{prefix}comparisons must be an object")
    else:
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
            errors.extend(_benchmark_ranking_errors(rankings, successful_results=successful_results, prefix=prefix))
    regression = payload.get("regression")
    if not isinstance(regression, dict):
        errors.append(f"{prefix}regression must be an object")
    elif "status" not in regression or "failed" not in regression:
        errors.append(f"{prefix}regression must contain status and failed")
    else:
        status = str(regression.get("status") or "")
        if status not in {"not_configured", "ok"}:
            errors.append(f"{prefix}regression.status must be not_configured or ok")
        if regression.get("failed") is not False:
            errors.append(f"{prefix}regression.failed must be false")
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


def _benchmark_ranking_errors(rankings: list[Any], *, successful_results: Mapping[str, Mapping[str, Any]], prefix: str) -> list[str]:
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
        if not isinstance(candidates, list) or not candidates:
            errors.append(f"{prefix}rankings[{ranking_index}] candidates must be a non-empty list")
            continue
        if not fastest_stable:
            errors.append(f"{prefix}rankings[{ranking_index}] fastest_stable must be non-empty")
        if not isinstance(skipped, list):
            errors.append(f"{prefix}rankings[{ranking_index}] skipped must be a list")
            skipped = []
        skipped_names = {
            str(item.get("name") or "")
            for item in skipped
            if isinstance(item, Mapping)
        }
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
            if str(candidate.get("mode") or "").casefold() == "live":
                errors.append(f"{prefix}rankings[{ranking_index}].candidates[{candidate_index - 1}] must not use live mode")
            if not _is_positive_number(candidate.get("payload_bytes")) and not _is_positive_number(candidate.get("index_bytes")):
                errors.append(f"{prefix}rankings[{ranking_index}].candidates[{candidate_index - 1}] must report payload_bytes or index_bytes")
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
    if label == "qdrant-systemd-print":
        required = {
            "ExecStartPre=podman volume create teebotus-qdrant": "Qdrant volume preflight missing",
            "-p 127.0.0.1:6333:6333": "Qdrant must bind only to 127.0.0.1:6333",
            "-v teebotus-qdrant:/qdrant/storage": "Qdrant storage volume missing",
        }
        for needle, message in required.items():
            if needle not in text:
                errors.append(message)
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
            "python3 -m TeeBotus --all --channels telegram,signal,matrix": "TeeBotus ExecStart must run the multi-channel bot",
        }
        for needle, message in required.items():
            if needle not in text:
                errors.append(message)
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
    elif not isinstance(dependencies.get("teebotus"), dict):
        errors.append(f"{prefix}context.dependencies.teebotus must be present")
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
        "llm=": {"missing_key"},
        "ollama=": {"unreachable"},
        "signal_service=": {"unreachable"},
        "signal_account=": {"missing", "unavailable"},
        "matrix_homeserver=": {"unreachable"},
        "local_transcription=": {"unavailable"},
        "bibliothekar=": {"unavailable", "unreachable"},
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
    parsed = urlparse(target)
    if parsed.username or parsed.password:
        return True
    if parsed.query or parsed.fragment:
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


def _runtime_status_line_contains_secret(line: str) -> bool:
    if any(pattern.search(line) for pattern in RUNTIME_STATUS_SECRET_PATTERNS):
        return True
    if RUNTIME_STATUS_URL_CREDENTIAL_RE.search(line):
        return True
    for match in RUNTIME_STATUS_SECRET_ASSIGNMENT_RE.finditer(line):
        if _secret_assignment_value_is_unsafe(match.group(1), match.group(2)):
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
        if key.endswith("_env") or key.endswith("-env") or re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", value):
            continue
        return True
    return False


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
            return _secret_assignment_value_is_unsafe(key_hint, value)
    return False


def _secret_assignment_value_is_unsafe(key: object, value: object) -> bool:
    key_text = str(key or "").strip().casefold().replace("-", "_").replace(" ", "_")
    value_text = str(value or "").strip().strip("\"'`")
    if not value_text:
        return False
    normalized_value = value_text.casefold()
    if normalized_value in SAFE_RUNTIME_STATUS_SECRET_PLACEHOLDERS:
        return False
    if key_text.endswith("_env") or re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", value_text):
        return False
    return True


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
