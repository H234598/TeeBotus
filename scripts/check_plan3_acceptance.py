#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import check_plan2_acceptance  # noqa: E402
from TeeBotus.llm.profiles import load_llm_profiles, load_llm_routing  # noqa: E402
from TeeBotus.llm.router import normalize_llm_provider  # noqa: E402

DEFAULT_BENCHMARK_MD = Path.home() / "Downloads" / "teebotus-plan3-benchmarks-latest.md"
DEFAULT_BENCHMARK_JSON = Path.home() / "Downloads" / "teebotus-plan3-benchmarks-latest.json"
DEFAULT_PROFILES_PATH = REPO_ROOT / "config" / "llm_profiles.yaml"
DEFAULT_ROUTING_PATH = REPO_ROOT / "config" / "llm_routing.yaml"

PLAN3_TEST_FILES: tuple[str, ...] = (
    "tests/test_hf_pool_config.py",
    "tests/test_hf_pool_scheduler.py",
    "tests/test_hf_pool_nonfatal.py",
    "tests/test_hf_pool_doctor.py",
    "tests/test_hf_pool_executor.py",
    "tests/test_hf_pool_fallback_routing.py",
    "tests/test_hf_pool_models_feed.py",
    "tests/test_hf_pool_redaction.py",
    "tests/test_llm_router.py",
    "tests/test_llm_client.py",
    "tests/test_embedding.py",
    "tests/test_embedding_rebuild.py",
    "tests/test_qdrant_health.py",
    "tests/test_qdrant_collections.py",
    "tests/test_qdrant_memory_index.py",
    "tests/test_memory_search_service.py",
    "tests/test_engine_memory_search.py",
    "tests/test_export.py",
    "tests/test_bibliothekar_qdrant_index.py",
    "tests/test_bibliothekar.py",
    "tests/test_bibliothekar_plan2.py",
    "tests/test_decision_schemas.py",
    "tests/test_pydantic_decision_fake_model.py",
    "tests/test_pydantic_decisions.py",
    "tests/test_source_quality.py",
    "tests/test_source_harvester.py",
    "tests/test_graphs_bibliothekar.py",
    "tests/test_graphs_source_harvester.py",
    "tests/test_benchmarks_runner.py",
)


@dataclass(frozen=True)
class Plan3Command:
    label: str
    argv: tuple[str, ...]
    nonfatal: bool = False
    validate_runtime_status: bool = False
    validate_benchmark_artifacts: bool = False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run non-invasive TeeBotus Plan3 acceptance checks.")
    parser.add_argument("--python", default=sys.executable, help="Python executable to use.")
    parser.add_argument("--runtime-channels", default="telegram,signal,matrix", help="Channels for --runtime-status.")
    parser.add_argument("--benchmark-output", default=str(DEFAULT_BENCHMARK_MD), help="Markdown benchmark output path.")
    parser.add_argument("--benchmark-json-output", default=str(DEFAULT_BENCHMARK_JSON), help="JSON benchmark output path.")
    parser.add_argument("--entries", type=int, default=2, help="Synthetic benchmark entries.")
    parser.add_argument("--iterations", type=int, default=1, help="Quick benchmark iterations.")
    parser.add_argument("--skip-runtime-status", action="store_true", help="Skip live runtime-status checks.")
    parser.add_argument("--skip-benchmarks", action="store_true", help="Skip quick benchmark artifact generation.")
    parser.add_argument("--include-live-hf", action="store_true", help="Run explicit live hf_pool doctor checks.")
    parser.add_argument("--check-safe-rollout", action="store_true", help="Run Plan3 static safe-rollout configuration checks.")
    parser.add_argument("--list", action="store_true", help="Print commands without executing them.")
    parser.add_argument("--dry-run", action="store_true", help="Alias for --list; print commands without executing them.")
    args = parser.parse_args(argv)
    if args.check_safe_rollout:
        errors = plan3_safe_rollout_errors()
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            return 1
        print("Plan3 safe-rollout configuration checks passed.")
        return 0

    commands = build_acceptance_commands(
        python=args.python,
        runtime_channels=args.runtime_channels,
        benchmark_output=Path(args.benchmark_output),
        benchmark_json_output=Path(args.benchmark_json_output),
        entries=args.entries,
        iterations=args.iterations,
        skip_runtime_status=args.skip_runtime_status,
        skip_benchmarks=args.skip_benchmarks,
        include_live_hf=args.include_live_hf,
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
    entries: int = 2,
    iterations: int = 1,
    skip_runtime_status: bool = False,
    skip_benchmarks: bool = False,
    include_live_hf: bool = False,
) -> list[Plan3Command]:
    commands: list[Plan3Command] = [
        Plan3Command("version", (python, "-m", "TeeBotus", "--version")),
        Plan3Command("hf-pool-doctor", (python, "-m", "TeeBotus.llm.hf_pool.doctor")),
        Plan3Command("embedding-cli-help", (python, "-m", "TeeBotus.embedding", "--help")),
        Plan3Command("plan3-safe-rollout-config", (python, "scripts/check_plan3_acceptance.py", "--check-safe-rollout")),
    ]
    if not skip_runtime_status:
        commands.append(
            Plan3Command(
                "runtime-status",
                (python, "-m", "TeeBotus", "--runtime-status", "--channels", runtime_channels),
                validate_runtime_status=True,
            )
        )
    commands.extend(
        [
            Plan3Command(
                "embedding-memory-dry-run",
                (python, "-m", "TeeBotus.embedding", "--json", "memory-rebuild", "--dry-run"),
            ),
            Plan3Command(
                "embedding-bibliothekar-dry-run",
                (python, "-m", "TeeBotus.embedding", "--json", "bibliothekar-rebuild", "--dry-run"),
            ),
            Plan3Command("plan3-pytest", (python, "-m", "pytest", "-q", *PLAN3_TEST_FILES)),
        ]
    )
    if include_live_hf:
        commands.append(
            Plan3Command(
                "hf-pool-doctor-live",
                (python, "-m", "TeeBotus.llm.hf_pool.doctor", "--live"),
            )
        )
    if not skip_benchmarks:
        commands.append(
            Plan3Command(
                "plan3-quick-benchmarks",
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
            )
        )
    return commands


