from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import types
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from TeeBotus import __version__
import TeeBotus.admin.codex_history as codex_history_module
from TeeBotus.admin.codex_history import (
    _codex_history_graph_mermaid_source,
    CODEX_HISTORY_FOLLOW_REPORT_ITEMS_LIMIT,
    _normalize_remote_url,
    _repo_provider,
    _update_watch_instance_report,
    acknowledge_codex_history_item,
    append_codex_history_summary,
    build_codex_history_markdown,
    build_local_codex_history_categorizer,
    build_codex_history_strategist,
    build_codex_history_report,
    categorize_codex_history_outbox,
    codex_history_bibliothekar_chunks,
    dispatch_codex_history_outbox,
    export_codex_history_bibliothekar_docs,
    export_codex_history_graph_doc,
    generate_codex_history_strategic_analysis,
    _safe_output_path,
    _safe_repo_root,
    _render_dispatch_report,
    import_codex_session_file,
    import_codex_session_roots,
    main as codex_history_main,
    record_codex_history_delivery_receipt,
    record_codex_history_reply,
    repair_codex_history_repo_versions,
    resolve_repo_version,
    rewrite_codex_history_display_times,
    rewrite_codex_history_markdown_display_times,
    run_codex_history_index,
    _render_watch_report,
    _watch_payload_ok,
    watch_codex_session_roots,
    watch_codex_session_roots_for_instances,
)
from TeeBotus.runtime.actions import SendAttachment
from TeeBotus.runtime.accounts import (
    ACCOUNT_MEMORY_KEY_PURPOSE,
    CODEX_HISTORY_OUTBOX_FILENAME,
    INSTANCE_STATE_ACCOUNT_ID,
    AccountStore,
    StaticSecretProvider,
    telegram_identity_key,
)
from TeeBotus.runtime.sqlite_memory import SQLiteAccountMemoryBackend, SQLiteMemoryConfig


def provider() -> StaticSecretProvider:
    return StaticSecretProvider(b"a" * 32)


def make_instance(tmp_path: Path, name: str = "Depressionsbot") -> Path:
    instance_dir = tmp_path / name
    instance_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text("## Hilfe\n", encoding="utf-8")
    return instance_dir


def authorize_codex_admin(store: AccountStore, account_id: str) -> None:
    store.write_status_auth_state(account_id, {"schema_version": 1, "authorized": True, "admin_opt_out": False})


def test_codex_history_default_store_uses_runtime_secret_retry_policy(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TEEBOTUS_SECRET_TOOL_LOOKUP_RETRIES", "2")
    monkeypatch.setenv("TEEBOTUS_SECRET_TOOL_LOOKUP_RETRY_DELAY_SECONDS", "0.25")
    monkeypatch.setenv("TEEBOTUS_SECRET_TOOL_TIMEOUT_SECONDS", "4")
    accounts_root = tmp_path / "Demo" / "data" / "accounts"
    accounts_root.mkdir(parents=True)

    store = codex_history_module._store_for_instance(tmp_path, "Demo", None)
    provider = store.secret_provider.delegate

    assert provider.create_if_missing is False
    assert provider.lookup_retries == 2
    assert provider.lookup_retry_delay_seconds == 0.25
    assert provider.timeout_seconds == 4.0


@pytest.fixture(autouse=True)
def redirect_codex_history_obsidian(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_obsidian_incoming_path(*parts: str) -> Path:
        path = tmp_path / "obsidian_incoming"
        for part in parts:
            path = path / str(part)
        return path

    monkeypatch.setattr("TeeBotus.admin.codex_history.obsidian_incoming_path", fake_obsidian_incoming_path)


def make_git_repo(tmp_path: Path, name: str, version: str = "1.2.3") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                f'name = "{name}"',
                f'version = "{version}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    subprocess.run(["git", "add", "pyproject.toml"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo, check=True)
    subprocess.run(["git", "remote", "add", "origin", f"git@example.invalid:{name}.git"], cwd=repo, check=True)
    return repo


def test_resolve_repo_version_prefers_teebotus_runtime_version_over_stale_git_tag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("TeeBotus.admin.codex_history._pyproject_version", lambda _root: "")
    monkeypatch.setattr("TeeBotus.admin.codex_history._version_file", lambda _root: "")
    monkeypatch.setattr("TeeBotus.admin.codex_history._teebotus_version", lambda _root: "1.8.2")
    monkeypatch.setattr("TeeBotus.admin.codex_history._git_latest_semver_tag", lambda _root: "v1.7.1")

    version = resolve_repo_version(tmp_path)

    assert version == {"semver": "1.8.2", "tag": "v1.8.2"}


def test_repair_codex_history_repo_versions_rewrites_stale_prefixes(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "TeeBotus", version="1.8.2")
    store = AccountStore(tmp_path / "accounts", "TeeBotus_Logger", provider())
    item = append_codex_history_summary(store, repo_root=repo, title="Version repair", bullets=["Falscher Tag war sichtbar."])
    stale_prefix = "v1.7.1 #0001"
    rows = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
    rows[0]["summary_prefix"] = stale_prefix
    rows[0]["version"]["semver"] = "1.7.1"
    rows[0]["version"]["tag"] = "v1.7.1"
    rows[0]["version"]["summary_prefix"] = stale_prefix
    rows[0]["summary"]["markdown"] = rows[0]["summary"]["markdown"].replace("v1.8.2 #0001", stale_prefix).replace("`v1.8.2`", "`v1.7.1`")
    store.write_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID, rows)
    store.append_codex_history_dispatch_result(
        INSTANCE_STATE_ACCOUNT_ID,
        {"codex_history_item_id": item["id"], "status": "accepted", "summary_prefix": stale_prefix},
    )
    projects = store.read_codex_history_projects(INSTANCE_STATE_ACCOUNT_ID)
    projects[0]["last_summary_prefix"] = stale_prefix
    store.write_codex_history_projects(INSTANCE_STATE_ACCOUNT_ID, projects)

    report = repair_codex_history_repo_versions(
        store,
        instance_name="TeeBotus_Logger",
        repo="TeeBotus",
        semver="1.8.2",
        dry_run=False,
    )

    assert report["changed_items"] == 1
    assert report["dispatch_results_changed"] == 1
    assert report["projects_changed"] == 1
    repaired = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert repaired["summary_prefix"] == "v1.8.2 #0001"
    assert repaired["version"]["semver"] == "1.8.2"
    assert repaired["version"]["tag"] == "v1.8.2"
    assert "# v1.8.2 #0001 Version repair" in repaired["summary"]["markdown"]
    assert "- Version: `v1.8.2`" in repaired["summary"]["markdown"]
    assert store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID)[0]["summary_prefix"] == "v1.8.2 #0001"
    assert store.read_codex_history_projects(INSTANCE_STATE_ACCOUNT_ID)[0]["last_summary_prefix"] == "v1.8.2 #0001"
    second_report = repair_codex_history_repo_versions(
        store,
        instance_name="TeeBotus_Logger",
        repo="TeeBotus",
        semver="1.8.2",
        dry_run=True,
    )
    assert second_report["changed_items"] == 0
    assert second_report["dispatch_results_changed"] == 0
    assert second_report["projects_changed"] == 0


def write_codex_session(path: Path, *, repo: Path, session_id: str = "sess-1", turn_id: str = "turn-1", final_text: str = "") -> Path:
    final_text = final_text or "\n".join(
        [
            "Watcher import gebaut.",
            "- Codex-History liest Sessionlogs.",
            "- Verifiziert mit pytest tests/test_codex_history.py.",
        ]
    )
    rows = [
        {"type": "session_meta", "timestamp": "2026-06-19T10:00:00+00:00", "payload": {"id": session_id, "cwd": str(repo)}},
        {"type": "turn_context", "timestamp": "2026-06-19T10:01:00+00:00", "payload": {"turn_id": turn_id, "started_at": "2026-06-19T10:01:00+00:00"}},
        {
            "type": "response_item",
            "timestamp": "2026-06-19T10:03:00+00:00",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": final_text}],
            },
        },
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return path


def test_account_store_persists_codex_history_collections(tmp_path: Path) -> None:
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())

    item_id = store.append_codex_history_item(
        INSTANCE_STATE_ACCOUNT_ID,
        {
            "kind": "codex_run_summary",
            "project": {"repo_id": "repo-1", "repo_name": "TeeBotus"},
            "summary_number": 1,
        },
    )
    dispatch_id = store.append_codex_history_dispatch_result(
        INSTANCE_STATE_ACCOUNT_ID,
        {"codex_history_item_id": item_id, "status": "accepted"},
    )
    store.write_codex_history_projects(
        INSTANCE_STATE_ACCOUNT_ID,
        [{"repo_id": "repo-1", "repo_name": "TeeBotus", "summary_count": 1}],
    )

    assert item_id.startswith("hist_")
    assert dispatch_id.startswith("chdisp_")
    assert store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]["status"] == "queued"
    assert store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID)[0]["status"] == "accepted"
    assert store.read_codex_history_projects(INSTANCE_STATE_ACCOUNT_ID)[0]["repo_name"] == "TeeBotus"


def test_codex_history_uses_sql_collection_when_account_backend_is_enabled(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "sql-demo", version="1.0.0")
    sqlite_path = tmp_path / "memory.sqlite3"
    backend = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=sqlite_path, fallback_path=None),
    )
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    store._account_memory_backend = backend

    item = append_codex_history_summary(
        store,
        repo_root=repo,
        title="SQL History",
        bullets=["Primaer in SQL."],
        session_id="sess-sql",
    )

    jsonl_path = store.account_dir(INSTANCE_STATE_ACCOUNT_ID) / CODEX_HISTORY_OUTBOX_FILENAME
    assert not jsonl_path.exists()
    assert backend.read_collection(INSTANCE_STATE_ACCOUNT_ID, "codex_history_outbox")[0]["id"] == item["id"]
    assert store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]["summary_prefix"] == "v1.0.0 #0001"


def test_codex_history_sql_dispatch_ids_do_not_duplicate_existing_rows(tmp_path: Path) -> None:
    backend = SQLiteAccountMemoryBackend(
        instance_name="Depressionsbot",
        provider=provider(),
        purpose=ACCOUNT_MEMORY_KEY_PURPOSE,
        config=SQLiteMemoryConfig(path=tmp_path / "memory.sqlite3", fallback_path=None),
    )
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    store._account_memory_backend = backend

    first_id = store.append_codex_history_dispatch_result(
        INSTANCE_STATE_ACCOUNT_ID,
        {"id": "fixed-dispatch-id", "status": "accepted"},
    )
    second_id = store.append_codex_history_dispatch_result(
        INSTANCE_STATE_ACCOUNT_ID,
        {"id": "fixed-dispatch-id", "status": "delivered"},
    )

    rows = store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID)
    assert first_id == "fixed-dispatch-id"
    assert second_id != first_id
    assert [row["id"] for row in rows] == [first_id, second_id]


def test_codex_history_dispatch_updates_sql_collections(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", str(tmp_path / "memory.sqlite3"))
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_FALLBACK_PATH", str(tmp_path / "memory.backup.sqlite3"))
    repo = make_git_repo(tmp_path, "sql-dispatch-demo", version="1.0.1")
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    admin_id = store.resolve_or_create_account(telegram_identity_key(420), display_label="Admin")
    store.update_identity_route(telegram_identity_key(420), channel="telegram", chat_id="420", chat_type="private", adapter_slot=1)
    authorize_codex_admin(store, admin_id)
    item = append_codex_history_summary(store, repo_root=repo, title="SQL Dispatch", bullets=["Gezielter SQL-Pfad."])
    sent: list[SendAttachment] = []

    def sender(_route: dict[str, object], action: SendAttachment, _metadata: dict[str, object]) -> str:
        sent.append(action)
        return "telegram-sql-1"

    result = asyncio.run(
        dispatch_codex_history_outbox(
            store,
            instance_name="TeeBotus_Logger",
            account_ids=(admin_id,),
            senders={"telegram": sender},
            now=datetime(2026, 6, 19, 12, tzinfo=timezone.utc),
        )
    )

    assert result["status_counts"] == {"accepted": 1}
    assert sent[0].chat_id == "420"
    assert not (store.account_dir(INSTANCE_STATE_ACCOUNT_ID) / CODEX_HISTORY_OUTBOX_FILENAME).exists()
    persisted = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert persisted["id"] == item["id"]
    assert persisted["status"] == "accepted"
    dispatch = store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert dispatch["status"] == "accepted"
    assert dispatch["message_ref"] == "telegram-sql-1"


def test_append_codex_history_summary_numbers_per_repo_and_redacts_secrets(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    repo_a = make_git_repo(tmp_path, "alpha", version="1.2.3")
    repo_b = make_git_repo(tmp_path, "beta", version="2.0.0")
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    fake_key = "sk-" + "svcacct-" + ("a" * 48)

    first = append_codex_history_summary(
        store,
        repo_root=repo_a,
        title="History outbox eingefuehrt",
        bullets=[f"Speichert keine Secrets wie {fake_key}."],
        changed_files=["TeeBotus/runtime/accounts.py"],
        tests=["pytest tests/test_codex_history.py"],
        session_id="sess-1",
    )
    second = append_codex_history_summary(
        store,
        repo_root=repo_a,
        title="Report ergaenzt",
        bullets=["Report zaehlt queued Items."],
        session_id="sess-2",
    )
    other_repo = append_codex_history_summary(
        store,
        repo_root=repo_b,
        title="Eigenes Repo",
        bullets=["Nummerierung beginnt je Repo neu."],
        session_id="sess-3",
    )

    assert first["summary_prefix"] == "v1.2.3 #0001"
    assert second["summary_prefix"] == "v1.2.3 #0002"
    assert other_repo["summary_prefix"] == "v2.0.0 #0001"
    assert fake_key not in first["summary"]["markdown"]
    assert "<redacted:openai-key>" in first["summary"]["markdown"]
    assert first["status"] == "queued"
    assert first["delivery"]["target_group"] == "status_admins"
    assert first["indexing"]["indexable"] is True


def test_codex_history_markdown_displays_berlin_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEEBOTUS_CODEX_HISTORY_TIMEZONE", "Europe/Berlin")

    markdown = build_codex_history_markdown(
        summary_prefix="v1.2.3 #0001",
        title="Zeitcheck",
        repo={"repo_name": "TeeBotus", "repo_root": "/tmp/TeeBotus", "head_commit": "abc", "branch": "main"},
        version={"tag": "v1.2.3"},
        bullets=["Zeit stimmt lokal."],
        changed_files=[],
        tests=[],
        created_at="2026-06-19T12:00:00+00:00",
    )

    assert "- Erstellt: `2026-06-19T14:00:00+02:00`" in markdown
    assert "2026-06-19T12:00:00+00:00" not in markdown


def test_codex_history_markdown_separates_comments_and_embeds_code_blocks() -> None:
    markdown = build_codex_history_markdown(
        summary_prefix="v1.2.3 #0001",
        title="Formatcheck",
        repo={"repo_name": "TeeBotus", "repo_root": "/tmp/TeeBotus", "head_commit": "abc", "branch": "main"},
        version={"tag": "v1.2.3"},
        bullets=["Summary ist lesbarer."],
        changed_files=["TeeBotus/admin/codex_history.py", "tests/test_codex_history.py"],
        tests=["pytest tests/test_codex_history.py"],
        created_at="2026-06-19T12:00:00+00:00",
        goal="Repo-Logikfehler finden",
        auftrag="Summary-Format verbessern.",
        intermediate_messages=[
            {
                "phase": "commentary",
                "turn_id": "turn-1",
                "text": "Ich trenne Kommentare und pruefe ```Fences```.",
            }
        ],
    )

    assert "> Codex-Run-Summary fuer Admins." in markdown
    assert "## Metadaten" in markdown
    assert "```text\nprojekt=TeeBotus" in markdown
    assert "## Arbeitsverlauf" in markdown
    assert "### Kommentar 1" in markdown
    assert "- Phase: `commentary`" in markdown
    assert "- Turn: `turn-1`" in markdown
    assert "````text\nIch trenne Kommentare und pruefe ```Fences```.\n````" in markdown
    assert "- Dateien: `2`" in markdown
    assert "```text\nTeeBotus/admin/codex_history.py\ntests/test_codex_history.py\n```" in markdown
    assert "- Checks: `1`" in markdown
    assert "```bash\npytest tests/test_codex_history.py\n```" in markdown


def test_codex_history_markdown_time_rewrite_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEEBOTUS_CODEX_HISTORY_TIMEZONE", "Europe/Berlin")
    old_markdown = "\n".join(
        [
            "# v1.2.3 #0001 Alt",
            "",
            "- Erstellt: `2026-06-19T12:00:00+00:00`",
            "- Aktualisiert: `2026-06-19T12:30:00Z`",
            "- KeinZeitfeld: `2026-06-19T12:30:00+00:00`",
        ]
    )

    rewritten, changed = rewrite_codex_history_markdown_display_times(old_markdown)
    rewritten_again, changed_again = rewrite_codex_history_markdown_display_times(rewritten)

    assert changed == 2
    assert changed_again == 0
    assert rewritten_again == rewritten
    assert "- Erstellt: `2026-06-19T14:00:00+02:00`" in rewritten
    assert "- Aktualisiert: `2026-06-19T14:30:00+02:00`" in rewritten
    assert "- KeinZeitfeld: `2026-06-19T12:30:00+00:00`" in rewritten


def test_codex_history_rewrite_times_apply_updates_sql_and_dispatch_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEEBOTUS_CODEX_HISTORY_TIMEZONE", "Europe/Berlin")
    repo = make_git_repo(tmp_path, "rewrite-demo", version="1.9.1")
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    item = append_codex_history_summary(
        store,
        repo_root=repo,
        title="Alte Zeiten",
        bullets=["Bestehende Summary wird migriert."],
    )
    rows = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
    rows[0]["created_at"] = "2026-06-19T12:00:00+00:00"
    rows[0]["summary"]["markdown"] = "\n".join(
        "- Erstellt: `2026-06-19T12:00:00+00:00`" if line.startswith("- Erstellt: ") else line
        for line in rows[0]["summary"]["markdown"].splitlines()
    )
    store.write_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID, rows)
    dispatch_dir = tmp_path / "Codex_History_Dispatches"
    dispatch_dir.mkdir()
    old_dispatch_path = dispatch_dir / f"20260619T120000_{item['id']}_rewrite-demo_release_1.9.1_0001.md"
    old_dispatch_path.write_text("# Dispatch\n\n- Erstellt: `2026-06-19T12:00:00+00:00`\n", encoding="utf-8")
    store.append_codex_history_dispatch_result(
        INSTANCE_STATE_ACCOUNT_ID,
        {
            "codex_history_item_id": item["id"],
            "instance": "Depressionsbot",
            "status": "accepted",
            "channel": "telegram",
            "chat_id": "42",
            "message_ref": "msg-1",
            "obsidian_path": str(old_dispatch_path),
        },
    )

    dry_run = rewrite_codex_history_display_times(
        store,
        instance_name="Depressionsbot",
        dry_run=True,
        include_dispatch_files=True,
    )
    assert dry_run["changed_items"] == 1
    assert dry_run["dispatch_files"]["changed"] == 1
    assert dry_run["dispatch_files"]["renamed"] == 1
    assert old_dispatch_path.exists()
    assert "2026-06-19T12:00:00+00:00" in store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]["summary"]["markdown"]

    applied = rewrite_codex_history_display_times(
        store,
        instance_name="Depressionsbot",
        dry_run=False,
        include_dispatch_files=True,
    )

    assert applied["changed_items"] == 1
    persisted = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert "- Erstellt: `2026-06-19T14:00:00+02:00`" in persisted["summary"]["markdown"]
    new_dispatch_path = dispatch_dir / f"20260619T140000_{item['id']}_rewrite-demo_release_1.9.1_0001.md"
    assert not old_dispatch_path.exists()
    assert new_dispatch_path.exists()
    assert "- Erstellt: `2026-06-19T14:00:00+02:00`" in new_dispatch_path.read_text(encoding="utf-8")
    dispatch = store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert dispatch["obsidian_path"] == str(new_dispatch_path)


def test_codex_history_rewrite_times_cli_dry_run_json(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEEBOTUS_CODEX_HISTORY_TIMEZONE", "Europe/Berlin")
    instance_dir = make_instance(tmp_path)
    repo = make_git_repo(tmp_path, "rewrite-cli-demo", version="1.9.2")
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    append_codex_history_summary(store, repo_root=repo, title="CLI Zeiten", bullets=["Dry-run zaehlt."])
    rows = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
    rows[0]["summary"]["markdown"] = "\n".join(
        "- Erstellt: `2026-06-19T12:00:00+00:00`" if line.startswith("- Erstellt: ") else line
        for line in rows[0]["summary"]["markdown"].splitlines()
    )
    store.write_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID, rows)

    result = codex_history_main(
        [
            "rewrite-times",
            "--instances-dir",
            str(tmp_path),
            "--instance",
            "Depressionsbot",
            "--format",
            "json",
        ],
        provider=provider(),
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["totals"]["changed_items"] == 1
    assert "2026-06-19T12:" in store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]["summary"]["markdown"]


def test_codex_history_cli_append_and_report_json(tmp_path: Path, capsys) -> None:
    make_instance(tmp_path)
    repo = make_git_repo(tmp_path, "teebotus-demo", version="1.8.0")

    append_result = codex_history_main(
        [
            "append",
            "--instances-dir",
            str(tmp_path),
            "--instance",
            "Depressionsbot",
            "--repo-root",
            str(repo),
            "--title",
            "CLI Append",
            "--bullet",
            "History-Zeile queued.",
            "--changed-file",
            "TeeBotus/admin/codex_history.py",
            "--test",
            "pytest tests/test_codex_history.py",
            "--session-id",
            "sess-cli",
            "--format",
            "json",
        ],
        provider=provider(),
    )

    assert append_result == 0
    appended = json.loads(capsys.readouterr().out)
    assert appended["item"]["summary_prefix"] == "v1.8.0 #0001"
    assert appended["item"]["project"]["repo_name"] == "teebotus-demo"

    report = build_codex_history_report(instances_dir=tmp_path, instances=("Depressionsbot",), provider=provider())

    assert report["scope"] == "codex_history"
    assert report["totals"]["outbox_items"] == 1
    assert report["totals"]["projects"] == 1
    assert report["instances"][0]["codex_history"]["outbox_status_counts"] == {"queued": 1}

    report_result = codex_history_main(
        ["report", "--instances-dir", str(tmp_path), "--instances", "Depressionsbot", "--format", "json"],
        provider=provider(),
    )

    assert report_result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["totals"]["outbox_items"] == 1
    assert payload["instances"][0]["codex_history"]["projects"][0]["repo_name"] == "teebotus-demo"


