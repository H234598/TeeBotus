from __future__ import annotations

import json

from TeeBotus.embedding.cli import main as embedding_cli_main
from TeeBotus.embedding.config import EmbeddingConfig
from TeeBotus.embedding.rebuild import rebuild_qdrant_memory_indexes
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, telegram_identity_key


def test_rebuild_qdrant_memory_indexes_discovers_accounts_and_uses_account_store_truth(tmp_path):
    calls: list[tuple[str, str, str | None, str, int]] = []

    class FakeQdrantMemoryIndex:
        def __init__(self, *, url=None, embedding_provider, **_kwargs) -> None:
            self.url = url
            self.embedding_provider = embedding_provider

        def rebuild(self, *, account_store, instance_name: str, account_id: str):
            calls.append((instance_name, account_id, self.url, self.embedding_provider.model_name, self.embedding_provider.dimensions))
            return tuple(f"point:{entry['id']}" for entry in account_store.read_memory_entries(account_id))

    instances_dir = tmp_path / "instances"
    store = AccountStore(instances_dir / "Depressionsbot" / "data" / "accounts", "Depressionsbot", StaticSecretProvider(b"a" * 32))
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.append_structured_memory_entry(account_id, {"id": "mem_sleep", "user_text": "Schlaf"})
    store.append_structured_memory_entry(account_id, {"id": "mem_plan", "user_text": "Plan"})

    results = rebuild_qdrant_memory_indexes(
        instances_dir=instances_dir,
        secret_provider=StaticSecretProvider(b"a" * 32),
        qdrant_url="http://localhost:6334",
        embedding_config=EmbeddingConfig(provider="hash", model_name="custom-memory-model", dimensions=32),
        qdrant_index_factory=FakeQdrantMemoryIndex,
    )

    assert calls == [("Depressionsbot", account_id, "http://localhost:6334", "custom-memory-model", 32)]
    assert len(results) == 1
    assert results[0].status == "rebuilt"
    assert results[0].point_count == 2
    assert results[0].point_ids == ("point:mem_sleep", "point:mem_plan")


def test_rebuild_qdrant_memory_indexes_uses_instance_memory_search_config_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr("TeeBotus.instructions.PROJECT_ROOT", tmp_path)
    calls: list[tuple[str, str, str, str, int]] = []

    class FakeQdrantMemoryIndex:
        def __init__(self, *, url=None, embedding_provider, **_kwargs) -> None:
            self.url = str(url)
            self.embedding_provider = embedding_provider

        def rebuild(self, *, account_store, instance_name: str, account_id: str):
            calls.append((instance_name, account_id, self.url, self.embedding_provider.model_name, self.embedding_provider.dimensions))
            return tuple(f"point:{entry['id']}" for entry in account_store.read_memory_entries(account_id))

    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    instance_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text(
        """
        ## Memory Search
        - semantic_enabled: true
        - semantic_backend: qdrant
        - qdrant_url: http://localhost:6334
        - embedding_provider: hash
        - embedding_model: instance-memory-model
        - embedding_dimensions: 48
        """,
        encoding="utf-8",
    )
    store = AccountStore(instance_dir / "data" / "accounts", "Depressionsbot", StaticSecretProvider(b"a" * 32))
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.append_structured_memory_entry(account_id, {"id": "mem_sleep", "user_text": "Schlaf"})

    results = rebuild_qdrant_memory_indexes(
        instances_dir=instances_dir,
        secret_provider=StaticSecretProvider(b"a" * 32),
        qdrant_index_factory=FakeQdrantMemoryIndex,
    )

    assert calls == [("Depressionsbot", account_id, "http://localhost:6334", "instance-memory-model", 48)]
    assert results[0].status == "rebuilt"
    assert results[0].point_count == 1


def test_rebuild_qdrant_memory_indexes_dry_run_avoids_qdrant_writes(tmp_path):
    class UnexpectedQdrantMemoryIndex:
        def __init__(self, **_kwargs) -> None:
            raise AssertionError("dry-run must not create qdrant index")

    instances_dir = tmp_path / "instances"
    store = AccountStore(instances_dir / "Depressionsbot" / "data" / "accounts", "Depressionsbot", StaticSecretProvider(b"a" * 32))
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.append_structured_memory_entry(account_id, {"id": "mem_sleep", "user_text": "Schlaf"})

    results = rebuild_qdrant_memory_indexes(
        instances_dir=instances_dir,
        instance_names=("Depressionsbot",),
        account_ids=(account_id,),
        secret_provider=StaticSecretProvider(b"a" * 32),
        dry_run=True,
        qdrant_index_factory=UnexpectedQdrantMemoryIndex,
    )

    assert results[0].status == "dry_run"
    assert results[0].point_count == 1
    assert results[0].point_ids == ()


def test_embedding_cli_memory_rebuild_dry_run_json(monkeypatch, capsys, tmp_path):
    def fake_rebuild(**kwargs):
        assert kwargs["instances_dir"] == str(tmp_path / "instances")
        assert kwargs["instance_names"] == ["Depressionsbot"]
        assert kwargs["account_ids"] == []
        assert kwargs["dry_run"] is True
        assert kwargs["embedding_overrides"] == {
            "provider": "tei",
            "model_name": "intfloat/multilingual-e5-small",
            "dimensions": 384,
            "endpoint": "http://127.0.0.1:8080/embeddings",
            "api_key_env": "HF_TOKEN",
        }
        from TeeBotus.embedding.rebuild import QdrantMemoryRebuildResult

        return (QdrantMemoryRebuildResult("Depressionsbot", "a" * 128, "dry_run", point_count=2),)

    monkeypatch.setattr("TeeBotus.embedding.cli.rebuild_qdrant_memory_indexes", fake_rebuild)

    assert (
        embedding_cli_main(
            [
                "--instances-dir",
                str(tmp_path / "instances"),
                "--instance",
                "Depressionsbot",
                "--json",
                "memory-rebuild",
                "--dry-run",
                "--embedding-provider",
                "tei",
                "--embedding-model",
                "intfloat/multilingual-e5-small",
                "--embedding-dimensions",
                "384",
                "--embedding-endpoint",
                "http://127.0.0.1:8080/embeddings",
                "--embedding-api-key-env",
                "HF_TOKEN",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["instance_name"] == "Depressionsbot"
    assert payload[0]["status"] == "dry_run"
    assert payload[0]["point_count"] == 2
