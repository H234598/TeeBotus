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
