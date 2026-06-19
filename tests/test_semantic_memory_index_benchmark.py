from __future__ import annotations

from TeeBotus.embedding import FakeEmbeddingProvider
from scripts import benchmark_semantic_memory_indexes as semantic_bench


def test_semantic_memory_benchmark_dataset_contains_all_query_targets() -> None:
    ids, _texts = semantic_bench._dataset(100)
    query_targets = {expected_id for _query, expected_id in semantic_bench._queries()}

    assert query_targets
    assert query_targets.issubset(set(ids))


def test_semantic_memory_benchmark_provider_specs_include_1024d_side_index() -> None:
    specs = semantic_bench._provider_specs([64, 384, 1024], env={})
    by_label = {spec["label"]: spec for spec in specs}

    assert by_label["hash_1024d"]["dimensions"] == 1024
    assert by_label["local_sentence_transformer_384d"]["provider"] == "sentence-transformers"
    assert by_label["local_sentence_transformer_1024d"]["model"] == "BAAI/bge-m3"


def test_semantic_memory_benchmark_local_hash_result_shape() -> None:
    spec = {
        "label": "hash_32d",
        "kind": "hash",
        "provider": "hash",
        "model": "teebotus-test-hash",
        "dimensions": 32,
    }
    provider = FakeEmbeddingProvider(model_name="teebotus-test-hash", dimensions=32)

    result = semantic_bench._benchmark_local(provider, spec=spec, size=100, batch_size=25)

    assert result["status"] == "ok"
    assert result["provider_label"] == "hash_32d"
    assert result["dimensions"] == 32
    assert result["entries"] == 100
    assert result["queries"] == len(semantic_bench._queries())
    assert 0.0 <= result["recall_at_5"] <= 1.0
    assert result["float32_vector_bytes"] == 100 * 32 * 4
