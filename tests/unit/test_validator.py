"""Unit tests for transitquery.mcp_server.validator.

The dangerous cases follow DESIGN.md: each one must be rejected before it
reaches the database, even though the read-only role would also stop it.
"""

import pytest
import sqlglot
from sqlglot import exp

from transitquery.mcp_server.validator import DEFAULT_LIMIT, MAX_LIMIT, ValidationError, validate


def _limit_of(sql: str) -> int | None:
    """The outermost LIMIT of validated SQL, as a number."""
    limit = sqlglot.parse_one(sql, dialect="postgres").args.get("limit")
    return int(limit.expression.name) if limit else None


# --- Allowed queries ---------------------------------------------------------------

@pytest.mark.parametrize(
    "sql",
    [
        "SELECT station FROM subway_delays",
        "select station from subway_delays",
        "SELECT station, count(*) AS n FROM subway_delays WHERE min_delay > 0 GROUP BY station ORDER BY n DESC",
        "SELECT d.code, c.description FROM subway_delays d LEFT JOIN delay_codes c USING (code)",
        "SELECT * FROM subway_delays WHERE occurred_at >= '2025-01-01' AND EXTRACT(hour FROM occurred_at) BETWEEN 7 AND 9",
        "SELECT date_trunc('month', occurred_at) AS month, avg(min_delay) FROM bus_delays GROUP BY 1",
        "WITH x AS (SELECT station, count(*) AS n FROM subway_delays GROUP BY 1) SELECT * FROM x",
        "SELECT route FROM bus_delays UNION SELECT route FROM streetcar_delays",
        "SELECT route FROM bus_delays UNION ALL SELECT route FROM streetcar_delays",
        "SELECT route FROM bus_delays INTERSECT SELECT route FROM streetcar_delays",
        "SELECT * FROM (SELECT * FROM subway_delays WHERE line_code = '1') AS s",
        "SELECT 1;",                                   # a trailing semicolon is fine
        "-- which station?\nSELECT station FROM subway_delays",
        "SELECT station FROM subway_delays WHERE station = 'QUEEN''S PARK'",
    ],
)
def test_accepts_read_queries(sql):
    result = validate(sql)
    assert sqlglot.parse_one(result, dialect="postgres") is not None   # output is valid SQL


def test_returns_rewritten_sql_not_the_input():
    assert validate("select station from subway_delays") == "SELECT station FROM subway_delays LIMIT 100"


# --- Rejected: not a read -------------------------------------------------------------

@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE subway_delays",
        "DELETE FROM subway_delays",
        "DELETE FROM subway_delays WHERE true",
        "UPDATE subway_delays SET min_delay = 0",
        "INSERT INTO delay_codes VALUES ('X', 'Y', 'bus')",
        "TRUNCATE subway_delays",
        "CREATE TABLE stolen (x int)",
        "ALTER TABLE subway_delays DROP COLUMN station",
        "COPY subway_delays TO '/tmp/out.csv'",
        "MERGE INTO delay_codes d USING delay_codes s ON d.code = s.code WHEN MATCHED THEN DELETE",
        "SET default_transaction_read_only = off",
        "GRANT ALL ON subway_delays TO PUBLIC",
        "EXPLAIN ANALYZE SELECT 1",
        "VACUUM subway_delays",
    ],
)
def test_rejects_statements_that_are_not_select(sql):
    with pytest.raises(ValidationError):
        validate(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; DROP TABLE subway_delays",
        "SELECT 1; SELECT 2",
        "SELECT 1; DELETE FROM subway_delays;",
    ],
)
def test_rejects_stacked_queries(sql):
    with pytest.raises(ValidationError, match="exactly one"):
        validate(sql)


# --- Rejected: starts with SELECT but still writes or locks ---------------------------

@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * INTO stolen FROM subway_delays",
        "SELECT * FROM subway_delays FOR UPDATE",
        "SELECT * FROM subway_delays FOR SHARE",
        "WITH d AS (DELETE FROM subway_delays RETURNING *) SELECT * FROM d",
        "WITH u AS (UPDATE subway_delays SET min_delay = 0 RETURNING *) SELECT count(*) FROM u",
        "WITH i AS (INSERT INTO delay_codes VALUES ('X', 'Y', 'bus') RETURNING *) SELECT * FROM i",
    ],
)
def test_rejects_hidden_writes(sql):
    with pytest.raises(ValidationError, match="not allowed"):
        validate(sql)


