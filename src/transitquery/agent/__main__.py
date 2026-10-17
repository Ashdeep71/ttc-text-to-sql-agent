"""Ask one question from the command line:

    python -m transitquery.agent "Which subway station had the most delays in 2025?"
"""

import argparse
import asyncio
import sys

from langchain_openai import ChatOpenAI

from transitquery.agent.client import MCPTools
from transitquery.agent.graph import ask, build_graph
from transitquery.config import get_settings


async def main(question: str) -> None:
    settings = get_settings()
    if settings.openai_api_key is None or not settings.openai_model:
        sys.exit("Set OPENAI_API_KEY and OPENAI_MODEL in .env first.")

    llm = ChatOpenAI(model=settings.openai_model, api_key=settings.openai_api_key)
    async with MCPTools.connect(settings) as tools:
        graph = build_graph(tools, llm, settings.agent_max_attempts)
        out = await ask(graph, question)

    for step in out["trace"]:
        status = f"error: {step['error']}" if step["error"] else f"{step['row_count']} rows"
        print(f"[attempt {step['attempt']}] {status}\n  {step['sql']}")
    print(f"\n{out['answer']}\n\n({out['attempts']} attempt(s), {out['latency_ms']} ms)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ask TransitQuery a question.")
    parser.add_argument("question")
    asyncio.run(main(parser.parse_args().question))
