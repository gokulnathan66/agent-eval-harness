"""Optional Langfuse export.

Local JSON is the source of truth. When LANGFUSE_PUBLIC_KEY and
LANGFUSE_SECRET_KEY are set, each scored trace is also posted to the public
ingestion API. A Langfuse failure is recorded and does not fail the eval.
"""

from __future__ import annotations

import base64
import json
import os
import uuid
from datetime import datetime, timezone


class LangfuseExporter:
    def __init__(self, env: dict | None = None, post=None):
        values = env if env is not None else os.environ
        self.public_key = values.get("LANGFUSE_PUBLIC_KEY", "")
        self.secret_key = values.get("LANGFUSE_SECRET_KEY", "")
        self.host = values.get("LANGFUSE_HOST", "https://cloud.langfuse.com").rstrip("/")
        self.enabled = bool(self.public_key and self.secret_key)
        self._post = post or _post_json
        self.exported = 0
        self.errors = []

    def export_trace(self, record: dict) -> None:
        if not self.enabled:
            return
        try:
            self._post(
                f"{self.host}/api/public/ingestion",
                {"batch": _batch(record)},
                {
                    "Authorization": _basic(self.public_key, self.secret_key),
                    "Content-Type": "application/json",
                },
            )
        except Exception as exc:  # network and API errors stay on the report
            self.errors.append(str(exc))
            return
        self.exported += 1


def _batch(record: dict) -> list:
    trace = record["trace"]
    score = record["score"]
    now = datetime.now(timezone.utc).isoformat()
    trace_id = str(uuid.uuid4())
    events = [
        {
            "id": str(uuid.uuid4()),
            "type": "trace-create",
            "timestamp": now,
            "body": {
                "id": trace_id,
                "timestamp": now,
                "name": "go-live-eval",
                "input": trace["prompt"],
                "output": {"verdict": trace["verdict"], "reason": trace["reason"]},
                "metadata": {
                    "variant": trace["variant"],
                    "task_id": trace["task_id"],
                    "success": score["success"],
                    "tool_match": score["tool_match"],
                },
                "tags": [trace["variant"], record["tag"]],
            },
        }
    ]
    for step in trace["steps"]:
        events.append(
            {
                "id": str(uuid.uuid4()),
                "type": "span-create",
                "timestamp": now,
                "body": {
                    "id": str(uuid.uuid4()),
                    "traceId": trace_id,
                    "name": step["tool"],
                    "input": step["args"],
                    "output": step["result"],
                },
            }
        )
    return events


def _basic(public_key: str, secret_key: str) -> str:
    token = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    return f"Basic {token}"


def _post_json(url: str, payload: dict, headers: dict) -> dict:
    import urllib.error
    import urllib.request

    body = json.dumps(payload).encode()
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"Langfuse {exc.code}: {detail}") from exc
