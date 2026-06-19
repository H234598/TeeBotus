from __future__ import annotations

import json
import os

from TeeBotus.embedding.cli import main as embedding_cli_main
from TeeBotus.embedding.config import EmbeddingConfig
from TeeBotus.embedding.rebuild import (
    ensure_qdrant_collections_for_instances,
    rebuild_qdrant_bibliothekar_indexes,
    rebuild_qdrant_memory_indexes,
)
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, telegram_identity_key
from TeeBotus.runtime.qdrant import QDRANT_BIBLIOTHEKAR_COLLECTION, QDRANT_USER_MEMORY_COLLECTION, QdrantCollectionResult


def test_rebuild_qdrant_memory_indexes_discovers_accounts_and_uses_account_store_truth(tmp_path):
    calls: list[tuple[str, str, str | None, str, str, int, bool]] = []

    class FakeQdrantMemoryIndex:
        def __init__(self, *, url=None, collection, embedding_provider, **_kwargs) -> None:
            self.url = url
            self.collection = collection
            self.embedding_provider = embedding_provider

        def rebuild(self, *, account_store, instance_name: str, account_id: str, include_legacy_raw_account_id_cleanup: bool = False):
            calls.append(
                (
                    instance_name,
                    account_id,
                    self.url,
                    self.collection,
                    self.embedding_provider.model_name,
                    self.embedding_provider.dimensions,
                    include_legacy_raw_account_id_cleanup,
                )
            )
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

    assert calls == [("Depressionsbot", account_id, "http://localhost:6334", QDRANT_USER_MEMORY_COLLECTION, "custom-memory-model", 32, False)]
    assert len(results) == 1
    assert results[0].status == "rebuilt"
    assert results[0].point_count == 2
    assert results[0].point_ids == ("point:mem_sleep", "point:mem_plan")
    assert results[0].qdrant_url == "http://localhost:6334"
    assert results[0].collection_name == QDRANT_USER_MEMORY_COLLECTION
    assert results[0].embedding_provider == "hash"
    assert results[0].embedding_model == "custom-memory-model"
    assert results[0].embedding_dimensions == 32


def test_rebuild_qdrant_memory_indexes_ignores_empty_placeholder_account_dirs(tmp_path):
    calls: list[str] = []

    class FakeQdrantMemoryIndex:
        def __init__(self, **_kwargs) -> None:
            pass

        def rebuild(self, *, account_store, instance_name: str, account_id: str, include_legacy_raw_account_id_cleanup: bool = False):
            calls.append(instance_name)
            return tuple(f"point:{entry['id']}" for entry in account_store.read_memory_entries(account_id))

    instances_dir = tmp_path / "instances"
    (instances_dir / "all" / "data" / "accounts").mkdir(parents=True)
    store = AccountStore(instances_dir / "Depressionsbot" / "data" / "accounts", "Depressionsbot", StaticSecretProvider(b"a" * 32))
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.append_structured_memory_entry(account_id, {"id": "mem_sleep", "user_text": "Schlaf"})

    results = rebuild_qdrant_memory_indexes(
        instances_dir=instances_dir,
        secret_provider=StaticSecretProvider(b"a" * 32),
        qdrant_index_factory=FakeQdrantMemoryIndex,
    )

    assert calls == ["Depressionsbot"]
    assert [result.instance_name for result in results] == ["Depressionsbot"]


