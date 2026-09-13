from pathlib import Path
from typing import cast

import pytest

from lingshu.errors import ConfigError
from lingshu.routing import Router
from lingshu.schemas import RiskLevel
from lingshu.settings import load_config


@pytest.fixture
def router(monkeypatch: pytest.MonkeyPatch) -> Router:
    monkeypatch.delenv("LINGSHU_ALLOWED_WORKSPACES", raising=False)
    root = Path(__file__).resolve().parents[1]
    return Router(load_config(root).routing)


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("实现一个普通配置加载器", "glm_primary"),
        ("简单摘要错误日志", "glm_fast"),
        ("完成一个局部实现", "kimi_code"),
        ("分析大仓库的跨模块架构", "kimi_context"),
        ("复核这个算法的边界条件", "deepseek_flash"),
    ],
)
def test_default_routes_stay_in_ark(router: Router, prompt: str, expected: str) -> None:
    decision = router.choose(prompt)

    assert decision.provider == "ark_coding"
    assert decision.model_alias == expected


def test_high_risk_uses_deepseek_pro_in_ark(router: Router) -> None:
    decision = router.choose("检查支付逻辑", risk="high")

    assert decision.provider == "ark_coding"
    assert decision.model_alias == "deepseek_pro"


def test_trial_route_must_be_explicit(router: Router) -> None:
    decision = router.choose("普通任务", trial="qwen_fast")

    assert decision.provider == "bailian"
    assert decision.model_alias == "fast"


def test_explicit_route_requires_provider_and_model(router: Router) -> None:
    with pytest.raises(ConfigError, match="同时提供"):
        router.choose("任务", provider="bailian")


def test_paid_providers_have_no_local_budget() -> None:
    root = Path(__file__).resolve().parents[1]
    config = load_config(root)

    assert config.providers["deepseek"].budget_cny is None
    assert config.providers["bailian"].budget_cny is None


def test_invalid_risk_is_rejected(router: Router) -> None:
    with pytest.raises(ConfigError, match="风险等级"):
        router.choose("任务", risk=cast(RiskLevel, "unknown"))


def test_malformed_trial_route_has_config_error() -> None:
    router = Router({"trial_routes": {"broken": {"provider": "deepseek"}}})

    with pytest.raises(ConfigError, match="试验路由配置无效"):
        router.choose("任务", trial="broken")
