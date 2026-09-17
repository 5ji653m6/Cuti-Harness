"""
Video and other multimedia utilities.

``prepare_video_for_llm``: download a URL or read a local file -> prefer uploading to Google to get ``file_uri``, fall back to base64 for small files.
HTTP download uses ``aiohttp`` (no dependency on ``s3_utils``).

``process_uploaded_files``: reads FastAPI ``UploadFile`` into memory and uploads to S3,
returning a list of ``ImageUserInput`` / ``AudioFileUserInput`` / ``VideoFileUserInput``.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import pathlib
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiofiles
import aiohttp

from app.chat.exceptions import BusinessException, BusinessExceptionCode
from app.chat.utils.google_file_upload import upload_video_to_google
from app.chat.utils import media_service_client as msc

logger = logging.getLogger(__name__)


async def _maybe_audio_duration_from_msc(audio_url: str) -> Optional[float]:
    """Call the media service's ``audio/info`` after uploading to S3."""
    try:
        info = await msc.audio_info(audio_url)
        if not isinstance(info, dict):
            return None
        for key in ("duration", "duration_sec", "duration_seconds", "length"):
            v = info.get(key)
            if v is not None:
                try:
                    return round(float(v), 2)
                except (TypeError, ValueError):
                    continue
    except Exception as exc:
        logger.warning("audio_info failed url=%s err=%s", (audio_url or "")[:80], exc)
    return None


SUPPORTED_VIDEO_EXTENSIONS = (
    ".mp4",
    ".mpeg",
    ".mov",
    ".avi",
    ".flv",
    ".mpg",
    ".webm",
    ".wmv",
    ".3gpp",
)
SUPPORTED_VIDEO_MIMETYPES = (
    "video/mp4",
    "video/mpeg",
    "video/quicktime",
    "video/avi",
    "video/x-msvideo",
    "video/x-flv",
    "video/mpg",
    "video/webm",
    "video/wmv",
    "video/3gpp",
)


class VideoContentForLLM:
    """Structured data for video content used by the LLM."""

    def __init__(
        self,
        use_file_uri: bool,
        file_uri: Optional[str] = None,
        base64_data: Optional[str] = None,
        mime_type: str = "video/mp4",
    ):
        self.use_file_uri = use_file_uri
        self.file_uri = file_uri
        self.base64_data = base64_data
        self.mime_type = mime_type

    def to_media_content(self) -> Dict[str, Any]:
        if self.use_file_uri and self.file_uri:
            return {"type": "media", "file_uri": self.file_uri, "mime_type": self.mime_type}
        if self.base64_data:
            return {"type": "media", "data": self.base64_data, "mime_type": self.mime_type}
        raise ValueError("VideoContentForLLM: 既没有 file_uri 也没有 base64_data")


async def _download_url_to_path(url: str, dest_path: str) -> bool:
    try:
        timeout = aiohttp.ClientTimeout(total=600)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning("prepare_video_for_llm: GET %s -> %s", url[:120], resp.status)
                    return False
                data = await resp.read()
        async with aiofiles.open(dest_path, "wb") as f:
            await f.write(data)
        return True
    except Exception as e:
        logger.warning("prepare_video_for_llm: 下载失败 %s", e)
        return False


