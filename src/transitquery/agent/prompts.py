"""What the model is told. Accuracy mostly comes from here, not from the graph.

The message builders at the bottom are done. Your part is SYSTEM, DOMAIN_HINTS
and EXAMPLES: the knowledge about this data that a model can't guess.
"""

import json
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

SYSTEM = """\
You write one PostgreSQL SELECT query that answers a question about TTC
(Toronto transit) delays. Use only the tables and columns in the schema below.
"""

# Facts about this data the model can't infer from the schema alone.
DOMAIN_HINTS: list[str] = [
    ("A \"delay\" means min_delay > 0. About 65% of subway rows have min_delay = 0 "
    "(an incident was logged but nothing was held up). Always filter min_delay > 0 "
    "when counting delays, ranking by delays, or averaging delay minutes."),
    ("Rush hour means weekdays only (NOT is_weekend) with hour BETWEEN 7 AND 9 or "
    "hour BETWEEN 16 AND 18. Hour 10 is not rush hour."),
    ("A season named with a year uses meteorological seasons. Winter 2025 means "
    "2024-12-01 up to but not including 2025-03-01. Spring is Mar-May, summer Jun-Aug, "
    "fall Sep-Nov of that year."),
    ("For a calendar year or date range, filter with occurred_at >= 'YYYY-01-01' AND "
    "occurred_at < 'YYYY+1-01-01' rather than EXTRACT(year ...), so the index is used."),
    ("Times are already in America/Toronto. Use the ready-made columns hour (0-23), "
    "day_of_week (e.g. 'Monday') and is_weekend instead of computing them."),
    ("subway_delays.station is NULL when the location isn't a station (a yard, a whole "
    "line, or between stations). Add station IS NOT NULL when ranking or grouping by station."),
    ("Stations use current names in uppercase: DUNDAS is 'TMU', EGLINTON WEST is "
    "'CEDARVALE', DOWNSVIEW is 'SHEPPARD WEST'. Match the stored name exactly."),
    ("Subway line_code can list several lines at interchange stations (e.g. '1/2'). "
    "To select a line, use line_code LIKE '%1%' rather than = '1'."),
    ("Bus and streetcar reasons: incident (text like 'Mechanical') is filled for 2014-2024 "
    "only, and code is filled from 2025 on only. Use incident for years up to 2024 and "
    "code for 2025 and later. Subway uses code for all years."),
    ("To describe a code, LEFT JOIN delay_codes ON delay_codes.code = <table>.code. "
    "Some codes are not in delay_codes, so never use an inner JOIN."),
    ("bus_delays.location and streetcar_delays.location are free text, not standardized. "
    "Match them with ILIKE '%KENNEDY%' rather than =."),
    ("To compare subway, bus and streetcar, query each table separately and combine "
    "with UNION ALL, adding a column that names the mode."),
]

