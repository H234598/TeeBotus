from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from TeeBotus.runtime.accounts import AccountStore
from TeeBotus.runtime.bibliothekar_service import BibliothekarService

SECRET_LIKE_PATTERNS = (
    "OPENAI_API_KEY=",
    "TEEBOTUS_LLM_API_KEY=",
    "SIGNAL_BOT_PHONE_NUMBER=",
    "MATRIX_BOT_ACCESS_TOKEN=",
)
SECRET_LIKE_KEY_PATTERN = re.compile(
    r"(^|[_-])(api[_-]?key|access[_-]?token|auth[_-]?token|bearer[_-]?token|token|secret|password)([_-]|$)"
    r"|(?:apiKey|accessToken|authToken|bearerToken|secretToken|password)",
    re.IGNORECASE,
)
SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"\b[A-Za-z0-9_.-]*(?:api[_-]?key|access[_-]?token|auth[_-]?token|bearer[_-]?token|token|secret|password)"
    r"[A-Za-z0-9_.-]*\s*[:=]\s*[^\s,;)\]}]+",
    re.IGNORECASE,
)
SECRET_TOKEN_PATTERNS = (
    r"\bsk-[A-Za-z0-9_-]{8,}\b",
    r"\bxox[baprs]-[A-Za-z0-9_-]{8,}\b",
    r"\bsyt_[A-Za-z0-9_=-]{8,}\b",
    r"\bgh[pousr]_[A-Za-z0-9_]{8,}\b",
    r"\bgithub_pat_[A-Za-z0-9_]{12,}\b",
    r"\bglpat-[A-Za-z0-9_-]{8,}\b",
    r"\bhf_[A-Za-z0-9]{8,}\b",
    r"\bgsk_[A-Za-z0-9]{8,}\b",
    r"\bAIza[0-9A-Za-z_-]{16,}\b",
)
URL_CREDENTIAL_PATTERN = re.compile(r"(?:[a-z][a-z0-9+.-]*://|(?:target|base_url|url)=)[^\s/@:=]+:[^\s/@]+@", re.IGNORECASE)
PRIVATE_DATA_PATH_PATTERN = re.compile(
    r"(?:^|[/\\])(?:"
    r"account_(?:identities|index|memory|profile|secrets|tombstone)\.json|"
    r"secret_verifier\.json|"
    r"openai_state\.json|"
    r"agent_state\.json|"
    r"proactive_(?:audit|outbox)\.jsonl|"
    r"user_habbits_and_behave\.md|"
    r"user_memory_(?:entries\.jsonl|index\.json)|"
    r"legacy_user_memory_entries\.jsonl"
    r")(?:$|[\s,;)\]}])",
    re.IGNORECASE,
)
PRIVATE_DATA_PATH_SEGMENT_PATTERN = re.compile(r"(?:^|[/\\])data[/\\](?:accounts|users)(?:[/\\]|$)", re.IGNORECASE)


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
        known = {str(name).casefold() for name in DEFAULT_MCP_TOOL_POLICIES}
        self._policies = {str(name).casefold(): policy for name, policy in policies.items() if str(name).casefold() in known}
        self._tools = {str(name).casefold(): tool for name, tool in tools.items() if str(name).casefold() in known}

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(sorted(name for name, policy in self._policies.items() if _policy_is_directly_callable(policy) and name in self._tools))

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
        if policy.requires_confirmation:
            raise MCPToolError(f"MCP tool requires confirmation: {key}")
        if policy.requires_admin:
            raise MCPToolError(f"MCP tool requires admin context: {key}")
        if policy.sandbox_required:
            raise MCPToolError(f"MCP tool requires sandbox: {key}")
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
    policies = resolve_mcp_tool_policies(tool_config or {})
    tools: dict[str, ToolCallable] = {}
    if bibliothekar_service is not None:
        tools["bibliothekar.search"] = lambda arguments: _bibliothekar_search_tool(bibliothekar_service, arguments)
    memory_policy = policies.get("memory.search", DEFAULT_MCP_TOOL_POLICIES["memory.search"])
    # Account memory is user-private data. Keep this boundary hard even if a
    # future instruction file tries to relax memory.search.private_chat_only.
    if account_store is not None and str(account_id or "").strip() and private_chat and memory_policy.private_chat_only:
        tools["memory.search"] = lambda arguments: _memory_search_tool(account_store, account_id, arguments)
    return MCPToolRegistry(policies, tools)


def resolve_mcp_tool_policies(
    overrides: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    defaults: Mapping[str, MCPToolPolicy] = DEFAULT_MCP_TOOL_POLICIES,
) -> dict[str, MCPToolPolicy]:
    merged = dict(defaults)
    for raw_name, raw_config in (overrides or {}).items():
        name = str(raw_name or "").strip().casefold()
        if name not in defaults:
            continue
        config = raw_config if isinstance(raw_config, Mapping) else {}
        base = defaults[name]
        merged[name] = MCPToolPolicy(
            enabled=_bool_config(config.get("enabled"), base.enabled),
            read_only=False if not base.read_only else _bool_config(config.get("read_only"), base.read_only),
            requires_confirmation=True if base.requires_confirmation else _bool_config(config.get("requires_confirmation"), base.requires_confirmation),
            private_chat_only=True if base.private_chat_only else _bool_config(config.get("private_chat_only"), base.private_chat_only),
            requires_admin=True if base.requires_admin else _bool_config(config.get("requires_admin"), base.requires_admin),
            sandbox_required=True if base.sandbox_required else _bool_config(config.get("sandbox_required"), base.sandbox_required),
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


def _policy_is_directly_callable(policy: MCPToolPolicy) -> bool:
    return policy.enabled and policy.read_only and not policy.requires_confirmation and not policy.requires_admin and not policy.sandbox_required


def _safe_result(value: Mapping[str, Any]) -> dict[str, Any]:
    result = {str(key): item for key, item in value.items()}
    if _contains_secret_like_content(result):
        raise MCPToolError("MCP tool result contained secret-looking content")
    return result


def _contains_secret_like_content(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(_contains_secret_like_key(key) or _contains_secret_like_content(item) for key, item in value.items())
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_secret_like_content(item) for item in value)
    if not isinstance(value, str):
        return False
    if any(marker.casefold() in value.casefold() for marker in SECRET_LIKE_PATTERNS):
        return True
    if SECRET_ASSIGNMENT_PATTERN.search(value):
        return True
    if URL_CREDENTIAL_PATTERN.search(value):
        return True
    if PRIVATE_DATA_PATH_PATTERN.search(value) or PRIVATE_DATA_PATH_SEGMENT_PATTERN.search(value):
        return True
    return any(re.search(pattern, value) for pattern in SECRET_TOKEN_PATTERNS)


def _contains_secret_like_key(value: Any) -> bool:
    return bool(SECRET_LIKE_KEY_PATTERN.search(str(value or "")))
