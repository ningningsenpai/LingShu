from pathlib import Path

import pytest

from lingshu.errors import ConfigError
from lingshu.settings import ModelConfig, ProviderConfig, load_config


def test_remote_base_url_must_use_https(monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("ARK_CODING_BASE_URL", "http://example.com/v1")
    config = load_config(root)

    with pytest.raises(ConfigError, match="HTTPS"):
        _ = config.providers["ark_coding"].base_url


def test_loopback_base_url_can_use_http(monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("ARK_CODING_BASE_URL", "http://127.0.0.1:8000/v1/")
    config = load_config(root)

    assert config.providers["ark_coding"].base_url == "http://127.0.0.1:8000/v1"


def test_budget_environment_must_be_nonnegative(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_PILOT_BUDGET_CNY", "-1")
    provider = ProviderConfig(
        display_name="测试供应商",
        base_url_env="TEST_BASE_URL",
        api_key_env="TEST_API_KEY",
        default_base_url="https://example.com/v1",
        budget_env="DEEPSEEK_PILOT_BUDGET_CNY",
        models={"default": ModelConfig(id="test")},
    )

    with pytest.raises(ConfigError, match="非负"):
        _ = provider.budget_cny


def test_exchange_rate_must_be_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("LINGSHU_USD_CNY_RATE", "0")

    with pytest.raises(ConfigError, match="模型配置"):
        load_config(root)