def test_codex_history_cli_report_loads_project_dotenv_for_sqlite_backend(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    instances_dir = tmp_path / "instances"
    instance_dir = make_instance(instances_dir)
    sqlite_path = tmp_path / "Account_Memory.sqlite3"
    fallback_path = tmp_path / "Account_Memory.backup.sqlite3"
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "TEEBOTUS_ACCOUNT_MEMORY_BACKEND=sqlite",
                f'TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH="{sqlite_path}"',
                f'TEEBOTUS_ACCOUNT_MEMORY_SQLITE_FALLBACK_PATH="{fallback_path}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    repo = make_git_repo(tmp_path, "dotenv-sqlite-history", version="1.8.1")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", str(sqlite_path))
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_FALLBACK_PATH", str(fallback_path))
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    append_codex_history_summary(store, repo_root=repo, title="Aus dotenv SQLite", bullets=["Report muss .env laden."])
    monkeypatch.delenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", raising=False)
    monkeypatch.delenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", raising=False)
    monkeypatch.delenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_FALLBACK_PATH", raising=False)

    result = codex_history_main(
        ["report", "--instances-dir", str(instances_dir), "--instances", "Depressionsbot", "--format", "json"],
        provider=provider(),
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["totals"]["outbox_items"] == 1
    assert payload["instances"][0]["codex_history"]["latest_by_repo"][0]["title"] == "Aus dotenv SQLite"


def test_codex_history_report_builds_repo_history_and_filters_dispatch_results(tmp_path: Path, capsys) -> None:
    instance_dir = make_instance(tmp_path)
    repo_alpha = make_git_repo(tmp_path, "alpha-history", version="1.8.0")
    repo_beta = make_git_repo(tmp_path, "beta-history", version="2.0.0")
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    alpha_first = append_codex_history_summary(store, repo_root=repo_alpha, title="Alpha eins", bullets=["Erster Alpha-Lauf."])
    alpha_second = append_codex_history_summary(store, repo_root=repo_alpha, title="Alpha zwei", bullets=["Zweiter Alpha-Lauf."])
    beta_first = append_codex_history_summary(store, repo_root=repo_beta, title="Beta eins", bullets=["Fremdes Repo."])
    rows = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
    for row in rows:
        if row["id"] == alpha_first["id"]:
            row["status"] = "accepted"
        elif row["id"] == alpha_second["id"]:
            row["status"] = "failed"
        elif row["id"] == beta_first["id"]:
            row["status"] = "accepted"
    store.write_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID, rows)
    store.append_codex_history_dispatch_result(
        INSTANCE_STATE_ACCOUNT_ID,
        {"codex_history_item_id": alpha_first["id"], "repo_id": alpha_first["project"]["repo_id"], "status": "accepted"},
    )
    store.append_codex_history_dispatch_result(
        INSTANCE_STATE_ACCOUNT_ID,
        {"codex_history_item_id": alpha_second["id"], "repo_id": alpha_second["project"]["repo_id"], "status": "failed"},
    )
    store.append_codex_history_dispatch_result(
        INSTANCE_STATE_ACCOUNT_ID,
        {"codex_history_item_id": beta_first["id"], "repo_id": beta_first["project"]["repo_id"], "status": "accepted"},
    )

    report = build_codex_history_report(
        instances_dir=tmp_path,
        instances=("Depressionsbot",),
        repo="alpha-history",
        provider=provider(),
        summary_limit=1,
    )
    history = report["instances"][0]["codex_history"]

    assert history["outbox_items"] == 2
    assert history["dispatch_results"] == 2
    assert history["outbox_status_counts"] == {"accepted": 1, "failed": 1}
    assert history["dispatch_status_counts"] == {"accepted": 1, "failed": 1}
    assert len(history["repo_history"]) == 1
    repo_history = history["repo_history"][0]
    assert repo_history["repo_name"] == "alpha-history"
    assert repo_history["summary_count"] == 2
    assert repo_history["outbox_status_counts"] == {"accepted": 1, "failed": 1}
    assert repo_history["dispatch_status_counts"] == {"accepted": 1, "failed": 1}
    assert [item["summary_prefix"] for item in repo_history["latest_summaries"]] == ["v1.8.0 #0002"]
    assert repo_history["latest_summaries"][0]["title"] == "Alpha zwei"

    assert (
        codex_history_main(
            [
                "report",
                "--instances-dir",
                str(tmp_path),
                "--instances",
                "Depressionsbot",
                "--repo",
                "alpha-history",
                "--summary-limit",
                "1",
            ],
            provider=provider(),
        )
        == 0
    )
    rendered = capsys.readouterr().out
    assert "Repo-History:" in rendered
    assert "alpha-history summaries=2 statuses=accepted=1, failed=1 dispatch=accepted=1, failed=1" in rendered
    assert "v1.8.0 #0002 failed Alpha zwei" in rendered
    assert "beta-history" not in rendered


def test_codex_history_latest_by_repo_uses_summary_order_over_row_order(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    repo = make_git_repo(tmp_path, "latest-order-demo", version="1.8.1")
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    first = append_codex_history_summary(store, repo_root=repo, title="Aeltere Summary", bullets=["Erster Lauf."])
    second = append_codex_history_summary(store, repo_root=repo, title="Neuere Summary", bullets=["Zweiter Lauf."])
    rows = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
    for row in rows:
        row["created_at"] = "2026-06-19T12:00:00+00:00"
    store.write_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID, list(reversed(rows)))

    report = build_codex_history_report(instances_dir=tmp_path, instances=("Depressionsbot",), provider=provider())
    latest = report["instances"][0]["codex_history"]["latest_by_repo"][0]

    assert latest["summary_prefix"] == second["summary_prefix"]
    assert latest["title"] == "Neuere Summary"
    assert latest["summary_prefix"] != first["summary_prefix"]


def test_codex_history_bibliothekar_export_writes_admin_only_docs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEEBOTUS_CODEX_HISTORY_TIMEZONE", "Europe/Berlin")
    instance_dir = make_instance(tmp_path)
    repo = make_git_repo(tmp_path, "bibliothekar-export-demo", version="1.8.6")
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    fake_key = "sk-" + "svcacct-" + ("c" * 48)
    item = append_codex_history_summary(
        store,
        repo_root=repo,
        title="Bibliothekar Export",
        bullets=[
            "Qdrant und Bibliothekar bekommen admin-only Projekthistory.",
            f"Secret {fake_key} darf nicht im Export stehen.",
        ],
        changed_files=["TeeBotus/admin/codex_history.py", "docs/Codex_Outbox_History_Plan.md"],
        tests=["pytest tests/test_codex_history.py"],
    )
    rows = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
    rows[0]["created_at"] = "2026-06-19T12:00:00+00:00"
    rows[0]["updated_at"] = "2026-06-19T12:30:00+00:00"
    rows[0]["delivery"]["sent_at"] = "2026-06-19T13:00:00+00:00"
    rows[0]["delivery"]["accepted_at"] = "2026-06-19T13:05:00+00:00"
    rows[0]["delivery"]["delivered_at"] = "2026-06-19T13:10:00+00:00"
    rows[0]["delivery"]["acknowledged_at"] = "2026-06-19T13:15:00+00:00"
    store.write_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID, rows)

    result = export_codex_history_bibliothekar_docs(
        store,
        instance_dir=instance_dir,
        instance_name="Depressionsbot",
    )

    destination = (instance_dir / "data" / "Codex_History_Bibliothek").resolve()
    assert result["ok"] is True
    assert result["destination"] == str(destination)
    assert result["exported"] == 1
    assert result["files"][0]["item_id"] == item["id"]
    assert "codex-history" in result["files"][0]["categories"]
    assert "change-bibliothekar" in result["files"][0]["categories"]
    assert "change-memory" in result["files"][0]["categories"]
    assert not (instance_dir / "data" / "Bibliothek").exists()
    assert (destination / "README.md").exists()

    exported_text = Path(result["files"][0]["path"]).read_text(encoding="utf-8")
    assert "admin-only" in exported_text
    assert "codex_history_outbox" in exported_text
    assert "Qdrant und Bibliothekar" in exported_text
    assert fake_key not in exported_text
    assert "<redacted:openai-key>" in exported_text
    assert "- Erstellt: `2026-06-19T14:00:00+02:00`" in exported_text
    assert "- Aktualisiert: `2026-06-19T14:30:00+02:00`" in exported_text
    assert "- Sent: `2026-06-19T15:00:00+02:00`" in exported_text
    assert "- Accepted: `2026-06-19T15:05:00+02:00`" in exported_text
    assert "- Delivered: `2026-06-19T15:10:00+02:00`" in exported_text
    assert "- Acknowledged: `2026-06-19T15:15:00+02:00`" in exported_text
    assert "2026-06-19T13:15:00+00:00" not in exported_text