# --- Rejected: dangerous functions ---------------------------------------------------

@pytest.mark.parametrize(
    "sql",
    [
        "SELECT pg_sleep(10)",
        "SELECT PG_SLEEP(10)",
        "SELECT pg_sleep_for('1 hour')",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT pg_ls_dir('.')",
        "SELECT lo_import('/etc/passwd')",
        "SELECT lo_export(1, '/tmp/x')",
        "SELECT dblink('host=evil', 'SELECT 1')",
        "SELECT dblink_exec('host=evil', 'DROP TABLE x')",
        "SELECT set_config('statement_timeout', '0', false)",
        "SELECT pg_terminate_backend(123)",
        "SELECT nextval('some_seq')",
        # hidden deeper in the query
        "SELECT * FROM subway_delays WHERE station = (SELECT pg_read_file('/etc/passwd'))",
        "WITH x AS (SELECT pg_sleep(10)) SELECT * FROM x",
        "SELECT station FROM subway_delays UNION SELECT pg_read_file('/etc/passwd')",
    ],
)
def test_rejects_dangerous_functions(sql):
    with pytest.raises(ValidationError, match=r"function .*\(\) is not allowed"):
        validate(sql)


def test_allows_ordinary_functions():
    sql = "SELECT upper(station), round(avg(min_delay), 1), coalesce(bound, '?') FROM subway_delays GROUP BY 1, 3"
    validate(sql)   # must not raise


# --- Rejected: empty or unreadable --------------------------------------------------

@pytest.mark.parametrize("sql", ["", "   ", "\n", ";"])
def test_rejects_empty_sql(sql):
    with pytest.raises(ValidationError):
        validate(sql)


@pytest.mark.parametrize("sql", ["SELEC * FRM subway_delays", "SELECT FROM WHERE", "SELECT (1"])
def test_rejects_invalid_sql(sql):
    with pytest.raises(ValidationError):
        validate(sql)


def test_error_message_names_what_was_sent():
    with pytest.raises(ValidationError, match="starts with DELETE"):
        validate("DELETE FROM subway_delays")


# --- LIMIT ------------------------------------------------------------------------

def test_adds_default_limit():
    assert _limit_of(validate("SELECT * FROM subway_delays")) == DEFAULT_LIMIT


@pytest.mark.parametrize("n", [1, 5, 100, MAX_LIMIT])
def test_keeps_limit_within_max(n):
    assert _limit_of(validate(f"SELECT * FROM subway_delays LIMIT {n}")) == n


@pytest.mark.parametrize(
    "sql",
    [
        f"SELECT * FROM subway_delays LIMIT {MAX_LIMIT + 1}",
        "SELECT * FROM subway_delays LIMIT 50000",
        "SELECT * FROM subway_delays LIMIT (SELECT count(*) FROM bus_delays)",
        "SELECT * FROM subway_delays FETCH FIRST 5000 ROWS ONLY",
    ],
)
def test_clamps_large_or_unusual_limits(sql):
    assert _limit_of(validate(sql)) == MAX_LIMIT


def test_limit_all_gets_default_limit():
    assert _limit_of(validate("SELECT * FROM subway_delays LIMIT ALL")) == DEFAULT_LIMIT


def test_keeps_offset():
    result = validate("SELECT * FROM subway_delays LIMIT 10 OFFSET 20")
    tree = sqlglot.parse_one(result, dialect="postgres")
    assert _limit_of(result) == 10
    assert tree.args["offset"].expression.name == "20"


def test_limit_applies_to_whole_union():
    result = validate("SELECT route FROM bus_delays UNION SELECT route FROM streetcar_delays")
    tree = sqlglot.parse_one(result, dialect="postgres")
    assert isinstance(tree, exp.Union)
    assert _limit_of(result) == DEFAULT_LIMIT


def test_limit_in_subquery_is_left_alone():
    """Only the outermost LIMIT caps the result; an inner one is part of the query's logic."""
    result = validate("SELECT * FROM (SELECT * FROM subway_delays LIMIT 5000) AS s")
    assert _limit_of(result) == DEFAULT_LIMIT
    assert "LIMIT 5000" in result
