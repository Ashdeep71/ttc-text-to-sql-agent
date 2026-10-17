"""Run the agent on every eval question and report how it did.

    python -m transitquery.eval.runner                     # model from OPENAI_MODEL
    python -m transitquery.eval.runner --model <name>      # compare another model
    python -m transitquery.eval.runner --only hard         # ids starting with "hard"
    python -m transitquery.eval.runner --no-hints          # ablation: schema only, no hints/examples

Metrics:
    execution accuracy  questions whose result matches the gold result
    self-correction     of the questions whose first query failed, how many still
                        ended with a query that ran (and how many of those were correct)
    latency             per question, end to end (schema load counts once)

Writes eval/reports/<timestamp>-<model>.{json,md}. Exits 1 if accuracy is below
--min-accuracy, so CI can use it as a gate.
"""

import argparse
import asyncio
import json
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from langchain_openai import ChatOpenAI

from transitquery.agent import prompts
from transitquery.agent.client import MCPTools
from transitquery.agent.graph import ask, build_graph
from transitquery.config import PROJECT_ROOT, get_settings
from transitquery.eval.compare import is_ordered, results_match

EVAL_DIR = PROJECT_ROOT / "eval"


async def run_one(graph, tools: MCPTools, item: dict[str, Any]) -> dict[str, Any]:
    gold = await tools.run_query(item["gold_sql"])      # same validator and read-only path
    record = {key: item[key] for key in ("id", "question", "mode", "difficulty", "feature")}
    try:
        out = await ask(graph, item["question"])
    except Exception as error:  # noqa: BLE001 -- one API failure shouldn't stop the run
        return {**record, "correct": False, "reason": f"agent crashed: {error!r}",
                "attempts": 0, "first_failed": False, "ran": False, "latency_ms": None,
                "sql": None, "answer": None}

    ran = not out["trace"][-1]["error"]                  # the last attempt's query ran
    correct, reason = (results_match(gold["rows"], out["rows"], is_ordered(item["gold_sql"]))
                       if ran else (False, "no query ran"))
    return {**record, "correct": correct, "reason": reason, "attempts": out["attempts"],
            "first_failed": bool(out["trace"][0]["error"]), "ran": ran,
            "latency_ms": out["latency_ms"], "sql": out["sql"], "answer": out["answer"]}


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    def accuracy(rows):
        return round(sum(r["correct"] for r in rows) / len(rows), 3) if rows else None

    first_failed = [r for r in results if r["first_failed"]]
    latencies = sorted(r["latency_ms"] for r in results if r["latency_ms"] is not None)
    return {
        "questions": len(results),
        "correct": sum(r["correct"] for r in results),
        "accuracy": accuracy(results),
        "accuracy_by_difficulty": {
            d: accuracy([r for r in results if r["difficulty"] == d])
            for d in ("easy", "medium", "hard")
        },
        "first_attempt_failed": len(first_failed),
        "self_corrected": sum(r["ran"] for r in first_failed),
        "correct_after_retry": sum(r["correct"] for r in first_failed),
        "self_correction_rate": (round(sum(r["ran"] for r in first_failed) / len(first_failed), 3)
                                 if first_failed else None),
        "mean_attempts": round(statistics.mean(r["attempts"] for r in results), 2),
        "latency_ms": {
            "p50": round(statistics.median(latencies)) if latencies else None,
            "p95": latencies[min(len(latencies) - 1, round(0.95 * (len(latencies) - 1)))]
            if latencies else None,
            "mean": round(statistics.mean(latencies)) if latencies else None,
        },
    }


