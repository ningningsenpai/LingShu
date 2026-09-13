from __future__ import annotations

import json
from typing import Any

from lingshu.schemas import Usage
from lingshu.settings import ModelConfig


def estimate_input_tokens(
    messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
) -> int:
    serialized = json.dumps({"messages": messages, "tools": tools or []}, ensure_ascii=False)
    return max(1, len(serialized.encode("utf-8")))


def calculate_cost_cny(model: ModelConfig, usage: Usage, usd_cny_rate: float) -> float:
    if model.input_price_per_million is None or model.output_price_per_million is None:
        return 0.0
    cached = min(usage.cached_input_tokens, usage.input_tokens)
    uncached = max(0, usage.input_tokens - cached)
    cached_price = model.cached_input_price_per_million
    input_cost = uncached * model.input_price_per_million
    if cached_price is not None:
        input_cost += cached * cached_price
    else:
        input_cost += cached * model.input_price_per_million
    output_cost = usage.output_tokens * model.output_price_per_million
    cost = (input_cost + output_cost) / 1_000_000
    if model.currency.upper() == "USD":
        cost *= usd_cny_rate
    return round(cost, 8)


def estimate_reservation_cny(
    model: ModelConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    max_output_tokens: int,
    usd_cny_rate: float,
) -> float:
    usage = Usage(
        input_tokens=estimate_input_tokens(messages, tools),
        cached_input_tokens=0,
        output_tokens=max_output_tokens,
    )
    return calculate_cost_cny(model, usage, usd_cny_rate)
