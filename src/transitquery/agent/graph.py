"""The agent: question -> SQL -> rows -> answer, retrying when a query fails.

    START -> load_schema -> generate_sql -> execute --ok--> summarize -> END
                                 ^            |
                                 +--error-----+  (attempts < max)
                                              +--error, attempts = max--> fail -> END

The LLM and the tools are passed in, so tests can swap in fakes.
"""

import operator
import time
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from transitquery.agent import prompts
from transitquery.agent.client import MCPTools, ToolCallError


class SQLDraft(BaseModel):
    """What the model returns when writing SQL (structured output)."""
    reasoning: str = Field(description="One or two sentences: which tables, filters and why.")
    sql: str = Field(description="A single PostgreSQL SELECT statement.")


class State(TypedDict, total=False):
    question: str
    schema_ctx: str
    sql: str
    reasoning: str
    result: dict[str, Any] | None    # run_query's payload on success
    error: str | None                # run_query's error on failure
    attempts: int
    trace: Annotated[list[dict[str, Any]], operator.add]   # one entry per attempt, appended
    answer: str


Route = Literal["summarize", "generate_sql", "fail"]


def route_after_execute(state: State, max_attempts: int) -> Route:
    """Decide what happens after a query runs.

    - no error                        -> "summarize"
    - error, attempts < max_attempts  -> "generate_sql" (try again)
    - error, attempts >= max_attempts -> "fail"
    """
    if state.get("error") is None:
        return "summarize"
    if state["attempts"] < max_attempts:
        return "generate_sql"
    return "fail"
   


def build_graph(tools: MCPTools, llm: BaseChatModel, max_attempts: int = 3):
    sql_writer = llm.with_structured_output(SQLDraft)
    schema_cache: list[str] = []          # the schema is static: load it once per graph

    async def load_schema(state: State) -> State:
        if not schema_cache:
            tables = await tools.list_tables()
            details = [await tools.describe_table(t["name"]) for t in tables]
            schema_cache.append(prompts.format_schema(tables, details))
        return {"schema_ctx": schema_cache[0], "attempts": 0}

    async def generate_sql(state: State) -> State:
        retrying = state.get("error") is not None
        messages = prompts.generation_messages(
            state["question"], state["schema_ctx"],
            previous_sql=state.get("sql") if retrying else None,
            error=state.get("error"),
        )
        draft: SQLDraft = await sql_writer.ainvoke(messages)
        return {"sql": draft.sql, "reasoning": draft.reasoning, "attempts": state["attempts"] + 1}

    async def execute(state: State) -> State:
        step = {"attempt": state["attempts"], "sql": state["sql"]}
        try:
            result = await tools.run_query(state["sql"])
        except ToolCallError as error:
            return {"result": None, "error": str(error), "trace": [{**step, "error": str(error)}]}
        return {"result": result, "error": None,
                "trace": [{**step, "error": None, "row_count": result["row_count"]}]}

    async def summarize(state: State) -> State:
        reply = await llm.ainvoke(prompts.summary_messages(
            state["question"], state["result"]["executed_sql"], state["result"]))
        return {"answer": reply.content}

    async def fail(state: State) -> State:
        return {"answer": f"I couldn't answer that: the query failed {state['attempts']} times. "
                          f"Last error: {state['error']}"}

    graph = StateGraph(State)
    graph.add_node("load_schema", load_schema)
    graph.add_node("generate_sql", generate_sql)
    graph.add_node("execute", execute)
    graph.add_node("summarize", summarize)
    graph.add_node("fail", fail)

    graph.add_edge(START, "load_schema")
    graph.add_edge("load_schema", "generate_sql")
    graph.add_edge("generate_sql", "execute")
    graph.add_conditional_edges("execute", lambda s: route_after_execute(s, max_attempts),
                                ["summarize", "generate_sql", "fail"])
    graph.add_edge("summarize", END)
    graph.add_edge("fail", END)
    return graph.compile()


async def ask(graph, question: str) -> dict[str, Any]:
    """Run one question; the output the API and the eval use."""
    start = time.perf_counter()
    state = await graph.ainvoke({"question": question, "trace": []})
    result = state.get("result") or {}
    return {
        "answer": state["answer"],
        "sql": result.get("executed_sql", state.get("sql")),
        "columns": result.get("columns", []),
        "rows": result.get("rows", []),
        "attempts": state["attempts"],
        "errors": [step["error"] for step in state["trace"] if step["error"]],
        "latency_ms": round((time.perf_counter() - start) * 1000),
        "trace": state["trace"],
    }