def test_codex_history_bibliothekar_chunks_are_admin_only_and_citeable(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    repo = make_git_repo(tmp_path, "codex-chunk-demo", version="1.8.8")
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    item = append_codex_history_summary(
        store,
        repo_root=repo,
        title="Qdrant Chunk",
        bullets=["Codex-History wird als separater Qdrant-Chunk indexierbar."],
        changed_files=["TeeBotus/embedding/rebuild.py"],
    )

    chunks = codex_history_bibliothekar_chunks(
        store,
        instance_dir=instance_dir,
        instance_name="Depressionsbot",
    )

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk["chunk_id"].startswith("codex_history:")
    assert chunk["document_id"].startswith("codex_history:")
    assert chunk["source_id"] == f"codex_history:{item['id']}"
    assert chunk["relative_path"].startswith("codex_history/codex-chunk-demo/")
    assert "Codex_History_Bibliothek" in chunk["file_path"]
    assert chunk["source_harvest_route"] == "codex_history_outbox"
    assert "admin-only" in chunk["categories"]
    assert "project-history" in chunk["categories"]
    assert "codex-history" in chunk["text"]
    assert chunk["file_sha256"]


def test_codex_history_categorize_persists_local_llm_categories(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    repo = make_git_repo(tmp_path, "categorize-demo", version="1.9.1")
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    item = append_codex_history_summary(
        store,
        repo_root=repo,
        title="Secret- und Runtime-Fix",
        bullets=["Auth-Guard repariert und systemd Runtime abgesichert."],
    )

    def fake_categorizer(_item: dict[str, object]) -> dict[str, object]:
        return {
            "categories": [
                "change-security",
                "risk-runtime-outage",
                "repo-wrong",
                "bad category",
                "change-security",
            ]
        }

    result = categorize_codex_history_outbox(
        store,
        categorizer=fake_categorizer,
        now=datetime(2026, 6, 19, 13, tzinfo=timezone.utc),
    )

    assert result["ok"] is True
    assert result["categorized"] == 1
    persisted = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]
    indexing = persisted["indexing"]
    assert indexing["category_source"] == "local_llm"
    assert indexing["categorized_at"] == "2026-06-19T13:00:00+00:00"
    assert "change-security" in indexing["categories"]
    assert "risk-runtime-outage" in indexing["categories"]
    assert "repo-wrong" not in indexing["categories"]
    assert "bad-category" not in indexing["categories"]

    exported = export_codex_history_bibliothekar_docs(
        store,
        instance_dir=instance_dir,
        instance_name="Depressionsbot",
    )
    assert "risk-runtime-outage" in exported["files"][0]["categories"]
    assert exported["files"][0]["item_id"] == item["id"]


def test_codex_history_graph_export_writes_admin_only_mermaid_doc(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    repo = make_git_repo(tmp_path, "graph-demo", version="1.9.3")
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    admin_id = store.resolve_or_create_account(telegram_identity_key(88), display_label="Admin")
    store.update_identity_route(telegram_identity_key(88), channel="telegram", chat_id="88", chat_type="private", adapter_slot=1)
    authorize_codex_admin(store, admin_id)
    append_codex_history_summary(
        store,
        repo_root=repo,
        title="Graph Export",
        bullets=["Mermaid-Uebersicht fuer Admins erzeugt."],
    )

    result = export_codex_history_graph_doc(
        store,
        instance_dir=instance_dir,
        instance_name="Depressionsbot",
        svg=True,
        queue_svg=True,
        now=datetime(2026, 6, 19, 15, tzinfo=timezone.utc),
    )

    assert result["ok"] is True
    assert result["exported"] == 1
    assert result["repo_count"] == 1
    assert result["item_count"] == 1
    graph_path = Path(result["path"])
    assert graph_path.parent == instance_dir / "data" / "Codex_History_Bibliothek" / "graphs"
    graph_text = graph_path.read_text(encoding="utf-8")
    assert "```mermaid" in graph_text
    assert "flowchart LR" in graph_text
    assert "Admin-only TeeBotus Codex-History-Graph" in graph_text
    assert "Graph Export" in graph_text
    assert 'totals["1 Summaries / 1 Repos"]:::metric' in graph_text
    assert 'status_overview["Status: queued=1"]:::status' in graph_text
    assert "Top-Kategorien:" in graph_text
    assert 'repo_0_stats["1 Summaries / queued=1"]:::metric' in graph_text
    assert result["svg_exported"] == 1
    svg_path = Path(result["svg_path"])
    assert svg_path.suffix == ".svg"
    svg_text = svg_path.read_text(encoding="utf-8")
    assert "<svg" in svg_text
    assert "TeeBotus Codex-History" in svg_text
    assert "Graph Export" in svg_text
    assert result["svg_engine"] == "builtin"
    queued = result["queued_item"]
    assert queued["kind"] == "codex_graph_artifact"
    assert queued["status"] == "queued"
    assert queued["attachment"]["filename"].endswith(".svg")
    assert queued["attachment"]["content_type"] == "image/svg+xml"
    assert not (instance_dir / "data" / "Bibliothek").exists()

    sent: list[SendAttachment] = []

    def sender(_route: dict[str, object], action: SendAttachment, _metadata: dict[str, object]) -> str:
        sent.append(action)
        return f"telegram-graph-{len(sent)}"

    dispatch = asyncio.run(
        dispatch_codex_history_outbox(
            store,
            instance_name="TeeBotus_Logger",
            account_ids=(admin_id,),
            senders={"telegram": sender},
            now=datetime(2026, 6, 19, 15, 5, tzinfo=timezone.utc),
        )
    )

    assert dispatch["status_counts"] == {"accepted": 2}
    assert sent[-1].filename.endswith(".svg")
    assert sent[-1].content_type == "image/svg+xml"
    assert b"<svg" in sent[-1].data


def test_codex_history_graph_mermaid_source_extracts_first_block(monkeypatch) -> None:
    def fake_markdown(_items: object, *, instance_name: str, repo_filter: str) -> str:  # noqa: ARG001
        return (
            f"Intro: {instance_name}|{repo_filter}\n"
            "```mermaid\n"
            "flowchart LR\n"
            "  A[Start] --> B[End]\n"
            "```\n"
            "Tail\n"
            "```mermaid\n"
            "flowchart LR\n"
            "  X --> Y\n"
            "```\n"
        )

    monkeypatch.setattr("TeeBotus.admin.codex_history._codex_history_graph_markdown", fake_markdown)
    body = _codex_history_graph_mermaid_source([], instance_name="demo", repo_filter="alpha")
    assert body == "flowchart LR\n  A[Start] --> B[End]\n"


def test_codex_history_graph_mermaid_source_requires_block_end(monkeypatch) -> None:
    def fake_markdown(_items: object, *, instance_name: str, repo_filter: str) -> str:  # noqa: ARG001
        return f"Intro: {instance_name}|{repo_filter}\n```mermaid\nflowchart LR\n  A --> B\n"

    monkeypatch.setattr("TeeBotus.admin.codex_history._codex_history_graph_markdown", fake_markdown)
    with pytest.raises(ValueError, match="does not contain a mermaid block"):
        _codex_history_graph_mermaid_source([], instance_name="demo", repo_filter="alpha")


def test_codex_history_graph_export_auto_svg_engine_falls_back_to_builtin(tmp_path: Path, monkeypatch) -> None:
    instance_dir = make_instance(tmp_path)
    repo = make_git_repo(tmp_path, "graph-auto-demo", version="1.9.3")
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    append_codex_history_summary(store, repo_root=repo, title="Auto Graph", bullets=["Optionales Rendering."])
    monkeypatch.setattr("TeeBotus.admin.codex_history.shutil.which", lambda _name: None)

    result = export_codex_history_graph_doc(
        store,
        instance_dir=instance_dir,
        instance_name="Depressionsbot",
        svg=True,
        svg_engine="auto",
    )

    assert result["svg_exported"] == 1
    assert result["svg_engine"] == "builtin"
    assert result["svg_warning"] == "mmdc_not_found_fallback_builtin"
    assert "Auto Graph" in Path(result["svg_path"]).read_text(encoding="utf-8")


def test_codex_history_graph_export_explicit_mmdc_requires_mermaid_cli(tmp_path: Path, monkeypatch) -> None:
    instance_dir = make_instance(tmp_path)
    repo = make_git_repo(tmp_path, "graph-mmdc-demo", version="1.9.3")
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    append_codex_history_summary(store, repo_root=repo, title="MMDC Graph", bullets=["Mermaid CLI Pflicht."])
    monkeypatch.setattr("TeeBotus.admin.codex_history.shutil.which", lambda _name: None)

    with pytest.raises(ValueError, match="mmdc svg render requested"):
        export_codex_history_graph_doc(
            store,
            instance_dir=instance_dir,
            instance_name="Depressionsbot",
            svg=True,
            svg_engine="mmdc",
        )


def test_codex_history_strategic_analysis_queues_admin_dispatchable_report(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    repo = make_git_repo(tmp_path, "strategy-demo", version="1.9.4")
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    admin_id = store.resolve_or_create_account(telegram_identity_key(77), display_label="Admin")
    store.update_identity_route(telegram_identity_key(77), channel="telegram", chat_id="77", chat_type="private", adapter_slot=1)
    authorize_codex_admin(store, admin_id)
    append_codex_history_summary(store, repo_root=repo, title="Feature A", bullets=["Neues Feature gebaut."])
    append_codex_history_summary(store, repo_root=repo, title="Bugfix B", bullets=["Runtime-Fehler repariert."])

    result = generate_codex_history_strategic_analysis(
        store,
        instance_name="Depressionsbot",
        strategist=lambda _items: {
            "future_improvements": ["Qdrant-Graph rendern."],
            "strategic_goals": ["Admin-History als Projektnerv nutzen."],
            "pitfalls_logic_errors": ["Dispatch-Status nicht mit echter Zustellung verwechseln."],
            "attack_surface": ["Admin-only Index darf nicht in Nutzerbibliothek leaken."],
            "recommendations": ["Receipts weiter haerten."],
            "confidence": "high",
        },
        now=datetime(2026, 6, 19, 14, tzinfo=timezone.utc),
    )

    assert result["ok"] is True
    assert result["status"] == "queued"
    assert result["analyzed"] == 2
    persisted = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
    assert [row["kind"] for row in persisted] == ["codex_run_summary", "codex_run_summary", "codex_strategy_analysis"]
    strategy = persisted[-1]
    assert strategy["summary_prefix"] == f"v{__version__} #0001"
    assert strategy["codex"]["strategy_profile"] == "local_ollama"
    assert strategy["codex"]["source_fingerprint"]
    assert strategy["delivery"]["target_group"] == "status_admins"
    assert "Strategische Codex-History-Analyse" in strategy["summary"]["markdown"]
    assert "Admin-only Index darf nicht" in strategy["summary"]["markdown"]
    assert "codex-strategy-analysis" in strategy["indexing"]["categories"]

    sent: list[SendAttachment] = []

    def sender(_route: dict[str, object], action: SendAttachment, _metadata: dict[str, object]) -> str:
        sent.append(action)
        return "telegram-strategy-1"

    dispatch = asyncio.run(
        dispatch_codex_history_outbox(
            store,
            instance_name="TeeBotus_Logger",
            account_ids=(admin_id,),
            senders={"telegram": sender},
            now=datetime(2026, 6, 19, 14, 5, tzinfo=timezone.utc),
        )
    )

    assert dispatch["status_counts"] == {"accepted": 3}
    assert sent[-1].caption == f"Release Codex-History-Strategie {__version__}"
    assert sent[-1].filename == f"Codex-History-Strategie_release_{__version__}_0001.md"
    assert b"Strategische Codex-History-Analyse" in sent[-1].data


def test_codex_history_strategic_analysis_reuses_cached_source_set(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    repo = make_git_repo(tmp_path, "strategy-cache-demo", version="1.9.4")
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    append_codex_history_summary(store, repo_root=repo, title="Feature A", bullets=["Neues Feature gebaut."])
    calls: list[int] = []

    def strategist(_items):
        calls.append(1)
        return {"recommendations": ["Einmal analysieren."]}

    first = generate_codex_history_strategic_analysis(
        store,
        instance_name="Depressionsbot",
        strategist=strategist,
        now=datetime(2026, 6, 19, 14, tzinfo=timezone.utc),
    )
    second = generate_codex_history_strategic_analysis(
        store,
        instance_name="Depressionsbot",
        strategist=strategist,
        now=datetime(2026, 6, 19, 15, tzinfo=timezone.utc),
    )
    forced = generate_codex_history_strategic_analysis(
        store,
        instance_name="Depressionsbot",
        strategist=strategist,
        force=True,
        now=datetime(2026, 6, 19, 16, tzinfo=timezone.utc),
    )

    assert first["cache_hit"] is False
    assert second["status"] == "skipped"
    assert second["reason"] == "source_set_unchanged"
    assert second["cache_hit"] is True
    assert second["cached_summary_prefix"] == first["item"]["summary_prefix"]
    assert forced["cache_hit"] is False
    assert calls == [1, 1]
    persisted = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
    assert [row["kind"] for row in persisted].count("codex_strategy_analysis") == 2


def test_codex_history_strategist_rejects_remote_profile_without_explicit_allow() -> None:
    with pytest.raises(ValueError, match="remote"):
        build_codex_history_strategist(profile="openai_premium", env={})


def test_codex_history_index_can_categorize_before_export_without_provider_call(tmp_path: Path) -> None:
    instance_dir = make_instance(tmp_path)
    repo = make_git_repo(tmp_path, "categorize-index-demo", version="1.9.2")
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    append_codex_history_summary(store, repo_root=repo, title="Benchmark gebaut", bullets=["Neue Latenzbenchmarks."])
    rows = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
    rows[0]["summary"]["markdown"] = rows[0]["summary"]["markdown"].split("## Verknuepfte Summaries", 1)[0].rstrip() + "\n"
    store.write_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID, rows)

    result = run_codex_history_index(
        store,
        instance_dir=instance_dir,
        instance_name="Depressionsbot",
        categorize=True,
        graph=True,
        graph_svg=True,
        graph_queue_svg=True,
        categorizer=lambda _item: {"categories": ["work-benchmark", "change-performance"]},
        strategic_analysis=True,
        strategist=lambda _items: {"recommendations": ["Graph und Strategie in einem Batch pruefen."]},
    )

    assert result["ok"] is True
    assert result["categorize"]["categorized"] == 1
    assert result["summary_context"]["changed_items"] == 1
    assert result["strategic_analysis"]["analyzed"] == 1
    assert result["export"]["exported"] == 2
    assert result["graph"]["exported"] == 1
    assert result["graph"]["svg_exported"] == 1
    assert result["graph"]["queued_item"]["kind"] == "codex_graph_artifact"
    # The strategy report is created before export, so the same batch exports both docs.
    assert len(result["export"]["files"]) == 2
    exported_texts = [Path(file["path"]).read_text(encoding="utf-8") for file in result["export"]["files"]]
    assert any("work-benchmark" in text for text in exported_texts)
    assert any("change-performance" in text for text in exported_texts)
    assert any("## Verknuepfte Summaries" in text for text in exported_texts)
    assert any("## Mermaid-Kontext" in text for text in exported_texts)
    assert any("Strategische Codex-History-Analyse" in text for text in exported_texts)
    graph_text = Path(result["graph"]["path"]).read_text(encoding="utf-8")
    assert "work-benchmark" in graph_text
    assert "Strategische Codex-History-Analyse" in graph_text


def test_codex_history_local_categorizer_rejects_remote_profiles() -> None:
    with pytest.raises(ValueError, match="local-only"):
        build_local_codex_history_categorizer(profile="openai_premium", env={})


def test_codex_history_cli_bibliothekar_export_filters_repo(tmp_path: Path, capsys) -> None:
    instance_dir = make_instance(tmp_path)
    repo_alpha = make_git_repo(tmp_path, "alpha-export", version="1.8.7")
    repo_beta = make_git_repo(tmp_path, "beta-export", version="2.0.0")
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    append_codex_history_summary(store, repo_root=repo_alpha, title="Alpha Export", bullets=["Soll exportiert werden."])
    append_codex_history_summary(store, repo_root=repo_beta, title="Beta Export", bullets=["Soll gefiltert werden."])

    result = codex_history_main(
        [
            "bibliothekar-export",
            "--instances-dir",
            str(tmp_path),
            "--instance",
            "Depressionsbot",
            "--repo",
            "alpha-export",
            "--format",
            "json",
        ],
        provider=provider(),
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["totals"] == {"exported": 1, "skipped": 0}
    files = payload["instances"][0]["files"]
    assert len(files) == 1
    assert files[0]["repo_name"] == "alpha-export"
    assert Path(files[0]["path"]).exists()
    assert "Alpha Export" in Path(files[0]["path"]).read_text(encoding="utf-8")
    assert "Beta Export" not in Path(files[0]["path"]).read_text(encoding="utf-8")


def test_codex_history_index_cli_exports_and_dry_runs_qdrant(tmp_path: Path, capsys) -> None:
    instance_dir = make_instance(tmp_path)
    repo = make_git_repo(tmp_path, "index-cli-demo", version="1.8.9")
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    append_codex_history_summary(store, repo_root=repo, title="Index CLI", bullets=["Export und Qdrant-Dry-Run in einem Lauf."])

    result = codex_history_main(
        [
            "index",
            "--instances-dir",
            str(tmp_path),
            "--instance",
            "Depressionsbot",
            "--qdrant",
            "--qdrant-dry-run",
            "--format",
            "json",
        ],
        provider=provider(),
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["totals"]["exported"] == 1
    assert payload["totals"]["qdrant_points"] == 1
    instance = payload["instances"][0]
    assert instance["export"]["exported"] == 1
    assert instance["qdrant"][0]["status"] == "dry_run"
    assert instance["qdrant"][0]["point_count"] == 1
    assert (tmp_path / "Depressionsbot" / "data" / "Codex_History_Bibliothek").exists()
    assert not (tmp_path / "Depressionsbot" / "data" / "Bibliothek").exists()


def test_codex_history_dispatch_sends_markdown_attachment_and_marks_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEEBOTUS_CODEX_HISTORY_TIMEZONE", "Europe/Berlin")
    repo = make_git_repo(tmp_path, "dispatch-demo", version="1.9.0")
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    admin_id = store.resolve_or_create_account(telegram_identity_key(42), display_label="Admin")
    store.update_identity_route(telegram_identity_key(42), channel="telegram", chat_id="42", chat_type="private", adapter_slot=1)
    authorize_codex_admin(store, admin_id)
    item = append_codex_history_summary(
        store,
        repo_root=repo,
        title="Dispatch gebaut",
        bullets=["Summary wird als Markdown-Datei versendet."],
        session_id="sess-dispatch",
    )
    rows = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
    rows[0]["created_at"] = "2026-06-19T12:00:00+00:00"
    store.write_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID, rows)
    sent: list[tuple[dict[str, object], SendAttachment, dict[str, object]]] = []

    def sender(route: dict[str, object], action: SendAttachment, metadata: dict[str, object]) -> str:
        sent.append((route, action, metadata))
        return "telegram-msg-1"

    result = asyncio.run(
        dispatch_codex_history_outbox(
            store,
            instance_name="TeeBotus_Logger",
            account_ids=(admin_id,),
            senders={"telegram": sender},
            now=datetime(2026, 6, 19, 12, tzinfo=timezone.utc),
        )
    )

    assert result["status_counts"] == {"accepted": 1}
    assert sent
    route, action, metadata = sent[0]
    assert route["channel"] == "telegram"
    assert action.chat_id == "42"
    assert action.caption == "Release dispatch-demo 1.9.0"
    assert action.filename == "dispatch-demo_release_1.9.0_0001.md"
    assert action.content_type == "text/markdown"
    assert b"# v1.9.0 #0001 Dispatch gebaut" in action.data
    assert metadata["source"] == "codex_history_dispatch"
    assert metadata["codex_history_item_id"] == item["id"]

    persisted = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert persisted["status"] == "accepted"
    assert persisted["delivery"]["attempts"] == 1
    assert persisted["delivery"]["sent_at"] == "2026-06-19T12:00:00+00:00"
    assert persisted["delivery"]["accepted_at"] == "2026-06-19T12:00:00+00:00"
    assert [entry["status"] for entry in persisted["status_history"]][-2:] == ["dispatching", "accepted"]
    dispatch = store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert dispatch["codex_history_item_id"] == item["id"]
    assert dispatch["account_id"] == admin_id
    assert dispatch["status"] == "accepted"
    assert dispatch["message_ref"] == "telegram-msg-1"
    assert Path(dispatch["obsidian_path"]).name.startswith("20260619T140000_")


def test_codex_history_dispatch_bridge_claims_sends_and_completes_only_open_recipients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def request(self, operation: str, body: dict[str, object] | None = None) -> dict[str, object]:
            calls.append((operation, dict(body or {})))
            if operation == "dispatch.claim":
                return {
                    "ok": True,
                    "data": {
                        "items": [{
                            "id": "hd-item-1",
                            "kind": "codex_run_summary",
                            "created_at": "2026-06-19T12:00:00+00:00",
                            "payload": {"summary": {"text": "Bridge summary"}, "project": "/tmp/bridge"},
                            "recipient_results": [{"account_id": "already", "status": "delivered"}],
                        }],
                    },
                }
            if operation == "dispatch.complete":
                return {"ok": True, "data": {"ok": True, "status": "delivered"}}
            raise AssertionError(operation)

    async def fake_send(*_args, **kwargs):
        return {"account_id": kwargs.get("account_id", "open"), "status": "accepted", "channel": "telegram"}

    monkeypatch.setattr(codex_history_module, "HistoryDispatcherClient", FakeClient)
    monkeypatch.setattr(codex_history_module, "_codex_history_dispatch_account_ids", lambda *args, **kwargs: ("already", "open"))
    monkeypatch.setattr(codex_history_module, "_dispatch_codex_history_item_to_account", fake_send)
    result = asyncio.run(
        dispatch_codex_history_outbox(
            object(),
            instance_name="TeeBotus_Logger",
            env={"TEEBOTUS_HISTORY_DISPATCHER_MODE": "bridge", "HISTORY_DISPATCHER_SOCKET": "/tmp/dispatcher.sock"},
            limit=0,
        )
    )
    assert result["mode"] == "history-dispatcher"
    assert result["status_counts"] == {"delivered": 2}
    assert [operation for operation, _body in calls] == ["dispatch.claim", "dispatch.complete"]
    assert calls[0][1]["limit"] == 0
    complete_body = calls[-1][1]
    assert [row["recipient_id"] for row in complete_body["recipient_results"]] == ["open"]


def test_codex_history_dispatch_bridge_preserves_already_delivered_recipients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def request(self, operation: str, body: dict[str, object] | None = None) -> dict[str, object]:
            calls.append((operation, dict(body or {})))
            if operation == "dispatch.claim":
                return {
                    "ok": True,
                    "data": {
                        "items": [{
                            "id": "hd-item-already-delivered",
                            "kind": "codex_run_summary",
                            "payload": {"summary": {"text": "Already delivered"}},
                            "recipient_results": [{"recipient_id": "already", "status": "delivered"}],
                        }],
                    },
                }
            if operation == "dispatch.complete":
                return {"ok": True, "data": {"ok": True, "status": "delivered"}}
            raise AssertionError(operation)

    async def unexpected_send(*_args, **_kwargs):
        raise AssertionError("an already delivered recipient must not be sent again")

    monkeypatch.setattr(codex_history_module, "HistoryDispatcherClient", FakeClient)
    monkeypatch.setattr(codex_history_module, "_codex_history_dispatch_account_ids", lambda *args, **kwargs: ("already",))
    monkeypatch.setattr(codex_history_module, "_dispatch_codex_history_item_to_account", unexpected_send)
    result = asyncio.run(
        dispatch_codex_history_outbox(
            object(),
            instance_name="TeeBotus_Logger",
            env={"TEEBOTUS_HISTORY_DISPATCHER_MODE": "bridge", "HISTORY_DISPATCHER_SOCKET": "/tmp/dispatcher.sock"},
        )
    )

    assert result["status_counts"] == {"delivered": 1}
    assert [operation for operation, _body in calls] == ["dispatch.claim", "dispatch.complete"]
    assert calls[-1][1]["recipient_results"] == [{
        "recipient_id": "already",
        "status": "delivered",
        "channel": "",
        "message_ref": "",
        "reason": "",
        "possible_duplicate": False,
    }]


def test_codex_history_dispatch_bridge_rejects_nested_completion_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def request(self, operation: str, body: dict[str, object] | None = None) -> dict[str, object]:
            if operation == "dispatch.claim":
                return {
                    "ok": True,
                    "data": {
                        "items": [{
                            "id": "hd-item-claim-lost",
                            "kind": "codex_run_summary",
                            "payload": {"summary": {"text": "Claim verloren"}},
                            "recipient_results": [],
                        }],
                    },
                }
            if operation == "dispatch.complete":
                return {"ok": True, "data": {"ok": False, "error": "claim_not_owned"}}
            raise AssertionError(operation)

    async def fake_send(*_args, **kwargs):
        return {"account_id": kwargs.get("account_id", "open"), "status": "accepted", "channel": "telegram"}

    monkeypatch.setattr(codex_history_module, "HistoryDispatcherClient", FakeClient)
    monkeypatch.setattr(codex_history_module, "_codex_history_dispatch_account_ids", lambda *args, **kwargs: ("open",))
    monkeypatch.setattr(codex_history_module, "_dispatch_codex_history_item_to_account", fake_send)

    result = asyncio.run(
        dispatch_codex_history_outbox(
            object(),
            instance_name="TeeBotus_Logger",
            env={"TEEBOTUS_HISTORY_DISPATCHER_MODE": "bridge", "HISTORY_DISPATCHER_SOCKET": "/tmp/dispatcher.sock"},
        )
    )

    assert result["ok"] is False
    assert result["status_counts"] == {"failed": 1}
    assert result["items"][0]["reason"] == "history_dispatcher_unavailable"
    assert "claim_not_owned" in result["items"][0]["error"]


def test_codex_history_dispatch_bridge_rejects_malformed_claim_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def request(self, operation: str, body: dict[str, object] | None = None) -> dict[str, object]:
            if operation == "dispatch.claim":
                return {"ok": True, "data": None}
            raise AssertionError(operation)

    monkeypatch.setattr(codex_history_module, "HistoryDispatcherClient", FakeClient)
    result = asyncio.run(
        dispatch_codex_history_outbox(
            object(),
            instance_name="TeeBotus_Logger",
            env={"TEEBOTUS_HISTORY_DISPATCHER_MODE": "bridge", "HISTORY_DISPATCHER_SOCKET": "/tmp/dispatcher.sock"},
        )
    )

    assert result["ok"] is False
    assert result["status_counts"] == {"failed": 1}
    assert result["items"][0]["reason"] == "history_dispatcher_unavailable"
    assert "invalid data" in result["items"][0]["error"]


def test_history_dispatcher_response_items_rejects_duplicate_ids() -> None:
    with pytest.raises(codex_history_module.HistoryDispatcherError, match="duplicate item id"):
        codex_history_module._history_dispatcher_response_items(
            {"items": [{"id": "same"}, {"id": "same"}]},
            operation="dispatch.claim",
        )


def test_codex_history_dispatch_bridge_rejects_invalid_claim_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def request(self, operation: str, body: dict[str, object] | None = None) -> dict[str, object]:
            if operation == "dispatch.claim":
                return {"ok": True, "data": {"items": [{"id": "wrong-status", "status": "delivered"}]}}
            raise AssertionError(operation)

    monkeypatch.setattr(codex_history_module, "HistoryDispatcherClient", FakeClient)
    result = asyncio.run(
        dispatch_codex_history_outbox(
            object(),
            instance_name="TeeBotus_Logger",
            env={"TEEBOTUS_HISTORY_DISPATCHER_MODE": "bridge", "HISTORY_DISPATCHER_SOCKET": "/tmp/dispatcher.sock"},
        )
    )

    assert result["ok"] is False
    assert result["items"][0]["reason"] == "history_dispatcher_unavailable"
    assert "invalid status" in result["items"][0]["error"]


def test_codex_history_dispatch_bridge_rejects_missing_completion_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def request(self, operation: str, body: dict[str, object] | None = None) -> dict[str, object]:
            if operation == "dispatch.claim":
                return {"ok": True, "data": {"items": [{"id": "missing-completion-status", "kind": "codex_run_summary", "payload": {"summary": {"text": "Status fehlt"}}, "recipient_results": []}]}}
            if operation == "dispatch.complete":
                return {"ok": True, "data": {"ok": True}}
            raise AssertionError(operation)

    async def fake_send(*_args, **kwargs):
        return {"account_id": kwargs.get("account_id", "open"), "status": "accepted", "channel": "telegram"}

    monkeypatch.setattr(codex_history_module, "HistoryDispatcherClient", FakeClient)
    monkeypatch.setattr(codex_history_module, "_codex_history_dispatch_account_ids", lambda *args, **kwargs: ("open",))
    monkeypatch.setattr(codex_history_module, "_dispatch_codex_history_item_to_account", fake_send)
    result = asyncio.run(
        dispatch_codex_history_outbox(
            object(),
            instance_name="TeeBotus_Logger",
            env={"TEEBOTUS_HISTORY_DISPATCHER_MODE": "bridge", "HISTORY_DISPATCHER_SOCKET": "/tmp/dispatcher.sock"},
        )
    )

    assert result["ok"] is False
    assert result["items"][0]["reason"] == "history_dispatcher_unavailable"
    assert "invalid status" in result["items"][0]["error"]


def test_codex_history_dispatch_bridge_rejects_non_object_claim_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def request(self, operation: str, body: dict[str, object] | None = None) -> dict[str, object]:
            calls.append(operation)
            if operation == "dispatch.claim":
                return {"ok": True, "data": {"items": [None]}}
            raise AssertionError(operation)

    monkeypatch.setattr(codex_history_module, "HistoryDispatcherClient", FakeClient)
    result = asyncio.run(
        dispatch_codex_history_outbox(
            object(),
            instance_name="TeeBotus_Logger",
            env={"TEEBOTUS_HISTORY_DISPATCHER_MODE": "bridge", "HISTORY_DISPATCHER_SOCKET": "/tmp/dispatcher.sock"},
        )
    )

    assert result["ok"] is False
    assert result["status_counts"] == {"failed": 1}
    assert result["items"][0]["reason"] == "history_dispatcher_unavailable"
    assert "invalid item" in result["items"][0]["error"]
    assert calls == ["dispatch.claim"]


def test_codex_history_dispatch_bridge_rejects_invalid_recipient_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def request(self, operation: str, body: dict[str, object] | None = None) -> dict[str, object]:
            calls.append(operation)
            if operation == "dispatch.claim":
                return {
                    "ok": True,
                    "data": {
                        "items": [{
                            "id": "hd-item-invalid-recipients",
                            "kind": "codex_run_summary",
                            "payload": {"summary": {"text": "Ungueltige Empfaenger"}},
                            "recipient_results": None,
                        }],
                    },
                }
            raise AssertionError(operation)

    monkeypatch.setattr(codex_history_module, "HistoryDispatcherClient", FakeClient)
    result = asyncio.run(
        dispatch_codex_history_outbox(
            object(),
            instance_name="TeeBotus_Logger",
            env={"TEEBOTUS_HISTORY_DISPATCHER_MODE": "bridge", "HISTORY_DISPATCHER_SOCKET": "/tmp/dispatcher.sock"},
        )
    )

    assert result["ok"] is False
    assert result["status_counts"] == {"failed": 1}
    assert "invalid recipient_results" in result["items"][0]["error"]
    assert calls == ["dispatch.claim"]


def test_codex_history_dispatch_bridge_rejects_foreign_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def request(self, operation: str, body: dict[str, object] | None = None) -> dict[str, object]:
            calls.append(operation)
            if operation == "dispatch.claim":
                return {
                    "ok": True,
                    "data": {
                        "items": [{
                            "id": "hd-item-foreign-kind",
                            "kind": "other_runtime_event",
                            "payload": {"summary": {"text": "Fremder Typ"}},
                            "recipient_results": [],
                        }],
                    },
                }
            raise AssertionError(operation)

    monkeypatch.setattr(codex_history_module, "HistoryDispatcherClient", FakeClient)
    result = asyncio.run(
        dispatch_codex_history_outbox(
            object(),
            instance_name="TeeBotus_Logger",
            env={"TEEBOTUS_HISTORY_DISPATCHER_MODE": "bridge", "HISTORY_DISPATCHER_SOCKET": "/tmp/dispatcher.sock"},
        )
    )

    assert result["ok"] is False
    assert result["status_counts"] == {"failed": 1}
    assert "unsupported kind" in result["items"][0]["error"]
    assert calls == ["dispatch.claim"]


def test_codex_history_dispatch_bridge_rejects_unknown_recipient_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def request(self, operation: str, body: dict[str, object] | None = None) -> dict[str, object]:
            calls.append(operation)
            if operation == "dispatch.claim":
                return {
                    "ok": True,
                    "data": {
                        "items": [{
                            "id": "hd-item-unknown-status",
                            "kind": "codex_run_summary",
                            "payload": {"summary": {"text": "Unbekannter Status"}},
                            "recipient_results": [{"recipient_id": "admin", "status": "sent"}],
                        }],
                    },
                }
            raise AssertionError(operation)

    monkeypatch.setattr(codex_history_module, "HistoryDispatcherClient", FakeClient)
    result = asyncio.run(
        dispatch_codex_history_outbox(
            object(),
            instance_name="TeeBotus_Logger",
            env={"TEEBOTUS_HISTORY_DISPATCHER_MODE": "bridge", "HISTORY_DISPATCHER_SOCKET": "/tmp/dispatcher.sock"},
        )
    )

    assert result["ok"] is False
    assert result["status_counts"] == {"failed": 1}
    assert "unsupported recipient status" in result["items"][0]["error"]
    assert calls == ["dispatch.claim"]


def test_history_dispatcher_recipient_results_reject_duplicate_or_conflicting_identity() -> None:
    with pytest.raises(codex_history_module.HistoryDispatcherError, match="duplicate recipient_id"):
        codex_history_module._history_dispatcher_recipient_results(
            {
                "id": "duplicate-recipient",
                "recipient_results": [
                    {"recipient_id": "admin", "status": "delivered"},
                    {"recipient_id": "ADMIN", "status": "failed"},
                ],
            }
        )
    with pytest.raises(codex_history_module.HistoryDispatcherError, match="conflicting recipient identity"):
        codex_history_module._history_dispatcher_recipient_results(
            {
                "id": "conflicting-recipient",
                "recipient_results": [{"recipient_id": "admin-a", "account_id": "admin-b", "status": "delivered"}],
            }
        )


def test_codex_history_overall_status_aligns_success_plus_skip_with_dispatcher() -> None:
    rows = [
        {"status": "accepted"},
        {"status": "skipped", "reason": "no_private_route"},
    ]
    assert codex_history_module._overall_dispatch_status(rows) == "delivered"
    assert codex_history_module._overall_dispatch_reason(rows) == ""


def test_codex_history_success_plus_skip_clears_stale_item_reason(tmp_path: Path) -> None:
    store = AccountStore(tmp_path / "accounts", "TeeBotus_Logger", provider())
    store.append_codex_history_item(
        INSTANCE_STATE_ACCOUNT_ID,
        {
            "id": "mixed-success-skip",
            "kind": "codex_run_summary",
            "status": "queued",
            "last_reason": "send_error:old_failure",
            "summary": {"text": "Erfolg und begruendeter Skip."},
        },
    )
    rows = [
        {"status": "accepted", "reason": "accepted"},
        {"status": "skipped", "reason": "no_private_route"},
    ]

    codex_history_module._update_codex_history_item_status(
        store,
        "mixed-success-skip",
        codex_history_module._overall_dispatch_status(rows),
        reason=codex_history_module._overall_dispatch_reason(rows),
        now="2026-07-13T12:00:00+00:00",
        dispatch_results=rows,
    )

    persisted = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert persisted["status"] == "delivered"
    assert "last_reason" not in persisted


def test_codex_history_dispatch_bridge_rejects_incomplete_completion_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def request(self, operation: str, body: dict[str, object] | None = None) -> dict[str, object]:
            calls.append(operation)
            if operation == "dispatch.claim":
                return {
                    "ok": True,
                    "data": {
                        "items": [{
                            "id": "hd-item-incomplete-completion",
                            "kind": "codex_run_summary",
                            "payload": {"summary": {"text": "Completion fehlt"}},
                            "recipient_results": [],
                        }],
                    },
                }
            if operation == "dispatch.complete":
                return {"ok": True, "data": None}
            raise AssertionError(operation)

    async def fake_send(*_args, **kwargs):
        return {"account_id": kwargs.get("account_id", "open"), "status": "accepted", "channel": "telegram"}

    monkeypatch.setattr(codex_history_module, "HistoryDispatcherClient", FakeClient)
    monkeypatch.setattr(codex_history_module, "_codex_history_dispatch_account_ids", lambda *args, **kwargs: ("open",))
    monkeypatch.setattr(codex_history_module, "_dispatch_codex_history_item_to_account", fake_send)
    result = asyncio.run(
        dispatch_codex_history_outbox(
            object(),
            instance_name="TeeBotus_Logger",
            env={"TEEBOTUS_HISTORY_DISPATCHER_MODE": "bridge", "HISTORY_DISPATCHER_SOCKET": "/tmp/dispatcher.sock"},
        )
    )

    assert result["ok"] is False
    assert result["status_counts"] == {"failed": 1}
    assert "invalid data" in result["items"][0]["error"]
    assert calls == ["dispatch.claim", "dispatch.complete"]


def test_codex_history_dispatch_bridge_dry_run_requests_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    seen_items: list[dict[str, object]] = []

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def request(self, operation: str, body: dict[str, object] | None = None) -> dict[str, object]:
            calls.append((operation, dict(body or {})))
            if operation == "history.query":
                return {
                    "ok": True,
                    "data": {
                        "items": [{
                            "id": "hd-item-dry-run",
                            "kind": "codex_run_summary",
                            "project": "/tmp/dry-run",
                            "created_at": "2026-07-13T12:00:00+00:00",
                            "payload": {
                                "summary_prefix": "v1.9.380 #0001",
                                "summary": {"text": "Dry-Run mit Payload"},
                            },
                        }],
                    },
                }
            raise AssertionError(operation)

    def fake_rows(item, *_args, **_kwargs):
        seen_items.append(dict(item))
        return [{"status": "would_skip", "summary_prefix": item["summary_prefix"]}]

    monkeypatch.setattr(codex_history_module, "HistoryDispatcherClient", FakeClient)
    monkeypatch.setattr(codex_history_module, "_dry_run_dispatch_rows", fake_rows)
    result = asyncio.run(
        dispatch_codex_history_outbox(
            object(),
            instance_name="TeeBotus_Logger",
            env={"TEEBOTUS_HISTORY_DISPATCHER_MODE": "bridge", "HISTORY_DISPATCHER_SOCKET": "/tmp/dispatcher.sock"},
            dry_run=True,
        )
    )

    assert result["ok"] is True
    assert calls == [("history.query", {"status": "queued", "limit": 100, "include_payload": True})]
    assert seen_items[0]["summary_prefix"] == "v1.9.380 #0001"
    assert result["items"] == [{"status": "would_skip", "summary_prefix": "v1.9.380 #0001"}]


def test_codex_history_dispatch_bridge_mirrors_local_orphan_before_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = AccountStore(tmp_path / "accounts", "TeeBotus_Logger", provider())
    store.append_codex_history_item(
        INSTANCE_STATE_ACCOUNT_ID,
        {
            "id": "local-orphan",
            "kind": "codex_run_summary",
            "status": "queued",
            "created_at": "2026-07-13T12:00:00+00:00",
            "project": {"repo_name": "TeeBotus"},
            "summary_prefix": "v1.9.409 #0001",
            "codex": {"dedupe_key": "sha256:local-orphan"},
            "summary": {"text": "Lokaler Orphan wird nachgefuehrt."},
        },
    )
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def request(self, operation: str, body: dict[str, object] | None = None) -> dict[str, object]:
            calls.append((operation, dict(body or {})))
            if operation == "history.append":
                return {"ok": True, "data": {"id": "external-orphan", "deduplicated": False, "status": "queued"}}
            if operation == "dispatch.claim":
                return {"ok": True, "data": {"items": []}}
            if operation == "history.query":
                return {"ok": True, "data": {"items": []}}
            raise AssertionError(operation)

    monkeypatch.setattr(codex_history_module, "HistoryDispatcherClient", FakeClient)
    monkeypatch.setattr(codex_history_module, "_codex_history_dispatch_account_ids", lambda *args, **kwargs: ())
    result = asyncio.run(
        dispatch_codex_history_outbox(
            store,
            instance_name="TeeBotus_Logger",
            env={"TEEBOTUS_HISTORY_DISPATCHER_MODE": "bridge", "HISTORY_DISPATCHER_SOCKET": "/tmp/dispatcher.sock"},
            now=datetime(2026, 7, 13, 12, 5, tzinfo=timezone.utc),
            limit=1,
        )
    )

    assert result["ok"] is True
    assert [operation for operation, _body in calls] == ["history.append", "dispatch.claim", "history.query"]
    assert calls[0][1]["id"] == "local-orphan"
    assert calls[0][1]["dedupe_key"] == "sha256:local-orphan"
    assert calls[0][1]["payload"]["id"] == "local-orphan"
    assert store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]["status"] == "queued"


def test_codex_history_dispatch_bridge_reconciles_terminal_local_queue_after_empty_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = AccountStore(tmp_path / "accounts", "TeeBotus_Logger", provider())
    store.append_codex_history_item(
        INSTANCE_STATE_ACCOUNT_ID,
        {
            "id": "local-terminal-sync",
            "kind": "codex_run_summary",
            "status": "queued",
            "created_at": "2026-07-13T12:00:00+00:00",
            "summary_prefix": "v1.9.409 #0004",
            "codex": {"dedupe_key": "sha256:terminal-live"},
            "summary": {"text": "Der zentrale Dispatcher ist bereits fertig."},
        },
    )
    calls: list[str] = []

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def request(self, operation: str, body: dict[str, object] | None = None) -> dict[str, object]:
            calls.append(operation)
            if operation == "history.append":
                return {
                    "ok": True,
                    "data": {"id": "external-terminal-sync", "deduplicated": True, "status": "queued"},
                }
            if operation == "dispatch.claim":
                return {"ok": True, "data": {"items": []}}
            if operation == "history.query":
                return {
                    "ok": True,
                    "data": {
                        "items": [{
                            "id": "external-terminal-sync",
                            "kind": "codex_run_summary",
                            "status": "delivered",
                            "dedupe_key": "sha256:terminal-live",
                        }],
                    },
                }
            raise AssertionError(operation)

    monkeypatch.setattr(codex_history_module, "HistoryDispatcherClient", FakeClient)
    monkeypatch.setattr(codex_history_module, "_codex_history_dispatch_account_ids", lambda *args, **kwargs: ())
    result = asyncio.run(
        dispatch_codex_history_outbox(
            store,
            instance_name="TeeBotus_Logger",
            env={"TEEBOTUS_HISTORY_DISPATCHER_MODE": "bridge", "HISTORY_DISPATCHER_SOCKET": "/tmp/dispatcher.sock"},
            now=datetime(2026, 7, 13, 12, 5, tzinfo=timezone.utc),
            limit=1,
        )
    )

    assert result["ok"] is True
    assert result["status_counts"] == {"synchronized": 1}
    assert calls == ["history.append", "dispatch.claim", "history.query"]
    persisted = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert persisted["status"] == "delivered"
    assert persisted["status_history"][-1] == {
        "at": "2026-07-13T12:05:00+00:00",
        "status": "delivered",
        "reason": "dispatcher_terminal_status_delivered",
    }


def test_codex_history_dispatch_bridge_dry_run_reports_local_reconciliation_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = AccountStore(tmp_path / "accounts", "TeeBotus_Logger", provider())
    store.append_codex_history_item(
        INSTANCE_STATE_ACCOUNT_ID,
        {
            "id": "local-orphan",
            "kind": "codex_run_summary",
            "status": "queued",
            "created_at": "2026-07-13T12:00:00+00:00",
            "summary_prefix": "v1.9.409 #0001",
            "codex": {"dedupe_key": "sha256:orphan"},
            "summary": {"text": "Noch nicht zentral vorhanden."},
        },
    )
    store.append_codex_history_item(
        INSTANCE_STATE_ACCOUNT_ID,
        {
            "id": "local-terminal",
            "kind": "codex_run_summary",
            "status": "queued",
            "created_at": "2026-07-13T12:01:00+00:00",
            "summary_prefix": "v1.9.409 #0002",
            "codex": {"dedupe_key": "sha256:terminal"},
            "summary": {"text": "Zentral bereits terminal."},
        },
    )
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def request(self, operation: str, body: dict[str, object] | None = None) -> dict[str, object]:
            calls.append((operation, dict(body or {})))
            if operation == "history.query":
                return {
                    "ok": True,
                    "data": {
                        "items": [{
                            "id": "external-terminal",
                            "status": "delivered",
                            "kind": "codex_run_summary",
                            "dedupe_key": "sha256:terminal",
                            "payload": {"summary": {"text": "Zentral bestaetigt"}},
                        }],
                    },
                }
            raise AssertionError(operation)

    monkeypatch.setattr(codex_history_module, "HistoryDispatcherClient", FakeClient)
    monkeypatch.setattr(codex_history_module, "_codex_history_dispatch_account_ids", lambda *args, **kwargs: ())
    result = asyncio.run(
        dispatch_codex_history_outbox(
            store,
            instance_name="TeeBotus_Logger",
            env={"TEEBOTUS_HISTORY_DISPATCHER_MODE": "bridge", "HISTORY_DISPATCHER_SOCKET": "/tmp/dispatcher.sock"},
            dry_run=True,
            limit=0,
        )
    )

    assert result["ok"] is True
    assert [operation for operation, _body in calls] == ["history.query"]
    assert calls[0][1] == {"status": "", "limit": 0, "include_payload": True}
    assert {row["status"] for row in result["items"]} == {"would_mirror", "would_sync"}
    assert any(row["reason"] == "local_outbox_not_in_dispatcher" for row in result["items"])
    assert any(row["reason"] == "dispatcher_terminal_status_delivered" for row in result["items"])
    assert all(row["status"] == "queued" for row in store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID))


def test_codex_history_dispatch_bridge_mirror_failure_keeps_local_item_queued(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = AccountStore(tmp_path / "accounts", "TeeBotus_Logger", provider())
    store.append_codex_history_item(
        INSTANCE_STATE_ACCOUNT_ID,
        {
            "id": "local-mirror-failure",
            "kind": "codex_run_summary",
            "status": "queued",
            "created_at": "2026-07-13T12:00:00+00:00",
            "summary_prefix": "v1.9.409 #0003",
            "codex": {"dedupe_key": "sha256:mirror-failure"},
            "summary": {"text": "Mirror darf nicht als Erfolg gelten."},
        },
    )

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def request(self, operation: str, body: dict[str, object] | None = None) -> dict[str, object]:
            if operation == "history.append":
                return {"ok": False, "error": "item_id_conflict"}
            if operation == "dispatch.claim":
                return {"ok": True, "data": {"items": []}}
            if operation == "history.query":
                return {"ok": True, "data": {"items": []}}
            raise AssertionError(operation)

    monkeypatch.setattr(codex_history_module, "HistoryDispatcherClient", FakeClient)
    monkeypatch.setattr(codex_history_module, "_codex_history_dispatch_account_ids", lambda *args, **kwargs: ())
    result = asyncio.run(
        dispatch_codex_history_outbox(
            store,
            instance_name="TeeBotus_Logger",
            env={"TEEBOTUS_HISTORY_DISPATCHER_MODE": "bridge", "HISTORY_DISPATCHER_SOCKET": "/tmp/dispatcher.sock"},
            now=datetime(2026, 7, 13, 12, 5, tzinfo=timezone.utc),
            limit=1,
        )
    )

    assert result["ok"] is False
    assert result["status_counts"] == {"failed": 1}
    assert result["items"][0]["reason"] == "history_dispatcher_mirror_failed"
    assert store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]["status"] == "queued"


def test_codex_history_dispatch_bridge_reports_unsafe_socket_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnexpectedClient:
        def __init__(self, *_args, **_kwargs) -> None:
            raise AssertionError("unsafe socket path must be rejected before client creation")

    monkeypatch.setattr(codex_history_module, "HistoryDispatcherClient", UnexpectedClient)
    result = asyncio.run(
        dispatch_codex_history_outbox(
            object(),
            instance_name="TeeBotus_Logger",
            env={"TEEBOTUS_HISTORY_DISPATCHER_MODE": "bridge", "HISTORY_DISPATCHER_SOCKET": "relative.sock"},
        )
    )

    assert result["ok"] is False
    assert result["status_counts"] == {"failed": 1}
    assert result["items"][0]["reason"] == "history_dispatcher_unavailable"
    assert "unsafe" in result["items"][0]["error"]


def test_codex_history_dispatch_bridge_reconciles_authoritative_local_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AccountStore(tmp_path / "accounts", "TeeBotus_Logger", provider())
    store.append_codex_history_item(
        INSTANCE_STATE_ACCOUNT_ID,
        {
            "id": "local-history-id",
            "kind": "codex_run_summary",
            "status": "queued",
            "created_at": "2026-07-13T12:00:00+00:00",
            "project": {"repo_name": "TeeBotus"},
            "version": {"semver": "1.9.384", "summary_number": 1},
            "summary_prefix": "v1.9.384 #0001",
            "codex": {"dedupe_key": "sha256:local-external"},
            "summary": {"text": "Lokaler Status wird abgeglichen."},
        },
    )

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def request(self, operation: str, body: dict[str, object] | None = None) -> dict[str, object]:
            if operation == "history.append":
                return {"ok": True, "data": {"id": "external-history-id", "deduplicated": True, "status": "queued"}}
            if operation == "dispatch.claim":
                return {
                    "ok": True,
                    "data": {
                        "items": [{
                            "id": "external-history-id",
                            "kind": "codex_run_summary",
                            "dedupe_key": "sha256:local-external",
                            "project": "/tmp/TeeBotus",
                            "payload": {"summary": {"text": "Extern bereits mit Fehlerhistorie"}},
                            "recipient_results": [{
                                "recipient_id": "old-admin",
                                "status": "failed",
                                "reason": "send_error:TimeoutError",
                            }],
                        }],
                    },
                }
            if operation == "dispatch.complete":
                return {"ok": True, "data": {"ok": True, "status": "queued"}}
            raise AssertionError(operation)

    sent_item: dict[str, object] = {}

    async def fake_send(_store, item, *_args, **kwargs):
        sent_item.update(item)
        return {"account_id": kwargs.get("account_id", "new-admin"), "status": "accepted", "channel": "telegram"}

    monkeypatch.setattr(codex_history_module, "HistoryDispatcherClient", FakeClient)
    monkeypatch.setattr(codex_history_module, "_codex_history_dispatch_account_ids", lambda *args, **kwargs: ("new-admin",))
    monkeypatch.setattr(codex_history_module, "_dispatch_codex_history_item_to_account", fake_send)

    result = asyncio.run(
        dispatch_codex_history_outbox(
            store,
            instance_name="TeeBotus_Logger",
            env={"TEEBOTUS_HISTORY_DISPATCHER_MODE": "bridge", "HISTORY_DISPATCHER_SOCKET": "/tmp/dispatcher.sock"},
            now=datetime(2026, 7, 13, 12, 5, tzinfo=timezone.utc),
        )
    )

    assert result["ok"] is False
    assert result["status_counts"] == {"delivered": 1, "failed": 1}
    assert sent_item["version"]["semver"] == "1.9.384"
    assert sent_item["summary"]["text"] == "Lokaler Status wird abgeglichen."
    persisted = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert persisted["status"] == "queued"
    assert persisted["delivery"]["attempts"] == 1
    assert persisted["status_history"][-1]["status"] == "queued"


def test_codex_history_dispatch_bridge_clears_stale_failure_after_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AccountStore(tmp_path / "accounts", "TeeBotus_Logger", provider())
    store.append_codex_history_item(
        INSTANCE_STATE_ACCOUNT_ID,
        {
            "id": "local-history-id",
            "kind": "codex_run_summary",
            "status": "queued",
            "last_reason": "send_error:TimeoutError",
            "created_at": "2026-07-13T12:00:00+00:00",
            "project": {"repo_name": "TeeBotus"},
            "codex": {"dedupe_key": "sha256:local-external"},
            "summary": {"text": "Fehler wird durch erfolgreichen Retry abgeloest."},
        },
    )

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def request(self, operation: str, body: dict[str, object] | None = None) -> dict[str, object]:
            if operation == "history.append":
                return {"ok": True, "data": {"id": "external-history-id", "deduplicated": True, "status": "delivered"}}
            if operation == "dispatch.claim":
                return {
                    "ok": True,
                    "data": {
                        "items": [{
                            "id": "external-history-id",
                            "kind": "codex_run_summary",
                            "dedupe_key": "sha256:local-external",
                            "payload": {"summary": {"text": "Externer Retry"}},
                            "recipient_results": [{
                                "recipient_id": "admin",
                                "status": "failed",
                                "reason": "send_error:TimeoutError",
                            }],
                        }],
                    },
                }
            if operation == "dispatch.complete":
                return {"ok": True, "data": {"ok": True, "status": "delivered"}}
            raise AssertionError(operation)

    async def fake_send(_store, _item, *_args, **kwargs):
        return {"account_id": kwargs.get("account_id", "admin"), "status": "accepted", "reason": "accepted", "channel": "telegram"}

    monkeypatch.setattr(codex_history_module, "HistoryDispatcherClient", FakeClient)
    monkeypatch.setattr(codex_history_module, "_codex_history_dispatch_account_ids", lambda *args, **kwargs: ("admin",))
    monkeypatch.setattr(codex_history_module, "_dispatch_codex_history_item_to_account", fake_send)

    result = asyncio.run(
        dispatch_codex_history_outbox(
            store,
            instance_name="TeeBotus_Logger",
            env={"TEEBOTUS_HISTORY_DISPATCHER_MODE": "bridge", "HISTORY_DISPATCHER_SOCKET": "/tmp/dispatcher.sock"},
            now=datetime(2026, 7, 13, 12, 5, tzinfo=timezone.utc),
        )
    )

    assert result["ok"] is True
    persisted = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert persisted["status"] == "delivered"
    assert "last_reason" not in persisted


def test_codex_history_bridge_persists_local_result_and_reply_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_git_repo(tmp_path, "bridge-local-result", version="1.9.0")
    store = AccountStore(tmp_path / "accounts", "TeeBotus_Logger", provider())
    admin_id = store.resolve_or_create_account(telegram_identity_key(777), display_label="Admin")
    store.update_identity_route(telegram_identity_key(777), channel="telegram", chat_id="777", chat_type="private", adapter_slot=1)
    authorize_codex_admin(store, admin_id)
    monkeypatch.delenv("TEEBOTUS_HISTORY_DISPATCHER_MODE", raising=False)
    item = append_codex_history_summary(
        store,
        repo_root=repo,
        title="Bridge lokal",
        bullets=["Externe und lokale IDs unterscheiden sich."],
        codex_metadata={"dedupe_key": "sha256:bridge-local-result"},
    )

    delivery_events: list[dict[str, object]] = []

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def request(self, operation: str, body: dict[str, object] | None = None) -> dict[str, object]:
            if operation == "history.append":
                return {"ok": True, "data": {"id": "external-bridge-local-result", "deduplicated": True, "status": "delivered"}}
            if operation == "dispatch.claim":
                return {
                    "ok": True,
                    "data": {
                        "items": [{
                            "id": "external-bridge-local-result",
                            "status": "delivering",
                            "kind": "codex_run_summary",
                            "dedupe_key": "sha256:bridge-local-result",
                            "payload": {"summary": {"text": "unvollstaendig"}},
                            "recipient_results": [],
                        }],
                    },
                }
            if operation == "dispatch.complete":
                return {"ok": True, "data": {"ok": True, "status": "delivered"}}
            if operation == "delivery.record":
                delivery_events.append(dict(body or {}))
                return {"ok": True, "data": {"ok": True, "event_id": body.get("event_id") if body else ""}}
            raise AssertionError(operation)

    def sender(_route: dict[str, object], _action: SendAttachment, _metadata: dict[str, object]) -> str:
        return "telegram-bridge-local-1"

    monkeypatch.setattr(codex_history_module, "HistoryDispatcherClient", FakeClient)
    result = asyncio.run(
        dispatch_codex_history_outbox(
            store,
            instance_name="TeeBotus_Logger",
            account_ids=(admin_id,),
            senders={"telegram": sender},
            env={"TEEBOTUS_HISTORY_DISPATCHER_MODE": "bridge", "HISTORY_DISPATCHER_SOCKET": "/tmp/dispatcher.sock"},
            now=datetime(2026, 7, 13, 13, 0, tzinfo=timezone.utc),
        )
    )

    assert result["ok"] is True
    dispatch_rows = store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID)
    assert any(
        row.get("codex_history_item_id") == item["id"]
        and row.get("message_ref") == "telegram-bridge-local-1"
        and row.get("account_id") == admin_id
        for row in dispatch_rows
    )
    monkeypatch.setenv("TEEBOTUS_HISTORY_DISPATCHER_MODE", "bridge")
    monkeypatch.setenv("HISTORY_DISPATCHER_SOCKET", "/tmp/dispatcher.sock")
    receipt = record_codex_history_delivery_receipt(
        store,
        instance_name="TeeBotus_Logger",
        channel="telegram",
        chat_id="777",
        message_ref="telegram-bridge-local-1",
        account_id=admin_id,
        now=datetime(2026, 7, 13, 13, 1, tzinfo=timezone.utc),
    )
    assert receipt["ok"] is True
    assert delivery_events[0]["item_id"] == "external-bridge-local-result"
    assert delivery_events[0]["event_type"] == "delivered"


def test_history_dispatcher_digest_payload_becomes_markdown_attachment() -> None:
    item = codex_history_module._history_dispatcher_item_to_legacy(
        {
            "id": "digest-1",
            "kind": "codex_history_digest",
            "project": "/home/teladi/TeeBotus",
            "created_at": "2026-07-12T21:55:15+00:00",
            "payload": {
                "summary_prefix": "digest_abc123",
                "summary_number": 1,
                "version": {"semver": "digest", "tag": "digest", "summary_number": 1},
                "summary": {
                    "title": "Codex-History-Sammelbericht: TeeBotus",
                    "markdown": "# digest_abc123 Codex-History-Sammelbericht\n\n- Original-ID: `one`\n",
                },
            },
        }
    )

    action = codex_history_module._codex_history_attachment_action(item, "42")

    assert item["summary_prefix"] == "digest_abc123"
    assert codex_history_module._codex_history_item_dispatchable(item) is True
    assert action.caption == "Release TeeBotus digest"
    assert action.filename == "TeeBotus_release_digest_0001.md"
    assert action.data.startswith(b"# digest_abc123 Codex-History-Sammelbericht")


def test_codex_history_shadow_append_mirrors_after_legacy_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_git_repo(tmp_path, "shadow-demo", version="1.9.0")
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    mirrored: list[dict[str, object]] = []

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def request(self, operation: str, body: dict[str, object]) -> dict[str, object]:
            mirrored.append({"operation": operation, **body})
            return {"ok": True, "data": {"id": body.get("id")}}

    monkeypatch.setenv("TEEBOTUS_HISTORY_DISPATCHER_MODE", "shadow")
    monkeypatch.setenv("HISTORY_DISPATCHER_SOCKET", str(tmp_path / "control.sock"))
    monkeypatch.setattr(codex_history_module, "HistoryDispatcherClient", FakeClient)
    item = append_codex_history_summary(
        store,
        repo_root=repo,
        title="Shadow",
        bullets=["Legacy bleibt lesbar."],
        status="accepted",
        codex_metadata={"dedupe_key": "sha256:session-turn-final"},
    )
    assert item["id"] == mirrored[0]["id"]
    assert mirrored[0]["operation"] == "history.append"
    assert mirrored[0]["dedupe_key"] == "sha256:session-turn-final"
    assert mirrored[0]["status"] == "accepted"
    assert store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]["id"] == item["id"]


