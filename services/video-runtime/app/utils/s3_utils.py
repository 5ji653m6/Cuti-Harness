import os
import logging
import shutil
import tempfile
import uuid
import base64
import io
import boto3
import asyncio
import aiohttp
from typing import Optional, Tuple
from urllib.parse import urlparse


def _local_public_base() -> str:
    """Local storage public base URL (PUBLIC_BASE_URL, defaults to http://localhost:8000)."""
    base = (getattr(settings, "PUBLIC_BASE_URL", "") or "").strip()
    return (base or "http://localhost:8000").rstrip("/")


def _storage_is_local() -> bool:
    return (getattr(settings, "STORAGE_BACKEND", "local") or "local").lower() == "local"


def is_our_cdn_url(url: str) -> bool:
    """Decide whether a URL is "ours" (our storage).
    - s3 backend: matches the netloc of settings.CDN_DOMAIN;
    - local backend: additionally recognizes the netloc of PUBLIC_BASE_URL (the local /files service).
    """
    if not url or not url.strip():
        return False
    try:
        netloc = urlparse(url.strip()).netloc
        if netloc == urlparse(settings.CDN_DOMAIN).netloc:
            return True
        if _storage_is_local() and netloc == urlparse(_local_public_base()).netloc:
            return True
        return False
    except Exception:
        return False
from PIL import Image
from app.config import settings
from app.exceptions import BusinessException, BusinessExceptionCode
from app.utils import media_service_client as msc

logger = logging.getLogger(__name__)

