from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from TeeBotus.runtime.bibliothekar import _coerce_bool, _is_allowed_library_source_path, _manifest_library_path, _manifest_sha256, _manifest_token
from TeeBotus.runtime.source_quality import SourceQualityInput, SourceQualityPipeline, SourceQualityReport, SourceRoute


HARVEST_MANIFEST = "harvest_manifest.jsonl"
HARVEST_DIRS = ("inbox", "quarantine", "accepted", "rejected")
PROMOTED_DIR = "books"


@dataclass(frozen=True)
class SourceHarvestResult:
    source_path: Path
    route: SourceRoute
    stored_path: Path | None
    sha256: str
    report: SourceQualityReport
    duplicate_of: Path | None = None

    @property
    def accepted_for_ingest(self) -> bool:
        return self.route == "accepted" and self.duplicate_of is None and self.stored_path is not None


@dataclass(frozen=True)
class SourcePromoteResult:
    staged_path: Path
    promoted_path: Path
    sha256: str
    copied: bool = True


class SourceHarvester:
    """Gate local source files before they can become Bibliothekar material."""

    def __init__(
        self,
        library_root: str | Path,
        *,
        quality_pipeline: SourceQualityPipeline | None = None,
    ) -> None:
        self.library_root = Path(library_root)
        self.quality_pipeline = quality_pipeline or SourceQualityPipeline()
        self.manifest_path = self.library_root / HARVEST_MANIFEST

    def prepare(self) -> None:
        self.library_root.mkdir(parents=True, exist_ok=True)
        _chmod_private_dir(self.library_root)
        for dirname in HARVEST_DIRS:
            path = self.library_root / dirname
            path.mkdir(parents=True, exist_ok=True)
            _chmod_private_dir(path)

    def harvest_path(
        self,
        source_path: str | Path,
        *,
        metadata: Mapping[str, Any] | None = None,
        claims: Iterable[str] = (),
        evidence: Iterable[str] = (),
        copy: bool = True,
    ) -> SourceHarvestResult:
        self.prepare()
        source = Path(source_path)
        if source.is_symlink():
            raise ValueError("SourceHarvester refuses symlink sources")
        if not source.is_file():
            raise FileNotFoundError(source)

        sha256 = _file_sha256(source)
        source_input = SourceQualityInput.from_path(
            source,
            metadata=dict(metadata or {}),
            claims=claims,
            evidence=evidence,
        )
        report = self.quality_pipeline.evaluate(source_input)
        duplicate = self._existing_path_for_hash(sha256, route=report.route)
        if duplicate is not None:
            result = SourceHarvestResult(source, report.route, None, sha256, report, duplicate_of=duplicate)
            self._append_manifest(result)
            return result

        stored_path = self._stored_path(source, sha256, report.route)
        if copy:
            shutil.copy2(source, stored_path)
        else:
            shutil.move(source, stored_path)
        _chmod_private_file(stored_path)
        result = SourceHarvestResult(source, report.route, stored_path, sha256, report)
        self._append_manifest(result)
        return result

    def promote_accepted(
        self,
        staged_path: str | Path,
        *,
        destination_dir: str = PROMOTED_DIR,
        copy: bool = True,
    ) -> SourcePromoteResult:
        self.prepare()
        staged = Path(staged_path)
        if staged.is_symlink():
            raise ValueError("SourceHarvester refuses symlink sources")
        if not staged.is_file():
            raise FileNotFoundError(staged)
        accepted_root = (self.library_root / "accepted").resolve()
        try:
            resolved_staged = staged.resolve(strict=True)
            resolved_staged.relative_to(accepted_root)
        except ValueError as exc:
            raise ValueError("Only files from the accepted harvest staging directory can be promoted") from exc

        sha256 = _file_sha256(staged)
        if not self._manifest_accepts_hash(sha256, staged):
            raise ValueError("Accepted source is not marked accepted_for_ingest in the harvest manifest")
        target_dir = self.library_root / _safe_destination_dir(destination_dir)
        candidate_path = target_dir / staged.name
        if not _is_allowed_library_source_path(candidate_path, self.library_root):
            raise ValueError("destination_dir must resolve to an indexed Bibliothek source path")
        target_dir.mkdir(parents=True, exist_ok=True)
        _chmod_private_dir(target_dir)
        promoted_path = _unique_destination(candidate_path, sha256=sha256)
        if copy:
            shutil.copy2(staged, promoted_path)
        else:
            shutil.move(staged, promoted_path)
        _chmod_private_file(promoted_path)
        result = SourcePromoteResult(staged, promoted_path, sha256, copied=copy)
        self._append_promote_manifest(result)
        return result

    def _stored_path(self, source: Path, sha256: str, route: SourceRoute) -> Path:
        safe_name = _safe_filename(source.name)
        return self.library_root / _route_dir(route) / f"{sha256[:16]}-{safe_name}"

    def _existing_path_for_hash(self, sha256: str, *, route: SourceRoute) -> Path | None:
        if not self.manifest_path.exists():
            return None
        for line in self.manifest_path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict) or _manifest_sha256(row.get("sha256")) != sha256 or _manifest_token(row.get("route")) != route:
                continue
            if _manifest_token(row.get("event")) == "promoted":
                continue
            if route == "accepted" and not _coerce_bool(row.get("accepted_for_ingest")):
                continue
            stored = _manifest_library_path(self.library_root, row.get("stored_path"), _route_dir(route))
            if stored is None:
                continue
            if _file_matches_sha256(stored, sha256):
                return stored
        return None

    def _manifest_accepts_hash(self, sha256: str, staged_path: Path) -> bool:
        if not self.manifest_path.exists():
            return False
        for line in self.manifest_path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            if _manifest_token(row.get("event")) == "promoted":
                continue
            stored = _manifest_library_path(self.library_root, row.get("stored_path"), "accepted")
            if _manifest_sha256(row.get("sha256")) != sha256 or stored is None or not _same_path(stored, staged_path):
                continue
            if _manifest_token(row.get("route")) == "accepted" and _coerce_bool(row.get("accepted_for_ingest")):
                return True
        return False

    def _append_manifest(self, result: SourceHarvestResult) -> None:
        row = {
            "created_at": datetime.now(UTC).isoformat(),
            "source_path": str(result.source_path),
            "stored_path": str(result.stored_path or ""),
            "duplicate_of": str(result.duplicate_of or ""),
            "sha256": result.sha256,
            "route": result.route,
            "accepted_for_ingest": result.accepted_for_ingest,
            "decision": {
                "status": result.report.decision.status,
                "reason": result.report.decision.reason,
                "requires_human_review": result.report.decision.requires_human_review,
                "confidence": result.report.decision.confidence,
            },
            "source": {
                "identifier": result.report.source.identifier,
                "suffix": result.report.source.suffix,
                "size_bytes": result.report.source.size_bytes,
                "metadata": dict(result.report.source.metadata or {}),
            },
            "issues": list(result.report.issues),
            "nli": [
                {
                    "stance": item.stance,
                    "confidence": item.confidence,
                    "model_name": item.model_name,
                    "reason": item.reason,
                }
                for item in result.report.nli_results
            ],
        }
        with self.manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        _chmod_private_file(self.manifest_path)

    def _append_promote_manifest(self, result: SourcePromoteResult) -> None:
        row = {
            "created_at": datetime.now(UTC).isoformat(),
            "event": "promoted",
            "source_path": str(result.staged_path),
            "stored_path": str(result.promoted_path),
            "sha256": result.sha256,
            "route": "promoted",
            "accepted_for_ingest": False,
            "copied": result.copied,
        }
        with self.manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        _chmod_private_file(self.manifest_path)


