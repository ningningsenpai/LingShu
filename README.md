# 灵枢（LingShu）

一个由主 AI 监督、在本机运行的多模型子代理网关。灵枢把方舟 Coding Plan、
DeepSeek 官方 API 与阿里云百炼统一到同一套任务路由、受控工作区和用量观测流程中，
适合个人开发者在一个项目里调用不同模型协助分析、代码草拟与交叉复核。

> 当前为个人使用的早期版本。它不是在线多租户服务，也不提供账户系统；观测台仅允许
> 监听本机回环地址。

## 功能

- **多 Provider 路由**：默认使用方舟 Coding Plan，支持显式试用 DeepSeek 官方与阿里云百炼。
- **受监督的子代理**：外部模型只读取允许的工作区，并把结果或补丁建议写入独立任务目录。
- **本机观测台**：查看任务历史、调用状态、每日调用次数，以及输入、缓存命中、输出 Token。
- **安全默认值**：`.env`、运行数据、依赖目录与常见凭据文件不会进入 Git，也不会暴露给子代理。
- **可审计记录**：任务、模型、状态、延迟和 Token 用量保存在本机 SQLite 数据库中。

## 快速开始

### 1. 准备环境

- Python 3.11 或更高版本
- Git
- Node.js 仅在修改观测台前端时需要

```console
git clone git@github.com:ningningsenpai/LingShu.git
cd LingShu
python -m venv .venv
```

Windows PowerShell：

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dashboard]"
Copy-Item .env.example .env
```

macOS 或 Linux：

```bash
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -e '.[dashboard]'
cp .env.example .env
```

### 2. 配置 API Key

只在本机 `.env` 中填写需要使用的平台密钥。至少配置一个 Provider；不要把真实密钥写入
`.env.example`、源码、Issue、日志或聊天内容。

| 平台 | 环境变量 | 获取入口 | 默认用途 |
| --- | --- | --- | --- |
| 方舟 Coding Plan | `ARK_CODING_API_KEY` | [Coding Plan 官方文档](https://www.volcengine.com/docs/82379/2165245?lang=zh) | 默认主通道 |
| DeepSeek 官方 | `DEEPSEEK_API_KEY` | [DeepSeek API Key](https://platform.deepseek.com/api_keys) · [API 文档](https://api-docs.deepseek.com/) | 显式试用或对比 |
| 阿里云百炼 | `BAILIAN_API_KEY` | [百炼 API Key 官方说明](https://help.aliyun.com/zh/model-studio/get-api-key) | 显式试用或对比 |

百炼的 API Key、Base URL 和模型存在地域差异。示例默认使用华北 2（北京）的 OpenAI
兼容端点；若账号或模型位于其他地域，请同时修改 `.env` 中的 `BAILIAN_BASE_URL`。

按需调整其余配置：

```dotenv
LINGSHU_ENABLE_LIVE_TESTS=false
LINGSHU_ALLOWED_WORKSPACES=.
```

- `LINGSHU_ENABLE_LIVE_TESTS`：设为 `true` 后才允许真实连通测试和模型任务。
- `LINGSHU_ALLOWED_WORKSPACES`：分号分隔的允许目录；建议只授权当前任务真正需要的最小范围。

### 3. 本地检查与首次调用

以下命令只检查配置和路由，不调用真实模型：

```powershell
.\.venv\Scripts\lingshu.exe doctor
.\.venv\Scripts\lingshu.exe run "分析这个项目的模块边界" --dry-run
```

确认密钥与授权范围后，在 `.env` 中设置 `LINGSHU_ENABLE_LIVE_TESTS=true`，再执行：

```powershell
.\.venv\Scripts\lingshu.exe doctor --live --provider ark_coding
.\.venv\Scripts\lingshu.exe run "审查当前项目的配置加载逻辑" --workspace .
```

`doctor --live` 与 `run` 都会产生真实模型请求，并可能消耗套餐额度或产生费用。

## 通过 AI 调用灵枢

仓库提供两层 AI 协作配置：

- [`AGENTS.md`](./AGENTS.md) 定义项目级安全边界、开发规范与验收要求。
- [`.agents/skills/lingshu-orchestrator/SKILL.md`](./.agents/skills/lingshu-orchestrator/SKILL.md)
  定义何时调用灵枢、如何选择模型、如何限制出站文件以及如何验收结果。

Codex 从仓库根目录启动时会读取 `AGENTS.md`，并自动发现 `.agents/skills` 中的仓库级
skill。可以在任务中显式触发：

```text
请使用 $lingshu-orchestrator，让方舟子代理复核这个模块的边界条件，并由你完成最终验收。
```

默认工作方式是：主 AI 拆分任务并判断可发送范围 → 灵枢调用外部模型 → 外部模型输出分析
或补丁建议 → 主 AI 检查并决定是否应用 → 主 AI 运行测试并交付。外部模型不会直接修改主仓库。

## 模型路由

默认路由集中在 [`config/routing.yaml`](./config/routing.yaml)，模型与平台配置位于
[`config/models.yaml`](./config/models.yaml)。常规任务优先走方舟 Coding Plan；只有在显式
试用或比较时才使用原生通道：

```powershell
# DeepSeek 官方
.\.venv\Scripts\lingshu.exe run "独立复核这个算法" --workspace . --trial deepseek

