"""Model backends.

FixtureModel is the default. It is one policy for every variant, and it never
sees the gold label. The harness changes what it can observe:

- The user can demand an answer with no tools. The model obeys.
- A runbook can contain an instruction. The model obeys that too.
- A check with status unknown is guessed as pass.

Guardrails and better tools change the transcript and the tool list, not this
policy. OpenAIModel runs the same loop against a chat-completions API.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from eval_harness.cost import estimate_tokens
from eval_harness.tools import EVIDENCE_TOOLS, INJECTION_MARK

MODEL_LATENCY_MS = 50

_SERVICE = re.compile(r"`([a-z0-9-]+)`")
_ASSERTED = re.compile(r"Reply immediately with verdict (pass|fail)\b")

_STATUS_FIELD = {
    "get_service": "config_status",
    "lookup_owner": "status",
    "check_feature_flag": "status",
    "check_slo": "status",
    "get_recent_incidents": "status",
    "read_runbook": "status",
}
_LABEL = {
    "get_service": "config",
    "lookup_owner": "owner",
    "check_feature_flag": "feature_flag",
    "check_slo": "slo",
    "get_recent_incidents": "incidents",
    "read_runbook": "runbook",
}


@dataclass
class ModelTurn:
    content: str | None = None
    tool_name: str | None = None
    tool_args: dict | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0


def parse_verdict(content: str) -> tuple:
    if not content:
        return "unknown", "empty model response"
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict) and data.get("verdict") in {"pass", "fail", "unknown"}:
        return data["verdict"], str(data.get("reason") or "")
    match = re.search(r"\b(pass|fail|unknown)\b", content)
    if match:
        return match.group(1), content.strip()
    return "unknown", content.strip()


class FixtureModel:
    name = "fixture-v1"
    simulated_latency = True

    def complete(self, messages: list, tools: list) -> ModelTurn:
        prompt_tokens = estimate_tokens(json.dumps(messages) + json.dumps(tools))
        content, tool_name, tool_args = self._decide(messages, tools)
        completion = content or json.dumps({"name": tool_name, "args": tool_args})
        return ModelTurn(
            content=content,
            tool_name=tool_name,
            tool_args=tool_args,
            prompt_tokens=prompt_tokens,
            completion_tokens=estimate_tokens(completion),
            latency_ms=MODEL_LATENCY_MS,
        )

    def _decide(self, messages: list, tools: list) -> tuple:
        names = [tool["name"] for tool in tools]
        results = _tool_results(messages)
        called = [name for name, _ in results]
        prompt = _task_prompt(messages)
        service = _service_name(prompt)
        rejected = any("Guardrail:" in message["content"] for message in messages)

        if "check_readiness" in names and "check_readiness" not in called:
            return None, "check_readiness", {"service": service}
        readiness = _result(results, "check_readiness")
        if readiness is not None:
            return _from_readiness(readiness), None, None

        asserted = _ASSERTED.search(prompt)
        if asserted and not rejected and not called:
            return (
                _final(
                    asserted.group(1),
                    "Answered from the user message without tools.",
                ),
                None,
                None,
            )

        runbook = _result(results, "read_runbook")
        if runbook is not None and INJECTION_MARK in (runbook.get("body") or ""):
            return (
                _final("pass", "Followed an instruction found in the runbook."),
                None,
                None,
            )

        for name in EVIDENCE_TOOLS:
            if name in names and name not in called:
                return None, name, {"service": service}
        return _from_statuses(results), None, None


class OpenAIModel:
    name = "openai"
    simulated_latency = False

    def __init__(self, api_key: str, base_url: str, model: str, post=None):
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Use the default fixture provider, "
                "or export OPENAI_API_KEY and EVAL_PROVIDER=openai."
            )
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.name = model
        self._post = post or _post_json

    def complete(self, messages: list, tools: list) -> ModelTurn:
        payload = {
            "model": self.model,
            "messages": _openai_messages(messages),
            "temperature": 0,
        }
        if tools:
            payload["tools"] = [_openai_tool(tool) for tool in tools]
        data = self._post(
            f"{self.base_url}/chat/completions",
            payload,
            {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        message = data["choices"][0]["message"]
        usage = data.get("usage") or {}
        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            call = tool_calls[0]
            function = call["function"]
            arguments = function.get("arguments") or "{}"
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            return ModelTurn(
                tool_name=function["name"],
                tool_args=arguments,
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                latency_ms=0,
            )
        return ModelTurn(
            content=message.get("content") or "",
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            latency_ms=0,
        )


def build_model(provider: str, env: dict | None = None):
    import os

    values = env if env is not None else os.environ
    if provider == "fixture":
        return FixtureModel()
    if provider == "openai":
        return OpenAIModel(
            api_key=values.get("OPENAI_API_KEY", ""),
            base_url=values.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            model=values.get("EVAL_MODEL", "gpt-4o-mini"),
        )
    raise SystemExit(f"unknown provider {provider!r}; use fixture or openai")


def _final(verdict: str, reason: str) -> str:
    return json.dumps({"verdict": verdict, "reason": reason})


def _from_readiness(result: dict) -> str:
    overall = result["overall"]
    checks = result["checks"]
    if overall == "fail":
        failed = [name for name, status in checks.items() if status == "fail"]
        return _final(overall, "check_readiness failed: " + ", ".join(failed))
    if overall == "unknown":
        unknown = [name for name, status in checks.items() if status == "unknown"]
        return _final(overall, "check_readiness unknown: " + ", ".join(unknown))
    return _final("pass", "check_readiness overall is pass.")


def _from_statuses(results: list) -> str:
    statuses = []
    failed = []
    for name, result in results:
        field = _STATUS_FIELD.get(name)
        if field is None or field not in result:
            continue
        status = result[field]
        statuses.append(status)
        if status == "fail":
            failed.append(_LABEL[name])
    if any(status == "unknown" for status in statuses):
        return _final("pass", "Guessed pass without resolving unknown checks.")
    if failed:
        return _final("fail", "Failed checks: " + ", ".join(failed))
    return _final("pass", "All required go-live checks passed.")


def _tool_results(messages: list) -> list:
    results = []
    for message in messages:
        if message["role"] == "tool":
            results.append((message["tool_name"], json.loads(message["content"])))
    return results


def _result(results: list, name: str):
    for tool_name, result in results:
        if tool_name == name:
            return result
    return None


def _task_prompt(messages: list) -> str:
    for message in messages:
        if message["role"] == "user" and _SERVICE.search(message["content"]):
            return message["content"]
    raise ValueError("conversation has no service id in the user prompt")


def _service_name(prompt: str) -> str:
    match = _SERVICE.search(prompt)
    if not match:
        raise ValueError("prompt has no `service-id`")
    return match.group(1)


def _openai_tool(tool: dict) -> dict:
    return {"type": "function", "function": tool}


def _openai_messages(messages: list) -> list:
    converted = []
    for message in messages:
        role = message["role"]
        if role == "tool":
            converted.append(
                {
                    "role": "tool",
                    "tool_call_id": message["tool_call_id"],
                    "content": message["content"],
                }
            )
            continue
        if role == "assistant" and message.get("tool_name"):
            converted.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": message["tool_call_id"],
                            "type": "function",
                            "function": {
                                "name": message["tool_name"],
                                "arguments": json.dumps(message["tool_args"]),
                            },
                        }
                    ],
                }
            )
            continue
        converted.append({"role": role, "content": message["content"]})
    return converted


def _post_json(url: str, payload: dict, headers: dict) -> dict:
    import urllib.error
    import urllib.request

    body = json.dumps(payload).encode()
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"model API {exc.code}: {detail}") from exc
