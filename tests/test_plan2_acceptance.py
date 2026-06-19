from __future__ import annotations

import fnmatch
import json
import subprocess
from pathlib import Path

from scripts import check_plan2_acceptance


RANKING_CANDIDATE_NAMES = {
    "account_memory": ("memory_jsonl", "memory_sqlite_projection"),
    "bibliothekar": (
        "bibliothekar_local_query",
        "bibliothekar_llamaindex_fake_query",
        "bibliothekar_haystack_fake_query",
    ),
    "langgraph_flows": ("langgraph_bibliothekar_deep_query", "langgraph_bibliothekar_linear"),
    "retrieval": ("retrieval_backend_haystack_fake", "retrieval_backend_llamaindex_fake", "retrieval_backend_local"),
    "transcription_youtube": (
        "youtube_parser_local",
        "youtube_local_job_queue_no_llm",
        "youtube_local_pipeline_cache_no_openai",
    ),
}


def _valid_ranking(category: str) -> dict:
    candidates = RANKING_CANDIDATE_NAMES.get(category, (f"{category}_benchmark", f"{category}_benchmark_alternate"))
    return {
        "category": category,
        "fastest_stable": candidates[0],
        "candidates": [
            {
                "rank": rank,
                "name": name,
                "mode": "local",
                "throughput_ops_s": 100.0,
                "total_ms": 1.0,
                "errors": 0,
                "payload_bytes": 1,
                "index_bytes": 1,
                "note": "",
            }
            for rank, name in enumerate(candidates, start=1)
        ],
        "skipped": [],
    }


def _valid_dependency_context() -> dict:
    return {
        dependency: {"version": "1.0.0", "status": "installed"}
        for dependency in check_plan2_acceptance.BENCHMARK_CONTEXT_DEPENDENCIES
    } | {"teebotus": {"version": "1.6.13", "status": "worktree"}}


def _valid_benchmark_payload() -> dict:
    payload = {
        "schema_version": 1,
        "quick": True,
        "include_live": False,
        "ok": True,
        "context": {
            "python": "3.14.0",
            "platform": "Linux-test",
            "machine": "x86_64",
            "cpu_count": 4,
            "dependencies": _valid_dependency_context(),
        },
        "results": [
            {
                "name": f"{category}_benchmark",
                "category": category,
                "ok": True,
                "mode": "local",
                "iterations": 1,
                "total_ms": 1.0,
                "throughput_ops_s": 100.0,
                "errors": 0,
                "payload_bytes": 1,
                "index_bytes": 1,
                "details": {
                    "network_calls": 0,
                    "openai_calls": 0,
                    "provider_calls": 0,
                    "remote_calls": 0,
                    "llm_calls": 0,
                },
            }
            for category in sorted(check_plan2_acceptance.REQUIRED_BENCHMARK_CATEGORIES)
        ],
        "comparisons": {
            "auto_switching": False,
            "selection_policy": "document_fastest_stable_backend_only",
            "stable_backend_rankings": [
                _valid_ranking(category)
                for category in sorted(check_plan2_acceptance.REQUIRED_BENCHMARK_RANKING_CATEGORIES)
            ]
        },
        "quality_gate": {
            "status": "ok",
            "ok": True,
            "checked_results": len(check_plan2_acceptance.REQUIRED_BENCHMARK_CATEGORIES),
            "error_count": 0,
            "errors": [],
        },
        "regression": {"status": "not_configured", "failed": False, "entries": []},
    }
    for candidate in _valid_ranking("bibliothekar")["candidates"]:
        payload["results"].append(
            {
                "name": candidate["name"],
                "category": "bibliothekar",
                "ok": True,
                "mode": candidate["mode"],
                "iterations": 1,
                "total_ms": candidate["total_ms"],
                "throughput_ops_s": candidate["throughput_ops_s"],
                "errors": candidate["errors"],
                "payload_bytes": candidate["payload_bytes"],
                "index_bytes": candidate["index_bytes"],
                "details": {
                    "network_calls": 0,
                    "openai_calls": 0,
                    "provider_calls": 0,
                    "remote_calls": 0,
                    "llm_calls": 0,
                },
            }
        )
    payload["results"].append(
        {
            "name": "retrieval_embedding_reranker_matrix",
            "category": "retrieval",
            "ok": True,
            "mode": "local",
            "iterations": 7,
            "total_ms": 1.0,
            "throughput_ops_s": 100.0,
            "errors": 0,
            "payload_bytes": 1,
            "index_bytes": 1,
            "details": {
                "network_calls": 0,
                "openai_calls": 0,
                "provider_calls": 0,
                "remote_calls": 0,
                "llm_calls": 0,
                "usermemory_models": sorted(check_plan2_acceptance.REQUIRED_RETRIEVAL_USERMEMORY_MODELS),
                "book_models": sorted(check_plan2_acceptance.REQUIRED_RETRIEVAL_BOOK_MODELS),
                "backend_modes": sorted(check_plan2_acceptance.REQUIRED_RETRIEVAL_BACKEND_MODES),
                "backend_selected": {"local": 1, "llamaindex_fake": 1, "haystack_fake": 1},
                "reranker_comparison": {
                    "without_reranker_model": "BAAI/bge-m3",
                    "without_reranker_top": [0, 1],
                    "with_reranker_model": "BAAI/bge-reranker-v2-m3",
                    "with_reranker_top": [0, 1],
                },
            },
        }
    )
    payload["results"].append(
        {
            "name": "hf_pool_eval_matrix",
            "category": "hf_pool",
            "ok": True,
            "mode": "local",
            "iterations": 7,
            "total_ms": 1.0,
            "throughput_ops_s": 100.0,
            "errors": 0,
            "payload_bytes": 1,
            "index_bytes": 1,
            "details": {
                "network_calls": 0,
                "openai_calls": 0,
                "provider_calls": 0,
                "remote_calls": 0,
                "llm_calls": 0,
                "purposes": sorted(check_plan2_acceptance.REQUIRED_HF_POOL_EVAL_PURPOSES),
                "routed_purposes": sorted(check_plan2_acceptance.REQUIRED_HF_POOL_EVAL_PURPOSES),
                "structured_decision_json_valid": True,
                "structured_decision_confidence": 0.92,
                "normal_chat_median_latency_ms": 0.5,
                "psychology_quality_score": 4,
                "psychology_quality_checks": {
                    "validierend": True,
                    "keine_diagnose": True,
                    "kleiner_schritt": True,
                    "sanft": True,
                },
                "psychology_quality_ok": True,
                "bibliothekar_citation_faithful": True,
                "bibliothekar_citation_fields": {
                    "chunk_id": True,
                    "file": True,
                    "locator": True,
                },
                "summarizer_faithful": True,
                "summarizer_terms": {
                    "aktivierung": True,
                    "schlafhygiene": True,
                    "kleine_aufgaben": True,
                },
                "summarizer_hallucinated": False,
                "provider_failure_fallback": True,
                "cooldown_fallback": True,
                "cooldown_state_key": "default/bench_normal_chat",
                "cooldown_network_calls": 0,
                "mock_executor_calls": 5,
            },
        }
    )
    payload["results"].append(
        {
            "name": "pydantic_structured_decisions",
            "category": "pydantic_ai",
            "ok": True,
            "mode": "local",
            "iterations": 1,
            "total_ms": 1.0,
            "throughput_ops_s": 100.0,
            "errors": 0,
            "payload_bytes": 1,
            "index_bytes": 1,
            "details": {
                "network_calls": 0,
                "openai_calls": 0,
                "provider_calls": 0,
                "remote_calls": 0,
                "llm_calls": 0,
                "schemas": sorted(check_plan2_acceptance.REQUIRED_PYDANTIC_DECISION_SCHEMAS),
                "fake_agent_calls": 1,
            },
        }
    )
    existing_names = {str(result.get("name") or "") for result in payload["results"]}
    for name, category in sorted(check_plan2_acceptance.REQUIRED_BENCHMARK_NAME_CATEGORIES.items()):
        if name in existing_names:
            continue
        payload["results"].append(
            {
                "name": name,
                "category": category,
                "ok": True,
                "mode": "local",
                "iterations": 1,
                "total_ms": 1.0,
                "throughput_ops_s": 100.0,
                "errors": 0,
                "payload_bytes": 1,
                "index_bytes": 1,
                "details": {
                    "network_calls": 0,
                    "openai_calls": 0,
                    "provider_calls": 0,
                    "remote_calls": 0,
                    "llm_calls": 0,
                },
            }
        )
    payload["quality_gate"]["checked_results"] = len(payload["results"])
    required_fields = sorted(check_plan2_acceptance.REQUIRED_BIBLIOTHEKAR_CITATION_FIELDS)
    for result in payload["results"]:
        if result["category"] != "bibliothekar":
            continue
        result["details"].update(
            {
                "citation_required_fields": required_fields,
                "citation_missing_fields": [],
                "provenance_fields_complete": True,
            }
        )
    return payload


