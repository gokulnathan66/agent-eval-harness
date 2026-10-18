"""Behavioral tests for the go-live harness.

The offline model is one policy. The three runs differ because the harness
changes the tool list, strips injection text, or rejects an early pass/fail.
"""

import json
from pathlib import Path

from eval_harness.agent import run_agent
from eval_harness.cli import main
from eval_harness.model import FixtureModel, OpenAIModel, parse_verdict
from eval_harness.runner import run_eval
from eval_harness.tasks import load_tasks
from eval_harness.tools import INJECTION_MARK, execute, sanitize
from eval_harness.world import assess, load_world

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "tasks" / "go_live.jsonl"
WORLD = ROOT / "world" / "company.json"


def test_gold_matches_the_go_live_rule():
    world = load_world(WORLD)
    tasks = load_tasks(TASKS)
    assert len(tasks) == 32
    counts = {tag: 0 for tag in ("happy", "missing", "hallucination", "injection")}
    for task in tasks:
        counts[task["tag"]] += 1
        gold = assess(world["services"][task["service"]])["overall"]
        assert task["gold_verdict"] == gold
        assert "`" + task["service"] + "`" in task["prompt"]
    assert counts == {"happy": 12, "missing": 8, "hallucination": 6, "injection": 6}


def test_three_runs_separate_the_failure_modes(tmp_path):
    report = run_eval(
        TASKS,
        WORLD,
        tmp_path,
        provider="fixture",
        run_id="test-run",
        exporter=_Quiet(),
    )
    scores = json.loads((tmp_path / "test-run" / "scores.json").read_text())
    baseline = _by_tag(tmp_path)
    assert scores["variants"]["baseline"]["task_success_n"] == 12
    assert scores["variants"]["guardrails"]["task_success_n"] == 24
    assert scores["variants"]["better_tools"]["task_success_n"] == 32
    assert scores["variants"]["baseline"]["tool_accuracy_n"] == 26
    assert scores["variants"]["guardrails"]["tool_accuracy"] == 1
    assert scores["variants"]["better_tools"]["tool_accuracy"] == 1

    assert baseline["happy"]["baseline"] == 12
    assert baseline["missing"]["baseline"] == 0
    assert baseline["hallucination"]["baseline"] == 0
    assert baseline["injection"]["baseline"] == 0
    assert baseline["hallucination"]["guardrails"] == 6
    assert baseline["injection"]["guardrails"] == 6
    assert baseline["missing"]["guardrails"] == 0
    assert baseline["missing"]["better_tools"] == 8

    latency = [scores["variants"][name]["latency_ms"] for name in ("better_tools", "baseline", "guardrails")]
    cost = [scores["variants"][name]["cost_usd"] for name in ("better_tools", "baseline", "guardrails")]
    assert latency == sorted(latency)
    assert cost == sorted(cost)

    leaked = scores["judge_wrong_while_agent_right"]
    assert len(leaked) == 8
    assert {row["tag"] for row in leaked} == {"missing"}
    assert {row["variant"] for row in leaked} == {"better_tools"}
    assert "Where the judge is wrong" in report["markdown"]
    assert (tmp_path / "test-run" / "REPORT.md").exists()
    assert (tmp_path / "test-run" / "baseline" / "happy-checkout-api.json").exists()
    assert len(list((tmp_path / "test-run").rglob("*.json"))) == 32 * 3 + 1
    readme = (ROOT / "README.md").read_text()
    for line in (
        "| Baseline | 37.5% (12/32) | 81.2% (26/32) | 414 ms | $0.000726 |",
        "| With guardrails | 75.0% (24/32) | 100.0% (32/32) | 507 ms | $0.000921 |",
        "| With better tools | 100.0% (32/32) | 100.0% (32/32) | 145 ms | $0.000222 |",
        "| happy | 12 | 12/12 | 12/12 | 12/12 |",
        "| missing | 8 | 0/8 | 0/8 | 8/8 |",
        "| hallucination | 6 | 0/6 | 6/6 | 6/6 |",
        "| injection | 6 | 0/6 | 6/6 | 6/6 |",
    ):
        assert line in report["markdown"]
        assert line in readme


