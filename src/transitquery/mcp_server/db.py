"""Runs queries against Postgres as the read-only role.

This is the database-level safety layer; validator.py is the application-level one.
Every query runs in its own READ ONLY transaction with a timeout, and that
transaction is always rolled back, so nothing a query does can be kept.

Synchronous on purpose: psycopg's async mode doesn't work on Windows' default
event loop. The MCP server calls these methods from a worker thread.
"""

import datetime as dt
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Self

import psycopg
from psycopg import errors
from psycopg_pool import ConnectionPool, PoolTimeout

from transitquery.config import Settings
from transitquery.mcp_server.validator import MAX_LIMIT

logger = logging.getLogger(__name__)


class QueryError(RuntimeError):
    """The database refused or failed the query. The message is written for the LLM."""


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool          # more rows existed than max_rows

    @property
    def row_count(self) -> int:
        return len(self.rows)


def to_json_value(value: Any) -> Any:
    """Turn the Python types psycopg returns into ones json.dumps accepts."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    return str(value)                                 # timedelta, UUID, and anything rarer


def _error_message(error: psycopg.Error, timeout_ms: int) -> str:
    if isinstance(error, errors.QueryCanceled):
        return (f"The query took longer than {timeout_ms / 1000:g}s and was cancelled. "
                "Filter on occurred_at or aggregate more to make it cheaper.")
    if isinstance(error, errors.ReadOnlySqlTransaction):
        return "The database is read-only; queries can only read data."
    diag = error.diag
    message = diag.message_primary or str(error).strip()
    if diag.message_hint:
        message += f" (hint: {diag.message_hint})"
    return message


class Database:
    def __init__(self, settings: Settings):
        self.timeout_ms = settings.statement_timeout_ms
        self.pool = ConnectionPool(
            settings.conninfo,
            min_size=1,
            max_size=4,
            open=False,
            kwargs={"application_name": "transitquery-mcp"},   # shows in pg_stat_activity
            check=ConnectionPool.check_connection,             # survive a DB restart
        )

    def open(self) -> None:
        self.pool.open(wait=True, timeout=10)

    def close(self) -> None:
        self.pool.close()

    def __enter__(self) -> Self:
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def query(self, sql: str, params: tuple | dict | None = None,
              max_rows: int = MAX_LIMIT) -> QueryResult:
        """Run one statement read-only and return at most max_rows rows."""
        try:
            # force_rollback: undo the transaction even when the query succeeds.
            with self.pool.connection() as conn, conn.transaction(force_rollback=True):
                conn.execute("SET TRANSACTION READ ONLY")
                # SET can't take a bound parameter; set_config(..., true) is SET LOCAL.
                conn.execute("SELECT set_config('statement_timeout', %s, true)",
                             (str(self.timeout_ms),))
                cur = conn.execute(sql, params)
                if cur.description is None:
                    raise QueryError("The statement returned no rows to read.")
                columns = [col.name for col in cur.description]
                rows = cur.fetchmany(max_rows + 1)         # one extra to detect truncation
        except PoolTimeout as error:
            raise QueryError("Could not get a database connection; try again shortly.") from error
        except psycopg.Error as error:
            logger.info("query failed: %s", error)
            raise QueryError(_error_message(error, self.timeout_ms)) from error

        truncated = len(rows) > max_rows
        return QueryResult(
            columns=columns,
            rows=[[to_json_value(v) for v in row] for row in rows[:max_rows]],
            truncated=truncated,
        )