def to_markdown(model: str, when: str, summary: dict[str, Any],
                results: list[dict[str, Any]]) -> str:
    s = summary
    by_diff = ", ".join(f"{d} {v:.0%}" for d, v in s["accuracy_by_difficulty"].items()
                        if v is not None)
    rate = f"{s['self_correction_rate']:.0%}" if s["self_correction_rate"] is not None else "n/a"
    lines = [
        f"# Eval report: {model}", "", f"Run {when}.", "",
        "| Metric | Value |", "|---|---|",
        f"| Execution accuracy | **{s['accuracy']:.0%}** ({s['correct']}/{s['questions']}) |",
        f"| By difficulty | {by_diff} |",
        f"| First query failed | {s['first_attempt_failed']} questions |",
        (f"| Self-correction rate | {rate} ({s['self_corrected']} recovered, "
         f"{s['correct_after_retry']} of them correct) |"),
        f"| Mean attempts | {s['mean_attempts']} |",
        (f"| Latency p50 / p95 / mean | {s['latency_ms']['p50']} / {s['latency_ms']['p95']} / "
         f"{s['latency_ms']['mean']} ms |"),
        "", "| Id | Result | Attempts | ms | Why |", "|---|---|---|---|---|",
    ]
    for r in results:
        mark = "✅" if r["correct"] else "❌"
        lines.append(f"| {r['id']} | {mark} | {r['attempts']} | {r['latency_ms']} | "
                     f"{'' if r['correct'] else r['reason']} |")
    misses = [r for r in results if not r["correct"]]
    if misses:
        lines += ["", "## Misses", ""]
        for r in misses:
            lines += [f"**{r['id']}**: {r['question']}", "", f"- Why: {r['reason']}",
                      f"- Agent answered: {r['answer']}", "", "```sql", f"{r['sql']}", "```", ""]
    return "\n".join(lines) + "\n"


async def main(args: argparse.Namespace) -> int:
    settings = get_settings()
    model = args.model or settings.openai_model
    if settings.openai_api_key is None or not model:
        sys.exit("Set OPENAI_API_KEY and OPENAI_MODEL in .env (or pass --model).")

    items = yaml.safe_load(Path(args.questions).read_text(encoding="utf-8"))
    if args.only:
        items = [i for i in items if i["id"].startswith(args.only)]

    if args.no_hints:                                    # ablation: how much do the hints add?
        prompts.DOMAIN_HINTS, prompts.EXAMPLES = [], []
    label = model + ("-nohints" if args.no_hints else "")

    llm = ChatOpenAI(model=model, api_key=settings.openai_api_key)
    results = []
    async with MCPTools.connect(settings) as tools:
        graph = build_graph(tools, llm, settings.agent_max_attempts)
        for n, item in enumerate(items, 1):
            result = await run_one(graph, tools, item)
            results.append(result)
            mark = "PASS" if result["correct"] else "FAIL"
            print(f"[{n:>2}/{len(items)}] {mark} {item['id']:<10} "
                  f"attempts={result['attempts']} {result['latency_ms']}ms "
                  f"{'' if result['correct'] else result['reason']}", flush=True)

    summary = summarize(results)
    now = datetime.now(UTC).astimezone()                # local time, timezone-aware
    when = now.strftime("%Y-%m-%d %H:%M %Z")
    stem = f"{now:%Y%m%d-%H%M%S}-{label}"
    reports = EVAL_DIR / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / f"{stem}.json").write_text(
        json.dumps({"model": label, "run_at": when, "summary": summary, "results": results},
                   indent=2, default=str), encoding="utf-8")
    (reports / f"{stem}.md").write_text(to_markdown(label, when, summary, results),
                                        encoding="utf-8")

    print(f"\naccuracy {summary['accuracy']:.0%} ({summary['correct']}/{summary['questions']}) | "
          f"self-correction {summary['self_corrected']}/{summary['first_attempt_failed']} | "
          f"latency p50 {summary['latency_ms']['p50']} ms\nreport: {reports / stem}.md")
    return 0 if summary["accuracy"] >= args.min_accuracy else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the TransitQuery eval.")
    parser.add_argument("--model", help="OpenAI model (default: OPENAI_MODEL)")
    parser.add_argument("--only", help="run only question ids starting with this")
    parser.add_argument("--questions", default=str(EVAL_DIR / "questions.yaml"))
    parser.add_argument("--min-accuracy", type=float, default=0.0)
    parser.add_argument("--no-hints", action="store_true",
                        help="ablation: drop DOMAIN_HINTS and EXAMPLES from the prompt")
    sys.exit(asyncio.run(main(parser.parse_args())))
