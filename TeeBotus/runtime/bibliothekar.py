from __future__ import annotations

import argparse
import hashlib
import html
import json
import logging
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree

LOGGER = logging.getLogger("TeeBotus")

LIBRARY_DIRNAME = "Bibliothek"
LIBRARY_META_DIRNAME = ".bibliothekar"
LIBRARY_INDEX_FILENAME = "index.json"
LIBRARY_CHUNKS_FILENAME = "chunks.jsonl"
LIBRARY_SCHEMA_VERSION = 2
LIBRARY_STAGING_DIRNAMES = frozenset({"inbox", "accepted", "quarantine", "rejected"})
HARVEST_MANIFEST_FILENAME = "harvest_manifest.jsonl"
DEFAULT_EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
DEFAULT_MAX_PROMPT_CHARS = 5000
DEFAULT_MAX_CHUNKS = 5
DEFAULT_MAX_QUOTE_CHARS = 900
SUPPORTED_SUFFIXES = {".pdf", ".epub", ".docx", ".txt", ".md", ".markdown"}
REQUIRED_CITATION_CHUNK_FIELDS = (
    "chunk_id",
    "source_id",
    "title",
    "relative_path",
    "file_path",
    "file_sha256",
    "file_type",
    "language",
    "locator",
    "license",
    "ingested_at",
    "embedding_model",
)
FORBIDDEN_LIBRARY_SOURCE_PATH_PARTS = {
    "account_identities.json",
    "account_index.json",
    "account_memory_entries.jsonl",
    "account_memory_index.json",
    "account_profile.json",
    "account_secrets.json",
    "account_tombstone.json",
    "agent_state.json",
    "legacy_user_memory_entries.jsonl",
    "llm_state.json",
    "openai_state.json",
    "proactive_audit.jsonl",
    "proactive_outbox.jsonl",
    "secret_verifier.json",
    "user_habbits_and_behave.md",
    "user_memory_entries.jsonl",
    "user_memory_index.json",
}
FORBIDDEN_LIBRARY_SOURCE_PATH_SEGMENTS = {
    ("data", "accounts"),
    ("data", "users"),
}
STOPWORDS = {
    "aber",
    "alle",
    "alles",
    "als",
    "also",
    "auch",
    "auf",
    "aus",
    "bei",
    "bin",
    "bis",
    "das",
    "dass",
    "dem",
    "den",
    "der",
    "des",
    "die",
    "dies",
    "ein",
    "eine",
    "einem",
    "einen",
    "einer",
    "eines",
    "fuer",
    "hat",
    "ich",
    "ist",
    "mit",
    "nicht",
    "oder",
    "sich",
    "sie",
    "und",
    "von",
    "war",
    "was",
    "wenn",
    "wie",
    "wird",
    "zur",
}
CATEGORY_KEYWORDS = {
    "psychologie": {
        "depression",
        "depressiv",
        "angst",
        "therapie",
        "psychotherapie",
        "trauma",
        "kognition",
        "gefuehl",
        "emotion",
        "stress",
        "schlaf",
    },
    "medizin": {"medizin", "arzt", "symptom", "diagnose", "behandlung", "patient", "klinik", "krankheit"},
    "philosophie": {"philosophie", "ethik", "moral", "bewusstsein", "wahrheit", "sinn"},
    "technik": {"software", "computer", "python", "daten", "system", "modell", "algorithmus"},
    "recht": {"recht", "gesetz", "vertrag", "urteil", "pflicht", "datenschutz"},
    "alltag": {"arbeit", "lernen", "wohnung", "familie", "termin", "organisation"},
    "literatur": {"roman", "gedicht", "kapitel", "figur", "erzaehlung", "autor"},
}


@dataclass(frozen=True)
class BibliothekarSelection:
    prompt_text: str
    selected_ids: tuple[str, ...]


