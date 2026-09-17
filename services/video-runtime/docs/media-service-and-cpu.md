# 方案一：Media Processing 微服务 (`cuti-media-service`)

## 1. 背景与问题

### 1.1 性能压测结论

| 阶段 | CPU | 瓶颈 |
|------|-----|------|
| Segment (FFmpeg concat/trim/pad) | **100%** 打满 | FFmpeg 是唯一 CPU 瓶颈 |
| Keyframe (真实 LLM + mock 图片生成) | 最高 60% (5 并发) | 不是瓶颈 |
| Video Gen (真实 LLM + mock 视频生成) | 最高 74% (50 并发) | LLM API 吞吐是限制，非本地 CPU |

**FFmpeg 并发线性退化**：1 任务 55s → 2 任务 106s → 5 任务 266s，因为单机 CPU 已打满。

### 1.2 存储泄漏（根因分析）

**核心问题：`convert_media_url_to_s3` 下载文件到持久目录，永不清理。**

此函数被 **18 个地方**调用，每次调用都把 S3 文件下载到 `../audios/`、`../videos/`、`../photos/` 目录，处理完后从不删除。

#### 泄漏点一览（输入文件不清理）

| 文件 | 函数 | 媒体类型 | 是否清理 |
|------|------|----------|----------|
| `utils/video_utils.py` | `adjust_video_speed_to_duration` | VIDEO | 不清理 |
| `utils/video_utils.py` | `get_video_duration` | VIDEO | 不清理 |
| `utils/video_utils.py` | `trim_audio_clip` | AUDIO | 不清理 |
| `utils/video_utils.py` | `trim_video_to_duration` | VIDEO | 不清理 |
| `utils/video_utils.py` | `strip_audio_from_video` | VIDEO | 不清理 |
| `utils/video_utils.py` | `get_audio_duration_from_url` | AUDIO | 不清理 |
| `utils/video_utils.py` | `concatenate_video_segments_by_urls` | VIDEO(多个) | 不清理 |
| `utils/video_utils.py` | `merge_video_with_mixed_audio` | VIDEO+AUDIO | 不清理 |
| `utils/video_utils.py` | `adjust_lipsync_video_music_volume` | VIDEO | 不清理 |
| `utils/video_utils.py` | `add_background_music_to_video` | VIDEO+AUDIO | 不清理 |
| `utils/file_utils.py` | `process_audio_duration` | AUDIO | 不清理 |
| `utils/file_utils.py` | `extract_audio_from_video` | VIDEO | 不清理 |
| `utils/file_utils.py` | `extract_audio_segment` | AUDIO | 不清理 |
| `utils/file_utils.py` | `merge_video_with_audio` | VIDEO+AUDIO | 不清理 |
| `services/agent/video/video_assembly_service.py` | `concatenate_video_segments_by_urls` | VIDEO(多个) | 不清理 |
| `llm/wavespeed_service.py` | `_get_audio_duration` | AUDIO | 不清理 |
| `crud/video/video_audio.py` | `create_music_from_audio_transcription_segments` | AUDIO | 不清理 |

#### 泄漏点二览（输出文件不清理）

这些函数处理完后上传到 S3，但本地生成的输出文件也不删除：

| 文件 | 函数 | 输出路径 | 是否清理 |
|------|------|----------|----------|
| `utils/video_utils.py` | `adjust_video_speed_to_duration` | `videos_dir/{filename}.mp4` | 不清理 |
| `utils/video_utils.py` | `merge_video_with_mixed_audio` | `videos_dir/{base}_mixed_audio.mp4` | 不清理 |
| `utils/video_utils.py` | `concatenate_video_segments_by_urls` | `video_dir/final_{title}_{uuid}.mp4` | 不清理 |
| `utils/file_utils.py` | `merge_video_with_audio` | `videos_dir/{base}_with_audio.mp4` | 不清理 |
| `services/.../video_assembly_service.py` | `concatenate_video_segments_by_urls` | `video_dir/final_{title}_{uuid}.mp4` | 不清理 |

#### 估算

- 每个视频任务（31 个 shot）：约 **50–300 MB** 的持久文件泄漏
- 100 个任务后：**5–30 GB** 无用文件积累
- 文件永远不会被自动清理

---

## 2. 新服务定位

### 核心原则

