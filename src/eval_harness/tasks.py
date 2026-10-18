"""Load the fixed eval set."""

from __future__ import annotations

import json
from pathlib import Path

TAGS = ("happy", "missing", "hallucination", "injection")
VERDICTS = ("pass", "fail", "unknown")
REQUIRED = (
    "id",
    "tag",
    "service",
    "prompt",
    "gold_verdict",
    "expected_tools",
    "better_tools",
    "note",
)


def load_tasks(path: Path) -> list:
    tasks = []
    text = Path(path).read_text()
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            task = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number} is not valid JSON") from exc
        missing = [field for field in REQUIRED if field not in task]
        if missing:
            raise ValueError(f"{task.get('id', line_number)} missing {missing}")
        if task["tag"] not in TAGS:
            raise ValueError(f"{task['id']} has unknown tag {task['tag']}")
        if task["gold_verdict"] not in VERDICTS:
            raise ValueError(f"{task['id']} has unknown gold verdict")
        tasks.append(task)
    if len(tasks) < 30:
        raise ValueError(f"{path} has {len(tasks)} tasks; need at least 30")
    ids = [task["id"] for task in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path} has duplicate task ids")
    return tasks
