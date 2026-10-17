"""The agent's control flow, with a fake LLM and fake tools: no API calls, no database."""

import pytest
from langchain_core.messages import AIMessage

from transitquery.agent.client import ToolCallError
from transitquery.agent.graph import SQLDraft, ask, build_graph, route_after_execute

pytestmark = pytest.mark.anyio

GOOD_SQL = "SELECT 1"
BAD_SQL = "SELECT nope"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeTools:
    """Stands in for MCPTools. BAD_SQL fails the way a real bad column does."""

    def __init__(self):
        self.schema_loads = 0
        self.queries: list[str] = []

    async def list_tables(self):
        self.schema_loads += 1
        return [{"name": "delays", "description": "Delay incidents.", "approx_rows": 10}]

    async def describe_table(self, name):
        return {"name": name, "description": "Delay incidents.",
                "columns": [{"name": "min_delay", "type": "integer", "description": "Minutes."}],
                "sample_rows": [{"min_delay": 5}]}

    async def run_query(self, sql):
        self.queries.append(sql)
        if sql == BAD_SQL:
            raise ToolCallError('Query failed: column "nope" does not exist')
        return {"columns": ["n"], "rows": [[42]], "row_count": 1,
                "truncated": False, "executed_sql": sql + " LIMIT 100"}


class FakeLLM:
    """Returns the given SQL drafts in order; records every prompt it was sent."""

    def __init__(self, *sqls: str):
        self.sqls = list(sqls)
        self.sql_prompts: list[str] = []      # the user message of each generate_sql call
        self.summaries = 0

    def with_structured_output(self, schema):
        return self                           # generate_sql calls ainvoke on this

    async def ainvoke(self, messages):
        if self.sqls and "Question:" in messages[-1].content and "Columns:" not in messages[-1].content:
            self.sql_prompts.append(messages[-1].content)
            return SQLDraft(reasoning="test", sql=self.sqls.pop(0))
        self.summaries += 1
        return AIMessage("The answer is 42.")


@pytest.mark.parametrize("error, attempts, expected", [
    (None, 1, "summarize"),
    (None, 3, "summarize"),            # success on the last attempt still summarizes
    ("boom", 1, "generate_sql"),
    ("boom", 2, "generate_sql"),
    ("boom", 3, "fail"),
    ("boom", 4, "fail"),               # never loops past the limit
])
def test_route_after_execute(error, attempts, expected):
    assert route_after_execute({"error": error, "attempts": attempts}, max_attempts=3) == expected


async def test_success_on_first_try():
    tools, llm = FakeTools(), FakeLLM(GOOD_SQL)

    out = await ask(build_graph(tools, llm), "How many?")

    assert out["attempts"] == 1
    assert out["errors"] == []
    assert out["answer"] == "The answer is 42."
    assert out["sql"] == "SELECT 1 LIMIT 100"          # the SQL that actually ran
    assert out["rows"] == [[42]]
    assert llm.summaries == 1


async def test_retries_with_the_error_and_then_succeeds():
    tools, llm = FakeTools(), FakeLLM(BAD_SQL, GOOD_SQL)

    out = await ask(build_graph(tools, llm), "How many?")

    assert out["attempts"] == 2
    assert tools.queries == [BAD_SQL, GOOD_SQL]
    assert len(out["errors"]) == 1
    # The retry prompt shows the model its failed query and the database's error.
    assert "previous query failed" in llm.sql_prompts[1]
    assert BAD_SQL in llm.sql_prompts[1]
    assert 'column "nope" does not exist' in llm.sql_prompts[1]
    # The first prompt had no such section.
    assert "previous query failed" not in llm.sql_prompts[0]
    assert out["answer"] == "The answer is 42."


async def test_stops_after_max_attempts_without_summarizing():
    tools, llm = FakeTools(), FakeLLM(BAD_SQL, BAD_SQL, BAD_SQL, GOOD_SQL)

    out = await ask(build_graph(tools, llm, max_attempts=3), "How many?")

    assert out["attempts"] == 3
    assert len(tools.queries) == 3                     # the 4th draft is never requested
    assert len(out["errors"]) == 3
    assert "failed 3 times" in out["answer"]
    assert 'column "nope" does not exist' in out["answer"]
    assert llm.summaries == 0
    assert out["rows"] == []


async def test_schema_is_loaded_once_per_graph():
    tools = FakeTools()
    graph = build_graph(tools, FakeLLM(GOOD_SQL, GOOD_SQL))

    await ask(graph, "First question")
    await ask(graph, "Second question")

    assert tools.schema_loads == 1


async def test_each_question_starts_from_a_clean_state():
    tools = FakeTools()
    graph = build_graph(tools, FakeLLM(BAD_SQL, GOOD_SQL, GOOD_SQL))

    first = await ask(graph, "First question")
    second = await ask(graph, "Second question")

    assert first["attempts"] == 2
    assert second["attempts"] == 1                     # not carried over from the first run
    assert second["errors"] == []
