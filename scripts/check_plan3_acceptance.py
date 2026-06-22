#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from TeeBotus.artifact_outputs import DEFAULT_OBSIDIAN_INCOMING_DIR
from scripts import check_plan2_acceptance  # noqa: E402
from TeeBotus.llm.profiles import load_llm_profiles, load_llm_routing  # noqa: E402
from TeeBotus.llm.router import normalize_llm_provider  # noqa: E402

DEFAULT_BENCHMARK_MD = DEFAULT_OBSIDIAN_INCOMING_DIR / "teebotus-plan3-benchmarks-latest.md"
DEFAULT_BENCHMARK_JSON = DEFAULT_OBSIDIAN_INCOMING_DIR / "teebotus-plan3-benchmarks-latest.json"
DEFAULT_STATE_EVALUATION_MD = DEFAULT_OBSIDIAN_INCOMING_DIR / "teebotus-plan3-benchmarks-latest-2.md"
DEFAULT_PROFILES_PATH = REPO_ROOT / "config" / "llm_profiles.yaml"
DEFAULT_ROUTING_PATH = REPO_ROOT / "config" / "llm_routing.yaml"

STATE_EVALUATION_BENCHMARKS: tuple[tuple[str, str, str], ...] = (
    ("2", "database_fallback_policy", "STATE-2: primary-fallback write/index policy"),
    (
        "3",
        "database_fallback_collection_corruption",
        "STATE-3: collection decrypt-corruption recovery",
    ),
)

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
    parser.add_argument(
        "--state-eval-output",
        default="",
        help=(
            "Optional markdown path for the small state-evaluation document (default: benchmark-output plus -2 suffix), "
            "e.g. ...-latest-2.md"
        ),
    )
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

    benchmark_output = Path(args.benchmark_output)
    state_eval_output = (
        Path(args.state_eval_output)
        if args.state_eval_output
        else (
            DEFAULT_STATE_EVALUATION_MD
            if benchmark_output == DEFAULT_BENCHMARK_MD
            else _default_state_evaluation_output(benchmark_output)
        )
    )

    commands = build_acceptance_commands(
        python=args.python,
        runtime_channels=args.runtime_channels,
        benchmark_output=benchmark_output,
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
    return run_acceptance_commands(commands, state_evaluation_output=state_eval_output)


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


def run_acceptance_commands(commands: Sequence[Plan3Command], *, state_evaluation_output: Path | None = None) -> int:
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
            if not artifact_errors and state_evaluation_output is not None:
                benchmark_json_output = check_plan2_acceptance._option_path(command.argv, "--json-output")
                eval_errors = _write_state_evaluation_document(
                    benchmark_json_output=benchmark_json_output,
                    state_evaluation_output=state_evaluation_output,
                )
                if eval_errors and not command.nonfatal:
                    print(
                        f"\nPlan3 acceptance failed at {command.label}: state evaluation document could not be written.",
                        file=sys.stderr,
                    )
                    for error in eval_errors:
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


def _default_state_evaluation_output(benchmark_output: Path) -> Path:
    suffix = benchmark_output.suffix
    if not suffix:
        return benchmark_output.with_name(f"{benchmark_output.name}-2")
    return benchmark_output.with_name(f"{benchmark_output.name[:-len(suffix)]}-2{suffix}")


def _write_state_evaluation_document(
    *,
    benchmark_json_output: Path | None,
    state_evaluation_output: Path,
) -> list[str]:
    errors: list[str] = []
    payload: Any | None = None

    if benchmark_json_output is None:
        errors.append("benchmark_json_output is missing; cannot evaluate STATE-2/STATE-3")
    else:
        try:
            raw = benchmark_json_output.read_text(encoding="utf-8")
        except OSError as exc:  # noqa: BLE001
            errors.append(f"failed to read benchmark JSON artifact: {benchmark_json_output}: {exc}")
        else:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                errors.append(f"invalid benchmark JSON artifact: {benchmark_json_output}: {exc}")

    benchmark_payload = payload if isinstance(payload, Mapping) else {}
    results_by_name = _index_benchmark_results(benchmark_payload.get("results") if isinstance(benchmark_payload, Mapping) else None)
    lines: list[str] = [
        "# TeeBotus Plan3 Benchmark State Evaluation (Dokument 2)",
        "",
        f"- source_json: {benchmark_json_output}",
        f"- generated_at: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "",
    ]

    for state_no, benchmark_name, headline in STATE_EVALUATION_BENCHMARKS:
        marker = f"STATE-{state_no}"
        lines.append(f"<!-- {marker}:START -->")
        lines.extend(_state_evaluation_lines(marker=marker, headline=headline, benchmark_name=benchmark_name, result=results_by_name.get(benchmark_name)))
        lines.append(f"<!-- {marker}:END -->")
        lines.append("")

    for state_no, benchmark_name, _headline in STATE_EVALUATION_BENCHMARKS:
        marker = f"STATE-{state_no}"
        if benchmark_name not in results_by_name:
            errors.append(f"{marker} missing benchmark result: {benchmark_name}")

    try:
        state_evaluation_output.parent.mkdir(parents=True, exist_ok=True)
        state_evaluation_output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    except OSError as exc:  # noqa: BLE001
        errors.append(f"failed to write state evaluation document: {state_evaluation_output}: {exc}")
    return errors


def _index_benchmark_results(results: Any) -> dict[str, Mapping[str, Any]]:
    if not isinstance(results, list):
        return {}
    indexed: dict[str, Mapping[str, Any]] = {}
    for item in results:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or "").strip()
        if name:
            indexed[name] = item
    return indexed