class S3Utils:
    """S3 utility class, for handling file uploads to S3."""

    def __init__(self):
        self._is_local = _storage_is_local()
        self.bucket_name = settings.S3_BUCKET_NAME
        if self._is_local:
            # local filesystem backend: no S3 client / AWS credentials needed
            self.s3_client = None
            self._local_dir = os.path.abspath(getattr(settings, "LOCAL_STORAGE_DIR", "./data/uploads"))
            os.makedirs(self._local_dir, exist_ok=True)
            # public URL prefix: {PUBLIC_BASE_URL}/files -- consistent with standalone's /files static mount
            self.cdn_domain = f"{_local_public_base()}/files"
            logger.info(f"🗂️ 存储后端=local，落地目录={self._local_dir}，URL 前缀={self.cdn_domain}")
        else:
            self.s3_client = self._build_s3_client()
            self.cdn_domain = settings.CDN_DOMAIN

    @staticmethod
    def _build_s3_client():
        """Build the S3 client. Defaults to AWS S3; switches to MinIO or other compatible storage when S3_ENDPOINT_URL is configured."""
        endpoint_url = getattr(settings, "S3_ENDPOINT_URL", None)
        if not endpoint_url:
            return boto3.client('s3', region_name=settings.AWS_REGION)
        from botocore.config import Config as _BotoConfig
        return boto3.client(
            's3',
            region_name=settings.AWS_REGION,
            endpoint_url=endpoint_url,
            aws_access_key_id=getattr(settings, "S3_ACCESS_KEY_ID", None),
            aws_secret_access_key=getattr(settings, "S3_SECRET_ACCESS_KEY", None),
            config=_BotoConfig(s3={"addressing_style": "path"}),
        )

    _IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"

    def _upload_file_sync(self, file_data: bytes, file_key: str, content_type: str = None) -> str:
        """Sync upload, for run_in_executor. The local backend writes to local disk; the s3 backend does put_object."""
        try:
            if self._is_local:
                dest = os.path.join(self._local_dir, file_key)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as f:
                    f.write(file_data)
                url = f"{self.cdn_domain}/{file_key}"
                logger.info(f"Successfully saved file to local storage: {dest}, URL: {url}")
                return url
            extra_args = {"CacheControl": self._IMMUTABLE_CACHE_CONTROL}
            if content_type:
                extra_args['ContentType'] = content_type
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=file_key,
                Body=file_data,
                **extra_args
            )
            cdn_url = f"{self.cdn_domain}/{file_key}"
            logger.info(f"Successfully uploaded file to S3: {file_key}, CDN URL: {cdn_url}")
            return cdn_url
        except Exception as e:
            logger.error(f"Error uploading file to storage: {e}")
            raise BusinessException(
                BusinessExceptionCode.BUSINESS_ERROR,
                f"文件上传失败: {str(e)}"
            )

    def upload_file_sync(self, file_data: bytes, file_key: str, content_type: str = None) -> str:
        """Sync upload (only for code already inside run_in_executor, e.g. openai_sora._download_and_save_video_sync)."""
        return self._upload_file_sync(file_data, file_key, content_type)

    async def upload_file(self, file_data: bytes, file_key: str, content_type: str = None) -> str:
        """
        Upload a file to S3 (async, internally run_in_executor, does not block the event loop). Callers use: await s3_utils.upload_file(...)
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._upload_file_sync(file_data, file_key, content_type),
        )

    def _upload_image_sync(self, image_data: bytes, generation_id: Optional[str] = None,
                           content_type: str = "image/webp", resize_to: Optional[Tuple[int, int]] = None) -> str:
        """Sync process and upload an image, for run_in_executor (includes PIL decode)."""
        try:
            image_bytes = image_data
            with Image.open(io.BytesIO(image_bytes)) as img:
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                if resize_to:
                    target_width, target_height = resize_to
                    if img.width != target_width or img.height != target_height:
                        logger.info(f"调整图片尺寸: {img.width}x{img.height} -> {target_width}x{target_height}")
                        img = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
                output = io.BytesIO()
                img.save(output, 'webp', quality=85)
                processed_image_bytes = output.getvalue()
            filename = f"{generation_id}.webp" if generation_id else f"{uuid.uuid4()}.webp"
            file_key = f"images/{filename}"
            return self._upload_file_sync(processed_image_bytes, file_key, content_type)
        except Exception as e:
            logger.error(f"Error processing and uploading image: {e}")
            raise BusinessException(
                BusinessExceptionCode.BUSINESS_ERROR,
                f"图片处理或上传失败: {str(e)}"
            )

    async def upload_image(self, image_data: bytes, generation_id: Optional[str] = None,
                           content_type: str = "image/webp", resize_to: Optional[Tuple[int, int]] = None) -> str:
        """
        Upload an image to S3 (async, internally run_in_executor with PIL, does not block the event loop). Callers use: await s3_utils.upload_image(...)
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._upload_image_sync(image_data, generation_id, content_type, resize_to),
        )

    def _upload_audio_sync(self, audio_data: bytes, filename: str = None,
                           generation_id: Optional[str] = None, content_type: str = "audio/mpeg") -> str:
        """Sync upload audio, for run_in_executor."""
        if filename:
            _, ext = os.path.splitext(filename)
            ext = ext or '.mp3'
        else:
            ext = '.mp3'
        name = f"{generation_id}{ext}" if generation_id else f"{uuid.uuid4()}{ext}"
        file_key = f"audios/{name}"
        return self._upload_file_sync(audio_data, file_key, content_type)

    async def upload_audio(self, audio_data: bytes, filename: str = None,
                           generation_id: Optional[str] = None, content_type: str = "audio/mpeg") -> str:
        """
        Upload audio to S3 (async, internally run_in_executor). Callers use: await s3_utils.upload_audio(...)
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._upload_audio_sync(audio_data, filename, generation_id, content_type),
        )

    def _upload_video_sync(self, video_data: bytes, filename: str = None,
                           generation_id: Optional[str] = None, content_type: str = "video/mp4") -> str:
        """Sync upload video, for run_in_executor."""
        if filename:
            _, ext = os.path.splitext(filename)
            ext = ext or '.mp4'
        else:
            ext = '.mp4'
        name = f"{generation_id}{ext}" if generation_id else f"{uuid.uuid4()}{ext}"
        file_key = f"videos/{name}"
        return self._upload_file_sync(video_data, file_key, content_type)

    async def upload_video(self, video_data: bytes, filename: str = None,
                           generation_id: Optional[str] = None, content_type: str = "video/mp4") -> str:
        """
        Upload a video to S3 (async, internally run_in_executor). Callers use: await s3_utils.upload_video(...)
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._upload_video_sync(video_data, filename, generation_id, content_type),
        )

    async def _download_http_url(
        self, url: str, local_path: str, *, max_retries: int = 3,
    ) -> bool:
        """Fetch a public http(s) URL to disk. Used for vendor media (Suno, etc.).

        Local open-source has no S3; dest/prod keep S3 for first-party CDN URLs and
        only reach this path for foreign hosts.
        """
        os.makedirs(os.path.dirname(os.path.abspath(local_path)) or ".", exist_ok=True)
        last_error: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                timeout = aiohttp.ClientTimeout(total=300.0)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url) as response:
                        response.raise_for_status()
                        data = await response.read()
                if not data or len(data) < 100:
                    raise RuntimeError(
                        f"response too small: {0 if not data else len(data)} bytes"
                    )
                with open(local_path, "wb") as handle:
                    handle.write(data)
                logger.info(
                    "Downloaded foreign media %s -> %s (%s bytes)",
                    url[:120], local_path, len(data),
                )
                return True
            except Exception as exc:
                last_error = exc
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2
                    logger.warning(
                        "HTTP download attempt %s failed: %s; retry in %ss",
                        attempt + 1, exc, wait_time,
                    )
                    await asyncio.sleep(wait_time)
        logger.error("HTTP download failed: %s (%s)", url, last_error)
        return False

    def _download_file_sync(self, file_key_or_url: str, local_path: str) -> bool:
        """Copy from local disk or S3. Foreign http(s) URLs are handled by download_file."""
        try:
            parsed_input = urlparse(file_key_or_url)
            if self._is_local:
                # First-party /files URLs only. Vendor links go through _download_http_url.
                if parsed_input.scheme in ('http', 'https'):
                    file_key = self.cdn_url_to_s3_key(file_key_or_url)
                    if not file_key:
                        logger.error(f"无法从URL获取本地存储键: {file_key_or_url}")
                        return False
                else:
                    file_key = file_key_or_url
                src = os.path.join(self._local_dir, file_key)
                if not os.path.exists(src):
                    logger.error(f"本地存储文件不存在: {src}")
                    return False
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                shutil.copyfile(src, local_path)
                logger.info(f"Successfully copied file from local storage: {file_key} -> {local_path}")
                return True

            if parsed_input.scheme in ('http', 'https'):
                expected_domain = urlparse(settings.CDN_DOMAIN).netloc
                if parsed_input.netloc != expected_domain:
                    logger.error(f"Invalid CDN domain: {parsed_input.netloc}, expected: {expected_domain}")
                    return False
                file_key = self.cdn_url_to_s3_key(file_key_or_url)
                if not file_key:
                    logger.error(f"无法从URL获取S3键: {file_key_or_url}")
                    return False
            else:
                file_key = file_key_or_url

            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            self.s3_client.download_file(
                Bucket=self.bucket_name,
                Key=file_key,
                Filename=local_path
            )
            logger.info(f"Successfully downloaded file from S3: {file_key} -> {local_path}")
            return True
        except Exception as e:
            logger.error(f"Error downloading file from storage: {e}")
            return False

    async def download_file(self, file_key_or_url: str, local_path: str) -> bool:
        """Fetch media onto a local path for Gemini / ffmpeg / callers.

        - Our storage URL or key: copy from disk (local) or S3 (dest/prod).
        - Any other http(s) URL: HTTP GET. Open-source has no S3; dest/prod still
          use S3 for CDN URLs and only hit this for vendor hosts.
        """
        parsed = urlparse(file_key_or_url)
        if (
            parsed.scheme in {"http", "https"}
            and not is_our_cdn_url(file_key_or_url)
        ):
            return await self._download_http_url(file_key_or_url, local_path)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._download_file_sync(file_key_or_url, local_path),
        )

    def cdn_url_to_s3_key(self, cdn_url: str) -> Optional[str]:
        """
        Convert a CDN URL to an S3 file key.

        Args:
            cdn_url: CDN URL, for example https://cdn.example.test/images/uuid.webp

        Returns:
            Optional[str]: the S3 file key, e.g. images/uuid.webp; None on failure
        """
        try:
            if not cdn_url:
                logger.error("Empty CDN URL")
                return None

            # use urllib.parse to properly parse the URL
            parsed = urlparse(cdn_url)

            if self._is_local:
                # local backend: the URL looks like {PUBLIC_BASE_URL}/files/<key>; strip the files/ prefix to get the key
                expected_domain = urlparse(_local_public_base()).netloc
                if parsed.netloc != expected_domain:
                    logger.error(f"Invalid local storage domain: {parsed.netloc}, expected: {expected_domain}")
                    return None
                file_key = parsed.path.lstrip('/')
                if file_key.startswith('files/'):
                    file_key = file_key[len('files/'):]
                logger.info(f"Converted local URL to storage key: {cdn_url} -> {file_key}")
                return file_key

            # check whether the domain matches
            expected_domain = urlparse(settings.CDN_DOMAIN).netloc
            if parsed.netloc != expected_domain:
                logger.error(f"Invalid CDN domain: {parsed.netloc}, expected: {expected_domain}")
                return None

            # extract the path part as the S3 file key
            file_key = parsed.path.lstrip('/')

            logger.info(f"Converted CDN URL to S3 key: {cdn_url} -> {file_key}")
            return file_key

        except Exception as e:
            logger.error(f"Error converting CDN URL to S3 key: {e}")
            return None

    async def download_and_upload_video_to_s3(
        self,
        video_url: str,
        generation_id: Optional[str] = None,
        max_retries: int = 3,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
        target_fps: Optional[int] = None,
        target_duration: Optional[float] = None,
        strip_audio: bool = False,
        watermark: bool = False,
    ) -> str:
        """
        Download a video from a URL and upload it to S3 (with retry).
        The Media Service does resize + fps + strip audio + trim + watermark in one FFmpeg pass.
        """
        # The extracted self-hosted Video Runtime deliberately does not require
        # Cuti Media Service. Provider outputs already use the requested
        # resolution/duration, so local storage can preserve the immutable MP4
        # directly; later Media Plugin steps still perform concat/export checks.
        if self._is_local:
            timeout = aiohttp.ClientTimeout(total=1200.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(video_url) as response:
                    response.raise_for_status()
                    video_data = await response.read()
            if len(video_data) < 100:
                raise BusinessException(
                    BusinessExceptionCode.BUSINESS_ERROR,
                    "下载视频失败：Provider 返回空文件",
                )
            filename = os.path.basename(urlparse(video_url).path) or "provider-output.mp4"
            return await self.upload_video(
                video_data,
                filename=filename,
                generation_id=generation_id,
            )
        result = await msc.pipeline_ensure_on_s3(
            video_url=video_url,
            run_id=generation_id or str(uuid.uuid4()),
            generation_id=generation_id,
            target_width=target_width,
            target_height=target_height,
            target_fps=target_fps,
            target_duration=target_duration,
            strip_audio=strip_audio,
            watermark=watermark,
        )
        cdn_url = result["result_url"]
        logger.info(f"✅ Media service pipeline_ensure_on_s3 succeeded: {cdn_url}")
        return cdn_url

    async def ensure_video_on_our_s3(
        self,
        video_url: str,
        generation_id: Optional[str] = None,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
        *,
        target_fps: int = 24,
        target_duration: Optional[float] = None,
        strip_audio: bool = True,
        watermark: bool = False,
    ) -> str:
        """Persist a clean canonical video, returning first-party URLs unchanged.

        Video Runtime artifacts are build inputs: they can be trimmed, retried,
        tail-frame chained, or reused by a later PlanPatch.  A presentation
        watermark must therefore never be baked into this canonical copy or it
        becomes generation input and compounds on every reuse.  Callers that
        deliberately create a delivery derivative may still pass
        ``watermark=True``; normal provider ingestion defaults to a clean
        master.
        """
        if not video_url or not video_url.strip():
            return video_url or ""
        if is_our_cdn_url(video_url):
            return video_url
        tw = target_width if target_width is not None and target_width > 0 else 1920
        th = target_height if target_height is not None and target_height > 0 else 1080
        new_cdn_url = await self.download_and_upload_video_to_s3(
            video_url,
            generation_id=generation_id,
            target_width=tw,
            target_height=th,
            target_fps=target_fps,
            target_duration=target_duration,
            strip_audio=strip_audio,
            watermark=watermark,
        )
        return new_cdn_url

    async def download_and_upload_audio_to_s3(
        self,
        audio_url: str,
        generation_id: Optional[str] = None,
        max_retries: int = 3
    ) -> str:
        """Fetch audio then store it. Same download_file contract as Gemini.

        Local: HTTP-get vendor URL, write ``/files/audios/...``. dest/prod: HTTP-get
        then S3. Returns our storage URL, not the vendor URL.
        """
        base_filename = generation_id or str(uuid.uuid4())
        file_extension = ".mp3"
        if audio_url:
            try:
                path = urlparse(audio_url).path.lower()
                if path.endswith(('.mp3', '.wav', '.ogg', '.aac', '.flac', '.m4a')):
                    file_extension = path[path.rfind('.'):]
            except Exception:
                pass

        handle, tmp_path = tempfile.mkstemp(suffix=file_extension)
        os.close(handle)
        try:
            last_error: Optional[Exception] = None
            for attempt in range(max_retries):
                ok = await self.download_file(audio_url, tmp_path)
                if ok:
                    with open(tmp_path, "rb") as fh:
                        audio_data = fh.read()
                    if audio_data and len(audio_data) >= 100:
                        return await self.upload_audio(
                            audio_data, generation_id=base_filename,
                        )
                    last_error = RuntimeError(
                        f"downloaded audio too small: "
                        f"{0 if not audio_data else len(audio_data)} bytes"
                    )
                else:
                    last_error = RuntimeError(f"download_file failed: {audio_url}")
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2
                    logger.warning(
                        "ingest audio attempt %s failed: %s; retry in %ss",
                        attempt + 1, last_error, wait_time,
                    )
                    await asyncio.sleep(wait_time)
            logger.error("Audio ingest failed: %s (%s)", audio_url, last_error)
            raise BusinessException(
                BusinessExceptionCode.BUSINESS_ERROR,
                f"下载音频失败（重试{max_retries}次）: {last_error}",
            )
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

async def convert_media_url_to_s3(media_url: str, media_type, target_format) -> Optional[str]:
    """
    Generic media-URL conversion method - uses S3 for handling.

    Args:
        media_url: input media URL (full URL)
        media_type: media type (MediaType.IMAGE/AUDIO/VIDEO)
        target_format: target format (MediaFormat.URL/BASE64/LOCAL_PATH)

    Returns:
        the converted media data, None on failure
    """
    if not media_url:
        return None

    try:
        from .file_utils import MediaType, MediaFormat, convert_image_url_to_base64, get_media_dir
        import os
        import uuid

        # already a full URL or another format (does not support /api/photos, /api/audios, /api/videos)
        full_url = media_url

        # convert according to the target format
        if target_format == MediaFormat.URL:
            return full_url

        elif target_format == MediaFormat.LOCAL_PATH:
            # generate a local file name
            filename = f"{uuid.uuid4().hex[:8]}_{os.path.basename(full_url)}"

            # determine the local directory
            local_dir = get_media_dir(media_type)
            os.makedirs(local_dir, exist_ok=True)
            local_path = os.path.join(local_dir, filename)

            # use S3Utils to download the file asynchronously (supports all URL types, does not block the event loop)
            success = await s3_utils.download_file(full_url, local_path)

            if success and os.path.exists(local_path):
                logger.info(f"✅ 文件下载成功: {full_url} -> {local_path}")
                return local_path
            else:
                logger.error(f"❌ 文件下载失败: {full_url}")
                return None

        elif target_format == MediaFormat.BASE64:
            # currently only supports base64 conversion for images
            if media_type == MediaType.IMAGE:
                return await convert_image_url_to_base64(media_url)
            else:
                logger.warning(f"不支持 {media_type} 的 base64 转换")
                return None

        else:
            logger.error(f"不支持的目标格式: {target_format}")
            return None

    except Exception as e:
        logger.error(f"媒体URL转换失败: {media_url} -> {target_format}, 错误: {e}")
        return None

# create the global instance
s3_utils = S3Utils()