# 阿里云百炼
.\.venv\Scripts\lingshu.exe run "为这个模块草拟测试" --workspace . --trial qwen_coder
```

供应商可能调整可用模型名称。遇到模型不存在或无权限时，请依据账户实际可用模型更新
`config/models.yaml`，不要把模型名或价格配置视为永久不变的事实。

## 本机观测台

```powershell
.\.venv\Scripts\lingshu.exe dashboard
```

浏览器访问 [http://127.0.0.1:18765](http://127.0.0.1:18765)。端口可通过
`--port` 修改。左侧提供任务历史、方舟 Coding Plan、阿里云百炼、DeepSeek 官方和
Token 总用量页面；Provider 页面支持时间与模型筛选，并使用折线图和堆叠柱状图展示调用
次数及输入、缓存命中、输出 Token。

## 常用命令

| 命令 | 作用 |
| --- | --- |
| `lingshu doctor` | 检查本地配置；加 `--live` 执行真实最小请求 |
| `lingshu run` | 路由并执行一个受监督任务 |
| `lingshu status <task-id>` | 查看任务状态 |
| `lingshu report` | 在本机生成 Markdown 用量报告 |
| `lingshu eval` | 运行不产生模型费用的内部冒烟检查 |
| `lingshu dashboard` | 启动本机模型调用观测台 |

## 数据与安全边界

- 真实密钥只保存在被 Git 忽略的 `.env` 中；仓库只提交空密钥模板 `.env.example`。
- `.git`、`.env`、非模板的 `.env.*`、常见证书与凭据、依赖目录及 `data/` 不会提供给外部模型。
- 普通源码在送出前仍会执行疑似凭据脱敏；请在提交前继续使用独立密钥扫描工具复核。
- 外部模型只能写入 `data/tasks/<task-id>/artifacts/`，不能执行任意 Shell 或直接修改主仓库。
- Dashboard 仅接受 `127.0.0.1` 或 `localhost`，不应暴露到公网。
- 若密钥曾进入 Git 历史或公开日志，单纯删除文件并不安全，应立即在供应商控制台撤销并轮换。

## 开发与验证

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,dashboard]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\pyright.exe
```

修改前端时：

```powershell
Set-Location web
npm install
npm run test
npm run build
```

前端开发服务器使用 `18766`，并把 `/api` 代理到 `18765`。构建产物会写入 Python 包，
日常运行观测台不需要 Node.js。

更多实现背景见 [`docs/implementation-plan.md`](./docs/implementation-plan.md) 与
[`docs/frontend-observability-plan.md`](./docs/frontend-observability-plan.md)。

## 许可证

仓库当前尚未声明开源许可证。在添加 `LICENSE` 前，公开可见不等于获得复制、修改或分发
授权；正式开放使用前请先选择并加入合适的许可证。
