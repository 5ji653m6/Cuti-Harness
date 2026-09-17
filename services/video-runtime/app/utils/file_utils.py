"""
File utility functions
Includes saving, downloading, and converting images, audio, and video

Functional modules:
1. Image processing: save, format conversion, WebP compression
2. Audio processing: save, format conversion, mixing
3. Video processing: download, audio mixing, format conversion
4. File upload: handle FastAPI UploadFile, upload to S3

Use cases:
- Tools save generated media files
- Agent processes user-uploaded files
- Media processing during video composition
"""
import os
import logging
import asyncio
import base64
import uuid
import pathlib
from typing import Dict, Any, Optional
from enum import Enum
from app.config import settings
from app.exceptions import BusinessException, BusinessExceptionCode
from PIL import Image
import io
import aiohttp
import aiofiles
from . import media_service_client as msc


class ImageFormat(str, Enum):
    """Image format enum."""
    URL = "url"              # full URL with domain
    BASE64 = "base64"        # base64-encoded data
    LOCAL_PATH = "local_path" # local file path


class MediaType(str, Enum):
    """Media type enum."""
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"


class MediaFormat(str, Enum):
    """Media format enum."""
    URL = "url"              # full URL with domain
    BASE64 = "base64"        # base64-encoded data
    LOCAL_PATH = "local_path" # local file path

logger = logging.getLogger(__name__)

def convert_image_url_to_local_path(image_url: str) -> str:
    """
    Convert an image_url to a local filesystem path.
    Supports: /api/photos/xxx.png, api/photos/xxx.png, https://domain.com/api/photos/xxx.png
    """
    # if it is a full URL, extract the path part
    if image_url.startswith(('http://', 'https://')):
        from urllib.parse import urlparse
        parsed = urlparse(image_url)
        path_part = parsed.path.lstrip('/')
    else:
        # handle cases starting or not starting with /
        path_part = image_url.lstrip('/')

    if path_part.startswith("api/photos/"):
        filename = path_part.replace("api/photos/", "")
        return os.path.join(settings.STATIC_PHOTOS_DIR, filename)

    # if it is already a local path, return it directly
    if os.path.isabs(image_url) and os.path.exists(image_url):
        return image_url

    # if it is a relative path, try to find it in the static directory
    if not image_url.startswith(('http://', 'https://')):
        potential_path = os.path.join(settings.STATIC_PHOTOS_DIR, image_url)
        if os.path.exists(potential_path):
            return potential_path

    return image_url


async def convert_image_url(image_url: str, target_format: ImageFormat) -> Optional[str]:
    """
    Generic image-URL conversion method.

    Args:
        image_url: input image URL (supports /api/photos relative paths and full URLs)
        target_format: target format (URL/BASE64/LOCAL_PATH)

    Returns:
        the converted image data, None on failure
    """
    if not image_url:
        return None

    try:
        # if it is a relative path starting with /api/photos, first convert to a full URL
        if image_url.startswith("/api/photos/") or image_url.startswith("api/photos/"):
            # build the full URL
            if settings.BASE_URL and settings.BASE_URL != "http://localhost:8000":
                base_url = settings.BASE_URL.rstrip('/')
                if image_url.startswith("/"):
                    full_url = f"{base_url}{image_url}"
                else:
                    full_url = f"{base_url}/{image_url}"
            else:
                # dev environment, build the full URL from the relative path
                if image_url.startswith("/"):
                    full_url = f"http://localhost:8000{image_url}"
                else:
                    full_url = f"http://localhost:8000/{image_url}"
        else:
            # already a full URL or another format
            full_url = image_url

        # convert according to the target format
        if target_format == ImageFormat.URL:
            return full_url

        elif target_format == ImageFormat.LOCAL_PATH:
            return convert_image_url_to_local_path(image_url)

        elif target_format == ImageFormat.BASE64:
            return await convert_image_url_to_base64(image_url)

        else:
            logger.error(f"不支持的目标格式: {target_format}")
            return None

    except Exception as e:
        logger.error(f"图像URL转换失败: {image_url} -> {target_format}, 错误: {e}")
        return None