def _write_valid_legacy_import_markdown(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "# TeeBotus Legacy User Memory Import",
                "",
                "## Apply Safety",
                "",
                "- apply_allowed_now: `True`",
                "- apply_requires_stopped_bot: `False`",
                "- running_bot_process_count: `0`",
                "",
                "## Totals",
                "",
                "- entries_imported: `1`",
                "",
                "## Events",
                "",
                "- instance=`Demo` legacy_user=`123` account=`<new>` entries=`1` imported=`1` action=`would-import`",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_apply_blocked_legacy_import_markdown(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "# TeeBotus Legacy User Memory Import",
                "",
                "## Apply Safety",
                "",
                "- apply_allowed_now: `False`",
                "- apply_requires_stopped_bot: `True`",
                "- running_bot_process_count: `1`",
                "",
                "## Totals",
                "",
                "- entries_imported: `1`",
                "",
                "## Events",
                "",
                "- instance=`Demo` legacy_user=`123` account=`<new>` entries=`1` imported=`1` action=`would-import`",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _valid_legacy_import_event(
    *,
    instance: str = "Demo",
    legacy_user_id: str = "123",
    account_id: str = "<new>",
    action: str = "would-import",
    entries: int = 1,
    imported: int = 1,
    account_created: bool = False,
    **extra: object,
) -> dict[str, object]:
    event: dict[str, object] = {
        "instance": instance,
        "legacy_user_id": legacy_user_id,
        "identity": f"telegram:user:{legacy_user_id}",
        "account_id": account_id,
        "action": action,
        "entries": entries,
        "imported": imported,
    }
    if account_created:
        event["account_created"] = True
    event.update(extra)
    return event


def _write_valid_memory_recovery_markdown(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "# TeeBotus Account-Memory Recovery Report",
                "",
                "- generated_at: `2026-06-16T00:00:00+00:00`",
                "- instances_dir: `instances`",
                "",
                "## Totals",
                "",
                "- accounts: `1`",
                "- recoverable_accounts: `0`",
                "",
                "## Instance: Demo",
                "",
                "- source_count: `1`",
                "- metadata_health: readable=`True` unreadable_items=`0`",
                "  - account_secrets: `instances/Demo/data/accounts/Account_Secrets.json` error=encrypted envelope authentication failed",
                "",
                "### Account: " + ("a" * 128),
                "- recovery_status: `empty`",
                "- recoverable: `False`",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _valid_legacy_plaintext_import_payload() -> dict[str, object]:
    return {
        "requested_legacy_instances_dir": "legacy",
        "requested_legacy_instances_dir_exists": True,
        "legacy_instances_dir": "legacy/instances.bak",
        "legacy_instances_dir_exists": True,
        "path": "legacy/instances.bak/Demo/data/users",
        "path_exists": True,
        "status": "available",
        "sources": 1,
        "entries": 2,
        "users": [{"user_id": "2", "entries": 2, "path": "legacy/instances.bak/Demo/data/users/2"}],
        "encrypted_sources": 0,
        "malformed_sources": 0,
        "dry_run_command": (
            "python3 scripts/import_legacy_user_memory.py --legacy-instances-dir legacy "
            "--target-instances-dir instances --instance Demo --replace-unreadable-account-metadata "
            "--json-output out.json --markdown-output out.md"
        ),
        "apply_command": (
            "python3 scripts/import_legacy_user_memory.py --legacy-instances-dir legacy "
            "--target-instances-dir instances --instance Demo --replace-unreadable --replace-unreadable-account-metadata --apply"
        ),
    }


def _valid_memory_recovery_source(
    name: str,
    *,
    kind: str = "sqlite",
    readable: bool = True,
    active: bool = True,
    entries: int = 0,
    raw_entries: int = 0,
    index_present: bool = False,
    raw_index_present: bool = False,
    error: str = "",
    partial: bool | None = None,
    fully_readable: bool | None = None,
) -> dict[str, object]:
    source: dict[str, object] = {
        "name": name,
        "kind": kind,
        "payload_kind": "encrypted_account_memory",
        "path": f"instances/Demo/data/accounts/{name}",
        "active": active,
        "readable": readable,
        "entries": entries,
        "raw_entries": raw_entries,
        "index_present": index_present,
        "raw_index_present": raw_index_present,
        "error": error,
    }
    if partial is not None:
        source["partial"] = partial
    if fully_readable is not None:
        source["fully_readable"] = fully_readable
    return source


def test_plan2_acceptance_commands_cover_non_invasive_plan2_paths(tmp_path: Path) -> None:
    commands = check_plan2_acceptance.build_acceptance_commands(
        python="python-test",
        benchmark_output=tmp_path / "bench.md",
        benchmark_json_output=tmp_path / "bench.json",
        entries=3,
        iterations=2,
        include_audit=True,
    )

    by_label = {command.label: command for command in commands}

    assert by_label["version"].argv == ("python-test", "-m", "TeeBotus", "--version")
    assert by_label["runtime-status"].argv == (
        "python-test",
        "-m",
        "TeeBotus",
        "--runtime-status",
        "--channels",
        "telegram,signal,matrix",
    )
    assert by_label["runtime-status"].validate_runtime_status is True
    for channel in ("telegram", "signal", "matrix"):
        assert by_label[f"runtime-status-{channel}"].argv == (
            "python-test",
            "-m",
            "TeeBotus",
            "--runtime-status",
            "--channels",
            channel,
        )
        assert by_label[f"runtime-status-{channel}"].validate_runtime_status is True
    assert "--all" not in " ".join(" ".join(command.argv) for command in commands)
    pytest_args = by_label["plan2-pytest"].argv
    expected_plan2_tests = check_plan2_acceptance._expand_test_patterns(check_plan2_acceptance.PLAN2_TEST_PATTERNS)
    assert pytest_args[:3] == ("python-test", "-m", "pytest")
    assert pytest_args[3] == "-q"
    assert set(pytest_args[4:]) == set(expected_plan2_tests)
    assert "tests/test_legacy_user_memory_import.py" not in pytest_args
    assert "tests/test_account_memory_migration.py" in pytest_args
    assert "tests/test_runtime_admin_accounts.py" in pytest_args
    assert "tests/test_python313_runtime_setup.py" in pytest_args
    assert "tests/test_proactive_backends.py" in pytest_args
    assert "tests/test_proactive_cli.py" in pytest_args
    assert "tests/test_readme_plan2_docs.py" in pytest_args
    assert "tests/test_secret_hygiene.py" in pytest_args
    assert "tests/test_ci_workflow.py" in pytest_args
    assert "tests/test_telegram_runner.py" in pytest_args
    assert "tests/test_sqlite_backup_sync.py" in pytest_args
    assert by_label["bibliothekar-status"].argv == ("python-test", "-m", "TeeBotus.bibliothekar", "status")
    assert by_label["bibliothekar-dry-run"].argv[-4:] == ("index", "--source", "tests/fixtures/books", "--dry-run")
    assert by_label["bibliothekar-fixture-query"].argv[-4:] == ("tests/fixtures/books", "Testfrage", "--top-k", "3")
    assert by_label["plan2-quick-benchmarks"].argv[-9:] == (
        "--quick",
        "--entries",
        "3",
        "--iterations",
        "2",
        "--output",
        str(tmp_path / "bench.md"),
        "--json-output",
        str(tmp_path / "bench.json"),
    )
    assert by_label["plan2-quick-benchmarks"].validate_benchmark_artifacts is True
    assert by_label["adapter-deps"].argv == ("python-test", "scripts/check_adapter_deps.py")
    assert by_label["plan2-optional-extras"].argv == ("python-test", "scripts/check_plan2_optional_extras.py", "--require-installed")
    assert by_label["qdrant-systemd-print"].argv == ("python-test", "-m", "TeeBotus.qdrant_systemd", "--print")
    assert by_label["qdrant-systemd-print"].validate_systemd_unit is True
    assert by_label["teebotus-systemd-print"].argv == ("python-test", "-m", "TeeBotus.systemd", "--print")
    assert by_label["teebotus-systemd-print"].validate_systemd_unit is True
    assert "memory-recovery-legacy-json" not in by_label
    assert "legacy-import-preflight" not in by_label
    assert any(command.label.startswith("pip-audit") and command.nonfatal for command in commands)


def test_plan2_acceptance_legacy_import_tests_are_explicit_opt_in(tmp_path: Path) -> None:
    commands = check_plan2_acceptance.build_acceptance_commands(
        python="python-test",
        benchmark_output=tmp_path / "bench.md",
        benchmark_json_output=tmp_path / "bench.json",
        include_legacy_import_tests=True,
    )
    by_label = {command.label: command for command in commands}

    assert "tests/test_legacy_user_memory_import.py" in by_label["plan2-pytest"].argv


def test_plan2_acceptance_with_legacy_opt_in_covers_all_repo_unit_tests() -> None:
    patterns = check_plan2_acceptance._plan2_test_patterns(include_legacy_import_tests=True)
    test_files = sorted(str(path) for path in Path("tests").glob("test_*.py"))

    missing = [
        path
        for path in test_files
        if not any(fnmatch.fnmatch(path, pattern) for pattern in patterns)
    ]

    assert missing == []


def test_plan2_acceptance_benchmark_constants_follow_core() -> None:
    from TeeBotus.benchmarks import core as benchmark_core

    assert check_plan2_acceptance.BENCHMARK_RANKING_NAME_SETS == benchmark_core.BENCHMARK_RANKING_NAME_SETS
    assert set(RANKING_CANDIDATE_NAMES) == check_plan2_acceptance.REQUIRED_BENCHMARK_RANKING_CATEGORIES
    for category, names in RANKING_CANDIDATE_NAMES.items():
        assert set(names) <= check_plan2_acceptance.BENCHMARK_RANKING_NAME_SETS[category]
    assert check_plan2_acceptance.REQUIRED_BENCHMARK_CATEGORIES == benchmark_core.REQUIRED_BENCHMARK_CATEGORIES
    assert check_plan2_acceptance.REQUIRED_BENCHMARK_NAME_CATEGORIES == benchmark_core.REQUIRED_BENCHMARK_NAME_CATEGORIES
    assert check_plan2_acceptance.REQUIRED_BENCHMARK_NAMES == benchmark_core.REQUIRED_BENCHMARK_NAMES
    assert check_plan2_acceptance.REQUIRED_BENCHMARK_RANKING_CATEGORIES == benchmark_core.REQUIRED_BENCHMARK_RANKING_CATEGORIES
    assert check_plan2_acceptance.STANDARD_BENCHMARK_FORBIDDEN_CALL_COUNTERS == benchmark_core.STANDARD_BENCHMARK_FORBIDDEN_CALL_COUNTERS


def test_plan2_acceptance_can_skip_live_optional_checks(tmp_path: Path) -> None:
    commands = check_plan2_acceptance.build_acceptance_commands(
        python="python-test",
        benchmark_output=tmp_path / "bench.md",
        benchmark_json_output=tmp_path / "bench.json",
        skip_runtime_status=True,
        skip_adapter_deps=True,
    )

    labels = {command.label for command in commands}

    assert "runtime-status" not in labels
    assert "runtime-status-telegram" not in labels
    assert "runtime-status-signal" not in labels
    assert "runtime-status-matrix" not in labels
    assert "adapter-deps" not in labels
    assert "plan2-pytest" in labels
    assert not any(label.startswith("qdrant-live") for label in labels)


def test_plan2_acceptance_can_run_adapter_deps_python_only(tmp_path: Path) -> None:
    commands = check_plan2_acceptance.build_acceptance_commands(
        python="python-test",
        benchmark_output=tmp_path / "bench.md",
        benchmark_json_output=tmp_path / "bench.json",
        skip_runtime_status=True,
        adapter_deps_python_only=True,
    )
    by_label = {command.label: command for command in commands}

    assert by_label["adapter-deps"].argv == ("python-test", "scripts/check_adapter_deps.py", "--python-only")


def test_plan2_acceptance_rejects_conflicting_adapter_deps_flags(tmp_path: Path) -> None:
    try:
        check_plan2_acceptance.build_acceptance_commands(
            python="python-test",
            benchmark_output=tmp_path / "bench.md",
            benchmark_json_output=tmp_path / "bench.json",
            skip_adapter_deps=True,
            adapter_deps_python_only=True,
        )
    except ValueError as exc:
        assert "adapter_deps_python_only cannot be combined with skip_adapter_deps" in str(exc)
    else:
        raise AssertionError("conflicting adapter dependency flags were accepted")


def test_plan2_acceptance_cli_rejects_conflicting_adapter_deps_flags(capsys) -> None:
    try:
        check_plan2_acceptance.main(["--skip-adapter-deps", "--adapter-deps-python-only", "--dry-run"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("conflicting adapter dependency CLI flags were accepted")

    assert "cannot be combined" in capsys.readouterr().err


def test_plan2_acceptance_dry_run_alias_lists_without_executing(monkeypatch, capsys) -> None:
    def fail_if_executed(_commands):  # noqa: ANN001
        raise AssertionError("--dry-run must not execute acceptance commands")

    monkeypatch.setattr(check_plan2_acceptance, "run_acceptance_commands", fail_if_executed)

    result = check_plan2_acceptance.main(["--dry-run", "--skip-runtime-status", "--skip-adapter-deps"])

    output = capsys.readouterr().out
    assert result == 0
    assert "version:" in output
    assert "plan2-pytest:" in output
    assert "tests/test_legacy_user_memory_import.py" not in output
    assert "runtime-status" not in output
    assert "adapter-deps" not in output


def test_plan2_acceptance_can_include_legacy_memory_preflight(tmp_path: Path) -> None:
    legacy_dir = tmp_path / "instances.bak"
    commands = check_plan2_acceptance.build_acceptance_commands(
        python="python-test",
        benchmark_output=tmp_path / "bench.md",
        benchmark_json_output=tmp_path / "bench.json",
        legacy_instances_dir=legacy_dir,
        memory_recovery_output=tmp_path / "recovery.md",
        memory_recovery_json_output=tmp_path / "recovery.json",
        legacy_import_output=tmp_path / "import.md",
        legacy_import_json_output=tmp_path / "import.json",
        legacy_rehearsal_output=tmp_path / "rehearsal.md",
        legacy_rehearsal_json_output=tmp_path / "rehearsal.json",
        legacy_rehearsal_copy_dir=tmp_path / "teebotus-rehearsal-copy",
    )

    by_label = {command.label: command for command in commands}

    assert by_label["memory-recovery-legacy-json"].argv == (
        "python-test",
        "-m",
        "TeeBotus.admin",
        "memory-recovery",
        "--instances-dir",
        "instances",
        "--legacy-instances-dir",
        str(legacy_dir),
        "--format",
        "json",
        "--output",
        str(tmp_path / "recovery.json"),
    )
    assert by_label["memory-recovery-legacy-text"].argv == (
        "python-test",
        "-m",
        "TeeBotus.admin",
        "memory-recovery",
        "--instances-dir",
        "instances",
        "--legacy-instances-dir",
        str(legacy_dir),
        "--output",
        str(tmp_path / "recovery.md"),
    )
    assert by_label["legacy-import-preflight"].argv == (
        "python-test",
        "scripts/import_legacy_user_memory.py",
        "--legacy-instances-dir",
        str(legacy_dir),
        "--target-instances-dir",
        "instances",
        "--replace-unreadable-account-metadata",
        "--json-output",
        str(tmp_path / "import.json"),
        "--markdown-output",
        str(tmp_path / "import.md"),
    )
    assert by_label["legacy-import-rehearsal"].argv == (
        "python-test",
        "scripts/import_legacy_user_memory.py",
        "--legacy-instances-dir",
        str(legacy_dir),
        "--target-instances-dir",
        "instances",
        "--rehearsal-copy-dir",
        str(tmp_path / "teebotus-rehearsal-copy"),
        "--replace-unreadable",
        "--apply",
        "--replace-unreadable-account-metadata",
        "--json-output",
        str(tmp_path / "rehearsal.json"),
        "--markdown-output",
        str(tmp_path / "rehearsal.md"),
    )
    assert by_label["memory-recovery-legacy-json"].validate_secret_artifacts is True
    assert by_label["memory-recovery-legacy-text"].validate_secret_artifacts is True
    assert by_label["legacy-import-preflight"].validate_secret_artifacts is True
    assert by_label["legacy-import-rehearsal"].validate_secret_artifacts is True
    assert by_label["legacy-import-preflight-Bote_der_Wahrheit"].argv == (
        "python-test",
        "scripts/import_legacy_user_memory.py",
        "--legacy-instances-dir",
        str(legacy_dir),
        "--target-instances-dir",
        "instances",
        "--instance",
        "Bote_der_Wahrheit",
        "--replace-unreadable-account-metadata",
        "--json-output",
        str(tmp_path / "import-Bote_der_Wahrheit.json"),
        "--markdown-output",
        str(tmp_path / "import-Bote_der_Wahrheit.md"),
    )
    assert by_label["legacy-import-preflight-Depressionsbot"].validate_secret_artifacts is True


def test_plan2_acceptance_prepares_legacy_rehearsal_copy_dir(tmp_path: Path) -> None:
    rehearsal_dir = tmp_path / "teebotus-plan2-rehearsal"
    rehearsal_dir.mkdir()
    (rehearsal_dir / "old.txt").write_text("old", encoding="utf-8")
    command = check_plan2_acceptance.AcceptanceCommand(
        "legacy-import-rehearsal",
        (
            "python-test",
            "scripts/import_legacy_user_memory.py",
            "--rehearsal-copy-dir",
            str(rehearsal_dir),
        ),
    )

    check_plan2_acceptance._prepare_acceptance_command(command)

    assert not rehearsal_dir.exists()


def test_plan2_acceptance_resolves_relative_rehearsal_copy_dir_against_repo_root(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "teebotus-plan2-repo"
    repo_root.mkdir()
    monkeypatch.setattr(check_plan2_acceptance, "REPO_ROOT", repo_root)
    original_cwd = tmp_path / "not-repo"
    original_cwd.mkdir()
    monkeypatch.chdir(original_cwd)
    rehearsal_file = repo_root / "teebotus-plan2-rehearsal"
    rehearsal_file.write_text("old", encoding="utf-8")
    command = check_plan2_acceptance.AcceptanceCommand(
        "legacy-import-rehearsal",
        (
            "python-test",
            "scripts/import_legacy_user_memory.py",
            "--rehearsal-copy-dir",
            "teebotus-plan2-rehearsal",
        ),
    )

    check_plan2_acceptance._prepare_acceptance_command(command)

    assert not rehearsal_file.exists()


def test_plan2_acceptance_prepares_legacy_rehearsal_copy_file(tmp_path: Path) -> None:
    rehearsal_file = tmp_path / "teebotus-plan2-rehearsal"
    rehearsal_file.write_text("old", encoding="utf-8")
    command = check_plan2_acceptance.AcceptanceCommand(
        "legacy-import-rehearsal",
        (
            "python-test",
            "scripts/import_legacy_user_memory.py",
            "--rehearsal-copy-dir",
            str(rehearsal_file),
        ),
    )

    check_plan2_acceptance._prepare_acceptance_command(command)

    assert not rehearsal_file.exists()


def test_plan2_acceptance_prepares_legacy_rehearsal_broken_symlink(tmp_path: Path) -> None:
    rehearsal_dir = tmp_path / "teebotus-rehearsal-target"
    broken_link = tmp_path / "teebotus-rehearsal-link"
    broken_link.symlink_to(rehearsal_dir)

    command = check_plan2_acceptance.AcceptanceCommand(
        "legacy-import-rehearsal",
        (
            "python-test",
            "scripts/import_legacy_user_memory.py",
            "--rehearsal-copy-dir",
            str(broken_link),
        ),
    )

    check_plan2_acceptance._prepare_acceptance_command(command)

    assert not broken_link.exists()


def test_plan2_acceptance_rejects_unsafe_legacy_rehearsal_copy_dir() -> None:
    command = check_plan2_acceptance.AcceptanceCommand(
        "legacy-import-rehearsal",
        (
            "python-test",
            "scripts/import_legacy_user_memory.py",
            "--rehearsal-copy-dir",
            "/home/teladi/TeeBotus/instances",
        ),
    )

    try:
        check_plan2_acceptance._prepare_acceptance_command(command)
    except RuntimeError as exc:
        assert "unsafe legacy rehearsal copy dir" in str(exc)
    else:
        raise AssertionError("unsafe rehearsal copy dir was accepted")


def test_plan2_acceptance_rejects_rehearsal_copy_dir_that_contains_target_instances(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "teebotus-plan2-repo"
    repo_root.mkdir()
    instances_dir = repo_root / "instances"
    instances_dir.mkdir(parents=True)
    rehearsal_root = repo_root
    monkeypatch.setattr(check_plan2_acceptance, "REPO_ROOT", repo_root)
    command = check_plan2_acceptance.AcceptanceCommand(
        "legacy-import-rehearsal",
        (
            "python-test",
            "scripts/import_legacy_user_memory.py",
            "--legacy-instances-dir",
            str(tmp_path / "legacy"),
            "--target-instances-dir",
            "instances",
            "--rehearsal-copy-dir",
            str(rehearsal_root),
        ),
    )

    try:
        check_plan2_acceptance._prepare_acceptance_command(command)
    except RuntimeError as exc:
        assert "must not contain source instances directory" in str(exc)
    else:
        raise AssertionError("legacy rehearsal copy directory containing source instances directory was accepted")


def test_plan2_acceptance_accepts_nested_safe_legacy_rehearsal_copy_dir(tmp_path: Path) -> None:
    rehearsal_root = tmp_path / "teebotus" / "rehearsal"
    command = check_plan2_acceptance.AcceptanceCommand(
        "legacy-import-rehearsal",
        (
            "python-test",
            "scripts/import_legacy_user_memory.py",
            "--rehearsal-copy-dir",
            str(rehearsal_root),
        ),
    )

    check_plan2_acceptance._prepare_acceptance_command(command)

    assert not rehearsal_root.exists()


def test_plan2_acceptance_instance_artifact_paths_are_stable(tmp_path: Path) -> None:
    assert check_plan2_acceptance._instance_artifact_path(tmp_path / "import.json", "Bote der Wahrheit") == (
        tmp_path / "import-Bote_der_Wahrheit.json"
    )


def test_plan2_acceptance_can_include_nonfatal_qdrant_live_probe(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(check_plan2_acceptance.shutil, "which", lambda name: "/usr/bin/curl" if name == "curl" else None)

    commands = check_plan2_acceptance.build_acceptance_commands(
        python="python-test",
        benchmark_output=tmp_path / "bench.md",
        benchmark_json_output=tmp_path / "bench.json",
        include_qdrant_live=True,
    )
    by_label = {command.label: command for command in commands}

    assert by_label["qdrant-live-collections"].argv == ("/usr/bin/curl", "-fsS", "http://127.0.0.1:6333/collections")
    assert by_label["qdrant-live-collections"].nonfatal is True


def test_plan2_acceptance_runner_stops_on_fatal_failure(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(argv, cwd, check, **kwargs):  # noqa: ANN001, ARG001
        calls.append(tuple(argv))
        return subprocess.CompletedProcess(argv, 7)

    monkeypatch.setattr(check_plan2_acceptance.subprocess, "run", fake_run)

    result = check_plan2_acceptance.run_acceptance_commands(
        [
            check_plan2_acceptance.AcceptanceCommand("fatal", ("python-test", "-m", "pytest")),
            check_plan2_acceptance.AcceptanceCommand("later", ("python-test", "-m", "TeeBotus")),
        ]
    )

    assert result == 7
    assert calls == [("python-test", "-m", "pytest")]


def test_plan2_acceptance_runner_continues_after_nonfatal_failure(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(argv, cwd, check, **kwargs):  # noqa: ANN001, ARG001
        calls.append(tuple(argv))
        code = 3 if tuple(argv) == ("pip-audit",) else 0
        return subprocess.CompletedProcess(argv, code)

    monkeypatch.setattr(check_plan2_acceptance.subprocess, "run", fake_run)

    result = check_plan2_acceptance.run_acceptance_commands(
        [
            check_plan2_acceptance.AcceptanceCommand("audit", ("pip-audit",), nonfatal=True),
            check_plan2_acceptance.AcceptanceCommand("later", ("python-test", "-m", "TeeBotus")),
        ]
    )

    assert result == 0
    assert calls == [("pip-audit",), ("python-test", "-m", "TeeBotus")]


def test_plan2_acceptance_runner_validates_benchmark_artifacts(tmp_path: Path, monkeypatch) -> None:
    markdown_path = tmp_path / "bench.md"
    json_path = tmp_path / "bench.json"
    calls: list[tuple[str, ...]] = []

    def fake_run(argv, cwd, check, **kwargs):  # noqa: ANN001, ARG001
        calls.append(tuple(argv))
        payload = _valid_benchmark_payload()
        payload["generated_at"] = "2026-06-17T00:00:00+00:00"
        from TeeBotus.benchmarks.reporting import render_markdown

        markdown_path.write_text(render_markdown(payload), encoding="utf-8")
        json_path.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(check_plan2_acceptance.subprocess, "run", fake_run)

    result = check_plan2_acceptance.run_acceptance_commands(
        [
            check_plan2_acceptance.AcceptanceCommand(
                "plan2-quick-benchmarks",
                (
                    "python-test",
                    "scripts/run_benchmarks.py",
                    "--output",
                    str(markdown_path),
                    "--json-output",
                    str(json_path),
                ),
                validate_benchmark_artifacts=True,
            ),
            check_plan2_acceptance.AcceptanceCommand("later", ("python-test", "-m", "pytest")),
        ]
    )

    assert result == 0
    assert calls == [
        (
            "python-test",
            "scripts/run_benchmarks.py",
            "--output",
            str(markdown_path),
            "--json-output",
            str(json_path),
        ),
        ("python-test", "-m", "pytest"),
    ]


def test_plan2_acceptance_runner_fails_on_invalid_benchmark_artifacts(tmp_path: Path, monkeypatch) -> None:
    markdown_path = tmp_path / "bench.md"
    json_path = tmp_path / "bench.json"
    calls: list[tuple[str, ...]] = []

    def fake_run(argv, cwd, check, **kwargs):  # noqa: ANN001, ARG001
        calls.append(tuple(argv))
        markdown_path.write_text("not a benchmark report\n", encoding="utf-8")
        json_path.write_text(json.dumps({"schema_version": 1, "ok": True, "results": []}), encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(check_plan2_acceptance.subprocess, "run", fake_run)

    result = check_plan2_acceptance.run_acceptance_commands(
        [
            check_plan2_acceptance.AcceptanceCommand(
                "plan2-quick-benchmarks",
                (
                    "python-test",
                    "scripts/run_benchmarks.py",
                    "--output",
                    str(markdown_path),
                    "--json-output",
                    str(json_path),
                ),
                validate_benchmark_artifacts=True,
            ),
            check_plan2_acceptance.AcceptanceCommand("later", ("python-test", "-m", "pytest")),
        ]
    )

    assert result == 1
    assert calls == [
        (
            "python-test",
            "scripts/run_benchmarks.py",
            "--output",
            str(markdown_path),
            "--json-output",
            str(json_path),
        )
    ]


def test_plan2_acceptance_runner_validates_secret_artifacts(tmp_path: Path, monkeypatch) -> None:
    output_path = tmp_path / "recovery.md"
    calls: list[tuple[str, ...]] = []

    def fake_run(argv, cwd, check, **kwargs):  # noqa: ANN001, ARG001
        calls.append(tuple(argv))
        _write_valid_memory_recovery_markdown(output_path)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(check_plan2_acceptance.subprocess, "run", fake_run)

    result = check_plan2_acceptance.run_acceptance_commands(
        [
            check_plan2_acceptance.AcceptanceCommand(
                "memory-recovery-legacy-text",
                ("python-test", "-m", "TeeBotus.admin", "memory-recovery", "--output", str(output_path)),
                validate_secret_artifacts=True,
            ),
            check_plan2_acceptance.AcceptanceCommand("later", ("python-test", "-m", "pytest")),
        ]
    )

    assert result == 0
    assert calls == [
        ("python-test", "-m", "TeeBotus.admin", "memory-recovery", "--output", str(output_path)),
        ("python-test", "-m", "pytest"),
    ]


def test_plan2_acceptance_runner_fails_on_malformed_memory_recovery_markdown(tmp_path: Path, monkeypatch) -> None:
    output_path = tmp_path / "recovery.md"
    calls: list[tuple[str, ...]] = []

    def fake_run(argv, cwd, check, **kwargs):  # noqa: ANN001, ARG001
        calls.append(tuple(argv))
        output_path.write_text(
            "\n".join(
                [
                    "# TeeBotus Account-Memory Recovery Report",
                    "",
                    "## Instance: Demo",
                    "",
                    "## Totals",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(check_plan2_acceptance.subprocess, "run", fake_run)

    result = check_plan2_acceptance.run_acceptance_commands(
        [
            check_plan2_acceptance.AcceptanceCommand(
                "memory-recovery-legacy-text",
                ("python-test", "-m", "TeeBotus.admin", "memory-recovery", "--output", str(output_path)),
                validate_secret_artifacts=True,
            ),
            check_plan2_acceptance.AcceptanceCommand("later", ("python-test", "-m", "pytest")),
        ]
    )

    assert result == 1
    assert calls == [("python-test", "-m", "TeeBotus.admin", "memory-recovery", "--output", str(output_path))]


def test_memory_recovery_markdown_validation_requires_legacy_users_summary(tmp_path: Path) -> None:
    output_path = tmp_path / "recovery.md"
    output_path.write_text(
        "\n".join(
            [
                "# TeeBotus Account-Memory Recovery Report",
                "",
                "## Totals",
                "",
                "- accounts: `0`",
                "",
                "## Instance: Demo",
                "",
                "- source_count: `0`",
                "- metadata_health: readable=`True` unreadable_items=`0`",
                "- legacy_plaintext_import: status=`available` sources=`1` entries=`2` requested_path_exists=`True` legacy_path_exists=`True` users_path_exists=`True` path=`legacy/Demo/data/users`",
                "",
                "### Account: " + ("a" * 128),
                "- recovery_status: `empty`",
                "",
            ]
        ),
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._memory_recovery_markdown_artifact_errors(
        ("python-test", "-m", "TeeBotus.admin", "memory-recovery", "--output", str(output_path))
    )

    assert any("lacks legacy users summary" in error for error in errors)


def test_plan2_acceptance_runner_fails_on_secret_artifact_leak(tmp_path: Path, monkeypatch) -> None:
    output_path = tmp_path / "recovery.md"
    calls: list[tuple[str, ...]] = []

    def fake_run(argv, cwd, check, **kwargs):  # noqa: ANN001, ARG001
        calls.append(tuple(argv))
        output_path.write_text("# Recovery\n\napi_key=plain-secret\n", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(check_plan2_acceptance.subprocess, "run", fake_run)

    result = check_plan2_acceptance.run_acceptance_commands(
        [
            check_plan2_acceptance.AcceptanceCommand(
                "memory-recovery-legacy-text",
                ("python-test", "-m", "TeeBotus.admin", "memory-recovery", "--output", str(output_path)),
                validate_secret_artifacts=True,
            ),
            check_plan2_acceptance.AcceptanceCommand("later", ("python-test", "-m", "pytest")),
        ]
    )

    assert result == 1
    assert calls == [("python-test", "-m", "TeeBotus.admin", "memory-recovery", "--output", str(output_path))]


def test_memory_recovery_artifact_validation_accepts_consistent_json(tmp_path: Path) -> None:
    output_path = tmp_path / "recovery.json"
    output_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "instance_count": 1,
                "instances": [
                    {
                        "instance": "Demo",
                        "source_count": 2,
                        "sources": [
                            _valid_memory_recovery_source(
                                "sqlite_primary",
                                readable=False,
                                raw_entries=1,
                                raw_index_present=True,
                                error="encrypted envelope authentication failed",
                            ),
                            _valid_memory_recovery_source("json_files", kind="json", readable=True),
                        ],
                        "metadata_health": {"readable": True, "unreadable_items": 0, "items": []},
                        "accounts": [
                            {
                                "account_id": "a" * 128,
                                "recoverable": False,
                                "recovery_status": "unrecoverable",
                                "sources": [
                                    _valid_memory_recovery_source(
                                        "sqlite_primary",
                                        readable=False,
                                        raw_entries=1,
                                        raw_index_present=True,
                                        error="encrypted envelope authentication failed",
                                    )
                                ],
                            },
                            {
                                "account_id": "b" * 128,
                                "recoverable": False,
                                "recovery_status": "empty",
                                "sources": [_valid_memory_recovery_source("json_files", kind="json", readable=True)],
                            },
                        ],
                        "legacy_plaintext_import": _valid_legacy_plaintext_import_payload(),
                    }
                ],
                "totals": {
                    "accounts": 2,
                    "recoverable_accounts": 0,
                    "unrecoverable_accounts": 1,
                    "empty_accounts": 1,
                    "no_source_accounts": 0,
                    "sources": 2,
                    "readable_sources": 1,
                    "unreadable_sources": 1,
                    "legacy_plaintext_sources": 1,
                    "legacy_plaintext_entries": 2,
                },
            }
        ),
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._memory_recovery_artifact_errors(
        (
            "python-test",
            "-m",
            "TeeBotus.admin",
            "memory-recovery",
            "--format",
            "json",
            "--output",
            str(output_path),
        )
    )

    assert errors == []


def test_memory_recovery_artifact_validation_rejects_inconsistent_totals(tmp_path: Path) -> None:
    output_path = tmp_path / "recovery.json"
    output_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "instance_count": 2,
                "instances": [
                    {
                        "instance": "Demo",
                        "source_count": 1,
                        "sources": [_valid_memory_recovery_source("sqlite_fallback", entries=1, index_present=True)],
                        "metadata_health": {"readable": True, "unreadable_items": 0, "items": []},
                        "accounts": [
                            {
                                "account_id": "a" * 128,
                                "recoverable": True,
                                "recovery_status": "recoverable",
                                "sources": [_valid_memory_recovery_source("sqlite_fallback", entries=1, index_present=True)],
                            }
                        ],
                        "legacy_plaintext_import": _valid_legacy_plaintext_import_payload(),
                    }
                ],
                "totals": {
                    "accounts": 9,
                    "recoverable_accounts": 0,
                    "unrecoverable_accounts": 0,
                    "empty_accounts": 0,
                    "no_source_accounts": 0,
                    "sources": 0,
                    "readable_sources": 0,
                    "unreadable_sources": 0,
                    "legacy_plaintext_sources": 0,
                    "legacy_plaintext_entries": 0,
                },
            }
        ),
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._memory_recovery_artifact_errors(
        (
            "python-test",
            "-m",
            "TeeBotus.admin",
            "memory-recovery",
            "--format",
            "json",
            "--output",
            str(output_path),
        )
    )

    assert any("instance_count must match instances length" in error for error in errors)
    assert any("totals.accounts must match instances (1)" in error for error in errors)
    assert any("totals.legacy_plaintext_entries must match instances (2)" in error for error in errors)


def test_memory_recovery_artifact_validation_rejects_invalid_source_structure(tmp_path: Path) -> None:
    output_path = tmp_path / "recovery.json"
    output_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "instance_count": 1,
                "instances": [
                    {
                        "instance": "Demo",
                        "source_count": 1,
                        "sources": [
                            {"name": "sqlite_primary", "kind": "sqlite", "path": "instances/Demo/data/accounts/Account_Memory.sqlite3", "active": "yes"},
                            {"name": "sqlite_primary", "kind": "sqlite", "path": "instances/Demo/data/accounts/Account_Memory.backup.sqlite3", "active": True},
                        ],
                        "metadata_health": {"readable": True, "unreadable_items": 0, "items": []},
                        "accounts": [
                            {
                                "account_id": "not-an-account-id",
                                "recoverable": True,
                                "recovery_status": "empty",
                                "sources": [
                                    {
                                        "name": "unknown_source",
                                        "kind": "",
                                        "path": "",
                                        "active": "no",
                                        "payload_kind": "plaintext",
                                        "readable": "yes",
                                        "entries": -1,
                                        "raw_entries": "one",
                                        "index_present": "false",
                                        "raw_index_present": None,
                                    }
                                ],
                            }
                        ],
                    }
                ],
                "totals": {
                    "accounts": 1,
                    "recoverable_accounts": 1,
                    "unrecoverable_accounts": 0,
                    "empty_accounts": 1,
                    "no_source_accounts": 0,
                    "sources": 1,
                    "readable_sources": 1,
                    "unreadable_sources": 0,
                    "legacy_plaintext_sources": 0,
                    "legacy_plaintext_entries": 0,
                },
            }
        ),
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._memory_recovery_artifact_errors(
        (
            "python-test",
            "-m",
            "TeeBotus.admin",
            "memory-recovery",
            "--format",
            "json",
            "--output",
            str(output_path),
        )
    )

    assert any("source_count must match sources length for Demo" in error for error in errors)
    assert any("Demo.sources[0].active must be boolean" in error for error in errors)
    assert any("Demo.sources[1].name is duplicated" in error for error in errors)
    assert any("Demo.accounts[0].account_id must be a 128-char hex account id" in error for error in errors)
    assert any("Demo.accounts[0].recoverable must match recovery_status" in error for error in errors)
    assert any("Demo.accounts[0].sources[0].name must reference instance sources" in error for error in errors)
    assert any("Demo.accounts[0].sources[0].payload_kind must be encrypted_account_memory" in error for error in errors)
    assert any("Demo.accounts[0].sources[0].entries must be a non-negative integer" in error for error in errors)
    assert any("Demo.accounts[0].sources[0].error must be present" in error for error in errors)


def test_memory_recovery_source_validation_accepts_partial_recoverable_source() -> None:
    source = _valid_memory_recovery_source(
        "sqlite_primary",
        readable=True,
        entries=1,
        raw_entries=2,
        error="SQLite account memory payload could not be decrypted",
        partial=True,
        fully_readable=False,
    )

    assert check_plan2_acceptance._memory_recovery_source_errors(
        source,
        "Demo.accounts[0].sources[0]",
        prefix="",
        require_payload_fields=True,
    ) == []


def test_memory_recovery_source_validation_rejects_inconsistent_partial_flags() -> None:
    source = _valid_memory_recovery_source(
        "sqlite_primary",
        readable=False,
        entries=0,
        raw_entries=2,
        error="",
        partial=True,
        fully_readable=True,
    )

    errors = check_plan2_acceptance._memory_recovery_source_errors(
        source,
        "Demo.accounts[0].sources[0]",
        prefix="",
        require_payload_fields=True,
    )

    assert any("partial true requires readable=true" in error for error in errors)
    assert any("partial true requires non-empty error" in error for error in errors)
    assert any("partial true requires recoverable payload" in error for error in errors)
    assert any("fully_readable true requires readable=true" in error for error in errors)
    assert any("partial and fully_readable cannot both be true" in error for error in errors)


def test_memory_recovery_artifact_validation_rejects_nonnumeric_readable_entries_without_crashing(tmp_path: Path) -> None:
    source = _valid_memory_recovery_source("sqlite_primary", readable=True)
    source["entries"] = "one"
    source["raw_entries"] = "one"
    source["index_present"] = False
    output_path = tmp_path / "recovery.json"
    output_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "instance_count": 1,
                "instances": [
                    {
                        "instance": "Demo",
                        "source_count": 1,
                        "sources": [_valid_memory_recovery_source("sqlite_primary")],
                        "metadata_health": {"readable": True, "unreadable_items": 0, "items": []},
                        "accounts": [
                            {
                                "account_id": "a" * 128,
                                "recoverable": True,
                                "recovery_status": "recoverable",
                                "sources": [source],
                            }
                        ],
                    }
                ],
                "totals": {
                    "accounts": 1,
                    "recoverable_accounts": 1,
                    "unrecoverable_accounts": 0,
                    "empty_accounts": 0,
                    "no_source_accounts": 0,
                    "sources": 1,
                    "readable_sources": 1,
                    "unreadable_sources": 0,
                    "legacy_plaintext_sources": 0,
                    "legacy_plaintext_entries": 0,
                },
            }
        ),
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._memory_recovery_artifact_errors(
        (
            "python-test",
            "-m",
            "TeeBotus.admin",
            "memory-recovery",
            "--format",
            "json",
            "--output",
            str(output_path),
        )
    )

    assert any("Demo.accounts[0].sources[0].entries must be a non-negative integer" in error for error in errors)
    assert any("Demo.accounts[0].recoverable requires at least one readable payload source" in error for error in errors)


def test_memory_recovery_artifact_validation_rejects_inconsistent_metadata_health(tmp_path: Path) -> None:
    output_path = tmp_path / "recovery.json"
    output_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "instance_count": 1,
                "instances": [
                    {
                        "instance": "Demo",
                        "metadata_health": {
                            "readable": True,
                            "unreadable_items": 2,
                            "items": [
                                {
                                    "kind": "accounts_dir",
                                    "path": "instances/Demo/data/accounts/accounts",
                                    "error": "encrypted envelope authentication failed",
                                    "account_ids": ["not-an-account-id"],
                                }
                            ],
                        },
                        "accounts": [],
                    }
                ],
                "totals": {
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
                },
            }
        ),
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._memory_recovery_artifact_errors(
        (
            "python-test",
            "-m",
            "TeeBotus.admin",
            "memory-recovery",
            "--format",
            "json",
            "--output",
            str(output_path),
        )
    )

    assert any("metadata_health.unreadable_items must match items length for Demo" in error for error in errors)
    assert any("metadata_health.readable true requires empty items for Demo" in error for error in errors)
    assert any("metadata_health.items[0].account_ids contains invalid account ids" in error for error in errors)


def test_memory_recovery_artifact_validation_rejects_inconsistent_legacy_users(tmp_path: Path) -> None:
    output_path = tmp_path / "recovery.json"
    output_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "instance_count": 1,
                "instances": [
                    {
                        "instance": "Demo",
                        "metadata_health": {"readable": True, "unreadable_items": 0, "items": []},
                        "accounts": [],
                        "legacy_plaintext_import": {
                            **_valid_legacy_plaintext_import_payload(),
                            "sources": 2,
                            "entries": 4,
                            "users": [
                                {"user_id": "395935293", "entries": 1, "path": "legacy/Demo/data/users/395935293"},
                                {"user_id": "395935293", "entries": 2, "path": ""},
                                "not-an-object",
                            ],
                            "dry_run_command": (
                                "python3 scripts/import_legacy_user_memory.py --legacy-instances-dir legacy "
                                "--target-instances-dir instances --instance Demo --replace-unreadable-account-metadata "
                                "--json-output /tmp/import-Demo.json --markdown-output /tmp/import-Demo.md"
                            ),
                        },
                    }
                ],
                "totals": {
                    "accounts": 0,
                    "recoverable_accounts": 0,
                    "unrecoverable_accounts": 0,
                    "empty_accounts": 0,
                    "no_source_accounts": 0,
                    "sources": 0,
                    "readable_sources": 0,
                    "unreadable_sources": 0,
                    "legacy_plaintext_sources": 2,
                    "legacy_plaintext_entries": 4,
                },
            }
        ),
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._memory_recovery_artifact_errors(
        (
            "python-test",
            "-m",
            "TeeBotus.admin",
            "memory-recovery",
            "--format",
            "json",
            "--output",
            str(output_path),
        )
    )

    assert any("legacy users length must match sources for Demo" in error for error in errors)
    assert any("legacy_plaintext_import.users[1].user_id is duplicated" in error for error in errors)
    assert any("legacy_plaintext_import.users[1].path must be non-empty" in error for error in errors)
    assert any("legacy_plaintext_import.users[2] must be an object" in error for error in errors)


def test_memory_recovery_artifact_validation_requires_artifacted_legacy_dry_run(tmp_path: Path) -> None:
    output_path = tmp_path / "recovery.json"
    output_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "instance_count": 1,
                "instances": [
                    {
                        "instance": "Demo",
                        "metadata_health": {"readable": True, "unreadable_items": 0, "items": []},
                        "accounts": [],
                        "legacy_plaintext_import": {
                            **_valid_legacy_plaintext_import_payload(),
                            "sources": 1,
                            "entries": 2,
                            "users": [{"user_id": "395935293", "entries": 2, "path": "legacy/Demo/data/users/395935293"}],
                            "dry_run_command": (
                                "python3 scripts/import_legacy_user_memory.py --legacy-instances-dir legacy "
                                "--target-instances-dir instances --instance Demo --replace-unreadable-account-metadata"
                            ),
                        },
                    }
                ],
                "totals": {
                    "accounts": 0,
                    "recoverable_accounts": 0,
                    "unrecoverable_accounts": 0,
                    "empty_accounts": 0,
                    "no_source_accounts": 0,
                    "sources": 0,
                    "readable_sources": 0,
                    "unreadable_sources": 0,
                    "legacy_plaintext_sources": 1,
                    "legacy_plaintext_entries": 2,
                },
            }
        ),
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._memory_recovery_artifact_errors(
        (
            "python-test",
            "-m",
            "TeeBotus.admin",
            "memory-recovery",
            "--format",
            "json",
            "--output",
            str(output_path),
        )
    )

    assert any("must write JSON and Markdown artifacts for Demo" in error for error in errors)


def test_secret_artifact_validation_checks_all_declared_outputs(tmp_path: Path) -> None:
    json_path = tmp_path / "import.json"
    markdown_path = tmp_path / "import.md"
    json_path.write_text(json.dumps({"status": "ok", "api_key_env": "GROQ_API_KEY"}), encoding="utf-8")
    markdown_path.write_text("# Import\n\npassword=plain-secret\n", encoding="utf-8")

    errors = check_plan2_acceptance._secret_artifact_errors(
        (
            "python-test",
            "scripts/import_legacy_user_memory.py",
            "--json-output",
            str(json_path),
            "--markdown-output",
            str(markdown_path),
        )
    )

    assert errors == [f"--markdown-output artifact contains secret-looking content: {markdown_path}"]


def test_secret_artifact_validation_rejects_yaml_style_secret_fields(tmp_path: Path) -> None:
    markdown_path = tmp_path / "import.md"
    markdown_path.write_text("# Import\n\napi_key: plain-secret\npassword: hunter2\n", encoding="utf-8")

    errors = check_plan2_acceptance._secret_artifact_errors(
        ("python-test", "script.py", "--markdown-output", str(markdown_path))
    )

    assert errors == [f"--markdown-output artifact contains secret-looking content: {markdown_path}"]


def test_secret_artifact_validation_allows_yaml_style_placeholders_and_env_names(tmp_path: Path) -> None:
    markdown_path = tmp_path / "import.md"
    markdown_path.write_text(
        "# Import\n\napi_key: configured\napi_key_env: GROQ_API_KEY\npassword: <redacted>\n",
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._secret_artifact_errors(
        ("python-test", "script.py", "--markdown-output", str(markdown_path))
    )

    assert errors == []


def test_plan2_acceptance_console_redaction_removes_command_output_secrets() -> None:
    github_token = "ghp_" + "1234567890ABCDEFGHIJK"
    text = check_plan2_acceptance._redact_console_text(
        f"stderr token={github_token} password: hunter2 "
        "target=https://user:plainpass@example.test/path "
        '{"api_key": "plain-json-secret", "api_key_env": "GROQ_API_KEY"}'
    )

    assert github_token not in text
    assert "hunter2" not in text
    assert "user:plainpass" not in text
    assert "plain-json-secret" not in text
    assert "token=<redacted-secret>" in text
    assert "password: <redacted>" in text
    assert "target=https://<redacted>@example.test/path" in text
    assert '"api_key": "<redacted>"' in text
    assert '"api_key_env": "GROQ_API_KEY"' in text


def test_secret_artifact_validation_rejects_uppercase_secret_values_without_env_key(tmp_path: Path) -> None:
    markdown_path = tmp_path / "import.md"
    markdown_path.write_text(
        "# Import\n\napi_key: PLAINSECRET123\npassword: HUNTER2\n",
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._secret_artifact_errors(
        ("python-test", "script.py", "--markdown-output", str(markdown_path))
    )

    assert errors == [f"--markdown-output artifact contains secret-looking content: {markdown_path}"]


def test_secret_artifact_validation_rejects_json_uppercase_secret_values_without_env_key(tmp_path: Path) -> None:
    json_path = tmp_path / "import.json"
    json_path.write_text(
        json.dumps({"status": "ok", "api_key": "PLAINSECRET123", "api_key_env": "GROQ_API_KEY"}),
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._secret_artifact_errors(("script.py", "--json-output", str(json_path)))

    assert errors == [f"--json-output artifact contains secret-looking content: {json_path}"]


def test_legacy_import_artifact_validation_requires_apply_safety(tmp_path: Path) -> None:
    json_path = tmp_path / "import.json"
    markdown_path = tmp_path / "import.md"
    _write_valid_legacy_import_markdown(markdown_path)
    json_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "dry-run",
                "options": {"allow_running_bot": False},
                "apply_safety": {
                    "running_bot_processes": [{"pid": "123", "cmdline": "python3 -m TeeBotus --all"}],
                    "running_bot_process_count": 1,
                    "apply_allowed_now": False,
                    "apply_requires_stopped_bot": True,
                    "message": "TeeBotus runtime processes are running; stop bot/proactive jobs before using --apply.",
                },
                "totals": {
                    "sources": 1,
                    "imported_sources": 1,
                    "skipped_sources": 0,
                    "malformed_sources": 0,
                    "encrypted_sources": 0,
                    "entries_seen": 1,
                    "entries_imported": 1,
                    "accounts_created": 1,
                    "accounts_existing": 0,
                    "unreadable_targets": 0,
                    "unreadable_metadata": 0,
                    "backups_created": 0,
                    "metadata_backups_created": 0,
                    "account_store_resets": 0,
                },
                "events": [_valid_legacy_import_event(account_created=True)],
            }
        ),
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._legacy_import_artifact_errors(
        (
            "python-test",
            "scripts/import_legacy_user_memory.py",
            "--json-output",
            str(json_path),
            "--markdown-output",
            str(markdown_path),
        )
    )

    assert errors == []


def test_legacy_import_artifact_validation_rejects_running_process_without_apply_block(tmp_path: Path) -> None:
    json_path = tmp_path / "import.json"
    markdown_path = tmp_path / "import.md"
    _write_valid_legacy_import_markdown(markdown_path)
    json_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "dry-run",
                "options": {"allow_running_bot": False},
                "apply_safety": {
                    "running_bot_processes": [{"pid": "123", "cmdline": "python3 -m TeeBotus --all"}],
                    "running_bot_process_count": 1,
                    "apply_allowed_now": True,
                    "apply_requires_stopped_bot": False,
                    "message": "unsafe",
                },
                "totals": {
                    "sources": 1,
                    "imported_sources": 1,
                    "skipped_sources": 0,
                    "malformed_sources": 0,
                    "encrypted_sources": 0,
                    "entries_seen": 1,
                    "entries_imported": 1,
                    "accounts_created": 1,
                    "accounts_existing": 0,
                    "unreadable_targets": 0,
                    "unreadable_metadata": 0,
                    "backups_created": 0,
                    "metadata_backups_created": 0,
                    "account_store_resets": 0,
                },
                "events": [_valid_legacy_import_event(account_created=True)],
            }
        ),
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._legacy_import_artifact_errors(
        (
            "python-test",
            "scripts/import_legacy_user_memory.py",
            "--json-output",
            str(json_path),
            "--markdown-output",
            str(markdown_path),
        )
    )

    assert any("apply_allowed_now must be false" in error for error in errors)
    assert any("apply_requires_stopped_bot must be true" in error for error in errors)


def test_legacy_import_artifact_validation_accepts_apply_blocked_mode(tmp_path: Path) -> None:
    json_path = tmp_path / "import.json"
    markdown_path = tmp_path / "import.md"
    _write_apply_blocked_legacy_import_markdown(markdown_path)
    json_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "apply-blocked",
                "options": {"allow_running_bot": False},
                "apply_safety": {
                    "running_bot_processes": [{"pid": "123", "cmdline": "python3 -m TeeBotus --all"}],
                    "running_bot_process_count": 1,
                    "apply_allowed_now": False,
                    "apply_requires_stopped_bot": True,
                    "message": "TeeBotus runtime processes are running; stop bot/proactive jobs before using --apply.",
                },
                "totals": {
                    "sources": 1,
                    "imported_sources": 1,
                    "skipped_sources": 0,
                    "malformed_sources": 0,
                    "encrypted_sources": 0,
                    "entries_seen": 1,
                    "entries_imported": 1,
                    "accounts_created": 1,
                    "accounts_existing": 0,
                    "unreadable_targets": 0,
                    "unreadable_metadata": 0,
                    "backups_created": 0,
                    "metadata_backups_created": 0,
                    "account_store_resets": 0,
                },
                "events": [_valid_legacy_import_event(account_created=True)],
            }
        ),
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._legacy_import_artifact_errors(
        (
            "python-test",
            "scripts/import_legacy_user_memory.py",
            "--json-output",
            str(json_path),
            "--markdown-output",
            str(markdown_path),
        )
    )

    assert errors == []


