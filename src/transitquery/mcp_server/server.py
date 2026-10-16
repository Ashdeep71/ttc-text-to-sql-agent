"""The TransitQuery MCP server: three tools over the TTC delay database.

    list_tables()          tables, what they hold, and roughly how many rows
    describe_table(name)   columns, types, comments and a few sample rows
    run_query(sql)         validate, then run read-only; rows or an error to fix

Run it with:  python -m transitquery.mcp_server [--transport stdio|streamable-http]
"""

import argparse
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import anyio.to_thread
import sqlglot
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from psycopg import sql as pgsql

from transitquery.config import get_settings
from transitquery.mcp_server.db import Database, QueryError
from transitquery.mcp_server.validator import ValidationError, validate

SCHEMA = "ttc"
SAMPLE_ROWS = 5

INSTRUCTIONS = """\
Answers questions about TTC (Toronto transit) delays: subway, bus and streetcar.
Start with list_tables, then describe_table for the tables you need, then run_query.
Only SELECT queries run, against a read-only copy; results are capped at 1000 rows.
Times are in America/Toronto. Some subway rows have a NULL station, so filter
station IS NOT NULL when ranking stations."""

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False,
                            idempotent_hint=True, open_world_hint=False)


@asynccontextmanager
async def lifespan(_: MCPServer) -> AsyncGenerator[Database]:
    """Open the connection pool once at startup; tools get it from the context."""
    db = Database(get_settings())
    await anyio.to_thread.run_sync(db.open)
    try:
        yield db
    finally:
        await anyio.to_thread.run_sync(db.close)


mcp = MCPServer("transitquery", instructions=INSTRUCTIONS, lifespan=lifespan)


def _db(ctx: Context) -> Database:
    return ctx.request_context.lifespan_context


def _query(db: Database, query: pgsql.Composable | str, params: tuple = ()) -> list[dict[str, Any]]:
    """Run a metadata query and return rows as dicts."""
    try:
        result = db.query(query, params)
    except QueryError as error:
        raise ToolError(str(error)) from error
    return [dict(zip(result.columns, row, strict=True)) for row in result.rows]


LIST_TABLES = """
    SELECT c.relname AS name,
           obj_description(c.oid, 'pg_class') AS description,
           GREATEST(c.reltuples, 0)::bigint AS approx_rows
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = %s AND c.relkind = 'r' AND has_table_privilege(c.oid, 'SELECT')
    ORDER BY c.relname
"""


@mcp.tool(annotations=READ_ONLY)
def list_tables(ctx: Context) -> list[dict[str, Any]]:
    """List the tables you can query, with a description and an approximate row count."""
    return _query(_db(ctx), LIST_TABLES, (SCHEMA,))


DESCRIBE_COLUMNS = """
    SELECT a.attname AS name,
           format_type(a.atttypid, a.atttypmod) AS type,
           NOT a.attnotnull AS nullable,
           col_description(a.attrelid, a.attnum) AS description
    FROM pg_attribute a
    WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped
    ORDER BY a.attnum
"""


@mcp.tool(annotations=READ_ONLY)
def describe_table(name: str, ctx: Context) -> dict[str, Any]:
    """Show a table's columns (type, nullable, meaning and units) and a few sample rows."""
    db = _db(ctx)
    tables = {t["name"]: t for t in _query(db, LIST_TABLES, (SCHEMA,))}
    table = name.strip().lower().removeprefix(f"{SCHEMA}.")
    if table not in tables:
        raise ToolError(f"No table named {name!r}. Tables: {', '.join(sorted(tables))}.")

    # The name is checked against the catalog above, and quoted as an identifier here.
    columns = _query(db, DESCRIBE_COLUMNS, (f"{SCHEMA}.{table}",))
    sample = pgsql.SQL("SELECT * FROM {} LIMIT {}").format(
        pgsql.Identifier(SCHEMA, table), pgsql.Literal(SAMPLE_ROWS))
    return {
        "name": table,
        "description": tables[table]["description"],
        "columns": columns,
        "sample_rows": _query(db, sample),
    }


def _row_cap(original: str, executed: str) -> int | None:
    """The LIMIT the validator imposed, or None if the caller's own LIMIT was kept."""
    def limit_of(text: str) -> int | None:
        limit = sqlglot.parse_one(text, dialect="postgres").args.get("limit")
        value = limit.expression if limit is not None else None
        return int(value.name) if value is not None and value.is_int else None
    cap = limit_of(executed)
    return None if cap == limit_of(original) else cap


@mcp.tool(annotations=READ_ONLY)
def run_query(sql: str, ctx: Context) -> dict[str, Any]:
    """Run one read-only PostgreSQL SELECT against the TTC delay tables.

    A LIMIT of 100 is added if missing, and anything above 1000 is lowered to 1000.
    `truncated` is true when that added LIMIT cut the result short. On a bad query
    the error explains what to fix.
    """
    try:
        executed = validate(sql)
    except ValidationError as error:
        raise ToolError(f"Query rejected: {error}") from error
    try:
        result = _db(ctx).query(executed)
    except QueryError as error:
        raise ToolError(f"Query failed: {error}") from error

    cap = _row_cap(sql, executed)
    return {
        "columns": result.columns,
        "rows": result.rows,
        "row_count": result.row_count,
        "truncated": cap is not None and result.row_count >= cap,
        "executed_sql": executed,
    }


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--transport", choices=["stdio", "streamable-http"],
                        default=settings.mcp_transport)
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run("stdio")
    else:
        mcp.run("streamable-http", host=settings.mcp_host, port=settings.mcp_port)
