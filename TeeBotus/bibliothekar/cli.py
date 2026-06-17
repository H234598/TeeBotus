from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable

from TeeBotus.instructions import BotInstructions, InstructionStore
from TeeBotus.bibliothekar.source_harvester import SourceHarvester
from TeeBotus.runtime.bibliothekar import BibliothekarStore, SUPPORTED_SUFFIXES, _is_allowed_library_source_path
from TeeBotus.runtime.bibliothekar_service import BibliothekarService, check_bibliothekar_service
from TeeBotus.runtime.graphs import run_bibliothekar_deep_query


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "status":
        return _status(args)
    if args.command == "index":
        return _index(args)
    if args.command == "harvest":
        return _harvest(args)
    if args.command == "promote":
        return _promote(args)
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
    status.add_argument("--json", dest="json", action="store_true", default=argparse.SUPPRESS, help="Emit JSON output.")
    status.set_defaults(command="status")

    index = subparsers.add_parser("index", help="Index Bibliothek folders.")
    index.add_argument("--json", dest="json", action="store_true", default=argparse.SUPPRESS, help="Emit JSON output.")
    index.add_argument("--source", default="")
    index.add_argument("--dry-run", action="store_true")
    index.set_defaults(command="index")

    harvest = subparsers.add_parser("harvest", help="Gate local source files before Bibliothekar ingestion.")
    harvest.add_argument("--json", dest="json", action="store_true", default=argparse.SUPPRESS, help="Emit JSON output.")
    harvest.add_argument("source")
    harvest.add_argument("--title", default="", help="Optional source title metadata.")
    harvest.add_argument("--license", default="", help="Optional source license metadata.")
    harvest.add_argument("--claim", action="append", default=[], help="Claim extracted from the source for optional verifier checks.")
    harvest.add_argument("--evidence", action="append", default=[], help="Evidence text paired with --claim.")
    harvest.add_argument("--move", action="store_true", help="Move instead of copy after the quality gate.")
    harvest.set_defaults(command="harvest")

    promote = subparsers.add_parser("promote", help="Promote an accepted harvested source into the indexed Bibliothek.")
    promote.add_argument("--json", dest="json", action="store_true", default=argparse.SUPPRESS, help="Emit JSON output.")
    promote.add_argument("source")
    promote.add_argument("--destination-dir", default="books", help="Relative library subdirectory for promoted sources.")
    promote.add_argument("--move", action="store_true", help="Move instead of copy from accepted staging.")
    promote.set_defaults(command="promote")

    query = subparsers.add_parser("query", help="Query indexed Bibliothekar chunks.")
    query.add_argument("--json", dest="json", action="store_true", default=argparse.SUPPRESS, help="Emit JSON output.")
    query.add_argument("query")
    query.add_argument("--source", default="", help="Query a source file or directory through a temporary local fixture index.")
    query.add_argument("--top-k", type=int, default=3)
    query.add_argument("--max-prompt-chars", type=int, default=5000)
    query.add_argument("--max-quote-chars", type=int, default=900)
    query.add_argument("--category", action="append", default=[], help="Limit results to one or more indexed categories.")
    query.add_argument("--topic", action="append", default=[], help="Limit results to one or more indexed topics/keywords.")
    query.add_argument("--keyword", action="append", default=[], help="Alias for --topic.")
    query.add_argument("--file", action="append", default=[], help="Limit results to source files whose relative path contains this value.")
    query.add_argument("--relative-path", action="append", default=[], help="Alias for --file.")
    query.add_argument("--extension", action="append", default=[], help="Limit results to one or more file types such as pdf, txt or md.")
    query.add_argument("--suffix", action="append", default=[], help="Limit results to one or more file suffixes such as .pdf, .txt or .md.")
    query.add_argument("--deep", action="store_true", help="Run the optional Bibliothekar Deep Query graph pilot.")
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
                "target": health.target,
                "status": health.status,
                "documents": health.documents,
                "chunks": health.chunks,
                "error": health.error,
            }
        )
    return _emit_rows(rows, args.json, "{instance}: backend={backend} store={store} collection={collection}{target_suffix} status={status} documents={documents} chunks={chunks}{error_suffix}")


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


