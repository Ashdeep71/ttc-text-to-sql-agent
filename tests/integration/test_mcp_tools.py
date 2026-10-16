"""End-to-end tests: MCP tool call -> validator -> read-only database -> result."""

import psycopg
import pytest

from transitquery.mcp_server.db import Database, QueryError

pytestmark = pytest.mark.anyio          # run the async tests with anyio (see conftest.py)

EXPECTED_TABLES = {"bus_delays", "delay_codes", "streetcar_delays", "subway_delays"}


async def test_list_tables_returns_every_table_with_a_description(call_tool):
    is_error, tables = await call_tool("list_tables")

    assert not is_error
    assert {t["name"] for t in tables} == EXPECTED_TABLES
    for table in tables:
        assert table["description"], f"{table['name']} has no COMMENT ON TABLE"
        assert table["approx_rows"] > 0


def test_read_only_role_blocks_writes(settings):
    """The database layer on its own: plain psycopg, no validator in the way."""
    with (psycopg.connect(settings.conninfo) as conn,
          pytest.raises(psycopg.errors.ReadOnlySqlTransaction)):
        conn.execute("INSERT INTO subway_delays (occurred_at, station, code) VALUES (now(), 'Bloor', 1)")


def test_statement_timeout_cancels_expensive_query(settings):
    short_timeout_settings = settings.model_copy(update={"statement_timeout_ms": 500})
    with Database(short_timeout_settings) as db:
        with pytest.raises(QueryError) as exc_info:
            db.query("SELECT * FROM subway_delays AS a CROSS JOIN subway_delays AS b")
        assert "cancelled" in str(exc_info.value)


async def test_run_query_rejects_writes_and_stacked_statements(call_tool):
    is_error, text = await call_tool("run_query", {"sql": "DROP TABLE subway_delays"})
    assert is_error
    assert "Only SELECT" in text

    is_error, text = await call_tool("run_query", {"sql": "select 1; delete from bus_delays"})
    assert is_error
    assert "exactly one SQL statement" in text


@pytest.mark.parametrize("sql, expected_rows, expected_truncated", [
    ("SELECT * FROM delay_codes", 100, True),                 # default LIMIT 100 added
    ("SELECT * FROM delay_codes LIMIT 10", 10, False),        # caller's own LIMIT kept
    ("SELECT * FROM delay_codes LIMIT 5000", 343, False),     # lowered to 1000, fewer rows exist
    ("SELECT * FROM bus_delays LIMIT 5000", 1000, True),      # lowered to 1000 and filled
])
async def test_truncated_flag(call_tool, sql, expected_rows, expected_truncated):
    is_error, payload = await call_tool("run_query", {"sql": sql})
    assert not is_error
    assert payload["truncated"] == expected_truncated
    assert len(payload["rows"]) == expected_rows


async def test_describe_table_good_and_bad_names(call_tool):
    # Good name: returns the table, and every column has a description
    is_error, payload = await call_tool("describe_table", {"name": "subway_delays"})
    assert not is_error
    assert payload["name"] == "subway_delays"
    assert payload["columns"]
    for col in payload["columns"]:
        assert col["description"], f"{col['name']} has no COMMENT ON COLUMN"

    # Bad name: an error that lists the real table names
    is_error, text = await call_tool("describe_table", {"name": "not_a_table"})
    assert is_error
    assert "No table named" in text
    for table in EXPECTED_TABLES:
        assert table in text