_IMAGE_MIME_BY_EXT = {
    ".webp": "image/webp",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


async def inline_local_image_url_for_llm(image_url: str) -> str:
    """
    Convert a locally stored image URL into a data URI, to avoid the LLM SDK synchronously fetching http://localhost:8000/files/...

    Under local STORAGE_BACKEND=local, remote model SDKs cannot directly read a local image_url;
    if that URL points to the uvicorn this process is running, it deadlocks the event loop (self-call deadlock). Reading from disk inline avoids HTTP.
    Returns as-is for non-local URLs / already data: / read failure.
    """
    if not image_url or not isinstance(image_url, str):
        return image_url
    url = image_url.strip()
    if not url or url.startswith("data:"):
        return image_url
    try:
        from app.utils.s3_utils import s3_utils, is_our_cdn_url, _storage_is_local

        if not _storage_is_local():
            return image_url
        if not is_our_cdn_url(url):
            return image_url
        file_key = s3_utils.cdn_url_to_s3_key(url)
        if not file_key:
            return image_url
        local_path = os.path.join(s3_utils._local_dir, file_key)
        if not os.path.isfile(local_path):
            logger.warning("inline_local_image_url_for_llm: file missing %s", local_path)
            return image_url
        raw = await asyncio.to_thread(pathlib.Path(local_path).read_bytes)
        ext = pathlib.Path(local_path).suffix.lower()
        mime = _IMAGE_MIME_BY_EXT.get(ext, "image/webp")
        b64 = base64.b64encode(raw).decode("ascii")
        logger.info(
            "inline_local_image_url_for_llm: inlined %s (%d bytes, %s)",
            file_key,
            len(raw),
            mime,
        )
        return f"data:{mime};base64,{b64}"
    except Exception as e:
        logger.warning("inline_local_image_url_for_llm failed url=%s err=%s", image_url[:120], e)
        return image_url


async def convert_image_url_to_base64(image_url: str) -> Optional[str]:
    """
    Convert an image URL to base64 encoding.

    Args:
        image_url: image URL (supports relative and absolute paths)

    Returns:
        base64-encoded image data, None on failure
    """
    import aiofiles

    try:
        # convert the URL to a local path
        local_path = convert_image_url_to_local_path(image_url)
        if not local_path or not os.path.exists(local_path):
            logger.warning(f"⚠️ 无法转换图像URL到本地路径或文件不存在: {image_url}")
            return None

        # use aiofiles for asynchronous file reading
        async with aiofiles.open(local_path, 'rb') as img_file:
            image_data = await img_file.read()
            base64_data = await asyncio.to_thread(base64.b64encode, image_data)
            base64_str = base64_data.decode('utf-8')
            logger.debug(f"✅ 图像转换为base64成功: {image_url}")
            return base64_str

    except Exception as e:
        logger.error(f"❌ 图像转换base64失败 {image_url}: {e}")
        return None


def get_media_dir(media_type: MediaType) -> str:
    """Get the media directory path."""
    if media_type == MediaType.IMAGE:
        return settings.STATIC_PHOTOS_DIR
    elif media_type == MediaType.AUDIO:
        return os.path.join(settings.STATIC_PHOTOS_DIR, "../audios")
    elif media_type == MediaType.VIDEO:
        return os.path.join(settings.STATIC_PHOTOS_DIR, "../videos")
    else:
        raise ValueError(f"不支持的媒体类型: {media_type}")


def _safe_unlink(*paths: str):
    """Safely delete a local file (cleanup after uploading to S3, to prevent storage leaks)."""
    for p in paths:
        if p and os.path.isfile(p):
            try:
                os.unlink(p)
            except OSError:
                pass


async def extract_audio_from_video(
    video_url: str,
    output_filename: Optional[str] = None
) -> Optional[str]:
    """
    Extract audio from a video file, upload to S3, and return the CDN URL.
    Uses a temp directory, auto-cleaned after processing; no longer writes to a persistent local directory.

    Args:
        video_url: video file URL (S3 CDN URL or /api/videos/ format)
        output_filename: output file name (without extension); uses a UUID if None

    Returns:
        the extracted audio S3 CDN URL; None when the video has no audio track (MSC returns result_url=null)
    """
    result = await msc.audio_extract(video_url, run_id=uuid.uuid4().hex[:12])
    return result.get("result_url")


SUPPORTED_VIDEO_EXTENSIONS = ('.mp4', '.mpeg', '.mov', '.avi', '.flv', '.mpg', '.webm', '.wmv', '.3gpp')
SUPPORTED_VIDEO_MIMETYPES = ('video/mp4', 'video/mpeg', 'video/quicktime', 'video/avi', 'video/x-msvideo', 'video/x-flv', 'video/mpg', 'video/webm', 'video/wmv', 'video/3gpp')


class VideoContentForLLM:
    """Structured data for video content used by the LLM."""
    def __init__(self, use_file_uri: bool, file_uri: Optional[str] = None, base64_data: Optional[str] = None, mime_type: str = "video/mp4"):
        self.use_file_uri = use_file_uri
        self.file_uri = file_uri
        self.base64_data = base64_data
        self.mime_type = mime_type

    def to_media_content(self) -> Dict[str, Any]:
        """Convert to the media content format in an LLM message."""
        if self.use_file_uri and self.file_uri:
            return {
                "type": "media",
                "file_uri": self.file_uri,
                "mime_type": self.mime_type
            }
        elif self.base64_data:
            return {
                "type": "media",
                "data": self.base64_data,
                "mime_type": self.mime_type
            }
        else:
            raise ValueError("VideoContentForLLM: 既没有 file_uri 也没有 base64_data")


async def prepare_video_for_llm(
    video_path: Optional[str] = None,
    video_url: Optional[str] = None,
    mime_type: Optional[str] = None,
    max_wait_time: int = 180,
    max_base64_size_mb: float = 20.0
) -> VideoContentForLLM:
    """
    Prepare video content for the LLM (prefer file_uri, fall back to base64).

    Behavior:
    - If video_path is provided, use it directly
    - If video_url is provided, download it to a temp file first
    - Try uploading to Google to get a file_uri (bypassing the LangSmith size limit)
    - If upload fails, fall back to base64 (but check the size limit)

    Args:
        video_path: local video file path
        video_url: video URL (needs downloading first)
        mime_type: video MIME type; inferred from the file extension if not provided
        max_wait_time: max wait time (seconds) for uploading to Google, default 300s (5 minutes)
        max_base64_size_mb: max file size (MB) for the base64 fallback, default 20MB (~26MB after base64)

    Returns:
        VideoContentForLLM: an object containing file_uri or base64_data

    Raises:
        BusinessException: if the video file is too large or processing fails
    """
    import tempfile
    import os
    from pathlib import Path
    from app.utils.s3_utils import s3_utils
    from app.utils.google_file_upload import upload_video_to_google
    from app.exceptions import BusinessException, BusinessExceptionCode

    temp_file_path = None
    need_cleanup = False

    try:
        # 1. Determine the video file path
        if video_path:
            if not Path(video_path).exists():
                raise BusinessException(
                    BusinessExceptionCode.FILE_UPLOAD_FAILED,
                    f"视频文件不存在: {video_path}"
                )
            actual_video_path = video_path
            logger.info(f"📁 处理本地视频文件: {video_path}")
        elif video_url:
            # download the video to a temp file
            video_ext = Path(video_url).suffix.lower() or '.mp4'
            temp_file = tempfile.NamedTemporaryFile(suffix=video_ext, delete=False)
            temp_file_path = temp_file.name
            temp_file.close()
            need_cleanup = True

            success = await s3_utils.download_file(video_url, temp_file_path)
            if not success:
                raise BusinessException(
                    BusinessExceptionCode.FILE_UPLOAD_FAILED,
                    f"无法下载视频文件: {video_url}"
                )
            actual_video_path = temp_file_path
            logger.info(f"📹 处理视频URL: {video_url}, 下载到: {temp_file_path}")
        else:
            raise ValueError("必须提供 video_path 或 video_url 之一")

        # 2. Determine the MIME type
        if not mime_type:
            video_ext = Path(actual_video_path).suffix.lower()
            ext_to_mime_map = dict(zip(SUPPORTED_VIDEO_EXTENSIONS, SUPPORTED_VIDEO_MIMETYPES))
            mime_type = ext_to_mime_map.get(video_ext, 'video/mp4')

        # 3. Check the file size
        file_size_mb = os.path.getsize(actual_video_path) / (1024 * 1024)
        logger.info(f"📊 视频文件大小: {file_size_mb:.2f} MB")

        # 4. Try uploading to Google to get a file_uri (bypassing the LangSmith size limit)
        file_uri, google_mime = await upload_video_to_google(actual_video_path, max_wait_time=max_wait_time)

        if file_uri:
            # ⚠️ When using file_uri, mime_type must be the actual type recognized by the Google Files API,
            # otherwise Gemini returns 400 Invalid argument (verified with audio)
            effective_mime = google_mime or mime_type
            logger.info(f"✅ 视频已上传到 Google，使用 file_uri: {file_uri}, mime_type: {effective_mime}")
            return VideoContentForLLM(
                use_file_uri=True,
                file_uri=file_uri,
                mime_type=effective_mime
            )
        else:
            # 5. Fallback: use base64 (if the file is not too large)
            logger.warning(f"⚠️ 上传到 Google 失败，降级使用 base64")
            if file_size_mb > max_base64_size_mb:
                raise BusinessException(
                    BusinessExceptionCode.FILE_UPLOAD_FAILED,
                    f"视频文件过大（{file_size_mb:.2f}MB），无法处理（超过 {max_base64_size_mb}MB 限制）"
                )

            async with aiofiles.open(actual_video_path, 'rb') as f:
                video_bytes = await f.read()
            base64_raw = await asyncio.to_thread(base64.b64encode, video_bytes)
            base64_data = base64_raw.decode("utf-8")

            logger.info(f"✅ 使用 base64 编码（大小: {file_size_mb:.2f}MB）")
            return VideoContentForLLM(
                use_file_uri=False,
                base64_data=base64_data,
                mime_type=mime_type
            )

    finally:
        # clean up the temp file
        if need_cleanup and temp_file_path:
            try:
                os.unlink(temp_file_path)
            except:
                pass
