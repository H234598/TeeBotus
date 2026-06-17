from __future__ import annotations

import sys
import types

import pytest

from TeeBotus.instructions import parse_instructions
from TeeBotus.core.status import mcp_tool_status_lines, redact_status_text
from TeeBotus.mcp_tools import MCPToolError, MCPToolPolicy, MCPToolRegistry, build_readonly_mcp_registry, resolve_mcp_tool_policies
from TeeBotus.mcp_tools.fastmcp_server import FASTMCP_READONLY_ALLOWLIST, build_fastmcp_server, fastmcp_available
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, signal_identity_key
from TeeBotus.runtime.bibliothekar import BibliothekarStore
from TeeBotus.runtime.bibliothekar_service import BibliothekarService, LocalBibliothekarBackend


def test_mcp_tool_config_is_parsed_as_flat_allowlist() -> None:
    instructions = parse_instructions(
        """
        ## MCP Tools
        - bibliothekar.search.enabled: true
        - bibliothekar.search.read_only: true
        - memory.search.enabled: false
        - codex.exec.enabled: true
        - shell.exec.enabled: true
        """
    )

    assert instructions.mcp_tools["bibliothekar.search"]["enabled"] is True
    assert instructions.mcp_tools["bibliothekar.search"]["read_only"] is True
    assert instructions.mcp_tools["memory.search"]["enabled"] is False
    assert instructions.mcp_tools["codex.exec"]["enabled"] is True
    assert instructions.mcp_tools["shell.exec"]["enabled"] is True


def test_mcp_policy_resolution_is_shared_and_keeps_hard_boundaries() -> None:
    policies = resolve_mcp_tool_policies(
        {
            "memory.search": {"enabled": True, "read_only": True, "private_chat_only": False},
            "codex.exec": {"enabled": True, "read_only": False, "requires_admin": False},
            "shell.exec": {"enabled": True, "read_only": True},
        }
    )

    assert policies["memory.search"].enabled is True
    assert policies["memory.search"].private_chat_only is True
    assert policies["codex.exec"].enabled is True
    assert policies["codex.exec"].read_only is False
    assert policies["codex.exec"].requires_admin is True
    assert policies["codex.exec"].requires_confirmation is True
    assert policies["codex.exec"].sandbox_required is True
    assert "shell.exec" not in policies


def test_mcp_status_separates_direct_allowlist_from_guarded_tools() -> None:
    lines = mcp_tool_status_lines(
        {
            "bibliothekar.search": {"enabled": True, "read_only": True},
            "export.account": {"enabled": True, "read_only": True},
        }
    )

    assert "- Read-only allowlist: bibliothekar.search, memory.search (private)" in lines
    assert "- Nur mit Schutz: export.account (private, confirm, admin)" in lines
    assert "export.account" not in next(line for line in lines if line.startswith("- Read-only allowlist:"))


def test_mcp_status_redacts_secret_like_unknown_tool_names() -> None:
    openai_key = "sk-" + "ignoredToolLeak123456"
    hf_key = "hf_" + "ignoredToolLeak123456"
    credential_url = "https://user:plain-password@example.invalid:8443/path"
    schemeless_credentials = "user:plain-password@example.invalid:8443"

    lines = mcp_tool_status_lines(
        {
            openai_key: {"enabled": True, "read_only": True},
            f"OPENAI_API_KEY={hf_key}": {"enabled": True, "read_only": True},
            credential_url: {"enabled": True, "read_only": True},
            schemeless_credentials: {"enabled": True, "read_only": True},
            "shell.exec": {"enabled": True, "read_only": True},
        }
    )

    joined = "\n".join(lines)
    assert openai_key not in joined
    assert hf_key not in joined
    assert "plain-password" not in joined
    assert "user:" not in joined
    assert "https://example.invalid:8443/path" in joined
    assert "example.invalid:8443" in joined
    assert "sk-<redacted>" in joined
    assert "openai_api_key=<redacted>" in joined
    assert "shell.exec" in joined


def test_status_redacts_colon_secret_assignments() -> None:
    text = redact_status_text("provider failed api_key: plain-secret access-token: plain-token password: hunter2")

    assert "plain-secret" not in text
    assert "plain-token" not in text
    assert "hunter2" not in text
    assert "api_key:<redacted>" in text
    assert "access-token:<redacted>" in text
    assert "password:<redacted>" in text