def test_codex_history_shadow_append_reconciles_deduplicated_terminal_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_git_repo(tmp_path, "shadow-deduplicated", version="1.9.0")
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def request(self, _operation: str, _body: dict[str, object]) -> dict[str, object]:
            return {
                "ok": True,
                "data": {
                    "ok": True,
                    "id": "external-existing-id",
                    "deduplicated": True,
                    "status": "delivered",
                },
            }

    monkeypatch.setenv("TEEBOTUS_HISTORY_DISPATCHER_MODE", "shadow")
    monkeypatch.setenv("HISTORY_DISPATCHER_SOCKET", str(tmp_path / "control.sock"))
    monkeypatch.setattr(codex_history_module, "HistoryDispatcherClient", FakeClient)

    item = append_codex_history_summary(
        store,
        repo_root=repo,
        title="Dedupliziert",
        bullets=["Der externe Status ist bereits terminal."],
        codex_metadata={"dedupe_key": "sha256:already-delivered"},
    )

    persisted = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert item["id"] == persisted["id"]
    assert persisted["status"] == "delivered"
    assert persisted["delivery"]["attempts"] == 0
    assert persisted["last_reason"] == "dispatcher_deduplicated"


def test_codex_history_shadow_append_reports_inner_dispatcher_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    repo = make_git_repo(tmp_path, "shadow-inner-failure", version="1.9.0")
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def request(self, _operation: str, _body: dict[str, object]) -> dict[str, object]:
            return {"ok": True, "data": {"ok": False, "error": "append_rejected"}}

    monkeypatch.setenv("TEEBOTUS_HISTORY_DISPATCHER_MODE", "shadow")
    monkeypatch.setenv("HISTORY_DISPATCHER_SOCKET", str(tmp_path / "control.sock"))
    monkeypatch.setattr(codex_history_module, "HistoryDispatcherClient", FakeClient)

    with caplog.at_level("WARNING"):
        item = append_codex_history_summary(
            store,
            repo_root=repo,
            title="Legacy bleibt erhalten",
            bullets=["Ein innerer Dispatcherfehler darf den Legacy-Pfad nicht verbergen."],
        )

    assert item["id"] == store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]["id"]
    assert "append_rejected" in caplog.text


