from __future__ import annotations

import json

from TeeBotus.runtime.working_memory import WorkingMemoryStore


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_working_memory_files_are_instance_scoped_and_sanitize_manual_entries(tmp_path):
    instances_dir = tmp_path / "instances"
    store = WorkingMemoryStore("Depressionsbot", instances_dir)

    index_path = store.ensure()
    memory_id = store.append_manual(
        "Allgemeine Regel: kurze Antworten. Kontakt @ada, ada@example.com, https://example.com/user/456 und 123456789."
    )

    payload = json.loads(index_path.read_text(encoding="utf-8"))
    entries = _read_jsonl(instances_dir / "Depressionsbot" / "data" / "Working_Memorys.entries.jsonl")
    entry_text = entries[0]["text"]
    assert index_path == instances_dir / "Depressionsbot" / "data" / "Working_Memorys.json"
    assert memory_id.startswith("wm_")
    assert payload["scope"] == "instance"
    assert "sender_id" not in payload
    assert "profile" not in payload
    assert memory_id in payload["index"]["entries"]
    assert "@ada" not in entry_text
    assert "ada@example.com" not in entry_text
    assert "https://example.com" not in entry_text
    assert "123456789" not in entry_text


def test_working_memory_corrupt_index_is_preserved_without_traceback_log(tmp_path, caplog):
    instances_dir = tmp_path / "instances"
    index_path = instances_dir / "Depressionsbot" / "data" / "Working_Memorys.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text("", encoding="utf-8")
    store = WorkingMemoryStore("Depressionsbot", instances_dir)

    with caplog.at_level("WARNING", logger="TeeBotus"):
        store.ensure()

    assert any("Resetting invalid instance working memory" in record.message for record in caplog.records)
    assert not any("Traceback" in record.message for record in caplog.records)
    backups = list(index_path.parent.glob("Working_Memorys.json.corrupt.*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == ""
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    assert payload["scope"] == "instance"


def test_working_memory_prepare_selects_relevant_entry(tmp_path):
    instances_dir = tmp_path / "instances"
    store = WorkingMemoryStore("Depressionsbot", instances_dir)
    relevant = store.append_manual("Architekturfragen zuerst kurz strukturieren.")
    store.append_manual("Katzenbilder nur mit Quellenhinweis.")

    record = store.prepare("Bitte eine Architekturfrage strukturieren.")

    assert relevant in record.selected_ids
    assert "Architekturfragen" in record.prompt_text
    assert "selected_working_memory_ids" in record.prompt_text
