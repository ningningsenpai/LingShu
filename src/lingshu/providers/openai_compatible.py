from __future__ import annotations

import json
import time
from typing import Any

import httpx

from lingshu.errors import ProviderError
from lingshu.providers.base import BaseProvider
from lingshu.schemas import ModelRequest, ModelResponse, ToolCall, Usage


class OpenAICompatibleProvider(BaseProvider):
    """通过 Chat Completions 协议访问模型供应商。"""

    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient()

    async def chat(self, request: ModelRequest) -> ModelResponse:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
            "stream": False,
        }
        if request.tools:
            payload["tools"] = request.tools
            if request.tool_choice is not None:
                payload["tool_choice"] = request.tool_choice

        started = time.perf_counter()
        try:
            response = await self._client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
                timeout=request.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = self._safe_response_text(exc.response)
            raise ProviderError(
                f"{self.name} 请求失败，HTTP {exc.response.status_code}：{detail}",
                error_type="HTTP_ERROR",
                response_received=True,
            ) from exc
        except httpx.TimeoutException as exc:
            raise ProviderError(
                f"{self.name} 请求超时", error_type="TIMED_OUT"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"{self.name} 网络请求失败：{type(exc).__name__}",
                error_type="NETWORK_ERROR",
            ) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise TypeError("响应顶层不是对象")
            choices = data["choices"]
            if not isinstance(choices, list) or not choices:
                raise TypeError("choices 不是非空数组")
            choice = choices[0]
            if not isinstance(choice, dict):
                raise TypeError("choice 不是对象")
            message = choice["message"]
            if not isinstance(message, dict):
                raise TypeError("message 不是对象")
            raw_tool_calls = message.get("tool_calls")
            if raw_tool_calls is None:
                raw_tool_calls = []
            if not isinstance(raw_tool_calls, list):
                raise TypeError("tool_calls 不是数组")
            raw_usage = data.get("usage")
            if raw_usage is None:
                raw_usage = {}
            return ModelResponse(
                provider=self.name,
                model=str(data.get("model") or request.model),
                request_id=data.get("id") or response.headers.get("x-request-id"),
                content=self._normalize_content(message.get("content")),
                tool_calls=self._parse_tool_calls(raw_tool_calls),
                usage=self._parse_usage(raw_usage),
                latency_ms=latency_ms,
                finish_reason=choice.get("finish_reason"),
                usage_reported="usage" in data,
            )
        except ProviderError:
            raise
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise ProviderError(
                f"{self.name} 返回了无法识别的响应结构",
                error_type="INVALID_RESPONSE",
                response_received=True,
            ) from exc

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "LingShu-Gateway/0.1",
        }

    async def aclose(self) -> None:
        if self._owns_client and not self._client.is_closed:
            await self._client.aclose()

    def _safe_response_text(self, response: httpx.Response) -> str:
        text = response.text
        for sensitive in (self.api_key, self.base_url):
            if sensitive:
                text = text.replace(sensitive, "[已隐藏]")
        return text[:500] or "供应商未返回错误详情"

    @staticmethod
    def _normalize_content(content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            return "\n".join(parts)
        raise TypeError("content 类型无效")

    def _parse_tool_calls(self, tool_calls: list[Any]) -> list[ToolCall]:
        parsed: list[ToolCall] = []
        seen_ids: set[str] = set()
        for index, item in enumerate(tool_calls, start=1):
            if not isinstance(item, dict):
                raise ProviderError(f"{self.name} 返回了无效的工具调用结构")
            function = item.get("function") or {}
            if not isinstance(function, dict):
                raise ProviderError(f"{self.name} 返回了无效的工具函数结构")
            name = function.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ProviderError(f"{self.name} 返回的工具名称为空")
            raw_arguments = function.get("arguments")
            if raw_arguments is None or raw_arguments == "":
                raw_arguments = "{}"
            try:
                arguments = (
                    raw_arguments if isinstance(raw_arguments, dict) else json.loads(raw_arguments)
                )
            except (TypeError, json.JSONDecodeError) as exc:
                raise ProviderError(f"{self.name} 返回了无效的工具参数 JSON") from exc
            if not isinstance(arguments, dict):
                raise ProviderError(f"{self.name} 返回的工具参数必须是对象")
            raw_id = item.get("id")
            call_id = str(raw_id).strip() if raw_id is not None else ""
            call_id = call_id or f"tool-call-{index}"
            if call_id in seen_ids:
                raise ProviderError(f"{self.name} 返回了重复的工具调用 ID")
            seen_ids.add(call_id)
            parsed.append(
                ToolCall(
                    id=call_id,
                    name=name.strip(),
                    arguments=arguments,
                )
            )
        return parsed

    @staticmethod
    def _parse_usage(usage: Any) -> Usage:
        if not isinstance(usage, dict):
            raise TypeError("usage 不是对象")
        details = usage.get("prompt_tokens_details")
        if details is None:
            details = {}
        if not isinstance(details, dict):
            raise TypeError("prompt_tokens_details 不是对象")
        cached = details.get("cached_tokens", usage.get("prompt_cache_hit_tokens", 0))
        return Usage(
            input_tokens=OpenAICompatibleProvider._parse_token_count(
                usage.get("prompt_tokens", usage.get("input_tokens", 0))
            ),
            cached_input_tokens=OpenAICompatibleProvider._parse_token_count(cached),
            output_tokens=OpenAICompatibleProvider._parse_token_count(
                usage.get("completion_tokens", usage.get("output_tokens", 0))
            ),
        )

    @staticmethod
    def _parse_token_count(value: Any) -> int:
        if value is None or value == "":
            return 0
        if isinstance(value, bool):
            raise TypeError("Token 数量不能是布尔值")
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        raise TypeError("Token 数量不是整数")