def test_readonly_mcp_registry_exposes_only_allowed_registered_tools(tmp_path) -> None:
    service = _bibliothekar_service(tmp_path)
    account_store, account_id = _account_store_with_memory(tmp_path)
    registry = build_readonly_mcp_registry(
        account_store=account_store,
        account_id=account_id,
        bibliothekar_service=service,
        tool_config={
            "bibliothekar.search": {"enabled": True, "read_only": True},
            "memory.search": {"enabled": True, "read_only": True},
            "codex.exec": {"enabled": True, "read_only": False},
            "shell.exec": {"enabled": True, "read_only": False},
        },
        private_chat=True,
    )

    assert registry.tool_names == ("bibliothekar.search", "memory.search")
    library = registry.call("bibliothekar.search", {"query": "Therapie", "top_k": 1})
    memory = registry.call("memory.search", {"query": "Mond"})

    assert library["read_only"] is True
    assert "therapie.txt" in library["prompt_text"]
    assert memory["read_only"] is True
    assert memory["selected_ids"] == ["mem_1"]
    entry = account_store.read_memory_entries_by_ids(account_id, ["mem_1"])[0]
    assert entry["access_count"] == 1
    assert entry["last_accessed_at"]
    with pytest.raises(MCPToolError, match="not read-only"):
        registry.call("codex.exec", {"command": "id"})
    with pytest.raises(MCPToolError, match="disabled"):
        registry.call("shell.exec", {"command": "id"})


def test_mcp_bibliothekar_search_applies_public_metadata_filters(tmp_path) -> None:
    service = _bibliothekar_service_with_documents(
        tmp_path,
        {
            "therapie.txt": "Depression Therapie Aktivierung Schlaf.",
            "technik.txt": "Python Software Daten System Algorithmus.",
        },
    )
    registry = build_readonly_mcp_registry(
        bibliothekar_service=service,
        tool_config={"bibliothekar.search": {"enabled": True, "read_only": True}},
    )

    result = registry.call(
        "bibliothekar.search",
        {
            "query": "System Therapie",
            "top_k": 3,
            "category": "technik",
            "topic": "python",
            "file": "technik",
            "extension": "txt",
            "account_id": "must-not-be-used",
        },
    )

    assert result["selected_ids"]
    assert "technik.txt" in result["prompt_text"]
    assert "therapie.txt" not in result["prompt_text"]
    assert "must-not-be-used" not in result["prompt_text"]


def test_mcp_known_future_tools_are_policy_visible_but_not_registered(tmp_path) -> None:
    registry = build_readonly_mcp_registry(
        bibliothekar_service=_bibliothekar_service(tmp_path),
        tool_config={
            "youtube.transcribe": {"enabled": True, "read_only": True},
            "export.account": {"enabled": True, "read_only": True},
        },
        private_chat=True,
    )

    assert registry.policy("youtube.transcribe").enabled is True
    assert registry.policy("export.account").requires_confirmation is True
    assert "youtube.transcribe" not in registry.tool_names
    assert "export.account" not in registry.tool_names
    with pytest.raises(MCPToolError, match="not registered"):
        registry.call("youtube.transcribe", {"query": "https://youtu.be/example"})


def test_mcp_registry_never_directly_calls_tools_that_require_extra_guards() -> None:
    registry = MCPToolRegistry(
        {
            "export.account": MCPToolPolicy(enabled=True, read_only=True, requires_confirmation=True, requires_admin=True),
            "codex.exec": MCPToolPolicy(enabled=True, read_only=True, sandbox_required=True),
        },
        {
            "export.account": lambda _arguments: {"export": "would leak account data"},
            "codex.exec": lambda _arguments: {"path": "/tmp/example"},
        },
    )

    assert registry.tool_names == ()
    with pytest.raises(MCPToolError, match="requires confirmation"):
        registry.call("export.account", {"query": "export"})
    with pytest.raises(MCPToolError, match="requires sandbox"):
        registry.call("codex.exec", {"query": "read"})