def test_legacy_import_artifact_validation_rejects_invalid_schema_and_mode(tmp_path: Path) -> None:
    json_path = tmp_path / "import.json"
    markdown_path = tmp_path / "import.md"
    _write_valid_legacy_import_markdown(markdown_path)
    json_path.write_text(
        json.dumps(
            {
                "schema_version": 99,
                "mode": "maybe",
                "options": {"allow_running_bot": False},
                "apply_safety": {
                    "running_bot_processes": [],
                    "running_bot_process_count": 0,
                    "apply_allowed_now": True,
                    "apply_requires_stopped_bot": False,
                    "message": "No TeeBotus runtime process detected.",
                },
                "totals": {
                    "sources": 0,
                    "imported_sources": 0,
                    "skipped_sources": 0,
                    "malformed_sources": 0,
                    "encrypted_sources": 0,
                    "entries_seen": 0,
                    "entries_imported": 0,
                    "accounts_created": 0,
                    "accounts_existing": 0,
                    "unreadable_targets": 0,
                    "unreadable_metadata": 0,
                    "backups_created": 0,
                    "metadata_backups_created": 0,
                    "account_store_resets": 0,
                },
                "events": [],
            }
        ),
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._legacy_import_artifact_errors(
        (
            "python-test",
            "scripts/import_legacy_user_memory.py",
            "--json-output",
            str(json_path),
            "--markdown-output",
            str(markdown_path),
        )
    )

    assert any("schema_version must be 1" in error for error in errors)
    assert any("mode must be one of" in error for error in errors)


def test_legacy_import_artifact_validation_rejects_apply_blocked_without_runtime_process(tmp_path: Path) -> None:
    json_path = tmp_path / "import.json"
    markdown_path = tmp_path / "import.md"
    _write_valid_legacy_import_markdown(markdown_path)
    json_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "apply-blocked",
                "options": {"allow_running_bot": False},
                "apply_safety": {
                    "running_bot_processes": [],
                    "running_bot_process_count": 0,
                    "apply_allowed_now": False,
                    "apply_requires_stopped_bot": True,
                    "message": "TeeBotus runtime processes are running; stop bot/proactive jobs before using --apply.",
                },
                "totals": {
                    "sources": 1,
                    "imported_sources": 1,
                    "skipped_sources": 0,
                    "malformed_sources": 0,
                    "encrypted_sources": 0,
                    "entries_seen": 1,
                    "entries_imported": 1,
                    "accounts_created": 1,
                    "accounts_existing": 0,
                    "unreadable_targets": 0,
                    "unreadable_metadata": 0,
                    "backups_created": 0,
                    "metadata_backups_created": 0,
                    "account_store_resets": 0,
                },
                "events": [_valid_legacy_import_event(account_created=True)],
            }
        ),
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._legacy_import_artifact_errors(
        (
            "python-test",
            "scripts/import_legacy_user_memory.py",
            "--json-output",
            str(json_path),
            "--markdown-output",
            str(markdown_path),
        )
    )

    assert any("apply-blocked requires detected runtime processes" in error for error in errors)


