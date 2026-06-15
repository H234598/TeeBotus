from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable

from TeeBotus.instructions import BotInstructions, InstructionStore
from TeeBotus.runtime.bibliothekar import BibliothekarStore
from TeeBotus.runtime.bibliothekar_service import BibliothekarService, check_bibliothekar_service


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "status":
        return _status(args)
    if args.command == "index":
        return _index(args)
    if args.command == "query":
        return _query(args)
    parser.print_help()
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TeeBotus Bibliothekar service CLI.")
    parser.add_argument("--instances-dir", default="instances")
    parser.add_argument("--instance", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    subparsers = parser.add_subparsers(dest="command")

    status = subparsers.add_parser("status", help="Show Bibliothekar backend status.")
    status.set_defaults(command="status")

    index = subparsers.add_parser("index", help="Index Bibliothek folders.")
    index.add_argument("--source", default="")
    index.add_argument("--dry-run", action="store_true")
    index.set_defaults(command="index")

    query = subparsers.add_parser("query", help="Query indexed Bibliothekar chunks.")
    query.add_argument("query")
    query.add_argument("--top-k", type=int, default=3)
    query.add_argument("--max-prompt-chars", type=int, default=5000)
    query.add_argument("--max-quote-chars", type=int, default=900)
    query.set_defaults(command="query")
    return parser


def _status(args: argparse.Namespace) -> int:
    instances_dir = Path(args.instances_dir)
    rows = []
    for instance_name in _resolve_instances(instances_dir, args.instance):
        instructions = _load_instructions(instances_dir, instance_name)
        health = check_bibliothekar_service(instance_name, instances_dir, instructions)
        rows.append(
            {
                "instance": health.instance_name,
                "backend": health.backend,
                "store": health.store,
                "collection": health.collection,
                "status": health.status,
                "documents": health.documents,
                "chunks": health.chunks,
                "error": health.error,
            }
        )
    return _emit_rows(rows, args.json, "{instance}: backend={backend} store={store} collection={collection} status={status} documents={documents} chunks={chunks}{error_suffix}")


def _index(args: argparse.Namespace) -> int:
    instances_dir = Path(args.instances_dir)
    rows = []
    for instance_name in _resolve_instances(instances_dir, args.instance):
        instructions = _load_instructions(instances_dir, instance_name)
        if args.source:
            index = _index_source(instance_name, instances_dir, Path(args.source), dry_run=args.dry_run, instructions=instructions)
            library_dir = str(Path(args.source))
        else:
            store = BibliothekarStore(instance_name, instances_dir)
            if args.dry_run:
                index = _dry_run_index(store)
            else:
                index = BibliothekarService.from_instructions(instance_name, instances_dir, instructions).rebuild()
            library_dir = str(store.library_dir)
        rows.append(
            {
                "instance": instance_name,
                "library_dir": library_dir,
                "documents": len(index.get("documents", {})) if isinstance(index.get("documents"), dict) else 0,
                "chunks": int(index.get("chunk_count") or 0),
                "dry_run": bool(args.dry_run),
            }
        )
    return _emit_rows(rows, args.json, "{instance}: {documents} Dokumente, {chunks} Chunks, dry_run={dry_run}, Ordner: {library_dir}")


def _query(args: argparse.Namespace) -> int:
    instances_dir = Path(args.instances_dir)
    rows = []
    for instance_name in _resolve_instances(instances_dir, args.instance):
        instructions = _load_instructions(instances_dir, instance_name)
        service = BibliothekarService.from_instructions(instance_name, instances_dir, instructions)
        selection = service.search(
            args.query,
            max_prompt_chars=max(1, int(args.max_prompt_chars)),
            max_chunks=max(1, int(args.top_k)),
            max_quote_chars=max(1, int(args.max_quote_chars)),
        )
        rows.append(
            {
                "instance": instance_name,
                "backend": service.backend_name,
                "selected_ids": list(selection.selected_ids),
                "prompt_text": selection.prompt_text,
            }
        )
    if args.json:
        print(json.dumps({"results": rows}, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            print(f"{row['instance']}: backend={row['backend']} selected={len(row['selected_ids'])}")
            if row["prompt_text"]:
                print(row["prompt_text"])
    return 0


def _index_source(instance_name: str, instances_dir: Path, source: Path, *, dry_run: bool, instructions: BotInstructions) -> dict[str, Any]:
    if not source.exists():
        raise SystemExit(f"source does not exist: {source}")
    if not dry_run:
        store = BibliothekarStore(instance_name, instances_dir)
        store.ensure()
        if source.is_dir():
            for path in source.rglob("*"):
                if path.is_file():
                    destination = store.library_dir / path.relative_to(source)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, destination)
        else:
            destination = store.library_dir / source.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        return BibliothekarService.from_instructions(instance_name, instances_dir, instructions).rebuild()
    with tempfile.TemporaryDirectory(prefix="teebotus-bibliothekar-") as tmp:
        tmp_instances = Path(tmp) / "instances"
        tmp_library = tmp_instances / instance_name / "data" / "Bibliothek"
        tmp_library.mkdir(parents=True)
        if source.is_dir():
            shutil.copytree(source, tmp_library, dirs_exist_ok=True)
        else:
            shutil.copy2(source, tmp_library / source.name)
        return BibliothekarStore(instance_name, tmp_instances).rebuild()


def _dry_run_index(store: BibliothekarStore) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="teebotus-bibliothekar-") as tmp:
        tmp_instances = Path(tmp) / "instances"
        tmp_library = tmp_instances / store.instance_name / "data" / "Bibliothek"
        tmp_library.mkdir(parents=True)
        if store.library_dir.exists():
            shutil.copytree(store.library_dir, tmp_library, dirs_exist_ok=True)
        return BibliothekarStore(store.instance_name, tmp_instances).rebuild()


def _resolve_instances(instances_dir: Path, requested: Iterable[str]) -> tuple[str, ...]:
    explicit = tuple(str(item).strip() for item in requested if str(item).strip())
    if explicit:
        return explicit
    if not instances_dir.exists():
        return ()
    return tuple(
        path.name
        for path in sorted(instances_dir.iterdir())
        if path.is_dir() and ((path / "Bot_Verhalten.md").exists() or (path / "data").exists())
    )


def _load_instructions(instances_dir: Path, instance_name: str) -> BotInstructions:
    path = instances_dir / instance_name / "Bot_Verhalten.md"
    if not path.exists():
        return BotInstructions()
    return InstructionStore(path).get()


def _emit_rows(rows: list[dict[str, Any]], as_json: bool, template: str) -> int:
    if as_json:
        print(json.dumps({"results": rows}, ensure_ascii=False, indent=2))
        return 0
    for row in rows:
        row = dict(row)
        row["error_suffix"] = f" error={row['error']}" if row.get("error") else ""
        print(template.format(**row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