def test_mcp_registry_rejects_unknown_registered_tools() -> None:
    registry = MCPToolRegistry(
        {"shell.exec": MCPToolPolicy(enabled=True, read_only=True)},
        {"shell.exec": lambda _arguments: {"stdout": "would run"}},
    )

    assert registry.tool_names == ()
    assert registry.policy("shell.exec").enabled is False
    with pytest.raises(MCPToolError, match="disabled"):
        registry.call("shell.exec", {"command": "id"})


def test_mcp_memory_search_requires_explicit_private_chat_context(tmp_path) -> None:
    service = _bibliothekar_service(tmp_path)
    account_store, account_id = _account_store_with_memory(tmp_path)

    registry = build_readonly_mcp_registry(
        account_store=account_store,
        account_id=account_id,
        bibliothekar_service=service,
        tool_config={
            "bibliothekar.search": {"enabled": True, "read_only": True},
            "memory.search": {"enabled": True, "read_only": True, "private_chat_only": True},
        },
    )

    assert registry.tool_names == ("bibliothekar.search",)
    with pytest.raises(MCPToolError, match="not registered"):
        registry.call("memory.search", {"query": "Mond"})


def test_mcp_memory_search_private_chat_boundary_cannot_be_relaxed_by_config(tmp_path) -> None:
    account_store, account_id = _account_store_with_memory(tmp_path)
    registry = build_readonly_mcp_registry(
        account_store=account_store,
        account_id=account_id,
        tool_config={
            "memory.search": {"enabled": True, "read_only": True, "private_chat_only": False},
        },
        private_chat=False,
    )

    assert registry.policy("memory.search").private_chat_only is True
    assert "memory.search" not in registry.tool_names
    with pytest.raises(MCPToolError, match="not registered"):
        registry.call("memory.search", {"query": "Mond"})


def test_mcp_registry_rejects_non_readonly_policy(tmp_path) -> None:
    registry = build_readonly_mcp_registry(
        bibliothekar_service=_bibliothekar_service(tmp_path),
        tool_config={"bibliothekar.search": {"enabled": True, "read_only": False}},
    )

    assert "bibliothekar.search" not in registry.tool_names
    with pytest.raises(MCPToolError, match="not read-only"):
        registry.call("bibliothekar.search", {"query": "Therapie"})


def test_mcp_registry_rejects_secret_like_tool_results() -> None:
    tokens = [
        "hf_" + "A" * 16,
        "gsk_" + "B" * 16,
        "AIza" + "C" * 24,
        "github_" + "pat_" + "D" * 24,
        "gh" + "p_" + "E" * 16,
        "gl" + "pat-" + "F" * 16,
        "sy" + "t_" + "G" * 16,
        "xox" + "b-" + "H" * 16,
        "sk-" + "I" * 16,
    ]
    registry = MCPToolRegistry(
        {"bibliothekar.search": MCPToolPolicy(enabled=True, read_only=True)},
        {"bibliothekar.search": lambda _arguments: {"prompt_text": "Quelle " + tokens[0], "nested": {"tokens": tokens[1:]}}},
    )

    with pytest.raises(MCPToolError, match="secret-looking content"):
        registry.call("bibliothekar.search", {"query": "Token"})


def test_mcp_registry_rejects_secret_like_tool_result_keys() -> None:
    registry = MCPToolRegistry(
        {"bibliothekar.search": MCPToolPolicy(enabled=True, read_only=True)},
        {
            "bibliothekar.search": lambda _arguments: {
                "prompt_text": "harmloser Text",
                "nested": {"OPENAI_API_KEY": "configured", "access_token": "configured", "token": "configured"},
            }
        },
    )

    with pytest.raises(MCPToolError, match="secret-looking content"):
        registry.call("bibliothekar.search", {"query": "Token"})


def test_mcp_registry_rejects_camelcase_secret_like_tool_result_keys() -> None:
    registry = MCPToolRegistry(
        {"bibliothekar.search": MCPToolPolicy(enabled=True, read_only=True)},
        {
            "bibliothekar.search": lambda _arguments: {
                "prompt_text": "harmloser Text",
                "nested": {"apiKey": "configured", "accessToken": "configured", "bearerToken": "configured"},
            }
        },
    )

    with pytest.raises(MCPToolError, match="secret-looking content"):
        registry.call("bibliothekar.search", {"query": "Token"})


