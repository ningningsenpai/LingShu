from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from lingshu.errors import LingShuError
from lingshu.gateway import Gateway
from lingshu.orchestrator import Orchestrator
from lingshu.routing import Router
from lingshu.schemas import CallSource, ModelRequest
from lingshu.settings import AppConfig, load_config
from lingshu.storage import Storage
from lingshu.tools import WorkspaceTools

app = typer.Typer(
    name="lingshu",
    help="供 Codex 调用的本地多模型 Gateway。",
    no_args_is_help=True,
)


def _runtime() -> tuple[AppConfig, Storage, Gateway, Orchestrator]:
    config = load_config()
    storage = Storage(config.project_root / "data" / "lingshu.db")
    gateway = Gateway(config, storage)
    orchestrator = Orchestrator(config, storage, gateway)
    return config, storage, gateway, orchestrator


def _print_error(exc: Exception) -> None:
    typer.secho(f"错误：{exc}", fg=typer.colors.RED, err=True)


@app.command()
def doctor(
    live: Annotated[bool, typer.Option("--live", help="执行真实最小请求。")] = False,
    provider: Annotated[
        str | None, typer.Option("--provider", help="只检查指定 Provider。")
    ] = None,
) -> None:
    """检查配置，并可选择执行真实连通测试。"""
    try:
        config, _, gateway, _ = _runtime()
        names = [provider] if provider else list(config.providers)
        unknown = [name for name in names if name not in config.providers]
        if unknown:
            raise LingShuError(f"未知 Provider：{unknown[0]}")
        if live and not config.live_tests_enabled:
            raise LingShuError("真实测试未启用，请先在 .env 中设置 LINGSHU_ENABLE_LIVE_TESTS=true")
        asyncio.run(_doctor_async(config, gateway, names, live))
    except (LingShuError, OSError) as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc


async def _doctor_async(config: AppConfig, gateway: Gateway, names: list[str], live: bool) -> None:
    preferred_aliases = {
        "ark_coding": "glm_fast",
        "deepseek": "default",
        "bailian": "fast",
    }
    for name in names:
        item = config.providers[name]
        configured = item.api_key is not None
        state = "已配置" if configured else "缺少 Key"
        typer.echo(f"{name:<12} {state:<8} {item.base_url}")
        if not live:
            continue
        if not configured:
            typer.echo("  跳过真实请求。")
            continue
        alias = preferred_aliases.get(name) or next(iter(item.models))
        model = item.models[alias]
        response = await gateway.complete(
            name,
            alias,
            ModelRequest(
                task_id=f"doctor-{name}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                model=model.id,
                messages=[{"role": "user", "content": "只回复：OK"}],
                tools=None,
                max_output_tokens=16,
                timeout_seconds=60,
                source=CallSource.DOCTOR,
            ),
        )
        typer.echo(
            f"  连通成功：{response.model}，{response.latency_ms} ms，"
            f"估算费用 ¥{response.estimated_cost_cny:.6f}"
        )


@app.command("run")
def run_task(
    prompt: Annotated[str, typer.Argument(help="要交给辅助模型的任务。")],
    workspace: Annotated[
        Path | None, typer.Option("--workspace", "-w", help="允许模型读取的工作区。")
    ] = None,
    risk: Annotated[str, typer.Option("--risk", help="风险等级：low、normal 或 high。")] = "normal",
    trial: Annotated[
        str | None,
        typer.Option("--trial", help="显式试验路由：deepseek、qwen_coder、qwen_fast。"),
    ] = None,
    provider: Annotated[str | None, typer.Option("--provider", help="显式指定 Provider。")] = None,
    model: Annotated[str | None, typer.Option("--model", help="显式指定模型别名。")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="只显示路由，不调用模型。")] = False,
) -> None:
    """路由并执行一个受监督任务。"""
    try:
        config, _, _, orchestrator = _runtime()
        if risk not in {"low", "normal", "high"}:
            raise LingShuError("risk 必须是 low、normal 或 high")
        target = (workspace or config.project_root).resolve()
        decision = orchestrator.route(
            prompt,
            risk=risk,  # type: ignore[arg-type]
            trial=trial,
            provider=provider,
            model_alias=model,
        )
        typer.echo(f"路由：{decision.provider}/{decision.model_alias}（{decision.rule_name}）")
        if dry_run:
            return
        task = asyncio.run(
            orchestrator.run(
                prompt,
                target,
                risk=risk,  # type: ignore[arg-type]
                trial=trial,
                provider=provider,
                model_alias=model,
            )
        )
        typer.echo(f"任务完成：{task.task_id}")
        typer.echo(f"结果：{task.result_path}")
    except (LingShuError, OSError) as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc


@app.command()
def status(task_id: Annotated[str, typer.Argument(help="任务 ID。")]) -> None:
    """查看任务状态。"""
    try:
        _, storage, _, _ = _runtime()
        task = storage.get_task(task_id)
        if not task:
            raise LingShuError(f"找不到任务：{task_id}")
        for key in (
            "task_id",
            "status",
            "provider",
            "model_alias",
            "workspace",
            "result_path",
            "error",
        ):
            typer.echo(f"{key}: {task.get(key) or '-'}")
    except (LingShuError, OSError) as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc


@app.command()
def report() -> None:
    """生成 Markdown 用量报告。"""
    try:
        config, storage, _, _ = _runtime()
        rows = storage.usage_summary()
        report_root = config.project_root / "data" / "reports"
        report_root.mkdir(parents=True, exist_ok=True)
        path = report_root / f"usage-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
        lines = [
            "# 灵枢模型用量报告",
            "",
            "| Provider | 调用数 | 成功数 | 输入 Token | 缓存 Token | "
            "输出 Token | 估算费用（元） |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        if rows:
            for row in rows:
                lines.append(
                    f"| {row['provider']} | {row['calls']} | {row['successful_calls']} | "
                    f"{row['input_tokens']} | {row['cached_input_tokens']} | "
                    f"{row['output_tokens']} | {row['estimated_cost_cny'] or 0:.6f} |"
                )
        else:
            lines.append("| 暂无调用 | 0 | 0 | 0 | 0 | 0 | 0.000000 |")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        typer.echo(f"报告已生成：{path}")
    except (LingShuError, OSError) as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc


@app.command()
def dashboard(
    host: Annotated[
        str, typer.Option("--host", help="监听地址，仅允许本机回环地址。")
    ] = "127.0.0.1",
    port: Annotated[
        int, typer.Option("--port", min=1, max=65535, help="本机观测台端口。")
    ] = 18765,
) -> None:
    """启动本机模型调用观测台。"""
    if host not in {"127.0.0.1", "localhost"}:
        _print_error(LingShuError("观测台只允许监听本机回环地址"))
        raise typer.Exit(1)
    try:
        import uvicorn

        from lingshu.dashboard import create_app

        config, storage, _, _ = _runtime()
        typer.echo(f"观测台：http://{host}:{port}")
        uvicorn.run(create_app(config, storage), host=host, port=port, log_level="warning")
    except ImportError as exc:
        _print_error(LingShuError("缺少 Dashboard 依赖，请安装项目的 dashboard 可选依赖"))
        raise typer.Exit(1) from exc
    except (LingShuError, OSError) as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc


@app.command("eval")
def run_eval() -> None:
    """运行不产生费用的内部冒烟检查。"""
    try:
        config, _, _, _ = _runtime()
        router = Router(config.routing)
        checks = {
            "常规 Coding": ("实现一个配置加载器", "glm_primary"),
            "快速任务": ("简单摘要这段错误", "glm_fast"),
            "大仓库": ("分析大仓库的跨模块架构", "kimi_context"),
            "高风险": ("执行高风险安全审计", "deepseek_pro"),
        }
        for name, (prompt, expected) in checks.items():
            risk = "high" if name == "高风险" else "normal"
            actual = router.choose(prompt, risk=risk).model_alias  # type: ignore[arg-type]
            if actual != expected:
                raise LingShuError(f"{name} 路由错误：期望 {expected}，实际 {actual}")
        artifact_root = config.project_root / "data" / "eval-artifacts"
        WorkspaceTools(config, config.project_root, artifact_root).list_files()
        typer.echo("内部冒烟检查通过；未调用任何真实模型。")
    except (LingShuError, OSError) as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc


if __name__ == "__main__":
    app()