1. **输入 URL，输出 URL** — VideoAgent 不再处理本地文件
2. **文件按 `run_id` 隔离** — 所有中间文件在 `/workspace/{run_id}/` 下，任务结束统一清理
3. **原子操作 + 组合 Pipeline** — 既提供单步 API（trim、concat），也提供组合 pipeline（segment 全流程），减少网络往返
4. **幂等** — 相同输入 + 操作 = 相同输出 URL

### 职责划分

| | `cuti-media-service` (新) | `Cuti-VideoAgent` (现有) |
|---|---|---|
| **视频处理** | concat, trim, pad, speed, normalize, watermark, strip/add/mix audio | - |
| **音频处理** | trim, extract, convert, mix, volume | - |
| **图片处理** | resize, downsample, format convert (→WebP) | - |
| **文件管理** | S3 download/upload, run_id 隔离, 清理 | - |
| **元数据查询** | duration, resolution, fps, has_audio | - |
| **LLM 调用** | - | prompt 生成, 评估, agent |
| **业务编排** | - | node 流程, batch 调度, DB, 事件 |
| **外部 API** | - | Gemini, WaveSpeed, Sora, Suno |
| **成本计算** | - | LangSmith, credit deduction |

---

## 3. API 设计

### 3.1 视频 API

```
POST /api/v1/video/info
    Input:  { "video_url": "s3://..." }
    Output: {
        "duration": 5.0,
        "width": 1920,
        "height": 1080,
        "fps": 25.0,
        "codec": "h264",
        "pix_fmt": "yuv420p",
        "has_audio": false
    }

POST /api/v1/video/trim
    Input:  {
        "video_url": "s3://...",
        "target_duration": 5.0,
        "mode": "pad_or_trim",  // "trim_only" | "pad_or_trim"
        "tolerance": 0.05,
        "run_id": "xxx"
    }
    Output: { "result_url": "s3://...", "duration": 5.0 }

POST /api/v1/video/concat
    Input:  {
        "video_urls": ["s3://...", "s3://..."],
        "normalize": true,  // 自动检测并统一分辨率/fps/codec
        "run_id": "xxx"
    }
    Output: { "result_url": "s3://...", "duration": 15.0 }

POST /api/v1/video/speed-adjust
    Input:  { "video_url": "s3://...", "target_duration": 8.0, "run_id": "xxx" }
    Output: { "result_url": "s3://...", "duration": 8.0 }

POST /api/v1/video/normalize
    Input:  {
        "video_url": "s3://...",
        "target_width": 1920,
        "target_height": 1080,
        "run_id": "xxx"
    }
    Output: { "result_url": "s3://...", "metadata": { "width": 1920, "height": 1080 } }

POST /api/v1/video/add-watermark
    Input:  { "video_url": "s3://...", "run_id": "xxx" }
    Output: { "result_url": "s3://..." }

POST /api/v1/video/strip-audio
    Input:  { "video_url": "s3://...", "run_id": "xxx" }
    Output: { "result_url": "s3://..." }

POST /api/v1/video/add-audio
    Input:  {
        "video_url": "s3://...",
        "audio_segments": [
            { "audio_url": "s3://...", "start_time": 0.0, "duration": 5.0, "volume": 1.0 }
        ],
        "run_id": "xxx"
    }
    Output: { "result_url": "s3://..." }

POST /api/v1/video/mix-audio
    Input:  {
        "video_url": "s3://...",
        "audio_url": "s3://...",
        "audio_volume": 0.3,
        "run_id": "xxx"
    }
    Output: { "result_url": "s3://..." }

POST /api/v1/video/create-placeholder
    Input:  {
        "duration": 5.0,
        "width": 1920,
        "height": 1080,
        "fps": 25,
        "run_id": "xxx"
    }
    Output: { "result_url": "s3://..." }
```

### 3.2 音频 API

```
POST /api/v1/audio/info
    Input:  { "audio_url": "s3://..." }
    Output: { "duration": 120.5 }

POST /api/v1/audio/trim
    Input:  { "audio_url": "s3://...", "start": 0.0, "duration": 3.0, "run_id": "xxx" }
    Output: { "result_url": "s3://..." }

POST /api/v1/audio/extract-from-video
    Input:  { "video_url": "s3://...", "run_id": "xxx" }
    Output: { "result_url": "s3://..." }

POST /api/v1/audio/convert
    Input:  { "audio_url": "s3://...", "target_format": "wav", "run_id": "xxx" }
    Output: { "result_url": "s3://..." }
```

