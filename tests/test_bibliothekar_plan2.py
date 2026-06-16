from __future__ import annotations

from pathlib import Path

from TeeBotus.bibliothekar.cli import main as bibliothekar_cli_main


def test_plan2_bibliothekar_acceptance_dry_run_index_and_query(tmp_path, capsys) -> None:
    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    library_dir = instance_dir / "data" / "Bibliothek"
    source_dir = Path("tests/fixtures/books")
    library_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text("## Bibliothekar\n- backend: local\n", encoding="utf-8")

    assert (
        bibliothekar_cli_main(
            [
                "--instances-dir",
                str(instances_dir),
                "--instance",
                "Depressionsbot",
                "index",
                "--source",
                str(source_dir),
                "--dry-run",
            ]
        )
        == 0
    )
    dry_run_output = capsys.readouterr().out
    assert "dry_run=True" in dry_run_output
    assert "2 Dokumente" in dry_run_output

    assert (
        bibliothekar_cli_main(
            [
                "--instances-dir",
                str(instances_dir),
                "--instance",
                "Depressionsbot",
                "index",
                "--source",
                str(source_dir),
            ]
        )
        == 0
    )
    assert (
        bibliothekar_cli_main(
            [
                "--instances-dir",
                str(instances_dir),
                "--instance",
                "Depressionsbot",
                "query",
                "Schlafhygiene",
                "--top-k",
                "3",
            ]
        )
        == 0
    )
    query_output = capsys.readouterr().out
    assert "selected_library_chunks" in query_output
    assert "therapie_basis.md" in query_output
    assert "chunk_id" in query_output


def test_plan2_bibliothekar_query_source_is_non_mutating_fixture_mode(tmp_path, capsys) -> None:
    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    live_library_dir = instance_dir / "data" / "Bibliothek"
    live_library_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text("## Bibliothekar\n- backend: local\n", encoding="utf-8")

    assert (
        bibliothekar_cli_main(
            [
                "--instances-dir",
                str(instances_dir),
                "--instance",
                "Depressionsbot",
                "query",
                "--source",
                "tests/fixtures/books",
                "Schlafhygiene Tagesstruktur",
                "--top-k",
                "3",
            ]
        )
        == 0
    )

    query_output = capsys.readouterr().out
    assert "selected=2" in query_output
    assert "therapie_basis.md" in query_output
    assert "tagesstruktur.txt" in query_output
    assert list(live_library_dir.iterdir()) == []


def test_plan2_bibliothekar_source_import_does_not_copy_private_account_files(tmp_path, capsys) -> None:
    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    live_library_dir = instance_dir / "data" / "Bibliothek"
    source_dir = tmp_path / "source"
    private_dir = source_dir / "data" / "accounts" / ("a" * 128)
    live_library_dir.mkdir(parents=True)
    private_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text("## Bibliothekar\n- backend: local\n", encoding="utf-8")
    (source_dir / "therapie.txt").write_text("Depression Therapie Aktivierung.", encoding="utf-8")
    (source_dir / "cover.png").write_bytes(b"not a supported document")
    (private_dir / "User_Memory_Entries.jsonl").write_text(
        '{"id":"mem_private","user_text":"private memory must stay out"}\n',
        encoding="utf-8",
    )
    (private_dir / "User_Habbits_and_behave.md").write_text("private habits must stay out", encoding="utf-8")

    assert (
        bibliothekar_cli_main(
            [
                "--instances-dir",
                str(instances_dir),
                "--instance",
                "Depressionsbot",
                "index",
                "--source",
                str(source_dir),
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "1 Dokumente" in output
    assert (live_library_dir / "therapie.txt").exists()
    assert not (live_library_dir / "cover.png").exists()
    assert not (live_library_dir / "data" / "accounts").exists()
    assert not any(live_library_dir.rglob("User_Memory_Entries.jsonl"))
    assert not any(live_library_dir.rglob("User_Habbits_and_behave.md"))


def test_plan2_bibliothekar_source_import_does_not_follow_symlinks(tmp_path, capsys) -> None:
    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    live_library_dir = instance_dir / "data" / "Bibliothek"
    source_dir = tmp_path / "source"
    outside_secret = tmp_path / "outside-secret.txt"
    live_library_dir.mkdir(parents=True)
    source_dir.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text("## Bibliothekar\n- backend: local\n", encoding="utf-8")
    (source_dir / "therapie.txt").write_text("Depression Therapie Aktivierung.", encoding="utf-8")
    outside_secret.write_text("PRIVATE HOST SECRET MUST NOT BE COPIED", encoding="utf-8")
    (source_dir / "linked-secret.txt").symlink_to(outside_secret)

    assert (
        bibliothekar_cli_main(
            [
                "--instances-dir",
                str(instances_dir),
                "--instance",
                "Depressionsbot",
                "index",
                "--source",
                str(source_dir),
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "1 Dokumente" in output
    assert (live_library_dir / "therapie.txt").exists()
    assert not (live_library_dir / "linked-secret.txt").exists()
    assert "PRIVATE HOST SECRET" not in (live_library_dir / ".bibliothekar" / "chunks.jsonl").read_text(encoding="utf-8")


def test_plan2_bibliothekar_source_import_rejects_symlinked_source_root(tmp_path, capsys) -> None:
    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    live_library_dir = instance_dir / "data" / "Bibliothek"
    outside_source = tmp_path / "outside-source"
    linked_source = tmp_path / "linked-source"
    live_library_dir.mkdir(parents=True)
    outside_source.mkdir(parents=True)
    (instance_dir / "Bot_Verhalten.md").write_text("## Bibliothekar\n- backend: local\n", encoding="utf-8")
    (outside_source / "external.txt").write_text("External source must not be copied.", encoding="utf-8")
    linked_source.symlink_to(outside_source, target_is_directory=True)

    assert (
        bibliothekar_cli_main(
            [
                "--instances-dir",
                str(instances_dir),
                "--instance",
                "Depressionsbot",
                "index",
                "--source",
                str(linked_source),
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "0 Dokumente" in output
    assert not (live_library_dir / "external.txt").exists()
