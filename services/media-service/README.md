# Cuti Media Service

English | [中文](README.zh.md)

Media processing microservice for the Cuti platform. Handles FFmpeg video/audio processing, image resizing, and S3 file management with per-task workspace isolation.

## Architecture

Local captions require Node.js, FFmpeg and the HyperFrames runtime. The supported `video-agent-harness setup` path installs the pinned CLI, GSAP and rendering browser in the selected user-data directory; `web` injects those paths into the media service without installing anything. Source-only media-service development may instead run `scripts/setup-video-captions.ps1`, which installs under `.runtime-deps/hyperframes`. The service supports Windows CJK fonts and Chrome/Edge paths, and explicit `HYPERFRAMES_*` environment settings override automatic discovery.

The same local runtime serves `POST /video/hyperframes/render` for complete Code-to-Video compositions. Requests contain self-contained HTML and output dimensions, duration, and frame rate. The service stages only local GSAP and CJK font assets, gives undeclared model-selected font families a bundled local fallback, and rejects remote URLs, embedded browsing contexts, browser network APIs, and document navigation before rendering.

- **FastAPI** REST API
- **FFmpeg** for video/audio processing with concurrency control
- **Pillow** for image processing
- **Local disk** for input/output storage (`STORAGE_BACKEND=local`); S3 is optional
- **Workspace isolation** per `run_id` with TTL-based cleanup

## Quick Start

The supported product path is the root compose file. Media Service listens on `18080`.

```bash
cp config/.env.example .env
docker compose --env-file .env -f deploy/compose.video.yml up --build -d

cd services/media-service
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8080

pip install pytest pytest-asyncio httpx
pytest tests/ -v
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/video/info` | Get video metadata |
| POST | `/api/v1/video/trim` | Trim/pad video to duration |
| POST | `/api/v1/video/concat` | Concatenate videos |
| POST | `/api/v1/video/speed-adjust` | Adjust video speed |
| POST | `/api/v1/video/normalize` | Normalize resolution |
| POST | `/api/v1/video/strip-audio` | Remove audio track |
| POST | `/api/v1/video/mix-audio` | Mix audio into video |
| POST | `/api/v1/video/add-audio` | Add audio track |
| POST | `/api/v1/video/create-placeholder` | Generate black video |
| POST | `/api/v1/video/extract-frame` | Extract a still frame at timestamp |
| POST | `/api/v1/audio/info` | Get audio duration |
| POST | `/api/v1/audio/trim` | Trim audio |
| POST | `/api/v1/audio/extract-from-video` | Extract audio from video |
| POST | `/api/v1/audio/convert` | Convert audio format |
| POST | `/api/v1/image/info` | Get image dimensions |
| POST | `/api/v1/image/resize` | Resize image |
| POST | `/api/v1/pipeline/segment-process` | Multi-video align + concat |
| POST | `/api/v1/pipeline/ensure-on-s3` | Download + normalize + upload |
| POST | `/api/v1/pipeline/workspace/cleanup` | Cleanup workspace |
| GET | `/healthz` | Liveness probe |
| GET | `/readyz` | Readiness probe |
| GET | `/metrics` | Prometheus metrics |

## Concatenation

`/api/v1/video/concat` probes every video and audio stream when no transition is requested. Inputs with identical codec, pixel format, dimensions, frame rate, audio codec, sample rate, channel layout, and time base use the FFmpeg concat demuxer with stream copy, including compatible HEVC Main10 Seedance segments. Incompatible inputs and transitions use normalized transcoding. A duration check after stream-copy concat forces one transcoding pass if timestamps produce an invalid result.

## Deployment

This track is local compose only. Cluster Helm, ECR, and EKS stay on the private branch.

```bash
cp config/.env.example .env
docker compose --env-file .env -f deploy/compose.video.yml up --build -d
```

Identity is `local-user`. Object storage defaults to the local disk (`STORAGE_BACKEND=local`). See the [root deploy README](../../deploy/README.md).