### 3.3 图片 API

```
POST /api/v1/image/info
    Input:  { "image_url": "s3://..." }
    Output: { "width": 1920, "height": 1080 }

POST /api/v1/image/resize
    Input:  {
        "image_url": "s3://...",
        "target_width": 1920,
        "target_height": 1080,
        "format": "webp",
        "quality": 85,
        "run_id": "xxx"
    }
    Output: { "result_url": "s3://...", "width": 1920, "height": 1080 }
```

### 3.4 组合 Pipeline API（减少网络往返）

```
POST /api/v1/pipeline/segment-process
    """一步完成: 下载多个视频 → align duration → concat → trim → 上传
    替代: batch_download + align_video_to_duration_exact_local + concat_local_videos_with_normalize + upload_file_from_temp
    """
    Input: {
        "run_id": "xxx",
        "videos": [
            { "url": "s3://...", "target_duration": 5.0 },
            { "url": "s3://...", "target_duration": 3.0 }
        ],
        "total_target_duration": 8.0,
        "normalize": true
    }
    Output: { "result_url": "s3://...", "duration": 8.0 }

POST /api/v1/pipeline/video-assembly
    """一步完成: 下载所有 segment → concat → 加旁白/音效/音乐 → 加水印 → 上传
    替代: _download_media_to_temp + concat + add_audio + watermark + upload
    """
    Input: {
        "run_id": "xxx",
        "segments": [
            { "url": "s3://...", "duration": 8.0 }
        ],
        "narrations": [
            { "url": "s3://...", "start_time": 0.0, "duration": 5.0, "volume": 1.0 }
        ],
        "audio_effects": [
            { "url": "s3://...", "start_time": 3.0, "duration": 2.0, "volume": 0.8 }
        ],
        "background_music": {
            "url": "s3://...",
            "mode": "loop",        // "loop" | "truncate" | "once"
            "volume": 0.3,
            "crossfade_ms": 2000
        },
        "watermark": true
    }
    Output: { "result_url": "s3://...", "duration": 120.0 }

POST /api/v1/pipeline/ensure-on-s3
    """外部 URL → 下载 → normalize → watermark → 上传到我们 S3
    替代: ensure_video_on_our_s3 / download_and_upload_video_to_s3
    """
    Input: {
        "external_url": "https://...",
        "target_width": 1920,
        "target_height": 1080,
        "watermark": true,
        "run_id": "xxx"
    }
    Output: { "result_url": "s3://..." }

POST /api/v1/workspace/cleanup
    """任务结束，清理该 run_id 下的所有中间文件"""
    Input: { "run_id": "xxx" }
    Output: { "cleaned_files": 42, "freed_mb": 350.0 }
```

### 3.5 网络往返优化

```
旧流程 (VideoAgent 内部，以 segment 为例):
  S3下载 → align → S3上传 → S3下载 → concat → S3上传 → S3下载 → trim → S3上传
  = 6次 S3 操作 + 3次 FFmpeg

新流程 (一次 pipeline 调用):
  VideoAgent → POST /pipeline/segment-process { urls, durations }
  media-service 内部: S3下载 → align → concat → trim → S3上传 (全在本地完成)
  = 2次 S3 操作 + 3次 FFmpeg (省了 4 次网络传输)
```

---

## 4. 通信方式

### HTTP REST Client（同步模式，适合 <60s 的操作）

```python
class MediaServiceClient:
    def __init__(self, base_url: str):
        self.base_url = base_url  # e.g. "http://media-service.internal:8080"
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(connect=5, read=300, write=60))

    async def video_info(self, video_url: str) -> dict:
        resp = await self.client.post(f"{self.base_url}/api/v1/video/info",
                                      json={"video_url": video_url})
        resp.raise_for_status()
        return resp.json()

    async def segment_process(self, run_id: str, videos: list, total_duration: float) -> str:
        resp = await self.client.post(f"{self.base_url}/api/v1/pipeline/segment-process", json={
            "run_id": run_id,
            "videos": videos,
            "total_target_duration": total_duration,
            "normalize": True
        })
        resp.raise_for_status()
        return resp.json()["result_url"]

    async def video_assembly(self, run_id: str, segments: list, narrations: list = None,
                              audio_effects: list = None, background_music: dict = None,
                              watermark: bool = True) -> str:
        resp = await self.client.post(f"{self.base_url}/api/v1/pipeline/video-assembly", json={
            "run_id": run_id,
            "segments": segments,
            "narrations": narrations or [],
            "audio_effects": audio_effects or [],
            "background_music": background_music,
            "watermark": watermark
        })
        resp.raise_for_status()
        return resp.json()["result_url"]

    async def cleanup(self, run_id: str):
        await self.client.post(f"{self.base_url}/api/v1/workspace/cleanup",
                               json={"run_id": run_id})
```

