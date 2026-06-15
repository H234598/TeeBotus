from __future__ import annotations

from TeeBotus.bibliothekar.cli import main as bibliothekar_cli_main


def test_plan2_bibliothekar_acceptance_dry_run_index_and_query(tmp_path, capsys) -> None:
    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    library_dir = instance_dir / "data" / "Bibliothek"
    source_dir = tmp_path / "books"
    library_dir.mkdir(parents=True)
    source_dir.mkdir()
    (instance_dir / "Bot_Verhalten.md").write_text("## Bibliothekar\n- backend: local\n", encoding="utf-8")
    (source_dir / "therapie.md").write_text("# Therapie\nAktivierung und Schlafhygiene helfen strukturiert.\n", encoding="utf-8")

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
    assert "1 Dokumente" in dry_run_output

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
    assert "therapie.md" in query_output
    assert "chunk_id" in query_output
