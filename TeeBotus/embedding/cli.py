from __future__ import annotations

import argparse
import json
import os
from contextlib import contextmanager
from dataclasses import asdict
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from TeeBotus.embedding.rebuild import (
    ensure_qdrant_collections_for_instances,
    rebuild_qdrant_bibliothekar_indexes,
    rebuild_qdrant_codex_history_indexes,
    rebuild_qdrant_memory_indexes,
)
from TeeBotus.runtime.qdrant import (
    QDRANT_CODEX_HISTORY_COLLECTION,
    QDRANT_USER_MEMORY_COLLECTION,
    qdrant_user_memory_side_collection,
    qdrant_user_memory_side_collection_spec,
)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    with _dotenv_defaults_for_instances_dir(args.instances_dir):
        if args.command == "memory-rebuild":
            _validate_memory_rebuild_args(parser, args)
            results = rebuild_qdrant_memory_indexes(
                instances_dir=args.instances_dir,
                instance_names=args.instance,
                account_ids=args.account_id,
                qdrant_url=args.qdrant_url or None,
                collection_name=_memory_collection_from_args(args),
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
                include_memory_side_dimensions=args.include_memory_side_index,
                include_codex_history=bool(args.include_codex_history),
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
        if args.command == "codex-history-rebuild":
            results = rebuild_qdrant_codex_history_indexes(
                instances_dir=args.instances_dir,
                instance_names=args.instance,
                qdrant_url=args.qdrant_url or None,
                collection_name=args.collection or QDRANT_CODEX_HISTORY_COLLECTION,
                repo=args.repo,
                limit=int(args.limit or 0),
                embedding_overrides=_embedding_overrides_from_args(args),
                dry_run=args.dry_run,
            )
            if args.json:
                print(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2))
            else:
                for result in results:
                    print(_format_codex_history_rebuild_result(result))
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
    memory.add_argument("--collection", default="", help="Override target Qdrant collection. Defaults to teebotus_user_memory.")
    memory.add_argument("--side-index-dimensions", type=int, default=None, help="Use the conventional optional side-index collection for this vector size, e.g. 384 or 1024.")
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
    collections.add_argument(
        "--include-memory-side-index",
        type=int,
        action="append",
        default=[],
        help="Also ensure an optional usermemory side-index collection for this vector size. Can be repeated, e.g. 384 and 1024.",
    )
    collections.add_argument("--include-codex-history", action="store_true", help="Also ensure the admin-only Codex-History Qdrant collection.")
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

    codex_history = subparsers.add_parser("codex-history-rebuild", help="Rebuild admin-only Qdrant Codex-History chunk cache from codex_history_outbox.")
    codex_history.add_argument("--json", dest="json", action="store_true", default=argparse.SUPPRESS, help="Emit JSON output.")
    codex_history.add_argument("--qdrant-url", default="", help="Override Qdrant URL from the instance Bibliothekar config.")
    codex_history.add_argument("--collection", default=QDRANT_CODEX_HISTORY_COLLECTION, help="Override target Qdrant collection.")
    codex_history.add_argument("--repo", default="", help="Limit rebuild to repo name, repo id, root, or remote substring.")
    codex_history.add_argument("--limit", type=int, default=0, help="Limit to the latest N Codex-History summaries after repo filtering.")
    codex_history.add_argument("--embedding-provider", default=None, help="Override Codex-History embedding provider: fake/hash or hf/tei.")
    codex_history.add_argument("--embedding-model", default=None, help="Override Codex-History embedding model name.")
    codex_history.add_argument("--embedding-dimensions", type=int, default=None, help="Override Codex-History embedding vector dimensions.")
    codex_history.add_argument("--embedding-endpoint", default=None, help="Override HF/TEI/OpenAI-compatible embedding endpoint.")
    codex_history.add_argument("--embedding-api-key-env", default=None, help="Override embedding API key environment variable.")
    codex_history.add_argument("--dry-run", action="store_true", help="Count Codex-History chunks without writing Qdrant.")
    codex_history.set_defaults(command="codex-history-rebuild")
    return parser