class BibliothekarStore:
    def __init__(self, instance_name: str, instances_dir: str | Path = "instances") -> None:
        self.instance_name = str(instance_name or "default")
        self.instances_dir = Path(instances_dir)

    @property
    def library_dir(self) -> Path:
        return self.instances_dir / self.instance_name / "data" / LIBRARY_DIRNAME

    @property
    def meta_dir(self) -> Path:
        return self.library_dir / LIBRARY_META_DIRNAME

    @property
    def index_path(self) -> Path:
        return self.meta_dir / LIBRARY_INDEX_FILENAME

    @property
    def chunks_path(self) -> Path:
        return self.meta_dir / LIBRARY_CHUNKS_FILENAME

    def ensure(self) -> Path:
        self.library_dir.mkdir(parents=True, exist_ok=True)
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            self.rebuild()
        return self.library_dir

    def rebuild(self) -> dict[str, Any]:
        self.library_dir.mkdir(parents=True, exist_ok=True)
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        now = _utc_timestamp()
        source_metadata = _read_harvest_source_metadata(self.library_dir)
        documents: dict[str, Any] = {}
        chunks: list[dict[str, Any]] = []
        for path in _iter_document_paths(self.library_dir):
            document, document_chunks = _index_document(path, self.library_dir, now, source_metadata)
            documents[str(document["document_id"])] = document
            chunks.extend(document_chunks)
        index = {
            "schema_version": LIBRARY_SCHEMA_VERSION,
            "scope": "instance_library",
            "instance_name": self.instance_name,
            "library_dir": str(self.library_dir),
            "created_at": now,
            "updated_at": now,
            "documents": documents,
            "chunk_store": LIBRARY_CHUNKS_FILENAME,
            "chunk_count": len(chunks),
            "categories": _summarize_categories(chunks),
            "topics": _top_keywords(" ".join(" ".join(chunk.get("topics", [])) for chunk in chunks), limit=48),
        }
        _write_json(self.index_path, index)
        with self.chunks_path.open("w", encoding="utf-8") as file:
            for chunk in chunks:
                file.write(json.dumps(chunk, ensure_ascii=False, sort_keys=True) + "\n")
        return index

    def ensure_current(self) -> None:
        index = _read_json(self.index_path)
        if not isinstance(index, dict) or _index_is_stale(index, self.library_dir) or _chunk_store_is_stale(index, self.chunks_path):
            self.rebuild()

    def select(
        self,
        query_text: str,
        *,
        max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS,
        max_chunks: int = DEFAULT_MAX_CHUNKS,
        max_quote_chars: int = DEFAULT_MAX_QUOTE_CHARS,
    ) -> BibliothekarSelection:
        if max_prompt_chars < 1 or max_chunks < 1:
            return BibliothekarSelection("", ())
        self.ensure_current()
        index = _read_json(self.index_path)
        if not isinstance(index, dict) or not int(index.get("chunk_count") or 0):
            return BibliothekarSelection("", ())
        chunks = [chunk for chunk in _read_chunks(self.chunks_path) if _chunk_has_required_citation_metadata(chunk)]
        selected = _rank_chunks(chunks, query_text)[:max_chunks]
        prompt_items: list[dict[str, Any]] = []
        selected_ids: list[str] = []
        for chunk in selected:
            item = _chunk_prompt_item(chunk, max_quote_chars=max_quote_chars)
            candidate = _prompt_payload(index, [*prompt_items, item])
            candidate_text = json.dumps(candidate, ensure_ascii=False, indent=2)
            if len(candidate_text) > max_prompt_chars:
                if prompt_items:
                    break
                item["quote"] = _clip(str(item.get("quote", "")), max(200, max_prompt_chars // 3))
                candidate_text = json.dumps(_prompt_payload(index, [item]), ensure_ascii=False, indent=2)
                if len(candidate_text) > max_prompt_chars:
                    break
            prompt_items.append(item)
            selected_ids.append(str(item["chunk_id"]))
        if not prompt_items:
            return BibliothekarSelection("", ())
        return BibliothekarSelection(
            prompt_text=json.dumps(_prompt_payload(index, prompt_items), ensure_ascii=False, indent=2),
            selected_ids=tuple(selected_ids),
        )


def select_bibliothekar_context(
    instance_name: str,
    instances_dir: str | Path,
    query_text: str,
    *,
    max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS,
    max_chunks: int = DEFAULT_MAX_CHUNKS,
    max_quote_chars: int = DEFAULT_MAX_QUOTE_CHARS,
) -> str:
    try:
        return BibliothekarStore(instance_name, instances_dir).select(
            query_text,
            max_prompt_chars=max_prompt_chars,
            max_chunks=max_chunks,
            max_quote_chars=max_quote_chars,
        ).prompt_text
    except OSError:
        LOGGER.exception("Failed to prepare Bibliothekar context for instance=%s.", instance_name)
        return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Index TeeBotus Bibliothek folders.")
    parser.add_argument("--instances-dir", default="instances")
    parser.add_argument("--instance", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    instances_dir = Path(args.instances_dir)
    instance_names = tuple(args.instance) or tuple(_discover_instances(instances_dir))
    results = []
    for instance_name in instance_names:
        store = BibliothekarStore(instance_name, instances_dir)
        index = store.rebuild()
        results.append(
            {
                "instance": instance_name,
                "library_dir": str(store.library_dir),
                "documents": len(index.get("documents", {})),
                "chunks": int(index.get("chunk_count") or 0),
            }
        )
    if args.json:
        print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
    else:
        for result in results:
            print(
                "{instance}: {documents} Dokumente, {chunks} Chunks, Ordner: {library_dir}".format(
                    **result
                )
            )
    return 0


def _discover_instances(instances_dir: Path) -> Iterable[str]:
    if not instances_dir.exists():
        return ()
    return (
        path.name
        for path in sorted(instances_dir.iterdir())
        if path.is_dir() and (path / "data").exists()
    )


def _iter_document_paths(library_dir: Path) -> Iterable[Path]:
    if not library_dir.exists():
        return ()
    return (
        path
        for path in sorted(library_dir.rglob("*"))
        if path.is_file()
        and not path.is_symlink()
        and _is_allowed_library_source_path(path, library_dir)
        and path.suffix.casefold() in SUPPORTED_SUFFIXES
    )


def _is_allowed_library_source_path(path: Path, library_dir: Path) -> bool:
    try:
        relative_path = path.relative_to(library_dir)
    except ValueError:
        return False
    normalized = relative_path.as_posix().strip().casefold()
    if not normalized or normalized.startswith("/") or normalized.startswith("../") or "/../" in normalized:
        return False
    parts = tuple(part for part in normalized.split("/") if part and part != ".")
    if not parts:
        return False
    if parts[0] in LIBRARY_STAGING_DIRNAMES:
        return False
    if LIBRARY_META_DIRNAME.casefold() in parts:
        return False
    if any(part in FORBIDDEN_LIBRARY_SOURCE_PATH_PARTS for part in parts):
        return False
    if any(_path_contains_segments(parts, forbidden) for forbidden in FORBIDDEN_LIBRARY_SOURCE_PATH_SEGMENTS):
        return False
    return True


def _read_harvest_source_metadata(library_dir: Path) -> dict[str, dict[str, Any]]:
    manifest_path = library_dir / HARVEST_MANIFEST_FILENAME
    if not manifest_path.exists():
        return {}
    rows: list[dict[str, Any]] = []
    try:
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    except OSError:
        return {}
    accepted_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    accepted_by_hash: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("event") == "promoted":
            continue
        sha256 = str(row.get("sha256") or "").strip()
        stored_path = str(row.get("stored_path") or "").strip()
        if not sha256 or not stored_path or row.get("accepted_for_ingest") is not True:
            continue
        accepted_by_key[(sha256, stored_path)] = row
        accepted_by_hash.setdefault(sha256, row)
    metadata: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("event") != "promoted":
            continue
        sha256 = str(row.get("sha256") or "").strip()
        promoted_text = str(row.get("stored_path") or "").strip()
        if not sha256 or not promoted_text:
            continue
        promoted_path = Path(promoted_text)
        accepted = accepted_by_key.get((sha256, str(row.get("source_path") or ""))) or accepted_by_hash.get(sha256)
        if not accepted:
            continue
        try:
            relative_path = promoted_path.resolve(strict=False).relative_to(library_dir.resolve(strict=False)).as_posix()
        except ValueError:
            continue
        metadata[relative_path] = _source_metadata_from_harvest_row(accepted)
    return metadata


def _source_metadata_from_harvest_row(row: dict[str, Any]) -> dict[str, Any]:
    source = row.get("source") if isinstance(row.get("source"), dict) else {}
    source_metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    decision = row.get("decision") if isinstance(row.get("decision"), dict) else {}
    status = str(decision.get("status") or "").strip()
    return {
        "title": str(source_metadata.get("title") or "").strip(),
        "license": str(source_metadata.get("license") or "").strip(),
        "source_quality": status or "unreviewed",
        "citation_quality": _citation_quality_from_source_status(status),
        "source_quality_reason": str(decision.get("reason") or "").strip(),
        "source_requires_human_review": bool(decision.get("requires_human_review")),
        "source_harvest_route": str(row.get("route") or "accepted").strip() or "accepted",
    }


def _citation_quality_from_source_status(status: str) -> str:
    normalized = str(status or "").strip().casefold()
    if normalized in {"trusted", "usable", "weak"}:
        return normalized
    if normalized in {"reject", "rejected"}:
        return "rejected"
    return "unreviewed"


def _index_document(
    path: Path,
    library_dir: Path,
    now: str,
    source_metadata: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    relative_path = path.relative_to(library_dir).as_posix()
    source_meta = dict((source_metadata or {}).get(relative_path) or {})
    document_id = _stable_id("doc", relative_path)
    stat = path.stat()
    file_sha256 = _file_sha256(path)
    source_id = f"sha256:{file_sha256}"
    file_type = path.suffix.casefold().lstrip(".")
    language = "de"
    title = str(source_meta.get("title") or _document_title(path)).strip() or _document_title(path)
    author = _document_author(path)
    license_value = str(source_meta.get("license") or "private").strip() or "private"
    source_quality = str(source_meta.get("source_quality") or "unreviewed").strip() or "unreviewed"
    citation_quality = str(source_meta.get("citation_quality") or _citation_quality_from_source_status(source_quality)).strip() or "unreviewed"
    source_quality_reason = str(source_meta.get("source_quality_reason") or "").strip()
    source_requires_human_review = bool(source_meta.get("source_requires_human_review"))
    source_harvest_route = str(source_meta.get("source_harvest_route") or "manual").strip() or "manual"
    error = ""
    sections: list[tuple[str, str]] = []
    try:
        sections = _extract_sections(path)
    except Exception as exc:  # noqa: BLE001 - document extractors must not break bot startup.
        error = f"{type(exc).__name__}: {exc}"[:300]
        LOGGER.warning("Failed to index Bibliothek document %s: %s", path, exc)
    document_text = " ".join(section_text for _, section_text in sections)
    topics = _top_keywords(document_text, limit=24)
    categories = _categories_for_keywords(topics)
    document = {
        "document_id": document_id,
        "source_id": source_id,
        "title": title,
        "author": author,
        "relative_path": relative_path,
        "file_path": relative_path,
        "file_sha256": file_sha256,
        "file_type": file_type,
        "suffix": path.suffix.casefold(),
        "language": language,
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "indexed_at": now,
        "ingested_at": now,
        "embedding_model": DEFAULT_EMBEDDING_MODEL,
        "license": license_value,
        "source_quality": source_quality,
        "citation_quality": citation_quality,
        "source_quality_reason": source_quality_reason,
        "source_requires_human_review": source_requires_human_review,
        "source_harvest_route": source_harvest_route,
        "topics": topics,
        "categories": categories,
        "error": error,
    }
    chunks: list[dict[str, Any]] = []
    for locator, text in sections:
        for chunk_index, chunk_text in enumerate(_chunk_text(text), start=1):
            if not chunk_text.strip():
                continue
            chunk_id = _stable_id("lib", f"{relative_path}:{locator}:{chunk_index}:{hashlib.sha1(chunk_text.encode('utf-8')).hexdigest()[:12]}")
            chunk_topics = _top_keywords(chunk_text, limit=16)
            page_start, page_end = _locator_page_range(locator)
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "document_id": document_id,
                    "source_id": source_id,
                    "title": title,
                    "author": author,
                    "relative_path": relative_path,
                    "file_path": relative_path,
                    "file_sha256": file_sha256,
                    "file_type": file_type,
                    "language": language,
                    "locator": locator if chunk_index == 1 else f"{locator}, chunk {chunk_index}",
                    "suffix": path.suffix.casefold(),
                    "page_start": page_start,
                    "page_end": page_end,
                    "chapter": "",
                    "section": locator,
                    "license": license_value,
                    "source_quality": source_quality,
                    "citation_quality": citation_quality,
                    "source_quality_reason": source_quality_reason,
                    "source_requires_human_review": source_requires_human_review,
                    "source_harvest_route": source_harvest_route,
                    "ingested_at": now,
                    "chunk_index": chunk_index,
                    "embedding_model": DEFAULT_EMBEDDING_MODEL,
                    "topics": chunk_topics,
                    "categories": _categories_for_keywords([*topics, *chunk_topics]),
                    "text": chunk_text,
                }
            )
    return document, chunks


def _extract_sections(path: Path) -> list[tuple[str, str]]:
    suffix = path.suffix.casefold()
    if suffix == ".pdf":
        return _extract_pdf_sections(path)
    if suffix == ".docx":
        return _extract_docx_sections(path)
    if suffix == ".epub":
        return _extract_epub_sections(path)
    return _extract_text_sections(path)


def _extract_pdf_sections(path: Path) -> list[tuple[str, str]]:
    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]
    except Exception:
        try:
            from PyPDF2 import PdfReader  # type: ignore[import-not-found]
        except Exception as exc:
            raise RuntimeError("Kein PDF-Textparser installiert (pypdf oder PyPDF2).") from exc
    reader = PdfReader(str(path))
    sections = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            sections.append((f"Seite {index}", _normalize_text(text)))
    return sections


def _extract_docx_sections(path: Path) -> list[tuple[str, str]]:
    with zipfile.ZipFile(path) as archive:
        payload = archive.read("word/document.xml")
    root = ElementTree.fromstring(payload)
    paragraphs: list[str] = []
    for paragraph in root.iter():
        if _local_name(paragraph.tag) != "p":
            continue
        texts = [node.text or "" for node in paragraph.iter() if _local_name(node.tag) == "t"]
        text = _normalize_text("".join(texts))
        if text:
            paragraphs.append(text)
    return [(f"Absatz {index}", paragraph) for index, paragraph in enumerate(paragraphs, start=1)]


def _extract_epub_sections(path: Path) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    with zipfile.ZipFile(path) as archive:
        names = [
            name
            for name in archive.namelist()
            if name.casefold().endswith((".xhtml", ".html", ".htm", ".xml"))
            and not name.casefold().endswith(("container.xml", ".opf", ".ncx"))
        ]
        for name in names:
            raw = archive.read(name).decode("utf-8", errors="replace")
            text = _htmlish_to_text(raw)
            if text:
                sections.append((name, text))
    return sections


def _extract_text_sections(path: Path) -> list[tuple[str, str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if not lines:
        return []
    sections: list[tuple[str, str]] = []
    for start in range(0, len(lines), 80):
        part = _normalize_text("\n".join(lines[start : start + 80]))
        if part:
            sections.append((f"Zeilen {start + 1}-{min(len(lines), start + 80)}", part))
    return sections


def _htmlish_to_text(raw: str) -> str:
    without_scripts = re.sub(r"<(script|style)\b.*?</\1>", " ", raw, flags=re.IGNORECASE | re.DOTALL)
    with_breaks = re.sub(r"</(p|div|h[1-6]|li|br|section|chapter)>", "\n", without_scripts, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", with_breaks)
    return _normalize_text(html.unescape(text))


def _chunk_text(text: str, *, target_chars: int = 1600, overlap_chars: int = 180) -> list[str]:
    normalized = _normalize_text(text)
    if len(normalized) <= target_chars:
        return [normalized] if normalized else []
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + target_chars)
        if end < len(normalized):
            boundary = max(normalized.rfind(". ", start, end), normalized.rfind("\n", start, end))
            if boundary > start + 400:
                end = boundary + 1
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        start = max(end - overlap_chars, start + 1)
    return chunks


def _rank_chunks(chunks: list[dict[str, Any]], query_text: str) -> list[dict[str, Any]]:
    query_keywords = set(_keywords(query_text, limit=32))
    if not query_keywords:
        return chunks[:]

    def score(chunk: dict[str, Any]) -> tuple[int, int]:
        topics = set(str(topic) for topic in chunk.get("topics", []) if isinstance(topic, str))
        text = str(chunk.get("text", "")).casefold()
        topic_hits = len(query_keywords.intersection(topics))
        text_hits = sum(1 for keyword in query_keywords if keyword in text)
        return topic_hits * 4 + text_hits, topic_hits

    ranked = sorted(chunks, key=score, reverse=True)
    return [chunk for chunk in ranked if score(chunk)[0] > 0] or ranked


def _chunk_prompt_item(chunk: dict[str, Any], *, max_quote_chars: int) -> dict[str, Any]:
    return {
        "chunk_id": str(chunk.get("chunk_id", "")),
        "source_id": str(chunk.get("source_id", "")),
        "title": str(chunk.get("title", "")),
        "author": str(chunk.get("author", "")),
        "file": str(chunk.get("relative_path", "")),
        "file_path": str(chunk.get("file_path", "") or chunk.get("relative_path", "")),
        "file_sha256": str(chunk.get("file_sha256", "")),
        "file_type": str(chunk.get("file_type", "") or str(chunk.get("suffix", "")).lstrip(".")),
        "language": str(chunk.get("language", "")),
        "locator": str(chunk.get("locator", "")),
        "page_start": chunk.get("page_start"),
        "page_end": chunk.get("page_end"),
        "chapter": str(chunk.get("chapter", "")),
        "section": str(chunk.get("section", "")),
        "license": str(chunk.get("license", "")),
        "source_quality": str(chunk.get("source_quality", "") or "unreviewed"),
        "citation_quality": str(chunk.get("citation_quality", "") or "unreviewed"),
        "source_quality_reason": str(chunk.get("source_quality_reason", "")),
        "source_requires_human_review": bool(chunk.get("source_requires_human_review")),
        "source_harvest_route": str(chunk.get("source_harvest_route", "") or "manual"),
        "ingested_at": str(chunk.get("ingested_at", "")),
        "chunk_index": chunk.get("chunk_index"),
        "embedding_model": str(chunk.get("embedding_model", "")),
        "categories": chunk.get("categories", []) if isinstance(chunk.get("categories"), list) else [],
        "topics": chunk.get("topics", []) if isinstance(chunk.get("topics"), list) else [],
        "quote": _clip(str(chunk.get("text", "")), max_quote_chars),
        "citation_format": "[Quelle: {title}, {file}, {locator}, chunk_id={chunk_id}]",
    }


def _prompt_payload(index: dict[str, Any], chunks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "scope": "instance_library",
        "instance_name": str(index.get("instance_name", "")),
        "library_dir": str(index.get("library_dir", "")),
        "citation_rules": [
            "Nutze diese Ausschnitte nur als Quellenkontext.",
            "Wenn du daraus zitierst oder eine konkrete Aussage daraus ableitest, nenne direkt die genaue Quelle mit Titel, Datei, Locator und chunk_id.",
            "Beachte source_quality/citation_quality: unreviewed oder weak Quellen nur vorsichtig verwenden und Unsicherheit benennen.",
            "Zitiere nur kurze Abschnitte; paraphrasiere laengere Inhalte.",
        ],
        "selected_library_chunks": chunks,
    }


def _index_is_stale(index: dict[str, Any], library_dir: Path) -> bool:
    if int(index.get("schema_version") or 0) != LIBRARY_SCHEMA_VERSION:
        return True
    documents = index.get("documents") if isinstance(index.get("documents"), dict) else {}
    current: dict[str, tuple[int, int]] = {}
    for path in _iter_document_paths(library_dir):
        relative = path.relative_to(library_dir).as_posix()
        stat = path.stat()
        current[relative] = (stat.st_size, stat.st_mtime_ns)
    indexed: dict[str, tuple[int, int]] = {}
    for document in documents.values():
        if not isinstance(document, dict):
            continue
        relative = str(document.get("relative_path") or "")
        if relative:
            indexed[relative] = (int(document.get("size_bytes") or -1), int(document.get("mtime_ns") or -1))
    return current != indexed


def _chunk_store_is_stale(index: dict[str, Any], chunks_path: Path) -> bool:
    expected_count = int(index.get("chunk_count") or 0)
    if expected_count < 1:
        return False
    if not chunks_path.exists():
        return True
    chunks = _read_chunks(chunks_path)
    return len(chunks) != expected_count or any(not _chunk_has_required_citation_metadata(chunk) for chunk in chunks)


def _read_chunks(path: Path) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as file:
            for line in file:
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    chunks.append(payload)
    except FileNotFoundError:
        return []
    return chunks


def _chunk_has_required_citation_metadata(chunk: dict[str, Any]) -> bool:
    return all(str(chunk.get(field) or "").strip() for field in REQUIRED_CITATION_CHUNK_FIELDS) and _chunk_has_library_source_path(chunk)


def _chunk_has_library_source_path(chunk: dict[str, Any]) -> bool:
    paths = [str(chunk.get("relative_path") or ""), str(chunk.get("file_path") or "")]
    for raw_path in paths:
        normalized = raw_path.replace("\\", "/").strip().casefold()
        if not normalized:
            return False
        if _looks_like_absolute_or_uri_source_path(normalized):
            return False
        if normalized.startswith("/") or normalized.startswith("../") or "/../" in normalized:
            return False
        parts = tuple(part for part in normalized.split("/") if part and part != ".")
        if parts and parts[0] in LIBRARY_STAGING_DIRNAMES:
            return False
        if any(part in FORBIDDEN_LIBRARY_SOURCE_PATH_PARTS for part in parts):
            return False
        if any(_path_contains_segments(parts, forbidden) for forbidden in FORBIDDEN_LIBRARY_SOURCE_PATH_SEGMENTS):
            return False
    return True


def _looks_like_absolute_or_uri_source_path(value: str) -> bool:
    return bool(re.match(r"^[a-z][a-z0-9+.-]*:", value))


def _path_contains_segments(parts: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    if not needle or len(parts) < len(needle):
        return False
    return any(parts[index : index + len(needle)] == needle for index in range(len(parts) - len(needle) + 1))


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _summarize_categories(chunks: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for chunk in chunks:
        categories = chunk.get("categories") if isinstance(chunk.get("categories"), list) else []
        for category in categories:
            counts[str(category)] = counts.get(str(category), 0) + 1
    return dict(sorted(counts.items(), key=lambda item: item[1], reverse=True))


def _categories_for_keywords(keywords: Iterable[str]) -> list[str]:
    keyword_set = {str(keyword).casefold() for keyword in keywords}
    categories = [
        category
        for category, category_keywords in CATEGORY_KEYWORDS.items()
        if keyword_set.intersection(category_keywords)
    ]
    return categories or ["allgemein"]


def _top_keywords(text: str, *, limit: int) -> list[str]:
    counts: dict[str, int] = {}
    for keyword in _keywords(text, limit=100000):
        counts[keyword] = counts.get(keyword, 0) + 1
    return [keyword for keyword, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def _keywords(text: str, *, limit: int) -> list[str]:
    keywords: list[str] = []
    for match in re.finditer(r"\b[\w-]{3,}\b", str(text or "").casefold(), re.UNICODE):
        keyword = match.group(0).strip("_-")
        if not keyword or keyword in STOPWORDS or keyword.isdigit():
            continue
        keywords.append(keyword)
        if len(keywords) >= limit:
            break
    return keywords


def _document_title(path: Path) -> str:
    stem = path.stem.replace("_", " ").replace("-", " ").strip()
    return re.sub(r"\s+", " ", stem).strip() or path.name


def _document_author(_path: Path) -> str:
    return ""


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}_{hashlib.sha1(value.encode('utf-8')).hexdigest()[:16]}"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _locator_page_range(locator: str) -> tuple[int | None, int | None]:
    match = re.search(r"\bSeite\s+(\d+)(?:\s*[-–]\s*(\d+))?", str(locator or ""), flags=re.IGNORECASE)
    if not match:
        return None, None
    start = int(match.group(1))
    end = int(match.group(2) or start)
    return start, end


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _clip(text: str, max_chars: int) -> str:
    stripped = str(text or "").strip()
    if len(stripped) <= max_chars:
        return stripped
    return stripped[: max(0, max_chars)].rstrip() + "\n[gekuerzt]"


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


if __name__ == "__main__":
    raise SystemExit(main())
