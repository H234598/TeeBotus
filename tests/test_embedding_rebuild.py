from __future__ import annotations

import json

from TeeBotus.embedding.cli import main as embedding_cli_main
from TeeBotus.embedding.config import EmbeddingConfig
from TeeBotus.embedding.rebuild import ensure_qdrant_collections_for_instances, rebuild_qdrant_memory_indexes
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, telegram_identity_key
from TeeBotus.runtime.qdrant import QDRANT_BIBLIOTHEKAR_COLLECTION, QDRANT_USER_MEMORY_COLLECTION, QdrantCollectionResult


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
    assert results[0].qdrant_url == "http://localhost:6334"
    assert results[0].embedding_provider == "hash"
    assert results[0].embedding_model == "custom-memory-model"
    assert results[0].embedding_dimensions == 32


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
    assert results[0].qdrant_url == "http://localhost:6334"
    assert results[0].embedding_provider == "hash"
    assert results[0].embedding_model == "instance-memory-model"
    assert results[0].embedding_dimensions == 48


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
    assert payload[0]["embedding_model"] == ""


def test_ensure_qdrant_collections_for_instances_uses_instance_memory_search_config(monkeypatch, tmp_path):
    monkeypatch.setattr("TeeBotus.instructions.PROJECT_ROOT", tmp_path)
    calls: list[tuple[str, list[tuple[str, int, str]]]] = []

    def fake_ensure(**kwargs):
        specs = kwargs["specs"]
        calls.append((kwargs["url"], [(spec.name, spec.vector_size, spec.embedding_model) for spec in specs]))
        return tuple(QdrantCollectionResult(spec.name, kwargs["url"], "ready", True) for spec in specs)

    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    instance_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text(
        """
        ## Memory Search
        - qdrant_url: http://localhost:6334
        - embedding_model: instance-memory-model
        - embedding_dimensions: 48
        """,
        encoding="utf-8",
    )

    results = ensure_qdrant_collections_for_instances(
        instances_dir=instances_dir,
        qdrant_ensure_factory=fake_ensure,
    )

    assert calls == [
        (
            "http://localhost:6334",
            [
                (QDRANT_USER_MEMORY_COLLECTION, 48, "instance-memory-model"),
                (QDRANT_BIBLIOTHEKAR_COLLECTION, 1024, "BAAI/bge-m3"),
            ],
        )
    ]
    assert [result.collection_name for result in results] == [QDRANT_USER_MEMORY_COLLECTION, QDRANT_BIBLIOTHEKAR_COLLECTION]
    assert all(result.ok for result in results)
    assert results[0].vector_size == 48
    assert results[0].embedding_model == "instance-memory-model"


def test_ensure_qdrant_collections_for_instances_reports_conflicting_memory_configs(monkeypatch, tmp_path):
    monkeypatch.setattr("TeeBotus.instructions.PROJECT_ROOT", tmp_path)

    def unexpected_ensure(**_kwargs):
        raise AssertionError("conflicting configs must not touch Qdrant")

    instances_dir = tmp_path / "instances"
    first = instances_dir / "A"
    second = instances_dir / "B"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "Bot_Verhalten.md").write_text(
        "## Memory Search\n- embedding_model: model-a\n- embedding_dimensions: 48\n",
        encoding="utf-8",
    )
    (second / "Bot_Verhalten.md").write_text(
        "## Memory Search\n- embedding_model: model-b\n- embedding_dimensions: 64\n",
        encoding="utf-8",
    )

    results = ensure_qdrant_collections_for_instances(
        instances_dir=instances_dir,
        qdrant_ensure_factory=unexpected_ensure,
    )

    assert len(results) == 1
    assert results[0].collection_name == QDRANT_USER_MEMORY_COLLECTION
    assert results[0].status == "config_conflict"
    assert results[0].ok is False
    assert "conflicting user-memory embedding configs" in results[0].error
    assert "A:model-a/48" in results[0].error
    assert "B:model-b/64" in results[0].error


def test_embedding_cli_collections_ensure_json(monkeypatch, capsys, tmp_path):
    def fake_ensure(**kwargs):
        assert kwargs["instances_dir"] == str(tmp_path / "instances")
        assert kwargs["instance_names"] == ["Depressionsbot"]
        assert kwargs["qdrant_url"] == "http://127.0.0.1:6334"
        assert kwargs["embedding_overrides"] == {
            "provider": "hash",
            "model_name": "custom-model",
            "dimensions": 32,
        }
        from TeeBotus.embedding.rebuild import QdrantCollectionEnsureResult

        return (
            QdrantCollectionEnsureResult(
                ("Depressionsbot",),
                QDRANT_USER_MEMORY_COLLECTION,
                "ready",
                True,
                qdrant_url="http://127.0.0.1:6334",
                vector_size=32,
                embedding_model="custom-model",
            ),
        )

    monkeypatch.setattr("TeeBotus.embedding.cli.ensure_qdrant_collections_for_instances", fake_ensure)

    assert (
        embedding_cli_main(
            [
                "--instances-dir",
                str(tmp_path / "instances"),
                "--instance",
                "Depressionsbot",
                "--json",
                "collections-ensure",
                "--qdrant-url",
                "http://127.0.0.1:6334",
                "--embedding-provider",
                "hash",
                "--embedding-model",
                "custom-model",
                "--embedding-dimensions",
                "32",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["collection_name"] == QDRANT_USER_MEMORY_COLLECTION
    assert payload[0]["vector_size"] == 32
    assert payload[0]["embedding_model"] == "custom-model"
