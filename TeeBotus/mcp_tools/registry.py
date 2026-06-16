from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from TeeBotus.runtime.accounts import AccountStore
from TeeBotus.runtime.bibliothekar_service import BibliothekarService


class MCPToolError(RuntimeError):
    pass


@dataclass(frozen=True)
class MCPToolPolicy:
    enabled: bool = False
    read_only: bool = True
    requires_confirmation: bool = False
    private_chat_only: bool = False
    requires_admin: bool = False
    sandbox_required: bool = False


DEFAULT_MCP_TOOL_POLICIES: dict[str, MCPToolPolicy] = {
    "bibliothekar.search": MCPToolPolicy(enabled=True, read_only=True),
    "memory.search": MCPToolPolicy(enabled=True, read_only=True, private_chat_only=True),
    "youtube.transcribe": MCPToolPolicy(enabled=False, read_only=True, private_chat_only=True),
    "export.account": MCPToolPolicy(enabled=False, read_only=True, requires_confirmation=True, private_chat_only=True, requires_admin=True),
    "codex.exec": MCPToolPolicy(enabled=False, read_only=False, requires_confirmation=True, requires_admin=True, sandbox_required=True),
}

ToolCallable = Callable[[Mapping[str, Any]], dict[str, Any]]


class MCPToolRegistry:
    def __init__(self, policies: Mapping[str, MCPToolPolicy], tools: Mapping[str, ToolCallable]) -> None:
        self._policies = {str(name).casefold(): policy for name, policy in policies.items()}
        self._tools = {str(name).casefold(): tool for name, tool in tools.items()}

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(sorted(name for name, policy in self._policies.items() if policy.enabled and policy.read_only and name in self._tools))

    def policy(self, name: str) -> MCPToolPolicy:
        key = str(name or "").strip().casefold()
        return self._policies.get(key, MCPToolPolicy(enabled=False))

    def call(self, name: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        key = str(name or "").strip().casefold()
        policy = self.policy(key)
        if not policy.enabled:
            raise MCPToolError(f"MCP tool is disabled: {key or '<empty>'}")
        if not policy.read_only:
            raise MCPToolError(f"MCP tool is not read-only: {key}")
        tool = self._tools.get(key)
        if tool is None:
            raise MCPToolError(f"MCP tool is not registered: {key}")
        result = tool(dict(arguments or {}))
        return _safe_result(result)


def build_readonly_mcp_registry(
    *,
    account_store: AccountStore | None = None,
    account_id: str = "",
    bibliothekar_service: BibliothekarService | None = None,
    tool_config: Mapping[str, Mapping[str, Any]] | None = None,
    private_chat: bool = False,
) -> MCPToolRegistry:
    policies = _merge_tool_policies(DEFAULT_MCP_TOOL_POLICIES, tool_config or {})
    tools: dict[str, ToolCallable] = {}
    if bibliothekar_service is not None:
        tools["bibliothekar.search"] = lambda arguments: _bibliothekar_search_tool(bibliothekar_service, arguments)
    memory_policy = policies.get("memory.search", DEFAULT_MCP_TOOL_POLICIES["memory.search"])
    # Account memory is user-private data. Keep this boundary hard even if a
    # future instruction file tries to relax memory.search.private_chat_only.
    if account_store is not None and str(account_id or "").strip() and private_chat and memory_policy.private_chat_only:
        tools["memory.search"] = lambda arguments: _memory_search_tool(account_store, account_id, arguments)
    return MCPToolRegistry(policies, tools)


def _merge_tool_policies(defaults: Mapping[str, MCPToolPolicy], overrides: Mapping[str, Mapping[str, Any]]) -> dict[str, MCPToolPolicy]:
    merged = dict(defaults)
    for raw_name, raw_config in overrides.items():
        name = str(raw_name or "").strip().casefold()
        if name not in defaults:
            continue
        config = raw_config if isinstance(raw_config, Mapping) else {}
        base = defaults[name]
        merged[name] = MCPToolPolicy(
            enabled=_bool_config(config.get("enabled"), base.enabled),
            read_only=_bool_config(config.get("read_only"), base.read_only),
            requires_confirmation=_bool_config(config.get("requires_confirmation"), base.requires_confirmation),
            private_chat_only=True if base.private_chat_only else _bool_config(config.get("private_chat_only"), base.private_chat_only),
            requires_admin=_bool_config(config.get("requires_admin"), base.requires_admin),
            sandbox_required=_bool_config(config.get("sandbox_required"), base.sandbox_required),
        )
    return merged


def _bibliothekar_search_tool(service: BibliothekarService, arguments: Mapping[str, Any]) -> dict[str, Any]:
    query = _required_query(arguments)
    selection = service.search(
        query,
        max_prompt_chars=_bounded_int(arguments.get("max_prompt_chars"), default=5000, lower=200, upper=12000),
        max_chunks=_bounded_int(arguments.get("max_chunks") or arguments.get("top_k"), default=5, lower=1, upper=12),
        max_quote_chars=_bounded_int(arguments.get("max_quote_chars"), default=900, lower=120, upper=2000),
    )
    return {
        "tool": "bibliothekar.search",
        "read_only": True,
        "selected_ids": list(selection.selected_ids),
        "prompt_text": selection.prompt_text,
    }


def _memory_search_tool(account_store: AccountStore, account_id: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    query = _required_query(arguments)
    selection = account_store.select_structured_memory(
        account_id,
        query_text=query,
        max_prompt_chars=_bounded_int(arguments.get("max_prompt_chars"), default=6000, lower=200, upper=12000),
        max_entry_chars=_bounded_int(arguments.get("max_entry_chars"), default=1200, lower=120, upper=4000),
    )
    return {
        "tool": "memory.search",
        "read_only": True,
        "selected_ids": list(selection.selected_ids),
        "prompt_text": selection.prompt_text,
    }


def _required_query(arguments: Mapping[str, Any]) -> str:
    query = str(arguments.get("query") or arguments.get("text") or "").strip()
    if not query:
        raise MCPToolError("MCP read-only search tools require a non-empty query")
    return query


def _bounded_int(value: object, *, default: int, lower: int, upper: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, lower), upper)


def _bool_config(value: object, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().casefold() in {"1", "true", "yes", "on", "enabled", "ja", "an"}


def _safe_result(value: Mapping[str, Any]) -> dict[str, Any]:
    result = {str(key): item for key, item in value.items()}
    text = str(result.get("prompt_text") or "")
    # Defense-in-depth: search tools should never return common secret-looking
    # environment assignments even if a caller accidentally indexed them.
    forbidden_markers = ("OPENAI_API_KEY=", "TEEBOTUS_LLM_API_KEY=", "SIGNAL_BOT_PHONE_NUMBER=", "MATRIX_BOT_ACCESS_TOKEN=")
    if any(marker in text for marker in forbidden_markers):
        raise MCPToolError("MCP tool result contained secret-looking content")
    return result
