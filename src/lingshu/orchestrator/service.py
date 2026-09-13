from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from pathlib import Path

from lingshu.errors import ConfigError, ProviderError
from lingshu.gateway import Gateway
from lingshu.routing import Router
from lingshu.schemas import ModelRequest, RiskLevel, RouteDecision, TaskRecord, TaskStatus
from lingshu.settings import AppConfig
from lingshu.storage import Storage
from lingshu.tools import WorkspaceTools


class Orchestrator:
    """执行一次受 Codex 监督的辅助模型任务。"""

    def __init__(self, config: AppConfig, storage: Storage, gateway: Gateway) -> None:
        self.config = config
        self.storage = storage
        self.gateway = gateway
        self.router = Router(config.routing)

    def route(
        self,
        prompt: str,
        risk: RiskLevel = "normal",
        trial: str | None = None,
        provider: str | None = None,
        model_alias: str | None = None,
    ) -> RouteDecision:
        decision = self.router.choose(prompt, risk, trial, provider, model_alias)
        provider_config = self.config.providers.get(decision.provider)
        if provider_config is None or decision.model_alias not in provider_config.models:
            raise ConfigError(f"路由结果无效：{decision.provider}/{decision.model_alias}")
        return decision

    async def run(
        self,
        prompt: str,
        workspace: Path,
        risk: RiskLevel = "normal",
        trial: str | None = None,
        provider: str | None = None,
        model_alias: str | None = None,
    ) -> TaskRecord:
        task_id = self._new_task_id()
        task = TaskRecord(
            task_id=task_id,
            status=TaskStatus.RECEIVED,
            prompt=prompt,
            workspace=workspace.resolve(),
            risk=risk,
        )
        self.storage.create_task(task)
        task_root = self.config.project_root / "data" / "tasks" / task_id
        artifact_root = task_root / "artifacts"
        failure_phase = "CONFIG"
        try:
            if not self.config.live_tests_enabled:
                raise ConfigError(
                    "真实模型调用当前关闭；请在 .env 中设置 LINGSHU_ENABLE_LIVE_TESTS=true"
                )
            failure_phase = "ROUTING"
            decision = self.route(prompt, risk, trial, provider, model_alias)
            self.storage.update_task_route(
                task_id, decision.provider, decision.model_alias, decision.rule_name
            )
            failure_phase = "PRE_DISPATCH"
            tools = WorkspaceTools(self.config, workspace, artifact_root)
            provider_config = self.config.providers[decision.provider]
            model = provider_config.models[decision.model_alias]
            request = ModelRequest(
                task_id=task_id,
                model=model.id,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是灵枢的辅助 Coding 模型。只处理用户明确要求的任务。"
                            "可使用受控工具读取工作区，但不能直接修改主仓库或执行命令。"
                            "需要改代码时，请输出统一 diff，或使用 propose_patch 保存补丁建议。"
                            "最终用中文给出简洁结果、风险和建议验证项，不输出隐藏思维链。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                tools=tools.schemas,
                max_output_tokens=self.config.policies.max_output_tokens,
                timeout_seconds=self.config.policies.request_timeout_seconds,
            )
            self.storage.update_task(task_id, TaskStatus.DISPATCHED)
            failure_phase = "DISPATCH"
            response = await self.gateway.complete(
                decision.provider, decision.model_alias, request, tools
            )
            if not response.content.strip():
                raise ProviderError("模型未返回可用文本内容")
            task_root.mkdir(parents=True, exist_ok=True)
            result_path = task_root / "result.md"
            result_path.write_text(response.content, encoding="utf-8", newline="\n")
            self.storage.update_task(task_id, TaskStatus.ACCEPTED, result_path=result_path)
            return TaskRecord(
                **task.model_dump(
                    exclude={"status", "provider", "model_alias", "route_rule", "result_path"}
                ),
                status=TaskStatus.ACCEPTED,
                provider=decision.provider,
                model_alias=decision.model_alias,
                route_rule=decision.rule_name,
                result_path=result_path,
            )
        except asyncio.CancelledError:
            self.storage.update_task(
                task_id,
                TaskStatus.FAILED,
                error="任务已取消",
                failure_phase=failure_phase,
            )
            raise
        except Exception as exc:
            self.storage.update_task(
                task_id,
                TaskStatus.FAILED,
                error=str(exc),
                failure_phase=failure_phase,
            )
            raise

    @staticmethod
    def _new_task_id() -> str:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return f"task-{timestamp}-{uuid.uuid4().hex[:8]}"
