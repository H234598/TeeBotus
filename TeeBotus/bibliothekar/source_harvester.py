from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from TeeBotus.runtime.source_quality import SourceQualityInput, SourceQualityPipeline, SourceQualityReport, SourceRoute


HARVEST_MANIFEST = "harvest_manifest.jsonl"
HARVEST_DIRS = ("inbox", "quarantine", "accepted", "rejected")


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
        duplicate = self._existing_path_for_hash(sha256)
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

    def _stored_path(self, source: Path, sha256: str, route: SourceRoute) -> Path:
        safe_name = _safe_filename(source.name)
        return self.library_root / _route_dir(route) / f"{sha256[:16]}-{safe_name}"

    def _existing_path_for_hash(self, sha256: str) -> Path | None:
        if not self.manifest_path.exists():
            return None
        for line in self.manifest_path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict) or row.get("sha256") != sha256:
                continue
            stored = Path(str(row.get("stored_path") or ""))
            if stored.exists():
                return stored
        return None

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
    safe = "".join(char if char.isalnum() or char in {".", "-", "_"} else "_" for char in str(value or "").strip())
    return safe.strip("._") or "source"


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


__all__ = ["HARVEST_DIRS", "HARVEST_MANIFEST", "SourceHarvestResult", "SourceHarvester"]
