from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from unittest.mock import patch

import pytest

from TeeBotus.adapters.telegram_runtime import WorkingMemoryStore as TelegramWorkingMemoryStore
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


@pytest.mark.parametrize("store_class", (WorkingMemoryStore, TelegramWorkingMemoryStore))
def test_working_memory_repairs_stale_instance_name(tmp_path, store_class):
    instances_dir = tmp_path / "instances"
    index_path = instances_dir / "Depressionsbot" / "data" / "Working_Memorys.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(
        json.dumps({"instance_name": "OldInstance", "scope": "instance", "index": {}}),
        encoding="utf-8",
    )

    store = store_class("Depressionsbot", instances_dir)
    store.ensure()

    payload = json.loads(index_path.read_text(encoding="utf-8"))
    assert payload["instance_name"] == "Depressionsbot"


@pytest.mark.parametrize("store_class", (WorkingMemoryStore, TelegramWorkingMemoryStore))
def test_working_memory_ignores_invalid_utf8_entry(tmp_path, store_class):
    instances_dir = tmp_path / "instances"
    store = store_class("Depressionsbot", instances_dir)
    memory_id = store.append_manual("Ein korrekter Eintrag")
    index_path = store.ensure()
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    entry_length = payload["index"]["entries"][memory_id]["length"]
    entries_path = index_path.parent / "Working_Memorys.entries.jsonl"
    entries_path.write_bytes(b"\xff" * entry_length)

    record = store.prepare("korrekter Eintrag")

    assert record.prompt_text == ""
    assert record.selected_ids == ()


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


@pytest.mark.parametrize("store_class", (WorkingMemoryStore, TelegramWorkingMemoryStore))
def test_working_memory_prepare_persists_corrupt_index_repair(tmp_path, store_class):
    instances_dir = tmp_path / "instances"
    index_path = instances_dir / "Depressionsbot" / "data" / "Working_Memorys.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text("not json", encoding="utf-8")
    store = store_class("Depressionsbot", instances_dir)

    record = store.prepare("irrelevant")

    assert record.prompt_text == ""
    assert record.selected_ids == ()
    assert json.loads(index_path.read_text(encoding="utf-8"))["scope"] == "instance"
    assert len(list(index_path.parent.glob("Working_Memorys.json.corrupt.*"))) == 1


@pytest.mark.parametrize("store_class", (WorkingMemoryStore, TelegramWorkingMemoryStore))
def test_working_memory_prepare_rebuilds_entries_after_index_corruption(tmp_path, store_class):
    instances_dir = tmp_path / "instances"
    store = store_class("Depressionsbot", instances_dir)
    memory_id = store.append_manual("Architekturfragen zuerst strukturieren.")
    index_path = store.ensure()
    index_path.write_text("not json", encoding="utf-8")

    record = store.prepare("Architekturfragen")

    assert record.selected_ids == (memory_id,)
    assert "Architekturfragen" in record.prompt_text
    rebuilt = json.loads(index_path.read_text(encoding="utf-8"))
    assert rebuilt["index"]["entries"][memory_id]["offset"] == 0


@pytest.mark.parametrize("store_class", (WorkingMemoryStore, TelegramWorkingMemoryStore))
def test_working_memory_prepare_persists_metadata_normalization(tmp_path, store_class):
    instances_dir = tmp_path / "instances"
    index_path = instances_dir / "Depressionsbot" / "data" / "Working_Memorys.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(
        json.dumps(
            {
                "instance_name": "OldInstance",
                "scope": "instance",
                "sender_id": "must be removed",
                "index": {"keywords": {}, "recent_ids": [], "entries": {}},
            }
        ),
        encoding="utf-8",
    )
    store = store_class("Depressionsbot", instances_dir)

    store.prepare("irrelevant")

    payload = json.loads(index_path.read_text(encoding="utf-8"))
    assert payload["instance_name"] == "Depressionsbot"
    assert "sender_id" not in payload