def test_codex_history_shadow_append_reports_missing_dispatcher_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    repo = make_git_repo(tmp_path, "shadow-missing-id", version="1.9.0")
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def request(self, _operation: str, _body: dict[str, object]) -> dict[str, object]:
            return {"ok": True, "data": {"ok": True}}

    monkeypatch.setenv("TEEBOTUS_HISTORY_DISPATCHER_MODE", "shadow")
    monkeypatch.setenv("HISTORY_DISPATCHER_SOCKET", str(tmp_path / "control.sock"))
    monkeypatch.setattr(codex_history_module, "HistoryDispatcherClient", FakeClient)

    with caplog.at_level("WARNING"):
        item = append_codex_history_summary(
            store,
            repo_root=repo,
            title="Legacy bleibt erhalten",
            bullets=["Ein erfolgreicher Append braucht eine persistierte ID."],
        )

    assert item["id"] == store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]["id"]
    assert "returned no item id" in caplog.text


def test_codex_history_shadow_append_keeps_legacy_write_on_unsafe_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_git_repo(tmp_path, "shadow-invalid-socket", version="1.9.0")
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    monkeypatch.setenv("TEEBOTUS_HISTORY_DISPATCHER_MODE", "shadow")
    monkeypatch.setenv("HISTORY_DISPATCHER_SOCKET", "relative.sock")

    item = append_codex_history_summary(
        store,
        repo_root=repo,
        title="Shadow bleibt intakt",
        bullets=["Ein fehlerhafter Dispatcher-Socket darf den Legacy-Pfad nicht abbrechen."],
    )

    persisted = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
    assert [row["id"] for row in persisted] == [item["id"]]


def test_codex_history_dispatch_uses_cross_instance_admin_route(tmp_path: Path) -> None:
    instances_dir = tmp_path / "instances"
    logger_dir = make_instance(instances_dir, "TeeBotus_Logger")
    source_dir = make_instance(instances_dir, "Bote_der_Wahrheit")
    repo = make_git_repo(tmp_path, "cross-route-demo", version="1.9.1")
    logger_store = AccountStore(logger_dir / "data" / "accounts", "TeeBotus_Logger", provider())
    source_store = AccountStore(source_dir / "data" / "accounts", "Bote_der_Wahrheit", provider())
    identity = telegram_identity_key(123)
    admin_id = source_store.resolve_or_create_account(identity, display_label="Admin")
    source_store.update_identity_route(identity, channel="telegram", chat_id="123", chat_type="private", adapter_slot=1)
    authorize_codex_admin(source_store, admin_id)
    item = append_codex_history_summary(
        logger_store,
        repo_root=repo,
        title="Cross Route",
        bullets=["TBL nutzt Adminroute aus Quellinstanz."],
        session_id="sess-cross-route",
    )
    sent: list[tuple[dict[str, object], SendAttachment, dict[str, object]]] = []

    def sender(route: dict[str, object], action: SendAttachment, metadata: dict[str, object]) -> str:
        sent.append((route, action, metadata))
        return "telegram-cross-1"

    result = asyncio.run(
        dispatch_codex_history_outbox(
            logger_store,
            instance_name="TeeBotus_Logger",
            account_ids=(admin_id,),
            senders={"telegram": sender},
            instances_dir=instances_dir,
            secret_provider=provider(),
            now=datetime(2026, 6, 19, 12, tzinfo=timezone.utc),
        )
    )

    assert result["status_counts"] == {"accepted": 1}
    assert sent
    route, action, metadata = sent[0]
    assert route["channel"] == "telegram"
    assert route["chat_id"] == "123"
    assert route["route_source_instance"] == "Bote_der_Wahrheit"
    assert action.chat_id == "123"
    assert metadata["codex_history_item_id"] == item["id"]
    persisted = logger_store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert persisted["status"] == "accepted"
    dispatch = logger_store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert dispatch["status"] == "accepted"
    assert dispatch["channel"] == "telegram"
    assert dispatch["chat_id"] == "123"
    assert dispatch["message_ref"] == "telegram-cross-1"


def test_successful_dispatch_selection_uses_result_timestamps(tmp_path: Path) -> None:
    store = AccountStore(tmp_path / "accounts", "TeeBotus_Logger", provider())
    item_id = "history-timestamp-order"
    store.append_codex_history_dispatch_result(
        INSTANCE_STATE_ACCOUNT_ID,
        {
            "codex_history_item_id": item_id,
            "account_id": "account-a",
            "status": "delivered",
            "updated_at": "2026-07-13T12:00:00+00:00",
        },
    )
    store.append_codex_history_dispatch_result(
        INSTANCE_STATE_ACCOUNT_ID,
        {
            "codex_history_item_id": item_id,
            "account_id": "account-a",
            "status": "failed",
            "updated_at": "2026-07-12T12:00:00+00:00",
        },
    )
    store.append_codex_history_dispatch_result(
        INSTANCE_STATE_ACCOUNT_ID,
        {
            "codex_history_item_id": item_id,
            "account_id": "account-b",
            "status": "delivered",
            "updated_at": "2026-07-12T12:00:00+00:00",
        },
    )
    store.append_codex_history_dispatch_result(
        INSTANCE_STATE_ACCOUNT_ID,
        {
            "codex_history_item_id": item_id,
            "account_id": "account-b",
            "status": "failed",
            "updated_at": "2026-07-13T12:00:00+00:00",
        },
    )

    successful = codex_history_module._successful_codex_history_dispatch_accounts(store, item_id)

    assert successful == {"account-a"}


def test_codex_history_dispatch_non_logger_instance_does_not_mutate_outbox(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "non-logger-dispatch-demo", version="1.9.2")
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    admin_id = store.resolve_or_create_account(telegram_identity_key(124), display_label="Admin")
    store.update_identity_route(telegram_identity_key(124), channel="telegram", chat_id="124", chat_type="private", adapter_slot=1)
    authorize_codex_admin(store, admin_id)
    item = append_codex_history_summary(store, repo_root=repo, title="Nicht TBL", bullets=["Darf nicht senden."])
    sent: list[str] = []

    result = asyncio.run(
        dispatch_codex_history_outbox(
            store,
            instance_name="Depressionsbot",
            account_ids=(admin_id,),
            senders={"telegram": lambda _route, _action, _metadata: sent.append("sent") or "msg"},
            now=datetime(2026, 6, 19, 12, tzinfo=timezone.utc),
        )
    )

    assert result["status_counts"] == {"skipped": 1}
    assert result["items"][0]["reason"] == "non_logger_dispatch_instance"
    assert sent == []
    persisted = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert persisted["id"] == item["id"]
    assert persisted["status"] == "queued"
    assert store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID) == []


def test_codex_history_acknowledge_marks_item_without_deleting_it(tmp_path: Path, capsys) -> None:
    instance_dir = make_instance(tmp_path)
    repo = make_git_repo(tmp_path, "ack-demo", version="1.8.1")
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    item = append_codex_history_summary(store, repo_root=repo, title="Ack gebaut", bullets=["Bestaetigung wird auditierbar."])

    acknowledged = acknowledge_codex_history_item(
        store,
        item["id"],
        instance_name="Depressionsbot",
        account_id="acc-admin",
        message_ref="telegram-msg-1",
        now=datetime(2026, 6, 19, 12, 30, tzinfo=timezone.utc),
    )

    assert acknowledged["ok"] is True
    assert acknowledged["item_id"] == item["id"]
    assert acknowledged["status"] == "acknowledged"
    persisted = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert persisted["id"] == item["id"]
    assert persisted["status"] == "acknowledged"
    assert persisted["delivery"]["acknowledged_at"] == "2026-06-19T12:30:00+00:00"
    assert persisted["status_history"][-1] == {
        "at": "2026-06-19T12:30:00+00:00",
        "status": "acknowledged",
        "reason": "manual_acknowledgement",
    }
    dispatch = store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert dispatch["codex_history_item_id"] == item["id"]
    assert dispatch["account_id"] == "acc-admin"
    assert dispatch["status"] == "acknowledged"
    assert dispatch["reason"] == "manual_acknowledgement"
    assert dispatch["message_ref"] == "telegram-msg-1"

    assert (
        codex_history_main(
            [
                "acknowledge",
                "--instances-dir",
                str(tmp_path),
                "--instance",
                "Depressionsbot",
                "--item-id",
                item["id"],
                "--account-id",
                "acc-admin",
                "--message-ref",
                "telegram-msg-2",
                "--format",
                "json",
            ],
            provider=provider(),
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["status"] == "acknowledged"
    persisted = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert persisted["status"] == "acknowledged"
    assert store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID)[-1]["message_ref"] == "telegram-msg-2"


def test_record_codex_history_reply_marks_dispatch_delivered_and_acknowledged(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "reply-ack-demo", version="1.8.2")
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    admin_id = store.resolve_or_create_account(telegram_identity_key(42), display_label="Admin")
    item = append_codex_history_summary(store, repo_root=repo, title="Reply Ack", bullets=["Antworten markieren die Summary."])
    store.append_codex_history_dispatch_result(
        INSTANCE_STATE_ACCOUNT_ID,
        {
            "codex_history_item_id": item["id"],
            "account_id": admin_id,
            "instance": "Depressionsbot",
            "status": "accepted",
            "channel": "telegram",
            "chat_id": "42",
            "message_ref": "101",
            "summary_prefix": item["summary_prefix"],
        },
    )

    result = record_codex_history_reply(
        store,
        instance_name="Depressionsbot",
        channel="telegram",
        chat_id="42",
        account_id=admin_id,
        reply_to_message_ref="101",
        reply_message_ref="202",
        reply_text="ok, angekommen",
        now=datetime(2026, 6, 19, 13, tzinfo=timezone.utc),
    )

    assert result["ok"] is True
    assert result["status"] == "acknowledged"
    assert result["item_id"] == item["id"]
    persisted = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert persisted["status"] == "acknowledged"
    assert persisted["delivery"]["delivered_at"] == "2026-06-19T13:00:00+00:00"
    assert persisted["delivery"]["acknowledged_at"] == "2026-06-19T13:00:00+00:00"
    assert [entry["status"] for entry in persisted["status_history"]][-2:] == ["delivered", "acknowledged"]
    dispatch_rows = store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID)
    assert [row["status"] for row in dispatch_rows] == ["accepted", "delivered", "acknowledged"]
    assert dispatch_rows[-1]["message_ref"] == "101"
    assert dispatch_rows[-1]["reply_message_ref"] == "202"
    assert dispatch_rows[-1]["reply_text_preview"] == "ok, angekommen"

    duplicate = record_codex_history_reply(
        store,
        instance_name="Depressionsbot",
        channel="telegram",
        chat_id="42",
        account_id=admin_id,
        reply_to_message_ref="101",
        reply_message_ref="202",
        reply_text="ok, angekommen erneut",
        now=datetime(2026, 6, 19, 13, 1, tzinfo=timezone.utc),
    )

    assert duplicate["ok"] is True
    assert duplicate["status"] == "acknowledged"
    assert duplicate["idempotent"] is True
    assert len(store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID)) == 3
    assert len(store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]["status_history"]) == 3


def test_record_codex_history_reply_without_reply_ref_is_idempotent(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "reply-no-ref-demo", version="1.8.3")
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    admin_id = store.resolve_or_create_account(telegram_identity_key(42), display_label="Admin")
    item = append_codex_history_summary(store, repo_root=repo, title="Reply ohne Ref", bullets=["Adapter liefert keine Reply-ID."])
    store.append_codex_history_dispatch_result(
        INSTANCE_STATE_ACCOUNT_ID,
        {
            "codex_history_item_id": item["id"],
            "account_id": admin_id,
            "instance": "Depressionsbot",
            "status": "accepted",
            "channel": "signal",
            "chat_id": "+491",
            "message_ref": "summary-1",
            "summary_prefix": item["summary_prefix"],
        },
    )

    first = record_codex_history_reply(
        store,
        instance_name="Depressionsbot",
        channel="signal",
        chat_id="+491",
        account_id=admin_id,
        reply_to_message_ref="summary-1",
        reply_text="angekommen",
        now=datetime(2026, 6, 19, 15, tzinfo=timezone.utc),
    )
    second = record_codex_history_reply(
        store,
        instance_name="Depressionsbot",
        channel="signal",
        chat_id="+491",
        account_id=admin_id,
        reply_to_message_ref="summary-1",
        reply_text="erneut verarbeitet",
        now=datetime(2026, 6, 19, 15, 1, tzinfo=timezone.utc),
    )

    assert first["idempotent"] is False
    assert second["idempotent"] is True
    assert len(store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID)) == 3
    assert len(store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]["status_history"]) == 3


def test_record_codex_history_reply_requires_account_id(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "reply-account-demo", version="1.8.4")
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    admin_id = store.resolve_or_create_account(telegram_identity_key(42), display_label="Admin")
    item = append_codex_history_summary(store, repo_root=repo, title="Reply Account", bullets=["Identitaet ist Pflicht."])
    store.append_codex_history_dispatch_result(
        INSTANCE_STATE_ACCOUNT_ID,
        {
            "codex_history_item_id": item["id"],
            "account_id": admin_id,
            "instance": "Depressionsbot",
            "status": "accepted",
            "channel": "telegram",
            "chat_id": "42",
            "message_ref": "101",
            "summary_prefix": item["summary_prefix"],
        },
    )

    result = record_codex_history_reply(
        store,
        instance_name="Depressionsbot",
        channel="telegram",
        chat_id="42",
        reply_to_message_ref="101",
        reply_message_ref="202",
    )

    assert result == {"ok": False, "status": "not_found", "reason": "missing_account_id"}
    assert store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]["status"] == "queued"
    assert len(store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID)) == 1


def test_record_codex_history_delivery_receipt_marks_dispatch_delivered_only(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "receipt-demo", version="1.8.3")
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    admin_id = store.resolve_or_create_account(telegram_identity_key(42), display_label="Admin")
    item = append_codex_history_summary(store, repo_root=repo, title="Native Receipt", bullets=["Receipts markieren Zustellung."])
    store.append_codex_history_dispatch_result(
        INSTANCE_STATE_ACCOUNT_ID,
        {
            "codex_history_item_id": item["id"],
            "account_id": admin_id,
            "instance": "Depressionsbot",
            "status": "accepted",
            "channel": "matrix",
            "chat_id": "!room:test",
            "message_ref": "$event-1",
            "summary_prefix": item["summary_prefix"],
        },
    )

    result = record_codex_history_delivery_receipt(
        store,
        instance_name="Depressionsbot",
        channel="matrix",
        chat_id="!room:test",
        account_id=admin_id,
        message_ref="$event-1",
        receipt_type="read",
        now=datetime(2026, 6, 19, 14, tzinfo=timezone.utc),
    )

    assert result["ok"] is True
    assert result["status"] == "delivered"
    assert result["item_id"] == item["id"]
    persisted = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert persisted["status"] == "delivered"
    assert persisted["delivery"]["delivered_at"] == "2026-06-19T14:00:00+00:00"
    assert persisted["delivery"]["acknowledged_at"] == ""
    assert persisted["status_history"][-1] == {
        "at": "2026-06-19T14:00:00+00:00",
        "status": "delivered",
        "reason": "matrix_read_receipt",
    }
    dispatch_rows = store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID)
    assert [row["status"] for row in dispatch_rows] == ["accepted", "delivered"]
    assert dispatch_rows[-1]["message_ref"] == "$event-1"
    assert dispatch_rows[-1]["receipt_type"] == "read"

    duplicate = record_codex_history_delivery_receipt(
        store,
        instance_name="Depressionsbot",
        channel="matrix",
        chat_id="!room:test",
        account_id=admin_id,
        message_ref="$event-1",
        receipt_type="read",
        now=datetime(2026, 6, 19, 14, 1, tzinfo=timezone.utc),
    )
    weaker = record_codex_history_delivery_receipt(
        store,
        instance_name="Depressionsbot",
        channel="matrix",
        chat_id="!room:test",
        account_id=admin_id,
        message_ref="$event-1",
        receipt_type="viewed",
        now=datetime(2026, 6, 19, 14, 2, tzinfo=timezone.utc),
    )

    assert duplicate["idempotent"] is True
    assert weaker["idempotent"] is True
    assert len(store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID)) == 2
    assert len(store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]["status_history"]) == 2


def test_record_codex_history_delivery_receipt_keeps_routes_separate(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "receipt-route-demo", version="1.8.4")
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    admin_id = store.resolve_or_create_account(telegram_identity_key(42), display_label="Admin")
    item = append_codex_history_summary(store, repo_root=repo, title="Route Receipt", bullets=["IDs koennen kanalweise kollidieren."])
    for channel, chat_id in (("telegram", "42"), ("signal", "+491")):
        store.append_codex_history_dispatch_result(
            INSTANCE_STATE_ACCOUNT_ID,
            {
                "codex_history_item_id": item["id"],
                "account_id": admin_id,
                "instance": "Depressionsbot",
                "status": "accepted",
                "channel": channel,
                "chat_id": chat_id,
                "message_ref": "101",
                "summary_prefix": item["summary_prefix"],
            },
        )

    telegram_result = record_codex_history_delivery_receipt(
        store,
        instance_name="Depressionsbot",
        channel="telegram",
        chat_id="42",
        account_id=admin_id,
        message_ref="101",
        now=datetime(2026, 6, 19, 16, tzinfo=timezone.utc),
    )
    signal_result = record_codex_history_delivery_receipt(
        store,
        instance_name="Depressionsbot",
        channel="signal",
        chat_id="+491",
        account_id=admin_id,
        message_ref="101",
        now=datetime(2026, 6, 19, 16, 1, tzinfo=timezone.utc),
    )

    assert telegram_result["idempotent"] is False
    assert signal_result["idempotent"] is False
    rows = store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID)
    delivered = [row for row in rows if row.get("status") == "delivered"]
    assert {(row["channel"], row["chat_id"]) for row in delivered} == {("telegram", "42"), ("signal", "+491")}


def test_record_codex_history_delivery_receipt_keeps_adapter_slots_separate(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "receipt-slot-demo", version="1.8.5")
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    admin_id = store.resolve_or_create_account(telegram_identity_key(42), display_label="Admin")
    first = append_codex_history_summary(store, repo_root=repo, title="Slot One", bullets=["Slot 1."])
    second = append_codex_history_summary(store, repo_root=repo, title="Slot Two", bullets=["Slot 2."])
    for item_id, adapter_slot in ((second["id"], 2), (first["id"], 1)):
        store.append_codex_history_dispatch_result(
            INSTANCE_STATE_ACCOUNT_ID,
            {
                "codex_history_item_id": item_id,
                "account_id": admin_id,
                "instance": "Depressionsbot",
                "status": "accepted",
                "channel": "telegram",
                "chat_id": "42",
                "message_ref": "101",
                "adapter_slot": adapter_slot,
            },
        )

    result = record_codex_history_delivery_receipt(
        store,
        instance_name="Depressionsbot",
        channel="telegram",
        chat_id="42",
        account_id=admin_id,
        adapter_slot=2,
        message_ref="101",
        now=datetime(2026, 6, 19, 16, tzinfo=timezone.utc),
    )

    assert result["item_id"] == second["id"]
    assert store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]["status"] == "queued"
    assert store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[1]["status"] == "delivered"


def test_record_codex_history_delivery_receipt_requires_account_id(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "receipt-account-demo", version="1.8.5")
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    admin_id = store.resolve_or_create_account(telegram_identity_key(42), display_label="Admin")
    item = append_codex_history_summary(store, repo_root=repo, title="Receipt Account", bullets=["Receipt braucht Identitaet."])
    store.append_codex_history_dispatch_result(
        INSTANCE_STATE_ACCOUNT_ID,
        {
            "codex_history_item_id": item["id"],
            "account_id": admin_id,
            "instance": "Depressionsbot",
            "status": "accepted",
            "channel": "telegram",
            "chat_id": "42",
            "message_ref": "101",
            "summary_prefix": item["summary_prefix"],
        },
    )

    result = record_codex_history_delivery_receipt(
        store,
        instance_name="Depressionsbot",
        channel="telegram",
        chat_id="42",
        message_ref="101",
    )

    assert result == {"ok": False, "status": "not_found", "reason": "missing_account_id"}
    assert store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]["status"] == "queued"
    assert len(store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID)) == 1


def test_record_codex_history_delivery_receipt_does_not_downgrade_acknowledged_item(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "receipt-after-ack-demo", version="1.8.4")
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    admin_id = store.resolve_or_create_account(telegram_identity_key(43), display_label="Admin")
    item = append_codex_history_summary(store, repo_root=repo, title="Ack bleibt", bullets=["Spaete Receipts duerfen nicht downgraden."])
    store.append_codex_history_dispatch_result(
        INSTANCE_STATE_ACCOUNT_ID,
        {
            "codex_history_item_id": item["id"],
            "account_id": admin_id,
            "instance": "Depressionsbot",
            "status": "accepted",
            "channel": "signal",
            "chat_id": "+491",
            "message_ref": "1718798400000",
            "summary_prefix": item["summary_prefix"],
        },
    )
    acknowledge_codex_history_item(
        store,
        item["id"],
        instance_name="Depressionsbot",
        account_id=admin_id,
        message_ref="1718798400000",
        now=datetime(2026, 6, 19, 14, 15, tzinfo=timezone.utc),
    )

    result = record_codex_history_delivery_receipt(
        store,
        instance_name="Depressionsbot",
        channel="signal",
        chat_id="+491",
        account_id=admin_id,
        message_ref="1718798400000",
        receipt_type="viewed",
        now=datetime(2026, 6, 19, 14, 20, tzinfo=timezone.utc),
    )

    assert result["ok"] is True
    assert result["status"] == "acknowledged"
    persisted = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert persisted["status"] == "acknowledged"
    assert persisted["delivery"]["acknowledged_at"] == "2026-06-19T14:15:00+00:00"
    assert persisted["status_history"][-1]["status"] == "acknowledged"
    assert store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID)[-1]["receipt_type"] == "viewed"


