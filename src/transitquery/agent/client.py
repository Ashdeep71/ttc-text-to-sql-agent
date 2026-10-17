"""The MCP server's three tools as plain async methods, for the agent graph.

This uses the MCP SDK's own Client rather than langchain-mcp-adapters: the
adapters only support mcp 1.x, and the graph calls the tools itself in a fixed
order, so it doesn't need them wrapped as LangChain tools.
"""

import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from transitquery.config import PROJECT_ROOT, Settings


class ToolCallError(RuntimeError):
    """The tool returned an error (a rejected or failed query). The message is for the LLM."""


class MCPTools:
    def __init__(self, client: Client):
        self.client = client

    @classmethod
    @asynccontextmanager
    async def connect(cls, settings: Settings) -> AsyncGenerator["MCPTools"]:
        """Connect to settings.mcp_url, or start the server as a subprocess over stdio."""
        server = settings.mcp_url or StdioServerParameters(
            command=sys.executable, args=["-m", "transitquery.mcp_server"], cwd=PROJECT_ROOT)
        async with Client(server) as client:
            yield cls(client)

    async def _call(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        result = await self.client.call_tool(name, arguments or {})
        if result.is_error:
            raise ToolCallError(result.content[0].text)
        payload = result.structured_content
        if isinstance(payload, dict) and payload.keys() == {"result"}:   # list results come wrapped
            payload = payload["result"]
        return payload

    async def list_tables(self) -> list[dict[str, Any]]:
        return await self._call("list_tables")

    async def describe_table(self, name: str) -> dict[str, Any]:
        return await self._call("describe_table", {"name": name})

    async def run_query(self, sql: str) -> dict[str, Any]:
        """{columns, rows, row_count, truncated, executed_sql}, or raises ToolCallError."""
        return await self._call("run_query", {"sql": sql})