def test_legacy_import_artifact_validation_rejects_out_of_scope_instance_events(tmp_path: Path) -> None:
    json_path = tmp_path / "import-demo.json"
    markdown_path = tmp_path / "import-demo.md"
    _write_valid_legacy_import_markdown(markdown_path)
    json_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "dry-run",
                "instances": ["Demo"],
                "options": {"allow_running_bot": False},
                "apply_safety": {
                    "running_bot_processes": [],
                    "running_bot_process_count": 0,
                    "apply_allowed_now": True,
                    "apply_requires_stopped_bot": False,
                    "message": "No TeeBotus runtime process detected.",
                },
                "totals": {
                    "sources": 2,
                    "imported_sources": 2,
                    "skipped_sources": 0,
                    "malformed_sources": 0,
                    "encrypted_sources": 0,
                    "entries_seen": 0,
                    "entries_imported": 0,
                    "accounts_created": 0,
                    "accounts_existing": 0,
                    "unreadable_targets": 0,
                    "unreadable_metadata": 0,
                    "backups_created": 0,
                    "metadata_backups_created": 0,
                    "account_store_resets": 0,
                },
                "events": [
                    _valid_legacy_import_event(entries=0, imported=0),
                    _valid_legacy_import_event(instance="Other", legacy_user_id="124", entries=0, imported=0),
                ],
            }
        ),
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._legacy_import_artifact_errors(
        (
            "python-test",
            "scripts/import_legacy_user_memory.py",
            "--instance",
            "Demo",
            "--json-output",
            str(json_path),
            "--markdown-output",
            str(markdown_path),
        )
    )

    assert any("out-of-scope instances: Other" in error for error in errors)


def test_legacy_import_artifact_validation_accepts_matching_instance_scope(tmp_path: Path) -> None:
    json_path = tmp_path / "import-demo.json"
    markdown_path = tmp_path / "import-demo.md"
    _write_valid_legacy_import_markdown(markdown_path)
    json_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "dry-run",
                "instances": ["Demo"],
                "options": {"allow_running_bot": False},
                "apply_safety": {
                    "running_bot_processes": [],
                    "running_bot_process_count": 0,
                    "apply_allowed_now": True,
                    "apply_requires_stopped_bot": False,
                    "message": "No TeeBotus runtime process detected.",
                },
                "totals": {
                    "sources": 1,
                    "imported_sources": 1,
                    "skipped_sources": 0,
                    "malformed_sources": 0,
                    "encrypted_sources": 0,
                    "entries_seen": 0,
                    "entries_imported": 0,
                    "accounts_created": 0,
                    "accounts_existing": 0,
                    "unreadable_targets": 0,
                    "unreadable_metadata": 0,
                    "backups_created": 0,
                    "metadata_backups_created": 0,
                    "account_store_resets": 0,
                },
                "events": [_valid_legacy_import_event(entries=0, imported=0)],
            }
        ),
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._legacy_import_artifact_errors(
        (
            "python-test",
            "scripts/import_legacy_user_memory.py",
            "--instance",
            "Demo",
            "--json-output",
            str(json_path),
            "--markdown-output",
            str(markdown_path),
        )
    )

    assert errors == []


def test_legacy_import_artifact_validation_accepts_skip_empty_without_created_account(tmp_path: Path) -> None:
    json_path = tmp_path / "import-demo.json"
    markdown_path = tmp_path / "import-demo.md"
    _write_valid_legacy_import_markdown(markdown_path)
    json_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "apply",
                "instances": ["Demo"],
                "options": {"allow_running_bot": False},
                "apply_safety": {
                    "running_bot_processes": [],
                    "running_bot_process_count": 0,
                    "apply_allowed_now": True,
                    "apply_requires_stopped_bot": False,
                    "message": "No TeeBotus runtime process detected.",
                },
                "totals": {
                    "sources": 1,
                    "imported_sources": 0,
                    "skipped_sources": 1,
                    "malformed_sources": 0,
                    "encrypted_sources": 0,
                    "entries_seen": 0,
                    "entries_imported": 0,
                    "accounts_created": 0,
                    "accounts_existing": 0,
                    "unreadable_targets": 0,
                    "unreadable_metadata": 0,
                    "backups_created": 0,
                    "metadata_backups_created": 0,
                    "account_store_resets": 0,
                },
                "events": [
                    _valid_legacy_import_event(
                        account_id="<not-created>",
                        action="skip-empty",
                        entries=0,
                        imported=0,
                    )
                ],
            }
        ),
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._legacy_import_artifact_errors(
        (
            "python-test",
            "scripts/import_legacy_user_memory.py",
            "--instance",
            "Demo",
            "--json-output",
            str(json_path),
            "--markdown-output",
            str(markdown_path),
        )
    )

    assert errors == []


def test_legacy_import_artifact_validation_accepts_malformed_and_encrypted_source_skips(tmp_path: Path) -> None:
    json_path = tmp_path / "import-demo.json"
    markdown_path = tmp_path / "import-demo.md"
    _write_valid_legacy_import_markdown(markdown_path)
    json_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "apply",
                "instances": ["Demo"],
                "options": {"allow_running_bot": False},
                "apply_safety": {
                    "running_bot_processes": [],
                    "running_bot_process_count": 0,
                    "apply_allowed_now": True,
                    "apply_requires_stopped_bot": False,
                    "message": "No TeeBotus runtime process detected.",
                },
                "totals": {
                    "sources": 2,
                    "imported_sources": 0,
                    "skipped_sources": 2,
                    "malformed_sources": 1,
                    "encrypted_sources": 1,
                    "entries_seen": 0,
                    "entries_imported": 0,
                    "accounts_created": 0,
                    "accounts_existing": 0,
                    "unreadable_targets": 0,
                    "unreadable_metadata": 0,
                    "backups_created": 0,
                    "metadata_backups_created": 0,
                    "account_store_resets": 0,
                },
                "events": [
                    _valid_legacy_import_event(
                        account_id="<not-created>",
                        action="skip-malformed-source",
                        entries=0,
                        imported=0,
                        error="malformed JSON",
                    ),
                    _valid_legacy_import_event(
                        legacy_user_id="124",
                        account_id="<not-created>",
                        action="skip-encrypted-source",
                        entries=0,
                        imported=0,
                        error="encrypted",
                    ),
                ],
            }
        ),
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._legacy_import_artifact_errors(
        (
            "python-test",
            "scripts/import_legacy_user_memory.py",
            "--instance",
            "Demo",
            "--json-output",
            str(json_path),
            "--markdown-output",
            str(markdown_path),
        )
    )

    assert errors == []


