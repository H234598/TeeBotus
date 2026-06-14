from __future__ import annotations

import json

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


def test_pdf_degrades_to_markdown_without_engine(tmp_path):
    account_dir = make_account_dir(tmp_path)
    result = export_account_data(ACCOUNT_ID, account_dir, "pdf")

    assert result.degraded is True
    assert result.filename.endswith(".md")
    assert b"TeeBotus Account Export" in result.data


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
    assert "User_Habbits_and_behave.md" not in payload["files"]


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
