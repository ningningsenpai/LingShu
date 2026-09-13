import asyncio
from pathlib import Path
from typing import Any

import pytest

from lingshu.errors import ConfigError, ProviderError
from lingshu.orchestrator import Orchestrator
from lingshu.schemas import ModelResponse, TaskStatus
from lingshu.settings import load_config
from lingshu.storage import Storage


class EmptyGateway:
    async def complete(self, *_args: object, **_kwargs: object) -> ModelResponse:
        return ModelResponse(provider="ark_coding", model="glm-5.3", content="  ")


class CancelledGateway:
    async def complete(self, *_args: object, **_kwargs: object) -> ModelResponse:
        raise asyncio.CancelledError


def _orchestrator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gateway: Any,
) -> tuple[Orchestrator, Storage, Path]:
    root = Path(__file__).resolve().parents[1]
    config = load_config(root).model_copy(
        update={
            "project_root": tmp_path,
            "allowed_workspaces": [tmp_path],
            "live_tests_enabled": True,
        }
    )
    storage = Storage(tmp_path / "test.db")
    monkeypatch.setattr(
        Orchestrator, "_new_task_id", staticmethod(lambda: "task-fixed")
    )
    return Orchestrator(config, storage, gateway), storage, tmp_path


def test_empty_result_marks_task_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    orchestrator, storage, workspace = _orchestrator(tmp_path, monkeypatch, EmptyGateway())

    with pytest.raises(ProviderError, match="可用文本"):
        asyncio.run(
            orchestrator.run(
                "检查代码",
                workspace,
                provider="ark_coding",
                model_alias="glm_primary",
            )
        )

    task = storage.get_task("task-fixed")
    assert task is not None
    assert task["status"] == TaskStatus.FAILED.value
    assert task["result_path"] is None


def test_cancellation_marks_task_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    orchestrator, storage, workspace = _orchestrator(
        tmp_path, monkeypatch, CancelledGateway()
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            orchestrator.run(
                "检查代码",
                workspace,
                provider="ark_coding",
                model_alias="glm_primary",
            )
        )

    task = storage.get_task("task-fixed")
    assert task is not None
    assert task["status"] == TaskStatus.FAILED.value
    assert task["error"] == "任务已取消"


def test_pre_dispatch_failure_is_visible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    orchestrator, storage, workspace = _orchestrator(tmp_path, monkeypatch, EmptyGateway())

    with pytest.raises(ConfigError, match="路由结果无效"):
        asyncio.run(
            orchestrator.run(
                "检查代码",
                workspace,
                provider="missing",
                model_alias="missing",
            )
        )

    task = storage.get_task("task-fixed")
    assert task is not None
    assert task["status"] == TaskStatus.FAILED.value
    assert task["failure_phase"] == "ROUTING"
    assert task["provider"] is None
    with storage._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM calls").fetchone()[0] == 0
