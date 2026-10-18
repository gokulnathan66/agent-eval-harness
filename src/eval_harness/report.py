"""Score table, tag breakdown, and the judge-error note."""

from __future__ import annotations

from collections import defaultdict

DISPLAY = {
    "baseline": "Baseline",
    "guardrails": "With guardrails",
    "better_tools": "With better tools",
}
VARIANT_ORDER = ("baseline", "guardrails", "better_tools")
TAG_ORDER = ("happy", "missing", "hallucination", "injection")


def build_report(results: list, provider: str, judge_name: str, langfuse) -> dict:
    variants = []
    for variant in VARIANT_ORDER:
        rows = [row for row in results if row["variant"] == variant]
        if rows:
            variants.append(variant)
    by_variant = {}
    for variant in variants:
        rows = [row for row in results if row["variant"] == variant]
        by_variant[variant] = _aggregate(rows)
    by_tag = {}
    for tag in TAG_ORDER:
        tag_rows = [row for row in results if row["tag"] == tag]
        if not tag_rows:
            continue
        by_tag[tag] = {
            "tasks": len({row["task_id"] for row in tag_rows}),
            "variants": {
                variant: _success_fraction(
                    [row for row in tag_rows if row["variant"] == variant]
                )
                for variant in variants
            },
        }
    judge_wrong = [row for row in results if not row["judge_correct"]]
    judge_wrong_agent_right = [row for row in judge_wrong if row["success"]]
    markdown = _markdown(
        provider,
        judge_name,
        results,
        variants,
        by_variant,
        by_tag,
        judge_wrong,
        judge_wrong_agent_right,
        langfuse,
    )
    return {
        "provider": provider,
        "judge": judge_name,
        "task_count": len({row["task_id"] for row in results}),
        "variants": by_variant,
        "by_tag": by_tag,
        "judge_wrong": [_brief(row) for row in judge_wrong],
        "judge_wrong_while_agent_right": [_brief(row) for row in judge_wrong_agent_right],
        "langfuse": {
            "enabled": bool(getattr(langfuse, "enabled", False)),
            "exported": getattr(langfuse, "exported", 0),
            "errors": list(getattr(langfuse, "errors", [])),
        },
        "markdown": markdown,
    }


def _aggregate(rows: list) -> dict:
    total = len(rows)
    success = sum(1 for row in rows if row["success"])
    tools = sum(1 for row in rows if row["tool_match"])
    return {
        "tasks": total,
        "task_success_n": success,
        "task_success": success / total,
        "tool_accuracy_n": tools,
        "tool_accuracy": tools / total,
        "latency_ms": sum(row["latency_ms"] for row in rows) / total,
        "cost_usd": sum(row["cost_usd"] for row in rows) / total,
    }


def _success_fraction(rows: list) -> dict:
    total = len(rows)
    success = sum(1 for row in rows if row["success"])
    return {"success_n": success, "tasks": total}


def _brief(row: dict) -> dict:
    return {
        "task_id": row["task_id"],
        "variant": row["variant"],
        "tag": row["tag"],
        "gold": row["gold"],
        "agent_verdict": row["verdict"],
        "judge_verdict": row["judge_verdict"],
        "agent_correct": row["success"],
    }


