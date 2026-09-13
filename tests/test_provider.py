import asyncio
import json

import httpx
import pytest

from lingshu.errors import ProviderError
from lingshu.providers.deepseek import DeepSeekProvider
from lingshu.schemas import ModelRequest, ModelResponse


def test_provider_normalizes_openai_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={
                "id": "request-1",
                "model": "deepseek-v4-flash",
                "choices": [
                    {
                        "message": {
                            "content": "完成",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": json.dumps({"path": "README.md"}),
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "prompt_tokens_details": {"cached_tokens": 40},
                },
            },
        )

    async def run() -> ModelResponse:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = DeepSeekProvider("https://api.deepseek.com", "test-key", client)
            return await provider.chat(
                ModelRequest(
                    task_id="task-1",
                    model="deepseek-v4-flash",
                    messages=[{"role": "user", "content": "测试"}],
                )
            )

    response = asyncio.run(run())

    assert response.content == "完成"
    assert response.tool_calls[0].arguments == {"path": "README.md"}
    assert response.usage.cached_input_tokens == 40
    assert response.usage_reported is True


def test_provider_error_redacts_api_key() -> None:
    secret = "super-secret-key"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"无效密钥：{secret}")

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = DeepSeekProvider("https://api.deepseek.com", secret, client)
            await provider.chat(
                ModelRequest(
                    task_id="task-1",
                    model="deepseek-v4-flash",
                    messages=[{"role": "user", "content": "测试"}],
                )
            )

    with pytest.raises(ProviderError) as error:
        asyncio.run(run())

    assert secret not in str(error.value)
    assert "[已隐藏]" in str(error.value)


def test_provider_error_redacts_base_url() -> None:
    base_url = "https://example.com/private-tenant"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text=f"调用 {base_url} 失败")

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = DeepSeekProvider(base_url, "test-key", client)
            await provider.chat(
                ModelRequest(
                    task_id="task-1",
                    model="deepseek-v4-flash",
                    messages=[{"role": "user", "content": "测试"}],
                )
            )

    with pytest.raises(ProviderError) as error:
        asyncio.run(run())

    assert base_url not in str(error.value)


@pytest.mark.parametrize(
    "invalid_field",
    [
        {"usage": []},
        {"tool_calls": {}},
        {"usage": {"prompt_tokens": -1}},
        {"usage": {"prompt_tokens_details": []}},
        {
            "tool_calls": [
                {"function": {"name": "read_file", "arguments": 0}},
            ]
        },
    ],
)
def test_provider_rejects_malformed_success_response(invalid_field: dict[str, object]) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        message: dict[str, object] = {"content": "完成"}
        payload: dict[str, object] = {
            "choices": [{"message": message}],
            "usage": {},
        }
        if "tool_calls" in invalid_field:
            message["tool_calls"] = invalid_field["tool_calls"]
        if "usage" in invalid_field:
            payload["usage"] = invalid_field["usage"]
        return httpx.Response(200, json=payload)

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = DeepSeekProvider("https://api.deepseek.com", "test-key", client)
            await provider.chat(
                ModelRequest(
                    task_id="task-1",
                    model="deepseek-v4-flash",
                    messages=[{"role": "user", "content": "测试"}],
                )
            )

    with pytest.raises(ProviderError, match="无法识别|工具"):
        asyncio.run(run())


def test_provider_generates_unique_missing_tool_call_ids() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {"function": {"name": "list_files", "arguments": "{}"}},
                                {"function": {"name": "list_files", "arguments": "{}"}},
                            ],
                        }
                    }
                ]
            },
        )

    async def run() -> ModelResponse:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = DeepSeekProvider("https://api.deepseek.com", "test-key", client)
            return await provider.chat(
                ModelRequest(
                    task_id="task-1",
                    model="deepseek-v4-flash",
                    messages=[{"role": "user", "content": "测试"}],
                )
            )

    response = asyncio.run(run())

    assert [call.id for call in response.tool_calls] == ["tool-call-1", "tool-call-2"]
    assert response.usage_reported is False
