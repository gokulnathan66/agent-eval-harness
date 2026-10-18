"""Langfuse export is optional and shaped as an ingestion batch."""

import base64
import json

from eval_harness.langfuse import LangfuseExporter


def test_export_is_off_without_keys():
    exporter = LangfuseExporter(env={})
    exporter.export_trace({"trace": {}, "score": {}, "tag": "happy"})
    assert exporter.enabled is False
    assert exporter.exported == 0


def test_export_posts_a_trace_and_one_span_per_tool():
    captured = {}

    def post(url, payload, headers):
        captured["url"] = url
        captured["payload"] = payload
        captured["headers"] = headers
        return {}

    exporter = LangfuseExporter(
        env={
            "LANGFUSE_PUBLIC_KEY": "pk",
            "LANGFUSE_SECRET_KEY": "sk",
            "LANGFUSE_HOST": "https://langfuse.example",
        },
        post=post,
    )
    exporter.export_trace(
        {
            "tag": "injection",
            "trace": {
                "prompt": "Is `auth-gateway` ready?",
                "verdict": "fail",
                "reason": "flag",
                "variant": "guardrails",
                "task_id": "injection-auth-gateway",
                "steps": [
                    {"tool": "read_runbook", "args": {"service": "auth-gateway"}, "result": {"status": "pass"}}
                ],
            },
            "score": {"success": True, "tool_match": True},
        }
    )
    assert exporter.exported == 1
    assert captured["url"] == "https://langfuse.example/api/public/ingestion"
    token = captured["headers"]["Authorization"].split()[1]
    assert base64.b64decode(token).decode() == "pk:sk"
    batch = captured["payload"]["batch"]
    assert [event["type"] for event in batch] == ["trace-create", "span-create"]
    assert batch[0]["body"]["metadata"]["success"] is True
    assert batch[1]["body"]["name"] == "read_runbook"


def test_export_records_api_errors_without_raising():
    def post(url, payload, headers):
        raise RuntimeError("Langfuse 503: down")

    exporter = LangfuseExporter(
        env={"LANGFUSE_PUBLIC_KEY": "pk", "LANGFUSE_SECRET_KEY": "sk"},
        post=post,
    )
    exporter.export_trace(
        {
            "tag": "happy",
            "trace": {
                "prompt": "x",
                "verdict": "pass",
                "reason": "ok",
                "variant": "baseline",
                "task_id": "happy-checkout-api",
                "steps": [],
            },
            "score": {"success": True, "tool_match": False},
        }
    )
    assert exporter.exported == 0
    assert exporter.errors == ["Langfuse 503: down"]
    assert json.dumps(exporter.errors)
