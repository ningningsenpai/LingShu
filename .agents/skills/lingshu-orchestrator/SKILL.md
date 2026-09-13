---
name: lingshu-orchestrator
description: 使用当前仓库的 LingShu Gateway 调用方舟 Coding Plan、DeepSeek 官方或阿里云百炼作为受监督的外部子代理。适用于非简单编码、架构分析、疑难排查、独立复核和明确的模型对比；简单确定性任务不应机械调用。
---

# 灵枢外部子代理编排

把 LingShu 视为主 AI 可选择的外部模型辅助通道。主 AI 始终负责权限判断、主要实现、结果
验收和最终交付。

## 调用前判断

适合调用：

- 边界清晰的分析、代码草案、测试设计或局部审查可以独立完成。
- 长上下文、算法边界、高风险变更或疑难问题能从第二模型视角获益。
- 用户明确要求调用、比较或评测灵枢中的模型。

通常不调用：

- 主 AI 可立即完成的简单、确定性修改。
- 外部调用不会明显节省时间或提高质量。
- 完成任务必须发送密钥、`.env`、凭据、运行数据、个人文件或无关内部内容。
- 所需工作区不在 `LINGSHU_ALLOWED_WORKSPACES` 允许范围内。

只向外部模型提供完成子任务所需的最小上下文。绝不读取或发送 `.env`、API Key、访问
令牌、私钥、`.git`、`data/`、依赖目录和常见凭据文件。

## 运行前检查

从仓库根目录运行 LingShu。先确认 CLI 存在并执行不联网的配置检查：

```powershell
$repoRoot = git rev-parse --show-toplevel
$lingshuCli = Join-Path $repoRoot ".venv\Scripts\lingshu.exe"
Test-Path $lingshuCli
& $lingshuCli doctor
```

macOS 或 Linux 的 CLI 路径为 `<仓库根目录>/.venv/bin/lingshu`。

若 CLI 缺失、配置检查失败或工作区越界，应说明具体问题。未经用户要求，不要重装环境、
修改 API Key 或扩大允许目录。`doctor --live` 会发起真实最小请求，不要为每个任务重复执行。

真实任务要求用户已经在 `.env` 中显式设置：

```dotenv
LINGSHU_ENABLE_LIVE_TESTS=true
```

## 选择模型

默认优先使用方舟 Coding Plan：

- 一般分析和常规编码：`ark_coding/glm_primary`
- 快速摘要、定位和简单草稿：`ark_coding/glm_fast`
- 局部代码草拟：`ark_coding/kimi_code`
- 大仓库、跨模块和长上下文：`ark_coding/kimi_context`
- 算法、边界条件和第二意见：`ark_coding/deepseek_flash`
- 高风险或疑难任务：`ark_coding/deepseek_pro`

DeepSeek 官方和百炼只用于明确的试用、比较或独立复核：

- `--trial deepseek`
- `--trial qwen_coder`
- `--trial qwen_fast`

## 发布任务

把请求压缩为一个边界明确的子任务，写清：允许读取的相对路径、期望输出、禁止动作和验收
条件。工作区尽量指向相关仓库或更小的子目录。

```powershell
$repoRoot = git rev-parse --show-toplevel
$lingshuCli = Join-Path $repoRoot ".venv\Scripts\lingshu.exe"
& $lingshuCli run `
  "边界明确的子任务；列明允许路径、输出格式、禁止动作和验收条件" `
  --workspace "."
```

需要指定方舟模型时增加 `--provider ark_coding --model <模型别名>`；需要原生试用通道时
增加对应的 `--trial`。不要使用 `Invoke-Expression`，也不要把未经处理的模型文本拼成
Shell 命令。

外部模型只应输出分析、草稿或统一 diff，或使用受控工具写入任务产物目录；不得让它直接
修改主仓库或执行任意命令。

## 验收与返工

CLI 会输出任务 ID 和结果路径。主 AI 读取结果后必须：

1. 检查事实、路径、需求覆盖、安全边界和遗漏。
2. 对统一 diff 先运行 `git apply --check`；检查失败时不得应用。
3. 应用可接受的改动后，运行与风险相称的单元测试、Ruff、Pyright 和前端检查。
4. 需要返工时，只把精简的验证错误交回同一模型；单个子任务最多再尝试两次。
5. 两次返工仍不合格时，由主 AI 接管，或向用户报告明确阻碍。

模型声称“已完成”不能替代本地验证证据。
