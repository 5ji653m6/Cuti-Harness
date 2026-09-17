# Cuti Video Harness

[中文](PRODUCT_QUICKSTART.md) | **English**

> This is the English version of the product introduction and quick-start guide.

Cuti Video Harness is an open-source, general-purpose video agent harness built on [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness).

It does more than invoke image and video generation tools. It continuously manages scripts, characters, scenes, shots, audio, subtitles, timelines, and final videos. The Agent adapts the production plan to actual generated results, preserves reusable work through Artifact dependencies, and rebuilds only the affected parts.

## Key Capabilities

- Cuti Harness-powered conversation, Workflow selection, and dynamic `PlanPatch`
- Installable Workflow, Style, Provider, and supporting Skills
- Consistent character, scene, and shot references
- Durable long-running tasks with pause, resume, cancellation, and retry
- Incremental editing and partial regeneration
- Video assembly, audio, subtitles, timelines, and final export
- Auditable Agent decisions, tool calls, and build progress

## Architecture

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

Cuti Harness owns conversation, intent understanding, Workflow selection, creative decisions, and tool calls. Video Runtime owns project state, Artifact dependencies, task execution, failure recovery, incremental builds, and version commits.

A Workflow defines the available capabilities and creative rules without hard-coding the entire production process in advance. When a real asset completes or a task fails, the Agent can submit another `PlanPatch` to add tasks, revise later parameters, or cancel work that has not started.

## Clone and Run

```bash
npx @cuti-ai/video-agent-harness web
```

The first run prepares Python, FFmpeg, database storage, and all local processes automatically. Docker is not required.

## Detailed Production Deployment (Docker)

### Prerequisites

Install or configure the following before starting:

- Git
- Docker Desktop, or Docker Engine with Docker Compose v2
- Node.js 22.19+ or Node.js 24+
- Corepack
- An OpenAI API key

Real video generation also requires at least one of these provider credentials:

- `WAVESPEED_API_KEY`
- `ARK_API_KEY`

Workflows that generate music may also require `SUNO_API_KEY`. Other provider credentials are optional.

### 1. Clone the Repository

```bash
git clone https://github.com/blackzipper-hub/Video-agent-harness.git
cd Video-agent-harness
```

### 2. Create the Environment File

On macOS or Linux:

```bash
cp config/.env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item config/.env.example .env
```

Open `.env` and add at least:

```dotenv
OPENAI_API_KEY=your-openai-key
WAVESPEED_API_KEY=your-wavespeed-key
```

To use Volcengine Ark instead, configure:

```dotenv
OPENAI_API_KEY=your-openai-key
ARK_API_KEY=your-ark-key
```

> Never commit `.env` or real API credentials to Git.

### 3. Start the Video Services

```bash
docker compose --env-file .env -f deploy/compose.video.yml up --build -d
```

This starts:

- PostgreSQL
- Video Runtime
- Media Service
- Sandbox Worker
- Video Studio

Check the containers:

```bash
docker compose -f deploy/compose.video.yml ps
```

Check Video Runtime health:

```bash
curl http://127.0.0.1:8001/health
```

Expected response:

```json
{"status":"healthy"}
```

### 4. Install Dependencies and Build Cuti Harness

```bash
corepack enable
pnpm install --frozen-lockfile
pnpm run build
```

### 5. Start Cuti Harness

#### Windows PowerShell

```powershell
.\scripts\start-video-harness.ps1
```

The Windows launcher reads the repository `.env` and imports the Windows user proxy configuration when needed.

#### macOS or Linux

```bash
export OPENAI_API_KEY="your-openai-key"
export VIDEO_AGENT_MODEL="gpt-5.6-terra"
export VIDEO_RUNTIME_URL="http://127.0.0.1:8001"
export VIDEO_RUNTIME_SERVICE_TOKEN="video-harness-runtime-local"

pnpm dsh --profile web \
  --patch packages/bundle/video-agent/cordis.patch.yml \
  --no-open
```

Cuti Harness listens at:

[http://127.0.0.1:3080](http://127.0.0.1:3080)

Keep this terminal running.

### 6. Open Video Studio

English UI:

[http://127.0.0.1:3000/#/en/create](http://127.0.0.1:3000/#/en/create)

Chinese UI:

[http://127.0.0.1:3000/#/zh/create](http://127.0.0.1:3000/#/zh/create)

Video Studio is the primary interface for video generation and editing:

- Use the left side to chat with the Agent and submit editing requests.
- Use the right side to inspect scripts, images, clips, audio, build progress, and final videos.
- Open the Agent trajectory to inspect auditable planning results and tool calls.

## First Test

Start with a short, low-cost task:

> Create a 10-second, two-shot cinematic video of a robot watering one flower at sunrise. Use the same robot in both shots, include no narration, and export the final MP4.

Chinese prompt:

> 制作一个 10 秒、两个镜头的电影感短片：一个机器人在日出时给一朵花浇水。两个镜头保持同一个机器人，不要旁白，并导出最终 MP4。

## Development Mode

Keep the Docker services and Cuti Harness running, then create the frontend environment file:

```bash
cd apps/video-studio
cp ../../config/.env.example .env.local
```

On Windows PowerShell:

```powershell
Set-Location apps/video-studio
Copy-Item ../../config/.env.example .env.local
```

Add the following values to `apps/video-studio/.env.local`:

```dotenv
VITE_LOCAL_SINGLE_USER_MODE=true
VITE_VIDEO_RUNTIME_URL=http://127.0.0.1:8001
VITE_VIDEOCHAT_URL=http://127.0.0.1:8001
VITE_CUTI_BACKEND_URL=http://127.0.0.1:8001
VITE_BACKEND_URL=http://127.0.0.1:8001
```

Return to the repository root and start Vite:

```bash
pnpm --filter @cuti-ai/video-studio run dev
```

Open:

[http://127.0.0.1:5173/#/en/create](http://127.0.0.1:5173/#/en/create)

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| The UI opens, but sending a prompt produces no response | Confirm Cuti Harness is running on port `3080` and its process received `OPENAI_API_KEY`. |
| `401`, `NO_AUTH`, or model authentication error | Check `.env` and verify that the Cuti Harness process loaded the OpenAI key. |
| Image or video generation fails | Configure the key required by the selected Workflow. The default Seedance path requires WaveSpeed or Ark. |
| A Build remains queued | Run `docker compose -f deploy/compose.video.yml ps` and inspect the Runtime and Worker status. |
| A port is already in use | Free or remap ports `3000`, `3080`, `8001`, `8700`, and `18080`. |
| Sandbox Worker is unhealthy on Windows | Ensure Docker Desktop is running Linux containers. |
| Model or provider calls time out behind a proxy | Configure `HTTP_PROXY` and `HTTPS_PROXY`; Node also requires `NODE_USE_ENV_PROXY=1`. |

Inspect Video Runtime logs:

```bash
docker compose -f deploy/compose.video.yml logs video-runtime
```

Stop the services:

```bash
docker compose -f deploy/compose.video.yml down
```

Only use the following command when you intentionally want to delete the local database and generated-media volumes:

```bash
docker compose -f deploy/compose.video.yml down -v
```

## Project Status

Cuti Video Harness is currently in Developer Preview. Some APIs and data structures may still introduce compatibility-breaking changes.

Provider calls may incur real costs. Begin with short videos, fewer shots, and low-cost models.

## License

This project is licensed under the [MIT License](../LICENSE). DeepSeek and imported Cuti provenance is documented in [Source Provenance](../docs/source-provenance.md). Third-party dependencies and licenses are listed in [Third-Party Notices](THIRD_PARTY_NOTICES.md).
