from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json

import scripts.migrate_account_memory_to_postgres as postgres_migration
import scripts.migrate_account_memory_to_database as database_migration
from TeeBotus.runtime.accounts import LLM_STATE_COLLECTION, PROACTIVE_OUTBOX_COLLECTION


def test_postgres_memory_migration_wrapper_delegates_to_verified_database_migrator(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_database_main(argv: list[str]) -> int:
        calls.append(argv)
        return 0

    monkeypatch.setattr(postgres_migration, "database_migration_main", fake_database_main)

    result = postgres_migration.main(
        [
            "--backend",
            "sqlite",
            "--instances-dir",
            "instances",
            "--instance",
            "Depressionsbot",
            "--postgres-dsn",
            "postgresql://bench",
            "--delete-json-files",
        ]
    )

    assert result == 0
    assert calls == [
        [
            "--backend",
            "sqlite",
            "--instances-dir",
            "instances",
            "--instance",
            "Depressionsbot",
            "--postgres-dsn",
            "postgresql://bench",
            "--delete-json-files",
            "--backend",
            "postgres",
        ]
    ]


def test_migrate_selected_instances_skips_missing_instances(tmp_path, monkeypatch) -> None:
    calls: list[tuple[Path, bool]] = []

    class _FakeAccountStore:
        def __init__(self, accounts_dir: Path, instance_name: str, *_args, create_dirs: bool = True, **_kwargs) -> None:
            calls.append((accounts_dir, create_dirs))
            self.accounts_dir = accounts_dir
            self.account_memory_vault = SimpleNamespace(
                read_jsonl=lambda path: [],
                read_json=lambda path, default: default,
            )
            self._entries = []
            self._index = {}

        def write_memory_entries(self, account_id: str, entries: list[dict]) -> None:
            assert account_id
            self._entries.extend(entries)

        def write_memory_index(self, account_id: str, index: dict) -> None:
            assert account_id
            self._index[account_id] = index

        def read_memory_entries(self, account_id: str) -> list[dict]:
            assert account_id
            return self._entries

        def read_memory_index(self, account_id: str) -> dict:
            assert account_id
            return self._index.get(account_id, {})

    monkeypatch.setattr(database_migration, "AccountStore", _FakeAccountStore)

    instances_dir = tmp_path / "instances"
    existing_instance = instances_dir / "Existing"
    existing_instance.mkdir(parents=True)

    result = database_migration._migrate(
        instances_dir=instances_dir,
        selected=("Existing", "Missing"),
        dry_run=True,
        delete_json_files=False,
    )

    assert result == {"migrated": 0, "skipped": 0, "deleted": 0}
    assert calls == [
        (existing_instance / "data" / "accounts", False),
        (existing_instance / "data" / "accounts", False),
    ]


def test_migrate_selected_instances_deduplicates_duplicates(tmp_path, monkeypatch) -> None:
    calls: list[tuple[Path, bool]] = []

    class _FakeAccountStore:
        def __init__(self, accounts_dir: Path, instance_name: str, *_args, create_dirs: bool = True, **_kwargs) -> None:
            calls.append((accounts_dir, create_dirs))
            self.accounts_dir = accounts_dir
            self.account_memory_vault = SimpleNamespace(
                read_jsonl=lambda path: [],
                read_json=lambda path, default: default,
            )

        def write_memory_entries(self, account_id: str, entries: list[dict]) -> None:
            pass

        def write_memory_index(self, account_id: str, index: dict) -> None:
            pass

        def read_memory_entries(self, account_id: str) -> list[dict]:
            return []

        def read_memory_index(self, account_id: str) -> dict:
            return {}

    monkeypatch.setattr(database_migration, "AccountStore", _FakeAccountStore)

    instances_dir = tmp_path / "instances"
    existing_instance = instances_dir / "Existing"
    existing_instance.mkdir(parents=True)

    result = database_migration._migrate(
        instances_dir=instances_dir,
        selected=("Existing", "Existing", ""),
        dry_run=True,
        delete_json_files=False,
    )

    assert result == {"migrated": 0, "skipped": 0, "deleted": 0}
    assert calls == [
        (existing_instance / "data" / "accounts", False),
        (existing_instance / "data" / "accounts", False),
    ]


def test_migrate_account_json_artifacts_merges_sql_and_deletes_verified_sources(tmp_path, monkeypatch) -> None:
    account_id = "a" * 128
    instances_dir = tmp_path / "instances"
    account_dir = instances_dir / "Existing" / "data" / "accounts" / "accounts" / account_id
    account_dir.mkdir(parents=True)
    (account_dir / "User_Memory_Entries.jsonl").write_text(
        json.dumps({"id": "mem-new", "updated_at": "2026-06-15T12:00:00+00:00", "text": "new"}) + "\n",
        encoding="utf-8",
    )
    (account_dir / "LLM_State.json").write_text(
        json.dumps({"updated_at": "2026-06-15T12:00:00+00:00", "previous_response_ids": ["new"]}),
        encoding="utf-8",
    )
    (account_dir / "Proactive_Outbox.jsonl").write_text(
        json.dumps({"id": "pro-new", "updated_at": "2026-06-15T12:00:00+00:00", "message_text": "new"}) + "\n",
        encoding="utf-8",
    )

    class _Backend:
        entries = {account_id: [{"id": "mem-old", "updated_at": "2026-06-14T12:00:00+00:00", "text": "old"}]}
        indexes = {account_id: {"updated_at": "2026-06-14T12:00:00+00:00"}}
        collections = {
            (account_id, LLM_STATE_COLLECTION): [{"updated_at": "2026-06-14T12:00:00+00:00", "previous_response_ids": ["old"]}],
            (account_id, PROACTIVE_OUTBOX_COLLECTION): [
                {"id": "pro-old", "updated_at": "2026-06-14T12:00:00+00:00", "message_text": "old"}
            ],
        }

        def read_collection(self, account_id: str, collection: str):
            return list(self.collections.get((account_id, collection), []))

        def write_collection(self, account_id: str, collection: str, rows: list[dict]):
            self.collections[(account_id, collection)] = list(rows)

    class _FakeAccountStore:
        backend = _Backend()

        def __init__(self, accounts_dir: Path, instance_name: str, *_args, create_dirs: bool = True, **_kwargs) -> None:
            self.accounts_dir = accounts_dir / "accounts"
            self.account_memory_backend = self.backend
            self.account_memory_vault = SimpleNamespace()

        def _read_jsonl_with_fallback(self, path: Path, *, vault):
            return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

        def _read_json_with_fallback(self, path: Path, default: dict, *, vault):
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else dict(default)

        def read_memory_entries(self, account_id: str) -> list[dict]:
            return list(self.backend.entries.get(account_id, []))

        def write_memory_entries(self, account_id: str, entries: list[dict]) -> None:
            self.backend.entries[account_id] = list(entries)

        def read_memory_index(self, account_id: str) -> dict:
            return dict(self.backend.indexes.get(account_id, {}))

        def write_memory_index(self, account_id: str, index: dict) -> None:
            self.backend.indexes[account_id] = dict(index)

        def rebuild_structured_memory_index(self, account_id: str) -> None:
            self.backend.indexes[account_id] = {"rebuilt": True}

        def check_structured_memory_index(self, account_id: str):
            return SimpleNamespace(ok=True, errors=[])

    monkeypatch.setattr(database_migration, "AccountStore", _FakeAccountStore)
    monkeypatch.setattr(database_migration, "SecretToolInstanceSecretProvider", lambda create_if_missing=False: object())

    result = database_migration._migrate(
        instances_dir=instances_dir,
        selected=("Existing",),
        dry_run=False,
        delete_json_files=True,
    )

    assert result == {"migrated": 1, "skipped": 0, "deleted": 3}
    assert {row["id"] for row in _FakeAccountStore.backend.entries[account_id]} == {"mem-old", "mem-new"}
    assert _FakeAccountStore.backend.collections[(account_id, LLM_STATE_COLLECTION)] == [
        {"updated_at": "2026-06-15T12:00:00+00:00", "previous_response_ids": ["new"]}
    ]
    assert {row["id"] for row in _FakeAccountStore.backend.collections[(account_id, PROACTIVE_OUTBOX_COLLECTION)]} == {
        "pro-old",
        "pro-new",
    }
    assert not (account_dir / "User_Memory_Entries.jsonl").exists()
    assert not (account_dir / "LLM_State.json").exists()
    assert not (account_dir / "Proactive_Outbox.jsonl").exists()