def _markdown(
    provider,
    judge_name,
    results,
    variants,
    by_variant,
    by_tag,
    judge_wrong,
    judge_wrong_agent_right,
    langfuse,
) -> str:
    task_count = len({row["task_id"] for row in results})
    latency_note = (
        "Fixture latency is simulated: 50 ms per model call plus a fixed cost per tool. "
        "It is there so the three runs are comparable without sleeping."
        if provider == "fixture"
        else "Latency is wall clock for the live model."
    )
    lines = [
        "# Go-live eval",
        "",
        f"Provider: `{provider}`",
        f"Judge: `{judge_name}`",
        f"Tasks: {task_count}",
        "",
        latency_note,
        "",
        "| Run | Task success | Tool accuracy | Latency | Cost / run |",
        "|-----|--------------|---------------|---------|------------|",
    ]
    for variant in variants:
        stats = by_variant[variant]
        lines.append(
            "| {name} | {success} | {tools} | {latency} | {cost} |".format(
                name=DISPLAY.get(variant, variant),
                success=_pct(stats["task_success_n"], stats["tasks"]),
                tools=_pct(stats["tool_accuracy_n"], stats["tasks"]),
                latency=f"{stats['latency_ms']:.0f} ms",
                cost=f"${stats['cost_usd']:.6f}",
            )
        )
    lines.extend(
        [
            "",
            "## By tag",
            "",
            "Task success in each slice. A single average hides these.",
            "",
            _tag_header(variants),
            "|" + "|".join(["---"] * (2 + len(variants))) + "|",
        ]
    )
    for tag, payload in by_tag.items():
        cells = [tag, str(payload["tasks"])]
        for variant in variants:
            fraction = payload["variants"][variant]
            cells.append(f"{fraction['success_n']}/{fraction['tasks']}")
        lines.append("| " + " | ".join(cells) + " |")
    lines.extend(["", "## Where the judge is wrong", ""])
    lines.extend(_judge_prose(provider, judge_name, judge_wrong, judge_wrong_agent_right))
    lines.extend(["", "## Traces", ""])
    if getattr(langfuse, "enabled", False):
        lines.append(
            f"Langfuse export attempted for {getattr(langfuse, 'exported', 0)} traces."
        )
        for error in getattr(langfuse, "errors", []):
            lines.append(f"Langfuse error: {error}")
    else:
        lines.append("Langfuse is not configured. Traces are local JSON only.")
        lines.append(
            "Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY to also post each trace."
        )
    lines.append("")
    return "\n".join(lines)


def _judge_prose(provider, judge_name, judge_wrong, judge_wrong_agent_right) -> list:
    lines = []
    if provider == "fixture":
        lines.append(
            "This judge reads only the agent's final verdict. It rewrites `unknown` as "
            "`pass` and copies every other verdict. It never looks at the tool trace, so "
            "it agrees with fluent wrong answers and disagrees with a correct `unknown`."
        )
    else:
        lines.append(
            f"`{judge_name}` scored each trace from the rubric. A row is wrong when that "
            "verdict differs from the gold label. The programmatic verifier does not use this score."
        )
    lines.append("")
    lines.append(
        f"Judge wrong: {len(judge_wrong)}. "
        f"Of those, the programmatic verifier was right on {len(judge_wrong_agent_right)}."
    )
    if judge_wrong_agent_right:
        lines.append("")
        lines.append("Verifier right, judge wrong:")
        lines.append("")
        for row in judge_wrong_agent_right:
            lines.append(
                f"- `{row['task_id']}` ({DISPLAY.get(row['variant'], row['variant'])}): "
                f"gold `{row['gold']}`, agent `{row['verdict']}`, judge `{row['judge_verdict']}`"
            )
    copied = [row for row in judge_wrong if not row["success"]]
    if copied:
        lines.append("")
        lines.append(
            f"Judge copied a wrong agent verdict on {len(copied)} traces. "
            "Those are not evidence that the judge checked the work."
        )
        counts = defaultdict(int)
        for row in copied:
            counts[(row["variant"], row["tag"])] += 1
        for variant, tag in sorted(counts):
            lines.append(
                f"- {DISPLAY.get(variant, variant)}, {tag}: {counts[(variant, tag)]}"
            )
    return lines


def _tag_header(variants: list) -> str:
    names = ["Tag", "Tasks"] + [DISPLAY.get(variant, variant) for variant in variants]
    return "| " + " | ".join(names) + " |"


def _pct(numerator: int, denominator: int) -> str:
    rate = 100.0 * numerator / denominator
    return f"{rate:.1f}% ({numerator}/{denominator})"
