from __future__ import annotations

from typing import Any

from TeeBotus.mcp_tools.registry import MCPToolRegistry


FASTMCP_READONLY_ALLOWLIST = ("bibliothekar.search", "memory.search")


def fastmcp_available() -> bool:
    try:
        import fastmcp  # noqa: F401
    except Exception:
        return False
    return True


def build_fastmcp_server(registry: MCPToolRegistry, *, name: str = "TeeBotus Readonly Tools") -> Any:
    try:
        from fastmcp import FastMCP  # type: ignore[import-not-found]
    except Exception as exc:
        raise RuntimeError("FastMCP is not installed. Install TeeBotus with extra [tools].") from exc

    server = FastMCP(name)
    exposed = set(registry.tool_names).intersection(FASTMCP_READONLY_ALLOWLIST)

    if "bibliothekar.search" in exposed:

        @server.tool(name="bibliothekar.search")
        def bibliothekar_search(
            query: str,
            top_k: int = 5,
            max_prompt_chars: int = 5000,
            max_quote_chars: int = 900,
            category: str = "",
            topic: str = "",
            keyword: str = "",
            file: str = "",
            relative_path: str = "",
        ) -> dict[str, Any]:
            return registry.call(
                "bibliothekar.search",
                {
                    "query": query,
                    "top_k": top_k,
                    "max_prompt_chars": max_prompt_chars,
                    "max_quote_chars": max_quote_chars,
                    "category": category,
                    "topic": topic,
                    "keyword": keyword,
                    "file": file,
                    "relative_path": relative_path,
                },
            )

    if "memory.search" in exposed:

        @server.tool(name="memory.search")
        def memory_search(query: str) -> dict[str, Any]:
            return registry.call("memory.search", {"query": query})

    return server


__all__ = ["FASTMCP_READONLY_ALLOWLIST", "build_fastmcp_server", "fastmcp_available"]