def _embedding_overrides_from_args(args: argparse.Namespace) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    side_index_spec = None
    if getattr(args, "command", "") == "memory-rebuild" and getattr(args, "side_index_dimensions", None) is not None:
        side_index_spec = qdrant_user_memory_side_collection_spec(int(args.side_index_dimensions))
    if args.embedding_provider is not None:
        overrides["provider"] = args.embedding_provider
    if args.embedding_model is not None:
        overrides["model_name"] = args.embedding_model
    elif side_index_spec is not None and side_index_spec.embedding_model:
        overrides["model_name"] = side_index_spec.embedding_model
    if args.embedding_dimensions is not None:
        overrides["dimensions"] = args.embedding_dimensions
    elif side_index_spec is not None:
        overrides["dimensions"] = side_index_spec.vector_size
    if args.embedding_endpoint is not None:
        overrides["endpoint"] = args.embedding_endpoint
    if args.embedding_api_key_env is not None:
        overrides["api_key_env"] = args.embedding_api_key_env
    return overrides


def _memory_collection_from_args(args: argparse.Namespace) -> str:
    if getattr(args, "side_index_dimensions", None) is not None:
        return qdrant_user_memory_side_collection(int(args.side_index_dimensions))
    return str(getattr(args, "collection", "") or QDRANT_USER_MEMORY_COLLECTION).strip() or QDRANT_USER_MEMORY_COLLECTION


def _validate_memory_rebuild_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if getattr(args, "side_index_dimensions", None) is None:
        return
    try:
        side_dimensions = int(args.side_index_dimensions)
    except (TypeError, ValueError):
        parser.error("--side-index-dimensions must be a positive integer.")
        return
    if side_dimensions < 1:
        parser.error("--side-index-dimensions must be a positive integer.")
        return
    if args.embedding_dimensions is not None and int(args.embedding_dimensions) != side_dimensions:
        parser.error("--embedding-dimensions must match --side-index-dimensions for memory side-index rebuilds.")


@contextmanager
def _dotenv_defaults_for_instances_dir(instances_dir: str | Path) -> Iterator[None]:
    inserted_keys: list[str] = []
    for key, value in _read_dotenv_values(_project_root_for_instances_dir(instances_dir) / ".env").items():
        if key in os.environ:
            continue
        os.environ[key] = value
        inserted_keys.append(key)
    try:
        yield
    finally:
        for key in inserted_keys:
            os.environ.pop(key, None)


def _project_root_for_instances_dir(instances_dir: str | Path) -> Path:
    path = Path(instances_dir).expanduser()
    if path.name == "instances":
        return path.parent if str(path.parent) else Path(".")
    return path.parent


def _read_dotenv_values(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return {}
    values: dict[str, str] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", maxsplit=1)
        key = key.strip()
        if not key:
            continue
        values[key] = _clean_dotenv_value(value)
    return values


def _clean_dotenv_value(value: str) -> str:
    cleaned = str(value or "").strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        return cleaned[1:-1]
    return cleaned


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
    collection_name = str(getattr(result, "collection_name", "") or "")
    if collection_name:
        detail += f" collection={collection_name}"
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
    actual_vector_size = getattr(result, "actual_vector_size", None)
    embedding_model = str(getattr(result, "embedding_model", "") or "")
    error = str(getattr(result, "error", "") or "")
    detail = f" ok={ok}"
    if qdrant_url:
        detail += f" qdrant_url={qdrant_url}"
    if vector_size:
        detail += f" vector_size={vector_size}"
    if actual_vector_size is not None:
        detail += f" actual_vector_size={int(actual_vector_size)}"
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


def _format_codex_history_rebuild_result(result: object) -> str:
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
    return f"{instance}/codex-history: status={status}{detail}{suffix}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
