from __future__ import annotations

import hashlib
import json

import pytest

from TeeBotus.bibliothekar.source_harvester import HARVEST_DIRS, SourceHarvester
from TeeBotus.runtime.bibliothekar import BibliothekarStore
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


def test_source_harvester_promotes_accepted_source_before_indexing(tmp_path):
    instances_dir = tmp_path / "instances"
    source = tmp_path / "download" / "therapie.txt"
    source.parent.mkdir()
    marker = "PROMOTED_SOURCE_MARKER_D71E"
    source.write_text(f"Schlafhygiene und Aktivierung {marker}.", encoding="utf-8")
    store = BibliothekarStore("Depressionsbot", instances_dir)
    harvester = SourceHarvester(
        store.library_dir,
        quality_pipeline=SourceQualityPipeline(nli_verifier=FakeNLIVerifier(stance="entailment", confidence=0.91)),
    )

    harvest = harvester.harvest_path(
        source,
        metadata={"title": "Therapie", "license": "private"},
        claims=("Schlafhygiene ist relevant.",),
        evidence=("Schlafhygiene und Aktivierung.",),
    )
    assert store.rebuild()["chunk_count"] == 0

    promoted = harvester.promote_accepted(harvest.stored_path)
    index = store.rebuild()
    chunks_text = store.chunks_path.read_text(encoding="utf-8")
    chunk = json.loads(chunks_text.splitlines()[0])
    rows = [json.loads(line) for line in harvester.manifest_path.read_text(encoding="utf-8").splitlines()]

    assert promoted.promoted_path.parent == store.library_dir / "books"
    assert promoted.promoted_path.exists()
    assert index["chunk_count"] == 1
    assert marker in chunks_text
    assert chunk["title"] == "Therapie"
    assert chunk["source_quality"] == "trusted"
    assert chunk["citation_quality"] == "trusted"
    assert chunk["source_quality_reason"] == "metadata checks passed and NLI evidence supports extracted claims"
    assert chunk["source_harvest_route"] == "accepted"
    assert rows[-1]["event"] == "promoted"
    assert rows[-1]["stored_path"] == str(promoted.promoted_path)


def test_source_harvester_promotes_manifest_string_true_acceptance(tmp_path):
    instances_dir = tmp_path / "instances"
    source = tmp_path / "download" / "therapie.txt"
    source.parent.mkdir()
    source.write_text("Schlafhygiene und Aktivierung.", encoding="utf-8")
    store = BibliothekarStore("Depressionsbot", instances_dir)
    harvester = SourceHarvester(
        store.library_dir,
        quality_pipeline=SourceQualityPipeline(nli_verifier=FakeNLIVerifier(stance="entailment", confidence=0.91)),
    )
    harvest = harvester.harvest_path(
        source,
        metadata={"title": "Therapie", "license": "private"},
        claims=("Schlafhygiene ist relevant.",),
        evidence=("Schlafhygiene und Aktivierung.",),
    )
    rows = [json.loads(line) for line in harvester.manifest_path.read_text(encoding="utf-8").splitlines()]
    rows[0]["accepted_for_ingest"] = "true"
    harvester.manifest_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )

    promoted = harvester.promote_accepted(harvest.stored_path)

    assert promoted.promoted_path.exists()
    assert promoted.promoted_path.parent == store.library_dir / "books"