def test_rebuild_qdrant_memory_indexes_uses_instance_memory_search_config_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr("TeeBotus.instructions.PROJECT_ROOT", tmp_path)
    calls: list[tuple[str, str, str, str, str, int, bool]] = []

    class FakeQdrantMemoryIndex:
        def __init__(self, *, url=None, collection, embedding_provider, **_kwargs) -> None:
            self.url = str(url)
            self.collection = str(collection)
            self.embedding_provider = embedding_provider

        def rebuild(self, *, account_store, instance_name: str, account_id: str, include_legacy_raw_account_id_cleanup: bool = False):
            calls.append(
                (
                    instance_name,
                    account_id,
                    self.url,
                    self.collection,
                    self.embedding_provider.model_name,
                    self.embedding_provider.dimensions,
                    include_legacy_raw_account_id_cleanup,
                )
            )
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

    assert calls == [("Depressionsbot", account_id, "http://localhost:6334", QDRANT_USER_MEMORY_COLLECTION, "instance-memory-model", 48, False)]
    assert results[0].status == "rebuilt"
    assert results[0].point_count == 1
    assert results[0].qdrant_url == "http://localhost:6334"
    assert results[0].collection_name == QDRANT_USER_MEMORY_COLLECTION
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


def test_rebuild_qdrant_bibliothekar_indexes_uses_local_store_chunks(tmp_path):
    calls: list[tuple[str, str, str, int, list[str]]] = []

    class FakeQdrantBibliothekarIndex:
        def __init__(self, *, url=None, collection, embedding_provider, **_kwargs) -> None:
            self.url = str(url)
            self.collection = collection
            self.embedding_provider = embedding_provider

        def index_chunks(self, *, instance_name: str, chunks):
            chunk_list = list(chunks)
            calls.append(
                (
                    instance_name,
                    self.url,
                    self.embedding_provider.model_name,
                    self.embedding_provider.dimensions,
                    [str(chunk["chunk_id"]) for chunk in chunk_list],
                )
            )
            return tuple(f"{self.collection}:{chunk['chunk_id']}" for chunk in chunk_list)

    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    library_dir = instance_dir / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text(
        """
        ## Bibliothekar
        - backend: qdrant
        - collection: therapy_books
        - qdrant_url: http://localhost:6334
        """,
        encoding="utf-8",
    )
    (library_dir / "therapie.txt").write_text("Schlafhygiene und Tagesstruktur helfen bei Depression.", encoding="utf-8")

    results = rebuild_qdrant_bibliothekar_indexes(
        instances_dir=instances_dir,
        qdrant_index_factory=FakeQdrantBibliothekarIndex,
        embedding_config=EmbeddingConfig(provider="hash", model_name="custom-book-model", dimensions=32),
    )

    assert len(results) == 1
    assert results[0].status == "rebuilt"
    assert results[0].chunk_count == 1
    assert results[0].point_count == 1
    assert results[0].collection_name == "therapy_books"
    assert results[0].qdrant_url == "http://localhost:6334"
    assert results[0].embedding_provider == "hash"
    assert results[0].embedding_model == "custom-book-model"
    assert results[0].embedding_dimensions == 32
    assert calls == [("Depressionsbot", "http://localhost:6334", "custom-book-model", 32, [results[0].point_ids[0].split(":", 1)[1]])]


def test_rebuild_qdrant_bibliothekar_indexes_dry_run_avoids_qdrant_writes(tmp_path):
    class UnexpectedQdrantBibliothekarIndex:
        def __init__(self, **_kwargs) -> None:
            raise AssertionError("dry-run must not create a Bibliothekar Qdrant index")

    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    library_dir = instance_dir / "data" / "Bibliothek"
    library_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text("## Bibliothekar\n- backend: qdrant\n", encoding="utf-8")
    (library_dir / "therapie.txt").write_text("Aktivierung und Schlaf.", encoding="utf-8")

    results = rebuild_qdrant_bibliothekar_indexes(
        instances_dir=instances_dir,
        instance_names=("Depressionsbot",),
        dry_run=True,
        qdrant_index_factory=UnexpectedQdrantBibliothekarIndex,
    )

    assert len(results) == 1
    assert results[0].status == "dry_run"
    assert results[0].chunk_count == 1
    assert results[0].point_count == 1
    assert results[0].point_ids == ()
    assert results[0].embedding_provider == "fake"
    assert results[0].embedding_model == "teebotus-fake-bibliothekar-embedding-v1"


