# Cuti Video Harness

**中文** | [English](PRODUCT_QUICKSTART.en.md)

> 本文档为中文版。

Cuti Video Harness 是一个基于 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 构建的通用视频 Agent Harness。

它不仅能调用图片和视频生成工具，还能持续管理剧本、角色、场景、镜头、音频、字幕、时间线和最终成片。Agent 会根据真实生成结果动态调整制作计划，通过 Artifact 依赖关系保留可复用内容，并只重建受到影响的部分。

## 核心能力

- Cuti Harness 驱动的对话、Workflow 选择和动态 `PlanPatch`
- 可安装的 Workflow、Style、Provider 和辅助 Skill
- 角色、场景和镜头参考的一致性管理
- 可暂停、恢复、取消和失败重试的长任务
- 增量编辑和局部重新生成
- 视频拼接、音频、字幕、时间线与最终导出
- 可审计的 Agent 决策、工具调用和构建进度

## 系统架构

```text
Video Studio
  ↓
Cuti Harness
  ↓
Video Runtime
  ├─ Project / ProjectVersion
  ├─ Artifact Graph
  ├─ Dynamic PlanPatch
  ├─ Incremental Build
  ├─ Timeline
  └─ Validation / Export
  ↓
Workflow / Provider / Style / Media Plugins
```

Cuti Harness 负责对话、意图理解、Workflow 选择、创作判断和工具调用。Video Runtime 负责项目状态、Artifact 依赖、任务执行、失败恢复、增量构建和版本提交。

Workflow 负责约束可用能力和制作规则，但不会预先写死完整制作过程。每当真实素材生成完成或任务失败时，Agent 都可以通过新的 `PlanPatch` 追加任务、修改后续参数或取消尚未执行的任务。

## Clone and Run

```bash
npx @cuti-ai/video-agent-harness web
```

首次运行自动准备 Python、FFmpeg、数据库存储和全部本地进程，无需 Docker。

## 详细生产部署（Docker）

### 环境要求

运行项目前，请准备：

- Git
- Docker Desktop，或支持 Docker Compose v2 的 Docker Engine
- Node.js 22.19+ 或 Node.js 24+
- Corepack
- OpenAI API Key

进行真实视频生成时，还需要以下至少一种 Provider 凭据：

- `WAVESPEED_API_KEY`
- `ARK_API_KEY`

生成音乐的 Workflow 可能还需要 `SUNO_API_KEY`。其他 Provider 凭据为可选配置。

### 1. 克隆项目

```bash
git clone https://github.com/blackzipper-hub/Video-agent-harness.git
cd Video-agent-harness
```

### 2. 创建环境配置

macOS 或 Linux：

```bash
cp config/.env.example .env
```

Windows PowerShell：

```powershell
Copy-Item config/.env.example .env
```

编辑 `.env`，至少填写：

```dotenv
OPENAI_API_KEY=your-openai-key
WAVESPEED_API_KEY=your-wavespeed-key
```

如果使用火山引擎 Ark，可以改为：

```dotenv
OPENAI_API_KEY=your-openai-key
ARK_API_KEY=your-ark-key
```

> 请勿将 `.env` 或任何真实 API Key 提交到 Git 仓库。

### 3. 启动视频服务

```bash
docker compose --env-file .env -f deploy/compose.video.yml up --build -d
```

该命令会启动：

- PostgreSQL
- Video Runtime
- Media Service
- Sandbox Worker
- Video Studio

检查服务状态：

```bash
docker compose -f deploy/compose.video.yml ps
```

检查 Video Runtime：

```bash
curl http://127.0.0.1:8001/health
```

预期返回：

```json
{"status":"healthy"}
```

### 4. 安装依赖并构建 Cuti Harness

```bash
corepack enable
pnpm install --frozen-lockfile
pnpm run build
```

### 5. 启动 Cuti Harness

#### Windows PowerShell

```powershell
.\scripts\start-video-harness.ps1
```

Windows 启动脚本会读取仓库根目录的 `.env`，并自动处理 Windows 用户代理配置。

#### macOS 或 Linux

```bash
export OPENAI_API_KEY="your-openai-key"
export VIDEO_AGENT_MODEL="gpt-5.6-terra"
export VIDEO_RUNTIME_URL="http://127.0.0.1:8001"
export VIDEO_RUNTIME_SERVICE_TOKEN="video-harness-runtime-local"

pnpm dsh --profile web \
  --patch packages/bundle/video-agent/cordis.patch.yml \
  --no-open
```

