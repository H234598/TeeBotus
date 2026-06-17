from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from typing import Any

from TeeBotus.embedding.rebuild import (
    ensure_qdrant_collections_for_instances,
    rebuild_qdrant_bibliothekar_indexes,
    rebuild_qdrant_memory_indexes,
)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "memory-rebuild":
        results = rebuild_qdrant_memory_indexes(
            instances_dir=args.instances_dir,
            instance_names=args.instance,
            account_ids=args.account_id,
            qdrant_url=args.qdrant_url or None,
            embedding_overrides=_embedding_overrides_from_args(args),
            dry_run=args.dry_run,
            include_legacy_raw_account_id_cleanup=args.include_legacy_raw_account_id_cleanup,
        )
        if args.json:
            print(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2))
        else:
            for result in results:
                print(_format_memory_rebuild_result(result))
        return 1 if any(result.status == "error" for result in results) else 0
    if args.command == "collections-ensure":
        results = ensure_qdrant_collections_for_instances(
            instances_dir=args.instances_dir,
            instance_names=args.instance,
            qdrant_url=args.qdrant_url or None,
            embedding_overrides=_embedding_overrides_from_args(args),
        )
        if args.json:
            print(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2))
        else:
            for result in results:
                print(_format_collection_ensure_result(result))
        return 1 if any(not result.ok for result in results) else 0
    if args.command == "bibliothekar-rebuild":
        results = rebuild_qdrant_bibliothekar_indexes(
            instances_dir=args.instances_dir,
            instance_names=args.instance,
            qdrant_url=args.qdrant_url or None,
            embedding_overrides=_embedding_overrides_from_args(args),
            dry_run=args.dry_run,
        )
        if args.json:
            print(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2))
        else:
            for result in results:
                print(_format_bibliothekar_rebuild_result(result))
        return 1 if any(result.status == "error" for result in results) else 0
    parser.print_help()
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TeeBotus embedding and Qdrant cache maintenance.")
    parser.add_argument("--instances-dir", default="instances")
    parser.add_argument("--instance", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    subparsers = parser.add_subparsers(dest="command")

    memory = subparsers.add_parser("memory-rebuild", help="Rebuild Qdrant Usermemory cache from AccountStore.")
    memory.add_argument("--json", dest="json", action="store_true", default=argparse.SUPPRESS, help="Emit JSON output.")
    memory.add_argument("--account-id", action="append", default=[], help="Limit rebuild to one or more account IDs.")
    memory.add_argument("--qdrant-url", default="", help="Override Qdrant URL from the instance Bot_Verhalten.md Memory Search config.")
    memory.add_argument("--embedding-provider", default=None, help="Override embedding provider: hash/local_hash or hf/tei.")
    memory.add_argument("--embedding-model", default=None, help="Override embedding model name stored in Qdrant payload.")
    memory.add_argument("--embedding-dimensions", type=int, default=None, help="Override embedding vector dimensions.")
    memory.add_argument("--embedding-endpoint", default=None, help="Override HF/TEI/OpenAI-compatible embedding endpoint.")
    memory.add_argument("--embedding-api-key-env", default=None, help="Override environment variable containing the embedding API key.")
    memory.add_argument("--dry-run", action="store_true", help="Count AccountStore entries without writing Qdrant.")
    memory.add_argument(
        "--include-legacy-raw-account-id-cleanup",
        action="store_true",
        help="Also delete old Qdrant cache payloads scoped by raw account_id, including schema-less legacy payloads. This sends the account ID to local Qdrant for cleanup.",
    )
    memory.set_defaults(command="memory-rebuild")

    collections = subparsers.add_parser("collections-ensure", help="Ensure Qdrant collections using instance Memory Search config.")
    collections.add_argument("--json", dest="json", action="store_true", default=argparse.SUPPRESS, help="Emit JSON output.")
    collections.add_argument("--qdrant-url", default="", help="Override Qdrant URL from the instance Bot_Verhalten.md Memory Search config.")
    collections.add_argument("--embedding-provider", default=None, help="Override usermemory embedding provider for metadata parity.")
    collections.add_argument("--embedding-model", default=None, help="Override usermemory embedding model name.")
    collections.add_argument("--embedding-dimensions", type=int, default=None, help="Override usermemory embedding vector dimensions.")
    collections.add_argument("--embedding-endpoint", default=None, help="Override HF/TEI/OpenAI-compatible embedding endpoint metadata.")
    collections.add_argument("--embedding-api-key-env", default=None, help="Override embedding API key environment variable metadata.")
    collections.set_defaults(command="collections-ensure")

    bibliothekar = subparsers.add_parser("bibliothekar-rebuild", help="Rebuild Qdrant Bibliothekar chunk cache from local BibliothekarStore.")
    bibliothekar.add_argument("--json", dest="json", action="store_true", default=argparse.SUPPRESS, help="Emit JSON output.")
    bibliothekar.add_argument("--qdrant-url", default="", help="Override Qdrant URL from the instance Bibliothekar config.")
    bibliothekar.add_argument("--embedding-provider", default=None, help="Override Bibliothekar embedding provider: fake/hash or hf/tei.")
    bibliothekar.add_argument("--embedding-model", default=None, help="Override Bibliothekar embedding model name.")
    bibliothekar.add_argument("--embedding-dimensions", type=int, default=None, help="Override Bibliothekar embedding vector dimensions.")
    bibliothekar.add_argument("--embedding-endpoint", default=None, help="Override HF/TEI/OpenAI-compatible embedding endpoint.")
    bibliothekar.add_argument("--embedding-api-key-env", default=None, help="Override embedding API key environment variable.")
    bibliothekar.add_argument("--dry-run", action="store_true", help="Rebuild the local Bibliothekar chunk store and count chunks without writing Qdrant.")
    bibliothekar.set_defaults(command="bibliothekar-rebuild")
    return parser


def _embedding_overrides_from_args(args: argparse.Namespace) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    if args.embedding_provider is not None:
        overrides["provider"] = args.embedding_provider
    if args.embedding_model is not None:
        overrides["model_name"] = args.embedding_model
    if args.embedding_dimensions is not None:
        overrides["dimensions"] = args.embedding_dimensions
    if args.embedding_endpoint is not None:
        overrides["endpoint"] = args.embedding_endpoint
    if args.embedding_api_key_env is not None:
        overrides["api_key_env"] = args.embedding_api_key_env
    return overrides


def _format_memory_rebuild_result(result: object) -> str:
    instance = str(getattr(result, "instance_name", "") or "default")
    account_id = str(getattr(result, "account_id", "") or "<all>")
    status = str(getattr(result, "status", "") or "unknown")
    point_count = int(getattr(result, "point_count", 0) or 0)
    qdrant_url = str(getattr(result, "qdrant_url", "") or "")
    embedding_provider = str(getattr(result, "embedding_provider", "") or "")
    embedding_model = str(getattr(result, "embedding_model", "") or "")
    embedding_dimensions = int(getattr(result, "embedding_dimensions", 0) or 0)
    error = str(getattr(result, "error", "") or "")
    detail = ""
    if qdrant_url:
        detail += f" qdrant_url={qdrant_url}"
    if embedding_model:
        detail += f" embedding_provider={embedding_provider or 'unknown'} embedding_model={embedding_model} embedding_dimensions={embedding_dimensions}"
    suffix = f" error={error}" if error else ""
    return f"{instance}/{account_id}: status={status} points={point_count}{detail}{suffix}"


def _format_collection_ensure_result(result: object) -> str:
    instances = ",".join(getattr(result, "instance_names", ()) or ()) or "<all>"
    collection = str(getattr(result, "collection_name", "") or "unknown")
    status = str(getattr(result, "status", "") or "unknown")
    ok = "true" if bool(getattr(result, "ok", False)) else "false"
    qdrant_url = str(getattr(result, "qdrant_url", "") or "")
    vector_size = int(getattr(result, "vector_size", 0) or 0)
    embedding_model = str(getattr(result, "embedding_model", "") or "")
    error = str(getattr(result, "error", "") or "")
    detail = f" ok={ok}"
    if qdrant_url:
        detail += f" qdrant_url={qdrant_url}"
    if vector_size:
        detail += f" vector_size={vector_size}"
    if embedding_model:
        detail += f" embedding_model={embedding_model}"
    suffix = f" error={error}" if error else ""
    return f"{instances}/{collection}: status={status}{detail}{suffix}"


def _format_bibliothekar_rebuild_result(result: object) -> str:
    instance = str(getattr(result, "instance_name", "") or "default")
    status = str(getattr(result, "status", "") or "unknown")
    chunk_count = int(getattr(result, "chunk_count", 0) or 0)
    point_count = int(getattr(result, "point_count", 0) or 0)
    qdrant_url = str(getattr(result, "qdrant_url", "") or "")
    collection = str(getattr(result, "collection_name", "") or "")
    embedding_provider = str(getattr(result, "embedding_provider", "") or "")
    embedding_model = str(getattr(result, "embedding_model", "") or "")
    embedding_dimensions = int(getattr(result, "embedding_dimensions", 0) or 0)
    error = str(getattr(result, "error", "") or "")
    detail = f" chunks={chunk_count} points={point_count}"
    if qdrant_url:
        detail += f" qdrant_url={qdrant_url}"
    if collection:
        detail += f" collection={collection}"
    if embedding_model:
        detail += f" embedding_provider={embedding_provider or 'unknown'} embedding_model={embedding_model} embedding_dimensions={embedding_dimensions}"
    suffix = f" error={error}" if error else ""
    return f"{instance}: status={status}{detail}{suffix}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