### 异步任务模式（适合 >60s 的长操作，如 video-assembly）

```
POST /api/v1/pipeline/video-assembly → 202 { "task_id": "abc123" }
GET  /api/v1/tasks/abc123           → { "status": "processing", "progress": 60 }
GET  /api/v1/tasks/abc123           → { "status": "completed", "result_url": "s3://..." }
```

VideoAgent 可以 polling 或 webhook 回调。

---

## 5. 集成清单

Video Runtime 通过 `app.utils.media_service_client` 调用 Media Service；`video_utils.py` 只保留 Provider 出片后需要的薄封装（`finalize_pipeline_video_upload`、`trim_video_to_duration`、`strip_audio_from_video`、`get_audio_duration_from_url`、`normalize_video_to_target_sync`）。

### 5.4 s3_utils.py

| 原代码 | 迁移为 |
|--------|--------|
| `ensure_video_on_our_s3` (download → normalize → watermark → upload) | `POST /pipeline/ensure-on-s3` |
| `download_and_upload_video_to_s3` | `POST /pipeline/ensure-on-s3` |
| `download_and_upload_audio_to_s3` | 保留（简单 HTTP download → S3 upload，不涉及 FFmpeg）或迁移到 media-service |
| `upload_image` 中的 PIL resize + WebP 转换 | `POST /image/resize`，返回 URL 后 VideoAgent 拿 URL 用 |

### 5.5 工具文件

| 文件 | 原调用 | 迁移为 |
|------|--------|--------|
| `tools/video/wan25.py` | `get_audio_duration_from_url(audio_url)` | `POST /audio/info` |
| `tools/video/wan25.py` | `trim_video_to_duration(video_url, dur)` | `POST /video/trim` |
| `tools/video/wan25.py` | `strip_audio_from_video(video_url)` | `POST /video/strip-audio` |
| `tools/video/wan26_flash.py` | `get_audio_duration_from_url` + `trim_video_to_duration` | 同上 |
| `tools/lipsync/latentsync.py` | `get_audio_duration_from_url(audio_url)` | `POST /audio/info` |
| `llm/openai_sora_service.py` | `normalize_video_to_target_sync` + PIL resize | `POST /video/normalize` + `POST /image/resize` |
| `llm/wavespeed_service.py` | `downsample_to_target_sync` + `upload_image` | `POST /image/resize` |

### 5.6 file_utils.py

| 原函数 | 迁移为 |
|--------|--------|
| `extract_audio_from_video` | `POST /audio/extract-from-video` |
| `prepare_video_for_llm` (download for Google upload) | 保留（一致性检查，非通用媒体处理） |

### 5.7 其他

| 文件 | 原调用 | 迁移为 |
|------|--------|--------|
| `utils/image_utils.py` → `downsample_to_target_sync` | 调用方在 nano_banana/wavespeed_service | `POST /image/resize` |
| `services/download_service.py` → `create_image_sheets` | PIL 拼图 | 可选：`POST /image/create-sheet` 或保留（非关键路径）|
| `services/.../user_input_analysis_service.py` → 音频提取 | ffmpeg 内联 | `POST /audio/extract-from-video` |
| `tools/transcribe/gemini.py` → ffprobe 获取 duration | ffprobe 内联 | `POST /audio/info` |
| `api/admin/smart_testing_endpoints.py` → `_get_video_dimensions_sync` | ffprobe 内联 | `POST /video/info` |
| `utils/subtitle_utils.py` → `add_subtitles_to_video_command` | 返回 FFmpeg 命令 | media-service 内部实现（当字幕功能启用时）|

### 5.8 清理调用

在 VideoAgent 的每个 node 结束时调用清理：

```python
# video_agent_service.py 中，整个流程结束后
async def finalize_task(run_id: str):
    await media_client.cleanup(run_id)
```

---

## 6. media-service 内部文件管理

### 目录结构

