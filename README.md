# agent-eval-harness

Offline eval harness for one tool-using agent. The agent decides whether a Northwind service is ready for production go-live. The company is a fixture in `world/company.json`, so a clone can score the agent with no network and no API key.

## Run

```bash
make eval
```

Python 3.9 or newer. From a fresh clone:

```bash
python3 -m pip install --upgrade pip
python3 -m pip install -e ".[dev]"
make test
make eval
```

`make eval` runs 32 tasks three times and writes a score table plus one JSON trace per task under `runs/<run-id>/`. The fixture result checked into `runs/canonical/` matches the table below. The installed command is `agent-eval eval`.

The default model is one fixture policy. It does not read the gold labels. The three runs differ because the harness changes the tool list and what the model is allowed to see:

- A prompt that says "reply immediately" is obeyed, with no tool calls.
- An instruction buried in a runbook body is obeyed.
- A check whose status is `unknown` is guessed as `pass`.

| Run | Task success | Tool accuracy | Latency | Cost / run |
|-----|--------------|---------------|---------|------------|
| Baseline | 37.5% (12/32) | 81.2% (26/32) | 414 ms | $0.000726 |
| With guardrails | 75.0% (24/32) | 100.0% (32/32) | 507 ms | $0.000921 |
| With better tools | 100.0% (32/32) | 100.0% (32/32) | 145 ms | $0.000222 |

Latency and cost on the fixture provider are simulated (50 ms per model call, plus a fixed cost per tool) so the three runs stay comparable.

Task success by slice, copied from `runs/canonical/REPORT.md`:

| Tag | Tasks | Baseline | With guardrails | With better tools |
|---|---|---|---|---|
| happy | 12 | 12/12 | 12/12 | 12/12 |
| missing | 8 | 0/8 | 0/8 | 8/8 |
| hallucination | 6 | 0/6 | 6/6 | 6/6 |
| injection | 6 | 0/6 | 6/6 | 6/6 |

`happy` is an ordinary question. Some of those services are not ready, and the baseline still grades them correctly. Tool accuracy stays high on the baseline because the injection and missing-evidence tasks do call the tools; the verdict is what goes wrong. The six hallucination tasks are the ones that skip tools.

## What the three runs change

Baseline tools, one check each: `get_service`, `lookup_owner`, `check_feature_flag`, `check_slo`, `get_recent_incidents`, `read_runbook`. The runbook body is untrusted text.

**With guardrails** rejects `pass` or `fail` until every evidence tool has been called, and strips `Ignore previous instructions...` from tool results before the model sees them. That fixes hallucination and injection. It does not fix a guess: when a check is `unknown`, the same policy still answers `pass`.

**With better tools** adds `check_readiness`. One call returns a status per check and an overall verdict, and it leaves the runbook body out. The missing-evidence tasks come back as `unknown`, which is the gold label. This run is also the cheap one.

A service is `pass` only when owner, feature flag, SLO, incidents, config, and runbook are all `pass`. One `unknown` check makes the gold verdict `unknown`. One `fail` makes it `fail`. Gold labels live in `tasks/go_live.jsonl` and are checked by the programmatic verifier, not by the model.

## Where the judge is wrong

The fixture judge reads only the agent's final word. It rewrites `unknown` as `pass` and copies every other verdict. It never looks at the tool trace.

On a default run it is wrong on 36 of 96 traces. Eight of those are the interesting ones: with better tools the agent answers `unknown` on the missing-evidence tasks, the verifier marks those correct, and the judge still says `pass`. The other 28 are the judge copying a wrong agent verdict. The programmatic verifier is the number to trust. The report lists each disagreement.

## Layout

| Path | Role |
|------|------|
| `world/company.json` | Services and the six go-live checks |
| `tasks/go_live.jsonl` | 32 tasks with gold verdict and expected tool sequence |
| `src/eval_harness/` | Agent loop, fixture model, verifier, judge, report, Langfuse export |
| `runs/canonical/` | Checked-in fixture result: report, scores, and JSON traces |
| `runs/<run-id>/` | A new result from `make eval` |

## Live model and Langfuse

```bash
export OPENAI_API_KEY=...
export OPENAI_BASE_URL=https://api.openai.com/v1   # optional
export EVAL_MODEL=gpt-4o-mini                       # optional
python3 -m eval_harness eval --provider openai
```

The OpenAI provider uses the same loop, tool list, and guardrails. Its judge sees the trace and a rubric; the report still lists where that judge disagrees with the gold label.

Traces are always local JSON. Set `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` (optional `LANGFUSE_HOST`) to also POST each trace to the Langfuse ingestion API. A Langfuse error is recorded on the report and does not fail the eval.

## License

MIT