def test_codex_history_cli_receipt_marks_matching_dispatch_delivered(tmp_path: Path, capsys) -> None:
    instance_dir = make_instance(tmp_path)
    repo = make_git_repo(tmp_path, "receipt-cli-demo", version="1.8.5")
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", provider())
    admin_id = store.resolve_or_create_account(telegram_identity_key(44), display_label="Admin")
    item = append_codex_history_summary(store, repo_root=repo, title="CLI Receipt", bullets=["Receipt CLI markiert delivered."])
    store.append_codex_history_dispatch_result(
        INSTANCE_STATE_ACCOUNT_ID,
        {
            "codex_history_item_id": item["id"],
            "account_id": admin_id,
            "instance": "Depressionsbot",
            "status": "accepted",
            "channel": "matrix",
            "chat_id": "!room:cli",
            "message_ref": "$event-cli",
            "summary_prefix": item["summary_prefix"],
        },
    )

    assert (
        codex_history_main(
            [
                "receipt",
                "--instances-dir",
                str(tmp_path),
                "--instance",
                "Depressionsbot",
                "--channel",
                "matrix",
                "--chat-id",
                "!room:cli",
                "--message-ref",
                "$event-cli",
                "--account-id",
                admin_id,
                "--receipt-type",
                "read",
                "--format",
                "json",
            ],
            provider=provider(),
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["status"] == "delivered"
    persisted = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert persisted["status"] == "delivered"
    assert store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID)[-1]["reason"] == "matrix_read_receipt"


def test_record_codex_history_reply_ignores_unmatched_message_ref(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "reply-miss-demo", version="1.8.2")
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    item = append_codex_history_summary(store, repo_root=repo, title="Reply Miss", bullets=["Fremde Replys bleiben unberuehrt."])

    result = record_codex_history_reply(
        store,
        instance_name="Depressionsbot",
        channel="telegram",
        chat_id="42",
        account_id="unknown-account",
        reply_to_message_ref="999",
        reply_message_ref="202",
        reply_text="ok",
    )

    assert result == {"ok": False, "status": "not_found", "reason": "no_matching_dispatch"}
    persisted = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert persisted["id"] == item["id"]
    assert persisted["status"] == "queued"
    assert store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID) == []


def test_codex_history_dispatch_dry_run_does_not_mutate_outbox(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "dry-run-demo", version="1.0.1")
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    admin_id = store.resolve_or_create_account(telegram_identity_key(7), display_label="Admin")
    store.update_identity_route(telegram_identity_key(7), channel="telegram", chat_id="7", chat_type="private", adapter_slot=1)
    authorize_codex_admin(store, admin_id)
    append_codex_history_summary(store, repo_root=repo, title="Dry Run", bullets=["Nur anzeigen."])

    result = asyncio.run(
        dispatch_codex_history_outbox(
            store,
            instance_name="TeeBotus_Logger",
            account_ids=(admin_id,),
            senders={"telegram": lambda _route, _action, _metadata: "must-not-run"},
            dry_run=True,
            now=datetime(2026, 6, 19, 12, tzinfo=timezone.utc),
        )
    )

    assert result["dry_run"] is True
    assert result["status_counts"] == {"would_send": 1}
    assert store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]["status"] == "queued"
    assert store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID) == []


def test_codex_history_dispatch_filters_explicit_non_admin_account(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "non-admin-dispatch-demo", version="1.0.2")
    store = AccountStore(tmp_path / "accounts", "TeeBotus_Logger", provider())
    account_id = store.resolve_or_create_account(telegram_identity_key(70), display_label="Nichtadmin")
    store.update_identity_route(telegram_identity_key(70), channel="telegram", chat_id="70", chat_type="private", adapter_slot=1)
    item = append_codex_history_summary(store, repo_root=repo, title="Nichtadmin", bullets=["Darf nicht senden."])
    sent: list[str] = []

    result = asyncio.run(
        dispatch_codex_history_outbox(
            store,
            instance_name="TeeBotus_Logger",
            account_ids=(account_id,),
            senders={"telegram": lambda _route, _action, _metadata: sent.append("sent") or "msg"},
            now=datetime(2026, 6, 19, 12, tzinfo=timezone.utc),
        )
    )

    assert result["status_counts"] == {"skipped": 1}
    assert result["items"][0]["reason"] == "no_recipient_accounts"
    assert sent == []
    persisted = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert persisted["id"] == item["id"]
    assert persisted["status"] == "skipped"
    assert store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID)[0]["account_id"] == ""


def test_codex_history_dispatch_sends_once_per_admin_account(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "once-per-admin-demo", version="1.0.3")
    store = AccountStore(tmp_path / "accounts", "TeeBotus_Logger", provider())
    admin_id = store.resolve_or_create_account(telegram_identity_key(71), display_label="Admin")
    store.update_identity_route(telegram_identity_key(71), channel="telegram", chat_id="71", chat_type="private", adapter_slot=1)
    authorize_codex_admin(store, admin_id)
    append_codex_history_summary(store, repo_root=repo, title="Einmal", bullets=["Nur einmal pro Account."])
    sent: list[str] = []

    result = asyncio.run(
        dispatch_codex_history_outbox(
            store,
            instance_name="TeeBotus_Logger",
            account_ids=(admin_id, admin_id.upper(), admin_id),
            senders={"telegram": lambda _route, _action, _metadata: sent.append("sent") or "msg"},
            now=datetime(2026, 6, 19, 12, tzinfo=timezone.utc),
        )
    )

    assert result["status_counts"] == {"accepted": 1}
    assert sent == ["sent"]
    dispatch_rows = store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID)
    assert len(dispatch_rows) == 1
    assert dispatch_rows[0]["account_id"] == admin_id


def test_render_dispatch_report_formats_empty_status_counts_as_none() -> None:
    rendered = _render_dispatch_report(
        {
            "dry_run": False,
            "instances": [
                {
                    "instance": "TeeBotus_Logger",
                    "status_counts": {},
                    "items": [],
                }
            ],
        }
    )

    assert "statuses: none" in rendered


def test_codex_history_dispatch_cli_defaults_to_unlimited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_instance(tmp_path)
    limits: list[int] = []

    async def fake_dispatch(_store, **kwargs):
        limits.append(int(kwargs["limit"]))
        return {"ok": True, "dry_run": True, "status_counts": {}, "items": []}

    monkeypatch.setattr(codex_history_module, "dispatch_codex_history_outbox", fake_dispatch)

    result = codex_history_main(
        [
            "dispatch",
            "--instances-dir",
            str(tmp_path),
            "--instance",
            "Depressionsbot",
            "--dry-run",
            "--format",
            "json",
        ]
    )

    assert result == 0
    assert limits == [0]
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True


def test_codex_history_dispatch_marks_missing_sender_failed_without_deleting_item(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "missing-sender-demo", version="1.0.2")
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    admin_id = store.resolve_or_create_account(telegram_identity_key(8), display_label="Admin")
    store.update_identity_route(telegram_identity_key(8), channel="telegram", chat_id="8", chat_type="private", adapter_slot=1)
    authorize_codex_admin(store, admin_id)
    item = append_codex_history_summary(store, repo_root=repo, title="Missing Sender", bullets=["Fehler bleibt auditierbar."])

    result = asyncio.run(
        dispatch_codex_history_outbox(
            store,
            instance_name="TeeBotus_Logger",
            account_ids=(admin_id,),
            senders={},
            now=datetime(2026, 6, 19, 12, tzinfo=timezone.utc),
        )
    )

    assert result["status_counts"] == {"failed": 1}
    persisted = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert persisted["id"] == item["id"]
    assert persisted["status"] == "failed"
    assert persisted["last_reason"] == "missing_sender:telegram"
    dispatch = store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert dispatch["status"] == "failed"
    assert dispatch["reason"] == "missing_sender:telegram"


def test_codex_history_dispatch_requeues_transient_sender_errors(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "retry-sender-demo", version="1.0.3")
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    admin_id = store.resolve_or_create_account(telegram_identity_key(9), display_label="Admin")
    store.update_identity_route(telegram_identity_key(9), channel="telegram", chat_id="9", chat_type="private", adapter_slot=1)
    authorize_codex_admin(store, admin_id)
    item = append_codex_history_summary(store, repo_root=repo, title="Retry Sender", bullets=["Transienter Fehler."])

    def failing_sender(_route: dict[str, object], _action: SendAttachment, _metadata: dict[str, object]) -> str:
        raise RuntimeError("temporary network issue")

    result = asyncio.run(
        dispatch_codex_history_outbox(
            store,
            instance_name="TeeBotus_Logger",
            account_ids=(admin_id,),
            senders={"telegram": failing_sender},
            now=datetime(2026, 6, 19, 12, tzinfo=timezone.utc),
        )
    )

    assert result["ok"] is False
    assert result["status_counts"] == {"failed": 1}
    persisted = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert persisted["id"] == item["id"]
    assert persisted["status"] == "queued"
    assert persisted["delivery"]["attempts"] == 1
    assert persisted["last_reason"].startswith("send_error:RuntimeError")
    dispatch = store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert dispatch["status"] == "failed"
    assert dispatch["reason"].startswith("send_error:RuntimeError")


def test_codex_history_dispatch_retries_failed_admin_without_duplicate_success(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "mixed-admin-dispatch-demo", version="1.0.35")
    store = AccountStore(tmp_path / "accounts", "TeeBotus_Logger", provider())
    first_admin = store.resolve_or_create_account(telegram_identity_key(91), display_label="Admin 1")
    second_admin = store.resolve_or_create_account(telegram_identity_key(92), display_label="Admin 2")
    store.update_identity_route(telegram_identity_key(91), channel="telegram", chat_id="91", chat_type="private", adapter_slot=1)
    store.update_identity_route(telegram_identity_key(92), channel="telegram", chat_id="92", chat_type="private", adapter_slot=1)
    authorize_codex_admin(store, first_admin)
    authorize_codex_admin(store, second_admin)
    item = append_codex_history_summary(store, repo_root=repo, title="Mixed Admins", bullets=["Ein Erfolg, ein transienter Fehler."])
    sent_chat_ids: list[str] = []

    def mixed_sender(route: dict[str, object], _action: SendAttachment, _metadata: dict[str, object]) -> str:
        chat_id = str(route.get("chat_id") or "")
        sent_chat_ids.append(chat_id)
        if chat_id == "92":
            raise RuntimeError("temporary network issue")
        return "msg-91"

    first_result = asyncio.run(
        dispatch_codex_history_outbox(
            store,
            instance_name="TeeBotus_Logger",
            account_ids=(first_admin, second_admin),
            senders={"telegram": mixed_sender},
            now=datetime(2026, 6, 19, 12, tzinfo=timezone.utc),
        )
    )

    assert first_result["ok"] is False
    assert first_result["status_counts"] == {"accepted": 1, "failed": 1}
    assert store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]["status"] == "queued"
    assert store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]["last_reason"].startswith("send_error:")

    sent_chat_ids.clear()

    def succeeding_sender(route: dict[str, object], _action: SendAttachment, _metadata: dict[str, object]) -> str:
        sent_chat_ids.append(str(route.get("chat_id") or ""))
        return "msg-92"

    second_result = asyncio.run(
        dispatch_codex_history_outbox(
            store,
            instance_name="TeeBotus_Logger",
            account_ids=(first_admin, second_admin),
            senders={"telegram": succeeding_sender},
            now=datetime(2026, 6, 19, 12, 1, tzinfo=timezone.utc),
        )
    )

    assert second_result["status_counts"] == {"accepted": 2}
    assert sent_chat_ids == ["92"]
    persisted = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert persisted["id"] == item["id"]
    assert persisted["status"] == "accepted"
    assert persisted["delivery"]["attempts"] == 2


def test_codex_history_dispatch_ignores_fresh_in_flight_item(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "fresh-in-flight-demo", version="1.0.4")
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    admin_id = store.resolve_or_create_account(telegram_identity_key(10), display_label="Admin")
    store.update_identity_route(telegram_identity_key(10), channel="telegram", chat_id="10", chat_type="private", adapter_slot=1)
    authorize_codex_admin(store, admin_id)
    item = append_codex_history_summary(store, repo_root=repo, title="Fresh In Flight", bullets=["Laeuft gerade."])
    rows = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
    rows[0]["status"] = "dispatching"
    rows[0]["updated_at"] = "2026-06-19T12:10:00+00:00"
    rows[0]["delivery"]["last_attempt_at"] = "2026-06-19T12:10:00+00:00"
    store.write_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID, rows)

    sent: list[str] = []
    result = asyncio.run(
        dispatch_codex_history_outbox(
            store,
            instance_name="TeeBotus_Logger",
            account_ids=(admin_id,),
            senders={"telegram": lambda _route, _action, _metadata: sent.append("sent") or "msg"},
            now=datetime(2026, 6, 19, 12, 16, tzinfo=timezone.utc),
        )
    )

    assert result["items"] == []
    assert sent == []
    persisted = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert persisted["id"] == item["id"]
    assert persisted["status"] == "dispatching"


def test_codex_history_dispatch_reclaims_stale_in_flight_item_before_newer_queued(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "stale-in-flight-demo", version="1.0.5")
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    admin_id = store.resolve_or_create_account(telegram_identity_key(11), display_label="Admin")
    store.update_identity_route(telegram_identity_key(11), channel="telegram", chat_id="11", chat_type="private", adapter_slot=1)
    authorize_codex_admin(store, admin_id)
    stale = append_codex_history_summary(store, repo_root=repo, title="Stale In Flight", bullets=["Claim hing fest."])
    newer = append_codex_history_summary(store, repo_root=repo, title="Newer Queued", bullets=["Normale Queue."])
    rows = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
    rows[0]["status"] = "dispatching"
    rows[0]["created_at"] = "2026-06-19T12:00:00+00:00"
    rows[0]["updated_at"] = "2026-06-19T12:00:00+00:00"
    rows[0]["delivery"]["last_attempt_at"] = "2026-06-19T12:00:00+00:00"
    rows[1]["created_at"] = "2026-06-19T12:20:00+00:00"
    rows[1]["updated_at"] = "2026-06-19T12:20:00+00:00"
    store.write_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID, rows)

    sent_ids: list[str] = []

    def sender(_route: dict[str, object], _action: SendAttachment, metadata: dict[str, object]) -> str:
        sent_ids.append(str(metadata["codex_history_item_id"]))
        return f"msg-{len(sent_ids)}"

    result = asyncio.run(
        dispatch_codex_history_outbox(
            store,
            instance_name="TeeBotus_Logger",
            account_ids=(admin_id,),
            senders={"telegram": sender},
            now=datetime(2026, 6, 19, 12, 16, tzinfo=timezone.utc),
            limit=1,
        )
    )

    assert result["status_counts"] == {"accepted": 1}
    assert sent_ids == [stale["id"]]
    persisted = {row["id"]: row for row in store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)}
    assert persisted[stale["id"]]["status"] == "accepted"
    assert persisted[newer["id"]]["status"] == "queued"


def test_codex_history_dispatch_atomically_claims_item_across_concurrent_dispatchers(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "concurrent-dispatch-demo", version="1.0.6")
    store = AccountStore(tmp_path / "accounts", "TeeBotus_Logger", provider())
    admin_id = store.resolve_or_create_account(telegram_identity_key(12), display_label="Admin")
    store.update_identity_route(telegram_identity_key(12), channel="telegram", chat_id="12", chat_type="private", adapter_slot=1)
    authorize_codex_admin(store, admin_id)
    item = append_codex_history_summary(store, repo_root=repo, title="Concurrent", bullets=["Nur einmal senden."])
    first_sender_started = asyncio.Event()
    release_first_sender = asyncio.Event()
    sent_ids: list[str] = []

    async def sender(_route: dict[str, object], _action: SendAttachment, metadata: dict[str, object]) -> str:
        sent_ids.append(str(metadata["codex_history_item_id"]))
        first_sender_started.set()
        await release_first_sender.wait()
        return "msg-1"

    async def run() -> tuple[dict[str, Any], dict[str, Any]]:
        now = datetime(2026, 6, 19, 12, tzinfo=timezone.utc)
        first = asyncio.create_task(
            dispatch_codex_history_outbox(
                store,
                instance_name="TeeBotus_Logger",
                account_ids=(admin_id,),
                senders={"telegram": sender},
                now=now,
            )
        )
        await first_sender_started.wait()
        second = asyncio.create_task(
            dispatch_codex_history_outbox(
                store,
                instance_name="TeeBotus_Logger",
                account_ids=(admin_id,),
                senders={"telegram": sender},
                now=now,
            )
        )
        second_result = await second
        release_first_sender.set()
        first_result = await first
        return first_result, second_result

    first_result, second_result = asyncio.run(run())

    assert first_result["status_counts"] == {"accepted": 1}
    assert second_result["items"] == []
    assert sent_ids == [item["id"]]
    persisted = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert persisted["status"] == "accepted"
    assert persisted["delivery"]["attempts"] == 1


def test_import_codex_session_file_creates_redacted_deduped_history_item(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "watch-demo", version="2.1.0")
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    fake_key = "sk-" + "svcacct-" + ("b" * 48)
    session_file = write_codex_session(
        tmp_path / "sessions" / "rollout-1.jsonl",
        repo=repo,
        final_text=f"Watcher import gebaut.\n- pytest tests/test_codex_history.py lief.\n- Secret {fake_key} darf nicht landen.",
    )

    first = import_codex_session_file(store, session_file)
    second = import_codex_session_file(store, session_file)

    assert first["status"] == "imported"
    assert second["status"] == "duplicate"
    rows = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
    assert len(rows) == 1
    item = rows[0]
    assert item["source"] == "codex_session_watcher"
    assert item["summary_prefix"] == "v2.1.0 #0001"
    assert item["codex"]["session_id"] == "sess-1"
    assert item["codex"]["turn_id"] == "turn-1"
    assert item["codex"]["source_path_hash"].startswith("sha256:")
    assert item["codex"]["dedupe_key"].startswith("sha256:")
    assert fake_key not in item["summary"]["markdown"]
    assert "<redacted:openai-key>" in item["summary"]["markdown"]
    assert item["summary"]["tests"] == ["pytest tests/test_codex_history.py"]


def test_import_codex_session_file_skips_when_no_assistant_final_text(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "empty-session-demo", version="1.0.0")
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    session_file = tmp_path / "sessions" / "empty.jsonl"
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text(
        json.dumps({"type": "session_meta", "payload": {"id": "sess-empty", "cwd": str(repo)}}) + "\n",
        encoding="utf-8",
    )

    result = import_codex_session_file(store, session_file)

    assert result["status"] == "skipped"
    assert result["reason"] == "missing_final_text"
    assert store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID) == []


def test_import_codex_session_roots_imports_recent_large_directory_session_from_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_git_repo(tmp_path, "active-large-session-demo", version="1.0.0")
    store = AccountStore(tmp_path / "accounts", "TeeBotus_Logger", provider())
    session_file = tmp_path / "sessions" / "active-large.jsonl"
    rows = [
        {"type": "session_meta", "payload": {"id": "sess-active-large", "cwd": str(repo)}},
        {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "call-1", "output": "x" * 2048}},
        {"type": "turn_context", "payload": {"turn_id": "turn-active-large"}},
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "phase": "final_answer",
                "content": [{"type": "output_text", "text": "Aktive grosse Summary wird aus dem Tail importiert."}],
            },
        },
    ]
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    monkeypatch.setattr(codex_history_module, "CODEX_SESSION_LARGE_FILE_THRESHOLD_BYTES", 128)
    monkeypatch.setattr(codex_history_module, "CODEX_SESSION_LARGE_FILE_HEAD_BYTES", 256)
    monkeypatch.setattr(codex_history_module, "CODEX_SESSION_LARGE_FILE_TAIL_BYTES", 1024)

    directory_result = import_codex_session_roots(store, (session_file.parent,), limit=10)

    assert directory_result["status_counts"] == {"imported": 1}
    item = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert item["codex"]["session_id"] == "sess-active-large"
    assert item["codex"]["turn_id"] == "turn-active-large"
    assert item["summary"]["title"] == "Aktive grosse Summary wird aus dem Tail importiert."

    explicit_result = import_codex_session_file(store, session_file)

    assert explicit_result["status"] == "duplicate"


def test_import_codex_session_file_reads_large_logs_from_head_and_tail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = make_git_repo(tmp_path, "large-tail-session-demo", version="1.0.0")
    store = AccountStore(tmp_path / "accounts", "TeeBotus_Logger", provider())
    session_file = tmp_path / "sessions" / "large-tail.jsonl"
    rows = [
        {"type": "session_meta", "payload": {"id": "sess-large-tail", "cwd": str(repo)}},
        {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "call-1", "output": "x" * 2048}},
        {"type": "turn_context", "payload": {"turn_id": "turn-large-tail"}},
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "phase": "final_answer",
                "content": [{"type": "output_text", "text": "Tail Summary importiert."}],
            },
        },
    ]
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    monkeypatch.setattr(codex_history_module, "CODEX_SESSION_LARGE_FILE_THRESHOLD_BYTES", 128)
    monkeypatch.setattr(codex_history_module, "CODEX_SESSION_LARGE_FILE_HEAD_BYTES", 256)
    monkeypatch.setattr(codex_history_module, "CODEX_SESSION_LARGE_FILE_TAIL_BYTES", 1024)

    result = import_codex_session_file(store, session_file)

    assert result["status"] == "imported"
    item = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)[0]
    assert item["codex"]["session_id"] == "sess-large-tail"
    assert item["codex"]["turn_id"] == "turn-large-tail"
    assert item["summary"]["title"] == "Tail Summary importiert."


def test_import_codex_session_file_skips_commentary_only_assistant_updates(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "commentary-only-session-demo", version="1.0.1")
    store = AccountStore(tmp_path / "accounts", "TeeBotus_Logger", provider())
    session_file = tmp_path / "sessions" / "commentary.jsonl"
    rows = [
        {"type": "session_meta", "payload": {"id": "sess-commentary-only", "cwd": str(repo)}},
        {"type": "turn_context", "payload": {"turn_id": "turn-commentary-only"}},
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "phase": "commentary",
                "content": [{"type": "output_text", "text": "Ich pruefe gerade nur den Zwischenstand."}],
            },
        },
    ]
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")

    result = import_codex_session_file(store, session_file)

    assert result["status"] == "skipped"
    assert result["reason"] == "missing_final_text"
    assert store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID) == []


def test_import_codex_session_file_prefers_final_answer_over_commentary(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "final-phase-session-demo", version="1.0.2")
    store = AccountStore(tmp_path / "accounts", "TeeBotus_Logger", provider())
    session_file = tmp_path / "sessions" / "final-answer.jsonl"
    rows = [
        {"type": "session_meta", "payload": {"id": "sess-final-phase", "cwd": str(repo)}},
        {"type": "turn_context", "payload": {"turn_id": "turn-final-phase"}},
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": '<codex_internal_context source="goal"><objective>Repo-Logikfehler finden</objective></codex_internal_context>Bitte Summary-Import pruefen.',
                    }
                ],
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "phase": "commentary",
                "content": [{"type": "output_text", "text": "Zwischenstand darf nicht Summary werden."}],
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "phase": "final_answer",
                "content": [{"type": "output_text", "text": "Finale Summary soll importiert werden."}],
            },
        },
    ]
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")

    result = import_codex_session_file(store, session_file)

    assert result["status"] == "imported"
    rows = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
    assert len(rows) == 1
    assert rows[0]["summary"]["title"] == "Finale Summary soll importiert werden."
    assert rows[0]["summary"]["bullets"] == ["Finale Summary soll importiert werden."]
    assert rows[0]["codex"]["goal"] == "Repo-Logikfehler finden"
    assert rows[0]["codex"]["auftrag"] == "Bitte Summary-Import pruefen."
    assert rows[0]["codex"]["intermediate_messages"][0]["text"] == "Zwischenstand darf nicht Summary werden."
    assert "- Goal: `Repo-Logikfehler finden`" in rows[0]["summary"]["markdown"]
    assert "- Auftrag: `Bitte Summary-Import pruefen.`" in rows[0]["summary"]["markdown"]
    assert "## Arbeitsverlauf" in rows[0]["summary"]["markdown"]
    assert "- Zwischenantworten: `1`" in rows[0]["summary"]["markdown"]
    assert "### Kommentar 1" in rows[0]["summary"]["markdown"]
    assert "```text\nZwischenstand darf nicht Summary werden.\n```" in rows[0]["summary"]["markdown"]


