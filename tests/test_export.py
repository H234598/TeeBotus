from __future__ import annotations

import builtins
import json
import sys
import types

import pytest

from TeeBotus.core.export import ExportError, export_account_data, export_account_data_from_store
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, telegram_identity_key

ACCOUNT_ID = "c" * 128


def make_account_dir(tmp_path):
    account_dir = tmp_path / ACCOUNT_ID
    account_dir.mkdir()
    (account_dir / "Account_Profile.json").write_text(json.dumps({"account_id": ACCOUNT_ID, "secret_verifier": "do-not-export"}), encoding="utf-8")
    (account_dir / "User_Memory_Index.json").write_text(json.dumps({"topic": "tea"}), encoding="utf-8")
    (account_dir / "User_Memory_Entries.jsonl").write_text('{"entry":"hello"}\n', encoding="utf-8")
    (account_dir / "Agent_State.json").write_text(json.dumps({"proactive": {"enabled": True}}), encoding="utf-8")
    (account_dir / "Proactive_Outbox.jsonl").write_text('{"message_text":"hello later"}\n', encoding="utf-8")
    (account_dir / "User_Habbits_and_behave.md").write_text("manual note", encoding="utf-8")
    return account_dir


def test_json_export_redacts_secret_verifier(tmp_path):
    account_dir = make_account_dir(tmp_path)
    result = export_account_data(ACCOUNT_ID, account_dir, "json")

    payload = json.loads(result.data.decode("utf-8"))
    assert payload["files"]["Account_Profile.json"]["secret_verifier"] == "<REDACTED>"
    assert b"do-not-export" not in result.data


def test_markdown_and_csv_exports(tmp_path):
    account_dir = make_account_dir(tmp_path)
    md = export_account_data(ACCOUNT_ID, account_dir, "md")
    csv = export_account_data(ACCOUNT_ID, account_dir, "cls")

    assert md.content_type == "text/markdown"
    assert b"manual note" not in md.data
    assert b"User_Habbits_and_behave" not in md.data
    assert csv.filename.endswith(".cls")
    assert b"User_Memory_Index.json" in csv.data


def test_pdf_degrades_to_markdown_without_engine(monkeypatch, tmp_path):
    original_import = builtins.__import__

    def import_without_weasyprint(name, *args, **kwargs):
        if name == "weasyprint":
            raise ImportError("blocked for test")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_weasyprint)
    account_dir = make_account_dir(tmp_path)
    result = export_account_data(ACCOUNT_ID, account_dir, "pdf")

    assert result.degraded is True
    assert result.filename.endswith(".md")
    assert b"TeeBotus Account Export" in result.data


def test_pdf_uses_weasyprint_when_available(monkeypatch, tmp_path):
    account_dir = make_account_dir(tmp_path)
    captured = {}

    class FakeHTML:
        def __init__(self, *, string):
            captured["html"] = string

        def write_pdf(self):
            return b"%PDF-1.7\nfake\n"

    monkeypatch.setitem(sys.modules, "weasyprint", types.SimpleNamespace(HTML=FakeHTML))

    result = export_account_data(ACCOUNT_ID, account_dir, "pdf")

    assert result.degraded is False
    assert result.filename.endswith(".pdf")
    assert result.content_type == "application/pdf"
    assert result.data.startswith(b"%PDF")
    assert "secret_verifier" in captured["html"]
    assert "do-not-export" not in captured["html"]


def test_pdf_falls_back_when_weasyprint_render_fails(monkeypatch, tmp_path):
    account_dir = make_account_dir(tmp_path)

    class BrokenHTML:
        def __init__(self, *, string):
            pass

        def write_pdf(self):
            raise RuntimeError("render failed")

    monkeypatch.setitem(sys.modules, "weasyprint", types.SimpleNamespace(HTML=BrokenHTML))

    result = export_account_data(ACCOUNT_ID, account_dir, "pdf")

    assert result.degraded is True
    assert result.filename.endswith(".md")
    assert result.content_type == "text/markdown"