@pytest.mark.parametrize("store_class", (WorkingMemoryStore, TelegramWorkingMemoryStore))
def test_working_memory_prepare_rebuilds_nested_malformed_index(tmp_path, store_class):
    instances_dir = tmp_path / "instances"
    store = store_class("Depressionsbot", instances_dir)
    memory_id = store.append_manual("Architekturfragen zuerst strukturieren.")
    index_path = store.ensure()
    index_path.write_text(
        json.dumps(
            {
                "scope": "instance",
                "index": {
                    "keywords": {"architekturfragen": memory_id},
                    "recent_ids": [memory_id],
                    "entries": {},
                },
            }
        ),
        encoding="utf-8",
    )

    record = store.prepare("Architekturfragen")

    assert record.selected_ids == (memory_id,)
    assert "Architekturfragen" in record.prompt_text
    assert len(list(index_path.parent.glob("Working_Memorys.json.corrupt.*"))) == 1


@pytest.mark.parametrize("store_class", (WorkingMemoryStore, TelegramWorkingMemoryStore))
def test_working_memory_invalid_utf8_index_is_preserved(tmp_path, caplog, store_class):
    instances_dir = tmp_path / "instances"
    index_path = instances_dir / "Depressionsbot" / "data" / "Working_Memorys.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_bytes(b"\xff\xfe")
    store = store_class("Depressionsbot", instances_dir)

    with caplog.at_level("WARNING", logger="TeeBotus"):
        store.ensure()

    backups = list(index_path.parent.glob("Working_Memorys.json.corrupt.*"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"\xff\xfe"
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    assert payload["scope"] == "instance"


@pytest.mark.parametrize("store_class", (WorkingMemoryStore, TelegramWorkingMemoryStore))
def test_working_memory_non_object_index_is_preserved(tmp_path, caplog, store_class):
    instances_dir = tmp_path / "instances"
    index_path = instances_dir / "Depressionsbot" / "data" / "Working_Memorys.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(json.dumps(["not", "an", "index"]), encoding="utf-8")
    store = store_class("Depressionsbot", instances_dir)

    with caplog.at_level("WARNING", logger="TeeBotus"):
        store.ensure()

    backups = list(index_path.parent.glob("Working_Memorys.json.corrupt.*"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8")) == ["not", "an", "index"]
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    assert payload["scope"] == "instance"
    assert any("expected JSON object" in record.message for record in caplog.records)


@pytest.mark.parametrize(
    "invalid_index",
    (
        [],
        {"keywords": []},
        {"recent_ids": {}},
        {"entries": []},
    ),
)
@pytest.mark.parametrize("store_class", (WorkingMemoryStore, TelegramWorkingMemoryStore))
def test_working_memory_invalid_index_structure_is_preserved(tmp_path, caplog, invalid_index, store_class):
    instances_dir = tmp_path / "instances"
    index_path = instances_dir / "Depressionsbot" / "data" / "Working_Memorys.json"
    index_path.parent.mkdir(parents=True)
    original = {"scope": "instance", "index": invalid_index}
    index_path.write_text(json.dumps(original), encoding="utf-8")
    store = store_class("Depressionsbot", instances_dir)

    with caplog.at_level("WARNING", logger="TeeBotus"):
        store.ensure()

    backups = list(index_path.parent.glob("Working_Memorys.json.corrupt.*"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8")) == original
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    assert payload["index"]["entries"] == {}
    assert any("invalid index structure" in record.message for record in caplog.records)


@pytest.mark.parametrize(
    ("store_class", "module_name"),
    (
        (WorkingMemoryStore, "TeeBotus.runtime.working_memory"),
        (TelegramWorkingMemoryStore, "TeeBotus.adapters.telegram_runtime"),
    ),
)
def test_working_memory_append_rolls_back_entry_when_index_write_fails(tmp_path, store_class, module_name):
    instances_dir = tmp_path / "instances"
    store = store_class("Depressionsbot", instances_dir)
    index_path = store.ensure()
    entries_path = index_path.parent / "Working_Memorys.entries.jsonl"
    original_index = index_path.read_bytes()

    with patch.object(import_module(module_name), "_write_json_file", side_effect=OSError("replace failed")):
        with pytest.raises(OSError, match="replace failed"):
            store.append_manual("Nicht dauerhaft speichern")

    assert index_path.read_bytes() == original_index
    assert entries_path.read_bytes() == b""


@pytest.mark.parametrize("store_class", (WorkingMemoryStore, TelegramWorkingMemoryStore))
def test_working_memory_store_instances_share_path_lock(tmp_path, store_class):
    instances_dir = tmp_path / "instances"
    stores = (
        store_class("Depressionsbot", instances_dir),
        store_class("Depressionsbot", instances_dir),
    )
    index_path = stores[0].ensure()

    def append(number):
        return stores[number % 2].append_manual(f"Parallel entry {number}")

    with ThreadPoolExecutor(max_workers=8) as executor:
        memory_ids = list(executor.map(append, range(40)))

    payload = json.loads(index_path.read_text(encoding="utf-8"))
    entries = _read_jsonl(index_path.parent / "Working_Memorys.entries.jsonl")
    assert len(memory_ids) == 40
    assert len(set(memory_ids)) == 40
    assert len(payload["index"]["entries"]) == 40
    assert len(entries) == 40


@pytest.mark.parametrize("store_class", (WorkingMemoryStore, TelegramWorkingMemoryStore))
def test_working_memory_store_instances_share_symlinked_path_lock(tmp_path, store_class):
    instances_dir = tmp_path / "instances"
    instances_alias = tmp_path / "instances-alias"
    instances_dir.mkdir()
    instances_alias.symlink_to(instances_dir, target_is_directory=True)
    stores = (
        store_class("Depressionsbot", instances_dir),
        store_class("Depressionsbot", instances_alias),
    )
    index_path = stores[0].ensure()

    def append(number):
        return stores[number % 2].append_manual(f"Symlink entry {number}")

    with ThreadPoolExecutor(max_workers=8) as executor:
        memory_ids = list(executor.map(append, range(40)))

    payload = json.loads(index_path.read_text(encoding="utf-8"))
    entries = _read_jsonl(index_path.parent / "Working_Memorys.entries.jsonl")
    assert len(set(memory_ids)) == 40
    assert len(payload["index"]["entries"]) == 40
    assert len(entries) == 40


def test_working_memory_unreadable_index_is_not_replaced(tmp_path, caplog):
    instances_dir = tmp_path / "instances"
    store = WorkingMemoryStore("Depressionsbot", instances_dir)
    index_path = store.ensure()
    original = index_path.read_bytes()

    with patch("TeeBotus.runtime.working_memory.Path.read_text", side_effect=OSError("permission denied")):
        with caplog.at_level("WARNING", logger="TeeBotus"):
            assert store.ensure() == index_path

    assert index_path.read_bytes() == original
    assert any("existing data preserved" in record.message for record in caplog.records)


def test_working_memory_atomic_write_preserves_index_on_replace_error(tmp_path, caplog):
    instances_dir = tmp_path / "instances"
    store = WorkingMemoryStore("Depressionsbot", instances_dir)
    index_path = store.ensure()
    original = index_path.read_bytes()

    with patch("TeeBotus.runtime.working_memory.os.replace", side_effect=OSError("replace failed")):
        with caplog.at_level("WARNING", logger="TeeBotus"):
            assert store.ensure() == index_path

    assert index_path.read_bytes() == original
    assert not list(index_path.parent.glob(".Working_Memorys.json.*.tmp"))


def test_working_memory_prepare_selects_relevant_entry(tmp_path):
    instances_dir = tmp_path / "instances"
    store = WorkingMemoryStore("Depressionsbot", instances_dir)
    relevant = store.append_manual("Architekturfragen zuerst kurz strukturieren.")
    store.append_manual("Katzenbilder nur mit Quellenhinweis.")

    record = store.prepare("Bitte eine Architekturfrage strukturieren.")

    assert relevant in record.selected_ids
    assert "Architekturfragen" in record.prompt_text
    assert "selected_working_memory_ids" in record.prompt_text


@pytest.mark.parametrize("store_class", (WorkingMemoryStore, TelegramWorkingMemoryStore))
def test_working_memory_appends_recent_entries_after_keyword_matches(tmp_path, store_class):
    instances_dir = tmp_path / "instances"
    store = store_class("Depressionsbot", instances_dir)
    relevant = store.append_manual("Architekturfragen zuerst kurz strukturieren.")
    recent = store.append_manual("Katzenbilder nur mit Quellenhinweis.")

    record = store.prepare("Bitte eine Architekturfrage strukturieren.")

    assert record.selected_ids[:2] == (relevant, recent)
    assert record.prompt_text.index(relevant) < record.prompt_text.index(recent)
