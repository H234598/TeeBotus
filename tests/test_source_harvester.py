from __future__ import annotations

import hashlib
import json
import os
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from TeeBotus.bibliothekar import source_harvester as source_harvester_module
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


def test_source_harvester_serializes_duplicate_hash_check_and_copy(tmp_path, monkeypatch):
    source_dir = tmp_path / "download"
    source_dir.mkdir()
    source_text = "Schlafhygiene und Aktivierung."
    first_source = source_dir / "first.txt"
    second_source = source_dir / "second.txt"
    first_source.write_text(source_text, encoding="utf-8")
    second_source.write_text(source_text, encoding="utf-8")
    harvester = SourceHarvester(
        tmp_path / "library",
        quality_pipeline=SourceQualityPipeline(nli_verifier=FakeNLIVerifier(stance="entailment", confidence=0.91)),
    )
    original_copy = source_harvester_module._copy_file_private
    first_copy_started = threading.Event()
    release_first_copy = threading.Event()
    first_copy = True

    def blocking_copy(source, destination):
        nonlocal first_copy
        if first_copy:
            first_copy = False
            first_copy_started.set()
            assert release_first_copy.wait(timeout=5)
        return original_copy(source, destination)

    monkeypatch.setattr(source_harvester_module, "_copy_file_private", blocking_copy)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(harvester.harvest_path, first_source, metadata={"license": "private"})
        assert first_copy_started.wait(timeout=5)
        second = executor.submit(harvester.harvest_path, second_source, metadata={"license": "private"})
        release_first_copy.set()
        results = [first.result(timeout=5), second.result(timeout=5)]

    assert sum(result.duplicate_of is None for result in results) == 1
    assert sum(result.duplicate_of is not None for result in results) == 1
    rows = [json.loads(line) for line in harvester.manifest_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert sum(bool(row["duplicate_of"]) for row in rows) == 1


def test_source_harvester_refuses_symlink_harvest_destination_file(tmp_path):
    source = tmp_path / "download" / "therapie.txt"
    source.parent.mkdir()
    source.write_text("Schlafhygiene und Aktivierung.", encoding="utf-8")
    outside_target = tmp_path / "outside-accepted.txt"
    library_dir = tmp_path / "library"
    accepted_dir = library_dir / "accepted"
    accepted_dir.mkdir(parents=True)
    sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    (accepted_dir / f"{sha256[:16]}-{source.name}").symlink_to(outside_target)
    harvester = SourceHarvester(
        library_dir,
        quality_pipeline=SourceQualityPipeline(nli_verifier=FakeNLIVerifier(stance="entailment", confidence=0.91)),
    )

    with pytest.raises(ValueError, match="symlink destination file"):
        harvester.harvest_path(
            source,
            metadata={"title": "Therapie", "license": "private"},
            claims=("Schlafhygiene ist relevant.",),
            evidence=("Schlafhygiene und Aktivierung.",),
        )

    assert not outside_target.exists()


def test_source_harvester_file_hash_refuses_symlink(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("Schlafhygiene und Aktivierung.", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(source)

    with pytest.raises(ValueError, match="refuses symlink sources"):
        source_harvester_module._file_sha256(link)


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="requires atomic no-follow file open")
def test_source_harvester_refuses_harvest_destination_symlink_swapped_before_copy(tmp_path, monkeypatch):
    source = tmp_path / "download" / "therapie.txt"
    source.parent.mkdir()
    source.write_text("Schlafhygiene und Aktivierung.", encoding="utf-8")
    outside_target = tmp_path / "outside-accepted.txt"
    outside_target.write_text("outside-before\n", encoding="utf-8")
    library_dir = tmp_path / "library"
    sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    expected_destination = library_dir / "accepted" / f"{sha256[:16]}-{source.name}"
    original_open = os.open

    def open_with_destination_swap(path, flags, *args, **kwargs):
        if Path(path) == expected_destination:
            Path(path).symlink_to(outside_target)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(source_harvester_module.os, "open", open_with_destination_swap)
    harvester = SourceHarvester(
        library_dir,
        quality_pipeline=SourceQualityPipeline(nli_verifier=FakeNLIVerifier(stance="entailment", confidence=0.91)),
    )

    with pytest.raises(ValueError, match="symlink destination file"):
        harvester.harvest_path(
            source,
            metadata={"title": "Therapie", "license": "private"},
            claims=("Schlafhygiene ist relevant.",),
            evidence=("Schlafhygiene und Aktivierung.",),
        )

    assert outside_target.read_text(encoding="utf-8") == "outside-before\n"


def test_source_harvester_move_refuses_replaced_source_before_unlink(tmp_path, monkeypatch):
    source = tmp_path / "download" / "therapie.txt"
    source.parent.mkdir()
    source.write_text("Schlafhygiene und Aktivierung.", encoding="utf-8")
    replacement_text = "nicht loeschen\n"
    original_copy = source_harvester_module._copy_file_private

    def copy_and_replace_source(src, dst):
        source_stat = original_copy(src, dst)
        Path(src).unlink()
        Path(src).write_text(replacement_text, encoding="utf-8")
        return source_stat

    monkeypatch.setattr(source_harvester_module, "_copy_file_private", copy_and_replace_source)
    harvester = SourceHarvester(
        tmp_path / "library",
        quality_pipeline=SourceQualityPipeline(nli_verifier=FakeNLIVerifier(stance="entailment", confidence=0.91)),
    )

    with pytest.raises(ValueError, match="source changed before unlink"):
        harvester.harvest_path(
            source,
            copy=False,
            metadata={"title": "Therapie", "license": "private"},
            claims=("Schlafhygiene ist relevant.",),
            evidence=("Schlafhygiene und Aktivierung.",),
        )

    assert source.read_text(encoding="utf-8") == replacement_text


def test_source_harvester_move_keeps_source_when_manifest_append_fails(tmp_path):
    source = tmp_path / "download" / "therapie.txt"
    source.parent.mkdir()
    source_text = "Schlafhygiene und Aktivierung."
    source.write_text(source_text, encoding="utf-8")
    library_dir = tmp_path / "library"
    outside_manifest = tmp_path / "outside_manifest.jsonl"
    outside_manifest.write_text("outside-before\n", encoding="utf-8")

    class SymlinkManifestPipeline:
        def __init__(self, manifest_path: Path, target_path: Path) -> None:
            self.manifest_path = manifest_path
            self.target_path = target_path
            self.inner = SourceQualityPipeline(nli_verifier=FakeNLIVerifier(stance="entailment", confidence=0.91))

        def evaluate(self, source_input):
            self.manifest_path.symlink_to(self.target_path)
            return self.inner.evaluate(source_input)

    harvester = SourceHarvester(
        library_dir,
        quality_pipeline=SymlinkManifestPipeline(library_dir / "harvest_manifest.jsonl", outside_manifest),
    )

    with pytest.raises(ValueError, match="symlink manifest file"):
        harvester.harvest_path(
            source,
            copy=False,
            metadata={"title": "Therapie", "license": "private"},
            claims=("Schlafhygiene ist relevant.",),
            evidence=("Schlafhygiene und Aktivierung.",),
        )

    assert source.read_text(encoding="utf-8") == source_text
    assert outside_manifest.read_text(encoding="utf-8") == "outside-before\n"
    assert not any((library_dir / "accepted").iterdir())


def test_source_harvester_copy_removes_staged_file_when_manifest_append_fails(tmp_path):
    source = tmp_path / "download" / "therapie.txt"
    source.parent.mkdir()
    source_text = "Schlafhygiene und Aktivierung."
    source.write_text(source_text, encoding="utf-8")
    library_dir = tmp_path / "library"
    outside_manifest = tmp_path / "outside_manifest.jsonl"
    outside_manifest.write_text("outside-before\n", encoding="utf-8")

    class SymlinkManifestPipeline:
        def __init__(self, manifest_path: Path, target_path: Path) -> None:
            self.manifest_path = manifest_path
            self.target_path = target_path
            self.inner = SourceQualityPipeline(nli_verifier=FakeNLIVerifier(stance="entailment", confidence=0.91))

        def evaluate(self, source_input):
            self.manifest_path.symlink_to(self.target_path)
            return self.inner.evaluate(source_input)

    harvester = SourceHarvester(
        library_dir,
        quality_pipeline=SymlinkManifestPipeline(library_dir / "harvest_manifest.jsonl", outside_manifest),
    )

    with pytest.raises(ValueError, match="symlink manifest file"):
        harvester.harvest_path(
            source,
            metadata={"title": "Therapie", "license": "private"},
            claims=("Schlafhygiene ist relevant.",),
            evidence=("Schlafhygiene und Aktivierung.",),
        )

    assert source.read_text(encoding="utf-8") == source_text
    assert outside_manifest.read_text(encoding="utf-8") == "outside-before\n"
    assert not any((library_dir / "accepted").iterdir())


def test_source_harvester_refuses_symlink_manifest_file_before_copy(tmp_path):
    source = tmp_path / "download" / "therapie.txt"
    source.parent.mkdir()
    source.write_text("Schlafhygiene und Aktivierung.", encoding="utf-8")
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    outside_manifest = tmp_path / "outside_manifest.jsonl"
    outside_manifest.write_text("outside-before\n", encoding="utf-8")
    (library_dir / "harvest_manifest.jsonl").symlink_to(outside_manifest)
    harvester = SourceHarvester(
        library_dir,
        quality_pipeline=SourceQualityPipeline(nli_verifier=FakeNLIVerifier(stance="entailment", confidence=0.91)),
    )

    with pytest.raises(ValueError, match="symlink manifest file"):
        harvester.harvest_path(
            source,
            metadata={"title": "Therapie", "license": "private"},
            claims=("Schlafhygiene ist relevant.",),
            evidence=("Schlafhygiene und Aktivierung.",),
        )

    assert outside_manifest.read_text(encoding="utf-8") == "outside-before\n"
    assert not (library_dir / "accepted").exists()


def test_source_harvester_refuses_manifest_symlink_swapped_before_append(tmp_path):
    source = tmp_path / "download" / "therapie.txt"
    source.parent.mkdir()
    source.write_text("Schlafhygiene und Aktivierung.", encoding="utf-8")
    library_dir = tmp_path / "library"
    outside_manifest = tmp_path / "outside_manifest.jsonl"
    outside_manifest.write_text("outside-before\n", encoding="utf-8")

    class SymlinkManifestPipeline:
        def __init__(self, manifest_path: Path, target_path: Path) -> None:
            self.manifest_path = manifest_path
            self.target_path = target_path
            self.inner = SourceQualityPipeline(nli_verifier=FakeNLIVerifier(stance="entailment", confidence=0.91))

        def evaluate(self, source_input):
            self.manifest_path.symlink_to(self.target_path)
            return self.inner.evaluate(source_input)

    harvester = SourceHarvester(
        library_dir,
        quality_pipeline=SymlinkManifestPipeline(library_dir / "harvest_manifest.jsonl", outside_manifest),
    )

    with pytest.raises(ValueError, match="symlink manifest file"):
        harvester.harvest_path(
            source,
            metadata={"title": "Therapie", "license": "private"},
            claims=("Schlafhygiene ist relevant.",),
            evidence=("Schlafhygiene und Aktivierung.",),
        )

    assert outside_manifest.read_text(encoding="utf-8") == "outside-before\n"


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="requires atomic no-follow file open")
def test_source_harvester_manifest_append_uses_atomic_nofollow(tmp_path, monkeypatch):
    source = tmp_path / "download" / "therapie.txt"
    source.parent.mkdir()
    source.write_text("Schlafhygiene und Aktivierung.", encoding="utf-8")
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    outside_manifest = tmp_path / "outside_manifest.jsonl"
    outside_manifest.write_text("outside-before\n", encoding="utf-8")
    (library_dir / "harvest_manifest.jsonl").symlink_to(outside_manifest)
    monkeypatch.setattr(source_harvester_module, "_refuse_symlink_manifest_file", lambda path: None)
    harvester = SourceHarvester(
        library_dir,
        quality_pipeline=SourceQualityPipeline(nli_verifier=FakeNLIVerifier(stance="entailment", confidence=0.91)),
    )

    with pytest.raises(ValueError, match="symlink manifest file"):
        harvester.harvest_path(
            source,
            metadata={"title": "Therapie", "license": "private"},
            claims=("Schlafhygiene ist relevant.",),
            evidence=("Schlafhygiene und Aktivierung.",),
        )

    assert outside_manifest.read_text(encoding="utf-8") == "outside-before\n"


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="requires atomic no-follow file open")
def test_source_harvester_manifest_duplicate_read_uses_atomic_nofollow(tmp_path):
    source = tmp_path / "download" / "therapie.txt"
    source.parent.mkdir()
    source.write_text("Schlafhygiene und Aktivierung.", encoding="utf-8")
    library_dir = tmp_path / "library"
    outside_manifest = tmp_path / "outside_manifest.jsonl"
    outside_manifest.write_text("outside-before\n", encoding="utf-8")

    class SymlinkManifestBeforeDuplicatePipeline:
        def __init__(self, manifest_path: Path, target_path: Path) -> None:
            self.manifest_path = manifest_path
            self.target_path = target_path
            self.inner = SourceQualityPipeline(nli_verifier=FakeNLIVerifier(stance="entailment", confidence=0.91))

        def evaluate(self, source_input):
            self.manifest_path.symlink_to(self.target_path)
            return self.inner.evaluate(source_input)

    harvester = SourceHarvester(
        library_dir,
        quality_pipeline=SymlinkManifestBeforeDuplicatePipeline(library_dir / "harvest_manifest.jsonl", outside_manifest),
    )

    with pytest.raises(ValueError, match="symlink manifest file"):
        harvester.harvest_path(
            source,
            metadata={"title": "Therapie", "license": "private"},
            claims=("Schlafhygiene ist relevant.",),
            evidence=("Schlafhygiene und Aktivierung.",),
        )

    assert outside_manifest.read_text(encoding="utf-8") == "outside-before\n"
    assert not any((library_dir / "accepted").iterdir())


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="requires atomic no-follow file open")
def test_source_harvester_promote_manifest_read_uses_atomic_nofollow(tmp_path, monkeypatch):
    library_dir = tmp_path / "library"
    harvester = SourceHarvester(library_dir)
    harvester.prepare()
    staged = library_dir / "accepted" / "therapie.txt"
    staged.write_text("Schlafhygiene und Aktivierung.", encoding="utf-8")
    sha256 = hashlib.sha256(staged.read_bytes()).hexdigest()
    harvester.manifest_path.write_text(
        json.dumps(
            {
                "accepted_for_ingest": True,
                "route": "accepted",
                "sha256": sha256,
                "source_path": str(staged),
                "stored_path": str(staged),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    outside_manifest = tmp_path / "outside_manifest.jsonl"
    outside_manifest.write_text("outside-before\n", encoding="utf-8")
    original_open = os.open

    def open_and_swap_manifest(path, flags, *args, **kwargs):
        if Path(path) == harvester.manifest_path:
            harvester.manifest_path.unlink()
            harvester.manifest_path.symlink_to(outside_manifest)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(source_harvester_module.os, "open", open_and_swap_manifest)

    with pytest.raises(ValueError, match="symlink manifest file"):
        harvester.promote_accepted(staged)

    assert outside_manifest.read_text(encoding="utf-8") == "outside-before\n"
    assert not (library_dir / "books" / "therapie.txt").exists()


def test_source_harvester_manifest_append_does_not_chmod_swapped_symlink(tmp_path, monkeypatch):
    source = tmp_path / "download" / "therapie.txt"
    source.parent.mkdir()
    source.write_text("Schlafhygiene und Aktivierung.", encoding="utf-8")
    library_dir = tmp_path / "library"
    outside_manifest = tmp_path / "outside_manifest.jsonl"
    outside_manifest.write_text("outside-before\n", encoding="utf-8")
    outside_manifest.chmod(0o644)
    manifest_path = library_dir / "harvest_manifest.jsonl"
    original_fdopen = os.fdopen

    class SwapManifestAfterWrite:
        def __init__(self, handle) -> None:
            self.handle = handle

        def __enter__(self):
            self.handle.__enter__()
            return self

        def __exit__(self, exc_type, exc, tb):
            result = self.handle.__exit__(exc_type, exc, tb)
            manifest_path.unlink()
            manifest_path.symlink_to(outside_manifest)
            return result

        def write(self, text: str):
            return self.handle.write(text)

    def fdopen_and_swap(fd, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        handle = original_fdopen(fd, *args, **kwargs)
        if "a" in str(mode):
            return SwapManifestAfterWrite(handle)
        return handle

    monkeypatch.setattr(source_harvester_module.os, "fdopen", fdopen_and_swap)
    harvester = SourceHarvester(
        library_dir,
        quality_pipeline=SourceQualityPipeline(nli_verifier=FakeNLIVerifier(stance="entailment", confidence=0.91)),
    )

    harvester.harvest_path(
        source,
        metadata={"title": "Therapie", "license": "private"},
        claims=("Schlafhygiene ist relevant.",),
        evidence=("Schlafhygiene und Aktivierung.",),
    )

    assert stat.S_IMODE(outside_manifest.stat().st_mode) == 0o644
    assert outside_manifest.read_text(encoding="utf-8") == "outside-before\n"


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


@pytest.mark.parametrize("destination_dir", ("books", "books/thema"))
def test_source_harvester_refuses_symlink_promote_destination_dir(tmp_path, destination_dir):
    instances_dir = tmp_path / "instances"
    source = tmp_path / "download" / "therapie.txt"
    source.parent.mkdir()
    source.write_text("Schlafhygiene und Aktivierung.", encoding="utf-8")
    outside_dir = tmp_path / "outside-books"
    outside_dir.mkdir()
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
    (store.library_dir / "books").symlink_to(outside_dir, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink promote destination directory"):
        harvester.promote_accepted(harvest.stored_path, destination_dir=destination_dir)

    assert list(outside_dir.iterdir()) == []


def test_source_harvester_refuses_symlink_promote_destination_file(tmp_path):
    instances_dir = tmp_path / "instances"
    source = tmp_path / "download" / "therapie.txt"
    source.parent.mkdir()
    source.write_text("Schlafhygiene und Aktivierung.", encoding="utf-8")
    outside_target = tmp_path / "outside-promoted.txt"
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
    books_dir = store.library_dir / "books"
    books_dir.mkdir()
    (books_dir / harvest.stored_path.name).symlink_to(outside_target)

    with pytest.raises(ValueError, match="symlink destination file"):
        harvester.promote_accepted(harvest.stored_path)

    assert not outside_target.exists()


def test_source_harvester_preserves_suffix_for_symbolic_source_names(tmp_path):
    instances_dir = tmp_path / "instances"
    source = tmp_path / "download" / "###.txt"
    source.parent.mkdir()
    marker = "SYMBOLIC_SOURCE_MARKER_8751"
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
    promoted = harvester.promote_accepted(harvest.stored_path)
    index = store.rebuild()

    assert harvest.stored_path is not None
    assert harvest.stored_path.suffix == ".txt"
    assert promoted.promoted_path.suffix == ".txt"
    assert index["chunk_count"] == 1
    assert marker in store.chunks_path.read_text(encoding="utf-8")


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


def test_source_harvester_promotes_manifest_normalized_route_and_hash(tmp_path):
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
    rows[0]["accepted_for_ingest"] = "TRUE"
    rows[0]["route"] = " Accepted "
    rows[0]["sha256"] = str(rows[0]["sha256"]).upper()
    harvester.manifest_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )

    promoted = harvester.promote_accepted(harvest.stored_path)

    assert promoted.promoted_path.exists()
    assert promoted.promoted_path.parent == store.library_dir / "books"


def test_source_harvester_promote_ignores_promoted_event_acceptance_rows(tmp_path):
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
    rows[0]["event"] = "promoted"
    rows[0]["route"] = "accepted"
    rows[0]["accepted_for_ingest"] = True
    harvester.manifest_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not marked accepted_for_ingest"):
        harvester.promote_accepted(harvest.stored_path)


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


def test_source_harvester_detects_duplicate_with_normalized_manifest_route_and_hash(tmp_path):
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
    accepted_path = store.library_dir / "accepted" / f"{sha256[:16]}-{source.name}"
    accepted_path.write_text("Schlafhygiene und Aktivierung.", encoding="utf-8")
    harvester.manifest_path.write_text(
        json.dumps(
            {
                "accepted_for_ingest": "TRUE",
                "route": " Accepted ",
                "sha256": sha256.upper(),
                "source_path": str(source),
                "stored_path": str(accepted_path),
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

    assert result.duplicate_of == accepted_path.resolve()
    assert result.stored_path is None
    assert result.accepted_for_ingest is False


def test_source_harvester_ignores_stale_duplicate_path_with_wrong_hash(tmp_path):
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
    stale_path.write_text("anderer Inhalt mit falschem Hash", encoding="utf-8")
    harvester.manifest_path.write_text(
        json.dumps(
            {
                "accepted_for_ingest": True,
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

    assert result.duplicate_of is None
    assert result.accepted_for_ingest is True
    assert result.stored_path == stale_path
    assert result.stored_path.read_text(encoding="utf-8") == "Schlafhygiene und Aktivierung."


def test_source_harvester_ignores_promoted_event_accepted_duplicate_rows(tmp_path):
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
    accepted_path = store.library_dir / "accepted" / f"{sha256[:16]}-{source.name}"
    accepted_path.write_text("Schlafhygiene und Aktivierung.", encoding="utf-8")
    harvester.manifest_path.write_text(
        json.dumps(
            {
                "accepted_for_ingest": True,
                "event": "promoted",
                "route": "accepted",
                "sha256": sha256,
                "source_path": str(source),
                "stored_path": str(accepted_path),
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
    assert result.stored_path == accepted_path


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


def test_source_harvester_refuses_symlink_harvest_staging_dir(tmp_path):
    source = tmp_path / "download" / "therapie.txt"
    source.parent.mkdir()
    source.write_text("Schlafhygiene und Aktivierung.", encoding="utf-8")
    library_dir = tmp_path / "library"
    outside_dir = tmp_path / "outside-accepted"
    library_dir.mkdir()
    outside_dir.mkdir()
    (library_dir / "accepted").symlink_to(outside_dir, target_is_directory=True)
    harvester = SourceHarvester(
        library_dir,
        quality_pipeline=SourceQualityPipeline(nli_verifier=FakeNLIVerifier(stance="entailment", confidence=0.91)),
    )

    with pytest.raises(ValueError, match="symlink harvest staging directory"):
        harvester.harvest_path(
            source,
            metadata={"title": "Therapie", "license": "private"},
            claims=("Schlafhygiene ist relevant.",),
            evidence=("Schlafhygiene und Aktivierung.",),
        )

    assert list(outside_dir.iterdir()) == []


@pytest.mark.skipif(
    not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"),
    reason="requires atomic no-follow directory open",
)
def test_source_harvester_refuses_staging_dir_symlink_swapped_before_chmod(tmp_path, monkeypatch):
    source = tmp_path / "download" / "therapie.txt"
    source.parent.mkdir()
    source.write_text("Schlafhygiene und Aktivierung.", encoding="utf-8")
    library_dir = tmp_path / "library"
    accepted_dir = library_dir / "accepted"
    outside_dir = tmp_path / "outside-accepted"
    outside_dir.mkdir()
    original_open = os.open
    swapped = False

    def open_and_swap_dir(path, flags, *args, **kwargs):
        nonlocal swapped
        if Path(path) == accepted_dir and flags & os.O_DIRECTORY and not swapped:
            accepted_dir.rmdir()
            accepted_dir.symlink_to(outside_dir, target_is_directory=True)
            swapped = True
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(source_harvester_module.os, "open", open_and_swap_dir)
    harvester = SourceHarvester(
        library_dir,
        quality_pipeline=SourceQualityPipeline(nli_verifier=FakeNLIVerifier(stance="entailment", confidence=0.91)),
    )

    with pytest.raises(ValueError, match="symlink harvest staging directory"):
        harvester.harvest_path(
            source,
            metadata={"title": "Therapie", "license": "private"},
            claims=("Schlafhygiene ist relevant.",),
            evidence=("Schlafhygiene und Aktivierung.",),
        )

    assert swapped is True
    assert list(outside_dir.iterdir()) == []


def test_source_harvester_resolves_relative_manifest_paths_after_cwd_change(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    download_dir = workspace / "download"
    download_dir.mkdir()
    source = download_dir / "therapie.txt"
    source.write_text("Schlafhygiene und Aktivierung.", encoding="utf-8")
    relative_library = Path("instances") / "Depressionsbot" / "data" / "Bibliothek"
    monkeypatch.chdir(workspace)
    harvester = SourceHarvester(
        relative_library,
        quality_pipeline=SourceQualityPipeline(nli_verifier=FakeNLIVerifier(stance="entailment", confidence=0.91)),
    )
    first = harvester.harvest_path(
        source,
        metadata={"title": "Therapie", "license": "private"},
        claims=("Schlafhygiene ist relevant.",),
        evidence=("Schlafhygiene und Aktivierung.",),
    )
    assert first.stored_path is not None
    assert not first.stored_path.is_absolute()
    duplicate = download_dir / "therapie-kopie.txt"
    duplicate.write_text("Schlafhygiene und Aktivierung.", encoding="utf-8")
    other_cwd = tmp_path / "other-cwd"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)
    absolute_harvester = SourceHarvester(
        workspace / relative_library,
        quality_pipeline=SourceQualityPipeline(nli_verifier=FakeNLIVerifier(stance="entailment", confidence=0.91)),
    )

    second = absolute_harvester.harvest_path(
        duplicate,
        metadata={"title": "Therapie", "license": "private"},
        claims=("Schlafhygiene ist relevant.",),
        evidence=("Schlafhygiene und Aktivierung.",),
    )

    assert second.duplicate_of == (workspace / first.stored_path).resolve()
    assert second.stored_path is None
    assert second.accepted_for_ingest is False


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


@pytest.mark.parametrize("destination_dir", ("https://example.test/books", "file:books", "mailto:books", "urn:books"))
def test_source_harvester_rejects_uri_promote_destination_dir(tmp_path, destination_dir):
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
        harvester.promote_accepted(harvest.stored_path, destination_dir=destination_dir)

    assert not (store.library_dir / "https").exists()
    assert not (store.library_dir / "file_books").exists()


@pytest.mark.parametrize("destination_dir", ("###", "books/###"))
def test_source_harvester_rejects_promote_destination_without_usable_name(tmp_path, destination_dir):
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

    with pytest.raises(ValueError, match="usable name"):
        harvester.promote_accepted(harvest.stored_path, destination_dir=destination_dir)

    assert not (store.library_dir / "source").exists()
    assert not (store.library_dir / "books" / "source").exists()


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
    spaced_source = tmp_path / "payload-spaced.sh "
    spaced_source.write_text("#!/bin/sh\nrm -rf /tmp/nope-spaced\n", encoding="utf-8")
    harvester = SourceHarvester(tmp_path / "library")

    result = harvester.harvest_path(source, metadata={"title": "Payload", "license": "private"})
    spaced_result = harvester.harvest_path(spaced_source, metadata={"title": "Payload spaced", "license": "private"})

    assert result.route == "rejected"
    assert result.stored_path is not None
    assert result.stored_path.parent == tmp_path / "library" / "rejected"
    assert spaced_result.route == "rejected"
    assert spaced_result.stored_path is not None
    assert spaced_result.stored_path.parent == tmp_path / "library" / "rejected"
    for dirname in HARVEST_DIRS:
        assert (tmp_path / "library" / dirname).is_dir()

    link = tmp_path / "link.txt"
    link.symlink_to(source)
    with pytest.raises(ValueError, match="refuses symlink"):
        harvester.harvest_path(link, metadata={"title": "Link", "license": "private"})
