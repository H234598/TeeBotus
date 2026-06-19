from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import scripts.migrate_account_memory_to_postgres as postgres_migration
import scripts.migrate_account_memory_to_database as database_migration


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