def test_import_codex_session_file_imports_each_final_turn_from_explicit_file(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "multi-final-session-demo", version="1.0.3")
    store = AccountStore(tmp_path / "accounts", "TeeBotus_Logger", provider())
    session_file = tmp_path / "sessions" / "multi-final.jsonl"
    rows = [
        {"type": "session_meta", "payload": {"id": "sess-multi-final", "cwd": str(repo)}},
        {"type": "turn_context", "payload": {"turn_id": "turn-one"}},
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "phase": "final_answer",
                "content": [{"type": "output_text", "text": "Erste finale Summary."}],
            },
        },
        {"type": "turn_context", "payload": {"turn_id": "turn-two"}},
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "phase": "final_answer",
                "content": [{"type": "output_text", "text": "Zweite finale Summary."}],
            },
        },
    ]
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")

    first = import_codex_session_file(store, session_file)
    second = import_codex_session_file(store, session_file)

    assert first["status_counts"] == {"imported": 2}
    assert second["status_counts"] == {"duplicate": 2}
    persisted = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
    assert [(row["codex"]["turn_id"], row["summary"]["title"], row["summary_prefix"]) for row in persisted] == [
        ("turn-one", "Erste finale Summary.", "v1.0.3 #0001"),
        ("turn-two", "Zweite finale Summary.", "v1.0.3 #0002"),
    ]
    assert "## Verknuepfte Summaries" in persisted[0]["summary"]["markdown"]
    assert "Naechste im Repo" in persisted[0]["summary"]["markdown"]
    assert persisted[1]["id"] in persisted[0]["summary"]["markdown"]
    assert "Vorherige im Repo" in persisted[1]["summary"]["markdown"]
    assert persisted[0]["id"] in persisted[1]["summary"]["markdown"]
    assert "## Mermaid-Kontext" in persisted[0]["summary"]["markdown"]
    assert "flowchart " in persisted[0]["summary"]["markdown"]
    assert 'subgraph signals["Signale"]' in persisted[0]["summary"]["markdown"]
    assert 'subgraph scope["Umfang"]' in persisted[0]["summary"]["markdown"]
    assert "Status-Historie:" in persisted[0]["summary"]["markdown"]


def test_codex_history_mermaid_context_varies_layout_and_shows_summary_signals(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "mermaid-context-demo", version="1.9.5")
    store = AccountStore(tmp_path / "accounts", "TeeBotus_Logger", provider())
    security = append_codex_history_summary(
        store,
        repo_root=repo,
        title="Secret Guard",
        bullets=["Admin Secret Guard repariert."],
        changed_files=["TeeBotus/runtime/config.py", "TeeBotus/runtime/engine.py"],
    )
    tested = append_codex_history_summary(
        store,
        repo_root=repo,
        title="Dependency Test",
        bullets=["pytest und Dependency-Checks gepinnt."],
        changed_files=["pyproject.toml"],
        tests=["pytest tests/test_codex_history.py"],
    )

    rows = {row["id"]: row for row in store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)}
    security_markdown = rows[security["id"]]["summary"]["markdown"]
    tested_markdown = rows[tested["id"]]["summary"]["markdown"]

    assert "flowchart BT" in security_markdown
    assert "flowchart TD" in tested_markdown
    assert 'files["Dateien: 2"]:::metric' in security_markdown
    assert 'checks["Checks: 1"]:::metric' in tested_markdown
    assert 'delivery["Dispatch: not sent"]:::dispatch' in tested_markdown
    assert "change-security" in security_markdown
    assert "change-test" in tested_markdown


def test_import_codex_session_roots_directory_scan_imports_latest_final_turn_only(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "multi-final-directory-demo", version="1.0.4")
    store = AccountStore(tmp_path / "accounts", "TeeBotus_Logger", provider())
    session_file = tmp_path / "sessions" / "multi-final.jsonl"
    rows = [
        {"type": "session_meta", "payload": {"id": "sess-multi-final-dir", "cwd": str(repo)}},
        {"type": "turn_context", "payload": {"turn_id": "turn-one"}},
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "phase": "final_answer",
                "content": [{"type": "output_text", "text": "Alte finale Summary."}],
            },
        },
        {"type": "turn_context", "payload": {"turn_id": "turn-two"}},
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "phase": "final_answer",
                "content": [{"type": "output_text", "text": "Neueste finale Summary."}],
            },
        },
    ]
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")

    report = import_codex_session_roots(store, (session_file.parent,), limit=10)

    assert report["status_counts"] == {"imported": 1}
    persisted = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
    assert [(row["codex"]["turn_id"], row["summary"]["title"], row["summary_prefix"]) for row in persisted] == [
        ("turn-two", "Neueste finale Summary.", "v1.0.4 #0001"),
    ]


def test_import_codex_session_roots_skips_invalid_repo_root_without_aborting(tmp_path: Path) -> None:
    store = AccountStore(tmp_path / "accounts", "TeeBotus_Logger", provider())
    sessions_root = tmp_path / "sessions"
    session_file = sessions_root / "agent-session.jsonl"
    write_codex_session(
        session_file,
        repo=tmp_path / ".codex-agents" / "agent" / "work",
        session_id="sess-hidden-agent",
        turn_id="turn-hidden-agent",
    )

    report = import_codex_session_roots(store, (sessions_root,), limit=10)

    assert report["ok"] is True
    assert report["status_counts"] == {"skipped": 1}
    assert report["items"][0]["status"] == "skipped"
    assert report["items"][0]["reason"] == "invalid_repo_root"
    assert ".codex-agents" in report["items"][0]["error"]
    assert store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID) == []


def test_import_codex_session_roots_limit_prefers_newest_session_mtime(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "watch-newest-limit-demo", version="3.0.0")
    store = AccountStore(tmp_path / "accounts", "TeeBotus_Logger", provider())
    sessions_root = tmp_path / "sessions"
    old_session = write_codex_session(
        sessions_root / "000-old.jsonl",
        repo=repo,
        session_id="sess-old",
        turn_id="turn-old",
        final_text="Alte Summary darf bei limit=1 nicht gewinnen.",
    )
    new_session = write_codex_session(
        sessions_root / "999-new.jsonl",
        repo=repo,
        session_id="sess-new",
        turn_id="turn-new",
        final_text="Neue Summary gewinnt trotz spaeterem Pfadnamen.",
    )
    os.utime(old_session, ns=(1_000_000_000, 1_000_000_000))
    os.utime(new_session, ns=(2_000_000_000, 2_000_000_000))

    report = import_codex_session_roots(store, (sessions_root,), limit=1)

    assert report["status_counts"] == {"imported": 1}
    assert Path(report["items"][0]["path"]) == new_session.resolve()
    rows = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
    assert len(rows) == 1
    assert rows[0]["codex"]["session_id"] == "sess-new"
    assert rows[0]["summary"]["title"] == "Neue Summary gewinnt trotz spaeterem Pfadnamen."


def test_import_codex_session_roots_directory_scan_ignores_non_session_jsonl_for_limit(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "watch-ignore-non-session-demo", version="3.0.4")
    store = AccountStore(tmp_path / "accounts", "TeeBotus_Logger", provider())
    root = tmp_path / "codex-agents" / "a1"
    session_file = write_codex_session(
        root / "sessions" / "rollout.jsonl",
        repo=repo,
        session_id="sess-real-session",
        turn_id="turn-real-session",
        final_text="Echte Session darf durch neue Fixture-Datei nicht verdraengt werden.",
    )
    fixture_file = root / "plugins" / "cache" / "plugin-eval" / "fixtures" / "observed-usage" / "responses.jsonl"
    fixture_file.parent.mkdir(parents=True, exist_ok=True)
    fixture_file.write_text(json.dumps({"not": "a codex session"}) + "\n", encoding="utf-8")
    os.utime(session_file, ns=(1_000_000_000, 1_000_000_000))
    os.utime(fixture_file, ns=(2_000_000_000, 2_000_000_000))

    report = import_codex_session_roots(store, (root,), limit=1)

    assert report["status_counts"] == {"imported": 1}
    assert Path(report["items"][0]["path"]) == session_file.resolve()
    rows = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
    assert len(rows) == 1
    assert rows[0]["codex"]["session_id"] == "sess-real-session"


def test_import_codex_session_roots_numbers_limited_backfill_chronologically(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "watch-numbered-backfill-demo", version="3.0.1")
    store = AccountStore(tmp_path / "accounts", "TeeBotus_Logger", provider())
    sessions_root = tmp_path / "sessions"
    old_session = write_codex_session(
        sessions_root / "000-old.jsonl",
        repo=repo,
        session_id="sess-backfill-old",
        turn_id="turn-old",
        final_text="Alte Summary ausserhalb des Limits.",
    )
    middle_session = write_codex_session(
        sessions_root / "001-middle.jsonl",
        repo=repo,
        session_id="sess-backfill-middle",
        turn_id="turn-middle",
        final_text="Mittlere Summary soll zuerst nummeriert werden.",
    )
    new_session = write_codex_session(
        sessions_root / "002-new.jsonl",
        repo=repo,
        session_id="sess-backfill-new",
        turn_id="turn-new",
        final_text="Neue Summary soll danach nummeriert werden.",
    )
    os.utime(old_session, ns=(1_000_000_000, 1_000_000_000))
    os.utime(middle_session, ns=(2_000_000_000, 2_000_000_000))
    os.utime(new_session, ns=(3_000_000_000, 3_000_000_000))

    report = import_codex_session_roots(store, (sessions_root,), limit=2)

    assert [Path(item["path"]) for item in report["items"]] == [middle_session.resolve(), new_session.resolve()]
    rows = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
    assert [(row["codex"]["session_id"], row["summary_prefix"]) for row in rows] == [
        ("sess-backfill-middle", "v3.0.1 #0001"),
        ("sess-backfill-new", "v3.0.1 #0002"),
    ]


