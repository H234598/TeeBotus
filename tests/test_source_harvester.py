from __future__ import annotations

import json

import pytest

from TeeBotus.bibliothekar.source_harvester import HARVEST_DIRS, SourceHarvester
from TeeBotus.runtime.source_quality import FakeNLIVerifier, SourceQualityPipeline


def test_source_harvester_routes_accepted_file_without_blind_ingest(tmp_path):
    source = tmp_path / "download" / "therapie.pdf"
    source.parent.mkdir()
    source.write_text("Schlafhygiene und Aktivierung.", encoding="utf-8")
    harvester = SourceHarvester(
        tmp_path / "library",
        quality_pipeline=SourceQualityPipeline(nli_verifier=FakeNLIVerifier(stance="entailment", confidence=0.91)),
    )

    result = harvester.harvest_path(
        source,
        metadata={"title": "Therapie", "license": "private"},
        claims=("Schlafhygiene ist relevant.",),
        evidence=("Schlafhygiene und Aktivierung.",),
    )

    assert result.route == "accepted"
    assert result.accepted_for_ingest is True
    assert result.stored_path is not None
    assert result.stored_path.parent == tmp_path / "library" / "accepted"
    assert not (tmp_path / "library" / "therapie.pdf").exists()
    manifest = [json.loads(line) for line in (tmp_path / "library" / "harvest_manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    assert manifest[0]["route"] == "accepted"
    assert manifest[0]["accepted_for_ingest"] is True
    assert manifest[0]["decision"]["status"] == "trusted"


def test_source_harvester_quarantines_review_sources_and_dedupes_by_hash(tmp_path):
    source = tmp_path / "notes.txt"
    duplicate = tmp_path / "copy.txt"
    source.write_text("Notizen ohne Lizenz.", encoding="utf-8")
    duplicate.write_text("Notizen ohne Lizenz.", encoding="utf-8")
    harvester = SourceHarvester(tmp_path / "library")

    first = harvester.harvest_path(source, metadata={"title": "Notizen"})
    second = harvester.harvest_path(duplicate, metadata={"title": "Kopie"})

    assert first.route == "quarantine"
    assert first.stored_path is not None
    assert first.stored_path.parent == tmp_path / "library" / "quarantine"
    assert second.duplicate_of == first.stored_path
    assert second.accepted_for_ingest is False
    rows = [json.loads(line) for line in harvester.manifest_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert rows[1]["duplicate_of"] == str(first.stored_path)


def test_source_harvester_rejects_executables_and_refuses_symlinks(tmp_path):
    source = tmp_path / "payload.sh"
    source.write_text("#!/bin/sh\nrm -rf /tmp/nope\n", encoding="utf-8")
    harvester = SourceHarvester(tmp_path / "library")

    result = harvester.harvest_path(source, metadata={"title": "Payload", "license": "private"})

    assert result.route == "rejected"
    assert result.stored_path is not None
    assert result.stored_path.parent == tmp_path / "library" / "rejected"
    for dirname in HARVEST_DIRS:
        assert (tmp_path / "library" / dirname).is_dir()

    link = tmp_path / "link.txt"
    link.symlink_to(source)
    with pytest.raises(ValueError, match="refuses symlink"):
        harvester.harvest_path(link, metadata={"title": "Link", "license": "private"})
