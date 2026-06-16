from __future__ import annotations

import scripts.migrate_account_memory_to_postgres as postgres_migration


def test_postgres_memory_migration_wrapper_delegates_to_verified_database_migrator(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_database_main(argv: list[str]) -> int:
        calls.append(argv)
        return 0

    monkeypatch.setattr(postgres_migration, "database_migration_main", fake_database_main)

    result = postgres_migration.main(
        [
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
            "postgres",
            "--instances-dir",
            "instances",
            "--instance",
            "Depressionsbot",
            "--postgres-dsn",
            "postgresql://bench",
            "--delete-json-files",
        ]
    ]
