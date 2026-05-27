"""OpenAI Agents SDK MCP server construction."""

from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

try:  # Imported lazily so tests can run with mocked boundaries.
    from agents.mcp import MCPServerStreamableHttp
except Exception:  # pragma: no cover - import environment dependent
    MCPServerStreamableHttp = None  # type: ignore[assignment]


@dataclass(frozen=True)
class McpConfig:
    anysearch_api_key: str | None = None


class McpServerBundle:
    """Async context manager that exposes configured MCP servers to an agent."""

    def __init__(self, config: McpConfig) -> None:
        self.config = config
        self._stack = AsyncExitStack()
        self.servers: list[Any] = []

    async def __aenter__(self) -> "McpServerBundle":
        if MCPServerStreamableHttp is None:
            raise RuntimeError("OpenAI Agents SDK MCP support is unavailable")

        anysearch_headers = {}
        if self.config.anysearch_api_key:
            anysearch_headers["Authorization"] = f"Bearer {self.config.anysearch_api_key}"

        anysearch = MCPServerStreamableHttp(
            name="anysearch",
            params={
                "url": "https://api.anysearch.com/mcp",
                "headers": anysearch_headers,
                "timeout": 30,
            },
            cache_tools_list=True,
            max_retry_attempts=2,
        )
        self.servers.append(await self._stack.enter_async_context(anysearch))
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self._stack.aclose()
