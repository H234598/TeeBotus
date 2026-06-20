from __future__ import annotations

import json
from pathlib import Path

import scripts.import_memory_artifacts_daily as import_job


def test_daily_memory_artifact_job_discovers_legacy_users_dirs_inside_repo(tmp_path: Path) -> None:
    repo = tmp_path / "TeeBotus"
    user_dir = repo / "backups" / "instances.bak" / "Depressionsbot" / "data" / "users" / "123"
    user_dir.mkdir(parents=True)
    (user_dir / "User_Memory_Entries.jsonl").write_text(json.dumps({"id": "mem1"}) + "\n", encoding="utf-8")
    ignored = tmp_path / "outside" / "instances.bak" / "Depressionsbot" / "data" / "users" / "456"
    ignored.mkdir(parents=True)
    (ignored / "User_Memory_Entries.jsonl").write_text(json.dumps({"id": "mem2"}) + "\n", encoding="utf-8")

    roots = import_job.discover_legacy_instance_roots(search_roots=[repo, ignored.parents[4]], repo_root=repo)

    assert roots == [repo / "backups" / "instances.bak"]


def test_daily_memory_artifact_job_systemd_print_renders_daily_timer(capsys) -> None:
    result = import_job.main(
        [
            "install-systemd",
            "--print",
            "--repo-root",
            "/tmp/TeeBotus",
            "--instances-dir",
            "instances",
        ]
    )

    output = capsys.readouterr().out
    assert result == 0
    assert "teebotus-memory-artifact-import.service" in output
    assert "OnCalendar=daily" in output
    assert "Persistent=true" in output
    assert "import_memory_artifacts_daily.py run" in output