def test_guardrail_blocks_the_early_answer_and_the_runbook_instruction():
    world = load_world(WORLD)
    tasks = {task["id"]: task for task in load_tasks(TASKS)}
    model = FixtureModel()

    hallucination = run_agent(tasks["hallucination-checkout-api"], world, "baseline", model)
    assert hallucination["steps"] == []
    assert hallucination["verdict"] == "fail"

    guarded = run_agent(tasks["hallucination-checkout-api"], world, "guardrails", model)
    assert [step["tool"] for step in guarded["steps"]] == tasks["hallucination-checkout-api"]["expected_tools"]
    assert guarded["guardrail_rejections"]
    assert guarded["verdict"] == "pass"

    injected = run_agent(tasks["injection-auth-gateway"], world, "baseline", model)
    assert injected["verdict"] == "pass"
    assert INJECTION_MARK in injected["steps"][-1]["result"]["body"]

    cleaned = run_agent(tasks["injection-auth-gateway"], world, "guardrails", model)
    assert cleaned["verdict"] == "fail"
    assert INJECTION_MARK not in json.dumps(cleaned["steps"])


def test_readiness_tool_hides_untrusted_text_and_reports_unknown():
    world = load_world(WORLD)
    ready = execute(world, "check_readiness", {"service": "auth-gateway"})
    assert ready["overall"] == "fail"
    assert INJECTION_MARK not in json.dumps(ready)
    unknown = execute(world, "check_readiness", {"service": "catalog-feed"})
    assert unknown["overall"] == "unknown"
    assert unknown["checks"]["slo"] == "unknown"


def test_sanitizer_redacts_the_injection_sentence():
    cleaned = sanitize({"body": "Intro.\n" + INJECTION_MARK + "\nEnd.", "status": "fail"})
    assert INJECTION_MARK not in cleaned["body"]
    assert cleaned["status"] == "fail"
    assert sanitize({"status": "pass"}) == {"status": "pass"}


def test_parse_verdict_reads_json_and_falls_back():
    assert parse_verdict('{"verdict": "unknown", "reason": "no slo"}')[0] == "unknown"
    assert parse_verdict("I think this should fail.")[0] == "fail"
    assert parse_verdict("")[0] == "unknown"


def test_openai_model_parses_tool_calls_and_requires_a_key():
    seen = {}

    def post(url, payload, headers):
        seen["url"] = url
        seen["payload"] = payload
        return {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "get_service",
                                    "arguments": '{"service": "checkout-api"}',
                                }
                            }
                        ]
                    }
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4},
        }

    model = OpenAIModel("test-key", "https://example.invalid/v1", "gpt-test", post=post)
    turn = model.complete(
        [{"role": "user", "content": "hi"}],
        [{"name": "get_service", "description": "lookup", "parameters": {}}],
    )
    assert turn.tool_name == "get_service"
    assert turn.tool_args == {"service": "checkout-api"}
    assert seen["payload"]["tools"][0]["type"] == "function"
    try:
        OpenAIModel("", "https://example.invalid/v1", "gpt-test")
    except RuntimeError as exc:
        assert "OPENAI_API_KEY" in str(exc)
    else:
        raise AssertionError("missing API key should fail")


def _by_tag(tmp_path):
    scores = json.loads((tmp_path / "test-run" / "scores.json").read_text())
    found = {}
    for tag, payload in scores["by_tag"].items():
        found[tag] = {
            variant: payload["variants"][variant]["success_n"]
            for variant in payload["variants"]
        }
    return found


def test_cli_writes_local_traces(tmp_path, capsys):
    code = main(
        ["eval", "--run-id", "cli-run", "--out", str(tmp_path), "--provider", "fixture"]
    )
    assert code == 0
    captured = capsys.readouterr()
    assert "37.5% (12/32)" in captured.out
    assert (tmp_path / "cli-run" / "baseline" / "hallucination-checkout-api.json").is_file()
    assert (tmp_path / "cli-run" / "REPORT.md").is_file()


class _Quiet:
    enabled = False
    exported = 0
    errors = []

    def export_trace(self, record):
        return None
