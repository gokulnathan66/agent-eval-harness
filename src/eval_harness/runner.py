"""Run every variant over the fixed task set and write traces."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from eval_harness.agent import run_agent
from eval_harness.judge import build_judge
from eval_harness.langfuse import LangfuseExporter
from eval_harness.model import build_model
from eval_harness.report import build_report
from eval_harness.tasks import load_tasks
from eval_harness.verify import score_trace
from eval_harness.world import load_world

VARIANTS = ("baseline", "guardrails", "better_tools")


def run_eval(
    tasks_path: Path,
    world_path: Path,
    out_dir: Path,
    provider: str = "fixture",
    variants: tuple = VARIANTS,
    run_id: str | None = None,
    env: dict | None = None,
    exporter=None,
) -> dict:
    world = load_world(world_path)
    tasks = load_tasks(tasks_path)
    _check_services(tasks, world)
    model = build_model(provider, env)
    judge = build_judge(provider, env)
    if exporter is None:
        exporter = LangfuseExporter(env)
    run_id = run_id or _run_id()
    run_dir = Path(out_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for variant in variants:
        for task in tasks:
            trace = run_agent(task, world, variant, model)
            scored = score_trace(task, trace, variant)
            judge_verdict = judge.judge(task, trace)
            row = {
                "task_id": task["id"],
                "variant": variant,
                "tag": task["tag"],
                "service": task["service"],
                "gold": task["gold_verdict"],
                "verdict": trace["verdict"],
                "reason": trace["reason"],
                "success": scored["success"],
                "tool_match": scored["tool_match"],
                "expected_tools": scored["expected_tools"],
                "actual_tools": scored["actual_tools"],
                "latency_ms": trace["latency_ms"],
                "cost_usd": trace["cost_usd"],
                "judge_verdict": judge_verdict,
                "judge_correct": judge_verdict == task["gold_verdict"],
            }
            record = {"trace": trace, "score": row, "tag": task["tag"], "note": task["note"]}
            path = run_dir / variant / f"{task['id']}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record, indent=2) + "\n")
            row["trace_path"] = str(path)
            exporter.export_trace(record)
            results.append(row)

    report = build_report(results, provider, judge.name, exporter)
    report["run_id"] = run_id
    report["run_dir"] = _display_path(run_dir)
    (run_dir / "scores.json").write_text(json.dumps(_public_scores(report), indent=2) + "\n")
    (run_dir / "REPORT.md").write_text(report["markdown"])
    return report


def _public_scores(report: dict) -> dict:
    hidden = {"markdown"}
    return {key: value for key, value in report.items() if key not in hidden}


def _check_services(tasks: list, world: dict) -> None:
    missing = sorted({task["service"] for task in tasks if task["service"] not in world["services"]})
    if missing:
        raise ValueError(f"tasks reference unknown services: {', '.join(missing)}")


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(resolved)


def _run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid4().hex[:6]}"