# Good habits shown by example: delay filter, LEFT JOIN, NULL stations, rush hour, UNION ALL.
EXAMPLES: list[tuple[str, str]] = [
    (
        "What were the top 5 reasons for subway delays on Line 2 in 2024, by total minutes?",
        ("SELECT s.code, c.description, COUNT(*) AS incidents, SUM(s.min_delay) AS total_delay_min\n"
        "FROM subway_delays s\n"
        "LEFT JOIN delay_codes c ON c.code = s.code\n"
        "WHERE s.line_code LIKE '%2%'\n"
        "  AND s.min_delay > 0\n"
        "  AND s.occurred_at >= '2024-01-01' AND s.occurred_at < '2025-01-01'\n"
        "GROUP BY s.code, c.description\n"
        "ORDER BY total_delay_min DESC\n"
        "LIMIT 5"),
    ),
    (
        ("Which bus routes had the longest average rush-hour delay in 2023? "
        "Only include routes with at least 50 delays."),
        ("SELECT route, COUNT(*) AS incidents, ROUND(AVG(min_delay), 1) AS avg_delay_min\n"
        "FROM bus_delays\n"
        "WHERE min_delay > 0\n"
        "  AND NOT is_weekend\n"
        "  AND (hour BETWEEN 7 AND 9 OR hour BETWEEN 16 AND 18)\n"
        "  AND occurred_at >= '2023-01-01' AND occurred_at < '2024-01-01'\n"
        "GROUP BY route\n"
        "HAVING COUNT(*) >= 50\n"
        "ORDER BY avg_delay_min DESC\n"
        "LIMIT 10"),
    ),
    (
        "Which subway stations had the most weekend delays in winter 2025?",
        ("SELECT station, COUNT(*) AS incidents\n"
        "FROM subway_delays\n"
        "WHERE min_delay > 0\n"
        "  AND station IS NOT NULL\n"
        "  AND is_weekend\n"
        "  AND occurred_at >= '2024-12-01' AND occurred_at < '2025-03-01'\n"
        "GROUP BY station\n"
        "ORDER BY incidents DESC\n"
        "LIMIT 10"),
    ),
    (
        "How did subway, bus and streetcar compare on delays in 2025?",
        ("SELECT 'subway' AS mode, COUNT(*) AS incidents, SUM(min_delay) AS total_delay_min\n"
        "FROM subway_delays\n"
        "WHERE min_delay > 0 AND occurred_at >= '2025-01-01' AND occurred_at < '2026-01-01'\n"
        "UNION ALL\n"
        "SELECT 'bus', COUNT(*), SUM(min_delay)\n"
        "FROM bus_delays\n"
        "WHERE min_delay > 0 AND occurred_at >= '2025-01-01' AND occurred_at < '2026-01-01'\n"
        "UNION ALL\n"
        "SELECT 'streetcar', COUNT(*), SUM(min_delay)\n"
        "FROM streetcar_delays\n"
        "WHERE min_delay > 0 AND occurred_at >= '2025-01-01' AND occurred_at < '2026-01-01'\n"
        "ORDER BY total_delay_min DESC"),
    ),
    (
        "What were the most common reasons for delays on the 504 streetcar in 2022?",
        ("SELECT incident, COUNT(*) AS incidents\n"
        "FROM streetcar_delays\n"
        "WHERE min_delay > 0\n"
        "  AND route = 504\n"
        "  AND occurred_at >= '2022-01-01' AND occurred_at < '2023-01-01'\n"
        "GROUP BY incident\n"
        "ORDER BY incidents DESC\n"
        "LIMIT 5"),
    ),
]


def format_schema(tables: list[dict[str, Any]], details: list[dict[str, Any]]) -> str:
    """Tables and columns with their comments, compact enough to send on every call."""
    by_name = {d["name"]: d for d in details}
    parts = []
    for table in tables:
        detail = by_name[table["name"]]
        lines = [f"TABLE {table['name']} (~{table['approx_rows']:,} rows): {table['description']}"]
        for col in detail["columns"]:
            lines.append(f"  {col['name']} {col['type']}: {col['description'] or ''}")
        if detail["sample_rows"]:
            lines.append(f"  sample row: {json.dumps(detail['sample_rows'][0], default=str)}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def generation_messages(question: str, schema_ctx: str, previous_sql: str | None = None,
                        error: str | None = None) -> list[BaseMessage]:
    """Prompt for writing the SQL. On a retry, includes the failed query and its error."""
    system = [SYSTEM, "SCHEMA:\n" + schema_ctx]
    if DOMAIN_HINTS:
        system.append("ABOUT THE DATA:\n" + "\n".join(f"- {hint}" for hint in DOMAIN_HINTS))
    if EXAMPLES:
        system.append("EXAMPLES:\n" + "\n\n".join(f"Q: {q}\nSQL: {s}" for q, s in EXAMPLES))

    user = f"Question: {question}"
    if previous_sql is not None:
        user += (f"\n\nYour previous query failed.\nQuery: {previous_sql}\nError: {error}\n"
                 "Write a corrected query.")
    return [SystemMessage("\n\n".join(system)), HumanMessage(user)]


SUMMARY_ROWS = 50   # enough to answer from; keeps the prompt small on big results


def summary_messages(question: str, sql: str, result: dict[str, Any]) -> list[BaseMessage]:
    """Prompt for the plain-English answer, grounded in the rows the query returned."""
    rows = result["rows"][:SUMMARY_ROWS]
    note = " (truncated: more rows exist)" if result["truncated"] else ""
    return [
        SystemMessage("Answer the question in one to three sentences, using only the query "
                      "result below. Give numbers with units (minutes, incidents). If the result "
                      "is empty, say no matching delays were found."),
        HumanMessage(f"Question: {question}\nSQL: {sql}\n"
                     f"Columns: {result['columns']}\nRows{note}: {json.dumps(rows, default=str)}"),
    ]