async def prepare_video_for_llm(
    video_path: Optional[str] = None,
    video_url: Optional[str] = None,
    mime_type: Optional[str] = None,
    max_wait_time: int = 180,
    max_base64_size_mb: float = 20.0,
) -> VideoContentForLLM:
    """
    Prepare video content for the LLM (prefer ``file_uri``, fall back to base64).
    """
    temp_file_path: Optional[str] = None
    need_cleanup = False

    try:
        if video_path:
            if not Path(video_path).exists():
                raise BusinessException(
                    BusinessExceptionCode.FILE_UPLOAD_FAILED,
                    f"视频文件不存在: {video_path}",
                )
            actual_video_path = video_path
            logger.info("prepare_video_for_llm: 本地文件 %s", video_path)
        elif video_url:
            video_ext = Path(video_url).suffix.lower() or ".mp4"
            tmp = tempfile.NamedTemporaryFile(suffix=video_ext, delete=False)
            temp_file_path = tmp.name
            tmp.close()
            need_cleanup = True
            ok = await _download_url_to_path(video_url, temp_file_path)
            if not ok:
                raise BusinessException(
                    BusinessExceptionCode.FILE_UPLOAD_FAILED,
                    f"无法下载视频: {video_url}",
                )
            actual_video_path = temp_file_path
            logger.info("prepare_video_for_llm: 已下载 URL 到 %s", temp_file_path)
        else:
            raise ValueError("必须提供 video_path 或 video_url 之一")

        if not mime_type:
            video_ext = Path(actual_video_path).suffix.lower()
            ext_to_mime = dict(zip(SUPPORTED_VIDEO_EXTENSIONS, SUPPORTED_VIDEO_MIMETYPES))
            mime_type = ext_to_mime.get(video_ext, "video/mp4")

        file_size_mb = os.path.getsize(actual_video_path) / (1024 * 1024)
        logger.info("prepare_video_for_llm: 文件大小 %.2f MB", file_size_mb)

        file_uri, google_mime = await upload_video_to_google(actual_video_path, max_wait_time=max_wait_time)

        if file_uri:
            effective_mime = google_mime or mime_type
            logger.info("prepare_video_for_llm: 使用 Google file_uri, mime=%s", effective_mime)
            return VideoContentForLLM(
                use_file_uri=True,
                file_uri=file_uri,
                mime_type=effective_mime,
            )

        logger.warning("prepare_video_for_llm: Google 上传失败，尝试 base64 降级")
        if file_size_mb > max_base64_size_mb:
            raise BusinessException(
                BusinessExceptionCode.FILE_UPLOAD_FAILED,
                f"视频过大（{file_size_mb:.2f}MB），超过 {max_base64_size_mb}MB 且无法使用 file_uri",
            )

        async with aiofiles.open(actual_video_path, "rb") as f:
            video_bytes = await f.read()
        b64 = (await asyncio.to_thread(base64.b64encode, video_bytes)).decode("utf-8")
        return VideoContentForLLM(use_file_uri=False, base64_data=b64, mime_type=mime_type or "video/mp4")

    finally:
        if need_cleanup and temp_file_path:
            try:
                os.unlink(temp_file_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# user multipart upload (for the agent-router /stream)
# ---------------------------------------------------------------------------

SUPPORTED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
SUPPORTED_AUDIO_EXTENSIONS = (".wav", ".mp3", ".aiff", ".aac", ".ogg", ".flac")
SUPPORTED_VIDEO_EXTENSIONS = (".mp4", ".mpeg", ".mov", ".avi", ".flv", ".mpg", ".webm", ".wmv", ".3gpp")

MAX_IMAGE_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_AUDIO_UPLOAD_BYTES = 70 * 1024 * 1024
MAX_VIDEO_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024
_UPLOAD_READ_CHUNK = 1024 * 1024


def max_upload_bytes_for_file_type(file_type: str) -> int:
    return {
        "image": MAX_IMAGE_UPLOAD_BYTES,
        "audio": MAX_AUDIO_UPLOAD_BYTES,
        "video": MAX_VIDEO_UPLOAD_BYTES,
    }.get(file_type, 0)


def _upload_too_large(filename: str, file_type: str, limit: int) -> BusinessException:
    return BusinessException(
        BusinessExceptionCode.FILE_TOO_LARGE,
        f"{filename} exceeds the {file_type} size limit ({limit} bytes)",
    )


def assert_upload_size(file_type: str, size: int, filename: str) -> None:
    limit = max_upload_bytes_for_file_type(file_type)
    if limit <= 0:
        raise BusinessException(BusinessExceptionCode.UNSUPPORTED_FILE_FORMAT)
    if size > limit:
        raise _upload_too_large(filename, file_type, limit)


def _declared_upload_size(file: Any) -> Optional[int]:
    raw = getattr(file, "size", None)
    try:
        size = int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None
    if size is None or size < 0:
        return None
    return size


async def read_uploaded_file_capped(file: Any, *, file_type: str, filename: str) -> bytes:
    """Read an UploadFile up to the per-type cap. Abort before buffering an oversized body."""
    limit = max_upload_bytes_for_file_type(file_type)
    if limit <= 0:
        raise BusinessException(BusinessExceptionCode.UNSUPPORTED_FILE_FORMAT)
    declared = _declared_upload_size(file)
    if declared is not None and declared > limit:
        raise _upload_too_large(filename, file_type, limit)
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_READ_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise _upload_too_large(filename, file_type, limit)
        chunks.append(chunk)
    return b"".join(chunks)

SUPPORTED_IMAGE_MIMETYPES = ("image/png", "image/jpeg", "image/webp")
SUPPORTED_AUDIO_MIMETYPES = (
    "audio/wav",
    "audio/x-wav",
    "audio/mpeg",
    "audio/aiff",
    "audio/aac",
    "audio/ogg",
    "audio/flac",
)
SUPPORTED_VIDEO_MIMETYPES = (
    "video/mp4",
    "video/mpeg",
    "video/quicktime",
    "video/avi",
    "video/x-msvideo",
    "video/x-flv",
    "video/mpg",
    "video/webm",
    "video/wmv",
    "video/3gpp",
)


def get_file_type(filename: str, content_type: str = None) -> str:
    """
    Determine the file type from the file name and content_type.
    Matches the behavior of ``get_file_type``.
    """
    file_ext = pathlib.Path(filename).suffix.lower()
    content_type = content_type or ""

    if content_type.startswith("image/"):
        if file_ext in SUPPORTED_IMAGE_EXTENSIONS and content_type in SUPPORTED_IMAGE_MIMETYPES:
            return "image"
        return "unknown"
    if content_type.startswith("audio/"):
        if file_ext in SUPPORTED_AUDIO_EXTENSIONS and content_type in SUPPORTED_AUDIO_MIMETYPES:
            return "audio"
        return "unknown"
    if content_type.startswith("video/"):
        if file_ext in SUPPORTED_VIDEO_EXTENSIONS and content_type in SUPPORTED_VIDEO_MIMETYPES:
            return "video"
        return "unknown"
    if file_ext in SUPPORTED_IMAGE_EXTENSIONS:
        return "image"
    if file_ext in SUPPORTED_AUDIO_EXTENSIONS:
        return "audio"
    if file_ext in SUPPORTED_VIDEO_EXTENSIONS:
        return "video"
    return "unknown"


async def process_uploaded_files(files: List) -> tuple:
    """
    Process uploaded files, upload to S3, and return a list of structured objects.
    """
    from app.models.video_state import AudioFileUserInput, ImageUserInput, VideoFileUserInput
    from app.chat.utils.s3_utils import s3_utils

    images = []
    audio_files = []
    video_files = []

    if not files or not files[0].filename:
        return images, audio_files, video_files

    try:
        for file in files:
            if not file.filename:
                continue

            content_type = file.content_type or ""
            filename = file.filename
            file_type = get_file_type(filename, content_type)
            if file_type == "unknown":
                logger.warning("Unsupported file: %s (content_type=%s)", filename, content_type)
                raise BusinessException(BusinessExceptionCode.UNSUPPORTED_FILE_FORMAT)

            content = await read_uploaded_file_capped(
                file, file_type=file_type, filename=filename,
            )
            if not content:
                continue

            if file_type == "image":
                url = await s3_utils.upload_image(content, content_type=content_type)
                images.append(ImageUserInput(url=url, filename=filename))
                logger.info("Image uploaded: %s -> %s", filename, url)

            elif file_type == "audio":
                url = await s3_utils.upload_audio(content, filename=filename, content_type=content_type)
                audio_duration = await _maybe_audio_duration_from_msc(url)
                audio_files.append(AudioFileUserInput(url=url, filename=filename, duration=audio_duration))
                logger.info("Audio uploaded: %s -> %s duration=%s", filename, url, audio_duration)

            elif file_type == "video":
                url = await s3_utils.upload_video(content, filename=filename, content_type=content_type)
                video_files.append(VideoFileUserInput(url=url, filename=filename))
                logger.info("Video uploaded: %s -> %s", filename, url)

            else:
                logger.warning("Unsupported file: %s (content_type=%s)", filename, content_type)
                raise BusinessException(BusinessExceptionCode.UNSUPPORTED_FILE_FORMAT)

    except BusinessException:
        raise
    except Exception:
        raise BusinessException(BusinessExceptionCode.FILE_UPLOAD_FAILED)

    logger.info(
        "process_uploaded_files done: %s images, %s audio, %s video",
        len(images),
        len(audio_files),
        len(video_files),
    )
    return images, audio_files, video_files