def test_mcp_registry_rejects_case_insensitive_secret_assignment_markers() -> None:
    registry = MCPToolRegistry(
        {"bibliothekar.search": MCPToolPolicy(enabled=True, read_only=True)},
        {"bibliothekar.search": lambda _arguments: {"prompt_text": "openai_api_key=configured"}},
    )

    with pytest.raises(MCPToolError, match="secret-looking content"):
        registry.call("bibliothekar.search", {"query": "Token"})


def test_mcp_registry_rejects_colon_secret_assignment_markers() -> None:
    registry = MCPToolRegistry(
        {"bibliothekar.search": MCPToolPolicy(enabled=True, read_only=True)},
        {
            "bibliothekar.search": lambda _arguments: {
                "prompt_text": "Index:\napi_key: plain-secret\npassword: hunter2",
                "summary": "access-token: plain-token",
            }
        },
    )

    with pytest.raises(MCPToolError, match="secret-looking content"):
        registry.call("bibliothekar.search", {"query": "Token"})


def test_mcp_registry_rejects_private_account_paths_in_tool_results() -> None:
    registry = MCPToolRegistry(
        {"bibliothekar.search": MCPToolPolicy(enabled=True, read_only=True)},
        {
            "bibliothekar.search": lambda _arguments: {
                "prompt_text": (
                    "Quelle verweist versehentlich auf "
                    "/home/teladi/TeeBotus/instances/Demo/data/accounts/account/User_Memory_Entries.jsonl"
                )
            }
        },
    )

    with pytest.raises(MCPToolError, match="secret-looking content"):
        registry.call("bibliothekar.search", {"query": "Memory"})


def test_mcp_registry_rejects_url_credentials_in_tool_results() -> None:
    registry = MCPToolRegistry(
        {"bibliothekar.search": MCPToolPolicy(enabled=True, read_only=True)},
        {
            "bibliothekar.search": lambda _arguments: {
                "prompt_text": "Quelle: https://user:plain-password@example.invalid/books/therapie.pdf",
                "target": "base_url=http://reader:secret@127.0.0.1:6333",
            }
        },
    )

    with pytest.raises(MCPToolError, match="secret-looking content"):
        registry.call("bibliothekar.search", {"query": "Quelle"})


def test_mcp_registry_allows_normal_readonly_result_keys() -> None:
    registry = MCPToolRegistry(
        {"bibliothekar.search": MCPToolPolicy(enabled=True, read_only=True)},
        {
            "bibliothekar.search": lambda _arguments: {
                "tool": "bibliothekar.search",
                "read_only": True,
                "selected_ids": ["chunk_1"],
                "file": "therapie.txt",
                "source_url": "https://example.invalid/books/therapie.pdf",
                "topics": ["therapie"],
            }
        },
    )

    assert registry.call("bibliothekar.search", {"query": "Therapie"})["selected_ids"] == ["chunk_1"]


def test_fastmcp_adapter_is_optional_and_registers_readonly_tools(tmp_path, monkeypatch) -> None:
    created = []

    class FakeFastMCP:
        def __init__(self, name):
            self.name = name
            self.tools = {}
            created.append(self)

        def tool(self, name):
            def decorator(func):
                self.tools[name] = func
                return func

            return decorator

    fake_module = types.ModuleType("fastmcp")
    fake_module.FastMCP = FakeFastMCP
    monkeypatch.setitem(sys.modules, "fastmcp", fake_module)
    account_store, account_id = _account_store_with_memory(tmp_path)
    registry = build_readonly_mcp_registry(
        account_store=account_store,
        account_id=account_id,
        bibliothekar_service=_bibliothekar_service(tmp_path),
        tool_config={
            "bibliothekar.search": {"enabled": True, "read_only": True},
            "memory.search": {"enabled": True, "read_only": True, "private_chat_only": True},
            "youtube.transcribe": {"enabled": True, "read_only": True},
            "export.account": {"enabled": True, "read_only": True},
            "codex.exec": {"enabled": True, "read_only": False},
            "shell.exec": {"enabled": True, "read_only": False},
        },
        private_chat=True,
    )

    server = build_fastmcp_server(registry)

    assert fastmcp_available() is True
    assert server is created[0]
    assert FASTMCP_READONLY_ALLOWLIST == ("bibliothekar.search", "memory.search")
    assert sorted(server.tools) == ["bibliothekar.search", "memory.search"]
    assert "therapie.txt" in server.tools["bibliothekar.search"]("Therapie", top_k=1)["prompt_text"]
    filtered_library = server.tools["bibliothekar.search"](
        "System Therapie",
        top_k=3,
        max_prompt_chars=5000,
        max_quote_chars=400,
        category="technik",
        keyword="python",
        relative_path="technik",
        extension="txt",
    )
    assert "technik.txt" in filtered_library["prompt_text"]
    assert "therapie.txt" not in filtered_library["prompt_text"]
    assert server.tools["memory.search"]("Mond")["selected_ids"] == ["mem_1"]
    assert "youtube.transcribe" not in server.tools
    assert "export.account" not in server.tools
    assert "codex.exec" not in server.tools
    assert "shell.exec" not in server.tools


