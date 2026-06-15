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


PLAN2_TEST_PATTERNS: tuple[str, ...] = (
    "tests/test_entrypoint_compatibility.py",
    "tests/test_runtime_config.py",
    "tests/test_llm_config.py",
    "tests/test_llm_client.py",
    "tests/test_litellm_provider.py",
    "tests/test_llm_router.py",
    "tests/test_llm_package.py",
    "tests/test_openai_client.py",
    "tests/test_bibliothekar.py",
    "tests/test_bibliothekar_*.py",
    "tests/test_pydantic_decisions.py",
    "tests/test_reminder_intent.py",
    "tests/test_graphs_*.py",
    "tests/test_mcp_tools.py",
    "tests/test_readme_plan2_docs.py",
    "tests/test_secret_hygiene.py",
    "tests/test_benchmarks_runner.py",
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
) -> list[AcceptanceCommand]:
    commands = [
        AcceptanceCommand("version", (python, "-m", "TeeBotus", "--version")),
    ]
    if not skip_runtime_status:
        commands.append(
            AcceptanceCommand(
                "runtime-status",
                (python, "-m", "TeeBotus", "--runtime-status", "--channels", runtime_channels),
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
                    "Therapie Schlaf",
                    "--top-k",
                    "2",
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
        ]
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
        result = subprocess.run(command.argv, cwd=REPO_ROOT, check=False)
        if result.returncode and not command.nonfatal:
            print(f"\nPlan2 acceptance failed at {command.label} with exit code {result.returncode}.", file=sys.stderr)
            return result.returncode
        if result.returncode and command.nonfatal:
            print(f"\nNon-fatal Plan2 check failed at {command.label} with exit code {result.returncode}.", file=sys.stderr)
    print("\nPlan2 acceptance checks passed.")
    return 0


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
