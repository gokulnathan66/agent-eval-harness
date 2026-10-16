# agent-eval-harness

Offline eval harness for one tool-using agent.

**Status:** scaffold (2026-10-16). The score table and tasks are not implemented yet.

## What this will prove

A stranger can clone the repo, run `make eval`, and see a score table plus traces.

- One tool-using agent for enterprise go-live or production-readiness checks
- A fixed eval set of at least 30 tasks with gold outcomes (pass/fail and expected tool sequence)
- Metrics: tool-call correctness, task success, latency, cost per run, plus hallucination and injection cases
- An LLM-as-judge and a programmatic verifier, with a note on where the judge is wrong
- Traces in Langfuse or local JSON

## README result (when done)

| Run | Task success | Tool accuracy | Latency | Cost / run |
|-----|--------------|---------------|---------|------------|
| Baseline | — | — | — | — |
| With guardrails | — | — | — | — |
| With better tools | — | — | — | — |

## Run

Not runnable yet.

## License

MIT
