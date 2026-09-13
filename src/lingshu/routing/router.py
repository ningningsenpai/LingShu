from __future__ import annotations

from typing import Any

from lingshu.errors import ConfigError
from lingshu.schemas import RiskLevel, RouteDecision


class Router:
    """执行可解释的方舟优先规则路由。"""

    def __init__(self, routing: dict[str, Any]) -> None:
        self.routing = routing

    def choose(
        self,
        prompt: str,
        risk: RiskLevel = "normal",
        trial: str | None = None,
        provider: str | None = None,
        model_alias: str | None = None,
    ) -> RouteDecision:
        if risk not in {"low", "normal", "high"}:
            raise ConfigError("风险等级必须是 low、normal 或 high")
        if provider or model_alias:
            if not provider or not model_alias:
                raise ConfigError("显式路由必须同时提供 Provider 和模型别名")
            return RouteDecision(
                provider=provider,
                model_alias=model_alias,
                rule_name="用户显式指定",
            )

        if trial:
            trial_route = (self.routing.get("trial_routes") or {}).get(trial)
            if not trial_route:
                raise ConfigError(f"未知试验路由：{trial}")
            try:
                return RouteDecision(
                    provider=trial_route["provider"],
                    model_alias=trial_route["model"],
                    rule_name=f"显式试验：{trial}",
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ConfigError(f"试验路由配置无效：{trial}") from exc

        if risk == "high":
            return RouteDecision(
                provider="ark_coding",
                model_alias="deepseek_pro",
                rule_name="高风险任务升级",
            )

        normalized = prompt.casefold()
        if len(prompt) >= 20_000:
            return RouteDecision(
                provider="ark_coding",
                model_alias="kimi_context",
                rule_name="超长任务上下文",
            )

        try:
            for rule in self.routing.get("rules") or []:
                keywords = [
                    str(item).casefold()
                    for item in rule.get("keywords") or []
                    if str(item).strip()
                ]
                if any(keyword in normalized for keyword in keywords):
                    return RouteDecision(
                        provider=rule["provider"],
                        model_alias=rule["model"],
                        rule_name=rule["name"],
                    )
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise ConfigError("rules 路由配置无效") from exc

        default = self.routing.get("default") or {}
        try:
            return RouteDecision(
                provider=default["provider"],
                model_alias=default["model"],
                rule_name="默认方舟主路由",
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigError("路由配置缺少 default.provider 或 default.model") from exc
