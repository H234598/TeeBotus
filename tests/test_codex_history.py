from __future__ import annotations

import asyncio
import json
import os
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pytest

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
            instance_name="Depressionsbot",
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
    assert strategy["summary_prefix"] == "v1.8.0 #0001"
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
            instance_name="Depressionsbot",
            account_ids=(admin_id,),
            senders={"telegram": sender},
            now=datetime(2026, 6, 19, 14, 5, tzinfo=timezone.utc),
        )
    )

    assert dispatch["status_counts"] == {"accepted": 3}
    assert sent[-1].caption == "Release Codex-History-Strategie 1.8.0"
    assert sent[-1].filename == "Codex-History-Strategie_release_1.8.0_0001.md"
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
    assert Path(dispatch["obsidian_path"]).name.startswith("20260619T140000_")


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


def test_codex_history_dispatch_cli_defaults_to_limit_50(
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
    assert limits == [50]
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True


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


def test_codex_history_dispatch_requeues_transient_sender_errors(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "retry-sender-demo", version="1.0.3")
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    admin_id = store.resolve_or_create_account(telegram_identity_key(9), display_label="Admin")
    store.update_identity_route(telegram_identity_key(9), channel="telegram", chat_id="9", chat_type="private", adapter_slot=1)
    item = append_codex_history_summary(store, repo_root=repo, title="Retry Sender", bullets=["Transienter Fehler."])

    def failing_sender(_route: dict[str, object], _action: SendAttachment, _metadata: dict[str, object]) -> str:
        raise RuntimeError("temporary network issue")

    result = asyncio.run(
        dispatch_codex_history_outbox(
            store,
            instance_name="Depressionsbot",
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


def test_codex_history_dispatch_ignores_fresh_in_flight_item(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "fresh-in-flight-demo", version="1.0.4")
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    admin_id = store.resolve_or_create_account(telegram_identity_key(10), display_label="Admin")
    store.update_identity_route(telegram_identity_key(10), channel="telegram", chat_id="10", chat_type="private", adapter_slot=1)
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
            instance_name="Depressionsbot",
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
            instance_name="Depressionsbot",
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
    assert "Zwischenstand" not in rows[0]["summary"]["markdown"]


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


def test_codex_history_watch_dispatch_cli_defaults_to_limit_50(
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
    assert limits == [50]
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
