"""Programmatic verifier.

Task success is the verdict compared to gold. Tool accuracy is an exact match
of the tool-name sequence for that variant. The judge is not consulted.
"""

from __future__ import annotations


def expected_tools(task: dict, variant: str) -> list:
    if variant == "better_tools":
        return list(task["better_tools"])
    return list(task["expected_tools"])


def score_trace(task: dict, trace: dict, variant: str) -> dict:
    expected = expected_tools(task, variant)
    actual = [step["tool"] for step in trace["steps"]]
    return {
        "success": trace["verdict"] == task["gold_verdict"],
        "tool_match": actual == expected,
        "expected_tools": expected,
        "actual_tools": actual,
    }