def test_fastmcp_adapter_does_not_expose_private_memory_in_group_context(tmp_path, monkeypatch) -> None:
    class FakeFastMCP:
        def __init__(self, name):
            self.name = name
            self.tools = {}

        def tool(self, name):
            def decorator(func):
                self.tools[name] = func
                return func

            return decorator

    fake_module = types.ModuleType("fastmcp")
    fake_module.FastMCP = FakeFastMCP
    monkeypatch.setitem(sys.modules, "fastmcp", fake_module)
    account_store, account_id = _account_store_with_memory(tmp_path)
    registry = build_readonly_mcp_registry(
        account_store=account_store,
        account_id=account_id,
        bibliothekar_service=_bibliothekar_service(tmp_path),
        tool_config={
            "bibliothekar.search": {"enabled": True, "read_only": True},
            "memory.search": {"enabled": True, "read_only": True, "private_chat_only": True},
        },
        private_chat=False,
    )

    server = build_fastmcp_server(registry)

    assert sorted(server.tools) == ["bibliothekar.search"]
    assert "memory.search" not in server.tools


def test_fastmcp_adapter_does_not_expose_non_readonly_allowlisted_tools(tmp_path, monkeypatch) -> None:
    class FakeFastMCP:
        def __init__(self, name):
            self.name = name
            self.tools = {}

        def tool(self, name):
            def decorator(func):
                self.tools[name] = func
                return func

            return decorator

    fake_module = types.ModuleType("fastmcp")
    fake_module.FastMCP = FakeFastMCP
    monkeypatch.setitem(sys.modules, "fastmcp", fake_module)
    account_store, account_id = _account_store_with_memory(tmp_path)
    registry = build_readonly_mcp_registry(
        account_store=account_store,
        account_id=account_id,
        bibliothekar_service=_bibliothekar_service(tmp_path),
        tool_config={
            "bibliothekar.search": {"enabled": True, "read_only": False},
            "memory.search": {"enabled": True, "read_only": False, "private_chat_only": True},
        },
        private_chat=True,
    )

    server = build_fastmcp_server(registry)

    assert registry.tool_names == ()
    assert server.tools == {}


def _bibliothekar_service(tmp_path) -> BibliothekarService:
    return _bibliothekar_service_with_documents(
        tmp_path,
        {
            "therapie.txt": "Depression Therapie Aktivierung Schlaf.",
            "technik.txt": "Python Software Daten System Algorithmus.",
        },
    )


def _bibliothekar_service_with_documents(tmp_path, documents: dict[str, str]) -> BibliothekarService:
    library_dir = tmp_path / "instances" / "Depressionsbot" / "data" / "Bibliothek"
    library_dir.mkdir(parents=True, exist_ok=True)
    for relative_path, text in documents.items():
        target = library_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    store = BibliothekarStore("Depressionsbot", tmp_path / "instances")
    store.rebuild()
    return BibliothekarService(LocalBibliothekarBackend(store))


def _account_store_with_memory(tmp_path) -> tuple[AccountStore, str]:
    store = AccountStore(tmp_path / "accounts", "Depressionsbot", StaticSecretProvider(b"m" * 32))
    account_id = store.resolve_or_create_account(signal_identity_key(source_uuid="mcp-user"))
    store.append_structured_memory_entry(
        account_id,
        {
            "id": "mem_1",
            "kind": "observation",
            "memory_type": "episodic",
            "user_text": "Der User erwaehnte den Mond.",
            "keywords": ["mond"],
        },
    )
    return store, account_id
