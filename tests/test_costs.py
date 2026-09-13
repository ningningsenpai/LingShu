from lingshu.costs import calculate_cost_cny, estimate_input_tokens
from lingshu.schemas import Usage
from lingshu.settings import ModelConfig


def test_calculate_cny_cost_with_cache() -> None:
    model = ModelConfig(
        id="qwen",
        currency="CNY",
        input_price_per_million=10,
        cached_input_price_per_million=1,
        output_price_per_million=20,
    )
    usage = Usage(input_tokens=1_000_000, cached_input_tokens=400_000, output_tokens=100_000)

    assert calculate_cost_cny(model, usage, 7.2) == 8.4


def test_calculate_usd_cost_converts_to_cny() -> None:
    model = ModelConfig(
        id="deepseek",
        currency="USD",
        input_price_per_million=1,
        output_price_per_million=1,
    )
    usage = Usage(input_tokens=500_000, output_tokens=500_000)

    assert calculate_cost_cny(model, usage, 7.2) == 7.2


def test_estimate_tokens_is_conservative_for_serialized_input() -> None:
    messages = [{"role": "user", "content": "你好 world"}]

    assert estimate_input_tokens(messages) >= len("你好 world")


def test_estimate_tokens_uses_utf8_bytes_for_unicode_safety() -> None:
    messages = [{"role": "user", "content": "😀"}]

    assert estimate_input_tokens(messages) >= len("😀".encode())