def test_rebuild_qdrant_memory_indexes_rejects_remote_account_memory_embeddings(tmp_path):
    class UnexpectedQdrantMemoryIndex:
        def __init__(self, **_kwargs) -> None:
            raise AssertionError("remote account-memory embedding config must be rejected before Qdrant writes")

    instances_dir = tmp_path / "instances"
    store = AccountStore(instances_dir / "Depressionsbot" / "data" / "accounts", "Depressionsbot", StaticSecretProvider(b"a" * 32))
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.append_structured_memory_entry(account_id, {"id": "mem_sleep", "user_text": "Schlaf"})

    results = rebuild_qdrant_memory_indexes(
        instances_dir=instances_dir,
        secret_provider=StaticSecretProvider(b"a" * 32),
        embedding_config=EmbeddingConfig(provider="hf", model_name="intfloat/multilingual-e5-small", dimensions=384),
        qdrant_index_factory=UnexpectedQdrantMemoryIndex,
    )

    assert len(results) == 1
    assert results[0].status == "error"
    assert results[0].point_count == 0
    assert "Account-memory embeddings require a local endpoint" in results[0].error


def test_rebuild_qdrant_memory_indexes_dry_run_rejects_remote_account_memory_embeddings(tmp_path):
    class UnexpectedQdrantMemoryIndex:
        def __init__(self, **_kwargs) -> None:
            raise AssertionError("dry-run must validate config without creating a Qdrant index")

    instances_dir = tmp_path / "instances"
    store = AccountStore(instances_dir / "Depressionsbot" / "data" / "accounts", "Depressionsbot", StaticSecretProvider(b"a" * 32))
    store.resolve_or_create_account(telegram_identity_key(1))

    results = rebuild_qdrant_memory_indexes(
        instances_dir=instances_dir,
        secret_provider=StaticSecretProvider(b"a" * 32),
        embedding_config=EmbeddingConfig(provider="hf", model_name="intfloat/multilingual-e5-small", dimensions=384),
        dry_run=True,
        qdrant_index_factory=UnexpectedQdrantMemoryIndex,
    )

    assert len(results) == 1
    assert results[0].status == "error"
    assert results[0].point_count == 0
    assert "Account-memory embeddings require a local endpoint" in results[0].error


def test_rebuild_qdrant_memory_indexes_can_explicitly_request_legacy_raw_cleanup(tmp_path):
    calls: list[bool] = []

    class FakeQdrantMemoryIndex:
        def __init__(self, **_kwargs) -> None:
            pass

        def rebuild(self, *, account_store, instance_name: str, account_id: str, include_legacy_raw_account_id_cleanup: bool = False):
            calls.append(include_legacy_raw_account_id_cleanup)
            return tuple(f"point:{entry['id']}" for entry in account_store.read_memory_entries(account_id))

    instances_dir = tmp_path / "instances"
    store = AccountStore(instances_dir / "Depressionsbot" / "data" / "accounts", "Depressionsbot", StaticSecretProvider(b"a" * 32))
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.append_structured_memory_entry(account_id, {"id": "mem_sleep", "user_text": "Schlaf"})

    results = rebuild_qdrant_memory_indexes(
        instances_dir=instances_dir,
        secret_provider=StaticSecretProvider(b"a" * 32),
        include_legacy_raw_account_id_cleanup=True,
        qdrant_index_factory=FakeQdrantMemoryIndex,
    )

    assert calls == [True]
    assert results[0].status == "rebuilt"


def test_embedding_cli_memory_rebuild_dry_run_json(monkeypatch, capsys, tmp_path):
    def fake_rebuild(**kwargs):
        assert kwargs["instances_dir"] == str(tmp_path / "instances")
        assert kwargs["instance_names"] == ["Depressionsbot"]
        assert kwargs["account_ids"] == []
        assert kwargs["collection_name"] == QDRANT_USER_MEMORY_COLLECTION
        assert kwargs["dry_run"] is True
        assert kwargs["include_legacy_raw_account_id_cleanup"] is False
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


