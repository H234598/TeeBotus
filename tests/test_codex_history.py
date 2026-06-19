from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from TeeBotus.admin.codex_history import (
    _normalize_remote_url,
    _repo_provider,
    append_codex_history_summary,
    build_codex_history_report,
    dispatch_codex_history_outbox,
    import_codex_session_file,
    main as codex_history_main,
    watch_codex_session_roots,
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


def test_codex_history_dispatch_sends_markdown_attachment_and_marks_accepted(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "dispatch-demo", version="1.9.0")
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    admin_id = store.resolve_or_create_account(telegram_identity_key(42), display_label="Admin")
    store.update_identity_route(telegram_identity_key(42), channel="telegram", chat_id="42", chat_type="private", adapter_slot=1)
    item = append_codex_history_summary(
        store,
        repo_root=repo,
        title="Dispatch gebaut",
        bullets=["Summary wird als Markdown-Datei versendet."],
        session_id="sess-dispatch",
    )
    sent: list[tuple[dict[str, object], SendAttachment, dict[str, object]]] = []

    def sender(route: dict[str, object], action: SendAttachment, metadata: dict[str, object]) -> str:
        sent.append((route, action, metadata))
        return "telegram-msg-1"

    result = asyncio.run(
        dispatch_codex_history_outbox(
            store,
            instance_name="Depressionsbot",
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


def test_codex_history_dispatch_dry_run_does_not_mutate_outbox(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "dry-run-demo", version="1.0.1")
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    admin_id = store.resolve_or_create_account(telegram_identity_key(7), display_label="Admin")
    store.update_identity_route(telegram_identity_key(7), channel="telegram", chat_id="7", chat_type="private", adapter_slot=1)
    append_codex_history_summary(store, repo_root=repo, title="Dry Run", bullets=["Nur anzeigen."])

    result = asyncio.run(
        dispatch_codex_history_outbox(
            store,
            instance_name="Depressionsbot",
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


def test_codex_history_dispatch_marks_missing_sender_failed_without_deleting_item(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "missing-sender-demo", version="1.0.2")
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    admin_id = store.resolve_or_create_account(telegram_identity_key(8), display_label="Admin")
    store.update_identity_route(telegram_identity_key(8), channel="telegram", chat_id="8", chat_type="private", adapter_slot=1)
    item = append_codex_history_summary(store, repo_root=repo, title="Missing Sender", bullets=["Fehler bleibt auditierbar."])

    result = asyncio.run(
        dispatch_codex_history_outbox(
            store,
            instance_name="Depressionsbot",
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
            "--format",
            "json",
        ],
        provider=provider(),
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["mode"] == "watch"
    assert payload["instances"][0]["iterations"] == 1
    assert payload["instances"][0]["status_counts"] == {"imported": 1}


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
