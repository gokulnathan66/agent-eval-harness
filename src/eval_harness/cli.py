"""Command line. `python -m eval_harness eval` writes the score table and traces."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from eval_harness.runner import VARIANTS, run_eval


def repo_root() -> Path:
    """Find the checkout that holds tasks/ and world/, from source or an editable install."""
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / "tasks" / "go_live.jsonl").is_file() and (
            candidate / "world" / "company.json"
        ).is_file():
            return candidate
    raise SystemExit(
        "Could not find tasks/go_live.jsonl. Run agent-eval from the repository checkout."
    )


REPO_ROOT = repo_root()


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-eval")
    sub = parser.add_subparsers(dest="command", required=True)
    eval_parser = sub.add_parser("eval", help="run the go-live eval and print the score table")
    eval_parser.add_argument("--tasks", type=Path, default=REPO_ROOT / "tasks" / "go_live.jsonl")
    eval_parser.add_argument("--world", type=Path, default=REPO_ROOT / "world" / "company.json")
    eval_parser.add_argument("--out", type=Path, default=REPO_ROOT / "runs")
    eval_parser.add_argument(
        "--provider",
        default=os.environ.get("EVAL_PROVIDER", "fixture"),
        choices=("fixture", "openai"),
    )
    eval_parser.add_argument("--variants", default=",".join(VARIANTS))
    eval_parser.add_argument("--run-id", default=None)
    args = parser.parse_args(argv)
    if args.command == "eval":
        variants = tuple(part.strip() for part in args.variants.split(",") if part.strip())
        unknown = [name for name in variants if name not in VARIANTS]
        if unknown:
            parser.error(f"unknown variants: {', '.join(unknown)}")
        report = run_eval(
            tasks_path=args.tasks,
            world_path=args.world,
            out_dir=args.out,
            provider=args.provider,
            variants=variants,
            run_id=args.run_id,
        )
        print(report["markdown"])
        print(f"Wrote {report['run_dir']}")
        return 0
    parser.error(f"unknown command {args.command}")
    return 2