def test_codex_history_watch_once_cli_imports_session_directory(tmp_path: Path, capsys) -> None:
    make_instance(tmp_path)
    repo = make_git_repo(tmp_path, "watch-cli-demo", version="3.0.0")
    sessions_root = tmp_path / "sessions"
    write_codex_session(sessions_root / "2026" / "06" / "19" / "rollout.jsonl", repo=repo, session_id="sess-cli-watch", turn_id="turn-cli")

    result = codex_history_main(
        [
            "watch",
            "--once",
            "--instances-dir",
            str(tmp_path),
            "--instance",
            "Depressionsbot",
            "--sessions-root",
            str(sessions_root),
            "--format",
            "json",
        ],
        provider=provider(),
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["instances"][0]["status_counts"] == {"imported": 1}

    report = build_codex_history_report(instances_dir=tmp_path, instances=("Depressionsbot",), provider=provider())
    assert report["totals"]["outbox_items"] == 1
    latest = report["instances"][0]["codex_history"]["latest_by_repo"][0]
    assert latest["repo_name"] == "watch-cli-demo"


def test_codex_history_watch_once_cli_accepts_hidden_codex_session_root(tmp_path: Path, capsys) -> None:
    make_instance(tmp_path)
    repo = make_git_repo(tmp_path, "watch-hidden-root-demo", version="3.0.0")
    sessions_root = tmp_path / ".codex" / "sessions"
    write_codex_session(sessions_root / "rollout.jsonl", repo=repo, session_id="sess-hidden-watch", turn_id="turn-hidden")

    result = codex_history_main(
        [
            "watch",
            "--once",
            "--instances-dir",
            str(tmp_path),
            "--instance",
            "Depressionsbot",
            "--sessions-root",
            str(sessions_root),
            "--format",
            "json",
        ],
        provider=provider(),
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["sessions_roots"] == [str(sessions_root.resolve())]
    assert payload["instances"][0]["status_counts"] == {"imported": 1}


def test_codex_history_watch_once_can_post_index_after_import(tmp_path: Path, capsys) -> None:
    make_instance(tmp_path)
    repo = make_git_repo(tmp_path, "watch-post-index-demo", version="3.0.1")
    sessions_root = tmp_path / "sessions"
    write_codex_session(sessions_root / "rollout.jsonl", repo=repo, session_id="sess-watch-post-index", turn_id="turn-post-index")

    result = codex_history_main(
        [
            "watch",
            "--once",
            "--instances-dir",
            str(tmp_path),
            "--instance",
            "Depressionsbot",
            "--sessions-root",
            str(sessions_root),
            "--post-index",
            "--format",
            "json",
        ],
        provider=provider(),
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    instance = payload["instances"][0]
    assert instance["status_counts"] == {"imported": 1}
    assert instance["post_index"]["ok"] is True
    assert instance["post_index"]["export"]["exported"] == 1
    exported_files = list((tmp_path / "Depressionsbot" / "data" / "Codex_History_Bibliothek").rglob("*.md"))
    assert exported_files
    assert any("watch-post-index-demo" in path.read_text(encoding="utf-8") for path in exported_files)


def test_codex_history_watch_once_can_post_index_qdrant_dry_run(tmp_path: Path, capsys) -> None:
    make_instance(tmp_path)
    repo = make_git_repo(tmp_path, "watch-post-qdrant-demo", version="3.0.2")
    sessions_root = tmp_path / "sessions"
    write_codex_session(sessions_root / "rollout.jsonl", repo=repo, session_id="sess-watch-post-qdrant", turn_id="turn-post-qdrant")

    result = codex_history_main(
        [
            "watch",
            "--once",
            "--instances-dir",
            str(tmp_path),
            "--instance",
            "Depressionsbot",
            "--sessions-root",
            str(sessions_root),
            "--post-index-qdrant",
            "--post-index-qdrant-dry-run",
            "--format",
            "json",
        ],
        provider=provider(),
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    post_index = payload["instances"][0]["post_index"]
    assert post_index["export"]["exported"] == 1
    assert post_index["qdrant"][0]["status"] == "dry_run"
    assert post_index["qdrant"][0]["point_count"] == 1


def test_watch_codex_session_roots_polls_and_deduplicates_between_iterations(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "watch-loop-demo", version="3.1.0")
    sessions_root = tmp_path / "sessions"
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    write_codex_session(sessions_root / "first.jsonl", repo=repo, session_id="sess-watch-1", turn_id="turn-1")
    sleep_calls: list[float] = []

    def sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        write_codex_session(sessions_root / "second.jsonl", repo=repo, session_id="sess-watch-2", turn_id="turn-2")

    result = watch_codex_session_roots(
        store,
        (sessions_root,),
        poll_interval_seconds=0.25,
        max_iterations=2,
        sleep=sleep,
    )

    assert sleep_calls == [0.25]
    assert result["iterations"] == 2
    assert result["status_counts"] == {"duplicate": 1, "imported": 2}
    rows = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
    assert len(rows) == 2
    assert [row["summary_prefix"] for row in rows] == ["v3.1.0 #0001", "v3.1.0 #0002"]


def test_watch_codex_session_roots_runs_post_scan_callback_per_scan(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "watch-post-scan-callback-demo", version="3.1.2")
    sessions_root = tmp_path / "sessions"
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    write_codex_session(sessions_root / "first.jsonl", repo=repo, session_id="sess-post-scan-1", turn_id="turn-1")
    status_counts: list[dict[str, int]] = []

    def sleep(_seconds: float) -> None:
        write_codex_session(sessions_root / "second.jsonl", repo=repo, session_id="sess-post-scan-2", turn_id="turn-2")

    result = watch_codex_session_roots(
        store,
        (sessions_root,),
        poll_interval_seconds=0.25,
        max_iterations=2,
        sleep=sleep,
        post_scan=lambda report: status_counts.append(dict(report.get("status_counts", {}))),
    )

    assert result["iterations"] == 2
    assert status_counts == [{"imported": 1}, {"duplicate": 1, "imported": 1}]


def test_watch_post_index_callback_skips_expensive_work_without_new_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reports: list[dict[str, Any]] = []
    dispatch_reports: list[dict[str, Any]] = []
    index_calls: list[str] = []
    dispatch_calls: list[str] = []
    args = SimpleNamespace(
        post_index=True,
        post_index_qdrant=False,
        post_index_qdrant_ensure=False,
        dispatch=True,
        follow=False,
        format="json",
    )

    def fake_index(*_args, **kwargs):
        index_calls.append(str(kwargs["instance_name"]))
        return {"ok": True, "export": {"exported": 0}}

    def fake_dispatch(*_args, **kwargs):
        dispatch_calls.append("dispatch")
        return {"ok": True, "instances": []}

    monkeypatch.setattr(codex_history_module, "run_codex_history_index", fake_index)
    monkeypatch.setattr(codex_history_module, "_watch_dispatch_report", fake_dispatch)
    callback = codex_history_module._watch_post_index_callback(
        object(),
        tmp_path,
        "TeeBotus_Logger",
        args,
        provider(),
        reports,
        dispatch_reports,
    )
    assert callback is not None

    callback({"status_counts": {"duplicate": 12, "skipped": 4}, "items": []})
    callback({"status_counts": {"skipped": 12}, "items": []})
    callback({"status_counts": {"imported": 1}, "items": []})

    assert index_calls == ["TeeBotus_Logger", "TeeBotus_Logger"]
    assert dispatch_calls == ["dispatch", "dispatch"]
    assert len(reports) == 2
    assert len(dispatch_reports) == 2


def test_watch_codex_session_roots_for_instances_scans_all_instances_each_iteration(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "watch-multi-instance-demo", version="3.1.3")
    sessions_root = tmp_path / "sessions"
    stores = {
        "Alpha": AccountStore(tmp_path / "alpha-accounts", "Alpha", provider()),
        "Beta": AccountStore(tmp_path / "beta-accounts", "Beta", provider()),
    }
    write_codex_session(sessions_root / "first.jsonl", repo=repo, session_id="sess-multi-1", turn_id="turn-1")
    scan_events: list[tuple[str, dict[str, int]]] = []

    def sleep(_seconds: float) -> None:
        write_codex_session(sessions_root / "second.jsonl", repo=repo, session_id="sess-multi-2", turn_id="turn-2")

    result = watch_codex_session_roots_for_instances(
        stores,
        (sessions_root,),
        poll_interval_seconds=0.25,
        max_iterations=2,
        sleep=sleep,
        post_scan=lambda instance, report: scan_events.append((instance, dict(report.get("status_counts", {})))),
    )

    assert [report["instance"] for report in result] == ["Alpha", "Beta"]
    assert [report["iterations"] for report in result] == [2, 2]
    assert [report["status_counts"] for report in result] == [{"duplicate": 1, "imported": 2}, {"duplicate": 1, "imported": 2}]
    assert scan_events == [
        ("Alpha", {"imported": 1}),
        ("Beta", {"imported": 1}),
        ("Alpha", {"duplicate": 1, "imported": 1}),
        ("Beta", {"duplicate": 1, "imported": 1}),
    ]
    for store in stores.values():
        rows = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
        assert len(rows) == 2
        assert [row["summary_prefix"] for row in rows] == ["v3.1.3 #0001", "v3.1.3 #0002"]


def test_watch_follow_report_retains_recent_items_but_counts_all_statuses() -> None:
    report: dict[str, object] = {
        "ok": True,
        "items": [],
        "retained_items": 0,
        "dropped_items": 0,
        "status_counts": {},
    }
    status_counter: Counter[str] = Counter()
    total_items = CODEX_HISTORY_FOLLOW_REPORT_ITEMS_LIMIT + 3

    for index in range(total_items):
        _update_watch_instance_report(
            report,
            status_counter,
            [{"status": "imported", "sequence": index}],
            follow=True,
        )

    items = report["items"]
    assert isinstance(items, list)
    assert len(items) == CODEX_HISTORY_FOLLOW_REPORT_ITEMS_LIMIT
    assert report["retained_items"] == CODEX_HISTORY_FOLLOW_REPORT_ITEMS_LIMIT
    assert report["dropped_items"] == 3
    assert report["status_counts"] == {"imported": total_items}
    assert items[0]["sequence"] == 3
    assert items[-1]["sequence"] == total_items - 1


def test_watch_codex_session_roots_snapshot_skips_unchanged_iterations(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "watch-snapshot-demo", version="3.1.1")
    sessions_root = tmp_path / "sessions"
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    write_codex_session(sessions_root / "first.jsonl", repo=repo, session_id="sess-snapshot-1", turn_id="turn-1")
    sleep_calls: list[float] = []

    result = watch_codex_session_roots(
        store,
        (sessions_root,),
        poll_interval_seconds=0.25,
        max_iterations=2,
        event_mode="snapshot",
        sleep=lambda seconds: sleep_calls.append(seconds),
    )

    assert sleep_calls == [0.25]
    assert result["iterations"] == 2
    assert result["event_mode"] == "snapshot"
    assert result["skipped_unchanged_iterations"] == 1
    assert result["status_counts"] == {"imported": 1}
    rows = store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)
    assert len(rows) == 1


def test_watch_codex_session_roots_snapshot_reuses_selected_session_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = make_git_repo(tmp_path, "watch-snapshot-reuse", version="3.1.1")
    sessions_root = tmp_path / "sessions"
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    write_codex_session(sessions_root / "first.jsonl", repo=repo, session_id="sess-snapshot-reuse", turn_id="turn-1")
    original_iter = codex_history_module._iter_codex_session_files
    iter_calls = 0

    def tracked_iter(roots: Any, *, limit: int) -> tuple[Path, ...]:
        nonlocal iter_calls
        iter_calls += 1
        return original_iter(roots, limit=limit)

    monkeypatch.setattr(codex_history_module, "_iter_codex_session_files", tracked_iter)

    result = watch_codex_session_roots(
        store,
        (sessions_root,),
        max_iterations=1,
        event_mode="snapshot",
    )

    assert result["status_counts"] == {"imported": 1}
    assert iter_calls == 1


def test_codex_session_watchdog_watches_parent_for_missing_explicit_file_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sessions_root = tmp_path / "sessions"
    sessions_root.mkdir()
    missing_session = sessions_root / "future.jsonl"

    class FakeEventHandler:
        pass

    class FakeObserver:
        def __init__(self) -> None:
            self.schedules: list[tuple[str, bool]] = []

        def schedule(self, _handler: object, path: str, *, recursive: bool) -> None:
            self.schedules.append((path, recursive))

        def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

        def join(self, timeout: float) -> None:
            del timeout

    watchdog_package = types.ModuleType("watchdog")
    watchdog_events = types.ModuleType("watchdog.events")
    watchdog_observers = types.ModuleType("watchdog.observers")
    watchdog_events.FileSystemEventHandler = FakeEventHandler
    watchdog_observers.Observer = FakeObserver
    monkeypatch.setitem(sys.modules, "watchdog", watchdog_package)
    monkeypatch.setitem(sys.modules, "watchdog.events", watchdog_events)
    monkeypatch.setitem(sys.modules, "watchdog.observers", watchdog_observers)

    watchdog = codex_history_module._build_codex_session_watchdog((missing_session,))

    assert watchdog is not None
    assert watchdog._observer.schedules == [(str(sessions_root), True)]


def test_watch_codex_session_roots_snapshot_imports_only_changed_session_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_git_repo(tmp_path, "watch-changed-files", version="3.1.1")
    sessions_root = tmp_path / "sessions"
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    first = write_codex_session(sessions_root / "first.jsonl", repo=repo, session_id="sess-first", turn_id="turn-first")
    changed = write_codex_session(sessions_root / "changed.jsonl", repo=repo, session_id="sess-changed-before", turn_id="turn-before")
    wake_calls = 0
    snapshot_calls = 0
    original_snapshot = codex_history_module._codex_session_roots_snapshot

    def tracked_snapshot(roots: Any, *, limit: int) -> tuple[tuple[str, int, int], ...]:
        nonlocal snapshot_calls
        snapshot_calls += 1
        return original_snapshot(roots, limit=limit)

    def wake(_roots: Any, *, poll_interval_seconds: float, event_mode: str, sleep: Any) -> tuple[Path, ...]:
        nonlocal wake_calls
        wake_calls += 1
        assert poll_interval_seconds == 0.25
        assert event_mode == "snapshot"
        write_codex_session(changed, repo=repo, session_id="sess-changed-after", turn_id="turn-after")
        return (changed,)

    monkeypatch.setattr(codex_history_module, "_wait_for_codex_session_change", wake)
    monkeypatch.setattr(codex_history_module, "_codex_session_roots_snapshot", tracked_snapshot)

    result = watch_codex_session_roots(
        store,
        (sessions_root,),
        poll_interval_seconds=0.25,
        max_iterations=2,
        event_mode="snapshot",
        sleep=lambda _seconds: None,
    )

    assert first.exists()
    assert wake_calls == 1
    assert snapshot_calls == 1
    assert result["status_counts"] == {"imported": 3}
    assert len(store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID)) == 3


def test_watch_codex_session_roots_keeps_events_during_import(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = make_git_repo(tmp_path, "watch-events-during-import", version="3.1.1")
    sessions_root = tmp_path / "sessions"
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    changed = write_codex_session(
        sessions_root / "changed.jsonl",
        repo=repo,
        session_id="sess-before-import",
        turn_id="turn-before-import",
    )

    class FakeWatchdog:
        def __init__(self) -> None:
            self.pending: tuple[Path, ...] = ()
            self.started = False
            self.stopped = False
            self.wait_calls = 0

        def start(self) -> None:
            self.started = True

        def wait(self, _timeout_seconds: float) -> bool | tuple[Path, ...]:
            self.wait_calls += 1
            if self.wait_calls > 1:
                return False
            pending = self.pending
            self.pending = ()
            return pending

        def stop(self) -> None:
            self.stopped = True

    watchdog = FakeWatchdog()
    import_calls: list[tuple[Path, ...] | None] = []
    original_import = codex_history_module.import_codex_session_roots

    def tracked_import(store_arg: AccountStore, roots: Any, *, limit: int, session_files: Any = None) -> dict[str, Any]:
        import_calls.append(tuple(session_files) if session_files is not None else None)
        report = original_import(store_arg, roots, limit=limit, session_files=session_files)
        if len(import_calls) == 1:
            write_codex_session(
                changed,
                repo=repo,
                session_id="sess-after-import",
                turn_id="turn-after-import",
            )
            watchdog.pending = (changed,)
        return report

    monkeypatch.setattr(codex_history_module, "_build_codex_session_watchdog", lambda _roots: watchdog)
    monkeypatch.setattr(codex_history_module, "import_codex_session_roots", tracked_import)

    result = watch_codex_session_roots(
        store,
        (sessions_root,),
        poll_interval_seconds=0.25,
        max_iterations=3,
        event_mode="auto",
    )

    assert watchdog.started is True
    assert watchdog.stopped is True
    assert watchdog.wait_calls == 2
    assert len(import_calls) == 2
    assert import_calls[1] == (changed.resolve(),)
    assert result["status_counts"] == {"imported": 2}


def test_watch_codex_session_roots_stops_watchdog_on_scan_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeWatchdog:
        def __init__(self) -> None:
            self.started = False
            self.stopped = False

        def start(self) -> None:
            self.started = True

        def stop(self) -> None:
            self.stopped = True

    watchdog = FakeWatchdog()

    def fail_import(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("synthetic scan failure")

    monkeypatch.setattr(codex_history_module, "_build_codex_session_watchdog", lambda _roots: watchdog)
    monkeypatch.setattr(codex_history_module, "import_codex_session_roots", fail_import)
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())

    with pytest.raises(RuntimeError, match="synthetic scan failure"):
        watch_codex_session_roots(
            store,
            (tmp_path / "sessions",),
            poll_interval_seconds=0.25,
            max_iterations=1,
            event_mode="auto",
        )

    assert watchdog.started is True
    assert watchdog.stopped is True


def test_watch_codex_session_roots_stops_watchdog_if_start_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeWatchdog:
        def __init__(self) -> None:
            self.stopped = False

        def start(self) -> None:
            raise RuntimeError("synthetic watchdog start failure")

        def stop(self) -> None:
            self.stopped = True

    watchdog = FakeWatchdog()
    monkeypatch.setattr(codex_history_module, "_build_codex_session_watchdog", lambda _roots: watchdog)
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())

    with pytest.raises(RuntimeError, match="synthetic watchdog start failure"):
        watch_codex_session_roots(
            store,
            (tmp_path / "sessions",),
            poll_interval_seconds=0.25,
            max_iterations=1,
            event_mode="auto",
        )

    assert watchdog.stopped is True


def test_codex_session_watchdog_closes_observer_after_start_failure() -> None:
    class FailingObserver:
        def __init__(self) -> None:
            self.stopped = False
            self.joined = False

        def start(self) -> None:
            raise RuntimeError("synthetic observer failure")

        def stop(self) -> None:
            self.stopped = True

        def join(self, timeout: float) -> None:
            del timeout
            self.joined = True

    observer = FailingObserver()
    watchdog = codex_history_module._CodexSessionWatchdog(
        observer,
        threading.Event(),
        set(),
        threading.Lock(),
    )

    with pytest.raises(RuntimeError, match="synthetic observer failure"):
        watchdog.start()

    assert observer.stopped is True
    assert observer.joined is True


def test_codex_session_watchdog_resets_state_when_stop_or_join_fails(caplog: pytest.LogCaptureFixture) -> None:
    class FailingStopObserver:
        def start(self) -> None:
            return None

        def stop(self) -> None:
            raise RuntimeError("synthetic stop failure")

        def join(self, timeout: float) -> None:
            del timeout
            raise RuntimeError("synthetic join failure")

    observer = FailingStopObserver()
    watchdog = codex_history_module._CodexSessionWatchdog(
        observer,
        threading.Event(),
        set(),
        threading.Lock(),
    )
    watchdog.start()

    watchdog.stop()

    assert watchdog._started is False
    messages = [record.getMessage() for record in caplog.records]
    assert "watchdog stop failed" in " ".join(messages)
    assert "watchdog join failed" in " ".join(messages)


def test_watch_codex_session_roots_removes_deleted_event_from_snapshot_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_git_repo(tmp_path, "watch-deleted-event", version="3.1.1")
    sessions_root = tmp_path / "sessions"
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    deleted = write_codex_session(sessions_root / "deleted.jsonl", repo=repo, session_id="sess-deleted", turn_id="turn-deleted")

    class FakeWatchdog:
        def __init__(self) -> None:
            self.pending: tuple[Path, ...] = ()
            self.wait_calls = 0

        def start(self) -> None:
            return None

        def wait(self, _timeout_seconds: float) -> bool | tuple[Path, ...]:
            self.wait_calls += 1
            if self.wait_calls > 1:
                return False
            pending = self.pending
            self.pending = ()
            return pending

        def stop(self) -> None:
            return None

    watchdog = FakeWatchdog()
    import_calls = 0
    original_import = codex_history_module.import_codex_session_roots

    def tracked_import(store_arg: AccountStore, roots: Any, *, limit: int, session_files: Any = None) -> dict[str, Any]:
        nonlocal import_calls
        import_calls += 1
        report = original_import(store_arg, roots, limit=limit, session_files=session_files)
        deleted.unlink()
        watchdog.pending = (deleted,)
        return report

    monkeypatch.setattr(codex_history_module, "_build_codex_session_watchdog", lambda _roots: watchdog)
    monkeypatch.setattr(codex_history_module, "import_codex_session_roots", tracked_import)

    result = watch_codex_session_roots(
        store,
        (sessions_root,),
        poll_interval_seconds=0.25,
        max_iterations=3,
        event_mode="auto",
    )

    assert watchdog.wait_calls == 2
    assert import_calls == 1
    assert result["status_counts"] == {"imported": 1}


def test_watch_payload_ok_keeps_timer_successful_when_dispatch_has_channel_failure() -> None:
    assert (
        _watch_payload_ok(
            [
                {
                    "ok": True,
                    "dispatch": {
                        "ok": False,
                        "instances": [
                            {
                                "status_counts": {"accepted": 18, "failed": 1},
                            }
                        ],
                    },
                }
            ]
        )
        is True
    )


@pytest.mark.parametrize(
    "instance_reports",
    [
        [None],
        [{}],
        [{"ok": "false"}],
        [{"ok": 1}],
        [{"post_index": None}],
        [{"ok": True, "post_index": {}}],
        [{"post_index": {"ok": "false"}}],
    ],
)
def test_watch_payload_ok_fails_closed_for_malformed_health_values(instance_reports: list[object]) -> None:
    assert _watch_payload_ok(instance_reports) is False


def test_watch_post_index_callback_retries_malformed_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reports: list[dict[str, Any]] = []
    dispatch_reports: list[dict[str, Any]] = []
    args = SimpleNamespace(
        post_index=True,
        post_index_qdrant=False,
        post_index_qdrant_ensure=False,
        dispatch=True,
        follow=False,
        format="json",
    )
    index_calls = 0
    dispatch_calls = 0

    def malformed_index(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal index_calls
        index_calls += 1
        return {"error": "missing_ok"}

    def malformed_dispatch(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal dispatch_calls
        dispatch_calls += 1
        return {"ok": "false"}

    monkeypatch.setattr(codex_history_module, "_watch_post_index_report", malformed_index)
    monkeypatch.setattr(codex_history_module, "_watch_dispatch_report", malformed_dispatch)
    callback = codex_history_module._watch_post_index_callback(
        object(),
        tmp_path,
        "TeeBotus_Logger",
        args,
        provider(),
        reports,
        dispatch_reports,
    )
    assert callback is not None

    callback({"status_counts": {}, "items": []})
    callback({"status_counts": {}, "items": []})

    assert index_calls == 2
    assert dispatch_calls == 2
    assert reports == [{"error": "missing_ok"}, {"error": "missing_ok"}]
    assert dispatch_reports == [{"ok": "false"}, {"ok": "false"}]


def test_render_watch_report_omits_duplicate_import_details_but_keeps_counts() -> None:
    rendered = _render_watch_report(
        {
            "mode": "once",
            "sessions_roots": ["/tmp/sessions"],
            "instances": [
                {
                    "instance": "TeeBotus_Logger",
                    "status_counts": {"duplicate": 2, "imported": 1, "skipped": 1},
                    "items": [
                        {
                            "status": "duplicate",
                            "reason": "dedupe_key",
                            "item": {"summary_prefix": "v1.0.0 #0001"},
                        },
                        {
                            "status": "imported",
                            "reason": "",
                            "item": {"summary_prefix": "v1.0.0 #0002"},
                            "path": "/tmp/sessions/imported.jsonl",
                        },
                        {
                            "status": "skipped",
                            "reason": "missing_final_text",
                            "item": {},
                            "path": "/tmp/sessions/skipped.jsonl",
                        },
                    ],
                }
            ],
        }
    )

    assert "statuses: duplicate=2, imported=1, skipped=1" in rendered
    assert "summary=v1.0.0 #0001" not in rendered
    assert "import: status=duplicate" not in rendered
    assert "import: status=imported reason= summary=v1.0.0 #0002 path=/tmp/sessions/imported.jsonl" in rendered
    assert "import: status=skipped reason=missing_final_text summary= path=/tmp/sessions/skipped.jsonl" in rendered


def test_render_watch_report_bounds_non_duplicate_import_details() -> None:
    rendered = _render_watch_report(
        {
            "mode": "follow",
            "instances": [
                {
                    "instance": "TeeBotus_Logger",
                    "status_counts": {"skipped": 15},
                    "items": [
                        {
                            "status": "skipped",
                            "reason": "missing_final_text",
                            "path": f"/tmp/sessions/skipped-{index}.jsonl",
                        }
                        for index in range(15)
                    ],
                }
            ],
        }
    )

    assert rendered.count("import: status=skipped") == 12
    assert "import_details: shown=12 omitted=3 limit=12 status_counts_complete=True" in rendered
    assert "statuses: skipped=15" in rendered


def test_render_watch_report_formats_empty_dispatch_status_counts_as_none() -> None:
    rendered = _render_watch_report(
        {
            "mode": "once",
            "instances": [
                {
                    "instance": "TeeBotus_Logger",
                    "status_counts": {"duplicate": 1},
                    "items": [],
                    "dispatch": {
                        "instances": [
                            {
                                "ok": True,
                                "dry_run": False,
                                "status_counts": {},
                                "items": [],
                            }
                        ]
                    },
                }
            ],
        }
    )

    assert "dispatch: ok=True dry_run=False statuses=none" in rendered


def test_codex_history_watch_cli_can_run_bounded_poll_loop(tmp_path: Path, capsys) -> None:
    make_instance(tmp_path)
    repo = make_git_repo(tmp_path, "watch-loop-cli-demo", version="3.2.0")
    sessions_root = tmp_path / "sessions"
    write_codex_session(sessions_root / "rollout.jsonl", repo=repo, session_id="sess-loop-cli", turn_id="turn-loop-cli")

    result = codex_history_main(
        [
            "watch",
            "--instances-dir",
            str(tmp_path),
            "--instance",
            "Depressionsbot",
            "--sessions-root",
            str(sessions_root),
            "--max-iterations",
            "1",
            "--poll-interval",
            "0",
            "--event-mode",
            "snapshot",
            "--format",
            "json",
        ],
        provider=provider(),
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["mode"] == "watch"
    assert payload["follow"] is False
    assert payload["event_mode"] == "snapshot"
    assert payload["instances"][0]["iterations"] == 1
    assert payload["instances"][0]["event_mode"] == "snapshot"
    assert payload["instances"][0]["status_counts"] == {"imported": 1}


def test_codex_history_watch_dispatch_cli_defaults_to_unlimited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_instance(tmp_path)
    sessions_root = tmp_path / "sessions"
    sessions_root.mkdir()
    limits: list[int] = []

    async def fake_dispatch(_store, **kwargs):
        limits.append(int(kwargs["limit"]))
        return {"ok": True, "dry_run": True, "status_counts": {}, "items": []}

    monkeypatch.setattr(codex_history_module, "dispatch_codex_history_outbox", fake_dispatch)

    result = codex_history_main(
        [
            "watch",
            "--once",
            "--instances-dir",
            str(tmp_path),
            "--instance",
            "Depressionsbot",
            "--sessions-root",
            str(sessions_root),
            "--dispatch",
            "--dispatch-dry-run",
            "--format",
            "json",
        ]
    )

    assert result == 0
    assert limits == [0]
    payload = json.loads(capsys.readouterr().out)
    assert payload["instances"][0]["dispatch"]["instances"][0]["status_counts"] == {}


def test_watch_codex_session_roots_normalizes_iteration_options(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "watch-loop-bounds-demo", version="3.3.0")
    sessions_root = tmp_path / "sessions"
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    write_codex_session(sessions_root / "first.jsonl", repo=repo, session_id="sess-watch-bound", turn_id="turn-bound")

    result = watch_codex_session_roots(
        store,
        (sessions_root,),
        max_iterations=0,
        poll_interval_seconds=-1.0,
        limit=10,
    )

    assert result["iterations"] == 1
    assert result["status_counts"] == {"imported": 1}


def test_watch_codex_session_roots_rejects_unknown_event_mode(tmp_path: Path) -> None:
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())

    try:
        watch_codex_session_roots(store, (tmp_path / "sessions",), event_mode="bogus")
    except ValueError as exc:
        assert "event mode" in str(exc)
    else:
        raise AssertionError("expected invalid event mode rejection")


def test_watchdog_event_mode_falls_back_to_sleep_when_backend_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(
        codex_history_module,
        "_wait_for_watchdog_codex_session_change",
        lambda _roots, *, timeout_seconds: None,
    )

    codex_history_module._wait_for_codex_session_change(
        (tmp_path / "sessions",),
        poll_interval_seconds=0.5,
        event_mode="watchdog",
        sleep=sleep_calls.append,
    )

    assert sleep_calls == [0.5]


def test_watchdog_event_mode_does_not_sleep_again_after_watchdog_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(
        codex_history_module,
        "_wait_for_watchdog_codex_session_change",
        lambda _roots, *, timeout_seconds: False,
    )

    codex_history_module._wait_for_codex_session_change(
        (tmp_path / "sessions",),
        poll_interval_seconds=0.5,
        event_mode="watchdog",
        sleep=sleep_calls.append,
    )

    assert sleep_calls == []


def test_auto_event_mode_does_not_sleep_again_after_watchdog_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(
        codex_history_module,
        "_wait_for_watchdog_codex_session_change",
        lambda _roots, *, timeout_seconds: False,
    )

    codex_history_module._wait_for_codex_session_change(
        (tmp_path / "sessions",),
        poll_interval_seconds=0.5,
        event_mode="auto",
        sleep=sleep_calls.append,
    )

    assert sleep_calls == []


def test_codex_history_watch_once_rejects_missing_instance(tmp_path: Path, capsys) -> None:
    make_instance(tmp_path, "Depressionsbot")

    result = codex_history_main(
        [
            "watch",
            "--instances-dir",
            str(tmp_path),
            "--instance",
            "NichtVorhanden",
            "--once",
            "--format",
            "json",
        ],
        provider=provider(),
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "requested instances not found: NichtVorhanden" in captured.err


def test_codex_history_dispatch_rejects_missing_instance(tmp_path: Path, capsys) -> None:
    make_instance(tmp_path, "Depressionsbot")

    result = codex_history_main(
        [
            "dispatch",
            "--instances-dir",
            str(tmp_path),
            "--instance",
            "NichtVorhanden",
            "--format",
            "json",
        ],
        provider=provider(),
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "requested instances not found: NichtVorhanden" in captured.err


def test_codex_history_dispatch_rejects_invalid_instance_name(tmp_path: Path, capsys) -> None:
    make_instance(tmp_path, "Depressionsbot")

    result = codex_history_main(
        [
            "dispatch",
            "--instances-dir",
            str(tmp_path),
            "--instance",
            "../Depressionsbot",
            "--format",
            "json",
        ],
        provider=provider(),
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "instance name must be a single path segment" in captured.err


def test_codex_history_dispatch_rejects_missing_instance_list(tmp_path: Path, capsys) -> None:
    make_instance(tmp_path, "Depressionsbot")
    make_instance(tmp_path, "Anderesbot")

    result = codex_history_main(
        [
            "dispatch",
            "--instances-dir",
            str(tmp_path),
            "--instances",
            "Depressionsbot,NichtVorhanden,Anderesbot",
            "--format",
            "json",
        ],
        provider=provider(),
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "requested instances not found: NichtVorhanden" in captured.err


def test_safe_output_path_rejects_absolute_path(tmp_path: Path) -> None:
    try:
        _safe_output_path("/tmp/codex-output.json")
    except ValueError as exc:
        assert "safe relative path" in str(exc)
    else:
        raise AssertionError("absolute output path must be rejected")


def test_safe_output_path_rejects_parent_traversal(tmp_path: Path) -> None:
    try:
        _safe_output_path("../codex-output.json")
    except ValueError as exc:
        assert "forbidden relative segment" in str(exc)
    else:
        raise AssertionError("parent traversal in output path must be rejected")


def test_codex_history_report_cli_rejects_missing_parent_directory(tmp_path: Path, capsys) -> None:
    make_instance(tmp_path)
    output = tmp_path / "missing" / "dir" / "codex-report.json"

    result = codex_history_main(
        [
            "report",
            "--instances-dir",
            str(tmp_path),
            "--instances",
            "Depressionsbot",
            "--format",
            "json",
            "--output",
            str(output),
        ],
        provider=provider(),
    )

    assert result == 2
    assert "report failed:" in capsys.readouterr().err
    assert not output.exists()


def test_codex_history_cli_append_rejects_missing_parent_directory(tmp_path: Path, capsys) -> None:
    make_instance(tmp_path)
    repo = make_git_repo(tmp_path, "append-output-demo", version="2.0.0")
    output = tmp_path / "missing" / "dir" / "codex-append.json"

    result = codex_history_main(
        [
            "append",
            "--instances-dir",
            str(tmp_path),
            "--instance",
            "Depressionsbot",
            "--repo-root",
            str(repo),
            "--title",
            "Output regression",
            "--format",
            "json",
            "--output",
            str(output),
        ],
        provider=provider(),
    )

    assert result == 2
    assert "append failed:" in capsys.readouterr().err
    assert not output.exists()


def test_safe_output_path_rejects_windows_drive_paths(tmp_path: Path) -> None:
    try:
        _safe_output_path("C:/codex-output.json")
    except ValueError as exc:
        assert "invalid path segment" in str(exc) or "invalid path separator" in str(exc)
    else:
        raise AssertionError("windows drive output path must be rejected")


def test_safe_repo_root_rejects_parent_traversal(tmp_path: Path) -> None:
    try:
        _safe_repo_root(tmp_path / "../other")
    except ValueError as exc:
        assert "forbidden relative segment" in str(exc)
    else:
        raise AssertionError("parent traversal in repo root must be rejected")


def test_safe_repo_root_rejects_windows_drive_paths(tmp_path: Path) -> None:
    try:
        _safe_repo_root("C:/tmp")
    except ValueError as exc:
        assert "invalid path segment" in str(exc) or "invalid path separator" in str(exc)
    else:
        raise AssertionError("windows drive repo path must be rejected")


def test_normalize_and_classify_remote_urls() -> None:
    assert _normalize_remote_url("git@github.com:Org/Repo.git") == "ssh://git@github.com/org/repo"
    assert _repo_provider("git@github.com:Org/Repo.git") == "github"
    assert _normalize_remote_url("alice@github.com:Org/Repo") == "ssh://alice@github.com/org/repo"
    assert _repo_provider("alice@github.com:Org/Repo") == "github"
    assert _normalize_remote_url("https://github.com/Org/Repo.git") == "https://github.com/org/repo.git"
    assert _repo_provider("https://github.com/Org/Repo.git") == "github"
    assert _normalize_remote_url("example:foo/bar") == "example:foo/bar"
    assert _repo_provider("example:foo/bar") == "git"
    assert _normalize_remote_url("localhost:owner/repo") == "ssh://git@localhost/owner/repo"
    assert _repo_provider("localhost:owner/repo") == "git"
