from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from TeeBotus.runtime.accounts import INSTANCE_STATE_ACCOUNT_ID, AccountStore, StaticSecretProvider
from TeeBotus.runtime.codex_command import (
    execute_codex_admin_command,
    parse_codex_admin_command,
    resolve_codex_session_target,
)


def provider() -> StaticSecretProvider:
    return StaticSecretProvider(b"c" * 32)


def test_parse_codex_command_supports_default_bracket_and_known_positional() -> None:
    default = parse_codex_admin_command("/codex mach weiter")
    bracket = parse_codex_admin_command("/codex [Projekt A] [/tmp/repo-a] pruefe status")
    positional = parse_codex_admin_command("/codex ProjektA repo-a teste", (("ProjektA", "/tmp/repo-a"),))

    assert default is not None
    assert default.prompt == "mach weiter"
    assert default.project_filter == ""
    assert default.repo_filter == ""
    assert bracket is not None
    assert bracket.project_filter == "Projekt A"
    assert bracket.repo_filter == "/tmp/repo-a"
    assert bracket.prompt == "pruefe status"
    assert positional is not None
    assert positional.project_filter == "ProjektA"
    assert positional.repo_filter == "repo-a"
    assert positional.prompt == "teste"


def test_resolve_codex_session_target_uses_latest_session_for_latest_history_repo(tmp_path: Path) -> None:
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    session_root = tmp_path / ".codex" / "sessions"
    old_session = _write_session(session_root, "11111111-1111-1111-1111-111111111111", repo_a, mtime=10)
    new_session = _write_session(session_root, "22222222-2222-2222-2222-222222222222", repo_b, mtime=20)
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    store.write_codex_history_outbox(
        INSTANCE_STATE_ACCOUNT_ID,
        [
            _history_item("hist-a", "ProjektA", repo_a, old_session, "2026-06-19T12:00:00+00:00"),
            _history_item("hist-b", "ProjektB", repo_b, new_session, "2026-06-19T13:00:00+00:00"),
        ],
    )

    target = resolve_codex_session_target(store, project_root=repo_a, session_roots=(session_root,))

    assert target is not None
    assert target.session_id == "22222222-2222-2222-2222-222222222222"
    assert target.repo_root == str(repo_b)
    assert target.codex_home == str(tmp_path / ".codex")


def test_execute_codex_admin_command_resumes_selected_session_via_stdin(tmp_path: Path, monkeypatch) -> None:
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    session_root = tmp_path / ".codex" / "sessions"
    session_a = _write_session(session_root, "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", repo_a, mtime=10)
    session_b = _write_session(session_root, "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", repo_b, mtime=20)
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", provider())
    store.write_codex_history_outbox(
        INSTANCE_STATE_ACCOUNT_ID,
        [
            _history_item("hist-a", "ProjektA", repo_a, session_a, "2026-06-19T12:00:00+00:00"),
            _history_item("hist-b", "ProjektB", repo_b, session_b, "2026-06-19T13:00:00+00:00"),
        ],
    )
    monkeypatch.setattr("TeeBotus.runtime.codex_command.shutil.which", lambda _name: "/usr/bin/codex")
    calls: list[dict[str, object]] = []

    def runner(args, **kwargs):
        calls.append({"args": args, **kwargs})
        return subprocess.CompletedProcess(args, 0, stdout="fertig", stderr="")

    result = execute_codex_admin_command(
        store,
        instance_name="Depressionsbot",
        text="/codex [ProjektA] [repo-a] mach bitte weiter",
        project_root=repo_b,
        session_roots=(session_root,),
        runner=runner,
    )

    assert result.ok
    assert result.target is not None
    assert result.target.session_id == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert "fertig" in result.text
    assert calls[0]["args"] == ["codex", "exec", "resume", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "-"]
    assert calls[0]["cwd"] == str(repo_a)
    assert calls[0]["input"] == "mach bitte weiter"
    assert calls[0]["env"]["CODEX_HOME"] == str(tmp_path / ".codex")  # type: ignore[index]


def _write_session(root: Path, session_id: str, cwd: Path, *, mtime: int) -> Path:
    path = root / "2026" / "06" / "19" / f"rollout-2026-06-19T12-00-00-{session_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "timestamp": "2026-06-19T12:00:00Z",
                "type": "session_meta",
                "payload": {"id": session_id, "cwd": str(cwd)},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    os.utime(path, (mtime, mtime))
    return path


def _history_item(item_id: str, repo_name: str, repo_root: Path, session_path: Path, timestamp: str) -> dict[str, object]:
    session_id = session_path.stem.rsplit("-", maxsplit=5)
    return {
        "id": item_id,
        "created_at": timestamp,
        "updated_at": timestamp,
        "project": {"repo_name": repo_name, "repo_root": str(repo_root), "remote_url": ""},
        "codex": {"session_id": "-".join(session_id[-5:])},
        "summary": {"title": item_id, "markdown": "# test"},
    }