def _harvest(args: argparse.Namespace) -> int:
    instances_dir = Path(args.instances_dir)
    source = Path(args.source)
    if not source.exists():
        raise SystemExit(f"source does not exist: {source}")
    metadata = {key: value for key, value in {"title": args.title, "license": args.license}.items() if str(value or "").strip()}
    rows = []
    for instance_name in _resolve_instances(instances_dir, args.instance):
        store = BibliothekarStore(instance_name, instances_dir)
        harvester = SourceHarvester(store.library_dir)
        result = harvester.harvest_path(
            source,
            metadata=metadata,
            claims=tuple(str(item) for item in args.claim if str(item).strip()),
            evidence=tuple(str(item) for item in args.evidence if str(item).strip()),
            copy=not bool(args.move),
        )
        rows.append(
            {
                "instance": instance_name,
                "route": result.route,
                "decision_status": result.report.decision.status,
                "accepted_for_ingest": result.accepted_for_ingest,
                "sha256": result.sha256,
                "stored_path": str(result.stored_path or ""),
                "duplicate_of": str(result.duplicate_of or ""),
                "duplicate_suffix": f" duplicate_of={result.duplicate_of}" if result.duplicate_of else "",
            }
        )
    return _emit_rows(
        rows,
        args.json,
        "{instance}: route={route} decision={decision_status} accepted_for_ingest={accepted_for_ingest} stored_path={stored_path}{duplicate_suffix}",
    )


def _promote(args: argparse.Namespace) -> int:
    instances_dir = Path(args.instances_dir)
    source = Path(args.source)
    if not source.exists():
        raise SystemExit(f"source does not exist: {source}")
    rows = []
    for instance_name in _resolve_instances(instances_dir, args.instance):
        store = BibliothekarStore(instance_name, instances_dir)
        harvester = SourceHarvester(store.library_dir)
        result = harvester.promote_accepted(
            source,
            destination_dir=args.destination_dir,
            copy=not bool(args.move),
        )
        rows.append(
            {
                "instance": instance_name,
                "sha256": result.sha256,
                "staged_path": str(result.staged_path),
                "promoted_path": str(result.promoted_path),
                "copied": result.copied,
            }
        )
    return _emit_rows(
        rows,
        args.json,
        "{instance}: promoted_path={promoted_path} copied={copied}",
    )