def run_acceptance_commands(commands: Sequence[Plan3Command]) -> int:
    for index, command in enumerate(commands, start=1):
        print(f"\n[{index}/{len(commands)}] {command.label}: {_format_command(command.argv)}", flush=True)
        capture_output = command.validate_runtime_status
        result = subprocess.run(command.argv, cwd=REPO_ROOT, check=False, text=True, capture_output=capture_output)
        if capture_output:
            if result.stdout:
                check_plan2_acceptance._print_console_text(result.stdout)
            if result.stderr:
                check_plan2_acceptance._print_console_text(result.stderr, file=sys.stderr)
        if result.returncode and not command.nonfatal:
            print(f"\nPlan3 acceptance failed at {command.label} with exit code {result.returncode}.", file=sys.stderr)
            return result.returncode
        if result.returncode and command.nonfatal:
            print(f"\nNon-fatal Plan3 check failed at {command.label} with exit code {result.returncode}.", file=sys.stderr)
        if command.validate_runtime_status:
            output = "\n".join(part for part in (result.stdout, result.stderr) if part)
            broken_lines = check_plan2_acceptance._runtime_status_broken_lines(output)
            if broken_lines and not command.nonfatal:
                print(f"\nPlan3 acceptance failed at {command.label}: runtime-status reports broken state.", file=sys.stderr)
                for line in broken_lines:
                    print(f"  {check_plan2_acceptance._redact_console_text(line)}", file=sys.stderr)
                return 1
            missing_lines = check_plan2_acceptance._runtime_status_missing_required_lines(output)
            if missing_lines and not command.nonfatal:
                print(f"\nPlan3 acceptance failed at {command.label}: runtime-status is missing required Plan3 lines.", file=sys.stderr)
                for line in missing_lines:
                    print(f"  {check_plan2_acceptance._redact_console_text(line)}", file=sys.stderr)
                return 1
        if command.validate_benchmark_artifacts:
            artifact_errors = check_plan2_acceptance._benchmark_artifact_errors(command.argv)
            if artifact_errors and not command.nonfatal:
                print(f"\nPlan3 acceptance failed at {command.label}: benchmark artifacts are invalid.", file=sys.stderr)
                for error in artifact_errors:
                    print(f"  {check_plan2_acceptance._redact_console_text(error)}", file=sys.stderr)
                return 1
    print("\nPlan3 acceptance checks passed.")
    return 0


def _format_command(argv: Sequence[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in argv)


def plan3_safe_rollout_errors(
    *,
    profiles_path: Path = DEFAULT_PROFILES_PATH,
    routing_path: Path = DEFAULT_ROUTING_PATH,
) -> list[str]:
    profiles = load_llm_profiles(profiles_path)
    default_profile, routing = load_llm_routing(routing_path)
    errors: list[str] = []
    if not default_profile:
        errors.append(f"Plan3 safe-rollout: {routing_path} must define default_profile")
    elif _profile_provider(profiles, default_profile) == "hf_pool":
        errors.append("Plan3 safe-rollout: default_profile must not use provider=hf_pool")
    elif default_profile not in profiles:
        errors.append(f"Plan3 safe-rollout: default_profile references unknown profile {default_profile}")

    normal_chat_rule = routing.get("normal_chat")
    normal_profile = normal_chat_rule.profile if normal_chat_rule is not None else default_profile
    normal_fallback = normal_chat_rule.fallback if normal_chat_rule is not None else ""
    if not normal_profile:
        errors.append("Plan3 safe-rollout: normal_chat must resolve to a profile")
    elif _profile_provider(profiles, normal_profile) == "hf_pool":
        errors.append("Plan3 safe-rollout: normal_chat profile must not use provider=hf_pool")
    elif normal_profile not in profiles:
        errors.append(f"Plan3 safe-rollout: normal_chat references unknown profile {normal_profile}")
    if normal_fallback and _profile_provider(profiles, normal_fallback) == "hf_pool":
        errors.append("Plan3 safe-rollout: normal_chat fallback must not use provider=hf_pool")
    elif normal_fallback and normal_fallback not in profiles:
        errors.append(f"Plan3 safe-rollout: normal_chat fallback references unknown profile {normal_fallback}")
    return errors


def _profile_provider(profiles: object, profile_name: str) -> str:
    if not isinstance(profiles, dict):
        return ""
    profile = profiles.get(str(profile_name or "").strip())
    provider = getattr(profile, "provider", "")
    return normalize_llm_provider(provider) if provider else ""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