```
/workspace/
  {run_id}/
    inputs/        # S3 下载的源文件（按 hash 去重）
    intermediates/ # FFmpeg 中间产物
    outputs/       # 最终上传到 S3 的文件
```

### 智能缓存

```python
async def ensure_local(video_url: str, run_id: str) -> str:
    """下载到 /workspace/{run_id}/inputs/，已存在则跳过"""
    url_hash = hashlib.md5(video_url.encode()).hexdigest()
    local_path = f"/workspace/{run_id}/inputs/{url_hash}{ext}"
    if os.path.exists(local_path):
        return local_path
    await s3_download(video_url, local_path)
    return local_path
```

### 自动清理

1. `POST /workspace/cleanup` — VideoAgent 主动调用
2. TTL 兜底 — Cron job 清理超过 2 小时的 workspace（防止 VideoAgent 忘记调用）
3. Pod 销毁 — K8s emptyDir，Pod 重启自动清理

---

## 7. AWS 部署方案

### 架构图

```
VideoAgent Pods                    media-service Pods
┌─────────────┐                   ┌─────────────────────┐
│ Pod 1 (2C/4G)│──── ALB ────────▶│ Pod 1 (2C/4G, 20G)  │
│ Pod 2 (2C/4G)│    (internal)    │ Pod 2 (2C/4G, 20G)  │
└─────────────┘                   │ Pod 3 (auto scaled)  │
                                  │ ...                  │
                                  └──────────┬──────────┘
                                             │
                                  ┌──────────▼──────────┐
                                  │     AWS S3 Bucket    │
                                  └─────────────────────┘
```

### K8s 资源配置

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: media-service
spec:
  replicas: 2                        # 基础 2 个 Pod
  template:
    spec:
      containers:
      - name: media-service
        image: xxx.dkr.ecr.region.amazonaws.com/cuti-media-service:latest
        resources:
          requests:
            cpu: "1000m"             # 请求 1 CPU
            memory: "2Gi"
          limits:
            cpu: "2000m"             # 最多 2 CPU
            memory: "4Gi"
        env:
        - name: FFMPEG_THREADS
          value: "2"                 # 每个 FFmpeg 进程用 2 线程
        - name: MAX_CONCURRENT_JOBS
          value: "3"                 # 每个 Pod 最多 3 个并发任务
        - name: WORKSPACE_BASE
          value: "/workspace"
        - name: WORKSPACE_TTL_HOURS
          value: "2"                 # 超过 2 小时自动清理
        volumeMounts:
        - name: workspace
          mountPath: /workspace
      volumes:
      - name: workspace
        emptyDir:
          sizeLimit: 20Gi           # 每个 Pod 20GB 临时空间
```

### HPA Auto Scaling

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: media-service-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: media-service
  minReplicas: 2                     # 最少 2 个 Pod
  maxReplicas: 20                    # 最多 20 个 Pod
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 60       # CPU 超过 60% 触发扩容
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 30 # 快速扩容（30s 稳定窗口）
      policies:
      - type: Pods
        value: 4                     # 每次最多加 4 个 Pod
        periodSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300 # 缓慢缩容（5 分钟稳定窗口）
      policies:
      - type: Pods
        value: 1                     # 每次最多减 1 个 Pod
        periodSeconds: 120
```

### 扩容预测

| 并发视频任务 | 需要 Pod 数 (2C/pod, 60%目标) | 预计单任务耗时 |
|-------------|-------------------------------|--------------|
| 1-3 | 2 pods (基础) | ~55s |
| 10 | 3-4 pods | ~55-60s |
| 50 | 10-12 pods | ~55-65s |
| 100 | 18-20 pods | ~55-70s |

每个 Pod 同时处理 2-3 个 FFmpeg 任务（受 `MAX_CONCURRENT_JOBS` 限制），HPA 根据 CPU 自动扩缩。

### Docker 镜像

```dockerfile
FROM python:3.11-slim

# FFmpeg
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app
WORKDIR /app

EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
```

### Service + Ingress

```yaml
apiVersion: v1
kind: Service
metadata:
  name: media-service
spec:
  selector:
    app: media-service
  ports:
  - port: 8080
    targetPort: 8080
  type: ClusterIP              # 内部服务，不对外暴露
```

VideoAgent 通过 K8s 内部 DNS 访问：`http://media-service.default.svc.cluster.local:8080`

---

## 8. MMAudio 音效提取 → S3 迁移

### 现状问题