def test_legacy_import_artifact_validation_rejects_inconsistent_malformed_source_skip(tmp_path: Path) -> None:
    json_path = tmp_path / "import-demo.json"
    markdown_path = tmp_path / "import-demo.md"
    _write_valid_legacy_import_markdown(markdown_path)
    json_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "apply",
                "instances": ["Demo"],
                "options": {"allow_running_bot": False},
                "apply_safety": {
                    "running_bot_processes": [],
                    "running_bot_process_count": 0,
                    "apply_allowed_now": True,
                    "apply_requires_stopped_bot": False,
                    "message": "No TeeBotus runtime process detected.",
                },
                "totals": {
                    "sources": 1,
                    "imported_sources": 0,
                    "skipped_sources": 1,
                    "malformed_sources": 0,
                    "encrypted_sources": 0,
                    "entries_seen": 1,
                    "entries_imported": 1,
                    "accounts_created": 1,
                    "accounts_existing": 0,
                    "unreadable_targets": 1,
                    "unreadable_metadata": 0,
                    "backups_created": 0,
                    "metadata_backups_created": 0,
                    "account_store_resets": 0,
                },
                "events": [
                    _valid_legacy_import_event(
                        action="skip-malformed-source",
                        entries=1,
                        imported=1,
                        account_created=True,
                        target_unreadable=True,
                    )
                ],
            }
        ),
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._legacy_import_artifact_errors(
        (
            "python-test",
            "scripts/import_legacy_user_memory.py",
            "--instance",
            "Demo",
            "--json-output",
            str(json_path),
            "--markdown-output",
            str(markdown_path),
        )
    )

    assert any("skip actions must not import entries" in error for error in errors)
    assert any("skip-malformed-source must use account_id <not-created>" in error for error in errors)
    assert any("skip-malformed-source must have zero entries and zero imported" in error for error in errors)
    assert any("skip-malformed-source must not create an account" in error for error in errors)
    assert any("skip-malformed-source must not claim unreadable target or metadata" in error for error in errors)
    assert any("skip-malformed-source must include an error" in error for error in errors)
    assert any("totals.malformed_sources must match events (1)" in error for error in errors)


def test_legacy_import_artifact_validation_rejects_inconsistent_skip_events(tmp_path: Path) -> None:
    json_path = tmp_path / "import-demo.json"
    markdown_path = tmp_path / "import-demo.md"
    _write_valid_legacy_import_markdown(markdown_path)
    json_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "apply",
                "instances": ["Demo"],
                "options": {"allow_running_bot": False},
                "apply_safety": {
                    "running_bot_processes": [],
                    "running_bot_process_count": 0,
                    "apply_allowed_now": True,
                    "apply_requires_stopped_bot": False,
                    "message": "No TeeBotus runtime process detected.",
                },
                "totals": {
                    "sources": 1,
                    "imported_sources": 0,
                    "skipped_sources": 1,
                    "malformed_sources": 0,
                    "encrypted_sources": 0,
                    "entries_seen": 1,
                    "entries_imported": 1,
                    "accounts_created": 1,
                    "accounts_existing": 0,
                    "unreadable_targets": 1,
                    "unreadable_metadata": 0,
                    "backups_created": 0,
                    "metadata_backups_created": 0,
                    "account_store_resets": 0,
                },
                "events": [
                    _valid_legacy_import_event(
                        action="skip-empty",
                        entries=1,
                        imported=1,
                        account_created=True,
                        target_unreadable=True,
                    )
                ],
            }
        ),
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._legacy_import_artifact_errors(
        (
            "python-test",
            "scripts/import_legacy_user_memory.py",
            "--instance",
            "Demo",
            "--json-output",
            str(json_path),
            "--markdown-output",
            str(markdown_path),
        )
    )

    assert any("skip actions must not import entries" in error for error in errors)
    assert any("skip-empty must use account_id <not-created>" in error for error in errors)
    assert any("skip-empty must have zero entries and zero imported" in error for error in errors)
    assert any("skip-empty must not create an account" in error for error in errors)
    assert any("skip-empty must not claim unreadable target or metadata" in error for error in errors)


def test_legacy_import_artifact_validation_derives_existing_accounts(tmp_path: Path) -> None:
    json_path = tmp_path / "import-demo.json"
    markdown_path = tmp_path / "import-demo.md"
    _write_valid_legacy_import_markdown(markdown_path)
    json_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "dry-run",
                "instances": ["Demo"],
                "options": {"allow_running_bot": False},
                "apply_safety": {
                    "running_bot_processes": [],
                    "running_bot_process_count": 0,
                    "apply_allowed_now": True,
                    "apply_requires_stopped_bot": False,
                    "message": "No TeeBotus runtime process detected.",
                },
                "totals": {
                    "sources": 1,
                    "imported_sources": 1,
                    "skipped_sources": 0,
                    "malformed_sources": 0,
                    "encrypted_sources": 0,
                    "entries_seen": 1,
                    "entries_imported": 0,
                    "accounts_created": 0,
                    "accounts_existing": 0,
                    "unreadable_targets": 0,
                    "unreadable_metadata": 0,
                    "backups_created": 0,
                    "metadata_backups_created": 0,
                    "account_store_resets": 0,
                },
                "events": [
                    _valid_legacy_import_event(
                        account_id="a" * 128,
                        entries=1,
                        imported=0,
                    )
                ],
            }
        ),
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._legacy_import_artifact_errors(
        (
            "python-test",
            "scripts/import_legacy_user_memory.py",
            "--instance",
            "Demo",
            "--json-output",
            str(json_path),
            "--markdown-output",
            str(markdown_path),
        )
    )

    assert any("legacy import totals.accounts_existing must match events (1)" in error for error in errors)


def test_legacy_import_artifact_validation_rejects_inconsistent_metadata_reset_events(tmp_path: Path) -> None:
    json_path = tmp_path / "import-demo.json"
    markdown_path = tmp_path / "import-demo.md"
    _write_valid_legacy_import_markdown(markdown_path)
    json_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "dry-run",
                "instances": ["Demo"],
                "options": {"allow_running_bot": False},
                "apply_safety": {
                    "running_bot_processes": [],
                    "running_bot_process_count": 0,
                    "apply_allowed_now": True,
                    "apply_requires_stopped_bot": False,
                    "message": "No TeeBotus runtime process detected.",
                },
                "totals": {
                    "sources": 1,
                    "imported_sources": 1,
                    "skipped_sources": 0,
                    "malformed_sources": 0,
                    "encrypted_sources": 0,
                    "entries_seen": 2,
                    "entries_imported": 2,
                    "accounts_created": 1,
                    "accounts_existing": 0,
                    "unreadable_targets": 0,
                    "unreadable_metadata": 0,
                    "backups_created": 0,
                    "metadata_backups_created": 0,
                    "account_store_resets": 0,
                },
                "events": [
                    _valid_legacy_import_event(
                        action="would-import-after-metadata-reset",
                        entries=2,
                        imported=2,
                        account_created=True,
                        metadata_unreadable=False,
                    )
                ],
            }
        ),
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._legacy_import_artifact_errors(
        (
            "python-test",
            "scripts/import_legacy_user_memory.py",
            "--instance",
            "Demo",
            "--json-output",
            str(json_path),
            "--markdown-output",
            str(markdown_path),
        )
    )

    assert any("metadata_unreadable must be true for metadata-reset actions" in error for error in errors)
    assert any("totals.unreadable_metadata must match events (1)" in error for error in errors)


def test_legacy_import_artifact_validation_accepts_metadata_reset_existing_accounts(tmp_path: Path) -> None:
    json_path = tmp_path / "import-demo.json"
    markdown_path = tmp_path / "import-demo.md"
    _write_valid_legacy_import_markdown(markdown_path)
    json_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "dry-run",
                "instances": ["Demo"],
                "options": {"allow_running_bot": False},
                "apply_safety": {
                    "running_bot_processes": [],
                    "running_bot_process_count": 0,
                    "apply_allowed_now": True,
                    "apply_requires_stopped_bot": False,
                    "message": "No TeeBotus runtime process detected.",
                },
                "totals": {
                    "sources": 1,
                    "imported_sources": 1,
                    "skipped_sources": 0,
                    "malformed_sources": 0,
                    "encrypted_sources": 0,
                    "entries_seen": 2,
                    "entries_imported": 2,
                    "accounts_created": 1,
                    "accounts_existing": 0,
                    "unreadable_targets": 0,
                    "unreadable_metadata": 1,
                    "backups_created": 0,
                    "metadata_backups_created": 0,
                    "account_store_resets": 0,
                },
                "events": [
                    _valid_legacy_import_event(
                        action="would-import-after-metadata-reset",
                        entries=2,
                        imported=2,
                        account_created=True,
                        metadata_unreadable=True,
                        metadata_reset_existing_accounts=["a" * 128, "b" * 128],
                    )
                ],
            }
        ),
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._legacy_import_artifact_errors(
        (
            "python-test",
            "scripts/import_legacy_user_memory.py",
            "--instance",
            "Demo",
            "--json-output",
            str(json_path),
            "--markdown-output",
            str(markdown_path),
        )
    )

    assert errors == []


def test_legacy_import_artifact_validation_rejects_invalid_metadata_reset_existing_accounts(tmp_path: Path) -> None:
    json_path = tmp_path / "import-demo.json"
    markdown_path = tmp_path / "import-demo.md"
    _write_valid_legacy_import_markdown(markdown_path)
    json_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "dry-run",
                "instances": ["Demo"],
                "options": {"allow_running_bot": False},
                "apply_safety": {
                    "running_bot_processes": [],
                    "running_bot_process_count": 0,
                    "apply_allowed_now": True,
                    "apply_requires_stopped_bot": False,
                    "message": "No TeeBotus runtime process detected.",
                },
                "totals": {
                    "sources": 1,
                    "imported_sources": 1,
                    "skipped_sources": 0,
                    "malformed_sources": 0,
                    "encrypted_sources": 0,
                    "entries_seen": 1,
                    "entries_imported": 1,
                    "accounts_created": 1,
                    "accounts_existing": 0,
                    "unreadable_targets": 0,
                    "unreadable_metadata": 0,
                    "backups_created": 0,
                    "metadata_backups_created": 0,
                    "account_store_resets": 0,
                },
                "events": [
                    _valid_legacy_import_event(
                        account_created=True,
                        metadata_reset_existing_accounts=["not-an-account"],
                    )
                ],
            }
        ),
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._legacy_import_artifact_errors(
        (
            "python-test",
            "scripts/import_legacy_user_memory.py",
            "--instance",
            "Demo",
            "--json-output",
            str(json_path),
            "--markdown-output",
            str(markdown_path),
        )
    )

    assert any("metadata_reset_existing_accounts contains invalid account ids" in error for error in errors)
    assert any("metadata_reset_existing_accounts requires metadata_unreadable or metadata-reset action" in error for error in errors)