def _query(args: argparse.Namespace) -> int:
    instances_dir = Path(args.instances_dir)
    rows = []
    for instance_name in _resolve_instances(instances_dir, args.instance):
        instructions = _load_instructions(instances_dir, instance_name)
        service = (
            _service_from_source(instance_name, Path(args.source))
            if args.source
            else BibliothekarService.from_instructions(instance_name, instances_dir, instructions)
        )
        filters = _query_filters(args)
        if args.deep:
            graph_state = run_bibliothekar_deep_query(
                service,
                args.query,
                max_prompt_chars=max(1, int(args.max_prompt_chars)),
                max_chunks=max(1, int(args.top_k)),
                max_quote_chars=max(1, int(args.max_quote_chars)),
                filters=filters or None,
            )
            rows.append(
                {
                    "instance": instance_name,
                    "backend": service.backend_name,
                    "selected_ids": graph_state.get("selected_ids", []),
                    "prompt_text": graph_state.get("answer_text", ""),
                    "graph": graph_state,
                }
            )
            continue
        selection = service.search(
            args.query,
            filters=filters or None,
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


def _query_filters(args: argparse.Namespace) -> dict[str, list[str]]:
    filters: dict[str, list[str]] = {}
    if args.category:
        filters["categories"] = [str(item) for item in args.category if str(item).strip()]
    if args.topic:
        filters["topics"] = [str(item) for item in args.topic if str(item).strip()]
    if args.keyword:
        filters.setdefault("topics", []).extend(str(item) for item in args.keyword if str(item).strip())
    if args.file:
        filters["relative_path"] = [str(item) for item in args.file if str(item).strip()]
    if args.relative_path:
        filters.setdefault("relative_path", []).extend(str(item) for item in args.relative_path if str(item).strip())
    if args.extension:
        filters["extension"] = [str(item) for item in args.extension if str(item).strip()]
    if args.suffix:
        filters["suffix"] = [str(item) for item in args.suffix if str(item).strip()]
    return filters


def _index_source(instance_name: str, instances_dir: Path, source: Path, *, dry_run: bool, instructions: BotInstructions) -> dict[str, Any]:
    if not source.exists():
        raise SystemExit(f"source does not exist: {source}")
    if not dry_run:
        store = BibliothekarStore(instance_name, instances_dir)
        store.ensure()
        _copy_allowed_sources(source, store.library_dir)
        return BibliothekarService.from_instructions(instance_name, instances_dir, instructions).rebuild()
    with tempfile.TemporaryDirectory(prefix="teebotus-bibliothekar-") as tmp:
        tmp_instances = Path(tmp) / "instances"
        tmp_library = tmp_instances / instance_name / "data" / "Bibliothek"
        tmp_library.mkdir(parents=True)
        _copy_allowed_sources(source, tmp_library)
        return BibliothekarStore(instance_name, tmp_instances).rebuild()


def _service_from_source(instance_name: str, source: Path) -> BibliothekarService:
    if not source.exists():
        raise SystemExit(f"source does not exist: {source}")
    tmp = tempfile.TemporaryDirectory(prefix="teebotus-bibliothekar-query-")
    tmp_instances = Path(tmp.name) / "instances"
    tmp_library = tmp_instances / instance_name / "data" / "Bibliothek"
    tmp_library.mkdir(parents=True)
    _copy_allowed_sources(source, tmp_library)
    store = BibliothekarStore(instance_name, tmp_instances)
    store.rebuild()
    service = BibliothekarService.local(instance_name, tmp_instances)
    service._fixture_tmp = tmp  # type: ignore[attr-defined]
    return service


def _dry_run_index(store: BibliothekarStore) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="teebotus-bibliothekar-") as tmp:
        tmp_instances = Path(tmp) / "instances"
        tmp_library = tmp_instances / store.instance_name / "data" / "Bibliothek"
        tmp_library.mkdir(parents=True)
        if store.library_dir.exists():
            _copy_allowed_sources(store.library_dir, tmp_library)
        return BibliothekarStore(store.instance_name, tmp_instances).rebuild()


def _copy_allowed_sources(source: Path, library_dir: Path) -> None:
    if source.is_symlink():
        return
    if source.is_dir():
        for path in sorted(source.rglob("*")):
            if path.is_file() and not path.is_symlink():
                _copy_allowed_source_file(path, library_dir / path.relative_to(source), library_dir)
        return
    _copy_allowed_source_file(source, library_dir / source.name, library_dir)


def _copy_allowed_source_file(source: Path, destination: Path, library_dir: Path) -> None:
    if source.is_symlink():
        return
    if destination.suffix.casefold() not in SUPPORTED_SUFFIXES:
        return
    if not _is_allowed_library_source_path(destination, library_dir):
        return
    try:
        if destination.exists() and source.resolve(strict=True) == destination.resolve(strict=True):
            return
    except OSError:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _resolve_instances(instances_dir: Path, requested: Iterable[str]) -> tuple[str, ...]:
    explicit = tuple(str(item).strip() for item in requested if str(item).strip())
    if explicit:
        return explicit
    if not instances_dir.exists():
        return ()
    return tuple(
        path.name
        for path in sorted(instances_dir.iterdir())
        if path.is_dir() and (path / "Bot_Verhalten.md").exists()
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
        row["target_suffix"] = f" target={row['target']}" if row.get("target") else ""
        print(template.format(**row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