`wavespeed_service.py` 中 WaveSpeed MMAudio 生成音效后，调用 `file_utils.extract_audio_from_video` 提取纯音频，存在两个问题：

1. **输出写入持久化目录**：提取的音频保存到 `get_media_dir(AUDIO)` (即 `../audios/extracted_audio_xxx.mp3`)，从不清理
2. **返回本地 URL**：返回 `/api/audios/extracted_audio_xxx.mp3` 格式的本地 URL，存入 `video_audio_effect_versions.audio_url` 字段
3. **Nginx 在提供服务**：这些本地 URL 通过 Nginx `location /api/audios/` 提供静态文件访问
4. **assembly 阶段依赖**：`video_assembly_service` 通过 `audio_effect_data['version'].audio_url` 读取这个本地 URL，用 `convert_media_url_to_local_path` 解析为本地路径后混音

### 为什么需要提取

WaveSpeed MMAudio 是 Video-to-Audio 模型：输入视频 → 输出带音效的视频文件（视频+音频合并）。但 assembly 需要**纯音频轨**独立操作：
- 视频可能被调速（匹配旁白时长），原合成视频不能直接用
- 音效需要以 30% 音量单独混入，和旁白分层混合

### 迁移方案

#### 短期修复（不依赖 media-service）

修改 `file_utils.extract_audio_from_video`，改为 **temp 文件 + 上传 S3 + 返回 S3 URL**：

```python
async def extract_audio_from_video(video_url: str, output_filename: str = None) -> str:
    """从视频提取音频 → 上传 S3 → 返回 CDN URL"""
    with tempfile.TemporaryDirectory() as temp_dir:
        # 1. 下载视频到 temp
        video_path = os.path.join(temp_dir, "input.mp4")
        await s3_utils.download_file(video_url, video_path)

        # 2. FFmpeg 提取音频到 temp
        audio_filename = f"{output_filename or uuid.uuid4().hex}.mp3"
        audio_path = os.path.join(temp_dir, audio_filename)
        cmd = ['ffmpeg', '-i', video_path, '-vn', '-acodec', 'mp3', '-ab', '192k', '-ar', '44100', '-y', audio_path]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
        await proc.communicate()

        # 3. 上传到 S3
        async with aiofiles.open(audio_path, 'rb') as f:
            audio_data = await f.read()
        audio_url = await s3_utils.upload_audio(audio_data, generation_id=output_filename)
        return audio_url  # 返回 S3 CDN URL，不再是 /api/audios/ 本地路径
    # temp_dir 自动清理
```

参考实现：`user_input_analysis_service.py` 的 `_extract_audio_from_video` 已经用了正确模式（temp + S3 + cleanup）。

#### 长期方案（media-service 接管）

迁移为 `POST /api/v1/audio/extract-from-video`，VideoAgent 不再本地处理 FFmpeg。

### 兼容性注意

修改后新生成的 `audio_url` 是 S3 CDN URL。已有的 DB 记录中 `audio_url` 仍为 `/api/audios/extracted_audio_xxx.mp3` 格式。需要保留 Nginx 和 `convert_media_url_to_local_path` 的旧路径兼容逻辑，直到所有旧记录的 assembly 完成。

---

## 9. 存储清理可行性分析

### 9.1 当前磁盘状态

```
/dev/root  436GB  414GB  23GB  95%
```

| 目录 | 大小 | 说明 |
|------|------|------|
| `/home/ubuntu/app/cartoonbook/data/videos/` | **212GB** | 29,395 个文件 |
| `/home/ubuntu/app/cartoonbook/data/audios/` | **20GB** | 17,106 个文件 |
| `/home/ubuntu/app/cartoonbook/data/images/` | **953MB** | 图片文件 |

### 9.2 文件分类

#### videos/ 目录 (29,395 个文件, 212GB)

