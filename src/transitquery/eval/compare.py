"""Execution match: does the agent's result contain the gold result?

Results are compared by value, not by SQL text, because many different queries
are correct. The rules, chosen so a right answer isn't marked wrong for style:

- Every gold column must match some predicted column by its values. Column names
  are ignored, and extra predicted columns are fine (an agent that returns the
  station and its count still answers "which station").
- If the gold SQL has a top-level ORDER BY, row order matters, and a longer
  predicted ranking is accepted when it starts with the gold rows.
- Otherwise rows are compared as a multiset.
- Numbers are rounded to 1 decimal place; 2024.0 and 2024 are equal.
- A one-column gold answer may come back as one row instead ("weekend avg,
  weekday avg" side by side); the values must still match exactly.
"""

from collections import Counter
from itertools import product
from typing import Any

import sqlglot


def normalize(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        value = round(float(value), 1)
        return int(value) if value.is_integer() else value
    return str(value).strip()


def is_ordered(sql: str) -> bool:
    """True if the query's outermost level has an ORDER BY."""
    return sqlglot.parse_one(sql, dialect="postgres").args.get("order") is not None


def _columns(rows: list[list[Any]]) -> list[tuple]:
    return list(zip(*rows, strict=True)) if rows else []


def _sort_key(value: Any) -> tuple[str, str]:
    return type(value).__name__, repr(value)


def results_match(gold_rows: list[list[Any]], pred_rows: list[list[Any]],
                  ordered: bool) -> tuple[bool, str]:
    """(matched, reason). The reason says why not, for the report."""
    gold = [[normalize(v) for v in row] for row in gold_rows]
    pred = [[normalize(v) for v in row] for row in pred_rows]
    if len(pred) == 1 and len(gold) > 1 and len(gold[0]) == 1 and not ordered:
        pred = [[v] for v in pred[0]]              # one row of values for a one-column answer:
                                                   # "weekend 18.2, weekday 17.8" side by side
    if ordered and len(pred) > len(gold):
        pred = pred[:len(gold)]                    # "top 3" answered with a top 10
    if len(pred) != len(gold):
        return False, f"{len(pred)} rows, expected {len(gold)}"
    if not gold:
        return True, "both empty"

    gold_cols, pred_cols = _columns(gold), _columns(pred)

    if ordered:
        # Same row order, so each gold column must equal a predicted column exactly.
        missing = [i for i, col in enumerate(gold_cols) if col not in pred_cols]
        if missing:
            return False, f"no predicted column matches gold column {missing[0]}"
        return True, "match"

    # Unordered: find columns with the same values in any order, then check that
    # the rows, cut down to those columns, are the same multiset.
    candidates = [
        [j for j, p in enumerate(pred_cols) if sorted(p, key=_sort_key) == sorted(g, key=_sort_key)]
        for g in gold_cols
    ]
    if not all(candidates):
        return False, f"no predicted column matches gold column {candidates.index([])}"
    gold_bag = Counter(map(tuple, gold))
    for choice in product(*candidates):
        distinct = len(set(choice)) == len(choice)
        if distinct and Counter(tuple(row[j] for j in choice) for row in pred) == gold_bag:
            return True, "match"
    return False, "columns match individually but not row by row"