def test_export_from_store_decrypts_structured_memory(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Bot", StaticSecretProvider(b"f" * 32))
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_memory_index(account_id, {"topic": "encrypted tea"})
    store.write_memory_entries(account_id, [{"entry": "encrypted hello"}])
    (store.account_dir(account_id) / "User_Habbits_and_behave.md").write_text("manual note", encoding="utf-8")

    raw = (store.account_dir(account_id) / "User_Memory_Index.json").read_text(encoding="utf-8")
    assert "encrypted tea" not in raw
    result = export_account_data_from_store(store, account_id, "json")
    payload = json.loads(result.data.decode("utf-8"))
    assert payload["files"]["User_Memory_Index.json"]["topic"] == "encrypted tea"
    assert payload["files"]["User_Memory_Entries.jsonl"] == [{"entry": "encrypted hello"}]
    assert payload["files"]["Agent_State.json"] == {}
    assert payload["files"]["Proactive_Outbox.jsonl"] == []
    assert payload["files"]["Proactive_Audit.jsonl"] == []
    assert "User_Habbits_and_behave.md" not in payload["files"]


def test_export_from_store_decrypts_proactive_agent_files(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Bot", StaticSecretProvider(b"f" * 32))
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_agent_state(account_id, {"proactive": {"enabled": True}})
    store.append_proactive_outbox_item(account_id, {"message_text": "Erinnerung spaeter", "category": "reminder"})
    store.append_proactive_audit_event(account_id, {"event_type": "llm_decision_rejected", "reason": "unsafe_message_text"})

    raw = (store.account_dir(account_id) / "Proactive_Outbox.jsonl").read_text(encoding="utf-8")
    assert "Erinnerung spaeter" not in raw
    raw_audit = (store.account_dir(account_id) / "Proactive_Audit.jsonl").read_text(encoding="utf-8")
    assert "unsafe_message_text" not in raw_audit
    result = export_account_data_from_store(store, account_id, "json")
    payload = json.loads(result.data.decode("utf-8"))

    assert payload["files"]["Agent_State.json"]["proactive"]["enabled"] is True
    assert payload["files"]["Proactive_Outbox.jsonl"][0]["message_text"] == "Erinnerung spaeter"
    assert payload["files"]["Proactive_Audit.jsonl"][0]["reason"] == "unsafe_message_text"


def test_raw_export_refuses_encrypted_account_files_without_vault(tmp_path):
    store = AccountStore(tmp_path / "accounts", "Bot", StaticSecretProvider(b"f" * 32))
    account_id = store.resolve_or_create_account(telegram_identity_key(1))
    store.write_memory_index(account_id, {"topic": "encrypted tea"})

    with pytest.raises(ExportError):
        export_account_data(account_id, store.account_dir(account_id), "json")


def test_raw_export_refuses_encrypted_payload_without_working_vault(tmp_path):
    from TeeBotus.core.export import ExportError
    import pytest

    account_dir = tmp_path / ACCOUNT_ID
    account_dir.mkdir()
    (account_dir / "User_Memory_Index.json").write_text('{"magic":"TMBMAP1","ciphertext":"abc"}\n', encoding="utf-8")

    with pytest.raises(ExportError):
        export_account_data(ACCOUNT_ID, account_dir, "json")


def test_export_refuses_to_emit_encrypted_envelope_when_vault_fails(tmp_path):
    import pytest
    from TeeBotus.core.export import ExportError, export_account_data

    account_id = "c" * 128
    account_dir = tmp_path / account_id
    account_dir.mkdir()
    (account_dir / "User_Memory_Index.json").write_text('{"magic":"TMBMEM1","version":1,"algorithm":"AES-256-GCM","nonce":"bad","ciphertext":"abc"}\n', encoding="utf-8")

    with pytest.raises(ExportError):
        export_account_data(account_id, account_dir, "json")


def test_export_redacts_broad_secret_like_keys(tmp_path):
    import json
    from TeeBotus.core.export import export_account_data

    account_id = "d" * 128
    account_dir = tmp_path / account_id
    account_dir.mkdir()
    (account_dir / "Account_Profile.json").write_text(json.dumps({"api_token": "hidden", "account_id": account_id}), encoding="utf-8")

    result = export_account_data(account_id, account_dir, "json")
    payload = json.loads(result.data.decode("utf-8"))

    assert payload["files"]["Account_Profile.json"]["api_token"] == "<REDACTED>"
    assert payload["files"]["Account_Profile.json"]["account_id"] == account_id