| 类别 | 数量 | 来源 | DB 引用方式 | 能否安全删除 |
|------|------|------|------------|------------|
| **下载缓存** (`{uuid8}_{provider}_{name}`) | **23,252** | `download_s3_file_to_local` 每次新建 UUID 文件名，下载 S3 到本地 | **DB 存的是 S3 CDN URL**，本地文件仅作 FFmpeg 输入 | **可以删除** |
| **final_*** 输出 | **2,241** | `concatenate_video_segments_by_urls` 拼接输出 | 需确认：可能在旧 assembly 记录中有本地 URL | **谨慎** |
| **with_audio_*** 输出 | **1,507** | `merge_video_with_audio` 合并音视频输出 | 中间文件，正常流程上传 S3 后不再引用 | **可以删除** |
| **UUID 格式** (`xxxxxxxx-xxxx-...`) | **1,869** | 早期 `save_video` 或其他 legacy 代码 | 可能有旧 DB 记录引用 | **谨慎** |
| **adjusted_video_*** / **mixed_audio_*** 等 | **124** | assembly 中间产物 | 不存 DB | **可以删除** |
| 其他 | ~402 | 混合 | 需逐一分析 | **谨慎** |

#### audios/ 目录 (17,106 个文件, 20GB)

| 类别 | 数量 | 来源 | DB 引用方式 | 能否安全删除 |
|------|------|------|------------|------------|
| **下载缓存** (`{uuid8}_{name}`) | **13,153** | `download_s3_file_to_local` | DB 存 S3 URL | **可以删除** |
| **extracted_audio_*** | **1,423** | `extract_audio_from_video` | **DB 存本地 `/api/audios/` URL** | **不能直接删除** |
| 其他 | **2,530** | `ensure_duration`、`merge_audio` 等输出 | 部分可能被 DB 引用 | **谨慎** |

### 9.3 Nginx 提供服务确认

```nginx
location /api/videos/ { alias /home/ubuntu/app/cartoonbook/data/videos/; }
location /api/audios/ { alias /home/ubuntu/app/cartoonbook/data/audios/; }
location /api/photos/ { alias /home/ubuntu/app/cartoonbook/data/images/; }
```

Nginx **正在服务**这些文件。如果 DB 中有 `/api/videos/xxx.mp4` 格式的 URL 被前端或 assembly 引用，删除文件会导致 404。

### 9.4 安全清理建议

**第一步：立即可做（释放约 150-180GB）— 删除下载缓存**

```bash
# videos 目录：删除 download cache（{8字符uuid}_{provider}_{name} 模式）
# 这些文件的 DB 对应的是 S3 CDN URL，本地只是临时下载
find /home/ubuntu/app/cartoonbook/data/videos/ -name "[0-9a-f]*_wan26_*" -mtime +1 -delete
find /home/ubuntu/app/cartoonbook/data/videos/ -name "[0-9a-f]*_wavespeed_*" -mtime +1 -delete
find /home/ubuntu/app/cartoonbook/data/videos/ -name "[0-9a-f]*_seedance_*" -mtime +1 -delete
find /home/ubuntu/app/cartoonbook/data/videos/ -name "[0-9a-f]*_kling_*" -mtime +1 -delete
find /home/ubuntu/app/cartoonbook/data/videos/ -name "[0-9a-f]*_openai_sora_*" -mtime +1 -delete

# audios 目录：删除 download cache
find /home/ubuntu/app/cartoonbook/data/audios/ -regex '.*/[0-9a-f]\{8\}_.*' -mtime +1 -delete
```

保留最近 24 小时的，以免影响正在进行的任务。

**第二步：需要确认后才能做（释放约 20-40GB）— 删除 assembly 中间产物**

```bash
# 中间文件（不存 DB，可删）
find /home/ubuntu/app/cartoonbook/data/videos/ -name "adjusted_video_*" -mtime +1 -delete
find /home/ubuntu/app/cartoonbook/data/videos/ -name "*mixed_audio*" -mtime +1 -delete
find /home/ubuntu/app/cartoonbook/data/videos/ -name "video_with_effect_*" -mtime +1 -delete
find /home/ubuntu/app/cartoonbook/data/videos/ -name "processed_segment_*" -mtime +1 -delete
find /home/ubuntu/app/cartoonbook/data/videos/ -name "with_audio_*" -mtime +1 -delete
```

**第三步：需要查 DB 后再决定 — final_* 和 UUID 文件**

| 文件 | 问题 | 建议 |
|------|------|------|
| `final_*` (2,241 个) | 可能在 `video_assembly.final_video_url` 中以 `/api/videos/` URL 存储 | 需查 DB: `SELECT final_video_url FROM video_assemblies WHERE final_video_url LIKE '/api/videos/final_%'` |
| UUID 格式 (1,869 个) | 最新是 2025-11，全部在 S3 迁移前产生 | 如果所有 assembly 已完成则可删 |
| `extracted_audio_*` (1,423 个) | **确认存在 DB 引用** | 先修代码改用 S3，再迁移旧记录，最后删除 |