def test_legacy_import_artifact_validation_rejects_malformed_markdown_report(tmp_path: Path) -> None:
    json_path = tmp_path / "import-demo.json"
    markdown_path = tmp_path / "import-demo.md"
    json_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "dry-run",
                "instances": ["Demo"],
                "options": {"allow_running_bot": False},
                "apply_safety": {
                    "running_bot_processes": [],
                    "running_bot_process_count": 0,
                    "apply_allowed_now": True,
                    "apply_requires_stopped_bot": False,
                    "message": "No TeeBotus runtime process detected.",
                },
                "totals": {
                    "sources": 1,
                    "imported_sources": 1,
                    "skipped_sources": 0,
                    "malformed_sources": 0,
                    "encrypted_sources": 0,
                    "entries_seen": 0,
                    "entries_imported": 0,
                    "accounts_created": 0,
                    "accounts_existing": 0,
                    "unreadable_targets": 0,
                    "unreadable_metadata": 0,
                    "backups_created": 0,
                    "metadata_backups_created": 0,
                    "account_store_resets": 0,
                },
                "events": [_valid_legacy_import_event(entries=0, imported=0)],
            }
        ),
        encoding="utf-8",
    )
    markdown_path.write_text(
        "\n".join(
            [
                "# TeeBotus Legacy User Memory Import",
                "",
                "## Apply Safety",
                "",
                "- apply_allowed_now: `True`",
                "- apply_requires_stopped_bot: `False`",
                "- running_bot_process_count: `0`",
                "",
                "### Running Bot Processes",
                "",
                "## Totals",
                "",
                "## Events",
                "",
            ]
        ),
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._legacy_import_artifact_errors(
        (
            "python-test",
            "scripts/import_legacy_user_memory.py",
            "--instance",
            "Demo",
            "--json-output",
            str(json_path),
            "--markdown-output",
            str(markdown_path),
        )
    )

    assert any("places running processes before totals" in error for error in errors)


def test_legacy_import_markdown_validation_requires_metadata_reset_flag(tmp_path: Path) -> None:
    markdown_path = tmp_path / "import-demo.md"
    _write_valid_legacy_import_markdown(markdown_path)
    text = markdown_path.read_text(encoding="utf-8")
    markdown_path.write_text(
        text.replace(
            "action=`would-import`",
            "action=`would-import-after-metadata-reset`",
        ),
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._legacy_import_markdown_artifact_errors(markdown_path)

    assert errors == [f"legacy import markdown artifact metadata-reset event lacks metadata_unreadable flag: {markdown_path}"]


def test_legacy_import_markdown_validation_rejects_bad_metadata_reset_accounts(tmp_path: Path) -> None:
    markdown_path = tmp_path / "import-demo.md"
    _write_valid_legacy_import_markdown(markdown_path)
    text = markdown_path.read_text(encoding="utf-8")
    markdown_path.write_text(
        text.replace(
            "action=`would-import`",
            "action=`would-import` metadata_reset_accounts=`not-valid`",
        ),
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._legacy_import_markdown_artifact_errors(markdown_path)

    assert any("metadata_reset_accounts lacks metadata reset context" in error for error in errors)
    assert any("metadata_reset_accounts contains invalid short account id" in error for error in errors)


def test_benchmark_artifact_validation_rejects_secret_leaks(tmp_path: Path) -> None:
    markdown_path = tmp_path / "bench.md"
    json_path = tmp_path / "bench.json"
    markdown_path.write_text(
        "# TeeBotus Benchmarks\n\n## Results\n\napi_key=plain-secret\n\n## Regression Check\n\nok\n",
        encoding="utf-8",
    )
    payload = _valid_benchmark_payload()
    payload["results"][0]["details"]["api_key"] = "plain-secret"
    json_path.write_text(json.dumps(payload), encoding="utf-8")

    markdown_errors = check_plan2_acceptance._markdown_artifact_errors(markdown_path)
    json_errors = check_plan2_acceptance._json_benchmark_artifact_errors(json_path)

    assert any("benchmark markdown artifact contains secret-looking content" in error for error in markdown_errors)
    assert any("benchmark JSON artifact contains secret-looking content" in error for error in json_errors)


def test_benchmark_markdown_artifact_validation_accepts_rendered_report(tmp_path: Path) -> None:
    from TeeBotus.benchmarks.reporting import render_markdown
    from TeeBotus.benchmarks.suite import run_benchmarks

    markdown_path = tmp_path / "bench.md"
    suite = run_benchmarks(entries=1, iterations=1, quick=True)
    markdown_path.write_text(render_markdown(suite), encoding="utf-8")

    errors = check_plan2_acceptance._markdown_artifact_errors(markdown_path)

    assert errors == []


def test_benchmark_markdown_artifact_validation_requires_complete_report_sections(tmp_path: Path) -> None:
    markdown_path = tmp_path / "bench.md"
    markdown_path.write_text(
        "# TeeBotus Benchmarks\n\n## Results\n\n## Regression Check\n",
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._markdown_artifact_errors(markdown_path)

    assert any("lacks context marker '- python:'" in error for error in errors)
    assert any("lacks dependencies section" in error for error in errors)
    assert any("lacks results table" in error for error in errors)
    assert any("lacks stable backend rankings section" in error for error in errors)
    assert any("lacks quality gate section" in error for error in errors)
    assert any("lacks no-live-calls note" in error for error in errors)


def test_benchmark_markdown_artifact_validation_requires_core_result_names(tmp_path: Path) -> None:
    from TeeBotus.benchmarks.reporting import render_markdown

    payload = _valid_benchmark_payload()
    payload["generated_at"] = "2026-06-17T00:00:00+00:00"
    markdown_path = tmp_path / "bench.md"
    markdown_path.write_text(
        render_markdown(payload).replace(
            "| memory_jsonl | account_memory |",
            "| memory_jsonl_missing | account_memory |",
        ),
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._markdown_artifact_errors(markdown_path)

    assert f"benchmark markdown artifact missing required benchmark result memory_jsonl: {markdown_path}" in errors


def test_benchmark_markdown_artifact_validation_requires_core_result_categories(tmp_path: Path) -> None:
    from TeeBotus.benchmarks.reporting import render_markdown

    payload = _valid_benchmark_payload()
    payload["generated_at"] = "2026-06-17T00:00:00+00:00"
    markdown_path = tmp_path / "bench.md"
    markdown_path.write_text(
        render_markdown(payload).replace(
            "| memory_jsonl | account_memory |",
            "| memory_jsonl | qdrant |",
        ),
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._markdown_artifact_errors(markdown_path)

    assert f"benchmark markdown artifact required result memory_jsonl category must be account_memory: {markdown_path}" in errors


def test_benchmark_markdown_artifact_validation_requires_core_ranking_categories(tmp_path: Path) -> None:
    from TeeBotus.benchmarks.reporting import render_markdown

    payload = _valid_benchmark_payload()
    payload["generated_at"] = "2026-06-17T00:00:00+00:00"
    markdown = render_markdown(payload)
    markdown = markdown.replace("| retrieval | 1 |", "| retrieval_missing | 1 |")
    markdown = markdown.replace("| retrieval | 2 |", "| retrieval_missing | 2 |")
    markdown = markdown.replace("| retrieval | 3 |", "| retrieval_missing | 3 |")
    markdown_path = tmp_path / "bench.md"
    markdown_path.write_text(markdown, encoding="utf-8")

    errors = check_plan2_acceptance._markdown_artifact_errors(markdown_path)

    assert f"benchmark markdown artifact missing required benchmark ranking retrieval: {markdown_path}" in errors


def test_benchmark_markdown_artifact_validation_requires_core_ranking_candidate_count(tmp_path: Path) -> None:
    from TeeBotus.benchmarks.reporting import render_markdown

    payload = _valid_benchmark_payload()
    payload["generated_at"] = "2026-06-17T00:00:00+00:00"
    markdown = render_markdown(payload).replace(
        "| retrieval | 2 |",
        "| retrieval_missing | 2 |",
    ).replace(
        "| retrieval | 3 |",
        "| retrieval_missing | 3 |",
    )
    markdown_path = tmp_path / "bench.md"
    markdown_path.write_text(markdown, encoding="utf-8")

    errors = check_plan2_acceptance._markdown_artifact_errors(markdown_path)

    assert f"benchmark markdown artifact ranking retrieval must compare at least 2 candidates: {markdown_path}" in errors


def test_benchmark_markdown_artifact_validation_requires_teebotus_dependency(tmp_path: Path) -> None:
    from TeeBotus.benchmarks.reporting import render_markdown

    payload = _valid_benchmark_payload()
    payload["generated_at"] = "2026-06-17T00:00:00+00:00"
    markdown_path = tmp_path / "bench.md"
    markdown_path.write_text(
        render_markdown(payload).replace(
            "| teebotus | 1.6.13 | worktree |",
            "| other-package | 1.6.13 | worktree |",
        ),
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._markdown_artifact_errors(markdown_path)

    assert f"benchmark markdown artifact lacks teebotus dependency row: {markdown_path}" in errors


def test_benchmark_artifact_validation_rejects_secret_lists_in_json(tmp_path: Path) -> None:
    json_path = tmp_path / "bench.json"
    payload = _valid_benchmark_payload()
    payload["results"][0]["details"]["tokens"] = ["plain-secret"]
    json_path.write_text(json.dumps(payload), encoding="utf-8")

    errors = check_plan2_acceptance._json_benchmark_artifact_errors(json_path)

    assert any("benchmark JSON artifact contains secret-looking content" in error for error in errors)


def test_secret_artifact_validation_rejects_nested_secret_lists_in_json(tmp_path: Path) -> None:
    json_path = tmp_path / "import.json"
    json_path.write_text(
        json.dumps({"status": "ok", "auth": {"access_tokens": ["plain-secret"]}}),
        encoding="utf-8",
    )

    errors = check_plan2_acceptance._secret_artifact_errors(("script.py", "--json-output", str(json_path)))

    assert errors == [f"--json-output artifact contains secret-looking content: {json_path}"]


def test_benchmark_artifact_validation_allows_env_var_names_without_values(tmp_path: Path) -> None:
    json_path = tmp_path / "bench.json"
    payload = _valid_benchmark_payload()
    payload["results"][0]["details"]["api_key_env"] = "GROQ_API_KEY"
    json_path.write_text(json.dumps(payload), encoding="utf-8")

    errors = check_plan2_acceptance._json_benchmark_artifact_errors(json_path)

    assert not any("secret-looking content" in error for error in errors)


def test_systemd_unit_validation_flags_public_or_unchecked_units() -> None:
    qdrant_errors = check_plan2_acceptance._systemd_unit_errors(
        "qdrant-systemd-print",
        "\n".join(
            [
                "[Unit]",
                "[Service]",
                "ExecStart=podman run --rm --name teebotus-qdrant -p 0.0.0.0:6333:6333 qdrant/qdrant:latest",
                "[Install]",
            ]
        ),
    )
    teebotus_errors = check_plan2_acceptance._systemd_unit_errors(
        "teebotus-systemd-print",
        "\n".join(
            [
                "[Unit]",
                "[Service]",
                "EnvironmentFile=-/tmp/.env",
                "ExecStart=python3 -m TeeBotus --all",
                "[Install]",
            ]
        ),
    )

    assert any("127.0.0.1" in error for error in qdrant_errors)
    assert any("pinned" in error for error in qdrant_errors)
    assert any("volume preflight" in error for error in qdrant_errors)
    assert any("permission check missing" in error for error in teebotus_errors)
    assert any("multi-channel" in error for error in teebotus_errors)


def test_systemd_unit_validation_accepts_current_rendered_units(tmp_path: Path) -> None:
    from TeeBotus.qdrant_systemd import render_qdrant_systemd_unit
    from TeeBotus.systemd import render_teebotus_systemd_unit

    assert check_plan2_acceptance._systemd_unit_errors(
        "qdrant-systemd-print",
        render_qdrant_systemd_unit().service_text,
    ) == []
    assert check_plan2_acceptance._systemd_unit_errors(
        "teebotus-systemd-print",
        render_teebotus_systemd_unit(repo_root=tmp_path).service_text,
    ) == []


def test_systemd_unit_validation_accepts_teebotus_venv_python(tmp_path: Path) -> None:
    from TeeBotus.systemd import render_teebotus_systemd_unit

    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!/bin/sh\n", encoding="utf-8")

    unit = render_teebotus_systemd_unit(repo_root=tmp_path)
    errors = check_plan2_acceptance._systemd_unit_errors("teebotus-systemd-print", unit.service_text)

    assert errors == []


def test_benchmark_artifact_validation_requires_plan2_core_categories() -> None:
    payload = {
        "schema_version": 1,
        "quick": True,
        "include_live": False,
        "ok": True,
        "results": [
            {
                "name": "memory_jsonl",
                "category": "account_memory",
                "ok": True,
                "mode": "local",
                "iterations": 1,
                "total_ms": 1.0,
                "throughput_ops_s": 100.0,
                "errors": 0,
                "payload_bytes": 1,
                "index_bytes": 1,
                "details": {"network_calls": 0},
            }
        ],
        "comparisons": {"stable_backend_rankings": [_valid_ranking("account_memory")]},
        "quality_gate": {"status": "ok", "ok": True, "checked_results": 1, "error_count": 0, "errors": []},
        "regression": {"status": "not_configured", "failed": False},
    }

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert any("benchmark results missing required categories" in error for error in errors)
    assert any("pydantic_ai" in error and "mcp_tools" in error and "transcription_youtube" in error for error in errors)


def test_benchmark_artifact_validation_requires_plan2_ranking_categories() -> None:
    payload = {
        "schema_version": 1,
        "quick": True,
        "include_live": False,
        "ok": True,
        "results": [
            {
                "name": f"{category}_benchmark",
                "category": category,
                "ok": True,
                "mode": "local",
                "iterations": 1,
                "total_ms": 1.0,
                "throughput_ops_s": 100.0,
                "errors": 0,
                "payload_bytes": 1,
                "index_bytes": 1,
                "details": {"network_calls": 0},
            }
            for category in sorted(check_plan2_acceptance.REQUIRED_BENCHMARK_CATEGORIES)
        ],
        "comparisons": {"stable_backend_rankings": [_valid_ranking("account_memory")]},
        "quality_gate": {
            "status": "ok",
            "ok": True,
            "checked_results": len(check_plan2_acceptance.REQUIRED_BENCHMARK_CATEGORIES),
            "error_count": 0,
            "errors": [],
        },
        "regression": {"status": "not_configured", "failed": False},
    }

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert any("benchmark rankings missing required categories" in error for error in errors)
    assert any("bibliothekar" in error and "langgraph_flows" in error and "retrieval" in error for error in errors)


def test_benchmark_artifact_validation_rejects_required_name_with_wrong_category() -> None:
    payload = _valid_benchmark_payload()
    result = next(item for item in payload["results"] if item["name"] == "memory_jsonl")
    result["category"] = "qdrant"

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert any("computed quality_gate: memory_jsonl category must be account_memory" in error for error in errors)


def test_benchmark_artifact_validation_rejects_duplicate_result_names() -> None:
    payload = _valid_benchmark_payload()
    duplicate = dict(next(item for item in payload["results"] if item["name"] == "memory_jsonl"))
    duplicate["category"] = "qdrant"
    payload["results"].append(duplicate)
    payload["quality_gate"]["checked_results"] = len(payload["results"])

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert "benchmark result names must be unique: memory_jsonl" in errors
    assert "computed quality_gate: duplicate benchmark result name: memory_jsonl" in errors


def test_benchmark_artifact_validation_requires_plan2_measurement_fields() -> None:
    payload = {
        "schema_version": 1,
        "quick": True,
        "include_live": False,
        "ok": True,
        "results": [
            {
                "name": "memory_jsonl",
                "category": "account_memory",
                "ok": True,
                "mode": "local",
                "iterations": 0,
                "total_ms": -1.0,
                "throughput_ops_s": 100.0,
                "errors": False,
                "payload_bytes": "unknown",
                "details": {},
            }
        ],
        "comparisons": {"stable_backend_rankings": [{"category": "account_memory", "candidates": [{"name": "memory_jsonl"}]}]},
        "quality_gate": {"status": "ok", "ok": True, "checked_results": 1, "error_count": 0, "errors": []},
        "regression": {"status": "not_configured", "failed": False},
    }

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert any("results[0] missing index_bytes" in error for error in errors)
    assert any("results[0] total_ms must be a non-negative number" in error for error in errors)
    assert any("results[0] payload_bytes must be a non-negative number" in error for error in errors)
    assert any("results[0] errors must be a non-negative integer" in error for error in errors)
    assert any("results[0] iterations must be a positive integer" in error for error in errors)
    assert any("results[0] details must be a non-empty object" in error for error in errors)


def test_benchmark_artifact_validation_requires_no_live_counters() -> None:
    payload = _valid_benchmark_payload()
    payload["results"][0]["details"] = {"network_calls": 0}

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert any("results[0] details missing standard no-live counters" in error for error in errors)
    assert any("openai_calls" in error and "provider_calls" in error and "remote_calls" in error for error in errors)


def test_benchmark_artifact_validation_requires_bibliothekar_provenance_details() -> None:
    payload = _valid_benchmark_payload()
    bibliothekar = next(result for result in payload["results"] if result["category"] == "bibliothekar")
    bibliothekar["details"]["provenance_fields_complete"] = False
    bibliothekar["details"]["citation_missing_fields"] = ["file_sha256", "ingested_at"]
    bibliothekar["details"]["citation_required_fields"] = ["chunk_id", "file", "locator", "citation_format"]

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert any("bibliothekar provenance_fields_complete must be true" in error for error in errors)
    assert any("bibliothekar citation_missing_fields must be empty" in error for error in errors)
    assert any("bibliothekar citation_required_fields missing" in error and "file_sha256" in error and "ingested_at" in error for error in errors)


def test_benchmark_artifact_validation_requires_bibliothekar_backend_results() -> None:
    payload = _valid_benchmark_payload()
    payload["results"] = [
        result
        for result in payload["results"]
        if result["name"] != "bibliothekar_llamaindex_fake_query"
    ]
    payload["quality_gate"]["checked_results"] = len(payload["results"])

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert any("benchmark results missing required bibliothekar backends" in error for error in errors)
    assert any("bibliothekar_llamaindex_fake_query" in error for error in errors)


def test_benchmark_artifact_validation_requires_bibliothekar_ranking_backends() -> None:
    payload = _valid_benchmark_payload()
    bibliothekar_ranking = next(ranking for ranking in payload["comparisons"]["stable_backend_rankings"] if ranking["category"] == "bibliothekar")
    bibliothekar_ranking["candidates"] = [
        candidate
        for candidate in bibliothekar_ranking["candidates"]
        if candidate["name"] != "bibliothekar_llamaindex_fake_query"
    ]

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert any("bibliothekar candidates missing required backends" in error for error in errors)
    assert any("bibliothekar_llamaindex_fake_query" in error for error in errors)


def test_benchmark_artifact_validation_rejects_unknown_ranking_categories() -> None:
    payload = _valid_benchmark_payload()
    payload["comparisons"]["stable_backend_rankings"].append(
        {
            "category": "custom_backend",
            "fastest_stable": "custom_b",
            "candidates": [
                {
                    "rank": 1,
                    "name": "custom_b",
                    "mode": "local",
                    "throughput_ops_s": 100.0,
                    "total_ms": 1.0,
                    "errors": 0,
                    "payload_bytes": 1,
                    "index_bytes": 1,
                }
            ],
            "skipped": [],
        }
    )

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert any("rankings[5] category must be one of required benchmark ranking categories" in error for error in errors)


def test_benchmark_artifact_validation_requires_pydantic_decision_details() -> None:
    payload = _valid_benchmark_payload()
    decision_result = next(result for result in payload["results"] if result["name"] == "pydantic_structured_decisions")
    decision_result["details"]["schemas"] = ["BibliothekarQueryDecision"]
    decision_result["details"]["fake_agent_calls"] = 0

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert any("pydantic schemas missing required decisions" in error and "AgentTaskDecision" in error for error in errors)
    assert any("pydantic fake_agent_calls must be a positive integer" in error for error in errors)


def test_benchmark_artifact_validation_requires_hf_pool_eval_details() -> None:
    payload = _valid_benchmark_payload()
    hf_eval = next(result for result in payload["results"] if result["name"] == "hf_pool_eval_matrix")
    hf_eval["details"]["purposes"] = ["normal_chat"]
    hf_eval["details"]["routed_purposes"] = ["normal_chat"]
    hf_eval["details"]["structured_decision_json_valid"] = False
    hf_eval["details"]["structured_decision_confidence"] = 1.5
    hf_eval["details"]["normal_chat_median_latency_ms"] = 0.0
    hf_eval["details"]["psychology_quality_score"] = 2
    hf_eval["details"]["psychology_quality_checks"] = {"validierend": True, "keine_diagnose": False}
    hf_eval["details"]["bibliothekar_citation_faithful"] = False
    hf_eval["details"]["bibliothekar_citation_fields"] = {"chunk_id": True, "file": False}
    hf_eval["details"]["cooldown_state_key"] = "bench_normal_chat"
    hf_eval["details"]["cooldown_network_calls"] = 1
    hf_eval["details"]["summarizer_terms"] = {"aktivierung": True, "schlafhygiene": False}
    hf_eval["details"]["summarizer_hallucinated"] = True
    hf_eval["details"]["mock_executor_calls"] = 0

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert any("hf_pool purposes missing required evals" in error and "structured_decision" in error for error in errors)
    assert any("hf_pool routed_purposes missing" in error and "structured_decision" in error for error in errors)
    assert any("hf_pool structured_decision_json_valid must be true" in error for error in errors)
    assert any("hf_pool structured_decision_confidence must be between 0 and 1" in error for error in errors)
    assert any("hf_pool normal_chat_median_latency_ms must be positive" in error for error in errors)
    assert any("hf_pool psychology_quality_score must be at least 3" in error for error in errors)
    assert any("hf_pool psychology_quality_checks missing" in error and "kleiner_schritt" in error for error in errors)
    assert any("hf_pool psychology_quality_checks entries must be true" in error and "keine_diagnose" in error for error in errors)
    assert any("hf_pool bibliothekar_citation_faithful must be true" in error for error in errors)
    assert any("hf_pool bibliothekar_citation_fields missing" in error and "locator" in error for error in errors)
    assert any("hf_pool bibliothekar_citation_fields entries must be true" in error and "file" in error for error in errors)
    assert any("hf_pool summarizer_terms missing" in error and "kleine_aufgaben" in error for error in errors)
    assert any("hf_pool summarizer_terms entries must be true" in error and "schlafhygiene" in error for error in errors)
    assert any("hf_pool summarizer_hallucinated must be false" in error for error in errors)
    assert any("hf_pool cooldown_state_key must be pool-scoped" in error for error in errors)
    assert any("hf_pool cooldown_network_calls must be 0" in error for error in errors)
    assert any("hf_pool mock_executor_calls must cover all eval purposes" in error for error in errors)


def test_benchmark_artifact_validation_requires_hf_pool_eval_result() -> None:
    payload = _valid_benchmark_payload()
    payload["results"] = [result for result in payload["results"] if result["name"] != "hf_pool_eval_matrix"]
    payload["quality_gate"]["checked_results"] = len(payload["results"])

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert "benchmark results missing required hf_pool_eval_matrix result" in errors


def test_benchmark_artifact_validation_requires_retrieval_matrix_details() -> None:
    payload = _valid_benchmark_payload()
    retrieval = next(result for result in payload["results"] if result["name"] == "retrieval_embedding_reranker_matrix")
    retrieval["details"]["usermemory_models"] = ["intfloat/multilingual-e5-small"]
    retrieval["details"]["book_models"] = ["BAAI/bge-m3"]
    retrieval["details"]["backend_modes"] = ["local"]
    retrieval["details"]["backend_selected"] = {"local": 1, "llamaindex_fake": 0}
    retrieval["details"]["reranker_comparison"] = {
        "without_reranker_model": "wrong",
        "without_reranker_top": [],
        "with_reranker_model": "wrong",
        "with_reranker_top": [],
    }

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert any("retrieval usermemory_models missing" in error and "intfloat/multilingual-e5-base" in error for error in errors)
    assert any("retrieval book_models missing" in error and "intfloat/multilingual-e5-base" in error for error in errors)
    assert any("retrieval backend_modes missing" in error and "haystack_fake" in error for error in errors)
    assert any("retrieval without_reranker_model must be BAAI/bge-m3" in error for error in errors)
    assert any("retrieval with_reranker_model must be BAAI/bge-reranker-v2-m3" in error for error in errors)
    assert any("retrieval without_reranker_top must be a non-empty list" in error for error in errors)
    assert any("retrieval backend_selected missing" in error and "haystack_fake" in error for error in errors)
    assert any("retrieval backend_selected.llamaindex_fake must be a positive integer" in error for error in errors)


def test_benchmark_artifact_validation_requires_retrieval_matrix_result() -> None:
    payload = _valid_benchmark_payload()
    payload["results"] = [result for result in payload["results"] if result["name"] != "retrieval_embedding_reranker_matrix"]
    payload["quality_gate"]["checked_results"] = len(payload["results"])

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert "benchmark results missing required retrieval_embedding_reranker_matrix result" in errors


def test_benchmark_artifact_validation_requires_pydantic_structured_result() -> None:
    payload = _valid_benchmark_payload()
    payload["results"] = [result for result in payload["results"] if result["name"] != "pydantic_structured_decisions"]
    payload["quality_gate"]["checked_results"] = len(payload["results"])

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert "benchmark results missing required pydantic_structured_decisions result" in errors


def test_benchmark_artifact_validation_rejects_live_or_nonquick_standard_artifacts() -> None:
    payload = {
        "schema_version": 1,
        "quick": False,
        "include_live": True,
        "live_hf": True,
        "live_qdrant": True,
        "ok": True,
        "results": [
            {
                "name": f"{category}_benchmark",
                "category": category,
                "ok": True,
                "mode": "local",
                "iterations": 1,
                "total_ms": 1.0,
                "throughput_ops_s": 100.0,
                "errors": 0,
                "payload_bytes": 1,
                "index_bytes": 1,
                "details": {"network_calls": 0},
            }
            for category in sorted(check_plan2_acceptance.REQUIRED_BENCHMARK_CATEGORIES)
        ],
        "comparisons": {
            "auto_switching": False,
            "selection_policy": "document_fastest_stable_backend_only",
            "stable_backend_rankings": [
                _valid_ranking(category)
                for category in sorted(check_plan2_acceptance.REQUIRED_BENCHMARK_RANKING_CATEGORIES)
            ]
        },
        "quality_gate": {
            "status": "ok",
            "ok": True,
            "checked_results": len(check_plan2_acceptance.REQUIRED_BENCHMARK_CATEGORIES),
            "error_count": 0,
            "errors": [],
        },
        "regression": {"status": "not_configured", "failed": False},
    }

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert "quick must be true for standard Plan2 benchmark artifacts" in errors
    assert "include_live must be false for standard Plan2 benchmark artifacts" in errors
    assert "live_hf must be false for standard Plan2 benchmark artifacts" in errors
    assert "live_qdrant must be false for standard Plan2 benchmark artifacts" in errors


def test_benchmark_artifact_validation_rejects_automatic_backend_switching() -> None:
    payload = _valid_benchmark_payload()
    payload["comparisons"]["auto_switching"] = True
    payload["comparisons"]["selection_policy"] = "switch_to_fastest"

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert "comparisons.auto_switching must be false" in errors
    assert "comparisons.selection_policy must be document_fastest_stable_backend_only" in errors


def test_benchmark_artifact_validation_rejects_provider_or_network_calls_in_standard_artifacts() -> None:
    payload = _valid_benchmark_payload()
    payload["results"][0]["mode"] = "live_optional"
    payload["results"][1]["details"]["network_calls"] = 1
    payload["results"][2]["details"]["nested"] = {"openai_calls": 2}
    payload["results"][3]["details"]["llm_calls"] = 1

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert "results[0] must not use live mode in standard Plan2 benchmark artifacts" in errors
    assert "results[1] details.network_calls must be 0 in standard Plan2 benchmark artifacts, got 1" in errors
    assert "results[2] details.nested.openai_calls must be 0 in standard Plan2 benchmark artifacts, got 2" in errors
    assert "results[3] details.llm_calls must be 0 in standard Plan2 benchmark artifacts, got 1" in errors


def test_benchmark_artifact_validation_rejects_ok_results_with_errors() -> None:
    payload = _valid_benchmark_payload()
    payload["results"][0]["errors"] = 1

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert "results[0] errors must be 0 for ok standard benchmark results" in errors


def test_benchmark_artifact_validation_rejects_malformed_skipped_results() -> None:
    payload = _valid_benchmark_payload()
    result_index = len(payload["results"])
    payload["results"].append(
        {
            "name": "memory_postgres",
            "category": "account_memory",
            "ok": True,
            "skipped": True,
            "iterations": 1,
            "total_ms": 1.0,
            "throughput_ops_s": 1.0,
            "errors": 1,
            "payload_bytes": 0,
            "index_bytes": 0,
            "mode": "",
            "reason": "",
            "details": {"network_calls": 1},
        }
    )
    payload["quality_gate"]["checked_results"] = len(payload["results"])

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert f"results[{result_index}] skipped result must not be ok" in errors
    assert f"results[{result_index}] skipped result iterations must be 0" in errors
    assert f"results[{result_index}] skipped result errors must be 0" in errors
    assert f"results[{result_index}] skipped result reason must be non-empty" in errors
    assert f"results[{result_index}] skipped result mode must be non-empty" in errors
    assert any(f"results[{result_index}] details missing standard no-live counters" in error for error in errors)
    assert f"results[{result_index}] details.network_calls must be 0 in standard Plan2 benchmark artifacts, got 1" in errors


def test_benchmark_artifact_validation_rejects_invalid_ranking_candidates() -> None:
    payload = _valid_benchmark_payload()
    ranking = payload["comparisons"]["stable_backend_rankings"][0]
    ranking["fastest_stable"] = "skipped_backend"
    ranking["skipped"] = [{"name": "skipped_backend", "mode": "live_optional", "reason": "missing dsn"}]
    ranking["candidates"][0] = {
        "rank": 2,
        "name": "candidate_with_errors",
        "mode": "live_optional",
        "throughput_ops_s": 1000.0,
        "total_ms": 0.1,
        "errors": 1,
        "payload_bytes": 0,
        "index_bytes": 0,
    }

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert any("rankings[0].candidates[0] rank must be 1" in error for error in errors)
    assert any("rankings[0].candidates[0] name must belong to account_memory ranking benchmark set" in error for error in errors)
    assert any("rankings[0].candidates[0] errors must be 0" in error for error in errors)
    assert any("rankings[0].candidates[0] must not use live mode" in error for error in errors)
    assert any("rankings[0].candidates[0] must report payload_bytes or index_bytes" in error for error in errors)
    assert any("rankings[0] fastest_stable must match rank 1 candidate" in error for error in errors)
    assert any("rankings[0] fastest_stable must not be skipped" in error for error in errors)


def test_benchmark_artifact_validation_rejects_invalid_ranking_skips() -> None:
    payload = _valid_benchmark_payload()
    ranking = payload["comparisons"]["stable_backend_rankings"][0]
    ranking["skipped"] = [
        {"name": "", "mode": "", "reason": ""},
        {"name": "memory_jsonl", "mode": "live_optional", "reason": ""},
        {"name": "duplicate_skip", "mode": "live_optional", "reason": "missing dsn"},
        {"name": "duplicate_skip", "mode": "live_optional", "reason": "still missing dsn"},
    ]

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert any("rankings[0].skipped[0] name must be non-empty" in error for error in errors)
    assert any("rankings[0].skipped[0] mode must be non-empty" in error for error in errors)
    assert any("rankings[0].skipped[0] reason must be non-empty" in error for error in errors)
    assert any("rankings[0].skipped[1] reason must be non-empty" in error for error in errors)
    assert any("rankings[0] skipped item must not also be a candidate: memory_jsonl" in error for error in errors)
    assert any("rankings[0] duplicate skipped name: duplicate_skip" in error for error in errors)
    assert any("rankings[0].skipped[2] name must belong to account_memory ranking benchmark set" in error for error in errors)


def test_benchmark_artifact_validation_rejects_ranking_skips_without_matching_results() -> None:
    payload = _valid_benchmark_payload()
    ranking = payload["comparisons"]["stable_backend_rankings"][0]
    ranking["skipped"] = [{"name": "memory_postgres", "mode": "live_optional", "reason": "missing dsn"}]

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert any("rankings[0].skipped[0] must reference a skipped result" in error for error in errors)


def test_benchmark_artifact_validation_rejects_ranking_skips_that_do_not_match_results() -> None:
    payload = _valid_benchmark_payload()
    payload["results"].append(
        {
            "name": "memory_postgres",
            "category": "qdrant",
            "ok": False,
            "skipped": True,
            "iterations": 0,
            "total_ms": 0.0,
            "throughput_ops_s": 0.0,
            "errors": 0,
            "payload_bytes": 0,
            "index_bytes": 0,
            "mode": "live_optional",
            "reason": "different reason",
            "details": {
                "network_calls": 0,
                "openai_calls": 0,
                "provider_calls": 0,
                "remote_calls": 0,
                "llm_calls": 0,
            },
        }
    )
    ranking = payload["comparisons"]["stable_backend_rankings"][0]
    ranking["skipped"] = [{"name": "memory_postgres", "mode": "live_optional", "reason": "missing dsn"}]

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert any("rankings[0].skipped[0] category must match skipped result category" in error for error in errors)
    assert any("rankings[0].skipped[0] reason must match skipped result" in error for error in errors)


def test_benchmark_artifact_validation_rejects_rankings_without_matching_results() -> None:
    payload = _valid_benchmark_payload()
    ranking = payload["comparisons"]["stable_backend_rankings"][0]
    ranking["fastest_stable"] = "synthetic_fastest"
    ranking["candidates"][0]["name"] = "synthetic_fastest"

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert any("rankings[0].candidates[0] must reference a successful result" in error for error in errors)


def test_benchmark_artifact_validation_requires_ranking_comparisons_not_single_candidate_smokes() -> None:
    payload = _valid_benchmark_payload()
    ranking = payload["comparisons"]["stable_backend_rankings"][0]
    ranking["candidates"] = ranking["candidates"][:1]

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert any("rankings[0]" in error and "must compare at least 2 successful candidates" in error for error in errors)


def test_benchmark_artifact_validation_requires_runtime_context() -> None:
    payload = _valid_benchmark_payload()
    payload["context"] = {
        "python": "",
        "cpu_count": "unknown",
        "dependencies": {},
    }

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert "context missing required keys: machine, platform" in errors
    assert "context.cpu_count must be a non-negative integer" in errors
    assert "context.dependencies must be a non-empty object" in errors
    assert "context.python must be non-empty" in errors


def test_benchmark_artifact_validation_requires_core_dependency_context() -> None:
    payload = _valid_benchmark_payload()
    dependencies = payload["context"]["dependencies"]
    dependencies.pop("faster-whisper")
    dependencies["langgraph"] = {"version": "1.0.0", "status": ""}
    dependencies["qdrant-haystack"] = {"status": "installed"}

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert any("context.dependencies missing required packages" in error and "faster-whisper" in error for error in errors)
    assert "context.dependencies.langgraph.status must be non-empty" in errors
    assert "context.dependencies.qdrant-haystack.version must be present" in errors


def test_benchmark_artifact_validation_requires_successful_quality_gate() -> None:
    payload = _valid_benchmark_payload()
    payload["quality_gate"] = {
        "status": "failed",
        "ok": False,
        "checked_results": "unknown",
        "error_count": 2,
        "errors": "benchmark smoke only",
    }

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert "quality_gate.ok must be true" in errors
    assert "quality_gate.status must be ok" in errors
    assert "quality_gate.checked_results must be a non-negative integer" in errors
    assert "quality_gate.error_count must be 0" in errors
    assert "quality_gate.errors must be a list" in errors


def test_benchmark_artifact_validation_requires_quality_gate_to_cover_all_results() -> None:
    payload = _valid_benchmark_payload()
    payload["quality_gate"]["checked_results"] = 1

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert "quality_gate.checked_results must match results length" in errors


def test_benchmark_artifact_validation_requires_successful_regression_gate() -> None:
    payload = _valid_benchmark_payload()
    payload["regression"] = {
        "status": "failed",
        "failed": True,
        "entries": [{"name": "account_memory_benchmark", "status": "regressed"}],
    }

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert "regression.status must be not_configured or ok" in errors
    assert "regression.failed must be false" in errors


def test_benchmark_artifact_validation_accepts_structured_ok_regression_gate() -> None:
    payload = _valid_benchmark_payload()
    current = next(result for result in payload["results"] if result["name"] == "memory_jsonl")
    payload["regression"] = {
        "status": "ok",
        "failed": False,
        "baseline_json": "/tmp/teebotus-benchmark-baseline.json",
        "max_total_ms_factor": 2.0,
        "min_throughput_factor": 0.5,
        "matched_results": 1,
        "entries": [
            {
                "name": "memory_jsonl",
                "status": "ok",
                "previous_total_ms": 2.0,
                "current_total_ms": current["total_ms"],
                "total_ms_factor": 0.5,
                "previous_throughput_ops_s": 50.0,
                "current_throughput_ops_s": current["throughput_ops_s"],
                "throughput_factor": 2.0,
            }
        ],
    }

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert not [error for error in errors if error.startswith("regression")]


def test_benchmark_artifact_validation_rejects_weak_regression_entries() -> None:
    payload = _valid_benchmark_payload()
    payload["regression"] = {
        "status": "ok",
        "failed": False,
        "baseline_json": "",
        "max_total_ms_factor": 0.0,
        "min_throughput_factor": "slow",
        "matched_results": 1,
        "entries": [
            {
                "name": "memory_jsonl",
                "status": "regressed",
                "previous_total_ms": "old",
                "current_total_ms": 999.0,
                "total_ms_factor": -1.0,
                "previous_throughput_ops_s": 50.0,
                "current_throughput_ops_s": 100.0,
                "throughput_factor": 2.0,
            },
            {
                "name": "synthetic_benchmark",
                "status": "ok",
                "previous_total_ms": 1.0,
                "current_total_ms": 1.0,
                "total_ms_factor": 1.0,
                "previous_throughput_ops_s": 100.0,
                "current_throughput_ops_s": 100.0,
                "throughput_factor": 1.0,
            },
        ],
    }

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert "regression.max_total_ms_factor must be a positive number" in errors
    assert "regression.min_throughput_factor must be a positive number" in errors
    assert "regression.baseline_json must be non-empty when status is ok" in errors
    assert "regression.matched_results must match regression entries length" in errors
    assert "regression.entries[0].status must be ok" in errors
    assert "regression.entries[0].previous_total_ms must be a non-negative number" in errors
    assert "regression.entries[0].total_ms_factor must be a non-negative number" in errors
    assert "regression.entries[0].current_total_ms must match current result total_ms" in errors
    assert "regression.entries[1] must reference a successful benchmark result" in errors


def test_benchmark_artifact_validation_rejects_configured_regression_without_matches() -> None:
    payload = _valid_benchmark_payload()
    payload["regression"] = {
        "status": "ok",
        "failed": False,
        "baseline_json": "/tmp/teebotus-benchmark-baseline.json",
        "matched_results": 0,
        "entries": [],
    }

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert "regression.entries must be non-empty when status is ok" in errors


def test_benchmark_artifact_validation_rejects_not_configured_regression_with_entries() -> None:
    payload = _valid_benchmark_payload()
    payload["regression"] = {
        "status": "not_configured",
        "failed": False,
        "entries": [
            {
                "name": "memory_jsonl",
                "status": "ok",
                "previous_total_ms": 1.0,
                "current_total_ms": 1.0,
                "total_ms_factor": 1.0,
                "previous_throughput_ops_s": 100.0,
                "current_throughput_ops_s": 100.0,
                "throughput_factor": 1.0,
            }
        ],
    }

    errors = check_plan2_acceptance._benchmark_payload_errors(payload)

    assert "regression.entries must be empty when status is not_configured" in errors


def test_plan2_acceptance_runner_fails_on_broken_runtime_status(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(argv, cwd, check, **kwargs):  # noqa: ANN001, ARG001
        calls.append(tuple(argv))
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=(
                "TeeBotus runtime configuration resolves.\n"
                "account_memory=Demo/abc status=broken error=recent_ids missing entries: mem_missing\n"
                "account_memory_recovery=Demo status=needed command=\"python3 -m TeeBotus.admin memory-recovery\"\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(check_plan2_acceptance.subprocess, "run", fake_run)

    result = check_plan2_acceptance.run_acceptance_commands(
        [
            check_plan2_acceptance.AcceptanceCommand(
                "runtime-status",
                ("python-test", "-m", "TeeBotus", "--runtime-status"),
                validate_runtime_status=True,
            ),
            check_plan2_acceptance.AcceptanceCommand("later", ("python-test", "-m", "pytest")),
        ]
    )

    assert result == 1
    assert calls == [("python-test", "-m", "TeeBotus", "--runtime-status")]


def test_plan2_acceptance_runner_checks_runtime_status_stderr(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []
    leaked_key = "sk-" + "runtimeStatusStderrLeak123456"

    def fake_run(argv, cwd, check, **kwargs):  # noqa: ANN001, ARG001
        calls.append(tuple(argv))
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout="TeeBotus runtime configuration resolves.\n",
            stderr=f"llm=Demo/telegram:1 provider=openai model=gpt status=configured api_key={leaked_key}\n",
        )

    monkeypatch.setattr(check_plan2_acceptance.subprocess, "run", fake_run)

    result = check_plan2_acceptance.run_acceptance_commands(
        [
            check_plan2_acceptance.AcceptanceCommand(
                "runtime-status",
                ("python-test", "-m", "TeeBotus", "--runtime-status"),
                validate_runtime_status=True,
            ),
            check_plan2_acceptance.AcceptanceCommand("later", ("python-test", "-m", "pytest")),
        ]
    )

    assert result == 1
    assert calls == [("python-test", "-m", "TeeBotus", "--runtime-status")]


def test_runtime_status_broken_lines_ignores_non_broken_statuses() -> None:
    output = "\n".join(
        [
            "llm=Demo/telegram:1 provider=openai model=gpt status=configured",
            "llm=Demo/signal:1 provider=litellm model=ollama_chat/qwen status=configured api_key=configured",
            "signal_service=Demo/signal:1 target=127.0.0.1:8080 status=reachable",
            "account_memory=Demo/abc status=ok",
            "llm=Demo/telegram:1 provider=hf_pool model=pool:default#structured_decision status=unavailable purpose=structured_decision api_key=none fallback_models=1 fallback_profile=local_ollama fallback_model=ollama_chat/llama3.1:8b",
            "ollama=127.0.0.1:11434 status=reachable models=llama3.1:8b",
            "local_transcription=Demo backend=local model=tiny status=ready engine=faster-whisper",
            "bibliothekar=Demo backend=local store=json collection=teebotus_bibliothekar_chunks status=ready documents=1 chunks=1",
            "bibliothekar=Demo backend=haystack store=qdrant collection=therapy_books target=http://127.0.0.1:6333 status=reachable documents=1 chunks=1",
            "bibliothekar=Demo backend=haystack store=qdrant collection=therapy_books target=http://localhost:6334 status=reachable documents=1 chunks=1",
            'account_memory_recovery_legacy=Demo status=available sources=1 entries=2 path=/tmp/TeeBotus_Backups/TeeBotus.bak2/instances.bak command="python3 scripts/import_legacy_user_memory.py --legacy-instances-dir /tmp/TeeBotus_Backups/TeeBotus.bak2 --target-instances-dir /tmp/TeeBotus/instances --instance Demo --replace-unreadable-account-metadata --json-output /tmp/import.json --markdown-output /tmp/import.md" apply_command="python3 scripts/import_legacy_user_memory.py --legacy-instances-dir /tmp/TeeBotus_Backups/TeeBotus.bak2 --target-instances-dir /tmp/TeeBotus/instances --instance Demo --replace-unreadable --replace-unreadable-account-metadata --apply"',
        ]
    )

    assert check_plan2_acceptance._runtime_status_broken_lines(output) == []


def test_runtime_status_missing_required_lines_flags_missing_plan3_diagnostics() -> None:
    complete = "\n".join(
        [
            "hf_pool=default status=disabled",
            "llm_route=structured_decision profile=hf_pool_structured provider=hf_pool model=pool:default#structured_decision status=unavailable fallback=local_ollama",
            "llm_route=bibliothekar_answer profile=gemini_flash_stateful provider=litellm_gemini_stateful model=gemini/gemini-3.5-flash status=configured api_key_env=GEMINI_API_KEY google_mode=stateful free_tier_guard=rpm=5,tpm=250000,rpd=20,reserve=2048",
            "structured_decision=Demo/telegram:1 status=enabled source=text_llm_enabled profile=hf_pool_structured provider=hf_pool model=pool:default#structured_decision route_status=unavailable fallback=local_ollama",
            "qdrant=127.0.0.1:6333 status=unreachable fallback=keyword_memory_search",
            "qdrant_collection=teebotus_user_memory target=127.0.0.1:6333 status=unavailable vector_size=64",
            "qdrant_collection=teebotus_bibliothekar_chunks target=127.0.0.1:6333 status=unavailable vector_size=1024",
        ]
    )
    incomplete = "\n".join(
        [
            "hf_pool=default status=disabled",
            "qdrant=127.0.0.1:6333 status=unreachable fallback=keyword_memory_search",
        ]
    )

    assert check_plan2_acceptance._runtime_status_missing_required_lines(complete) == []
    missing = check_plan2_acceptance._runtime_status_missing_required_lines(incomplete)
    assert "runtime-status missing structured decision provider line: llm_route=structured_decision" in missing
    assert "runtime-status missing bibliothekar Gemini route line: llm_route=bibliothekar_answer" in missing
    assert "runtime-status missing structured decision instance line: structured_decision=" in missing
    assert "runtime-status missing qdrant user-memory collection line: qdrant_collection=teebotus_user_memory" in missing


def test_runtime_status_missing_required_lines_flags_malformed_structured_route() -> None:
    output = "\n".join(
        [
            "hf_pool=default status=disabled",
            "llm_route=structured_decision profile=openai_premium provider=openai model=gpt-5.5 status=unavailable",
            "llm_route=bibliothekar_answer profile=local_ollama provider=litellm model=ollama_chat/llama3.1:8b status=configured",
            "structured_decision=Demo/telegram:1 status=enabled source=text_llm_enabled profile=hf_pool_structured provider=hf_pool model=pool:default#structured_decision route_status=unavailable fallback=local_ollama",
            "qdrant=127.0.0.1:6333 status=unreachable fallback=keyword_memory_search",
            "qdrant_collection=teebotus_user_memory target=127.0.0.1:6333 status=unavailable vector_size=64",
            "qdrant_collection=teebotus_bibliothekar_chunks target=127.0.0.1:6333 status=unavailable vector_size=1024",
        ]
    )

    missing = check_plan2_acceptance._runtime_status_missing_required_lines(output)

    assert "runtime-status structured decision route must use profile=hf_pool_structured" in missing
    assert "runtime-status structured decision route must use provider=hf_pool" in missing
    assert "runtime-status structured decision route must use model=pool:default#structured_decision" in missing
    assert "runtime-status unavailable structured decision route must show fallback" in missing
    assert "runtime-status bibliothekar route must use profile=gemini_flash_stateful" in missing
    assert "runtime-status bibliothekar route must use model=gemini/gemini-3.5-flash" in missing
    assert "runtime-status bibliothekar route must show google_mode=stateful" in missing
    assert "runtime-status bibliothekar route must show free_tier_guard" in missing


def test_runtime_status_account_memory_recovery_requires_matching_recovery_line() -> None:
    missing_lines = [
        "account_memory_metadata=Demo status=broken item=account_index path=/repo/instances/Demo/data/accounts/Account_Index.json error=encrypted envelope authentication failed",
    ]
    valid_lines = [
        missing_lines[0],
        'account_memory_recovery=Demo status=needed command="python3 -m TeeBotus.admin memory-recovery --instances-dir /repo/instances --instances Demo"',
    ]
    malformed_lines = [
        "account_memory=Demo/abc status=broken error=index_missing",
        'account_memory_recovery=Demo status=available command="python3 -m TeeBotus.admin memory-recovery --instances-dir /repo/instances --instances Other"',
    ]

    missing = check_plan2_acceptance._runtime_status_account_memory_recovery_errors(missing_lines)
    valid = check_plan2_acceptance._runtime_status_account_memory_recovery_errors(valid_lines)
    malformed = check_plan2_acceptance._runtime_status_account_memory_recovery_errors(malformed_lines)

    assert "runtime-status account-memory recovery missing for broken account-memory instance Demo" in missing
    assert valid == []
    assert any("must use status=needed" in error for error in malformed)
    assert any("command instance does not match status line" in error for error in malformed)


def test_runtime_status_missing_required_lines_validates_account_memory_legacy_recovery() -> None:
    valid_line = (
        'account_memory_recovery_legacy=Demo status=available sources=1 entries=2 path=/tmp/TeeBotus_Backups/TeeBotus.bak2/instances.bak '
        'command="python3 scripts/import_legacy_user_memory.py --legacy-instances-dir /tmp/TeeBotus_Backups/TeeBotus.bak2 --target-instances-dir /tmp/TeeBotus/instances --instance Demo --replace-unreadable-account-metadata --json-output /tmp/import.json --markdown-output /tmp/import.md" '
        'apply_command="python3 scripts/import_legacy_user_memory.py --legacy-instances-dir /tmp/TeeBotus_Backups/TeeBotus.bak2 --target-instances-dir /tmp/TeeBotus/instances --instance Demo --replace-unreadable --replace-unreadable-account-metadata --apply"'
    )

    assert check_plan2_acceptance._runtime_status_account_memory_recovery_legacy_errors([valid_line]) == []


def test_runtime_status_missing_required_lines_rejects_malformed_account_memory_legacy_recovery() -> None:
    broken_line = (
        'account_memory_recovery_legacy=Demo status=available sources=0 entries=2 path=/tmp/TeeBotus Backups/TeeBotus.bak2/instances.bak '
        'command="python3 scripts/import_legacy_user_memory.py --legacy-instances-dir /tmp/TeeBotus_Backups/TeeBotus.bak2 --target-instances-dir /tmp/TeeBotus/instances --instance Demo --replace-unreadable-account-metadata --apply" '
        'apply_command="python3 scripts/import_legacy_user_memory.py --legacy-instances-dir /tmp/TeeBotus_Backups/TeeBotus.bak2 --target-instances-dir /tmp/TeeBotus/instances --instance Demo --replace-unreadable-account-metadata --apply"'
    )

    errors = check_plan2_acceptance._runtime_status_account_memory_recovery_legacy_errors([broken_line])

    assert any("has unkeyed tokens" in error for error in errors)
    assert any("sources must be positive" in error for error in errors)
    assert any("preflight command must not include --apply" in error for error in errors)
    assert any("preflight command must write JSON and Markdown artifacts" in error for error in errors)
    assert any("apply_command missing --replace-unreadable" in error for error in errors)


def test_runtime_status_missing_required_lines_rejects_inconsistent_account_memory_legacy_recovery_paths() -> None:
    broken_line = (
        'account_memory_recovery_legacy=Demo status=available sources=1 entries=2 path=/tmp/Other_Backup/instances.bak '
        'command="python3 scripts/import_legacy_user_memory.py --legacy-instances-dir /tmp/TeeBotus_Backups/TeeBotus.bak2 --target-instances-dir /tmp/TeeBotus/instances --instance Other --replace-unreadable-account-metadata --json-output /tmp/import.json --markdown-output /tmp/import.md" '
        'apply_command="python3 scripts/import_legacy_user_memory.py --legacy-instances-dir /tmp/TeeBotus_Backups/TeeBotus.bak3 --target-instances-dir /tmp/TeeBotus/instances --instance Demo --replace-unreadable --replace-unreadable-account-metadata --apply"'
    )

    errors = check_plan2_acceptance._runtime_status_account_memory_recovery_legacy_errors([broken_line])

    assert any("command instance does not match status line" in error for error in errors)
    assert any("command and apply_command legacy paths differ" in error for error in errors)
    assert any("path is not below command --legacy-instances-dir" in error for error in errors)
    assert any("path is not below apply_command --legacy-instances-dir" in error for error in errors)


def test_runtime_status_broken_lines_flags_secret_leaks() -> None:
    openai_key = "sk-" + "liveSecretLeak123456"
    matrix_token = "syt_" + "liveSecretLeak123456"
    output = "\n".join(
        [
            f"llm=Demo/telegram:1 provider=openai model=gpt status=configured api_key={openai_key}",
            f"matrix_homeserver=Demo/matrix:1 target=matrix.example:443 status=reachable token={matrix_token}",
            "account_memory=Demo/abcdef status=ok",
        ]
    )

    assert check_plan2_acceptance._runtime_status_broken_lines(output) == output.splitlines()[:2]


def test_runtime_status_broken_lines_flags_generic_secret_assignments() -> None:
    output = "\n".join(
        [
            "llm=Demo/telegram:1 provider=litellm model=x status=configured api_key=configured",
            "llm=Demo/signal:1 provider=litellm model=x status=broken error=provider refused api_key=plain-secret",
            "signal_service=Demo/signal:1 target=127.0.0.1:8080 status=reachable password:hunter2",
            "matrix_homeserver=Demo/matrix:1 target=matrix.example:443 status=reachable access-token: plain-token",
            "api_budget=demo status=broken error=password:nested-secret",
        ]
    )

    assert check_plan2_acceptance._runtime_status_broken_lines(output) == output.splitlines()[1:]


def test_runtime_status_broken_lines_allow_safe_key_metadata() -> None:
    output = "\n".join(
        [
            "llm_route=bibliothekar_answer profile=gemini_flash_stateful provider=litellm_gemini_stateful model=gemini/gemini-3.5-flash status=configured api_key_env=GEMINI_API_KEY api_key_ring=3 fallback_api_key=missing",
            "api_budget=normal_chat profile=local provider=litellm model=ollama status=configured tokens=provider_usage_response+local_guard costs=local limits=local free_tier_guard=rpm=5,tpm=250000",
            "llm_route=cheap_fast profile=groq_fast provider=litellm model=groq/x status=missing_key api_key=plain-secret",
        ]
    )

    assert check_plan2_acceptance._runtime_status_broken_lines(output) == [output.splitlines()[2]]


def test_runtime_status_broken_lines_flags_unhealthy_qdrant_lines() -> None:
    output = "\n".join(
        [
            "qdrant=127.0.0.1:6333 status=unreachable fallback=keyword_memory_search",
            "qdrant=127.0.0.1:6333 status=ready fallback=keyword_memory_search",
            "qdrant_collection=teebotus_user_memory target=127.0.0.1:6333 status=unavailable vector_size=64",
            "qdrant_collection=teebotus_user_memory target=127.0.0.1:6333 status=ready vector_size=64",
        ]
    )

    assert check_plan2_acceptance._runtime_status_broken_lines(output) == [
        "qdrant=127.0.0.1:6333 status=unreachable fallback=keyword_memory_search",
        "qdrant_collection=teebotus_user_memory target=127.0.0.1:6333 status=unavailable vector_size=64",
    ]


def test_runtime_status_broken_lines_flags_url_credentials() -> None:
    output = "\n".join(
        [
            "signal_service=Demo/signal:1 target=https://user:plain-password@signal.example:8080 status=reachable",
            "llm=Demo/telegram:1 provider=litellm model=x status=configured base_url=http://127.0.0.1:11434 api_key=configured",
            "matrix_homeserver=Demo/matrix:1 target=bot:matrix-password@matrix.example:443 status=reachable",
        ]
    )

    assert check_plan2_acceptance._runtime_status_broken_lines(output) == [output.splitlines()[0], output.splitlines()[2]]


def test_runtime_status_broken_lines_flags_unsafe_qdrant_targets() -> None:
    output = "\n".join(
        [
            "bibliothekar=Demo backend=haystack store=qdrant collection=therapy_books target=http://qdrant.example:6333 status=reachable documents=1 chunks=1",
            "bibliothekar=Demo backend=haystack store=qdrant collection=therapy_books target=http://user:secret@127.0.0.1:6333 status=reachable documents=1 chunks=1",
            "bibliothekar=Demo backend=haystack store=qdrant collection=therapy_books target=http://127.0.0.1:6333?api_key=plain-secret status=reachable documents=1 chunks=1",
            "bibliothekar=Demo backend=haystack store=qdrant collection=therapy_books target=http://127.0.0.1:6333#token status=reachable documents=1 chunks=1",
            "bibliothekar=Demo backend=haystack store=qdrant collection=therapy_books target=http://127.0.0.1:6333/collections status=reachable documents=1 chunks=1",
            "bibliothekar=Demo backend=haystack store=qdrant collection=therapy_books target=http://127.0.0.1:99999 status=reachable documents=1 chunks=1",
            "bibliothekar=Demo backend=haystack store=qdrant collection=therapy_books target=http://127.0.0.1 status=reachable documents=1 chunks=1",
            "bibliothekar=Demo backend=haystack store=qdrant collection=therapy_books target=http://[::1 status=reachable documents=1 chunks=1",
            "bibliothekar=Demo backend=haystack store=qdrant collection=therapy_books status=reachable documents=1 chunks=1",
        ]
    )

    assert check_plan2_acceptance._runtime_status_broken_lines(output) == output.splitlines()


def test_runtime_status_broken_lines_flags_unhealthy_configured_resources() -> None:
    output = "\n".join(
        [
            "ollama=127.0.0.1:11434 status=unreachable error=connection refused",
            "llm=Demo/telegram:1 provider=openai model=gpt status=missing_key",
            "llm=Demo/signal:1 provider=litellm model=groq/llama-3.1-8b-instant status=missing_key api_key=none",
            "llm=Demo/matrix:1 provider=litellm model=ollama_chat/llama3.1:8b status=degraded fallback_api_key=missing",
            "signal_service=Demo/signal:1 target=127.0.0.1:8080 status=unreachable error=connection refused",
            "signal_account=Demo/signal:1 phone=+491234 target=127.0.0.1:8080 status=missing error=account missing",
            "matrix_homeserver=Demo/matrix:1 target=matrix.example:443 status=unreachable error=connection refused",
            "local_transcription=Demo backend=local model=tiny status=unavailable error=missing backend",
            "bibliothekar=Demo backend=haystack store=qdrant collection=therapy_books status=unavailable error=missing dependency",
            "account_memory_metadata=Demo status=broken item=account_index path=/repo/instances/Demo/data/accounts/Account_Index.json error=encrypted envelope authentication failed",
            "account_memory_recovery=Demo status=needed command=\"python3 -m TeeBotus.admin memory-recovery\"",
        ]
    )

    assert check_plan2_acceptance._runtime_status_broken_lines(output) == output.splitlines()