def test_source_harvester_ignores_non_ingestable_accepted_duplicate_rows(tmp_path):
    instances_dir = tmp_path / "instances"
    source = tmp_path / "download" / "therapie.txt"
    source.parent.mkdir()
    source.write_text("Schlafhygiene und Aktivierung.", encoding="utf-8")
    store = BibliothekarStore("Depressionsbot", instances_dir)
    harvester = SourceHarvester(
        store.library_dir,
        quality_pipeline=SourceQualityPipeline(nli_verifier=FakeNLIVerifier(stance="entailment", confidence=0.91)),
    )
    harvester.prepare()
    sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    stale_path = store.library_dir / "accepted" / f"{sha256[:16]}-{source.name}"
    stale_path.write_text("alter nicht ingestbarer Stand", encoding="utf-8")
    harvester.manifest_path.write_text(
        json.dumps(
            {
                "accepted_for_ingest": False,
                "route": "accepted",
                "sha256": sha256,
                "source_path": str(source),
                "stored_path": str(stale_path),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    result = harvester.harvest_path(
        source,
        metadata={"title": "Therapie", "license": "private"},
        claims=("Schlafhygiene ist relevant.",),
        evidence=("Schlafhygiene und Aktivierung.",),
    )
    rows = [json.loads(line) for line in harvester.manifest_path.read_text(encoding="utf-8").splitlines()]

    assert result.duplicate_of is None
    assert result.accepted_for_ingest is True
    assert result.stored_path == stale_path
    assert rows[-1]["accepted_for_ingest"] is True


def test_source_harvester_ignores_external_accepted_duplicate_paths(tmp_path):
    instances_dir = tmp_path / "instances"
    source = tmp_path / "download" / "therapie.txt"
    source.parent.mkdir()
    source.write_text("Schlafhygiene und Aktivierung.", encoding="utf-8")
    external = tmp_path / "outside-accepted.txt"
    external.write_text("Schlafhygiene und Aktivierung.", encoding="utf-8")
    store = BibliothekarStore("Depressionsbot", instances_dir)
    harvester = SourceHarvester(
        store.library_dir,
        quality_pipeline=SourceQualityPipeline(nli_verifier=FakeNLIVerifier(stance="entailment", confidence=0.91)),
    )
    harvester.prepare()
    sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    harvester.manifest_path.write_text(
        json.dumps(
            {
                "accepted_for_ingest": True,
                "route": "accepted",
                "sha256": sha256,
                "source_path": str(source),
                "stored_path": str(external),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    result = harvester.harvest_path(
        source,
        metadata={"title": "Therapie", "license": "private"},
        claims=("Schlafhygiene ist relevant.",),
        evidence=("Schlafhygiene und Aktivierung.",),
    )

    assert result.duplicate_of is None
    assert result.accepted_for_ingest is True
    assert result.stored_path is not None
    assert result.stored_path.parent == store.library_dir / "accepted"


def test_source_harvester_rejects_absolute_promote_destination_dir(tmp_path):
    source = tmp_path / "download" / "therapie.txt"
    source.parent.mkdir()
    source.write_text("Schlafhygiene und Aktivierung.", encoding="utf-8")
    store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    harvester = SourceHarvester(
        store.library_dir,
        quality_pipeline=SourceQualityPipeline(nli_verifier=FakeNLIVerifier(stance="entailment", confidence=0.91)),
    )
    harvest = harvester.harvest_path(
        source,
        metadata={"title": "Therapie", "license": "private"},
        claims=("Schlafhygiene ist relevant.",),
        evidence=("Schlafhygiene und Aktivierung.",),
    )

    with pytest.raises(ValueError, match="relative library subdirectory"):
        harvester.promote_accepted(harvest.stored_path, destination_dir=str(tmp_path / "outside"))


def test_source_harvester_rejects_promote_destination_ignored_by_indexer(tmp_path):
    source = tmp_path / "download" / "therapie.txt"
    source.parent.mkdir()
    source.write_text("Schlafhygiene und Aktivierung.", encoding="utf-8")
    store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    harvester = SourceHarvester(
        store.library_dir,
        quality_pipeline=SourceQualityPipeline(nli_verifier=FakeNLIVerifier(stance="entailment", confidence=0.91)),
    )
    harvest = harvester.harvest_path(
        source,
        metadata={"title": "Therapie", "license": "private"},
        claims=("Schlafhygiene ist relevant.",),
        evidence=("Schlafhygiene und Aktivierung.",),
    )

    with pytest.raises(ValueError, match="indexed Bibliothek source path"):
        harvester.promote_accepted(harvest.stored_path, destination_dir="data/accounts")

    assert not (store.library_dir / "data" / "accounts").exists()


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

    with pytest.raises(ValueError, match="accepted harvest staging"):
        harvester.promote_accepted(first.stored_path)


def test_source_harvester_allows_reclassification_with_better_metadata(tmp_path):
    source = tmp_path / "quelle.txt"
    source.write_text("Schlafhygiene und Aktivierung.", encoding="utf-8")
    harvester = SourceHarvester(
        tmp_path / "library",
        quality_pipeline=SourceQualityPipeline(nli_verifier=FakeNLIVerifier(stance="entailment", confidence=0.91)),
    )

    quarantined = harvester.harvest_path(source, metadata={"title": "Quelle"})
    accepted = harvester.harvest_path(
        source,
        metadata={"title": "Quelle", "license": "private"},
        claims=("Schlafhygiene ist relevant.",),
        evidence=("Schlafhygiene und Aktivierung.",),
    )

    assert quarantined.route == "quarantine"
    assert accepted.route == "accepted"
    assert accepted.duplicate_of is None
    assert accepted.accepted_for_ingest is True
    assert accepted.stored_path is not None
    assert accepted.stored_path.parent == tmp_path / "library" / "accepted"


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