def _route_dir(route: SourceRoute) -> str:
    if route == "accepted":
        return "accepted"
    if route == "rejected":
        return "rejected"
    return "quarantine"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_filename(value: str) -> str:
    raw = str(value or "").strip()
    suffix = Path(raw).suffix
    stem = raw[: -len(suffix)] if suffix else raw
    safe_stem = "".join(char if char.isalnum() or char in {".", "-", "_"} else "_" for char in stem)
    safe_suffix = "".join(char if char.isalnum() or char in {"."} else "_" for char in suffix)
    return f"{safe_stem.strip('._') or 'source'}{safe_suffix}"


def _safe_destination_dir(value: str) -> str:
    raw = str(value or PROMOTED_DIR).strip()
    if Path(raw).is_absolute() or raw.startswith(("/", "\\")) or (len(raw) >= 2 and raw[1] == ":"):
        raise ValueError("destination_dir must be a relative library subdirectory")
    text = raw.replace("\\", "/")
    parts = tuple(part for part in text.split("/") if part and part != ".")
    if not parts or any(part == ".." for part in parts):
        raise ValueError("destination_dir must be a relative library subdirectory")
    if any(not any(char.isalnum() for char in part) for part in parts):
        raise ValueError("destination_dir contains a path segment without a usable name")
    if parts[0].casefold() in set(HARVEST_DIRS):
        raise ValueError("destination_dir must not be a harvest staging directory")
    return "/".join(_safe_filename(part) for part in parts)


def _unique_destination(candidate: Path, *, sha256: str) -> Path:
    if not candidate.exists():
        return candidate
    try:
        if candidate.is_file() and _file_sha256(candidate) == sha256:
            return candidate
    except OSError:
        pass
    stem = candidate.stem or "source"
    suffix = candidate.suffix
    for index in range(2, 10_000):
        versioned = candidate.with_name(f"{stem}-{index}{suffix}")
        if not versioned.exists():
            return versioned
    raise FileExistsError(candidate)


def _same_path(left: object, right: Path) -> bool:
    left_text = str(left or "")
    if not left_text:
        return False
    if left_text == str(right):
        return True
    try:
        return Path(left_text).resolve(strict=False) == right.resolve(strict=False)
    except OSError:
        return False


def _file_matches_sha256(path: Path, sha256: str) -> bool:
    expected = str(sha256 or "").strip().casefold()
    if not expected:
        return False
    try:
        return path.is_file() and not path.is_symlink() and _file_sha256(path).casefold() == expected
    except OSError:
        return False


def _chmod_private_dir(path: Path) -> None:
    try:
        path.chmod(0o700)
    except OSError:
        return


def _chmod_private_file(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError:
        return


__all__ = ["HARVEST_DIRS", "HARVEST_MANIFEST", "PROMOTED_DIR", "SourceHarvestResult", "SourceHarvester", "SourcePromoteResult"]