def test_embedding_cli_memory_rebuild_passes_explicit_legacy_raw_cleanup(monkeypatch, capsys, tmp_path):
    def fake_rebuild(**kwargs):
        assert kwargs["include_legacy_raw_account_id_cleanup"] is True
        from TeeBotus.embedding.rebuild import QdrantMemoryRebuildResult

        return (QdrantMemoryRebuildResult("Depressionsbot", "a" * 128, "rebuilt", point_count=1),)

    monkeypatch.setattr("TeeBotus.embedding.cli.rebuild_qdrant_memory_indexes", fake_rebuild)

    assert (
        embedding_cli_main(
            [
                "--instances-dir",
                str(tmp_path / "instances"),
                "memory-rebuild",
                "--include-legacy-raw-account-id-cleanup",
            ]
        )
        == 0
    )

    assert "status=rebuilt" in capsys.readouterr().out


def test_embedding_cli_memory_rebuild_can_target_1024d_side_index(monkeypatch, capsys, tmp_path):
    def fake_rebuild(**kwargs):
        assert kwargs["collection_name"] == "teebotus_user_memory_1024d"
        assert kwargs["embedding_overrides"] == {
            "provider": "sentence-transformers",
            "model_name": "BAAI/bge-m3",
            "dimensions": 1024,
        }
        from TeeBotus.embedding.rebuild import QdrantMemoryRebuildResult

        return (
            QdrantMemoryRebuildResult(
                "Depressionsbot",
                "a" * 128,
                "dry_run",
                point_count=2,
                collection_name="teebotus_user_memory_1024d",
                embedding_provider="sentence-transformers",
                embedding_model="BAAI/bge-m3",
                embedding_dimensions=1024,
            ),
        )

    monkeypatch.setattr("TeeBotus.embedding.cli.rebuild_qdrant_memory_indexes", fake_rebuild)

    assert (
        embedding_cli_main(
            [
                "--instances-dir",
                str(tmp_path / "instances"),
                "memory-rebuild",
                "--dry-run",
                "--side-index-dimensions",
                "1024",
                "--embedding-provider",
                "sentence-transformers",
                "--embedding-model",
                "BAAI/bge-m3",
                "--embedding-dimensions",
                "1024",
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "collection=teebotus_user_memory_1024d" in output


def test_embedding_cli_memory_rebuild_loads_local_dotenv_without_overriding_env(monkeypatch, tmp_path):
    instances_dir = tmp_path / "instances"
    instances_dir.mkdir()
    (tmp_path / ".env").write_text(
        "TEEBOTUS_ACCOUNT_MEMORY_BACKEND=sqlite\n"
        "TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH=from-dotenv.sqlite3\n"
        "TEEBOTUS_ACCOUNT_MEMORY_SQLITE_FALLBACK_PATH='quoted-fallback.sqlite3'\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", raising=False)
    monkeypatch.setenv("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", "from-shell.sqlite3")
    captured_env: dict[str, str] = {}

    def fake_rebuild(**_kwargs):
        captured_env["backend"] = os.environ.get("TEEBOTUS_ACCOUNT_MEMORY_BACKEND", "")
        captured_env["path"] = os.environ.get("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH", "")
        captured_env["fallback"] = os.environ.get("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_FALLBACK_PATH", "")
        return ()

    monkeypatch.setattr("TeeBotus.embedding.cli.rebuild_qdrant_memory_indexes", fake_rebuild)

    assert embedding_cli_main(["--instances-dir", str(instances_dir), "memory-rebuild"]) == 0

    assert captured_env == {
        "backend": "sqlite",
        "path": "from-shell.sqlite3",
        "fallback": "quoted-fallback.sqlite3",
    }
    assert os.environ.get("TEEBOTUS_ACCOUNT_MEMORY_BACKEND") is None
    assert os.environ.get("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_PATH") == "from-shell.sqlite3"
    assert os.environ.get("TEEBOTUS_ACCOUNT_MEMORY_SQLITE_FALLBACK_PATH") is None


def test_embedding_cli_bibliothekar_rebuild_dry_run_json(monkeypatch, capsys, tmp_path):
    def fake_rebuild(**kwargs):
        assert kwargs["instances_dir"] == str(tmp_path / "instances")
        assert kwargs["instance_names"] == ["Depressionsbot"]
        assert kwargs["qdrant_url"] == "http://127.0.0.1:6334"
        assert kwargs["dry_run"] is True
        assert kwargs["embedding_overrides"] == {
            "provider": "hash",
            "model_name": "custom-book-model",
            "dimensions": 32,
        }
        from TeeBotus.embedding.rebuild import QdrantBibliothekarRebuildResult

        return (
            QdrantBibliothekarRebuildResult(
                "Depressionsbot",
                "dry_run",
                chunk_count=2,
                point_count=2,
                qdrant_url="http://127.0.0.1:6334",
                collection_name=QDRANT_BIBLIOTHEKAR_COLLECTION,
                embedding_provider="hash",
                embedding_model="custom-book-model",
                embedding_dimensions=32,
            ),
        )

    monkeypatch.setattr("TeeBotus.embedding.cli.rebuild_qdrant_bibliothekar_indexes", fake_rebuild)

    assert (
        embedding_cli_main(
            [
                "--instances-dir",
                str(tmp_path / "instances"),
                "--instance",
                "Depressionsbot",
                "bibliothekar-rebuild",
                "--json",
                "--dry-run",
                "--qdrant-url",
                "http://127.0.0.1:6334",
                "--embedding-provider",
                "hash",
                "--embedding-model",
                "custom-book-model",
                "--embedding-dimensions",
                "32",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["instance_name"] == "Depressionsbot"
    assert payload[0]["status"] == "dry_run"
    assert payload[0]["chunk_count"] == 2
    assert payload[0]["collection_name"] == QDRANT_BIBLIOTHEKAR_COLLECTION


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


def test_ensure_qdrant_collections_for_instances_rejects_remote_memory_embedding_config(monkeypatch, tmp_path):
    monkeypatch.setattr("TeeBotus.instructions.PROJECT_ROOT", tmp_path)

    def unexpected_ensure(**_kwargs):
        raise AssertionError("invalid account-memory embedding configs must not touch Qdrant")

    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    instance_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text(
        """
        ## Memory Search
        - semantic_enabled: true
        - semantic_backend: qdrant
        - embedding_provider: hf
        - embedding_model: intfloat/multilingual-e5-small
        - embedding_dimensions: 384
        """,
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
    assert results[0].vector_size == 384
    assert results[0].embedding_model == "intfloat/multilingual-e5-small"
    assert "invalid user-memory embedding config" in results[0].error
    assert "Account-memory embeddings require a local endpoint" in results[0].error


def test_embedding_cli_collections_ensure_json(monkeypatch, capsys, tmp_path):
    def fake_ensure(**kwargs):
        assert kwargs["instances_dir"] == str(tmp_path / "instances")
        assert kwargs["instance_names"] == ["Depressionsbot"]
        assert kwargs["qdrant_url"] == "http://127.0.0.1:6334"
        assert kwargs["include_memory_side_dimensions"] == [1024]
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
                "--include-memory-side-index",
                "1024",
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


def test_embedding_cli_collections_ensure_rejects_remote_memory_embedding_config(capsys, tmp_path):
    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    instance_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text(
        """
        ## Memory Search
        - semantic_enabled: true
        - semantic_backend: qdrant
        """,
        encoding="utf-8",
    )

    result = embedding_cli_main(
        [
            "--instances-dir",
            str(instances_dir),
            "--instance",
            "Depressionsbot",
            "collections-ensure",
            "--embedding-provider",
            "hf",
            "--embedding-model",
            "intfloat/multilingual-e5-small",
            "--embedding-dimensions",
            "384",
        ]
    )

    assert result == 1
    output = capsys.readouterr().out
    assert "status=config_conflict" in output
    assert "Account-memory embeddings require a local endpoint" in output
