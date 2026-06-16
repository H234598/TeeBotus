#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCHMARK_MD = Path.home() / "Downloads" / "teebotus-benchmarks-latest.md"
DEFAULT_BENCHMARK_JSON = Path.home() / "Downloads" / "teebotus-benchmarks-latest.json"


@dataclass(frozen=True)
class AcceptanceCommand:
    label: str
    argv: tuple[str, ...]
    nonfatal: bool = False
    validate_runtime_status: bool = False


PLAN2_TEST_PATTERNS: tuple[str, ...] = (
    "tests/test_account_store.py",
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
    "tests/test_benchmarks_runner.py",
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
            ),
            AcceptanceCommand(
                "plan2-optional-extras",
                (python, "scripts/check_plan2_optional_extras.py", "--require-installed"),
            ),
            AcceptanceCommand(
                "qdrant-systemd-print",
                (python, "-m", "TeeBotus.qdrant_systemd", "--print"),
            ),
            AcceptanceCommand(
                "teebotus-systemd-print",
                (python, "-m", "TeeBotus.systemd", "--print"),
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
        result = subprocess.run(command.argv, cwd=REPO_ROOT, check=False, text=True, capture_output=command.validate_runtime_status)
        if command.validate_runtime_status:
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
            broken_lines = _runtime_status_broken_lines(result.stdout or "")
            if broken_lines and not command.nonfatal:
                print(f"\nPlan2 acceptance failed at {command.label}: runtime-status reports broken state.", file=sys.stderr)
                for line in broken_lines:
                    print(f"  {line}", file=sys.stderr)
                return 1
    print("\nPlan2 acceptance checks passed.")
    return 0


def _runtime_status_broken_lines(output: str) -> list[str]:
    broken: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if " status=broken" in stripped or "account_memory_recovery=" in stripped and " status=needed" in stripped:
            broken.append(stripped)
    return broken


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