Cuti Harness 默认运行在：

[http://127.0.0.1:3080](http://127.0.0.1:3080)

请保持该终端持续运行。

### 6. 打开 Video Studio

中文界面：

[http://127.0.0.1:3000/#/zh/create](http://127.0.0.1:3000/#/zh/create)

English UI：

[http://127.0.0.1:3000/#/en/create](http://127.0.0.1:3000/#/en/create)

Video Studio 是视频生成和编辑的主要产品界面：

- 左侧用于与 Agent 对话并提交修改指令
- 右侧用于查看剧本、图片、视频片段、音频、构建进度和最终成片
- Agent 轨迹用于查看可审计的规划结果与工具调用

## 第一个测试任务

建议先使用低成本、短时长任务进行验证：

> 制作一个 10 秒、两个镜头的电影感短片：一个机器人在日出时给一朵花浇水。两个镜头保持同一个机器人，不要旁白，并导出最终 MP4。

English prompt：

> Create a 10-second, two-shot cinematic video of a robot watering one flower at sunrise. Use the same robot in both shots, include no narration, and export the final MP4.

## 开发模式

如需使用 Vite 热更新运行 Video Studio，请保持 Docker 服务和 Cuti Harness 正常运行。

进入前端目录并创建本地环境文件：

```bash
cd apps/video-studio
cp ../../config/.env.example .env.local
```

Windows PowerShell：

```powershell
Set-Location apps/video-studio
Copy-Item ../../config/.env.example .env.local
```

在 `apps/video-studio/.env.local` 中填写：

```dotenv
VITE_LOCAL_SINGLE_USER_MODE=true
VITE_VIDEO_RUNTIME_URL=http://127.0.0.1:8001
VITE_VIDEOCHAT_URL=http://127.0.0.1:8001
VITE_CUTI_BACKEND_URL=http://127.0.0.1:8001
VITE_BACKEND_URL=http://127.0.0.1:8001
```

回到仓库根目录并启动开发服务器：

```bash
pnpm --filter @cuti-ai/video-studio run dev
```

打开：

[http://127.0.0.1:5173/#/zh/create](http://127.0.0.1:5173/#/zh/create)

## 常见问题

| 问题 | 检查方式 |
| --- | --- |
| 页面可以打开，但发送消息后没有响应 | 确认 Cuti Harness 正在 `3080` 端口运行，并且启动终端中已设置 `OPENAI_API_KEY`。 |
| 出现 `401`、`NO_AUTH` 或模型认证错误 | 检查 `.env` 和 Cuti Harness 进程是否正确读取 OpenAI Key。 |
| 图片或视频生成失败 | 检查所选 Workflow 需要的 Provider Key；默认 Seedance 流程需要 WaveSpeed 或 Ark。 |
| Build 长时间停留在 queued | 使用 `docker compose -f deploy/compose.video.yml ps` 检查 Runtime 和 Worker 状态。 |
| 端口已被占用 | 检查并释放或重新映射 `3000`、`3080`、`8001`、`8700` 和 `18080`。 |
| Windows 下 Sandbox Worker 不健康 | 确认 Docker Desktop 正在使用 Linux containers。 |
| 模型或 Provider 请求超时 | 配置 `HTTP_PROXY`、`HTTPS_PROXY`，Node 环境还需要设置 `NODE_USE_ENV_PROXY=1`。 |

查看 Video Runtime 日志：

```bash
docker compose -f deploy/compose.video.yml logs video-runtime
```

停止服务：

```bash
docker compose -f deploy/compose.video.yml down
```

只有在确定需要删除本地数据库和生成媒体时，才使用：

```bash
docker compose -f deploy/compose.video.yml down -v
```

## 项目状态

Cuti Video Harness 当前处于 Developer Preview 阶段，部分接口和数据结构仍可能发生兼容性调整。

Provider 调用可能产生真实费用。首次使用时建议选择短视频、较少镜头和低成本模型进行验证。

## License

本项目使用 [MIT License](../LICENSE)。DeepSeek 与 Cuti 导入代码的来源记录参见 [Source Provenance](../docs/source-provenance.md)，第三方依赖及许可证参见 [Third-Party Notices](THIRD_PARTY_NOTICES.md)。
