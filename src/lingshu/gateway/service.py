from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Callable
from typing import Any

from lingshu.costs import calculate_cost_cny, estimate_reservation_cny
from lingshu.errors import ConfigError, ProviderError, StorageError
from lingshu.providers import ArkCodingProvider, BailianProvider, DeepSeekProvider
from lingshu.providers.base import BaseProvider
from lingshu.schemas import ModelRequest, ModelResponse
from lingshu.settings import AppConfig, ModelConfig, ProviderConfig
from lingshu.storage import Storage

ProviderFactory = Callable[[str, str], BaseProvider]


class Gateway:
    """统一处理模型解析、预算预留、调用记录和工具循环。"""

    def __init__(
        self,
        config: AppConfig,
        storage: Storage,
        factories: dict[str, ProviderFactory] | None = None,
    ) -> None:
        self.config = config
        self.storage = storage
        self.factories = factories or {
            "ark_coding": lambda url, key: ArkCodingProvider(url, key),
            "deepseek": lambda url, key: DeepSeekProvider(url, key),
            "bailian": lambda url, key: BailianProvider(url, key),
        }

    async def complete(
        self,
        provider_name: str,
        model_alias: str,
        request: ModelRequest,
        tool_executor: Any | None = None,
    ) -> ModelResponse:
        provider_config, model_config = self._resolve(provider_name, model_alias)
        if not provider_config.api_key:
            raise ConfigError(
                f"{provider_config.display_name} 尚未配置 {provider_config.api_key_env}"
            )
        provider = self._create_provider(provider_name, provider_config)
        try:
            return await self._complete_with_provider(
                provider_name,
                provider_config,
                model_config,
                provider,
                request,
                tool_executor,
            )
        finally:
            await provider.aclose()

    async def _complete_with_provider(
        self,
        provider_name: str,
        provider_config: ProviderConfig,
        model_config: ModelConfig,
        provider: BaseProvider,
        request: ModelRequest,
        tool_executor: Any | None,
    ) -> ModelResponse:
        messages = list(request.messages)

        tool_rounds = 0
        calls = 0
        while calls < self.config.policies.max_calls_per_task:
            can_use_tools = (
                tool_executor is not None
                and bool(request.tools)
                and tool_rounds < self.config.policies.max_tool_rounds
                and calls + 1 < self.config.policies.max_calls_per_task
            )
            current_messages = messages
            if request.tools and not can_use_tools:
                current_messages = [
                    *messages,
                    {
                        "role": "user",
                        "content": "工具调用额度已用尽，请根据已有信息直接给出最终文本结果。",
                    },
                ]
            current_request = request.model_copy(
                update={
                    "model": model_config.id,
                    "messages": current_messages,
                    "tools": request.tools if can_use_tools else None,
                    "tool_choice": request.tool_choice if can_use_tools else None,
                }
            )
            response = await self._call_once(
                provider_name, provider_config, model_config, provider, current_request
            )
            calls += 1
            if not response.tool_calls:
                if not response.content.strip():
                    raise ProviderError("模型未返回可用文本内容")
                return response
            if tool_executor is None:
                raise ProviderError("模型请求了工具调用，但当前未提供工具执行器")
            if not request.tools:
                raise ProviderError("模型返回了请求中未声明的工具调用")
            if tool_rounds >= self.config.policies.max_tool_rounds:
                raise ProviderError("模型工具调用轮次超过安全上限")
            if calls >= self.config.policies.max_calls_per_task:
                raise ProviderError("模型调用次数达到单任务安全上限，无法继续工具循环")

            messages.append(
                {
                    "role": "assistant",
                    "content": response.content,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(call.arguments, ensure_ascii=False),
                            },
                        }
                        for call in response.tool_calls
                    ],
                }
            )
            for call in response.tool_calls:
                result = tool_executor.execute(call.name, call.arguments)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": result,
                    }
                )
            tool_rounds += 1

        raise ProviderError("模型调用次数超过单任务安全上限")

    async def _call_once(
        self,
        provider_name: str,
        provider_config: ProviderConfig,
        model_config: ModelConfig,
        provider: BaseProvider,
        request: ModelRequest,
    ) -> ModelResponse:
        budget_limit = provider_config.budget_cny
        if budget_limit is not None and (
            model_config.input_price_per_million is None
            or model_config.output_price_per_million is None
        ):
            raise ConfigError(
                f"{provider_config.display_name}/{model_config.id} 缺少计费价格，"
                "不能执行预算受控调用"
            )
        reservation_amount = estimate_reservation_cny(
            model=model_config,
            messages=request.messages,
            tools=request.tools,
            max_output_tokens=request.max_output_tokens,
            usd_cny_rate=self.config.usd_cny_rate,
        )
        pricing_version = self._pricing_config_version(model_config)
        call_id, reservation_id = self.storage.begin_call_and_reserve(
            task_id=request.task_id,
            source=request.source,
            provider=provider_name,
            model=model_config.id,
            model_alias=self._model_alias(provider_config, model_config),
            reservation_amount_cny=reservation_amount,
            budget_limit_cny=budget_limit,
            model_config=model_config,
            usd_cny_rate=self.config.usd_cny_rate,
            pricing_config_version=pricing_version,
        )
        started = time.perf_counter()
        try:
            response = await asyncio.wait_for(
                provider.chat(request), timeout=request.timeout_seconds
            )
        except TimeoutError as exc:
            error = ProviderError(
                f"{provider_name} 请求超时", error_type="TIMED_OUT"
            )
            self._finish_failed_call(call_id, reservation_id, error, started)
            raise error from exc
        except asyncio.CancelledError as exc:
            self._finish_failed_call(call_id, reservation_id, exc, started)
            raise
        except Exception as exc:
            self._finish_failed_call(call_id, reservation_id, exc, started)
            raise

        response.estimated_cost_cny = calculate_cost_cny(
            model_config, response.usage, self.config.usd_cny_rate
        )
        try:
            self.storage.complete_call(
                call_id=call_id,
                reservation_id=reservation_id,
                response=response,
                duration_ms=self._duration_ms(started),
            )
        except Exception as exc:
            raise StorageError("模型调用成功，但本地预算结算或调用记录失败") from exc
        return response

    def _finish_failed_call(
        self,
        call_id: str,
        reservation_id: str | None,
        error: BaseException,
        started: float,
    ) -> None:
        """原子更新预算与失败调用，同时保留原始异常。"""
        error_text = str(error) or (
            "请求已取消" if isinstance(error, asyncio.CancelledError) else type(error).__name__
        )
        if isinstance(error, asyncio.CancelledError):
            state = "CANCELLED"
            error_type = "CANCELLED"
        elif isinstance(error, ProviderError):
            error_type = error.error_type
            state = (
                error_type
                if error_type
                in {"HTTP_ERROR", "INVALID_RESPONSE", "TIMED_OUT", "NETWORK_ERROR"}
                else "FAILED"
            )
        else:
            state = "FAILED"
            error_type = type(error).__name__
        try:
            self.storage.fail_call(
                call_id=call_id,
                reservation_id=reservation_id,
                state=state,
                error_type=error_type,
                error=error_text,
                duration_ms=self._duration_ms(started),
            )
        except Exception as cleanup_error:
            error.add_note(f"更新失败调用与预算状态失败：{cleanup_error}")

    @staticmethod
    def _duration_ms(started: float) -> int:
        return max(1, int((time.perf_counter() - started) * 1000))

    @staticmethod
    def _pricing_config_version(model: ModelConfig) -> str:
        snapshot = "|".join(
            str(value)
            for value in (
                model.currency,
                model.pricing_mode,
                model.input_price_per_million,
                model.cached_input_price_per_million,
                model.output_price_per_million,
            )
        )
        return hashlib.sha256(snapshot.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _model_alias(provider: ProviderConfig, model: ModelConfig) -> str:
        for alias, candidate in provider.models.items():
            if candidate is model:
                return alias
        raise ConfigError(f"找不到模型 {model.id} 的配置别名")

    def _resolve(self, provider_name: str, model_alias: str) -> tuple[ProviderConfig, ModelConfig]:
        provider = self.config.providers.get(provider_name)
        if provider is None:
            raise ConfigError(f"未知 Provider：{provider_name}")
        model = provider.models.get(model_alias)
        if model is None:
            raise ConfigError(f"{provider.display_name} 不存在模型别名：{model_alias}")
        return provider, model

    def _create_provider(self, provider_name: str, provider_config: ProviderConfig) -> BaseProvider:
        factory = self.factories.get(provider_name)
        if factory is None:
            raise ConfigError(f"未注册 Provider 工厂：{provider_name}")
        api_key = provider_config.api_key
        if api_key is None:
            raise ConfigError(f"{provider_config.display_name} API Key 未配置")
        return factory(provider_config.base_url, api_key)
