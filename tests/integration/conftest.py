"""Fixtures for tests that need the real database (the transitquery-db container).

Start it first:  docker start transitquery-db
If it isn't reachable, every test in this folder is skipped instead of failing.
"""

from typing import Any

import psycopg
import pytest
from mcp import Client

from transitquery.config import Settings, get_settings
from transitquery.mcp_server.db import Database
from transitquery.mcp_server.server import mcp


@pytest.fixture
def anyio_backend() -> str:
    """Async tests here run under anyio's plugin (each test module sets pytestmark).

    anyio, not pytest-asyncio: the MCP client is built on anyio and must be opened
    and closed in the same task, which only anyio's plugin guarantees for fixtures.
    """
    return "asyncio"


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Settings from .env; skips the whole folder if the database isn't up."""
    settings = get_settings()
    try:
        psycopg.connect(settings.conninfo, connect_timeout=3).close()
    except psycopg.OperationalError as error:
        pytest.skip(f"database not reachable (is transitquery-db running?): {error}")
    return settings


@pytest.fixture(scope="session")
def db(settings: Settings):
    """One Database (connection pool) shared by every test."""
    with Database(settings) as db:
        yield db


@pytest.fixture
async def client(settings: Settings):
    """An MCP client connected to the server in-process, the way Claude Desktop sees it.

    The server's lifespan runs here, so it opens its own pool, as in production.
    """
    async with Client(mcp) as client:
        yield client


@pytest.fixture
def call_tool(client: Client):
    """Call a tool and return (is_error, payload).

    payload is the tool's return value on success, or the error text on failure.
    Tools that return a list come back wrapped as {"result": [...]}; this unwraps them.
    """
    async def call(name: str, arguments: dict[str, Any] | None = None) -> tuple[bool, Any]:
        result = await client.call_tool(name, arguments or {})
        if result.is_error:
            return True, result.content[0].text
        payload = result.structured_content
        if isinstance(payload, dict) and payload.keys() == {"result"}:
            payload = payload["result"]
        return False, payload

    return call
