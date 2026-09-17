# Cuti 媒体服务

本地字幕依赖 Node.js、FFmpeg 和 HyperFrames。受支持的 `video-agent-harness setup` 路径会在所选用户数据目录中安装固定版本的 CLI、GSAP 和渲染浏览器；`web` 只把这些路径注入媒体服务，不执行安装。仅开发媒体服务源码时，也可以运行 `scripts/setup-video-captions.ps1`，将依赖安装到 `.runtime-deps/hyperframes`。服务支持 Windows 中文字体及 Chrome/Edge 路径；可使用 `HYPERFRAMES_*` 环境变量覆盖自动发现结果。

同一个本地运行时通过 `POST /video/hyperframes/render` 为完整 Code-to-Video 组合提供服务。请求包含自包含 HTML、输出尺寸、时长和帧率。服务只暂存本地 GSAP 与 CJK 字体素材，为模型选择但未声明的字体族提供内置本地回退，并在渲染前拒绝远程 URL、嵌入式浏览上下文、浏览器网络 API 和文档导航。

[English](README.md) | 中文

Cuti 平台的媒体处理微服务，负责 FFmpeg 视频与音频处理、图片缩放和 S3 文件管理，并为每个任务隔离工作目录。

## 架构

- **FastAPI** REST API
- **FFmpeg** 视频与音频处理，并带并发控制
- **Pillow** 图片处理
- **本地磁盘** 作为输入与输出存储（`STORAGE_BACKEND=local`）；S3 可选
- 按 `run_id` 隔离工作目录，并基于 TTL 清理

## 快速开始

推荐从仓库根目录用 compose 启动整套服务。媒体服务端口是 `18080`。

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

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/video/info` | 读取视频元数据 |
| POST | `/api/v1/video/trim` | 裁剪视频或补足时长 |
| POST | `/api/v1/video/concat` | 拼接视频 |
| POST | `/api/v1/video/speed-adjust` | 调整视频速度 |
| POST | `/api/v1/video/normalize` | 统一分辨率 |
| POST | `/api/v1/video/strip-audio` | 移除音轨 |
| POST | `/api/v1/video/mix-audio` | 混合音频与视频 |
| POST | `/api/v1/video/add-audio` | 添加音轨 |
| POST | `/api/v1/video/create-placeholder` | 生成黑色视频 |
| POST | `/api/v1/video/extract-frame` | 按时间点提取静帧 |
| POST | `/api/v1/audio/info` | 读取音频时长 |
| POST | `/api/v1/audio/trim` | 裁剪音频 |
| POST | `/api/v1/audio/extract-from-video` | 从视频提取音频 |
| POST | `/api/v1/audio/convert` | 转换音频格式 |
| POST | `/api/v1/image/info` | 读取图片尺寸 |
| POST | `/api/v1/image/resize` | 调整图片尺寸 |
| POST | `/api/v1/pipeline/segment-process` | 多视频对齐并拼接 |
| POST | `/api/v1/pipeline/ensure-on-s3` | 下载、标准化并上传 |
| POST | `/api/v1/pipeline/workspace/cleanup` | 清理工作目录 |
| GET | `/healthz` | 存活探针 |
| GET | `/readyz` | 就绪探针 |
| GET | `/metrics` | Prometheus 指标 |

## 视频拼接

未要求转场时，`/api/v1/video/concat` 会检查每个视频流和音频流。编码、像素格式、尺寸、帧率、音频编码、采样率、声道布局和时间基一致的输入使用 FFmpeg concat demuxer 直接复制码流，包括参数兼容的 HEVC Main10 Seedance 片段。不兼容的输入以及带转场的输入使用标准化转码。直接拼接后会检查时长；若时间戳导致结果异常，则强制执行一次转码。

## 部署

这条线只支持本地 compose。集群 Helm、ECR、EKS 留在私有分支。

```bash
cp config/.env.example .env
docker compose --env-file .env -f deploy/compose.video.yml up --build -d
```

身份是 `local-user`。对象存储默认本地磁盘（`STORAGE_BACKEND=local`）。见[根目录部署说明](../../deploy/README.zh.md)。