**不能删除**：
- `extracted_audio_*` — DB 中 `video_audio_effect_versions.audio_url` 直接引用
- 任何最近 24 小时内的文件 — 可能正在被 pipeline 使用

### 9.5 文件每月增长量

| 月份 | videos 新增文件 | 估计大小 |
|------|----------------|---------|
| 2025-10 | 5,258 | ~36GB |
| 2025-11 | 5,407 | ~37GB |
| 2025-12 | 5,760 | ~39GB |
| 2026-01 | 5,505 | ~38GB |
| 2026-02 | 5,144 | ~35GB |
| 2026-03 (9天) | 3,488 | ~24GB |

**每月约增长 35-39GB**，不清理的话月底就会磁盘 100%。

---

## 10. 实施顺序建议

### Phase 0（紧急，1-2 天）：止血 + 释放磁盘

**目的**：磁盘 95% 濒临爆满，每月增长 35GB+，必须先止血。

1. **修复 `extract_audio_from_video`**：改用 temp + S3 + cleanup（参考第 8 节方案）
2. **清理下载缓存**：删除 >24h 的 `{uuid8}_{provider}_{name}` 格式文件（videos/ 和 audios/）— 预计释放 **150-180GB**
3. **清理中间产物**：删除 >24h 的 `adjusted_video_*`、`mixed_audio_*`、`video_with_effect_*` 等
4. **查 DB 确认**：`final_*` 和 `extracted_audio_*` 文件的引用情况，确认后清理
5. **添加 cron job**：定期清理 >24h 的下载缓存文件，防止重新积累

### Phase 1（1-2 周）：基础 API + segment 迁移
1. 搭建 media-service 框架 (FastAPI + S3 client)
2. 实现原子 API: `/video/info`, `/video/trim`, `/video/concat`, `/video/normalize`, `/video/create-placeholder`
3. 实现 `/pipeline/segment-process`
4. 迁移 `video_segments_service.py` 中的所有 FFmpeg 调用
5. 实现 `/workspace/cleanup` + TTL 清理

### Phase 2（1 周）：assembly 迁移
1. 实现 `/video/add-audio`, `/video/mix-audio`, `/video/add-watermark`, `/video/strip-audio`
2. 实现 `/pipeline/video-assembly`
3. 迁移 `video_assembly_service.py` 中的所有调用

### Phase 3（1 周）：音频/图片 + 工具迁移
1. 实现 `/audio/*` API
2. 实现 `/image/resize`
3. 迁移 `wan25.py`, `wan26_flash.py`, `openai_sora_service.py`, `wavespeed_service.py` 中的调用
4. 迁移 `file_utils.py` 中的音频处理

### Phase 4（持续）：清理 + 监控
1. 删除 VideoAgent 中不再使用的 `video_utils.py` 函数
2. 删除 `convert_media_url_to_s3` 相关的持久化下载逻辑
3. 移除 Nginx 中 `/api/photos/`、`/api/videos/`、`/api/audios/` 的静态文件配置
4. 添加 Prometheus 监控 (FFmpeg 并发数、处理时间、队列深度)

---

## 附录：VideoAgent Regenerate 与本地 FFmpeg CPU（摘要）

与上文 **Media Service / Segment 阶段** 的 CPU 不同，以下为 **Agent 本机** 在 **多路 Regenerate**（关键帧/视频重生）时的 CPU 要点（原独立文档已合并进此附录）。

- **入口**：`POST .../regenerate-keyframes`、`POST .../regenerate-videos`；单次请求内为**顺序**执行，CPU 飙高主要来自**多个 HTTP 请求并发**（用户连点或多 tab），叠加多路 LLM、图像/视频 API、本地 **ffmpeg**。
- **ffmpeg**：`video_assembly_service` 等路径若使用 `-threads 0` 会占满多核；多段 ffmpeg 与 assembly 下载并发（如默认 `video_assembly_download` 限制）同时存在时，整机 CPU 易打满。
- **可选手段**：限制同时进行的 regenerate/assembly 并发、将 ffmpeg **线程数**改为可配置（例如默认 2）、对 CPU 密集型任务做全局队列/信号量；轮询等待视频 API **几乎不占 CPU**。
- **监控**：整机 100% 为所有进程合计，需结合 `top`/`ps` 区分是否本进程为主因。