def _state_evaluation_lines(
    *,
    marker: str,
    headline: str,
    benchmark_name: str,
    result: Mapping[str, Any] | None,
) -> list[str]:
    lines: list[str] = [f"## {headline}", f"- marker: {marker}", f"- benchmark: `{benchmark_name}`"]
    if not isinstance(result, Mapping):
        lines.append("- status: NO_DATA")
        lines.append("- note: benchmark result not present in JSON payload")
        return lines

    ok = bool(result.get("ok", False))
    lines.append(f"- status: {'OK' if ok else 'FAIL'}")
    lines.append(f"- errors: {result.get('errors', 'n/a')}")
    lines.append(f"- iterations: {result.get('iterations', 'n/a')}")
    lines.append(f"- total_ms: {result.get('total_ms', 'n/a')}")
    details = result.get("details")
    if not isinstance(details, Mapping):
        details = {}

    detail_keys = _state_detail_keys_for(marker)
    if detail_keys:
        lines.append("### Kennzahlen")
        lines.append("| Kennzahl | Wert |")
        lines.append("| --- | --- |")
        for key in detail_keys:
            value = details.get(key)
            if value is None:
                continue
            lines.append(f"| {key} | {value} |")
    else:
        lines.append("### Kennzahlen")
        lines.append("- no detail keys configured")
    if isinstance(result.get("note"), str):
        lines.append(f"- note: {result.get('note')}")
    if "details" in result:
        # Keep this list short; avoid dumping the full nested payload.
        if not detail_keys:
            for key in sorted(details.keys()):
                lines.append(f"- {key}: {details.get(key)}")
    return lines


def _state_detail_keys_for(marker: str) -> tuple[str, ...]:
    if marker == "STATE-2":
        return (
            "fallback_warnings",
            "recovery_warnings",
            "synced_entries",
            "synced_index",
            "primary_entry_writes",
            "secondary_entry_writes",
            "primary_index_writes",
            "secondary_index_writes",
        )
    if marker == "STATE-3":
        return (
            "fallback_warnings",
            "recovery_warnings",
            "corrupted_rows_injected",
            "collection_rows_seen",
            "collection_rows_skipped",
            "corrupt_collection_rows_detected",
        )
    return ()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
