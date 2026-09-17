from pathlib import Path
import tempfile
from typing import Optional

from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache

# project root (/app inside the container): same source as the video runtime's app/assets/watermark.png
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _settings_env_files() -> list[str]:
    """Local monorepo may load repo-root .env; container /app has no parents[1]."""
    files: list[str] = [".env"]
    try:
        files.insert(0, str(_PROJECT_ROOT.parents[1] / ".env"))
    except IndexError:
        pass
    return files


class Settings(BaseSettings):
    environment: str = Field(default="development")
    log_level: str = Field(default="info")
    port: int = Field(default=8080)

    # Storage backend: "local" (default, self-hosted local disk) | "s3" (optional object storage)
    # uses the same switch names as the agent project (STORAGE_BACKEND / LOCAL_STORAGE_DIR / PUBLIC_BASE_URL),
    # in local mode shares the same LOCAL_STORAGE_DIR as the agent, served via the agent's /files static mount.
    storage_backend: str = Field(default="local", description="s3 | local")
    local_storage_dir: str = Field(
        default="",
        description="local 后端落地目录；应与 agent 的 LOCAL_STORAGE_DIR 指向同一路径以共享文件",
    )
    public_base_url: str = Field(
        default="",
        description="local 后端对外访问基址（与 agent 一致，如 http://localhost:8000）；产出 URL 形如 {public_base_url}/files/{key}",
    )

    # AWS S3 (used when storage_backend=s3; can all be left empty in local mode, no AWS credentials needed)
    aws_access_key_id: str = Field(default="")
    aws_secret_access_key: str = Field(default="")
    aws_region: str = Field(default="ap-southeast-2")
    s3_bucket: str = Field(default="cuti-media")
    s3_cdn_prefix: str = Field(default="")
    s3_endpoint_url: str = Field(
        default="",
        description="S3 兼容存储自定义端点（如 MinIO）；留空走真实 AWS S3",
    )

    # FFmpeg
    ffmpeg_threads: int = Field(default=2)
    max_concurrent_jobs: int = Field(default=3)
    request_timeout: int = Field(default=1200, description="Global timeout for long operations (seconds)")
    subtitle_font_name: str = Field(
        default="",
        description="Optional libass font family for burned subtitles; auto-detects a CJK font when empty",
    )
    subtitle_fonts_dir: str = Field(
        default="",
        description="Optional directory containing subtitle fonts, passed to FFmpeg/libass as fontsdir",
    )
    trim_shorten_hybrid: bool = Field(
        default=True,
        description="截短：关键帧前 copy + 仅尾部 ultrafast + concat；失败抛错。false=整段 -t ultrafast",
    )
    # source shorter than target (mode=freeze_or_tail_slow): small gap uses a still-frame concat copy; large gap slows the tail or evenly slows the whole clip
    trim_extend_freeze_max_sec: float = Field(
        default=0.2,
        description="0<gap≤此值：整段视频轨 copy + 仅编码最后一帧静帧小条再 concat copy（主片不重编码）",
    )
    trim_extend_tail_min_sec: float = Field(default=0.4, description="尾部减速段最小长度（秒）")
    trim_extend_tail_max_sec: float = Field(default=3.0, description="尾部减速段最大长度（秒）")
    trim_extend_tail_fraction: float = Field(
        default=0.25, description="尾部减速段长度≈min(max,fraction*片长)"
    )
    trim_extend_tail_max_slow_factor: float = Field(
        default=1.35,
        description="尾部最多放慢倍数 (L+gap)/L；超出则加大 L 或改整片 setpts=T/d",
    )

    # Watermark (overlaid during ensure-on-s3 normalization; same source as the video runtime / frontend watermark.png)
    watermark_image_path: str = Field(
        default="assets/watermark.png",
        description="Path to watermark logo (relative to project root or absolute); empty to disable",
    )

    # Workspace
    workspace_base: str = Field(
        default=str(Path(tempfile.gettempdir()) / "cuti-media-workspace")
    )
    workspace_ttl_hours: int = Field(default=2)
    workspace_auto_cleanup: bool = Field(
        default=True,
        description="写操作上传 S3 后立即清理该 run_id 工作区，避免长任务（如 66 段增量 concat 重下前缀）把 EmptyDir 顶满被驱逐；本地文件用完即弃，下游均从 S3 重新拉取。设为 false 回退到仅 TTL 清理。",
    )

    model_config = {
        "env_file": _settings_env_files(),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


def resolve_watermark_image_path(configured: str = "") -> Optional[str]:
    """Resolve the watermark image path; relative paths resolve against the project root (matching the video runtime's VIDEO_WATERMARK_IMAGE_PATH behavior)."""
    candidate = (configured or "").strip()
    if not candidate:
        return None
    p = Path(candidate)
    if not p.is_absolute():
        p = _PROJECT_ROOT / p
    resolved = p.resolve()
    return str(resolved) if resolved.is_file() else None


@lru_cache
def get_settings() -> Settings:
    return Settings()
