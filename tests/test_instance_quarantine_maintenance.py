from __future__ import annotations

import json
import tarfile
from pathlib import Path

from scripts.maintain_instance_quarantine import (
    apply_retention,
    collect_quarantine_candidates,
    confirm_sql_backup,
    install_systemd_timer,
    main,
    quarantine_stale_instance_artifacts,
)


def test_quarantine_moves_only_stale_artifacts_and_preserves_active_store(tmp_path: Path) -> None:
    instances = tmp_path / "instances"
    accounts = instances / "Depressionsbot" / "data" / "accounts"
    accounts.mkdir(parents=True)
    active_files = [
        accounts / "accounts" / "account-id" / "Account_Profile.json",
        accounts / "Account_Memory.sqlite3",
        accounts / "Account_Memory.sqlite3-wal",
        accounts / "Account_Memory.sqlite3-shm",
        accounts / "Account_Memory.backup.sqlite3",
        accounts / "Account_Memory.backup.sqlite3-wal",
        accounts / "Account_Memory.backup.sqlite3-shm",
    ]
    for path in active_files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("active", encoding="utf-8")
    stale_dir = accounts / ".pre-legacy-user-memory-import-20260617T000000Z"
    stale_dir.mkdir()
    (stale_dir / "old.json").write_text("old", encoding="utf-8")
    nested_stale_dir = accounts / "accounts" / "account-id" / ".pre-legacy-user-memory-state-replace-20260617T000000Z"
    nested_stale_dir.mkdir()
    (nested_stale_dir / "old-profile.json").write_text("old-profile", encoding="utf-8")
    unreadable = accounts / "Account_Index.json.unreadable-20260615T000000Z"
    unreadable.write_text("bad", encoding="utf-8")
    metadata_quarantine = accounts / "Account_Metadata_Quarantine"
    metadata_quarantine.mkdir()
    (metadata_quarantine / "Account_Index.json").write_text("old-meta", encoding="utf-8")
    snapshot = instances / "Depressionsbot" / "data" / "accounts.pre-secret-repair-20260617T000000Z"
    snapshot.mkdir()
    (snapshot / "Account_Memory.sqlite3").write_text("snapshot-db", encoding="utf-8")
    pseudo = instances / "all"
    pseudo.mkdir()
    (pseudo / "data").mkdir()

    result = quarantine_stale_instance_artifacts(
        instances_dir=instances,
        quarantine_root=instances / ".quarantine",
        apply=True,
        timestamp_override="20260620T010203Z",
    )

    assert result["candidate_count"] == 6
    for path in active_files:
        assert path.exists(), path
    assert not stale_dir.exists()
    assert not nested_stale_dir.exists()
    assert not unreadable.exists()
    assert not metadata_quarantine.exists()
    assert not snapshot.exists()
    assert not pseudo.exists()
    bundle = Path(result["bundle_dir"])
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    reasons = {item["reason"] for item in manifest["items"]}
    assert reasons == {
        "account_quarantine_legacy",
        "pre_import_or_backup_sync_snapshot",
        "pre_secret_repair_account_store_snapshot",
        "pseudo_instance",
        "nested_pre_import_or_backup_sync_snapshot",
        "unreadable_metadata_snapshot",
    }
    assert (bundle / "Depressionsbot" / "data" / "accounts" / ".pre-legacy-user-memory-import-20260617T000000Z" / "old.json").exists()
    assert (
        bundle
        / "Depressionsbot"
        / "data"
        / "accounts"
        / "accounts"
        / "account-id"
        / ".pre-legacy-user-memory-state-replace-20260617T000000Z"
        / "old-profile.json"
    ).exists()
    assert (bundle / "Depressionsbot" / "data" / "accounts.pre-secret-repair-20260617T000000Z" / "Account_Memory.sqlite3").exists()


def test_collect_quarantine_candidates_ignores_real_instance_with_bot_config(tmp_path: Path) -> None:
    instances = tmp_path / "instances"
    real_demo = instances / "Demo"
    real_demo.mkdir(parents=True)
    (real_demo / "Bot_Verhalten.md").write_text("# Demo\n", encoding="utf-8")

    candidates = collect_quarantine_candidates(instances, instances / ".quarantine")

    assert candidates == []


def test_retention_archives_eligible_bundle_and_removes_raw_after_archive(tmp_path: Path) -> None:
    instances = tmp_path / "instances"
    bundle = instances / ".quarantine" / "cleanup-20260601T000000Z"
    bundle.mkdir(parents=True)
    (bundle / "manifest.json").write_text('{"schema_version": 1}', encoding="utf-8")

    result = apply_retention(
        instances_dir=instances,
        quarantine_root=instances / ".quarantine",
        apply=True,
        min_age_days=999,
        delete_raw_after_archive=True,
        sql_confirmation_path=instances / ".quarantine" / "sql-backup-confirmed.json",
    )

    assert result["archived_count"] == 0
    assert result["raw_removed_count"] == 0
    assert bundle.exists()

    confirm_sql_backup(
        instances_dir=instances,
        quarantine_root=instances / ".quarantine",
        confirmation_path=instances / ".quarantine" / "sql-backup-confirmed.json",
        backup_label="postgresql daily backup",
        apply=True,
    )
    result = apply_retention(
        instances_dir=instances,
        quarantine_root=instances / ".quarantine",
        apply=True,
        min_age_days=999,
        delete_raw_after_archive=True,
        sql_confirmation_path=instances / ".quarantine" / "sql-backup-confirmed.json",
    )

    archive_path = instances / ".quarantine" / "archives" / "cleanup-20260601T000000Z.tar.gz"
    assert result["archived_count"] == 1
    assert result["raw_removed_count"] == 1
    assert archive_path.exists()
    assert not bundle.exists()
    with tarfile.open(archive_path, "r:gz") as archive:
        assert "cleanup-20260601T000000Z/manifest.json" in archive.getnames()


def test_install_systemd_timer_prints_retention_command(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    script = repo / "scripts" / "maintain_instance_quarantine.py"
    script.parent.mkdir(parents=True)
    script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    python = repo / ".venv-py313" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")

    result = install_systemd_timer(
        repo_root=repo,
        instances_dir=repo / "instances",
        quarantine_root=repo / "instances" / ".quarantine",
        python_executable="",
        service_name="teebotus-test-retention.service",
        timer_name="teebotus-test-retention.timer",
        interval="daily",
        randomized_delay="5min",
        min_age_days=7,
        delete_raw_after_archive=True,
        enable=False,
        print_only=True,
    )

    output = capsys.readouterr().out
    assert result is None
    assert "teebotus-test-retention.service" in output
    assert "maintain_instance_quarantine.py retention" in output
    assert "--delete-raw-after-archive" in output
    assert "OnCalendar=daily" in output


def test_retention_cli_dry_run_uses_retention_delete_flag(tmp_path: Path, capsys) -> None:
    instances = tmp_path / "instances"
    bundle = instances / ".quarantine" / "cleanup-20260601T000000Z"
    bundle.mkdir(parents=True)
    (bundle / "manifest.json").write_text('{"schema_version": 1}', encoding="utf-8")

    assert main(["retention", "--instances-dir", str(instances), "--delete-raw-after-archive"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["operation"] == "retention"
    assert output["delete_raw_after_archive"] is True
