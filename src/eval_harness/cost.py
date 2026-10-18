"""Token cost for the score table.

Prices are a small-model stand-in so every run has a dollar figure without a
billing API. Live calls still use these rates on the token counts the API
returns.
"""

from __future__ import annotations

INPUT_USD_PER_MILLION = 0.15
OUTPUT_USD_PER_MILLION = 0.60


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def cost_usd(prompt_tokens: int, completion_tokens: int) -> float:
    return (
        prompt_tokens * INPUT_USD_PER_MILLION / 1_000_000
        + completion_tokens * OUTPUT_USD_PER_MILLION / 1_000_000
    )
