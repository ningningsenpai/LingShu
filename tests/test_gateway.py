import asyncio
from collections import deque
from pathlib import Path

import pytest

from lingshu.errors import ConfigError, ProviderError
from lingshu.gateway import Gateway
from lingshu.providers.base import BaseProvider
from lingshu.schemas import CallSource, ModelRequest, ModelResponse, ToolCall, Usage
from lingshu.settings import load_config
from lingshu.storage import Storage


class FakeProvider(BaseProvider):
    name = "ark_coding"

    def __init__(self, responses: deque[ModelResponse]) -> None:
        self.responses = responses
        self.requests: list[ModelRequest] = []
        self.closed = False

    async def chat(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return self.responses.popleft()

    async def aclose(self) -> None:
        self.closed = True


class FakeToolExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def execute(self, name: str, arguments: dict[str, str]) -> str:
        self.calls.append((name, arguments))
        return '{"content":"测试内容"}'


class HangingProvider(BaseProvider):
    name = "deepseek"

    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def chat(self, request: ModelRequest) -> ModelResponse:
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("不可达")


def test_gateway_executes_tool_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("ARK_CODING_API_KEY", "test")
    config = load_config(root)
    responses = deque(
        [
            ModelResponse(
                provider="ark_coding",
                model="glm-5.3",
                tool_calls=[ToolCall(id="call-1", name="read_file", arguments={"path": "a.py"})],
                usage=Usage(input_tokens=10, output_tokens=5),
            ),
            ModelResponse(
                provider="ark_coding",
                model="glm-5.3",
                content="审查完成",
                usage=Usage(input_tokens=20, output_tokens=5),
            ),
        ]
    )
    provider = FakeProvider(responses)
    gateway = Gateway(
        config,
        Storage(tmp_path / "test.db"),
        factories={"ark_coding": lambda _url, _key: provider},
    )
    tools = FakeToolExecutor()

    result = asyncio.run(
        gateway.complete(
            "ark_coding",
            "glm_primary",
            ModelRequest(
                task_id="task-1",
                model="glm-5.3",
                messages=[{"role": "user", "content": "读取文件"}],
                tools=[{"type": "function", "function": {"name": "read_file"}}],
            ),
            tools,
        )
    )

    assert result.content == "审查完成"
    assert tools.calls == [("read_file", {"path": "a.py"})]
    assert provider.closed is True
    assert provider.requests[1].messages[-1]["role"] == "tool"
    arguments = provider.requests[1].messages[-2]["tool_calls"][0]["function"]["arguments"]
    assert arguments == '{"path": "a.py"}'


def test_gateway_disables_tools_for_final_synthesis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("ARK_CODING_API_KEY", "test")
    config = load_config(root)
    config.policies.max_tool_rounds = 1
    responses = deque(
        [
            ModelResponse(
                provider="ark_coding",
                model="glm-5.3",
                tool_calls=[ToolCall(id="call-1", name="read_file", arguments={"path": "a.py"})],
            ),
            ModelResponse(provider="ark_coding", model="glm-5.3", content="最终结果"),
        ]
    )
    provider = FakeProvider(responses)
    gateway = Gateway(
        config,
        Storage(tmp_path / "test.db"),
        factories={"ark_coding": lambda _url, _key: provider},
    )

    result = asyncio.run(
        gateway.complete(
            "ark_coding",
            "glm_primary",
            ModelRequest(
                task_id="task-final",
                model="glm-5.3",
                messages=[{"role": "user", "content": "读取文件"}],
                tools=[{"type": "function", "function": {"name": "read_file"}}],
            ),
            FakeToolExecutor(),
        )
    )

    assert result.content == "最终结果"
    assert provider.requests[1].tools is None
    assert "直接给出最终文本结果" in provider.requests[1].messages[-1]["content"]


def test_gateway_rejects_empty_final_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("ARK_CODING_API_KEY", "test")
    config = load_config(root)
    provider = FakeProvider(
        deque([ModelResponse(provider="ark_coding", model="glm-5.3", content="  ")])
    )
    gateway = Gateway(
        config,
        Storage(tmp_path / "test.db"),
        factories={"ark_coding": lambda _url, _key: provider},
    )

    with pytest.raises(ProviderError, match="可用文本"):
        asyncio.run(
            gateway.complete(
                "ark_coding",
                "glm_primary",
                ModelRequest(
                    task_id="task-empty",
                    model="glm-5.3",
                    messages=[{"role": "user", "content": "测试"}],
                ),
            )
        )


def test_budgeted_provider_requires_pricing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("ARK_CODING_API_KEY", "test")
    config = load_config(root)
    config.providers["ark_coding"].default_budget_cny = 10
    provider = FakeProvider(
        deque([ModelResponse(provider="ark_coding", model="glm-5.3", content="完成")])
    )
    gateway = Gateway(
        config,
        Storage(tmp_path / "test.db"),
        factories={"ark_coding": lambda _url, _key: provider},
    )

    with pytest.raises(ConfigError, match="缺少计费价格"):
        asyncio.run(
            gateway.complete(
                "ark_coding",
                "glm_primary",
                ModelRequest(
                    task_id="task-price",
                    model="glm-5.3",
                    messages=[{"role": "user", "content": "测试"}],
                ),
            )
        )


def test_gateway_without_local_budget_does_not_create_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")
    config = load_config(root)
    provider = FakeProvider(
        deque([ModelResponse(provider="deepseek", model="deepseek-v4-flash", content="完成")])
    )
    storage = Storage(tmp_path / "test.db")
    gateway = Gateway(
        config,
        storage,
        factories={"deepseek": lambda _url, _key: provider},
    )

    result = asyncio.run(
        gateway.complete(
            "deepseek",
            "default",
            ModelRequest(
                task_id="task-no-budget",
                model="deepseek-v4-flash",
                messages=[{"role": "user", "content": "测试"}],
            ),
        )
    )

    with storage._connect() as connection:
        budget_count = connection.execute("SELECT COUNT(*) FROM budget_events").fetchone()[0]
        call = connection.execute(
            "SELECT state, model_alias, pricing_mode FROM calls"
        ).fetchone()
    assert result.content == "完成"
    assert budget_count == 0
    assert tuple(call) == ("SUCCEEDED", "default", "METERED")


def test_doctor_call_is_isolated_from_task_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("ARK_CODING_API_KEY", "test")
    config = load_config(root)
    provider = FakeProvider(
        deque([ModelResponse(provider="ark_coding", model="glm-5.3", content="正常")])
    )
    storage = Storage(tmp_path / "test.db")
    gateway = Gateway(
        config,
        storage,
        factories={"ark_coding": lambda _url, _key: provider},
    )

    asyncio.run(
        gateway.complete(
            "ark_coding",
            "glm_primary",
            ModelRequest(
                task_id="doctor-check-1",
                model="glm-5.3",
                messages=[{"role": "user", "content": "连通检查"}],
                source=CallSource.DOCTOR,
            ),
        )
    )

    with storage._connect() as connection:
        call = connection.execute(
            "SELECT task_id, correlation_id, source, state FROM calls"
        ).fetchone()
    assert tuple(call) == (None, "doctor-check-1", "DOCTOR", "SUCCEEDED")


def test_gateway_rejects_tool_call_without_executor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("ARK_CODING_API_KEY", "test")
    config = load_config(root)
    provider = FakeProvider(
        deque(
            [
                ModelResponse(
                    provider="ark_coding",
                    model="glm-5.3",
                    tool_calls=[ToolCall(id="call-1", name="read_file")],
                )
            ]
        )
    )
    gateway = Gateway(
        config,
        Storage(tmp_path / "test.db"),
        factories={"ark_coding": lambda _url, _key: provider},
    )

    with pytest.raises(ProviderError, match="工具执行器"):
        asyncio.run(
            gateway.complete(
                "ark_coding",
                "glm_primary",
                ModelRequest(
                    task_id="task-no-tools",
                    model="glm-5.3",
                    messages=[{"role": "user", "content": "测试"}],
                ),
            )
        )


def test_gateway_does_not_execute_tool_after_call_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("ARK_CODING_API_KEY", "test")
    config = load_config(root)
    config.policies.max_calls_per_task = 1
    provider = FakeProvider(
        deque(
            [
                ModelResponse(
                    provider="ark_coding",
                    model="glm-5.3",
                    tool_calls=[ToolCall(id="call-1", name="read_file")],
                )
            ]
        )
    )
    tools = FakeToolExecutor()
    gateway = Gateway(
        config,
        Storage(tmp_path / "test.db"),
        factories={"ark_coding": lambda _url, _key: provider},
    )

    with pytest.raises(ProviderError, match="调用次数"):
        asyncio.run(
            gateway.complete(
                "ark_coding",
                "glm_primary",
                ModelRequest(
                    task_id="task-limit",
                    model="glm-5.3",
                    messages=[{"role": "user", "content": "测试"}],
                    tools=[{"type": "function", "function": {"name": "read_file"}}],
                ),
                tools,
            )
        )
    assert tools.calls == []


def test_gateway_timeout_releases_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")
    config = load_config(root)
    config.providers["deepseek"].default_budget_cny = 10
    provider = HangingProvider()
    storage = Storage(tmp_path / "test.db")
    gateway = Gateway(
        config,
        storage,
        factories={"deepseek": lambda _url, _key: provider},
    )

    with pytest.raises(ProviderError, match="超时"):
        asyncio.run(
            gateway.complete(
                "deepseek",
                "default",
                ModelRequest(
                    task_id="task-timeout",
                    model="deepseek-v4-flash",
                    messages=[{"role": "user", "content": "测试"}],
                    timeout_seconds=0.01,
                ),
            )
        )

    with storage._connect() as connection:
        state = connection.execute("SELECT state FROM budget_events").fetchone()[0]
        call = connection.execute(
            "SELECT state, error_type, duration_ms FROM calls"
        ).fetchone()
    assert state == "released"
    assert call[0] == "TIMED_OUT"
    assert call[1] == "TIMED_OUT"
    assert call[2] >= 1


def test_gateway_cancellation_releases_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")
    config = load_config(root)
    config.providers["deepseek"].default_budget_cny = 10
    provider = HangingProvider()
    storage = Storage(tmp_path / "test.db")
    gateway = Gateway(
        config,
        storage,
        factories={"deepseek": lambda _url, _key: provider},
    )

    async def run() -> None:
        task = asyncio.create_task(
            gateway.complete(
                "deepseek",
                "default",
                ModelRequest(
                    task_id="task-cancel",
                    model="deepseek-v4-flash",
                    messages=[{"role": "user", "content": "测试"}],
                ),
            )
        )
        await provider.started.wait()
        with storage._connect() as connection:
            call_state = connection.execute("SELECT state FROM calls").fetchone()[0]
        assert call_state == "ATTEMPTING"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())

    with storage._connect() as connection:
        state = connection.execute("SELECT state FROM budget_events").fetchone()[0]
        call = connection.execute("SELECT state, error_type FROM calls").fetchone()
    assert state == "released"
    assert tuple(call) == ("CANCELLED", "CANCELLED")
