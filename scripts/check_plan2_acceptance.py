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
STANDARD_BENCHMARK_FORBIDDEN_CALL_COUNTERS = frozenset({"network_calls", "openai_calls", "provider_calls", "remote_calls", "llm_calls"})
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


@dataclass(frozen=True)
class AcceptanceCommand:
    label: str
    argv: tuple[str, ...]
    nonfatal: bool = False
    validate_runtime_status: bool = False
    validate_benchmark_artifacts: bool = False
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
        commands.extend(
            [
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
                ),
                AcceptanceCommand(
                    "legacy-import-preflight",
                    (
                        python,
                        "scripts/import_legacy_user_memory.py",
                        "--legacy-instances-dir",
                        str(legacy_instances_dir),
                        "--target-instances-dir",
                        "instances",
                        "--replace-unreadable-account-metadata",
                        "--json-output",
                        str(legacy_import_json_output),
                        "--markdown-output",
                        str(legacy_import_output),
                    ),
                ),
            ]
        )
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
    return errors


def _json_benchmark_artifact_errors(path: Path) -> list[str]:
    if not path.exists():
        return [f"benchmark JSON artifact missing: {path}"]
    if not path.is_file():
        return [f"benchmark JSON artifact is not a file: {path}"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"benchmark JSON artifact is not valid JSON: {path}: {exc}"]
    return _benchmark_payload_errors(payload, path=path)


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
            for key in ("name", "category", "total_ms", "throughput_ops_s", "errors", "payload_bytes", "index_bytes"):
                if key not in result:
                    errors.append(f"{prefix}results[{index}] missing {key}")
            for key in ("total_ms", "throughput_ops_s", "payload_bytes", "index_bytes"):
                if key in result and not _is_nonnegative_number(result.get(key)):
                    errors.append(f"{prefix}results[{index}] {key} must be a non-negative number")
            if "errors" in result and not _is_nonnegative_integer(result.get("errors")):
                errors.append(f"{prefix}results[{index}] errors must be a non-negative integer")
            if "ok" not in result and "skipped" not in result:
                errors.append(f"{prefix}results[{index}] missing ok/skipped status")
            if not result.get("skipped") and str(result.get("mode") or "local").casefold() == "live":
                errors.append(f"{prefix}results[{index}] must not use live mode in standard Plan2 benchmark artifacts")
            details = result.get("details")
            if isinstance(details, Mapping):
                for key, value in _forbidden_standard_benchmark_calls(details):
                    errors.append(f"{prefix}results[{index}] details.{key} must be 0 in standard Plan2 benchmark artifacts, got {value}")
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
    regression = payload.get("regression")
    if not isinstance(regression, dict):
        errors.append(f"{prefix}regression must be an object")
    elif "status" not in regression or "failed" not in regression:
        errors.append(f"{prefix}regression must contain status and failed")
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


def _is_nonnegative_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


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
    try:
        index = argv.index(option)
    except ValueError:
        return None
    value_index = index + 1
    if value_index >= len(argv):
        return None
    return Path(argv[value_index])


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


def _runtime_status_line_contains_secret(line: str) -> bool:
    return any(pattern.search(line) for pattern in RUNTIME_STATUS_SECRET_PATTERNS)


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
